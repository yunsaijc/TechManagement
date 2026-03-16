"""盖章提取器（Layer 4）

职责：从文档中提取印章内容
流程：Step1 LLM 定位印章区域 bbox → Step2 裁剪 → Step3 OCR 转写印章文字
"""
import io
import logging
import os
import re
from typing import Dict, List, Optional, Any

from PIL import Image
import numpy as np

from src.common.llm import get_default_llm_client
from src.common.vision import MultimodalLLM

logger = logging.getLogger(__name__)


class StampExtractor:
    """盖章提取器 - 先定位 bbox 再 OCR 转写"""

    def __init__(self):
        self._paddle_ocr = None
        self._llm_client = None

    async def extract(
        self,
        file_data: bytes,
        min_regions: int = 1,
        confidence: float = 0.7,
    ) -> Optional[Dict[str, Any]]:
        """
        提取印章内容

        Args:
            file_data: PDF/图片 bytes
            min_regions: 最少印章区域数
            confidence: 最低置信度

        Returns:
            印章字典 {"stamps": [{"text": "xxx", "bbox": {...}, "confidence": 0.9}, ...]}，未提取到返回 None
        """
        try:
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size

            # 2. Step1: LLM 定位印章区域 (bbox)
            coords = await self._locate_stamps(image_data)
            if not coords:
                logger.warning("[StampExtractor] 未能定位到印章区域")
                return None

            # 3. Step2: 裁剪 + OCR 转写
            stamps = []
            for bbox in coords:
                text = await self._extract_stamp_text(img, img_w, img_h, bbox)
                stamps.append({
                    "text": text or "",
                    "bbox": bbox,
                    "confidence": confidence,
                })

            if len(stamps) < min_regions:
                logger.warning(f"[StampExtractor] 印章区域不足: {len(stamps)} < {min_regions}")
                return None

            logger.info(f"[StampExtractor] 提取到 {len(stamps)} 个印章")
            return {"stamps": stamps}

        except Exception as e:
            logger.error(f"[StampExtractor] 印章提取失败: {e}")
            return None

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
        except Exception as e:
            logger.warning(f"[StampExtractor] PDF 转图片失败: {e}")
            return file_data

    async def _locate_stamps(self, image_data: bytes) -> Optional[List[Dict]]:
        """Step1: LLM 定位印章区域"""
        llm = self._get_llm()
        multi_llm = MultimodalLLM(llm)

        prompt = """请在图片中找出所有印章/公章的位置。

返回格式（每行一个印章区域）：
x1,y1,x2,y2 （归一化坐标0-1）

只返回坐标，不要其他内容。"""

        try:
            result = await multi_llm.agenerate([
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                {"type": "text", "text": prompt}
            ])
            result_text = result.content if hasattr(result, 'content') else str(result)

            # 解析坐标
            coords = []
            for line in result_text.strip().split('\n'):
                match = re.findall(r'([\d.]+),([\d.]+),([\d.]+),([\d.]+)', line)
                for m in match:
                    coords.append({
                        "x1": float(m[0]),
                        "y1": float(m[1]),
                        "x2": float(m[2]),
                        "y2": float(m[3]),
                    })

            logger.info(f"[StampExtractor] 定位到 {len(coords)} 个印章区域")
            return coords if coords else None
        except Exception as e:
            logger.error(f"[StampExtractor] Step1 印章区域定位失败: {e}")
            return None

    async def _extract_stamp_text(
        self,
        img: Image.Image,
        img_w: int,
        img_h: int,
        bbox: Dict,
    ) -> Optional[str]:
        """Step2: 裁剪 + OCR 转写"""
        import logging as _logging
        _logging.getLogger("ppocr").setLevel(_logging.ERROR)

        from paddleocr import PaddleOCR

        if self._paddle_ocr is None:
            self._paddle_ocr = PaddleOCR(use_angle_cls=True, lang='ch')

        x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

        # 扩展边距
        margin = 0.01
        x1, y1 = max(0, x1 - margin), max(0, y1 - margin)
        x2, y2 = min(1, x2 + margin), min(1, y2 + margin)

        # 裁剪坐标
        left = int(x1 * img_w)
        top = int(y1 * img_h)
        right = int(x2 * img_w)
        bottom = int(y2 * img_h)

        # 裁剪
        cropped_img = img.crop((left, top, right, bottom))
        
        # 放大
        scale = max(3, int(200 / cropped_img.width)) if cropped_img.width > 0 else 3
        cropped_img = cropped_img.resize(
            (cropped_img.width * scale, cropped_img.height * scale), Image.LANCZOS
        )

        # OCR 转写
        try:
            cropped_np = np.array(cropped_img)
            ocr_result = self._paddle_ocr.ocr(cropped_np)
            if ocr_result and ocr_result[0]:
                # 可能有多个文字，拼接
                texts = []
                for line in ocr_result[0]:
                    if isinstance(line, list):
                        for item in line:
                            rec_texts = item.get('rec_texts', [])
                            if rec_texts:
                                texts.append(rec_texts[0])
                if texts:
                    return "".join(texts)
        except Exception as e:
            logger.warning(f"[StampExtractor] OCR 识别失败: {e}")

        return None

    def _get_llm(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_default_llm_client()
        return self._llm_client
