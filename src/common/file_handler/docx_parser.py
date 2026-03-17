"""DOCX 文件解析器

从 DOCX 文件中提取文本和图片。
"""
from typing import List, Tuple
import io
import zipfile

from docx import Document
from lxml import etree

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class DOCXParser(BaseFileParser):
    """DOCX 解析器"""

    # XML 命名空间
    NS = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    }

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析 DOCX 文件
        
        Args:
            file_data: DOCX 文件数据
            
        Returns:
            解析结果
        """
        doc = Document(io.BytesIO(file_data))
        
        # 使用 XML 解析获取页码信息
        page_breaks = self._find_page_breaks(file_data)
        
        text_blocks = []
        
        # 处理段落
        para_idx = 0
        total_pages = self._estimate_total_pages(file_data, len(doc.paragraphs) + sum(len(t.rows) for t in doc.tables))
        
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if text:
                # 每 5 个块算一页（更细粒度）
                page = min(total_pages - 1, para_idx // 5)
                
                text_blocks.append(
                    TextBlock(
                        text=text,
                        bbox=BoundingBox(
                            x=0,
                            y=para_idx * 20,
                            width=0,
                            height=20,
                        ),
                        page=page,
                    )
                )
                para_idx += 1
        
        # 处理表格
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                # 提取每个单元格文本
                cell_texts = [cell.text.strip() for cell in row.cells]
                num_cols = len(cell_texts)
                
                # 12列表格结构: [行标题][字段1][值1...][字段2][值2...]
                # 6列表格结构: [字段1][值1][字段2][值2]...
                parsed_fields = []
                
                if num_cols == 12:
                    # 12列：Cell 1 是字段1, Cell 2-6 是值1, Cell 7 是字段2, Cell 9-11 是值2
                    field1 = cell_texts[1] if cell_texts[1] else ""
                    value1_parts = []
                    for c in range(2, 7):
                        if c < num_cols and cell_texts[c] and cell_texts[c] != field1:
                            if not value1_parts or cell_texts[c] != value1_parts[-1]:
                                value1_parts.append(cell_texts[c])
                    value1 = value1_parts[0] if value1_parts else ""
                    
                    field2 = cell_texts[7] if cell_texts[7] else ""
                    value2_parts = []
                    for c in range(9, 12):
                        if c < num_cols and cell_texts[c] and cell_texts[c] != field2:
                            if not value2_parts or cell_texts[c] != value2_parts[-1]:
                                value2_parts.append(cell_texts[c])
                    value2 = value2_parts[0] if value2_parts else ""
                    
                    if field1 and value1:
                        parsed_fields.append(f"{field1}: {value1}")
                    if field2 and value2:
                        parsed_fields.append(f"{field2}: {value2}")
                        
                elif num_cols == 6:
                    for group_start in range(0, 6, 2):
                        field = cell_texts[group_start] if group_start < num_cols else ""
                        value = cell_texts[group_start + 1] if group_start + 1 < num_cols else ""
                        if field and value:
                            parsed_fields.append(f"{field}: {value}")
                            
                else:
                    deduplicated = []
                    prev = None
                    for ct in cell_texts:
                        if ct and ct != prev:
                            deduplicated.append(ct)
                            prev = ct
                    if deduplicated:
                        parsed_fields.append(" | ".join(deduplicated[:6]))
                
                if parsed_fields:
                    row_text = " | ".join(parsed_fields)
                    
                    # 使用连续的索引，每 5 个块算一页
                    para_idx += 1
                    page = min(total_pages - 1, para_idx // 5)
                    
                    text_blocks.append(
                        TextBlock(
                            text=f"[表格行{row_idx + 1}] {row_text}",
                            bbox=BoundingBox(
                                x=0,
                                y=para_idx * 20,
                                width=0,
                                height=20,
                            ),
                            page=page,
                        )
                    )
        
        # 计算总页数
        total_pages = self._estimate_total_pages(file_data, len(text_blocks))
        
        metadata = {
            "title": doc.core_properties.title or "",
            "author": doc.core_properties.author or "",
            "sections": len(doc.sections),
            "page_breaks": len(page_breaks),
        }
        
        return ParseResult(
            content=DocumentContent(text_blocks=text_blocks),
            pages=total_pages,
            metadata=metadata,
        )

    def _find_page_breaks(self, file_data: bytes) -> List[int]:
        """从 XML 中查找分页符位置
        
        返回: [(段落索引, 页码), ...]
        """
        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as z:
                with z.open('word/document.xml') as f:
                    tree = etree.parse(f)
        except Exception:
            return []
        
        root = tree.getroot()
        
        # 查找所有分页符 (w:br type="page")
        page_breaks = []
        para_idx = 0
        
        # 遍历 body 下的所有元素
        body = root.xpath('//w:body', namespaces=self.NS)
        if not body:
            return []
        
        body = body[0]
        for child in body:
            tag = etree.QName(child).localname
            
            if tag == 'p':  # 段落
                # 检查段落中是否有分页符
                for elem in child.xpath('.//w:br', namespaces=self.NS):
                    br_type = elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type')
                    if br_type == 'page':
                        page_breaks.append(para_idx)
                para_idx += 1
                
            elif tag == 'tbl':  # 表格
                # 表格算一个段落索引
                para_idx += 1
        
        return page_breaks
    
    def _estimate_total_pages(self, file_data: bytes, text_blocks_count: int) -> int:
        """估算总页数
        
        结合以下信息估算：
        1. 页脚文件数量（最准确）
        2. python-docx 的 sections 数量
        3. 显式分页符数量
        """
        # 方法1: 使用页脚文件数量（最准确）
        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as z:
                footers = [n for n in z.namelist() if 'footer' in n and n.endswith('.xml')]
                footer_count = len(footers)
        except:
            footer_count = 0
        
        # 方法2: 使用 python-docx 的 sections
        doc = Document(io.BytesIO(file_data))
        section_count = len(doc.sections)
        
        # 方法3: 获取显式分页符
        page_breaks = self._find_page_breaks(file_data)
        
        # 取最大值
        # 页脚数量通常最准确
        estimated = max(footer_count, section_count, len(page_breaks) + 1)
        
        # 如果估算值太小，使用内容估算
        if estimated < 5:
            estimated = max(5, (text_blocks_count + 15) // 20)
        
        return max(1, estimated)

    async def extract_images(self, file_data: bytes) -> List[bytes]:
        """从 DOCX 文件中提取图片
        
        Args:
            file_data: DOCX 文件数据
            
        Returns:
            图片列表
        """
        try:
            import docx
        except ImportError:
            return []
        
        doc = Document(io.BytesIO(file_data))
        images = []
        
        # 遍历所有段落中的内联图片
        for paragraph in doc.paragraphs:
            for run in paragraph.runs:
                for inline_shape in run._element.xpath(".//w:drawing/wp:inline"):
                    # 提取图片
                    blip = inline_shape.xpath(".//a:blip/@r:embed")
                    if blip:
                        # 获取图片数据
                        image_part = doc.part.related_parts.get(blip[0])
                        if image_part:
                            images.append(image_part.blob)
        
        return images
