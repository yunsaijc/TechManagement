"""DOCX 文件解析器

从 DOCX 文件中提取文本和图片。
"""
from typing import Iterable, List
import io
import re

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class DOCXParser(BaseFileParser):
    """DOCX 解析器"""

    def _iter_block_items(self, doc) -> Iterable[object]:
        """按文档原始顺序遍历段落和表格。"""
        try:
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except Exception:
            return []

        blocks: list[object] = []
        for child in doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                blocks.append(Paragraph(child, doc))
            elif isinstance(child, CT_Tbl):
                blocks.append(Table(child, doc))
        return blocks

    def _split_long_text(self, text: str, max_len: int = 500) -> list[str]:
        if len(text) <= max_len:
            return [text]
        # 增加长度阈值，避免过度切分导致语义断裂
        parts: list[str] = []
        current = ""
        # 优先在句号、分号、感叹号、问号处切分
        for frag in re.split(r"([。；;！？!?\n])", text):
            if not frag:
                continue
            candidate = (current + frag).strip()
            if len(candidate) > max_len and current:
                parts.append(current.strip())
                current = frag
            else:
                current = candidate
        if current.strip():
            parts.append(current.strip())
        return parts or [text]

    def _row_to_text(self, row_cells: list[str], header: list[str]) -> str:
        cells = [str(c).strip() if c is not None else "" for c in row_cells]
        non_empty = [c for c in cells if c]
        if not non_empty:
            return ""

        if header and len(header) == len(cells):
            pairs = []
            for h, v in zip(header, cells):
                h = (h or "").strip()
                v = (v or "").strip()
                if h and v:
                    pairs.append(v if h == v else f"{h}:{v}")
            if pairs:
                return " ; ".join(pairs)

        return " | ".join(non_empty)

    def _extract_table_blocks(
        self,
        table,
        *,
        table_index: int,
        page_num: int,
        row_index_start: int,
        y_start: int,
    ) -> tuple[list[TextBlock], int, int]:
        table_blocks: list[TextBlock] = []
        header: list[str] = []
        row_index = row_index_start
        y_cursor = y_start

        for row_no, row in enumerate(table.rows, start=1):
            row_cells = [cell.text.strip() for cell in row.cells]
            if not any(row_cells):
                continue

            if row_no <= 2 and not header:
                if any(re.search(r"指标|金额|预算|类别|比例|内容|任务", c) for c in row_cells):
                    header = row_cells
                    hline = " | ".join([c for c in row_cells if c])
                    if hline:
                        table_blocks.append(
                            TextBlock(
                                text=f"[表格表头{table_index}] {hline}",
                                bbox=BoundingBox(x=0, y=y_cursor, width=0, height=20),
                                page=page_num,
                            )
                        )
                        y_cursor += 20
                    continue

            # 兜底：未识别关键词表头时，首行视作表头。
            if row_no == 1 and not header:
                header = row_cells
                hline = " | ".join([c for c in row_cells if c])
                if hline:
                    table_blocks.append(
                        TextBlock(
                            text=f"[表格表头{table_index}] {hline}",
                            bbox=BoundingBox(x=0, y=y_cursor, width=0, height=20),
                            page=page_num,
                        )
                    )
                    y_cursor += 20
                continue

            line = self._row_to_text(row_cells, header)
            if not line:
                continue

            row_index += 1
            table_blocks.append(
                TextBlock(
                    text=f"[表格行{row_index}] {line}",
                    bbox=BoundingBox(x=0, y=y_cursor, width=0, height=20),
                    page=page_num,
                )
            )
            y_cursor += 20

        return table_blocks, row_index, y_cursor

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
        row_index = 0
        table_index = 0
        y_cursor = 0
        blocks = self._iter_block_items(doc)
        for block in blocks:
            block_type = type(block).__name__
            if block_type == "Paragraph":
                # 保留换行符，有助于后续识别结构
                text = block.text.strip()
                if not text:
                    continue
                
                style_name = (getattr(getattr(block, "style", None), "name", "") or "").strip()
                # 识别标题级别，方便后续 Section 划分
                if style_name.lower().startswith("heading"):
                    level = 1
                    m = re.search(r"\d+", style_name)
                    if m:
                        level = int(m.group())
                    text = f"{'#' * level} {text}"

                # 增加切分长度限制，减少长文本解析时的碎片化
                for frag in self._split_long_text(text, max_len=800):
                    text_blocks.append(
                        TextBlock(
                            text=frag,
                            bbox=BoundingBox(x=0, y=y_cursor, width=0, height=20),
                            page=0,
                        )
                    )
                    y_cursor += 20
                continue

            if block_type == "Table":
                table_index += 1
                blocks_for_table, row_index, y_cursor = self._extract_table_blocks(
                    block,
                    table_index=table_index,
                    page_num=0,
                    row_index_start=row_index,
                    y_start=y_cursor,
                )
                text_blocks.extend(blocks_for_table)
        
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
