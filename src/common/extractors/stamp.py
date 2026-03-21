"""印章提取器（Layer 4）

职责：从文档中提取印章内容
流程：LLM 直接分析图片，描述印章位置和内容（不需要 OCR）
"""
import io
import json
import logging
from typing import Any, Dict, List, Optional

from PIL import Image

from src.common.llm import get_default_llm_client
from src.common.vision import MultimodalLLM

logger = logging.getLogger(__name__)


class StampExtractor:
    """印章提取器 - LLM 直接分析，返回结构化结果"""

    def __init__(self):
        self._llm_client = None

    async def extract(
        self,
        file_data: bytes,
        min_regions: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        提取印章内容

        Args:
            file_data: PDF/图片 bytes
            min_regions: 最少印章区域数

        Returns:
            印章字典 {"stamps": [{"text": "xxx", "bbox": {...}, "confidence": 0.0}], ...}
            未提取到返回 None
        """
        try:
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)

            # 2. LLM 直接分析印章位置和内容，返回结构化 JSON
            prompt = """这是一张科技项目文档图片。
请识别所有印章，返回严格 JSON，不要输出任何解释、代码块或多余文本。

返回格式：
{
    "stamps": [
        {
            "index": 1,
            "text": "印章上可见的单位名称或文字",
            "location": "印章位置描述",
            "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4},
            "confidence": 0.95
        }
    ]
}

要求：
- 只填写印章上明确可见的文字，不要猜测
- 看不清时可以把 text 设为空字符串
- 没有印章时返回 {"stamps": []}"""

            multi_llm = MultimodalLLM(self._get_llm_client())
            result = await multi_llm.analyze_image(image_data, prompt)

            if not result or len(result.strip()) < 2:
                logger.warning("[StampExtractor] 未能检测到印章")
                return None

            stamp_data = self._parse_stamp_result(result)
            stamps = stamp_data.get("stamps", [])

            if not stamps:
                logger.warning("[StampExtractor] 未能检测到印章")
                return {"stamps": [], "raw": result}

            logger.info(f"[StampExtractor] 提取到 {len(stamps)} 个印章")
            return {
                "stamps": stamps,
                "raw": result,
            }
            
        except Exception as e:
            logger.error(f"[StampExtractor] 印章提取失败: {e}")
            return None

    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_default_llm_client()
        return self._llm_client

    def _parse_stamp_coords(self, text: str) -> List[Dict]:
        """解析 LLM 返回的坐标描述"""
        import re

        coords = []
        patterns = [
            r'(\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*)',
            r'x[=:]?\s*(\d+\.?\d*)[,\s]+y[=:]?\s*(\d+\.?\d*)',
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

    def _parse_stamp_result(self, text: str) -> Dict[str, Any]:
        """解析 LLM 返回的结构化印章结果"""
        json_text = self._extract_json(text)
        if not json_text:
            return {"stamps": []}

        try:
            data = json.loads(json_text)
        except Exception as e:
            logger.warning(f"[StampExtractor] JSON 解析失败: {e}")
            return {"stamps": []}

        stamps: List[Dict[str, Any]] = []
        for index, stamp in enumerate(data.get("stamps", []), start=1):
            if not isinstance(stamp, dict):
                continue

            bbox = stamp.get("bbox")
            if isinstance(bbox, list) and len(bbox) >= 4:
                bbox = {
                    "x1": bbox[0],
                    "y1": bbox[1],
                    "x2": bbox[2],
                    "y2": bbox[3],
                }
            elif not isinstance(bbox, dict):
                bbox = None

            text_value = stamp.get("text") or stamp.get("unit") or ""
            confidence = stamp.get("confidence", 0.0)

            stamps.append({
                "index": stamp.get("index", index),
                "text": text_value,
                "unit": text_value,
                "location": stamp.get("location", ""),
                "bbox": bbox,
                "confidence": self._normalize_confidence(confidence),
            })

        return {"stamps": stamps}

    def _extract_json(self, text: str) -> Optional[str]:
        """从模型输出中提取 JSON 片段"""
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```", 2)
            if len(stripped) >= 2:
                stripped = stripped[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        return stripped[start:end + 1]

    def _normalize_confidence(self, confidence: Any) -> float:
        """将置信度归一化到 0~1"""
        try:
            value = float(confidence)
        except Exception:
            return 0.0

        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value

    def _pdf_to_image(self, file_data: bytes) -> bytes:
        """PDF 转图片（取第一页，fitz 放大3倍）"""
        import fitz
        
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
