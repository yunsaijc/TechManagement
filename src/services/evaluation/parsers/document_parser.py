"""
文档解析器

负责解析项目申报书正文内容，提取各章节文本。
"""
import re
from typing import Any, Dict, List, Optional

from src.common.file_handler import get_parser


class DocumentParser:
    """文档解析器
    
    负责：
    1. 解析项目申报书（Word/PDF）
    2. 提取章节结构
    3. 按章节组织内容
    """
    
    # 常见章节标题模式
    SECTION_PATTERNS = [
        # 数字编号
        r'^[一二三四五六七八九十]+[、\.．\s]',
        r'^\d+[、\.．\s]',
        r'^\d+\.\d+[、\.．\s]',
        # 中文章节关键词
        r'^(技术路线|研究方案|实施方案|创新点|研究内容|项目团队|人员分工|预期成果|考核指标|预期效益|社会效益|经济效益|风险分析|风险控制|进度安排|实施计划|政策依据|经费预算|伦理审查|预算说明|工作计划|研究计划)[：:\s]',
    ]
    
    def __init__(self):
        """初始化文档解析器"""
        pass
    
    async def parse(self, file_path: str) -> Dict[str, Any]:
        """解析文档
        
        Args:
            file_path: 文档路径
            
        Returns:
            Dict[str, Any]: 解析结果，包含章节内容
        """
        # 获取文档文本
        text = await self._extract_text(file_path)
        
        # 提取章节
        sections = self._extract_sections(text)
        
        return sections
    
    async def _extract_text(self, file_path: str) -> str:
        """提取文档文本
        
        Args:
            file_path: 文档路径
            
        Returns:
            str: 文档文本
        """
        # 判断文件类型
        if file_path.endswith('.docx'):
            return await self._extract_docx_text(file_path)
        elif file_path.endswith('.pdf'):
            return await self._extract_pdf_text(file_path)
        else:
            raise ValueError(f"不支持的文件类型: {file_path}")
    
    async def _extract_docx_text(self, file_path: str) -> str:
        """提取Word文档文本"""
        import docx
        
        doc = docx.Document(file_path)
        
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        
        return '\n'.join(paragraphs)
    
    async def _extract_pdf_text(self, file_path: str) -> str:
        """提取PDF文档文本"""
        import fitz  # PyMuPDF
        
        doc = fitz.open(file_path)
        
        pages = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(text.strip())
        
        doc.close()
        return '\n'.join(pages)
    
    def _extract_sections(self, text: str) -> Dict[str, Any]:
        """从文本中提取章节
        
        Args:
            text: 文档文本
            
        Returns:
            Dict[str, Any]: 章节字典，key为章节名，value为内容
        """
        sections = {}
        lines = text.split('\n')
        
        current_section = "概述"
        current_content = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 检查是否是章节标题
            is_section = self._is_section_title(line)
            
            if is_section:
                # 保存上一个章节
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                
                # 开始新章节
                current_section = self._normalize_section_name(line)
                current_content = []
            else:
                current_content.append(line)
        
        # 保存最后一个章节
        if current_content:
            sections[current_section] = '\n'.join(current_content)
        
        return sections
    
    def _is_section_title(self, line: str) -> bool:
        """判断是否是章节标题
        
        Args:
            line: 文本行
            
        Returns:
            bool: 是否是章节标题
        """
        for pattern in self.SECTION_PATTERNS:
            if re.match(pattern, line):
                return True
        return False
    
    def _normalize_section_name(self, title: str) -> str:
        """规范化章节名称
        
        Args:
            title: 原始标题
            
        Returns:
            str: 规范化后的章节名
        """
        # 移除编号
        name = re.sub(r'^[一二三四五六七八九十]+[、\.．\s]*', '', title)
        name = re.sub(r'^\d+(\.\d+)*[、\.．\s]*', '', name)
        
        # 移除标点
        name = re.sub(r'[：:\s]+$', '', name)
        
        return name.strip()