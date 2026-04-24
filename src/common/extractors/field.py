"""字段提取器（Layer 4）

职责：从文档中提取表格/表单字段的值
流程：Step1 识别字段 → Step2 定位 bbox → Step3 OCR 转写
"""
import asyncio
import base64
import io
import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional

import requests
from PIL import Image, ImageDraw, ImageOps

from src.common.llm import llm_config
from src.common.vision.multimodal import MultimodalLLM

logger = logging.getLogger(__name__)


class FieldExtractor:
    """字段提取器 - 先定位 bbox 再 OCR 转写"""

    def __init__(self):
        self._llm_client = None
        self._last_page_ocr_result: Dict[str, Any] = {}
        self._last_page_words: List[Dict[str, Any]] = []

    @property
    def ocr(self):
        """获取全局 OCR 实例"""
        from src.services.review.extractor import get_global_ocr
        return get_global_ocr()

    async def extract(
        self,
        file_data: bytes,
        document_type: Optional[str] = None,
        configured_fields: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        提取字段内容

        Args:
            file_data: PDF/图片 bytes
            document_type: 文档类型（用于加载配置字段）
            configured_fields: 配置的关键字段列表

        Returns:
            字段字典 {"__fields": [...], "字段名": "值", ...}，提取失败返回 None
        """
        try:
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size

            # 2. Step1: 识别表格字段
            field_names = await self._detect_fields(image_data, document_type, configured_fields)
            if not field_names:
                logger.warning("[FieldExtractor] 未能识别到表格字段")
                return None

            # 3. Step2: 定位字段值区域 (bbox)
            field_coords = await self._locate_fields(image_data, field_names)
            if not field_coords:
                logger.warning("[FieldExtractor] 未能定位到字段区域")
                return None

            # 4. Step3: 裁剪 + OCR 转写
            fields = await self._extract_values(img, img_w, img_h, field_names, field_coords)

            logger.info(f"[FieldExtractor] 字段提取完成，共 {len(fields)} 个字段")
            return fields

        except Exception as e:
            logger.error(f"[FieldExtractor] 字段提取失败: {e}")
            return None

    async def extract_with_coords(
        self,
        file_data: bytes,
        field_coords: Dict[str, tuple],
        field_names: List[str],
    ) -> Dict[str, Any]:
        """使用已知坐标提取字段值（跳过 LLM 定位步骤）"""
        try:
            # PDF 转图片
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size
            
            # 直接用已知坐标提取
            fields = await self._extract_values(img, img_w, img_h, field_names, field_coords)
            
            logger.info(f"[FieldExtractor] 字段提取完成，共 {len(fields)} 个字段")
            return fields
            
        except Exception as e:
            logger.error(f"[FieldExtractor] 字段提取失败: {e}")
            return {"__fields": field_names, "error": str(e)}

    def _pdf_to_image(self, file_data: bytes) -> bytes:
        """PDF 转图片（取第一页，fitz 放大3倍）"""
        import fitz  # PyMuPDF
        
        if file_data[:4] != b'%PDF':
            # 不是 PDF，直接返回
            return file_data
        
        try:
            doc = fitz.open(stream=file_data, filetype="pdf")
            if doc.page_count == 0:
                return file_data
            
            # 渲染第一页为图片（放大3倍，提高清晰度）
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))  # 3x 分辨率
            img_data = pix.tobytes("png")
            doc.close()
            return img_data
        except Exception as e:
            logger.warning(f"[FieldExtractor] PDF 转图片失败: {e}")
            return file_data

    async def _detect_fields(
        self,
        image_data: bytes,
        document_type: Optional[str],
        configured_fields: Optional[List[str]],
    ) -> Optional[List[str]]:
        """Step1: 识别表格字段"""
        # 优先使用配置字段
        if configured_fields:
            logger.info(f"[FieldExtractor] 使用配置的关键字段: {configured_fields}")
            return configured_fields

        # 从配置加载字段
        if document_type:
            from src.services.review.rules.config import load_llm_extract_fields
            configured = load_llm_extract_fields(document_type)
            if configured:
                logger.info(f"[FieldExtractor] 使用配置的关键字段: {configured}")
                return configured

        # 自动识别字段
        llm = self._get_llm()
        multi_llm = MultimodalLLM(llm)

        prompt = """请仔细看图，列出这个表格/表单的所有字段名（只返回字段名列表，每行一个）。

只输出字段名，不要其他内容。"""

        try:
            result = await multi_llm.analyze_image(image_data, prompt)
            field_names = [line.strip() for line in result.strip().split('\n') if line.strip() and len(line.strip()) > 1]
            
            max_fields = int(os.getenv("LLM_MAX_FIELDS", "25"))
            if len(field_names) > max_fields:
                logger.warning(f"[FieldExtractor] 字段数过多({len(field_names)})，仅保留前{max_fields}个")
                field_names = field_names[:max_fields]
            
            return field_names if field_names else None
        except Exception as e:
            logger.error(f"[FieldExtractor] Step1 字段识别失败: {e}")
            return None

    async def _locate_fields(self, image_data: bytes, field_names: List[str]) -> Optional[Dict[str, tuple]]:
        """Step2: 用原生 Qwen-OCR 识别整页文字和坐标，再映射到目标字段。"""
        try:
            img = Image.open(io.BytesIO(image_data)).convert("RGB")
            img_w, img_h = img.size
            ocr_result = await self._run_qwen_ocr(
                image_data=image_data,
                prompt="请对这张中文表单执行 OCR，返回所有文字及其位置。",
                debug_name="page_ocr",
            )
            words = list(ocr_result.get("words_info") or [])
            self._last_page_ocr_result = ocr_result
            self._last_page_words = words
            field_coords = {}
            debug_rows: Dict[str, Any] = {}
            for fname in field_names:
                label_word = self._match_field_label(words, fname)
                value_words = self._select_field_value_words(words, label_word, field_names)
                value_bbox = self._build_field_value_bbox(
                    words=words,
                    label_word=label_word,
                    value_words=value_words,
                    field_names=field_names,
                    image_size=(img_w, img_h),
                )
                if not value_bbox:
                    continue
                x1 = value_bbox["x1"] / max(img_w, 1)
                y1 = value_bbox["y1"] / max(img_h, 1)
                x2 = value_bbox["x2"] / max(img_w, 1)
                y2 = value_bbox["y2"] / max(img_h, 1)
                field_coords[fname] = (x1, y1, x2, y2)
                debug_rows[fname] = {
                    "label": label_word,
                    "value_words": value_words,
                    "value_bbox": value_bbox,
                    "normalized_bbox": [x1, y1, x2, y2],
                }
            self._save_qwen_page_debug(img, field_names, debug_rows, words)
            logger.info(f"[FieldExtractor] 定位到 {len(field_coords)} 个字段区域")
            return field_coords if field_coords else None
        except Exception as e:
            logger.error(f"[FieldExtractor] Step2 字段定位失败: {e}")
            return None

    async def _extract_values(
        self,
        img: Image.Image,
        img_w: int,
        img_h: int,
        field_names: List[str],
        field_coords: Dict[str, tuple],
    ) -> Dict[str, Any]:
        """Step3: 裁剪 + 原生 Qwen-OCR 二次转写"""
        fields = {"__fields": field_names}

        for i, fname in enumerate(field_names):
            if fname not in field_coords:
                fields[fname] = "未定位"
                continue

            raw_bbox = field_coords[fname]
            x1, y1, x2, y2 = self._expand_field_bbox(
                self._normalize_field_bbox(raw_bbox, img_w, img_h)
            )

            if x2 <= x1 or y2 <= y1:
                logger.warning(f"[FieldExtractor] 字段{fname}区域太小，跳过")
                self._save_field_debug_crop(
                    img=img,
                    img_w=img_w,
                    img_h=img_h,
                    fname=fname,
                    index=i,
                    bbox=(x1, y1, x2, y2),
                    suffix="invalid",
                    metadata={"raw_bbox": raw_bbox, "prepared_bbox": (x1, y1, x2, y2)},
                )
                fields[fname] = "区域太小"
                continue

            # 裁剪坐标
            left = int(x1 * img_w)
            top = int(y1 * img_h)
            right = int(x2 * img_w)
            bottom = int(y2 * img_h)

            if right - left < 5 or bottom - top < 5:
                logger.warning(f"[FieldExtractor] 字段{fname}裁剪区域太小")
                self._save_field_debug_crop(
                    img=img,
                    img_w=img_w,
                    img_h=img_h,
                    fname=fname,
                    index=i,
                    bbox=(x1, y1, x2, y2),
                    suffix="too_small",
                    metadata={
                        "raw_bbox": raw_bbox,
                        "prepared_bbox": (x1, y1, x2, y2),
                        "pixel_box": (left, top, right, bottom),
                    },
                )
                fields[fname] = "裁剪区域太小"
                continue

            cropped_img = img.crop((left, top, right, bottom))
            final_crop = self._prepare_crop_for_ocr(cropped_img)
            self._save_field_debug_assets(
                fname=fname,
                index=i,
                raw_crop=cropped_img,
                final_crop=final_crop,
                metadata={
                    "raw_bbox": raw_bbox,
                    "normalized_bbox": (x1, y1, x2, y2),
                    "pixel_box": (left, top, right, bottom),
                    "page_ocr_value_words": self._get_last_page_value_words(fname),
                },
            )
            trans = await self._qwen_transcribe_crop(final_crop, fname=fname, index=i)
            logger.info(f"[OCR] 字段{i+1}/{len(field_names)}: {fname} -> {trans[:30]}...")
            fields[fname] = trans.strip()

        return fields

    def _normalize_field_bbox(
        self,
        bbox: tuple,
        img_w: int,
        img_h: int,
    ) -> tuple[float, float, float, float]:
        """兼容 LLM 偶发返回像素坐标或百分比坐标。"""
        try:
            x1, y1, x2, y2 = [float(item) for item in bbox]
        except Exception:
            return 0.0, 0.0, 0.0, 0.0

        max_abs = max(abs(x1), abs(y1), abs(x2), abs(y2))
        if max_abs <= 1.0:
            return x1, y1, x2, y2
        if max_abs <= 100.0:
            return x1 / 100.0, y1 / 100.0, x2 / 100.0, y2 / 100.0
        return x1 / max(img_w, 1), y1 / max(img_h, 1), x2 / max(img_w, 1), y2 / max(img_h, 1)

    def _expand_field_bbox(
        self,
        bbox: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        """对齐 2026-03-20 风格：仅做轻量扩边。"""
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        margin_x = width * 0.04
        margin_y = height * 0.10
        x1 = max(0.0, x1 - margin_x)
        y1 = max(0.0, y1 - margin_y)
        x2 = min(1.0, x2 + margin_x)
        y2 = min(1.0, y2 + margin_y)
        return x1, y1, x2, y2

    def _prepare_crop_for_ocr(self, cropped_img: Image.Image) -> Image.Image:
        """对齐 2026-03-20 风格：适当放大并补白边。"""
        scale = max(1, min(4, math.ceil(72 / max(1, cropped_img.height))))
        prepared = cropped_img.resize(
            (max(1, cropped_img.width * scale), max(1, cropped_img.height * scale)),
            Image.LANCZOS,
        )
        padding = int(min(prepared.width, prepared.height) * 0.15)
        return ImageOps.expand(prepared, border=padding, fill="white")

    def _save_field_debug_crop(
        self,
        img: Image.Image,
        img_w: int,
        img_h: int,
        fname: str,
        index: int,
        bbox: tuple[float, float, float, float],
        suffix: str,
        metadata: Dict[str, Any],
    ) -> None:
        """保存字段裁剪调试图。"""
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)

        safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(fname or "field"))
        x1, y1, x2, y2 = bbox
        left = int(max(0.0, min(1.0, x1)) * img_w)
        top = int(max(0.0, min(1.0, y1)) * img_h)
        right = int(max(0.0, min(1.0, x2)) * img_w)
        bottom = int(max(0.0, min(1.0, y2)) * img_h)
        if right <= left or bottom <= top:
            return

        crop = img.crop((left, top, right, bottom))
        crop.save(f"{debug_dir}/{safe_name}_{index + 1}_{suffix}.png")

    def _save_field_debug_assets(
        self,
        fname: str,
        index: int,
        raw_crop: Image.Image,
        final_crop: Image.Image,
        metadata: Dict[str, Any],
    ) -> None:
        """保存字段原始裁剪图和最终 OCR 图。"""
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)

        safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(fname or "field"))
        raw_crop.save(f"{debug_dir}/{safe_name}_{index + 1}_raw.png")
        final_crop.save(f"{debug_dir}/{safe_name}_{index + 1}.png")

    async def _qwen_transcribe_crop(
        self,
        cropped_img: Image.Image,
        fname: str,
        index: int,
    ) -> str:
        """crop 后再走一次原生 Qwen-OCR，最终值只认第二次 OCR 结果。"""
        buf = io.BytesIO()
        cropped_img.save(buf, format="PNG")
        result = await self._run_qwen_ocr(
            image_data=buf.getvalue(),
            prompt="请对这张字段小图执行 OCR，只返回图片中实际可见文字，不要纠错，不要补全。",
            debug_name=f"{re.sub(r'[^\w\u4e00-\u9fff.-]+', '_', str(fname or 'field'))}_{index + 1}_ocr",
        )
        texts = self._extract_ordered_texts(result.get("words_info") or [])
        if texts:
            return "".join(texts).strip()
        processed_text = str(result.get("processed_text") or "").strip()
        if not processed_text:
            return ""
        parsed_lines = self._parse_processed_text_entries(processed_text)
        return "".join(item.get("text", "") for item in parsed_lines).strip()

    async def _run_qwen_ocr(
        self,
        image_data: bytes,
        prompt: str,
        debug_name: str,
    ) -> Dict[str, Any]:
        """调用 Qwen-OCR 原生 advanced_recognition。"""
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
                    "task": "advanced_recognition",
                    "enable_table": False,
                    "enable_rotate": True,
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
        return

    def _match_field_label(self, words: List[Dict[str, Any]], field_name: str) -> Optional[Dict[str, Any]]:
        target = self._normalize_text(field_name)
        exact = [word for word in words if self._normalize_text(word.get("text")) == target]
        if exact:
            return sorted(exact, key=lambda item: self._word_bbox(item)["x1"])[0]
        fuzzy = [word for word in words if target in self._normalize_text(word.get("text"))]
        if fuzzy:
            return sorted(fuzzy, key=lambda item: self._word_bbox(item)["x1"])[0]
        return None

    def _select_field_value_words(
        self,
        words: List[Dict[str, Any]],
        label_word: Optional[Dict[str, Any]],
        field_names: List[str],
    ) -> List[Dict[str, Any]]:
        if not label_word:
            return []
        label_box = self._word_bbox(label_word)
        label_center_y = (label_box["y1"] + label_box["y2"]) / 2.0
        label_height = max(1.0, label_box["y2"] - label_box["y1"])
        blocked = {self._normalize_text(item) for item in field_names}
        candidates: List[Dict[str, Any]] = []
        for word in words:
            if word is label_word:
                continue
            text_norm = self._normalize_text(word.get("text"))
            if not text_norm or text_norm in blocked:
                continue
            box = self._word_bbox(word)
            center_y = (box["y1"] + box["y2"]) / 2.0
            if box["x1"] < label_box["x2"] - 8:
                continue
            if abs(center_y - label_center_y) > max(24.0, label_height * 1.2):
                continue
            # 不跨到下一个单元格列头。优先限制在 label 右侧约 1.6 倍字段名宽度内。
            if box["x1"] - label_box["x2"] > max(180.0, (label_box["x2"] - label_box["x1"]) * 1.6):
                continue
            candidates.append(word)
        if not candidates:
            return []
        candidates = sorted(candidates, key=lambda item: self._word_bbox(item)["x1"])
        leftmost_x = self._word_bbox(candidates[0])["x1"]
        near_left_candidates = [
            item
            for item in candidates
            if self._word_bbox(item)["x1"] <= leftmost_x + 24.0
        ]
        best = max(
            near_left_candidates,
            key=lambda item: (
                self._word_bbox(item)["x2"] - self._word_bbox(item)["x1"],
                len(self._normalize_text(item.get("text"))),
            ),
        )
        return [best]

    def _build_field_value_bbox(
        self,
        words: List[Dict[str, Any]],
        label_word: Optional[Dict[str, Any]],
        value_words: List[Dict[str, Any]],
        field_names: List[str],
        image_size: tuple[int, int],
    ) -> Optional[Dict[str, float]]:
        """优先按整格推断字段值区域，覆盖多行单元格；失败时回退到 value words bbox。"""
        if not label_word:
            return self._merge_word_bboxes(value_words)

        label_box = self._word_bbox(label_word)
        label_height = max(1.0, label_box["y2"] - label_box["y1"])
        merged_value_bbox = self._merge_word_bboxes(value_words)
        img_w, img_h = image_size
        row_top, row_bottom = self._estimate_row_band(words, label_word, img_h)
        right_boundary = self._estimate_next_column_left(words, label_box, row_top, row_bottom, img_w)

        left = max(label_box["x2"] + 4.0, 0.0)
        right = min(right_boundary - 6.0, float(img_w))
        top = max(row_top + 2.0, 0.0)
        bottom = min(row_bottom - 2.0, float(img_h))

        if merged_value_bbox:
            value_height = max(1.0, merged_value_bbox["y2"] - merged_value_bbox["y1"])
            left = max(left, merged_value_bbox["x1"] - 8.0)
            right = min(right, merged_value_bbox["x2"] + max(28.0, value_height * 1.2))
            top = min(top, max(0.0, merged_value_bbox["y1"] - max(12.0, label_height * 0.35)))
            bottom = min(bottom, merged_value_bbox["y2"] + max(24.0, value_height * 1.8))

        if right - left >= 12.0 and bottom - top >= 12.0:
            return {"x1": left, "y1": top, "x2": right, "y2": bottom}
        return merged_value_bbox

    def _estimate_row_band(
        self,
        words: List[Dict[str, Any]],
        label_word: Dict[str, Any],
        img_h: int,
    ) -> tuple[float, float]:
        """根据左列标签的上下邻居估计整行边界，避免只截到单行文字。"""
        label_box = self._word_bbox(label_word)
        label_center_y = (label_box["y1"] + label_box["y2"]) / 2.0
        label_height = max(1.0, label_box["y2"] - label_box["y1"])

        left_column_words: List[Dict[str, Any]] = []
        for word in words:
            box = self._word_bbox(word)
            center_x = (box["x1"] + box["x2"]) / 2.0
            if center_x > label_box["x2"] + 40.0:
                continue
            if box["x1"] > label_box["x1"] + 80.0:
                continue
            text_norm = self._normalize_text(word.get("text"))
            if not text_norm:
                continue
            left_column_words.append(word)

        left_column_words = sorted(
            left_column_words,
            key=lambda item: ((self._word_bbox(item)["y1"] + self._word_bbox(item)["y2"]) / 2.0, self._word_bbox(item)["x1"]),
        )
        prev_center_y: Optional[float] = None
        next_center_y: Optional[float] = None
        for word in left_column_words:
            if word is label_word:
                continue
            box = self._word_bbox(word)
            center_y = (box["y1"] + box["y2"]) / 2.0
            if center_y < label_center_y - 2.0:
                prev_center_y = center_y
            elif center_y > label_center_y + 2.0 and next_center_y is None:
                next_center_y = center_y
                break

        top = max(0.0, (prev_center_y + label_center_y) / 2.0) if prev_center_y is not None else max(0.0, label_box["y1"] - label_height * 1.4)
        bottom = (
            min(float(img_h), (label_center_y + next_center_y) / 2.0)
            if next_center_y is not None
            else min(float(img_h), label_box["y2"] + label_height * 1.8)
        )
        if bottom <= top:
            return label_box["y1"], label_box["y2"]
        return top, bottom

    def _estimate_next_column_left(
        self,
        words: List[Dict[str, Any]],
        label_box: Dict[str, float],
        row_top: float,
        row_bottom: float,
        img_w: int,
    ) -> float:
        """寻找本行右侧下一列的起点，尽量裁成完整 cell。"""
        label_width = max(1.0, label_box["x2"] - label_box["x1"])
        threshold_x = label_box["x2"] + max(120.0, label_width * 1.3)
        best_left: Optional[float] = None
        for word in words:
            box = self._word_bbox(word)
            text_norm = self._normalize_text(word.get("text"))
            if not text_norm:
                continue
            overlap_y = min(box["y2"], row_bottom) - max(box["y1"], row_top)
            if overlap_y < max(8.0, (row_bottom - row_top) * 0.18):
                continue
            if box["x1"] <= threshold_x:
                continue
            if best_left is None or box["x1"] < best_left:
                best_left = box["x1"]
        if best_left is not None:
            return best_left
        return float(img_w) - 8.0

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

    def _extract_ordered_texts(self, words: List[Dict[str, Any]]) -> List[str]:
        ranked = []
        for word in words:
            text = str(word.get("text") or "").strip()
            if not text:
                continue
            box = self._word_bbox(word)
            ranked.append((box["y1"], box["x1"], text))
        ranked.sort()
        return [text for _, _, text in ranked]

    def _parse_processed_text_entries(self, processed_text: str) -> List[Dict[str, Any]]:
        cleaned = processed_text.strip()
        fence = chr(96) * 3
        if cleaned.startswith(fence):
            parts = cleaned.split(fence)
            if len(parts) >= 2:
                cleaned = parts[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(cleaned[start:end + 1])
        except Exception:
            return []
        return payload if isinstance(payload, list) else []

    def _save_qwen_page_debug(
        self,
        img: Image.Image,
        field_names: List[str],
        debug_rows: Dict[str, Any],
        words: List[Dict[str, Any]],
    ) -> None:
        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)
        canvas = img.copy()
        draw = ImageDraw.Draw(canvas)
        for index, fname in enumerate(field_names, start=1):
            row = debug_rows.get(fname) or {}
            label = row.get("label")
            if label:
                box = self._word_bbox(label)
                draw.rectangle((box["x1"], box["y1"], box["x2"], box["y2"]), outline="orange", width=3)
            value_bbox = row.get("value_bbox") or self._merge_word_bboxes(row.get("value_words") or [])
            if value_bbox:
                draw.rectangle(
                    (value_bbox["x1"], value_bbox["y1"], value_bbox["x2"], value_bbox["y2"]),
                    outline="green",
                    width=4,
                )
                draw.text((value_bbox["x1"], max(0, value_bbox["y1"] - 20)), f"{index}:{fname}", fill="green")
        canvas.save(f"{debug_dir}/field_page_boxes.png")

    def _get_last_page_value_words(self, fname: str) -> List[Dict[str, Any]]:
        selected_path = "/home/tdkx/workspace/tech/debug_cropped/field_page_ocr_selected.json"
        try:
            with open(selected_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return []
        selected = payload.get("selected") or {}
        row = selected.get(fname) or {}
        return list(row.get("value_words") or [])

    def _normalize_text(self, text: Any) -> str:
        value = str(text or "")
        return re.sub(r"\s+", "", value)

    def _get_llm(self):
        """获取 review 场景专用 LLM 客户端（temperature=0.7）。"""
        if self._llm_client is None:
            from src.common.llm import get_review_llm_client

            self._llm_client = get_review_llm_client()
        return self._llm_client


# 兼容旧代码
