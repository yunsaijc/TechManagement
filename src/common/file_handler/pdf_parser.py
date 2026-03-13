"""PDF 解析器"""
from typing import List

import fitz  # PyMuPDF

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class PDFParser(BaseFileParser):
    """PDF 解析器"""

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析 PDF"""
        doc = fitz.open(stream=file_data, filetype="pdf")

        text_blocks = []
        for page_num, page in enumerate(doc):
            # 提取文本块和位置
            blocks = page.get_text("blocks")
            for block in blocks:
                x0, y0, x1, y1, text_content, *_ = block
                if text_content.strip():  # 跳过空文本块
                    text_blocks.append(
                        TextBlock(
                            text=text_content,
                            bbox=BoundingBox(
                                x=x0,
                                y=y0,
                                width=x1 - x0,
                                height=y1 - y0,
                            ),
                            page=page_num,
                        )
                    )

        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
        }

        return ParseResult(
            content=DocumentContent(text_blocks=text_blocks),
            pages=len(doc),
            metadata=metadata,
        )

    async def extract_images(self, file_data: bytes) -> List[bytes]:
        """提取图片"""
        doc = fitz.open(stream=file_data, filetype="pdf")
        images = []

        for page in doc:
            for img in page.get_images():
                xref = img[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:  # CMYK
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                images.append(pix.tobytes())

        return images
