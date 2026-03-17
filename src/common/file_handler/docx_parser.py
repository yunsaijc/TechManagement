"""DOCX 文件解析器

从 DOCX 文件中提取文本和图片。
"""
from typing import List
import io

from pydantic import BaseModel

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class DOCXParser(BaseFileParser):
    """DOCX 解析器"""

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析 DOCX 文件
        
        Args:
            file_data: DOCX 文件数据
            
        Returns:
            解析结果
        """
        try:
            import docx
        except ImportError:
            raise ImportError("python-docx not installed. Run: uv add python-docx")
        
        doc = docx.Document(io.BytesIO(file_data))
        
        text_blocks = []
        for para_idx, paragraph in enumerate(doc.paragraphs):
            text = paragraph.text.strip()
            if text:
                text_blocks.append(
                    TextBlock(
                        text=text,
                        bbox=BoundingBox(
                            x=0,
                            y=para_idx * 20,  # 估算行高
                            width=0,
                            height=20,
                        ),
                        page=0,
                    )
                )
        
        # 处理表格
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                row_text = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip()])
                if row_text:
                    text_blocks.append(
                        TextBlock(
                            text=f"[表格行{row_idx + 1}] {row_text}",
                            bbox=BoundingBox(
                                x=0,
                                y=(len(doc.paragraphs) + table_idx * 10 + row_idx) * 20,
                                width=0,
                                height=20,
                            ),
                            page=0,
                        )
                    )
        
        metadata = {
            "title": doc.core_properties.title or "",
            "author": doc.core_properties.author or "",
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
        
        doc = docx.Document(io.BytesIO(file_data))
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
