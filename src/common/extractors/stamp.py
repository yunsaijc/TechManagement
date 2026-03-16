"""印章提取器（Layer 4）

职责：从文档中提取印章内容
流程：LLM 直接分析图片，描述印章位置和内容（不需要 OCR）
"""
import io
import logging
import os
from typing import Dict, List, Optional, Any

from PIL import Image

from src.common.llm import get_default_llm_client
from src.common.vision import MultimodalLLM

logger = logging.getLogger(__name__)


class StampExtractor:
    """印章提取器 - LLM 直接分析，不需要 OCR"""

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
            印章字典 {"stamps": [{"text": "xxx", "bbox": {...}]}, ...]，未提取到返回 None
        """
        try:
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)
            
            # 2. LLM 直接分析印章位置和内容
            prompt = """请描述页面中所有印章的位置和内容。
只返回描述，不要其他内容。"""

            multi_llm = MultimodalLLM(self._get_llm_client())
            result = await multi_llm.analyze_image(image_data, prompt)
            
            if not result or len(result.strip()) < 2:
                logger.warning("[StampExtractor] 未能检测到印章")
                return None
            
            # 解析 LLM 返回的描述，尝试提取坐标信息
            coords = self._parse_stamp_coords(result)
            
            if not coords:
                # 没有坐标，至少有描述也算成功
                return {
                    "stamps": [{
                        "text": result,
                        "bbox": None,
                    }]
                }
            
            logger.info(f"[StampExtractor] 提取到 {len(coords)} 个印章区域")
            return {"stamps": [{"text": result, "bbox": coords[0]}]}

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
