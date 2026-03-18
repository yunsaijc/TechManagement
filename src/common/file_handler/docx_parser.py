"""DOCX 文件解析器

从 DOCX 文件中提取文本和图片。
"""
from typing import List, Generator, Union
import io
import zipfile

from docx import Document
from docx.document import Document as DocDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


def iter_block_items(parent: DocDocument) -> Generator[Union[Paragraph, Table], None, None]:
    """按文档顺序遍历段落和表格（保持原始顺序）
    
    使用底层 XML 遍历，确保段落和表格按 DOCX 中的实际顺序输出。
    """
    parent_elm = parent.element.body
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


class DOCXParser(BaseFileParser):
    """DOCX 解析器"""

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
        
        text_blocks = []
        block_idx = 0
        
        # 使用底层 XML 遍历，保持段落和表格的原始顺序
        for item in iter_block_items(doc):
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if text:
                    text_blocks.append(
                        TextBlock(
                            text=text,
                            bbox=BoundingBox(
                                x=0,
                                y=block_idx * 20,
                                width=0,
                                height=20,
                            ),
                            page=0,
                        )
                    )
                    block_idx += 1
                    
            elif isinstance(item, Table):
                # 处理表格 - 去除重复单元格内容
                for row_idx, row in enumerate(item.rows):
                    # 获取所有非空单元格文本
                    cell_texts = []
                    prev_text = None
                    for cell in row.cells:
                        text = cell.text.strip()
                        # 去除连续重复的单元格（合并单元格导致）
                        if text and text != prev_text:
                            cell_texts.append(text)
                            prev_text = text
                    
                    if cell_texts:
                        row_text = " | ".join(cell_texts)
                        text_blocks.append(
                            TextBlock(
                                text=f"[表格行{row_idx + 1}] {row_text}",
                                bbox=BoundingBox(
                                    x=0,
                                    y=block_idx * 20,
                                    width=0,
                                    height=20,
                                ),
                                page=0,
                            )
                        )
                        block_idx += 1
        
        metadata = {
            "title": doc.core_properties.title or "",
            "author": doc.core_properties.author or "",
            "total_blocks": block_idx,
        }
        
        return ParseResult(
            content=DocumentContent(text_blocks=text_blocks),
            pages=1,
            metadata=metadata,
        )

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
