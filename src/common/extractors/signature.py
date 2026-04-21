"""签字提取器（Layer 4）。"""

import json
import logging
import re
from typing import Dict, List, Optional, Any

from src.common.llm import get_default_llm_client
from src.common.vision.multimodal import MultimodalLLM

logger = logging.getLogger(__name__)

_SIGNATURE_NAME_PATTERN = re.compile(r"^[A-Za-z\u4e00-\u9fff·• ]{2,30}$")
_SIGNATURE_DESCRIPTION_MARKERS = {
    "页面", "位置", "如下", "位于", "区域", "左下角", "右下角", "左侧", "右侧",
    "上方", "下方", "附近", "图中", "显示", "可见", "文字", "字样", "覆盖",
}
_SEAL_ONLY_MARKERS = {
    "公章", "印章", "盖章", "圆形章", "红章", "日期", "单位（盖章）", "单位盖章",
}
_HANDWRITING_MARKERS = {
    "手写签名", "手写签字", "本人签名", "本人签字", "手写", "签名笔迹", "签字笔迹",
}


def _looks_like_signature_name(text: str) -> bool:
    value = str(text or "").strip()
    if not value or len(value) > 30:
        return False
    if any(marker in value for marker in _SIGNATURE_DESCRIPTION_MARKERS | _SEAL_ONLY_MARKERS):
        return False
    if any(punct in value for punct in ("，", "。", "；", "：", ":", "\n")):
        return False
    return bool(_SIGNATURE_NAME_PATTERN.fullmatch(value))


def _is_meaningful_signature_text(text: Any) -> bool:
    value = str(text or "").replace("\n", " ").replace("\xa0", " ").strip()
    if not value:
        return False
    if _looks_like_signature_name(value):
        return True

    has_handwriting = any(marker in value for marker in _HANDWRITING_MARKERS)
    has_seal_only = any(marker in value for marker in _SEAL_ONLY_MARKERS)
    has_description = any(marker in value for marker in _SIGNATURE_DESCRIPTION_MARKERS)

    if has_handwriting and "未见手写" not in value and "无手写" not in value:
        return True
    if has_seal_only and not has_handwriting:
        return False
    if has_description:
        return False
    return False


def normalize_signature_entries(raw_signatures: Any) -> List[Dict[str, Any]]:
    """清洗签字结果，仅保留可用于判定签字存在的条目。"""
    items = raw_signatures if isinstance(raw_signatures, list) else [raw_signatures]
    normalized: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("name") or item.get("description") or "").strip()
            bbox = item.get("bbox")
            confidence = item.get("confidence", 0.0)
        else:
            text = str(item or "").strip()
            bbox = None
            confidence = 0.0

        if not _is_meaningful_signature_text(text):
            continue
        normalized.append({
            "text": text,
            "bbox": bbox,
            "confidence": confidence,
        })
    return normalized


class SignatureExtractor:
    """签字提取器。"""

    def __init__(self):
        self._llm_client = None

    async def extract(
        self,
        file_data: bytes,
        min_regions: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        提取签字内容

        Args:
            file_data: PDF/图片 bytes
            min_regions: 最少签字区域数

        Returns:
            签字字典 {"signatures": [{"text": "xxx", "bbox": {...}]}, ...]，未提取到返回 None
        """
        try:
            image_data = self._pdf_to_image(file_data)

            multi_llm = MultimodalLLM(self._get_llm_client())
            prompt = """请判断页面中是否存在“手写签字/手写签名”。

注意：
1. 公章、印章、盖章、打印文字、日期都不算签字。
2. 只有确认存在手写签字/手写签名时，has_signature 才能为 true。
3. 如果能辨认出姓名，text 写姓名；如果只能确认有手写签字但姓名不清晰，text 置空，description 写“检测到手写签字，姓名不清晰”。
4. 只返回 JSON，不要解释，不要代码块。

返回格式：
{
  "has_signature": true,
  "signatures": [
    {
      "text": "",
      "description": "",
      "bbox": null,
      "confidence": 0.0
    }
  ]
}"""
            raw = await multi_llm.analyze_image(image_data, prompt)

            signatures = self._parse_signatures(raw)
            if not signatures:
                logger.warning("[SignatureExtractor] 未能检测到签字")
                return None
            logger.info("[SignatureExtractor] 提取到 %s 个有效签字结果", len(signatures))
            return {"signatures": signatures}

        except Exception as e:
            logger.error(f"[SignatureExtractor] 签字提取失败: {e}")
            return None

    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_default_llm_client()
        return self._llm_client

    def _parse_signature_coords(self, text: str) -> List[Dict]:
        """解析 LLM 返回的坐标描述"""
        coords = []
        patterns = [
            r'(\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*)',  # x1,y1,x2,y2
            r'x[=:]?\s*(\d+\.?\d*)[,\s]+y[=:]?\s*(\d+\.?\d*)',   # x, y
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                if len(m) == 4:
                    coords.append({
                        "x1": float(m[0]), "y1": float(m[1]),
                        "x2": float(m[2]), "y2": float(m[3])
                    })
                elif len(m) == 2:
                    coords.append({
                        "x": float(m[0]), "y": float(m[1])
                    })
        return coords

    def _parse_signatures(self, raw_text: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的签字结果。"""
        stripped = str(raw_text or "").strip()
        if not stripped:
            return []

        if stripped.startswith("```"):
            parts = stripped.split("```", 2)
            if len(parts) >= 2:
                stripped = parts[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]

        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        payload: Dict[str, Any] = {}
        if match:
            try:
                payload = json.loads(match.group(0))
            except Exception:
                payload = {}

        if isinstance(payload, dict):
            if not payload.get("has_signature"):
                return []
            return normalize_signature_entries(payload.get("signatures", []))

        coords = self._parse_signature_coords(stripped)
        return normalize_signature_entries([{"text": stripped, "bbox": coords[0] if coords else None}])

    def _pdf_to_image(self, file_data: bytes) -> bytes:
        """PDF 转图片（取第一页，fitz 放大3倍）"""
        import fitz  # PyMuPDF
        
        if file_data[:4] != b'%PDF':
            return file_data
        
        try:
            doc = fitz.open(stream=file_data, filetype="pdf")
            if doc.page_count == 0:
                return file_data
            
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
            img_data = pix.tobytes("png")
            doc.close()
            return img_data
        except Exception:
            return file_data
