"""
文档内容提取器

OCR + LLM 混合方案：
1. OCR 提取文字 → 正则解析结构化信息
2. LLM 处理图像内容（印章、签字）
"""
import io
import os
import re
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
# PaddleOCR 3.x 在部分 CPU 环境下会走到不兼容的 PIR/oneDNN 路径，
# 这里固定使用稳定配置，避免运行时报错。
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")
os.environ.setdefault("PADDLE_PDX_USE_PIR_TRT", "False")
os.environ.setdefault("FLAGS_enable_pir_api", "0")
from paddleocr import PaddleOCR
from PIL import Image

from src.common.vision import MultimodalLLM


class ExtractedContent:
    """提取结果 - 开放式键值对"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.data: Dict[str, Any] = data or {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取字段值"""
        return self.data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """设置字段值"""
        self.data[key] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.data


class DocumentExtractor:
    """文档内容提取器
    
    OCR + LLM 混合方案：
    1. OCR 提取文字 → 正则解析结构化信息
    2. LLM 处理图像内容（印章、签字）
    """
    
    def __init__(self, llm_client: Any = None):
        self.llm = llm_client
        self._ocr = None
        self._multi_llm = None
    
    @property
    def ocr(self) -> PaddleOCR:
        """获取 OCR 实例"""
        if self._ocr is None:
            self._ocr = PaddleOCR(use_angle_cls=True, lang='ch')
        return self._ocr
    
    @property
    def multi_llm(self) -> MultimodalLLM:
        """获取多模态 LLM 实例"""
        if self._multi_llm is None:
            self._multi_llm = MultimodalLLM(self.llm)
        return self._multi_llm
    
    async def extract(
        self,
        file_data: bytes,
        document_type: str = None,
    ) -> ExtractedContent:
        """提取文档关键内容
        
        Args:
            file_data: 文件数据（PDF 或图片）
            document_type: 文档类型
            
        Returns:
            ExtractedContent: 提取结果
        """
        # 检测是否为 PDF
        if file_data[:4] == b'%PDF':
            return await self._extract_pdf(file_data, document_type)
        else:
            return await self._extract_image(file_data, document_type)
    
    async def _extract_pdf(
        self,
        file_data: bytes,
        document_type: str = None,
    ) -> ExtractedContent:
        """提取 PDF 内容"""
        try:
            doc = fitz.open(stream=file_data, filetype="pdf")
            page_count = doc.page_count
            
            all_text = []  # 所有页 OCR 文字
            all_stamps = []  # 印章（需要 LLM 识别）
            all_signatures = []  # 签字（需要 LLM 识别）
            
            # 逐页处理
            for page_num in range(page_count):
                page = doc.load_page(page_num)
                
                # 1. 渲染页面为图片（提高分辨率到 2.0 以提升 OCR 准确率）
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_data = pix.tobytes("png")
                
                # 压缩图片如果太大
                img_data = self._compress_image(img_data)
                
                # 2. OCR 提取文字
                text = await self._ocr_image(img_data)
                all_text.append(text)
                
                # 3. 用 LLM 识别印章和签字区域
                stamp_result = await self._detect_stamps_with_llm(img_data)
                if stamp_result.get("has_stamp"):
                    stamps = stamp_result.get("stamps", [])
                    for s in stamps:
                        s["page"] = page_num + 1
                    all_stamps.extend(stamps)
                
                sig_result = await self._detect_signatures_with_llm(img_data)
                if sig_result.get("has_signature"):
                    signatures = sig_result.get("signatures", [])
                    for s in signatures:
                        s["page"] = page_num + 1
                    all_signatures.extend(signatures)
            
            doc.close()
            
            # 合并所有文字
            full_text = "\n".join(all_text)
            
            # 4. 从 OCR 文字中解析结构化信息
            units = self._extract_units_from_text(full_text)
            work_units = self._extract_work_units_from_text(full_text)
            authors = self._extract_authors_from_text(full_text)
            project_name = self._extract_project_name_from_text(full_text)
            
            return ExtractedContent({
                "document_type": document_type,
                "project_name": project_name,
                "units": units,
                "work_units": work_units,
                "stamps": all_stamps,
                "signatures": all_signatures,
                "authors": authors,
                "text": full_text[:10000],  # 保留前 10000 字符
                "pages": page_count,
            })
            
        except Exception as e:
            return ExtractedContent({
                "error": str(e),
                "document_type": document_type,
            })
    
    async def _extract_image(
        self,
        image_data: bytes,
        document_type: str = None,
    ) -> ExtractedContent:
        """提取图片内容"""
        try:
            # 压缩图片
            img_data = self._compress_image(image_data)
            
            # 1. OCR 提取文字
            text = await self._ocr_image(img_data)
            
            # 2. 从文字中解析结构化信息
            units = self._extract_units_from_text(text)
            work_units = self._extract_work_units_from_text(text)
            authors = self._extract_authors_from_text(text)
            project_name = self._extract_project_name_from_text(text)
            
            # 3. LLM 识别印章
            stamp_result = await self._detect_stamps_with_llm(img_data)
            all_stamps = stamp_result.get("stamps", [])
            for s in all_stamps:
                s["page"] = 1
            
            # 4. LLM 识别签字
            sig_result = await self._detect_signatures_with_llm(img_data)
            all_signatures = sig_result.get("signatures", [])
            for s in all_signatures:
                s["page"] = 1
            
            return ExtractedContent({
                "document_type": document_type,
                "project_name": project_name,
                "units": units,
                "work_units": work_units,
                "stamps": all_stamps,
                "signatures": all_signatures,
                "authors": authors,
                "text": text,
                "pages": 1,
            })
            
        except Exception as e:
            return ExtractedContent({
                "error": str(e),
                "document_type": document_type,
            })
    
    def _compress_image(self, img_data: bytes, max_size: int = 2000000) -> bytes:
        """压缩图片到合理大小"""
        try:
            img = Image.open(io.BytesIO(img_data))
            
            # 调整大小
            max_dim = 2048
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            
            # 压缩
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85, optimize=True)
            return buf.getvalue()
        except Exception:
            return img_data
    
    async def _ocr_image(self, image_data: bytes) -> str:
        """OCR 识别文字"""
        import numpy as np
        
        try:
            # PaddleOCR 需要 numpy 数组
            img = Image.open(io.BytesIO(image_data))
            img_array = np.array(img)
            
            # PaddleOCR 3.x 推荐使用 predict，返回 OCRResult
            result = self.ocr.predict(img_array)

            # 提取文字
            texts = []
            if result:
                first = list(result)[0]
                rec_texts = first.get("rec_texts", [])
                texts.extend([t for t in rec_texts if isinstance(t, str) and t.strip()])
            
            return "\n".join(texts)
        except Exception as e:
            return f"[OCR失败: {e}]"
    
    async def _detect_stamps_with_llm(self, image_data: bytes) -> Dict[str, Any]:
        """用 LLM 识别印章"""
        if not self.llm:
            return {"has_stamp": False, "stamps": []}
        
        try:
            prompt = """这是一张科技项目文档的图片。
请仔细查找是否存在红色的印章/公章？
如果存在，请读取印章上的单位名称。

直接返回 JSON 格式：
{"has_stamp": true/false, "stamps": [{"unit": "印章上的单位名称"}]}
如果没有印章，返回 {"has_stamp": false, "stamps": []}"""
            
            result = await self.multi_llm.analyze_image(image_data, prompt)
            
            # 解析 JSON
            import json
            import re
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data
            
            return {"has_stamp": False, "stamps": []}
        except Exception:
            return {"has_stamp": False, "stamps": []}
    
    async def _detect_signatures_with_llm(self, image_data: bytes) -> Dict[str, Any]:
        """用 LLM 识别签字"""
        if not self.llm:
            return {"has_signature": False, "signatures": []}
        
        try:
            prompt = """这是一张科技项目文档的图片。
请仔细查找是否存在手写签名/签字？

直接返回 JSON 格式：
{"has_signature": true/false, "signatures": [{"name": "签字人姓名"}]}
如果没有签名，返回 {"has_signature": false, "signatures": []}"""
            
            result = await self.multi_llm.analyze_image(image_data, prompt)
            
            # 解析 JSON
            import json
            import re
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data
            
            return {"has_signature": False, "signatures": []}
        except Exception:
            return {"has_signature": False, "signatures": []}
    
    # ========== 正则解析方法 ==========
    
    def _extract_units_from_text(self, text: str) -> List[str]:
        """从文字中提取单位名称"""
        units = []
        
        # 模式：查找"单位"后面的内容（支持跨行）
        patterns = [
            r'单位[：:\s]*\n?\s*([^\n]{2,30})',
            r'完成单位[：:\s]*\n?\s*([^\n]{2,30})',
            r'盖章单位[：:\s]*\n?\s*([^\n]{2,30})',
            r'所属单位[：:\s]*\n?\s*([^\n]{2,30})',
            r'工作单位[：:\s]*\n?\s*([^\n]{2,30})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            units.extend(matches)
        
        # 去重清理
        units = list(set([u.strip() for u in units if u.strip() and len(u.strip()) > 1]))
        return units[:20]
    
    def _extract_work_units_from_text(self, text: str) -> List[str]:
        """提取工作单位"""
        work_units = []
        
        # 模式：查找"工作单位"（支持跨行）
        patterns = [
            r'工作单位[：:\s]*\n?\s*([^\n]{2,50})',
            r'主要完成人.*?工作单位[：:\s]*\n?\s*([^\n]{2,50})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            work_units.extend(matches)
        
        return list(set([u.strip() for u in work_units if u.strip() and len(u.strip()) > 1]))
    
    def _extract_authors_from_text(self, text: str) -> List[str]:
        """提取作者/完成人"""
        authors = []
        
        # 模式：查找"完成人"、"作者"（支持跨行）
        patterns = [
            r'完成人[：:\s]*\n?\s*([^\n]{2,30})',
            r'主要完成人[：:\s]*\n?\s*([^\n]{2,30})',
            r'作者[：:\s]*\n?\s*([^\n]{2,30})',
            r'姓名[：:\s]*\n?\s*([^\n]{2,30})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            authors.extend(matches)
        
        return list(set([a.strip() for a in authors if a.strip() and len(a.strip()) > 1]))
    
    def _extract_project_name_from_text(self, text: str) -> str:
        """提取项目名称"""
        # 模式：查找"项目名称"
        patterns = [
            r'项目名称[：:]\s*([^\n]{2,50})',
            r'课题名称[：:]\s*([^\n]{2,50})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        
        return ""
    
    async def extract_simple(
        self,
        file_data: bytes,
        fields: list[str],
    ) -> Dict[str, Any]:
        """简单提取 - 按需获取特定字段"""
        result = await self.extract(file_data)
        return {field: result.get(field) for field in fields}
