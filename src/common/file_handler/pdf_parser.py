"""PDF 解析器"""
from __future__ import annotations

import os
from typing import List

import fitz  # PyMuPDF

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.file_handler.ocr import OCRProcessor, SimpleOCRProcessor
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class PDFParser(BaseFileParser):
    """PDF 解析器"""

    def __init__(self) -> None:
        enable_ocr = os.getenv("ACCEPT_ENABLE_PDF_OCR", "true").strip().lower() in {"1", "true", "yes", "on"}
        self._enable_ocr = enable_ocr
        self._ocr_skip_min_chars = int(os.getenv("ACCEPT_PDF_OCR_SKIP_MIN_TEXT_CHARS", "240") or "240")
        self._ocr_skip_text_page_ratio = float(os.getenv("ACCEPT_PDF_OCR_SKIP_TEXT_PAGE_RATIO", "0.6") or "0.6")
        self._ocr_low_text_chars = int(os.getenv("ACCEPT_PDF_OCR_LOW_TEXT_CHARS", "20") or "20")
        self._ocr_low_text_max_pages = int(os.getenv("ACCEPT_PDF_OCR_LOW_TEXT_MAX_PAGES", "1") or "1")
        self._ocr_scale = float(os.getenv("ACCEPT_PDF_OCR_SCALE", "1.0") or "1.0")
        if not enable_ocr:
            self.ocr = None
            return
        backend = os.getenv("ACCEPT_OCR_BACKEND", "auto").strip().lower()
        if backend == "auto":
            try:
                self.ocr = OCRProcessor()
                return
            except Exception:
                self.ocr = SimpleOCRProcessor()
                return
        if backend in {"tesseract", "simple"}:
            self.ocr = SimpleOCRProcessor()
            return
        self.ocr = OCRProcessor()

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

    async def _extract_ocr_blocks(self, page, page_num: int) -> list[TextBlock]:
        matrix = fitz.Matrix(self._ocr_scale, self._ocr_scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image_bytes = pix.tobytes("png")
        try:
            ocr_blocks = await self.ocr.recognize(image_bytes, page=page_num)
        except Exception:
            return []
        if not ocr_blocks:
            return []

        scale_x = page.rect.width / max(pix.width, 1)
        scale_y = page.rect.height / max(pix.height, 1)
        scaled: list[TextBlock] = []
        for block in ocr_blocks:
            bbox = block.bbox
            scaled.append(
                TextBlock(
                    text=block.text,
                    bbox=BoundingBox(
                        x=bbox.x * scale_x,
                        y=bbox.y * scale_y,
                        width=bbox.width * scale_x,
                        height=bbox.height * scale_y,
                    ),
                    page=page_num,
                    confidence=block.confidence,
                )
            )
        return scaled

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析 PDF"""
        doc = fitz.open(stream=file_data, filetype="pdf")

        text_blocks = []
        text_pages = 0
        meaningful_text_pages = 0
        total_text_chars = 0
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

            page_text_chars = sum(len(block.text.strip()) for block in page_blocks if block.text.strip())
            if page_text_chars > 0:
                text_pages += 1
                total_text_chars += page_text_chars
            if page_text_chars > self._ocr_low_text_chars:
                meaningful_text_pages += 1

            should_run_ocr = self._should_run_ocr(
                direct_text_chars=page_text_chars,
                meaningful_text_pages=meaningful_text_pages,
                total_text_chars=total_text_chars,
                total_pages=max(len(doc), 1),
            )
            if should_run_ocr:
                page_blocks.extend(await self._extract_ocr_blocks(page, page_num))

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
            metadata={
                **metadata,
                "direct_text_pages": text_pages,
                "direct_meaningful_text_pages": meaningful_text_pages,
                "direct_text_chars": total_text_chars,
                "ocr_enabled": self._enable_ocr,
            },
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

    def _should_run_ocr(
        self,
        *,
        direct_text_chars: int,
        meaningful_text_pages: int,
        total_text_chars: int,
        total_pages: int,
    ) -> bool:
        if not self._enable_ocr or self.ocr is None:
            return False
        if direct_text_chars > 0:
            # A scanned appendix often has only a footer/page number as embedded text.
            # Treat those pages as OCR candidates; otherwise merged certificates and
            # dissertation covers after the first text page are silently skipped.
            return (
                direct_text_chars <= self._ocr_low_text_chars
                and meaningful_text_pages <= self._ocr_low_text_max_pages
            )
        if direct_text_chars > self._ocr_low_text_chars:
            return False
        if (
            total_text_chars >= self._ocr_skip_min_chars
            and (meaningful_text_pages / max(total_pages, 1)) >= self._ocr_skip_text_page_ratio
        ):
            return False
        return True
