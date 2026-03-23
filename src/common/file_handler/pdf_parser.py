"""PDF 解析器"""
from typing import List

import fitz  # PyMuPDF

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class PDFParser(BaseFileParser):
    """PDF 解析器"""

    def _row_to_text(self, row: list, header: list[str]) -> str:
        cells = [str(c).strip() if c is not None else "" for c in row]
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

    def _extract_table_blocks(self, page, page_num: int) -> list[TextBlock]:
        table_blocks: list[TextBlock] = []
        try:
            finder = page.find_tables()
        except Exception:
            return table_blocks

        tables = getattr(finder, "tables", []) or []
        row_index = 0
        for tb_idx, table in enumerate(tables, start=1):
            try:
                rows = table.extract() or []
            except Exception:
                continue
            if not rows:
                continue

            header: list[str] = []
            for row_no, row in enumerate(rows, start=1):
                cells = [str(c).strip() if c is not None else "" for c in row]
                if not any(cells):
                    continue

                if row_no <= 2 and not header:
                    if any("指标" in c or "金额" in c or "预算" in c or "类别" in c for c in cells):
                        header = cells
                        hline = " | ".join([c for c in cells if c])
                        if hline:
                            row_index += 1
                            table_blocks.append(
                                TextBlock(
                                    text=f"[表格表头{tb_idx}] {hline}",
                                    bbox=BoundingBox(
                                        x=float(getattr(table, "bbox", [0, 0, 0, 0])[0]),
                                        y=float(getattr(table, "bbox", [0, 0, 0, 0])[1]),
                                        width=max(
                                            0.0,
                                            float(getattr(table, "bbox", [0, 0, 0, 0])[2])
                                            - float(getattr(table, "bbox", [0, 0, 0, 0])[0]),
                                        ),
                                        height=max(
                                            0.0,
                                            float(getattr(table, "bbox", [0, 0, 0, 0])[3])
                                            - float(getattr(table, "bbox", [0, 0, 0, 0])[1]),
                                        ),
                                    ),
                                    page=page_num,
                                )
                            )
                        continue

                line = self._row_to_text(row, header)
                if not line:
                    continue
                row_index += 1
                table_blocks.append(
                    TextBlock(
                        text=f"[表格行{row_index}] {line}",
                        bbox=BoundingBox(
                            x=float(getattr(table, "bbox", [0, 0, 0, 0])[0]),
                            y=float(getattr(table, "bbox", [0, 0, 0, 0])[1]),
                            width=max(
                                0.0,
                                float(getattr(table, "bbox", [0, 0, 0, 0])[2])
                                - float(getattr(table, "bbox", [0, 0, 0, 0])[0]),
                            ),
                            height=max(
                                0.0,
                                float(getattr(table, "bbox", [0, 0, 0, 0])[3])
                                - float(getattr(table, "bbox", [0, 0, 0, 0])[1]),
                            ),
                        ),
                        page=page_num,
                    )
                )

        return table_blocks

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析 PDF"""
        doc = fitz.open(stream=file_data, filetype="pdf")

        text_blocks = []
        for page_num, page in enumerate(doc):
            page_blocks: list[TextBlock] = []
            # 提取文本块和位置
            blocks = page.get_text("blocks")
            for block in blocks:
                x0, y0, x1, y1, text_content, *_ = block
                if text_content.strip():  # 跳过空文本块
                    page_blocks.append(
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

            # 额外提取表格行，增强预算/指标等表格场景的结构化可读性。
            page_blocks.extend(self._extract_table_blocks(page, page_num))

            page_blocks.sort(key=lambda b: (b.page, b.bbox.y, b.bbox.x))
            text_blocks.extend(page_blocks)

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
