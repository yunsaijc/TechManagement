"""签字提取器（Layer 4）

职责：从文档中提取签字内容
流程：LLM 直接分析图片，描述签字位置（不需要 OCR）
"""
import io
import logging
import os
from typing import Dict, List, Optional, Any

from PIL import Image

from src.common.llm import get_default_llm_client
from src.common.vision.multimodal import MultimodalLLM

logger = logging.getLogger(__name__)


class SignatureExtractor:
    """签字提取器 - LLM 直接分析，不需要 OCR"""

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
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)
            
            # 2. LLM 直接分析签字位置
            prompt = """请描述页面中所有签字/签名的位置。
只返回描述，不要其他内容。"""

            multi_llm = MultimodalLLM(self._get_llm_client())
            result = await multi_llm.analyze_image(image_data, prompt)
            
            if not result or len(result.strip()) < 2:
                logger.warning("[SignatureExtractor] 未能检测到签字")
                return None
            
            # 解析 LLM 返回的描述，尝试提取坐标信息
            coords = self._parse_signature_coords(result)
            
            if not coords:
                # 没有坐标，至少有描述也算成功
                return {
                    "signatures": [{
                        "text": result,
                        "bbox": None,
                    }]
                }
            
            logger.info(f"[SignatureExtractor] 提取到 {len(coords)} 个签字区域")
            return {"signatures": [{"text": result, "bbox": coords[0]}]}

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
        import re
        coords = []
        # 尝试匹配坐标模式: x1,y1,x2,y2 或 x,y
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
