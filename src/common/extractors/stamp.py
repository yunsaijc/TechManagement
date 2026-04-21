"""印章提取器（Layer 4）

职责：从文档中提取印章内容。

当前提供两类能力：
1. 通用整页印章提取
2. 面向固定表单的锚点约束局部印章提取
"""
import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps

from src.common.llm import get_review_llm_client
from src.common.vision.multimodal import MultimodalLLM

logger = logging.getLogger(__name__)


class StampExtractor:
    """印章提取器。"""

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
- 只读取印章轮廓内部明确可见的文字
- 严禁把印章外部相邻的正文、表格字段、日期、签字、表头文字当作印章文字
- 不允许根据印章附近文字推测或补全印章内容
- 每个印章单独识别，不要合并多个印章
- bbox 尽量只覆盖印章本体，不要包含周围正文
- 看不清时可以把 text 设为空字符串，不要猜测
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

    async def extract_award_contributor_stamps(
        self,
        file_data: bytes,
    ) -> Dict[str, Any]:
        """专项：主要完成人情况表的锚点约束印章提取。"""
        image_data = self._pdf_to_image(file_data)
        page_image = self._load_image(image_data)
        if page_image is None:
            return self._empty_award_result()

        anchors = await self._locate_award_contributor_anchor_regions(image_data)
        regions: List[Dict[str, Any]] = []
        role_results: Dict[str, Dict[str, Any]] = {}
        for role_key, role_label in (
            ("work_unit", "工作单位（公章）"),
            ("completion_unit", "完成单位（公章）"),
        ):
            bbox = anchors.get(role_key)
            if bbox is None:
                bbox = self._default_award_stamp_bbox(role_key)
            crop_bytes, crop_bbox = self._crop_with_margin(page_image, bbox, margin_ratio=0.12)
            crop_result = await self._extract_stamps_from_region(
                image_data=crop_bytes,
                region_name=role_label,
                hint=f"这是一张从“主要完成人情况表”中裁剪出的局部区域，请只识别 {role_label} 附近印章内部的文字。",
            )
            role_results[role_key] = crop_result
            regions.append(
                {
                    "role": role_key,
                    "label": role_label,
                    "bbox": crop_bbox,
                    "stamps": crop_result.get("stamps", []),
                    "raw": crop_result.get("raw", ""),
                }
            )

        page_stamps: Dict[str, Any] = {"stamps": [], "raw": ""}
        if not role_results.get("work_unit", {}).get("stamps") and not role_results.get("completion_unit", {}).get("stamps"):
            page_stamps = await self._extract_stamps_from_region(
                image_data=image_data,
                region_name="整页落款区域",
                hint="优先关注页面下半部分尤其是右下角落款、公章区域，识别所有实际盖章的单位名称。",
            )

        work_units = self._dedup_units(role_results.get("work_unit", {}).get("stamps", []))
        completion_units = self._dedup_units(role_results.get("completion_unit", {}).get("stamps", []))
        all_units = self._dedup_units(
            [
                *page_stamps.get("stamps", []),
                *role_results.get("work_unit", {}).get("stamps", []),
                *role_results.get("completion_unit", {}).get("stamps", []),
            ]
        )

        all_stamps = self._merge_award_stamps(
            work_stamps=role_results.get("work_unit", {}).get("stamps", []),
            completion_stamps=role_results.get("completion_unit", {}).get("stamps", []),
            page_stamps=page_stamps.get("stamps", []),
        )

        return {
            "stamps": all_stamps,
            "work_unit_stamp_units": work_units,
            "completion_unit_stamp_units": completion_units,
            "all_stamp_units": all_units,
            "anchor_regions": anchors,
            "regions": regions,
            "raw": {
                "anchors": anchors,
                "page": page_stamps.get("raw", ""),
                "work_unit": role_results.get("work_unit", {}).get("raw", ""),
                "completion_unit": role_results.get("completion_unit", {}).get("raw", ""),
            },
        }

    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_review_llm_client()
        return self._llm_client

    def _empty_award_result(self) -> Dict[str, Any]:
        return {
            "stamps": [],
            "work_unit_stamp_units": [],
            "completion_unit_stamp_units": [],
            "all_stamp_units": [],
            "anchor_regions": {},
            "regions": [],
            "raw": {},
        }

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

    async def _locate_award_contributor_anchor_regions(self, image_data: bytes) -> Dict[str, Dict[str, float]]:
        prompt = """这是一张“主要完成人情况表”。
请定位页面底部两个公章落款区域，并严格返回 JSON：

{
  "work_unit": {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0},
  "completion_unit": {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0}
}

要求：
- 坐标使用相对整页的 0~1 归一化值
- bbox 覆盖“公章字样和其上方盖章区域”
- 如果无法精确定位，也返回大致区域
- 不要输出解释，只返回 JSON"""
        multi_llm = MultimodalLLM(self._get_llm_client())
        raw = await multi_llm.analyze_image(image_data, prompt)
        payload = self._extract_json(raw)
        if not payload:
            return {}
        try:
            data = json.loads(payload)
        except Exception:
            return {}

        out: Dict[str, Dict[str, float]] = {}
        for key in ("work_unit", "completion_unit"):
            bbox = self._normalize_bbox(data.get(key))
            if bbox:
                out[key] = bbox
        return out

    async def _extract_stamps_from_region(
        self,
        image_data: bytes,
        region_name: str,
        hint: str,
    ) -> Dict[str, Any]:
        prompt = f"""{hint}
请识别图中真实可见的印章，并严格返回 JSON：

{{
  "stamps": [
    {{
      "text": "印章内部可辨认的单位名称",
      "location": "{region_name}",
      "bbox": {{"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}},
      "confidence": 0.95
    }}
  ]
}}

要求：
- 只读取印章轮廓内部文字
- 严禁把印章外部的红字、正文、签字、日期当作印章文字
- 看不清就返回空字符串，不要猜
- 没有印章时返回 {{"stamps": []}}
- 只返回 JSON"""
        multi_llm = MultimodalLLM(self._get_llm_client())
        raw = await multi_llm.analyze_image(image_data, prompt)
        parsed = self._parse_stamp_result(raw)
        parsed["raw"] = raw
        return parsed

    def _normalize_bbox(self, bbox: Any) -> Optional[Dict[str, float]]:
        if not isinstance(bbox, dict):
            return None
        try:
            x1 = max(0.0, min(1.0, float(bbox.get("x1"))))
            y1 = max(0.0, min(1.0, float(bbox.get("y1"))))
            x2 = max(0.0, min(1.0, float(bbox.get("x2"))))
            y2 = max(0.0, min(1.0, float(bbox.get("y2"))))
        except Exception:
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

    def _load_image(self, image_data: bytes) -> Optional[Image.Image]:
        try:
            image = Image.open(io.BytesIO(image_data))
            return ImageOps.exif_transpose(image).convert("RGB")
        except Exception:
            return None

    def _crop_with_margin(
        self,
        image: Image.Image,
        bbox: Dict[str, float],
        margin_ratio: float = 0.1,
    ) -> Tuple[bytes, Dict[str, float]]:
        width, height = image.size
        x1 = int(max(0, (bbox["x1"] - margin_ratio) * width))
        y1 = int(max(0, (bbox["y1"] - margin_ratio) * height))
        x2 = int(min(width, (bbox["x2"] + margin_ratio) * width))
        y2 = int(min(height, (bbox["y2"] + margin_ratio) * height))
        if x2 <= x1 or y2 <= y1:
            x1, y1, x2, y2 = 0, 0, width, height
        cropped = image.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue(), {
            "x1": x1 / width,
            "y1": y1 / height,
            "x2": x2 / width,
            "y2": y2 / height,
        }

    def _default_award_stamp_bbox(self, role_key: str) -> Dict[str, float]:
        if role_key == "work_unit":
            return {"x1": 0.48, "y1": 0.68, "x2": 0.78, "y2": 0.96}
        return {"x1": 0.22, "y1": 0.68, "x2": 0.58, "y2": 0.96}

    def _dedup_units(self, stamps: List[Dict[str, Any]]) -> List[str]:
        seen: set[str] = set()
        units: List[str] = []
        for stamp in stamps:
            unit = str(stamp.get("unit") or stamp.get("text") or "").strip()
            key = unit.replace(" ", "")
            if not unit or not key or key in seen:
                continue
            seen.add(key)
            units.append(unit)
        return units

    def _merge_award_stamps(
        self,
        work_stamps: List[Dict[str, Any]],
        completion_stamps: List[Dict[str, Any]],
        page_stamps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str]] = set()
        for location, stamps in (
            ("工作单位（公章）", work_stamps),
            ("完成单位（公章）", completion_stamps),
            ("页面印章", page_stamps),
        ):
            for stamp in stamps:
                unit = str(stamp.get("unit") or stamp.get("text") or "").strip()
                key = (location, unit.replace(" ", ""))
                if not unit or key in seen:
                    continue
                seen.add(key)
                merged.append(
                    {
                        "unit": unit,
                        "text": unit,
                        "location": stamp.get("location") or location,
                        "bbox": stamp.get("bbox"),
                        "confidence": stamp.get("confidence", 0.0),
                    }
                )
        return merged


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
