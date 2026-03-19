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
            
            # 2. LLM 直接分析印章位置和内容（JSON 结构化输出）
            prompt = """请分析页面中所有印章的位置和内容。

【重要】只识别印章上**明确刻有**的文字，不要推测、补充或想象任何文字。

返回 JSON 格式：
{
  "stamps": [
    {"index": 1, "unit": "印章上明确有的单位名称", "location": "位置描述", "bbox": [x1,y1,x2,y2]},
    ...
  ]
}

注意：
- unit 只填写印章上**明确刻有**的文字，如果看不清或无法确认，设为 null
- bbox 为归一化坐标 (0-1)，无坐标则设为 null
- 如果未检测到印章，返回 {"stamps": []}
- 禁止推测、想象或补充任何印章上没有的文字

只输出 JSON，不要其他内容。"""

            multi_llm = MultimodalLLM(self._get_llm_client())
            result = await multi_llm.analyze_image(image_data, prompt)
            
            if not result or len(result.strip()) < 2:
                logger.warning("[StampExtractor] 未能检测到印章")
                return None
            
            # 解析 JSON 输出
            import json
            try:
                # 尝试提取 JSON（可能 LLM 输出包含在 ```json 中）
                json_str = result.strip()
                if json_str.startswith("```"):
                    json_str = json_str.split("```")[1]
                    if json_str.startswith("json"):
                        json_str = json_str[4:]
                json_str = json_str.strip()
                
                stamp_data = json.loads(json_str)
                stamps_list = stamp_data.get("stamps", [])
                
                if not stamps_list:
                    logger.warning("[StampExtractor] 未能检测到印章")
                    return {"stamps": [], "raw": result}
                
                stamps = []
                for s in stamps_list:
                    stamps.append({
                        "index": s.get("index", 0),
                        "unit": s.get("unit", ""),
                        "location": s.get("location", ""),
                        "bbox": s.get("bbox"),
                    })
                
                logger.info(f"[StampExtractor] 提取到 {len(stamps)} 个印章")
                return {"stamps": stamps, "raw": result}
                
            except json.JSONDecodeError as e:
                logger.warning(f"[StampExtractor] JSON 解析失败: {e}，原始输出: {result[:200]}")
                # 降级返回原始文本
                return {
                    "stamps": [],
                    "raw": result,
                    "error": f"JSON解析失败: {e}",
                }

        except Exception as e:
            logger.error(f"[StampExtractor] 印章提取失败: {e}")
            return None

    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_default_llm_client()
        return self._llm_client

    def _parse_stamp_result(self, text: str) -> List[Dict[str, Any]]:
        """解析结构化印章输出"""
        import re
        stamps = []
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 解析格式：序号|单位名称|位置描述|坐标
            parts = line.split('|')
            if len(parts) < 3:
                continue
            
            stamp = {
                "index": parts[0].strip(),
                "unit": parts[1].strip(),
                "location": parts[2].strip(),
                "bbox": None,
            }
            
            # 解析坐标（如果有）
            if len(parts) >= 4 and parts[3].strip() != '无':
                coord_str = parts[3].strip()
                coords = re.findall(r'([\d.]+)', coord_str)
                if len(coords) >= 4:
                    try:
                        stamp["bbox"] = {
                            "x1": float(coords[0]),
                            "y1": float(coords[1]),
                            "x2": float(coords[2]),
                            "y2": float(coords[3]),
                        }
                    except ValueError:
                        pass
            
            stamps.append(stamp)
        
        return stamps

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
