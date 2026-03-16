"""签字提取器（Layer 4）

职责：从文档中提取签字内容
流程：Step1 LLM 定位签字区域 bbox → Step2 裁剪 → Step3 OCR 转写
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


class SignatureExtractor:
    """签字提取器 - 先定位 bbox 再 OCR 转写"""

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
        提取签字内容

        Args:
            file_data: PDF/图片 bytes
            min_regions: 最少签字区域数
            confidence: 最低置信度

        Returns:
            签字字典 {"signatures": [{"text": "xxx", "bbox": {...}, "confidence": 0.9}, ...]}，未提取到返回 None
        """
        try:
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size

            # 2. Step1: LLM 定位签字区域 (bbox)
            coords = await self._locate_signatures(image_data)
            if not coords:
                logger.warning("[SignatureExtractor] 未能定位到签字区域")
                return None

            # 3. Step2: 裁剪 + OCR 转写
            signatures = []
            for bbox in coords:
                text = await self._extract_signature_text(img, img_w, img_h, bbox)
                if text:
                    signatures.append({
                        "text": text,
                        "bbox": bbox,
                        "confidence": confidence,
                    })

            if len(signatures) < min_regions:
                logger.warning(f"[SignatureExtractor] 签字区域不足: {len(signatures)} < {min_regions}")
                return None

            logger.info(f"[SignatureExtractor] 提取到 {len(signatures)} 个签字")
            return {"signatures": signatures}

        except Exception as e:
            logger.error(f"[SignatureExtractor] 签字提取失败: {e}")
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
            logger.warning(f"[SignatureExtractor] PDF 转图片失败: {e}")
            return file_data

    async def _locate_signatures(self, image_data: bytes) -> Optional[List[Dict]]:
        """Step1: LLM 定位签字区域"""
        llm = self._get_llm()
        multi_llm = MultimodalLLM(llm)

        prompt = """请在图片中找出所有签字/签名的位置。

返回格式（每行一个签字区域）：
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
                # 匹配各种格式: x1,y1,x2,y2 或 (x1, y1, x2, y2) 等
                match = re.findall(r'([\d.]+),([\d.]+),([\d.]+),([\d.]+)', line)
                for m in match:
                    coords.append({
                        "x1": float(m[0]),
                        "y1": float(m[1]),
                        "x2": float(m[2]),
                        "y2": float(m[3]),
                    })

            logger.info(f"[SignatureExtractor] 定位到 {len(coords)} 个签字区域")
            return coords if coords else None
        except Exception as e:
            logger.error(f"[SignatureExtractor] Step1 签字区域定位失败: {e}")
            return None

    async def _extract_signature_text(
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
                first_result = ocr_result[0][0] if isinstance(ocr_result[0], list) else ocr_result[0]
                rec_texts = first_result.get('rec_texts', [])
                if rec_texts:
                    return rec_texts[0]
        except Exception as e:
            logger.warning(f"[SignatureExtractor] OCR 识别失败: {e}")

        return None

    def _get_llm(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_default_llm_client()
        return self._llm_client
