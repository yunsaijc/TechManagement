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

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from src.common.llm import llm_config
from src.common.vision.multimodal import MultimodalLLM

logger = logging.getLogger(__name__)


class FieldExtractor:
    """字段提取器 - 先定位 bbox 再 OCR 转写"""

    _KNOWN_HEADER_WORDS = {
        "姓名",
        "性别",
        "排名",
        "出生年月",
        "出生地",
        "民族",
        "身份证号",
        "归国人员",
        "国籍",
        "文化程度",
        "毕业学校",
        "毕业时间",
        "技术职称",
        "专业专长",
        "最高学位",
        "电子信箱",
        "移动电话",
        "办公电话",
        "通讯地址",
        "邮政编码",
        "工作单位",
        "单位性质",
        "注册地",
        "二级单位",
        "党派",
        "行政职务",
        "完成单位",
        "曾获科学技术奖励情况",
        "参加本项目起止时间",
    }

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
                value_words = self._select_field_value_words(words, label_word, field_names, fname)
                value_bbox = self._build_field_value_bbox(
                    words=words,
                    label_word=label_word,
                    value_words=value_words,
                    field_names=field_names,
                    field_name=fname,
                    image_size=(img_w, img_h),
                    page_image=img,
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
                self._normalize_field_bbox(raw_bbox, img_w, img_h),
                field_name=fname,
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
            cropped_img = self._trim_left_table_boundary(cropped_img, fname)
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
        field_name: str = "",
    ) -> tuple[float, float, float, float]:
        """对齐 2026-03-20 风格：仅做轻量扩边。"""
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        field_key = self._normalize_field_key(field_name)
        no_left_expand_fields = {"姓名", "工作单位", "完成单位", "单位名称", "企业名称", "法定代表人"}
        margin_left = 0.0 if field_key in no_left_expand_fields else width * 0.04
        margin_right = width * 0.04
        margin_top = height * 0.10
        no_bottom_expand_fields = {"工作单位", "完成单位", "单位名称", "企业名称"}
        margin_bottom = 0.0 if field_key in no_bottom_expand_fields else height * 0.10
        x1 = max(0.0, x1 - margin_left)
        y1 = max(0.0, y1 - margin_top)
        x2 = min(1.0, x2 + margin_right)
        y2 = min(1.0, y2 + margin_bottom)
        return x1, y1, x2, y2

    def _prepare_crop_for_ocr(self, cropped_img: Image.Image) -> Image.Image:
        """字段 OCR 预处理：柔和增强，避免硬二值化吃掉笔画。"""
        cleaned = ImageOps.grayscale(cropped_img)
        cleaned = ImageOps.autocontrast(cleaned, cutoff=1)
        cleaned = ImageEnhance.Contrast(cleaned).enhance(1.35)
        cleaned = cleaned.filter(ImageFilter.SHARPEN).convert("RGB")
        scale = max(1, min(4, math.ceil(72 / max(1, cropped_img.height))))
        prepared = cleaned.resize(
            (max(1, cleaned.width * scale), max(1, cleaned.height * scale)),
            Image.LANCZOS,
        )
        padding = int(min(prepared.width, prepared.height) * 0.15)
        return ImageOps.expand(prepared, border=padding, fill="white")

    def _trim_left_table_boundary(self, cropped_img: Image.Image, field_name: str) -> Image.Image:
        """按表格竖线裁掉字段值左侧的标签残留。"""
        field_key = self._normalize_field_key(field_name)
        if field_key not in {"姓名", "工作单位", "完成单位", "单位名称", "企业名称", "法定代表人"}:
            return cropped_img

        gray = ImageOps.grayscale(cropped_img)
        width, height = gray.size
        if width < 20 or height < 20:
            return cropped_img

        pixels = gray.load()
        search_right = max(1, int(width * 0.55))
        dark_threshold = 120
        min_dark = max(8, int(height * 0.70))
        top_band = range(0, max(1, int(height * 0.18)))
        bottom_band = range(max(0, int(height * 0.82)), height)
        candidates: List[int] = []
        for x in range(search_right):
            dark_count = 0
            for y in range(height):
                if pixels[x, y] < dark_threshold:
                    dark_count += 1
            touches_top = any(pixels[x, y] < dark_threshold for y in top_band)
            touches_bottom = any(pixels[x, y] < dark_threshold for y in bottom_band)
            if dark_count >= min_dark and touches_top and touches_bottom:
                candidates.append(x)

        if not candidates:
            return cropped_img

        # 连续竖线取最右侧边缘，再向右留一点白边，避免把线送进 OCR。
        groups: List[List[int]] = []
        current: List[int] = []
        for x in candidates:
            if not current or x <= current[-1] + 1:
                current.append(x)
            else:
                groups.append(current)
                current = [x]
        if current:
            groups.append(current)

        line_group = max(groups, key=lambda item: len(item))
        cut_x = min(width - 1, line_group[-1] + 2)
        if cut_x <= 0 or width - cut_x < 12:
            return cropped_img
        return cropped_img.crop((cut_x, 0, width, height))

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
        target = self._normalize_field_key(field_name)
        exact = [word for word in words if self._normalize_field_key(word.get("text")) == target]
        if exact:
            return sorted(exact, key=lambda item: self._word_bbox(item)["x1"])[0]
        fuzzy = [
            word
            for word in words
            if self._field_key_has_embedded_label(self._normalize_field_key(word.get("text")), target)
        ]
        if fuzzy:
            return sorted(fuzzy, key=lambda item: self._word_bbox(item)["x1"])[0]
        return None

    def _select_field_value_words(
        self,
        words: List[Dict[str, Any]],
        label_word: Optional[Dict[str, Any]],
        field_names: List[str],
        field_name: str = "",
    ) -> List[Dict[str, Any]]:
        if not label_word:
            return []
        embedded = self._split_embedded_field_value(label_word, field_name)
        if embedded:
            return [embedded]
        label_box = self._word_bbox(label_word)
        label_center_y = (label_box["y1"] + label_box["y2"]) / 2.0
        label_height = max(1.0, label_box["y2"] - label_box["y1"])
        blocked = {self._normalize_field_key(item) for item in field_names}
        blocked.update(self._normalize_field_key(item) for item in self._KNOWN_HEADER_WORDS)
        row_top, row_bottom = self._estimate_row_band(words, label_word, 10**9)
        right_boundary = self._estimate_next_column_left(words, label_box, row_top, row_bottom, 10**9)
        label_width = max(1.0, label_box["x2"] - label_box["x1"])
        if self._normalize_field_key(field_name) == "姓名" and right_boundary > label_box["x2"] + 10000.0:
            right_boundary = label_box["x2"] + max(220.0, label_width * 2.4)
        candidates: List[Dict[str, Any]] = []
        for word in words:
            if word is label_word:
                continue
            text_norm = self._normalize_field_key(word.get("text"))
            if not text_norm or text_norm in blocked:
                continue
            if self._looks_like_header_value(field_name, text_norm):
                continue
            box = self._word_bbox(word)
            center_y = (box["y1"] + box["y2"]) / 2.0
            if box["x1"] < label_box["x2"] - 8:
                continue
            if abs(center_y - label_center_y) > max(24.0, label_height * 1.2):
                continue
            if box["x1"] >= right_boundary - 6.0:
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
        field_name: str,
        image_size: tuple[int, int],
        page_image: Optional[Image.Image] = None,
    ) -> Optional[Dict[str, float]]:
        """优先按整格推断字段值区域，覆盖多行单元格；失败时回退到 value words bbox。"""
        if not label_word:
            return self._merge_word_bboxes(value_words)

        label_box = self._word_bbox(label_word)
        label_height = max(1.0, label_box["y2"] - label_box["y1"])
        merged_value_bbox = self._merge_word_bboxes(value_words)
        field_key = self._normalize_field_key(field_name)
        grid_cell_fields = {"姓名", "工作单位", "完成单位", "单位名称", "企业名称"}
        if field_key in grid_cell_fields:
            table_cell = self._find_value_table_cell(
                image=page_image,
                label_box=label_box,
                image_size=image_size,
            )
            if table_cell is not None:
                left, top, right, bottom = table_cell
                return {"x1": left, "y1": top, "x2": right, "y2": bottom}
        if any(word.get("__embedded_value") for word in value_words):
            pad_x = max(8.0, (merged_value_bbox["x2"] - merged_value_bbox["x1"]) * 0.08)
            pad_y = max(8.0, (merged_value_bbox["y2"] - merged_value_bbox["y1"]) * 0.18)
            return {
                "x1": max(0.0, merged_value_bbox["x1"] - pad_x),
                "y1": max(0.0, merged_value_bbox["y1"] - pad_y),
                "x2": min(float(image_size[0]), merged_value_bbox["x2"] + pad_x),
                "y2": min(float(image_size[1]), merged_value_bbox["y2"] + pad_y),
            }
        img_w, img_h = image_size
        row_top, row_bottom = self._estimate_row_band(words, label_word, img_h)
        right_boundary = self._estimate_next_column_left(words, label_box, row_top, row_bottom, img_w)

        left = max(label_box["x2"] + 4.0, 0.0)
        right = min(right_boundary - 6.0, float(img_w))
        top = max(row_top + 2.0, 0.0)
        bottom = min(row_bottom - 2.0, float(img_h))

        full_cell_fields = {"工作单位", "完成单位", "单位名称", "企业名称"}
        if field_key in full_cell_fields and right - left >= 12.0 and bottom - top >= 12.0:
            return {"x1": left, "y1": top, "x2": right, "y2": bottom}

        if not merged_value_bbox:
            return None

        if merged_value_bbox:
            value_height = max(1.0, merged_value_bbox["y2"] - merged_value_bbox["y1"])
            no_left_pad_fields = {"姓名", "工作单位", "完成单位", "单位名称", "企业名称", "法定代表人"}
            value_left_pad = 0.0 if field_key in no_left_pad_fields else 8.0
            left = max(left, merged_value_bbox["x1"] - value_left_pad)
            if field_key == "姓名":
                left = max(left, label_box["x2"] + max(24.0, (label_box["x2"] - label_box["x1"]) * 0.22))
            right = min(right, merged_value_bbox["x2"] + max(28.0, value_height * 1.2))
            top = max(top, min(top, max(0.0, merged_value_bbox["y1"] - max(12.0, label_height * 0.35))))
            bottom = min(bottom, merged_value_bbox["y2"] + max(18.0, value_height * 1.1))

        if right - left >= 12.0 and bottom - top >= 12.0:
            return {"x1": left, "y1": top, "x2": right, "y2": bottom}
        return merged_value_bbox

    def _find_next_horizontal_table_line(
        self,
        image: Optional[Image.Image],
        left: float,
        right: float,
        start_y: float,
        stop_y: float,
    ) -> Optional[float]:
        """在字段值下方找最近表格横线，用真实单元格边界收住下边界。"""
        if image is None:
            return None

        width, height = image.size
        x1 = max(0, int(left))
        x2 = min(width, int(right))
        y1 = max(0, int(start_y))
        y2 = min(height, int(stop_y))
        if x2 - x1 < 40 or y2 - y1 < 4:
            return None

        gray = ImageOps.grayscale(image)
        pixels = gray.load()
        span = max(1, x2 - x1)
        # 表格线在扫描/拍照件里常是浅灰色；用较宽松的灰度阈值，
        # 但要求横向覆盖足够长，避免把普通文字笔画当作横线。
        min_dark = max(32, int(span * 0.42))
        candidate_rows: List[int] = []
        for y in range(y1, y2):
            dark_count = 0
            for x in range(x1, x2):
                if pixels[x, y] < 190:
                    dark_count += 1
            if dark_count >= min_dark:
                candidate_rows.append(y)

        if not candidate_rows:
            return None

        groups: List[List[int]] = []
        current: List[int] = []
        for y in candidate_rows:
            if not current or y <= current[-1] + 1:
                current.append(y)
            else:
                groups.append(current)
                current = [y]
        if current:
            groups.append(current)

        # 取最靠近字段值的横线组。组中心比单点稳定，避免粗线/阴影偏移。
        first = groups[0]
        return (first[0] + first[-1]) / 2.0

    def _find_value_table_cell(
        self,
        image: Optional[Image.Image],
        label_box: Dict[str, float],
        image_size: tuple[int, int],
    ) -> Optional[tuple[float, float, float, float]]:
        """Find the real value cell to the right of a label using table grid lines."""
        if image is None:
            return None

        img_w, img_h = image_size
        width, height = image.size
        gray = np.array(ImageOps.grayscale(image))
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(50, min(120, int(width * 0.04))), 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(35, min(90, int(height * 0.025)))))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)

        row_scan_left = max(0, int(label_box["x1"] - 24.0))
        row_scan_right = min(width, int(max(label_box["x2"] + 360.0, width * 0.55)))
        if row_scan_right - row_scan_left < 80:
            return None

        row_centers = self._line_centers_from_projection(
            (horizontal[:, row_scan_left:row_scan_right] > 0).sum(axis=1),
            threshold=max(45, int((row_scan_right - row_scan_left) * 0.45)),
        )
        label_center_y = (label_box["y1"] + label_box["y2"]) / 2.0
        top_candidates = [center for center in row_centers if center < label_center_y - 4.0]
        bottom_candidates = [center for center in row_centers if center > label_center_y + 4.0]
        if not top_candidates or not bottom_candidates:
            return None

        top = max(top_candidates) + 2.0
        bottom = min(bottom_candidates) - 2.0
        if bottom - top < 12.0:
            return None

        y1 = max(0, int(top))
        y2 = min(height, int(bottom))
        col_centers = self._line_centers_from_projection(
            (vertical[y1:y2, :] > 0).sum(axis=0),
            threshold=max(12, int((y2 - y1) * 0.45)),
        )
        if len(col_centers) < 2:
            return None

        label_center_x = (label_box["x1"] + label_box["x2"]) / 2.0
        value_left_candidates = [center for center in col_centers if center > label_center_x + 4.0]
        if not value_left_candidates:
            return None
        left_line = min(value_left_candidates)
        right_candidates = [center for center in col_centers if center > left_line + 24.0]
        if not right_candidates:
            return None
        right_line = min(right_candidates)

        left = min(float(img_w), left_line + 3.0)
        right = max(left + 12.0, right_line - 3.0)
        return left, top, min(float(img_w), right), min(float(img_h), bottom)

    def _line_centers_from_projection(self, counts: np.ndarray, threshold: int) -> List[float]:
        values = np.where(counts >= threshold)[0]
        if values.size == 0:
            return []
        groups: List[List[int]] = []
        current: List[int] = []
        for value in [int(item) for item in values.tolist()]:
            if not current or value <= current[-1] + 2:
                current.append(value)
            else:
                groups.append(current)
                current = [value]
        if current:
            groups.append(current)
        return [float(group[0] + group[-1]) / 2.0 for group in groups]

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
        label_key = self._normalize_field_key(label_word.get("text"))
        for word in words:
            box = self._word_bbox(word)
            center_x = (box["x1"] + box["x2"]) / 2.0
            if center_x > label_box["x2"] + 40.0:
                continue
            if box["x1"] > label_box["x1"] + 80.0:
                continue
            text_norm = self._normalize_field_key(word.get("text"))
            if not text_norm:
                continue
            if text_norm not in {label_key, *[self._normalize_field_key(item) for item in self._KNOWN_HEADER_WORDS]}:
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

        top = max(0.0, (prev_center_y + label_center_y) / 2.0) if prev_center_y is not None else max(0.0, label_box["y1"] - label_height * 0.25)
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
            text_norm = self._normalize_field_key(word.get("text"))
            if not text_norm:
                continue
            if not self._contains_known_header_key(text_norm):
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

    def _normalize_field_key(self, text: Any) -> str:
        value = self._normalize_text(text)
        value = re.sub(r"[：:()（）/\\|,，.。·\-_\[\]【】]+", "", value)
        return value

    def _field_key_has_embedded_label(self, text_norm: str, target: str) -> bool:
        """仅接受字段名在开头的合并块，避免标题中包含字段名时误命中。"""
        if not text_norm or not target:
            return False
        return text_norm.startswith(target) and len(text_norm) > len(target)

    def _contains_known_header_key(self, text_norm: str) -> bool:
        """识别被 OCR 合并/截断的表头，用于判断下一列边界。"""
        if not text_norm:
            return False
        header_keys = {self._normalize_field_key(item) for item in self._KNOWN_HEADER_WORDS}
        if text_norm in header_keys:
            return True
        return any(len(key) >= 3 and key in text_norm for key in header_keys)

    def _split_embedded_field_value(self, word: Dict[str, Any], field_name: str) -> Optional[Dict[str, Any]]:
        """把 Qwen OCR 合并出的“字段名+字段值”拆成 value word。

        例如同一个 OCR word 返回“姓名陈树林”，其 bbox 覆盖字段名和值。
        这里按字符占比切出字段值 bbox，作为后续 crop 的明确锚点。
        """
        target = self._normalize_field_key(field_name)
        raw_text = self._normalize_text(word.get("text"))
        text_norm = self._normalize_field_key(raw_text)
        if not self._field_key_has_embedded_label(text_norm, target):
            return None

        value_norm = text_norm[len(target):].strip()
        if self._looks_like_header_value(field_name, value_norm):
            return None

        box = self._word_bbox(word)
        width = max(1.0, box["x2"] - box["x1"])
        split_ratio = min(0.85, max(0.15, len(target) / max(1, len(text_norm))))
        value_x1 = box["x1"] + width * split_ratio
        value_word = dict(word)
        value_word["text"] = value_norm
        value_word["__embedded_value"] = True
        value_word["location"] = [
            value_x1,
            box["y1"],
            box["x2"],
            box["y1"],
            box["x2"],
            box["y2"],
            value_x1,
            box["y2"],
        ]
        value_word.pop("rotate_rect", None)
        return value_word

    def _looks_like_header_value(self, field_name: str, text_norm: str) -> bool:
        if not text_norm:
            return True
        header_keys = {self._normalize_field_key(item) for item in self._KNOWN_HEADER_WORDS}
        if text_norm in header_keys:
            return True
        field_key = self._normalize_field_key(field_name)
        if field_key == "姓名":
            if len(text_norm) < 2 or len(text_norm) > 8:
                return True
            if re.search(r"[0-9A-Za-z@]", text_norm):
                return True
        return False

    def _get_llm(self):
        """获取 review 场景专用 LLM 客户端（temperature=0.7）。"""
        if self._llm_client is None:
            from src.common.llm import get_review_llm_client

            self._llm_client = get_review_llm_client()
        return self._llm_client


# 兼容旧代码
