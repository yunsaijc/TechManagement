"""印章提取器（Layer 4）

职责：从文档中提取印章内容。

当前提供两类能力：
1. 通用整页印章提取
2. 面向固定表单的锚点约束局部印章提取
"""
import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from src.common.llm import get_llm_client, llm_config
from src.common.review_runtime import ReviewRuntime
from src.common.vision.multimodal import MultimodalLLM

logger = logging.getLogger(__name__)


class StampExtractor:
    """印章提取器。"""

    def __init__(self):
        self._llm_client = None
        self._last_stamp_page_ocr_result: Dict[str, Any] = {}
        self._last_stamp_page_words: List[Dict[str, Any]] = []

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
        anchors = await self.locate_award_contributor_stamp_anchors(file_data)
        return await self.extract_award_contributor_stamps_from_anchors(file_data, anchors, image_data=image_data)

    async def locate_award_contributor_stamp_anchors(
        self,
        file_data: bytes,
    ) -> Dict[str, Dict[str, float]]:
        """只定位主要完成人表公章锚点。"""
        image_data = self._pdf_to_image(file_data)
        return await self._locate_award_contributor_anchor_regions(image_data)

    async def extract_award_contributor_stamps_from_anchors(
        self,
        file_data: bytes,
        anchors: Optional[Dict[str, Dict[str, float]]] = None,
        image_data: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """基于已知锚点提取主要完成人表公章。"""
        if image_data is None:
            image_data = self._pdf_to_image(file_data)
        page_image = self._load_image(image_data)
        if page_image is None:
            return self._empty_award_result()

        if not isinstance(anchors, dict):
            anchors = {}
        role_specs = (
            ("work_unit", "工作单位（公章）"),
            ("completion_unit", "完成单位（公章）"),
        )
        role_outputs = await asyncio.gather(
            *[
                self._extract_award_contributor_stamp_role(
                    page_image=page_image,
                    anchors=anchors,
                    role_key=role_key,
                    role_label=role_label,
                )
                for role_key, role_label in role_specs
            ]
        )
        role_results: Dict[str, Dict[str, Any]] = {item["role"]: item["result"] for item in role_outputs}
        regions: List[Dict[str, Any]] = [item["region"] for item in role_outputs]

        page_stamps: Dict[str, Any] = {"stamps": [], "raw": ""}

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

    async def _extract_award_contributor_stamp_role(
        self,
        page_image: Image.Image,
        anchors: Dict[str, Dict[str, float]],
        role_key: str,
        role_label: str,
    ) -> Dict[str, Any]:
        """并行提取单个公章角色区域。"""
        bbox = anchors.get(role_key)
        if bbox is None:
            bbox = self._default_award_stamp_bbox(role_key)
        crop_bytes, crop_bbox = self._crop_with_margin(page_image, bbox, margin_ratio=0.015)
        crop_image = self._load_image(crop_bytes)
        ocr_image = self._prepare_stamp_crop_for_ocr(crop_image) if crop_image is not None else None
        ocr_bytes = self._image_to_png_bytes(ocr_image) if ocr_image is not None else crop_bytes
        ocr_bundle = self._build_stamp_ocr_variants(crop_image, role_key=role_key)
        ocr_variants = ocr_bundle.get("variants", [])
        self._save_award_stamp_debug_crop(
            role_key=role_key,
            role_label=role_label,
            page_image=page_image,
            anchor_bbox=bbox,
            crop_bbox=crop_bbox,
            crop_bytes=crop_bytes,
            ocr_bytes=ocr_bytes,
            ocr_variants=ocr_variants,
        )
        crop_result = await self._qwen_extract_stamps_from_variants(
            variants=ocr_variants or [("enhanced", ocr_bytes)],
            region_name=role_label,
            role_key=role_key,
            polar_raw_source=ocr_bundle.get("polar_raw_source"),
            polar_enhanced_source=ocr_bundle.get("polar_enhanced_source"),
            polar_source_variant=str(ocr_bundle.get("polar_source_variant") or ""),
        )
        return {
            "role": role_key,
            "result": crop_result,
            "region": {
                "role": role_key,
                "label": role_label,
                "bbox": crop_bbox,
                "stamps": crop_result.get("stamps", []),
                "raw": crop_result.get("raw", ""),
            },
        }

    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            extra_body = None
            if llm_config.provider == "qwen" and llm_config.model.startswith("qwen3.5"):
                # 印章/锚点属于纯识别任务，不需要 thinking，避免兼容接口在非流式下长耗时。
                extra_body = {"enable_thinking": False}
            self._llm_client = get_llm_client(
                provider=llm_config.provider or "openai",
                model=llm_config.model or None,
                api_key=llm_config.api_key or None,
                base_url=llm_config.base_url or None,
                temperature=0.0,
                max_tokens=llm_config.max_tokens,
                timeout=llm_config.timeout,
                max_retries=0,
                extra_body=extra_body,
            )
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
        image = self._load_image(image_data)
        if image is None:
            return {}
        img_w, img_h = image.size
        ocr_result = await self._run_qwen_ocr(
            image_data=image_data,
            prompt="请对这张主要完成人情况表执行 OCR，返回所有文字及其位置。",
            debug_name="stamp_page_ocr",
        )
        words = list(ocr_result.get("words_info") or [])
        self._last_stamp_page_ocr_result = ocr_result
        self._last_stamp_page_words = words

        out: Dict[str, Dict[str, float]] = {}
        selected: Dict[str, Any] = {}
        role_targets = {
            "work_unit": "工作单位公章",
            "completion_unit": "完成单位公章",
        }
        for role_key, target in role_targets.items():
            label_words = self._match_anchor_label_words(words, target, img_w=img_w, img_h=img_h)
            label_bbox = self._merge_word_bboxes(label_words)
            if not label_bbox:
                logger.warning(f"[StampExtractor] 未定位到{target}锚点")
                continue
            stamp_bbox = self._stamp_region_from_label_bbox(label_bbox, img_w=img_w, img_h=img_h)
            out[role_key] = stamp_bbox
            selected[role_key] = {
                "target": target,
                "label_words": label_words,
                "label_bbox": label_bbox,
                "stamp_bbox": stamp_bbox,
            }
        red_regions = self._detect_red_stamp_regions(image, selected)
        if len(red_regions) >= 2 and {"completion_unit", "work_unit"}.issubset(selected.keys()):
            sorted_regions = sorted(red_regions, key=lambda item: (item["x1"] + item["x2"]) / 2.0)
            out["completion_unit"] = sorted_regions[0]
            out["work_unit"] = sorted_regions[-1]
            selected["completion_unit"]["red_stamp_bbox"] = sorted_regions[0]
            selected["work_unit"]["red_stamp_bbox"] = sorted_regions[-1]
        self._save_award_stamp_anchor_debug(
            image_data,
            out,
            {
                "source": "qwen-vl-ocr-latest/advanced_recognition",
                "selected": selected,
                "red_regions": red_regions,
                "words_count": len(words),
            },
        )
        return out

    async def _qwen_extract_stamps_from_variants(
        self,
        variants: List[Tuple[str, bytes]],
        region_name: str,
        role_key: str,
        polar_raw_source: Optional[Image.Image] = None,
        polar_enhanced_source: Optional[Image.Image] = None,
        polar_source_variant: str = "",
    ) -> Dict[str, Any]:
        calls = [
            self._run_qwen_ocr(
                image_data=image_data,
                prompt="请对这张公章局部图片执行 OCR，只返回图片中实际可见文字，不要纠错，不要补全。",
                debug_name=f"stamp_{role_key}_{variant_name}_ocr",
                task="advanced_recognition",
                enable_rotate=False,
            )
            for variant_name, image_data in variants
            if image_data
        ]
        results = await asyncio.gather(*calls, return_exceptions=True)
        variant_payloads: List[Dict[str, Any]] = []
        for (variant_name, _), result in zip(variants, results):
            if isinstance(result, Exception):
                variant_payloads.append({"variant": variant_name, "error": str(result), "texts": []})
                continue
            texts = self._extract_stamp_unit_texts(result, variant_name=variant_name)
            variant_payloads.append(
                {
                    "variant": variant_name,
                    "texts": texts,
                    "processed_text": result.get("processed_text", ""),
                    "words_info": result.get("words_info", []),
                }
            )

        polar_payload = await self._build_polar_variant_payload(
            role_key=role_key,
            polar_raw_source=polar_raw_source,
            polar_enhanced_source=polar_enhanced_source,
            polar_source_variant=polar_source_variant,
        )
        if polar_payload is not None:
            variant_payloads.append(polar_payload)

        texts = self._choose_consensus_stamp_texts(variant_payloads)
        stamps = [
            {
                "index": index,
                "text": text,
                "unit": text,
                "location": region_name,
                "bbox": None,
                "confidence": 0.0,
            }
            for index, text in enumerate(texts, start=1)
        ]
        return {
            "stamps": stamps,
            "raw": json.dumps(
                {
                    "source": "qwen-vl-ocr-latest/advanced_recognition",
                    "texts": texts,
                    "variants": variant_payloads,
                },
                ensure_ascii=False,
            ),
        }

    async def _qwen_extract_stamps_from_crop(
        self,
        image_data: bytes,
        region_name: str,
        role_key: str,
    ) -> Dict[str, Any]:
        return await self._qwen_extract_stamps_from_variants(
            variants=[("enhanced", image_data)],
            region_name=region_name,
            role_key=role_key,
        )

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

    async def _run_qwen_ocr(
        self,
        image_data: bytes,
        prompt: str,
        debug_name: str,
        task: str = "advanced_recognition",
        enable_rotate: bool = True,
    ) -> Dict[str, Any]:
        """调用 Qwen-OCR 原生任务。"""
        api_key = str(llm_config.api_key or "").strip()
        if not api_key:
            raise RuntimeError("LLM_API_KEY 未配置，无法调用 Qwen-OCR")

        image_b64 = base64.b64encode(image_data).decode("utf-8")
        payload = {
            "model": "qwen-vl-ocr-latest",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/png;base64,{image_b64}",
                                "min_pixels": 28 * 28 * 256,
                                "max_pixels": 28 * 28 * 1600,
                            },
                            {"text": prompt},
                        ],
                    }
                ]
            },
            "parameters": {
                "ocr_options": {
                    "task": task,
                    "enable_table": False,
                    "enable_rotate": enable_rotate,
                }
            },
        }
        response = await asyncio.to_thread(
            requests.post,
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        self._save_qwen_ocr_debug_response(debug_name, data)
        return self._extract_qwen_ocr_result(data)

    def _extract_qwen_ocr_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            content = payload["output"]["choices"][0]["message"]["content"][0]["ocr_result"]
        except Exception as exc:
            raise RuntimeError(f"Qwen-OCR 返回结构异常: {exc}") from exc
        words_info = list(content.get("words_info") or [])
        processed_text = str(content.get("processed_text") or "")
        return {"words_info": words_info, "processed_text": processed_text}

    def _save_qwen_ocr_debug_response(self, debug_name: str, payload: Dict[str, Any]) -> None:
        if str(debug_name or "").startswith("stamp"):
            return
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)
        safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(debug_name or "qwen_ocr"))
        with open(f"{debug_dir}/{safe_name}.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _normalize_bbox(
        self,
        bbox: Any,
        image_size: Optional[Tuple[int, int]] = None,
    ) -> Optional[Dict[str, float]]:
        if not isinstance(bbox, dict):
            return None
        try:
            x1 = float(bbox.get("x1"))
            y1 = float(bbox.get("y1"))
            x2 = float(bbox.get("x2"))
            y2 = float(bbox.get("y2"))
        except Exception:
            return None
        if image_size and max(x1, y1, x2, y2) > 1.0:
            width, height = image_size
            if width <= 0 or height <= 0:
                return None
            x1 /= width
            x2 /= width
            y1 /= height
            y2 /= height
        x1 = max(0.0, min(1.0, x1))
        y1 = max(0.0, min(1.0, y1))
        x2 = max(0.0, min(1.0, x2))
        y2 = max(0.0, min(1.0, y2))
        if x2 <= x1 or y2 <= y1:
            return None
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

    def _normalize_text(self, text: Any) -> str:
        return re.sub(r"[\s（）()【】\[\]{}:：,，.;；。、·“”\"'`]+", "", str(text or ""))

    def _word_bbox(self, word: Dict[str, Any]) -> Dict[str, float]:
        location = word.get("location") or []
        if isinstance(location, list) and len(location) >= 8:
            xs = [float(location[i]) for i in range(0, len(location), 2)]
            ys = [float(location[i]) for i in range(1, len(location), 2)]
            return {"x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)}
        rotate_rect = word.get("rotate_rect") or []
        if isinstance(rotate_rect, list) and len(rotate_rect) >= 4:
            cx, cy, h, w = [float(item) for item in rotate_rect[:4]]
            return {
                "x1": cx - w / 2.0,
                "y1": cy - h / 2.0,
                "x2": cx + w / 2.0,
                "y2": cy + h / 2.0,
            }
        return {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0}

    def _merge_word_bboxes(self, words: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
        if not words:
            return None
        boxes = [self._word_bbox(word) for word in words]
        return {
            "x1": min(box["x1"] for box in boxes),
            "y1": min(box["y1"] for box in boxes),
            "x2": max(box["x2"] for box in boxes),
            "y2": max(box["y2"] for box in boxes),
        }

    def _match_anchor_label_words(
        self,
        words: List[Dict[str, Any]],
        target_text: str,
        img_w: int,
        img_h: int,
    ) -> List[Dict[str, Any]]:
        target = self._normalize_text(target_text)
        primary = target.replace("公章", "")
        seal = "公章"
        exact: List[Tuple[float, Dict[str, Any]]] = []
        partial: List[Tuple[float, List[Dict[str, Any]]]] = []

        for word in words:
            box = self._word_bbox(word)
            if box["y1"] < img_h * 0.72:
                continue
            text_norm = self._normalize_text(word.get("text"))
            if not text_norm:
                continue
            if target in text_norm:
                matched = self._slice_word_by_normalized_substring(word, target)
                score = box["y1"] - box["x1"] * 0.001
                exact.append((score, matched))
                continue
            if primary in text_norm:
                merged = [self._slice_word_by_normalized_substring(word, primary)]
                seal_word = self._find_nearby_anchor_word(words, base_word=word, target=seal, img_h=img_h)
                if seal_word is not None:
                    merged.append(self._slice_word_by_normalized_substring(seal_word, seal))
                score = box["y1"] - box["x1"] * 0.001
                partial.append((score, merged))

        if exact:
            exact.sort(key=lambda item: item[0], reverse=True)
            return [exact[0][1]]
        if partial:
            partial.sort(key=lambda item: item[0], reverse=True)
            return partial[0][1]
        return []

    def _slice_word_by_normalized_substring(self, word: Dict[str, Any], target: str) -> Dict[str, Any]:
        text_norm = self._normalize_text(word.get("text"))
        box = self._word_bbox(word)
        if not text_norm or target not in text_norm:
            return {
                "text": word.get("text", ""),
                "location": word.get("location"),
                "rotate_rect": word.get("rotate_rect"),
            }
        start = text_norm.find(target)
        end = start + len(target)
        width = max(1.0, box["x2"] - box["x1"])
        x1 = box["x1"] + width * (start / max(len(text_norm), 1))
        x2 = box["x1"] + width * (end / max(len(text_norm), 1))
        return {
            "text": target,
            "location": [x1, box["y1"], x2, box["y1"], x2, box["y2"], x1, box["y2"]],
        }

    def _find_nearby_anchor_word(
        self,
        words: List[Dict[str, Any]],
        base_word: Dict[str, Any],
        target: str,
        img_h: int,
    ) -> Optional[Dict[str, Any]]:
        base_box = self._word_bbox(base_word)
        base_center_y = (base_box["y1"] + base_box["y2"]) / 2.0
        candidates: List[Tuple[float, Dict[str, Any]]] = []
        for word in words:
            if word is base_word:
                continue
            text_norm = self._normalize_text(word.get("text"))
            if target not in text_norm:
                continue
            box = self._word_bbox(word)
            if box["y1"] < img_h * 0.72:
                continue
            center_y = (box["y1"] + box["y2"]) / 2.0
            if abs(center_y - base_center_y) > 36:
                continue
            gap = abs(box["x1"] - base_box["x2"])
            candidates.append((gap, word))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _stamp_region_from_label_bbox(
        self,
        label_bbox: Dict[str, float],
        img_w: int,
        img_h: int,
    ) -> Dict[str, float]:
        center_x = (label_bbox["x1"] + label_bbox["x2"]) / 2.0
        label_width = max(1.0, label_bbox["x2"] - label_bbox["x1"])
        radius_x = max(label_width * 1.25, img_w * 0.085)
        top = max(0.0, label_bbox["y1"] - img_h * 0.11)
        bottom = min(float(img_h), label_bbox["y2"] + img_h * 0.08)
        left = max(0.0, center_x - radius_x)
        right = min(float(img_w), center_x + radius_x)
        return {
            "x1": left / max(img_w, 1),
            "y1": top / max(img_h, 1),
            "x2": right / max(img_w, 1),
            "y2": bottom / max(img_h, 1),
        }

    def _detect_red_stamp_regions(
        self,
        image: Image.Image,
        selected: Dict[str, Any],
    ) -> List[Dict[str, float]]:
        label_boxes = [
            item.get("label_bbox")
            for item in selected.values()
            if isinstance(item, dict) and isinstance(item.get("label_bbox"), dict)
        ]
        if not label_boxes:
            return []
        img = image.convert("RGB")
        width, height = img.size
        min_label_y = min(float(box["y1"]) for box in label_boxes)
        max_label_y = max(float(box["y2"]) for box in label_boxes)
        band_top = int(max(0, min_label_y - height * 0.14))
        band_bottom = int(min(height, max_label_y + height * 0.20))

        pixels = img.load()
        column_counts = [0] * width
        red_points_by_x: Dict[int, List[int]] = {}
        for y in range(band_top, band_bottom):
            for x in range(width):
                r, g, b = pixels[x, y]
                if r >= 110 and r >= g + 28 and r >= b + 28:
                    column_counts[x] += 1
                    red_points_by_x.setdefault(x, []).append(y)

        active = [index for index, count in enumerate(column_counts) if count >= 3]
        if not active:
            return []
        runs: List[Tuple[int, int]] = []
        start = prev = active[0]
        max_gap = 16
        for x in active[1:]:
            if x - prev > max_gap:
                runs.append((start, prev))
                start = x
            prev = x
        runs.append((start, prev))

        regions: List[Dict[str, float]] = []
        for x1, x2 in runs:
            if x2 - x1 < width * 0.06:
                continue
            ys: List[int] = []
            red_count = 0
            for x in range(x1, x2 + 1):
                col_ys = red_points_by_x.get(x) or []
                red_count += len(col_ys)
                ys.extend(col_ys)
            if red_count < 120:
                continue
            y1 = min(ys)
            y2 = max(ys)
            if y2 - y1 < height * 0.05:
                continue
            pad_x = int(width * 0.02)
            pad_y = int(height * 0.018)
            regions.append(
                {
                    "x1": max(0, x1 - pad_x) / width,
                    "y1": max(0, y1 - pad_y) / height,
                    "x2": min(width, x2 + pad_x) / width,
                    "y2": min(height, y2 + pad_y) / height,
                    "_red_count": red_count,
                }
            )
        regions.sort(key=lambda item: item.get("_red_count", 0), reverse=True)
        trimmed = sorted(regions[:2], key=lambda item: (item["x1"] + item["x2"]) / 2.0)
        for region in trimmed:
            region.pop("_red_count", None)
        return trimmed

    def _load_image(self, image_data: bytes) -> Optional[Image.Image]:
        try:
            image = Image.open(io.BytesIO(image_data))
            return ImageOps.exif_transpose(image).convert("RGB")
        except Exception:
            return None

    def _image_to_png_bytes(self, image: Optional[Image.Image]) -> bytes:
        if image is None:
            return b""
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def _get_llm_image_size(self, image_data: bytes) -> Optional[Tuple[int, int]]:
        image = self._load_image(image_data)
        if image is None:
            return None
        max_dim = max(768, int(ReviewRuntime.ATTACHMENT_LLM_MAX_DIM))
        width, height = image.size
        if max(width, height) > max_dim:
            ratio = max_dim / max(width, height)
            width = int(width * ratio)
            height = int(height * ratio)
        return (width, height)

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

    def _prepare_stamp_crop_for_ocr(self, crop_image: Optional[Image.Image]) -> Optional[Image.Image]:
        if crop_image is None:
            return None
        rgb = crop_image.convert("RGB")
        width, height = rgb.size
        out = Image.new("L", (width, height), color=255)
        src = rgb.load()
        dst = out.load()
        for y in range(height):
            for x in range(width):
                r, g, b = src[x, y]
                if r >= 110 and r >= g + 28 and r >= b + 28:
                    dst[x, y] = 0
        out = out.filter(ImageFilter.MedianFilter(size=3))
        scale = 2
        out = out.resize((max(1, width * scale), max(1, height * scale)), Image.LANCZOS)
        out = ImageOps.expand(out, border=24, fill=255)
        return out.convert("RGB")

    def _prepare_stamp_crop_for_polar(self, crop_image: Optional[Image.Image]) -> Optional[Image.Image]:
        if crop_image is None:
            return None
        rgb = np.array(crop_image.convert("RGB")).astype(np.int16)
        red = rgb[:, :, 0]
        green = rgb[:, :, 1]
        blue = rgb[:, :, 2]
        dominance = np.clip((red - np.maximum(green, blue)) * 3.2, 0, 255).astype(np.uint8)
        gray = (255 - dominance).astype(np.uint8)
        gray = cv2.medianBlur(gray, 3)
        gray = cv2.resize(
            gray,
            (max(1, crop_image.size[0] * 2), max(1, crop_image.size[1] * 2)),
            interpolation=cv2.INTER_CUBIC,
        )
        gray = cv2.copyMakeBorder(gray, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
        return Image.fromarray(gray).convert("RGB")

    def _build_stamp_ocr_variants(
        self,
        crop_image: Optional[Image.Image],
        role_key: str,
    ) -> Dict[str, Any]:
        if crop_image is None:
            return {"variants": []}
        enhanced = self._prepare_stamp_crop_for_ocr(crop_image)
        if enhanced is None:
            return {"variants": []}
        variants: List[Tuple[str, Image.Image]] = [("enhanced", enhanced)]
        tight_crop = self._crop_largest_red_stamp_component(crop_image)
        polar_raw_source = crop_image
        polar_source = self._prepare_stamp_crop_for_polar(crop_image) or enhanced
        polar_source_variant = "enhanced"
        if tight_crop is not None:
            tight = self._prepare_stamp_crop_for_ocr(tight_crop)
            polar_tight = self._prepare_stamp_crop_for_polar(tight_crop)
            if tight is not None:
                variants.append(("tight", tight))
                polar_raw_source = tight_crop
                polar_source = polar_tight or tight
                polar_source_variant = "tight"
        upper_source = tight_crop or crop_image
        upper = self._prepare_stamp_upper_band_for_ocr(upper_source)
        if upper is not None:
            variants.append(("upper", upper))
        return {
            "variants": [(name, self._image_to_png_bytes(image)) for name, image in variants],
            "polar_raw_source": polar_raw_source,
            "polar_enhanced_source": polar_source,
            "polar_source_variant": polar_source_variant,
        }

    def _crop_largest_red_stamp_component(self, image: Image.Image) -> Optional[Image.Image]:
        try:
            rgb = np.array(image.convert("RGB")).astype(np.int16)
            red_mask = (
                (rgb[:, :, 0] >= 110)
                & (rgb[:, :, 0] >= rgb[:, :, 1] + 28)
                & (rgb[:, :, 0] >= rgb[:, :, 2] + 28)
            ).astype(np.uint8)
            if int(red_mask.sum()) < 80:
                return None

            kernel = np.ones((5, 5), dtype=np.uint8)
            red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(red_mask, connectivity=8)
            if count <= 1:
                return None

            image_area = image.size[0] * image.size[1]
            components: List[Tuple[int, int, int, int, int]] = []
            for label in range(1, count):
                x, y, w, h, area = [int(item) for item in stats[label]]
                if area < 80 or w * h < image_area * 0.04:
                    continue
                components.append((area, x, y, w, h))
            if not components:
                return None
            _, x, y, w, h = max(components, key=lambda item: item[0])
            pad = max(10, int(max(w, h) * 0.08))
            left = max(0, x - pad)
            top = max(0, y - pad)
            right = min(image.size[0], x + w + pad)
            bottom = min(image.size[1], y + h + pad)
            if right <= left or bottom <= top:
                return None
            return image.crop((left, top, right, bottom))
        except Exception as exc:
            logger.warning(f"[StampExtractor] 公章红色主体裁剪失败: {exc}")
            return None

    def _prepare_stamp_upper_band_for_ocr(self, image: Image.Image) -> Optional[Image.Image]:
        width, height = image.size
        if width < 20 or height < 20:
            return None
        box = (
            int(width * 0.04),
            int(height * 0.00),
            int(width * 0.96),
            int(height * 0.66),
        )
        cropped = image.crop(box)
        return self._prepare_stamp_crop_for_ocr(cropped)

    def _build_stamp_polar_variants(
        self,
        raw_image: Image.Image,
        enhanced_image: Image.Image,
        seam_angle_deg: Optional[float] = None,
        mask_angle_deg: Optional[float] = None,
        mask_half_span_deg: float = 10.0,
    ) -> List[Tuple[str, Image.Image]]:
        circles = self._detect_stamp_circle_candidates(raw_image)
        if not circles:
            return []
        gray = np.array(enhanced_image.convert("L"))
        candidates: List[Tuple[str, Image.Image]] = []
        scale = 2.0
        border = 24.0
        for circle_source, circle in circles:
            cx, cy, radius = circle
            if radius < 20:
                continue
            cx = cx * scale + border
            cy = cy * scale + border
            radius = radius * scale
            for candidate_name, inner_ratio, outer_ratio, start_deg, end_deg in (
                ("focus", 0.44, 0.90, -186.0, 6.0),
                ("wide", 0.38, 0.95, -194.0, 14.0),
                ("wider", 0.40, 0.94, -202.0, 22.0),
                ("widest", 0.42, 0.93, -214.0, 34.0),
                ("overscan", 0.43, 0.92, -226.0, 46.0),
                ("inner", 0.50, 0.86, -182.0, 2.0),
            ):
                band = self._unwrap_upper_annulus(
                    gray,
                    cx,
                    cy,
                    radius,
                    inner_ratio=inner_ratio,
                    outer_ratio=outer_ratio,
                    start_deg=start_deg,
                    end_deg=end_deg,
                )
                if band is None:
                    continue
                band = self._remove_stamp_ring_rows(band)
                band = self._trim_unwrapped_band_rows(band)
                band = self._trim_unwrapped_band_cols(band)
                if band is None:
                    continue
                forward = cv2.resize(
                    band,
                    (max(1600, band.shape[1] * 2), max(320, band.shape[0] * 3)),
                    interpolation=cv2.INTER_CUBIC,
                )
                forward = cv2.copyMakeBorder(forward, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)
                candidates.append((f"{circle_source}_{candidate_name}", Image.fromarray(forward).convert("RGB")))
        return candidates

    def _detect_stamp_circle_candidates(self, image: Image.Image) -> List[Tuple[str, Tuple[float, float, float]]]:
        rgb = np.array(image.convert("RGB")).astype(np.int16)
        mask = (
            (rgb[:, :, 0] >= 110)
            & (rgb[:, :, 0] >= rgb[:, :, 1] + 28)
            & (rgb[:, :, 0] >= rgb[:, :, 2] + 28)
        ).astype(np.uint8) * 255
        out: List[Tuple[str, Tuple[float, float, float]]] = []
        seen: List[Tuple[float, float, float]] = []

        def _push(name: str, circle: Tuple[float, float, float]) -> None:
            x, y, radius = circle
            for sx, sy, sr in seen:
                if abs(x - sx) <= 4.0 and abs(y - sy) <= 4.0 and abs(radius - sr) <= 4.0:
                    return
            seen.append(circle)
            out.append((name, circle))

        median_mask = cv2.medianBlur(mask, 5)
        min_dim = min(mask.shape[:2])
        circles = cv2.HoughCircles(
            median_mask,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=max(40, min_dim // 3),
            param1=80,
            param2=20,
            minRadius=max(20, int(min_dim * 0.25)),
            maxRadius=max(24, int(min_dim * 0.60)),
        )
        if circles is not None and circles.size > 0:
            x, y, radius = circles[0][0].tolist()
            _push("hough", (float(x), float(y), float(radius)))

        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            min_dim = min(mask.shape[:2])
            candidates: List[Tuple[float, Tuple[float, float, float]]] = []
            image_area = float(mask.shape[0] * mask.shape[1])
            for contour in contours:
                area = float(cv2.contourArea(contour))
                if area < max(120.0, image_area * 0.01):
                    continue
                (x, y), radius = cv2.minEnclosingCircle(contour)
                if radius < max(20.0, min_dim * 0.20):
                    continue
                candidates.append((area, (float(x), float(y), float(radius))))
            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                _push("contour", candidates[0][1])

        return out

    def _unwrap_upper_annulus(
        self,
        gray: np.ndarray,
        center_x: float,
        center_y: float,
        radius: float,
        inner_ratio: float,
        outer_ratio: float,
        start_deg: float,
        end_deg: float,
    ) -> Optional[np.ndarray]:
        text_center_ratio = (inner_ratio + outer_ratio) / 2.0
        mean_radius = radius * text_center_ratio
        arc_span = np.deg2rad(end_deg - start_deg)
        output_width = max(1200, int(mean_radius * arc_span * 2.4))
        output_height = max(180, int(radius * (outer_ratio - inner_ratio) * 3.2))
        angles = np.deg2rad(np.linspace(start_deg, end_deg, output_width))
        radii = np.linspace(radius * outer_ratio, radius * inner_ratio, output_height)
        angle_grid, radius_grid = np.meshgrid(angles, radii)
        map_x = (center_x + radius_grid * np.cos(angle_grid)).astype(np.float32)
        map_y = (center_y + radius_grid * np.sin(angle_grid)).astype(np.float32)
        band = cv2.remap(
            gray,
            map_x,
            map_y,
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )
        if int((band < 180).sum()) < 80:
            return None
        return band

    def _trim_unwrapped_band_rows(self, band: np.ndarray) -> Optional[np.ndarray]:
        dark_rows = np.where((band < 190).mean(axis=1) > 0.01)[0]
        if dark_rows.size == 0:
            return None
        top = max(0, int(dark_rows[0]) - 10)
        bottom = min(band.shape[0], int(dark_rows[-1]) + 11)
        trimmed = band[top:bottom, :]
        if trimmed.size == 0:
            return None
        return trimmed

    def _trim_unwrapped_band_cols(self, band: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if band is None or band.size == 0:
            return None
        dark_cols = np.where((band < 190).mean(axis=0) > 0.008)[0]
        if dark_cols.size == 0:
            return band
        left = max(0, int(dark_cols[0]) - 48)
        right = min(band.shape[1], int(dark_cols[-1]) + 49)
        trimmed = band[:, left:right]
        if trimmed.size == 0:
            return None
        return trimmed

    def _polar_edge_cut_penalty(self, image: Image.Image) -> float:
        gray = np.array(image.convert("L"))
        if gray.size == 0:
            return 1.0
        sample = min(80, max(16, gray.shape[1] // 20))
        left_density = float((gray[:, :sample] < 190).mean())
        right_density = float((gray[:, -sample:] < 190).mean())
        return max(left_density, right_density)

    def _remove_stamp_ring_rows(self, band: np.ndarray) -> np.ndarray:
        cleaned = band.copy()
        row_density = (cleaned < 180).mean(axis=1)
        dense_rows = np.where(row_density > 0.72)[0]
        if dense_rows.size:
            cleaned[dense_rows, :] = 255
        return cleaned

    def _build_polar_segments(self, polar_image: Image.Image) -> List[Tuple[str, bytes]]:
        gray = np.array(polar_image.convert("L"))
        width = gray.shape[1]
        segment_count = 5
        overlap = max(112, width // 9)
        step = max(1, int(np.ceil((width - overlap) / float(segment_count))))
        segments: List[Tuple[str, bytes]] = []
        for index in range(segment_count):
            left = max(0, index * step)
            right = min(width, left + step + overlap)
            if right - left < max(220, width // 6):
                continue
            segment = gray[:, left:right]
            segment = cv2.copyMakeBorder(segment, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            image = Image.fromarray(segment).convert("RGB")
            segments.append((f"polar_upper_seg{index + 1}", self._image_to_png_bytes(image)))
            if right >= width:
                break
        return segments

    async def _build_polar_variant_payload(
        self,
        role_key: str,
        polar_raw_source: Optional[Image.Image],
        polar_enhanced_source: Optional[Image.Image],
        polar_source_variant: str,
    ) -> Optional[Dict[str, Any]]:
        if polar_raw_source is None or polar_enhanced_source is None or not polar_source_variant:
            return None
        polar_variants = self._build_stamp_polar_variants(
            raw_image=polar_raw_source,
            enhanced_image=polar_enhanced_source,
        )
        if not polar_variants:
            return None
        candidate_payloads: List[Dict[str, Any]] = []
        best_payload: Optional[Dict[str, Any]] = None
        best_image: Optional[Image.Image] = None
        best_score: Tuple[int, int, float] = (-1, -1, -1.0)

        for candidate_name, polar_image in polar_variants:
            polar_bytes = self._image_to_png_bytes(polar_image)
            ocr_inputs: List[Tuple[str, bytes]] = [(candidate_name, polar_bytes)]
            ocr_inputs.extend(self._build_polar_segments(polar_image))
            calls = [
                self._run_qwen_ocr(
                    image_data=image_data,
                    prompt="请对这张公章文字展开图执行 OCR，只返回图片中实际可见文字，不要纠错，不要补全。",
                    debug_name=f"stamp_{role_key}_{name}_ocr",
                    task="advanced_recognition",
                    enable_rotate=False,
                )
                for name, image_data in ocr_inputs
            ]
            results = await asyncio.gather(*calls, return_exceptions=True)
            ocr_payloads: List[Dict[str, Any]] = []
            ordered_segment_texts: List[str] = []
            full_texts: List[str] = []
            for (name, _), result in zip(ocr_inputs, results):
                if isinstance(result, Exception):
                    ocr_payloads.append({"variant": name, "error": str(result), "texts": []})
                    continue
                texts = self._extract_stamp_unit_texts(result, variant_name=name)
                ocr_payloads.append(
                    {
                        "variant": name,
                        "texts": texts,
                        "processed_text": result.get("processed_text", ""),
                        "words_info": result.get("words_info", []),
                    }
                )
                if name == candidate_name:
                    full_texts = [self._normalize_stamp_unit_text(text) for text in texts if self._normalize_stamp_unit_text(text)]
                elif name.startswith("polar_upper_seg"):
                    segment_text = self._merge_ordered_stamp_texts(texts)
                    if segment_text:
                        ordered_segment_texts.append(segment_text)
            merged_segment_text = self._merge_overlapping_stamp_segments(ordered_segment_texts)
            texts: List[str] = []
            for text in full_texts:
                if text and text not in texts:
                    texts.append(text)
            if merged_segment_text and merged_segment_text not in texts:
                texts.append(merged_segment_text)
            candidate_payload = {
                "variant": candidate_name,
                "texts": texts[:2],
                "processed_text": "",
                "words_info": [],
                "ocr_payloads": ocr_payloads,
            }
            candidate_payloads.append(candidate_payload)
            primary_text = texts[0] if texts else ""
            edge_penalty = self._polar_edge_cut_penalty(polar_image)
            score = (
                len(primary_text),
                sum(1 for item in ordered_segment_texts if item),
                1.0 - edge_penalty,
            )
            if score > best_score:
                best_score = score
                best_payload = candidate_payload
                best_image = polar_image

        if best_payload is None or best_image is None:
            return None
        self._save_stamp_variant_debug(role_key, "polar_upper", self._image_to_png_bytes(best_image))
        other_candidates = [payload for payload in candidate_payloads if payload is not best_payload]
        best_payload["variant"] = "polar_upper"
        best_payload["candidate_variants"] = other_candidates
        return best_payload

    def _merge_ordered_stamp_texts(self, texts: List[str]) -> str:
        merged = ""
        for text in texts:
            normalized = self._normalize_stamp_unit_text(text)
            if not normalized:
                continue
            if not merged:
                merged = normalized
                continue
            if normalized in merged:
                continue
            if merged in normalized:
                merged = normalized
                continue
            overlap = self._max_suffix_prefix_overlap(merged, normalized)
            if overlap > 0:
                merged = merged + normalized[overlap:]
            else:
                merged = merged + normalized
        return merged

    def _merge_overlapping_stamp_segments(self, segments: List[str]) -> str:
        merged = ""
        for segment in segments:
            normalized = self._normalize_stamp_unit_text(segment)
            if not normalized:
                continue
            if not merged:
                merged = normalized
                continue
            if normalized in merged:
                continue
            if merged in normalized:
                merged = normalized
                continue
            overlap = self._max_suffix_prefix_overlap(merged, normalized)
            if overlap >= 1:
                merged = merged + normalized[overlap:]
            else:
                merged = merged + normalized
        return merged

    def _max_suffix_prefix_overlap(self, left: str, right: str) -> int:
        max_len = min(len(left), len(right))
        for size in range(max_len, 0, -1):
            if left.endswith(right[:size]):
                return size
        return 0

    def _roll_polar_band_to_blank_seam(self, band: np.ndarray) -> np.ndarray:
        dark = band < 180
        col_density = dark.mean(axis=0)
        if col_density.size < 8:
            return band
        # Find the weakest continuous text gap instead of the single lightest
        # column, so the seam is less likely to slice through a character.
        width = int(col_density.size)
        window = max(48, min(180, width // 10))
        doubled = np.concatenate([col_density, col_density], axis=0)
        prefix = np.concatenate([[0.0], np.cumsum(doubled, dtype=np.float32)])
        window_scores = prefix[window:] - prefix[:-window]
        if window_scores.size <= 0:
            seam = int(np.argmin(col_density))
        else:
            valid_scores = window_scores[:width]
            start = int(np.argmin(valid_scores))
            seam = start + window // 2
        shift = band.shape[1] // 2 - seam
        return np.roll(band, shift=shift, axis=1)

    def _mask_stamp_sector(
        self,
        gray: np.ndarray,
        center_x: float,
        center_y: float,
        angle_deg: float,
        half_span_deg: float,
    ) -> np.ndarray:
        height, width = gray.shape[:2]
        yy, xx = np.ogrid[:height, :width]
        angles = np.degrees(np.arctan2(yy - center_y, xx - center_x))
        delta = (angles - angle_deg + 180.0) % 360.0 - 180.0
        masked = gray.copy()
        masked[np.abs(delta) <= max(2.0, float(half_span_deg))] = 255
        return masked

    def _find_stamp_serial_word(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        words = list(result.get("words_info") or [])
        candidates: List[Tuple[int, float, Dict[str, Any]]] = []
        for word in words:
            raw = str(word.get("text") or "").strip()
            digits = re.sub(r"\D+", "", raw)
            if len(digits) < 6:
                continue
            box = self._word_bbox(word)
            candidates.append((len(digits), box["y1"], word))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], -item[1]))
        return candidates[0][2]

    def _compute_stamp_serial_angle(
        self,
        circle: Tuple[float, float, float],
        word: Dict[str, Any],
    ) -> Tuple[float, float]:
        cx, cy, radius = circle
        scale = 2.0
        border = 24.0
        cx = cx * scale + border
        cy = cy * scale + border
        radius = radius * scale

        box = self._word_bbox(word)
        word_cx = (box["x1"] + box["x2"]) / 2.0
        word_cy = (box["y1"] + box["y2"]) / 2.0
        angle_deg = float(np.degrees(np.arctan2(word_cy - cy, word_cx - cx)))
        word_w = max(1.0, box["x2"] - box["x1"])
        half_span_deg = max(8.0, min(22.0, np.degrees(word_w / max(radius, 1.0)) * 0.8))
        return angle_deg, float(half_span_deg)

    def _extract_stamp_unit_texts(self, result: Dict[str, Any], variant_name: str = "") -> List[str]:
        words = list(result.get("words_info") or [])
        if variant_name.startswith("polar"):
            reordered = self._extract_polar_stamp_unit_texts(words, str(result.get("processed_text") or ""))
            if reordered:
                return reordered
        ranked: List[Tuple[float, float, str]] = []
        for word in words:
            text = str(word.get("text") or "").strip()
            if not text:
                continue
            box = self._word_bbox(word)
            ranked.append((box["y1"], box["x1"], text))
        ranked.sort()
        texts = [text for _, _, text in ranked]
        if not texts:
            texts = self._extract_processed_texts(str(result.get("processed_text") or ""))

        unit_like: List[str] = []
        seen: set[str] = set()
        for text in texts:
            cleaned = self._retain_chinese_only(text)
            if not cleaned:
                continue
            if any(token in cleaned for token in ("工作单位", "完成单位", "公章", "声明", "签名")):
                continue
            if len(cleaned) < 2:
                continue
            key = cleaned
            if key in seen:
                continue
            seen.add(key)
            unit_like.append(cleaned)
        return unit_like

    def _extract_polar_stamp_unit_texts(self, words: List[Dict[str, Any]], processed_text: str) -> List[str]:
        entries: List[Tuple[float, str, str]] = []
        for word in words:
            raw = str(word.get("text") or "").strip()
            if not raw:
                continue
            box = self._word_bbox(word)
            entries.append((box["x1"], raw, re.sub(r"\D+", "", raw)))
        entries.sort(key=lambda item: item[0])

        if not entries:
            for raw in self._extract_processed_texts(processed_text):
                text = raw.strip()
                if not text:
                    continue
                entries.append((float(len(entries)), text, re.sub(r"\D+", "", text)))

        if not entries:
            return []

        candidates: List[str] = []
        seen: set[str] = set()

        def _push(text: str) -> None:
            normalized = self._normalize_stamp_unit_text(text)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        chinese_all = [self._retain_chinese_only(raw) for _, raw, _ in entries]
        _push("".join(part for part in chinese_all if part))

        boundary_indexes = [index for index, (_, _, digits) in enumerate(entries) if len(digits) >= 4]
        for index in boundary_indexes:
            left = "".join(
                self._retain_chinese_only(raw)
                for _, raw, _ in entries[:index]
                if self._retain_chinese_only(raw)
            )
            right = "".join(
                self._retain_chinese_only(raw)
                for _, raw, _ in entries[index + 1:]
                if self._retain_chinese_only(raw)
            )
            if right or left:
                _push(right + left)

        return candidates

    def _choose_consensus_stamp_texts(self, variant_payloads: List[Dict[str, Any]]) -> List[str]:
        for payload in variant_payloads:
            if str(payload.get("variant") or "") != "polar_upper":
                continue
            texts: List[str] = []
            for text in payload.get("texts") or []:
                cleaned = self._normalize_stamp_unit_text(text)
                if cleaned:
                    texts.append(cleaned)
            if texts:
                return texts[:1]

        variant_texts: List[List[str]] = []
        for payload in variant_payloads:
            texts: List[str] = []
            for text in payload.get("texts") or []:
                cleaned = self._normalize_stamp_unit_text(text)
                if cleaned:
                    texts.append(cleaned)
            if texts:
                variant_texts.append(texts)
        candidates = [text for texts in variant_texts for text in texts]
        if not candidates:
            return []

        counts: Dict[str, int] = {}
        for text in candidates:
            counts[text] = counts.get(text, 0) + 1
        repeated = [
            text
            for text, count in counts.items()
            if count >= 2 and all(texts == [text] for texts in variant_texts if text in texts)
        ]
        if repeated and len(counts) == 1:
            return sorted(repeated, key=lambda item: (-counts[item], candidates.index(item)))[:1]

        # 环形章 OCR 不稳定，碎片重复也不能当作完整章名。
        logger.warning(f"[StampExtractor] 公章 OCR 结果未形成可靠单一文本: {variant_texts}")
        return []

    def _normalize_stamp_unit_text(self, text: Any) -> str:
        cleaned = self._retain_chinese_only(text)
        if not cleaned:
            return ""
        cleaned = cleaned.replace("學", "学").replace("華", "华")
        if any(token in cleaned for token in ("工作单位", "完成单位", "公章", "声明", "签名", "校徽")):
            return ""
        if len(cleaned) < 3:
            return ""
        return cleaned

    def _retain_chinese_only(self, text: Any) -> str:
        raw = str(text or "")
        cleaned = "".join(ch for ch in raw if "\u4e00" <= ch <= "\u9fff")
        return cleaned.strip()

    def _extract_processed_texts(self, processed_text: str) -> List[str]:
        lines: List[str] = []
        for line in processed_text.splitlines():
            text = line.strip()
            if not text:
                continue
            text = text.lstrip("- ").strip()
            if text:
                lines.append(text)
        return lines

    def _save_award_stamp_anchor_debug(
        self,
        image_data: bytes,
        anchors: Dict[str, Dict[str, float]],
        raw: Any,
    ) -> None:
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        if os.path.isdir(debug_dir):
            for name in os.listdir(debug_dir):
                if (
                    name.startswith("stamp_anchor_")
                    or name.startswith("tmp_")
                    or (name.startswith("stamp_") and name.endswith(".json"))
                ):
                    path = os.path.join(debug_dir, name)
                    if os.path.isfile(path):
                        os.remove(path)
        return

    def _save_stamp_variant_debug(self, role_key: str, variant_name: str, image_data: bytes) -> None:
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)
        safe_role = re.sub(r"[^\w.-]+", "_", str(role_key or "stamp"))
        safe_variant = re.sub(r"[^\w.-]+", "_", str(variant_name or "variant"))
        image = self._load_image(image_data)
        if image is not None:
            image.save(f"{debug_dir}/stamp_{safe_role}_{safe_variant}.png")

    def _save_award_stamp_debug_crop(
        self,
        role_key: str,
        role_label: str,
        page_image: Image.Image,
        anchor_bbox: Dict[str, float],
        crop_bbox: Dict[str, float],
        crop_bytes: bytes,
        ocr_bytes: Optional[bytes] = None,
        ocr_variants: Optional[List[Tuple[str, bytes]]] = None,
    ) -> None:
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)
        safe_label = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", role_label)
        prefix = f"stamp_{role_key}_{safe_label}"
        for name in os.listdir(debug_dir):
            if name.startswith(f"stamp_{role_key}_"):
                path = os.path.join(debug_dir, name)
                if os.path.isfile(path):
                    os.remove(path)

        crop_image = self._load_image(crop_bytes)
        if crop_image is not None:
            crop_image.save(f"{debug_dir}/{prefix}.png")

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
