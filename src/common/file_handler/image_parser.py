"""Image parser backed by OCR."""
from __future__ import annotations

import os
from typing import List

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.file_handler.image_processor import ImageProcessor
from src.common.file_handler.ocr import OCRProcessor, SimpleOCRProcessor
from src.common.models.document import DocumentContent


class ImageParser(BaseFileParser):
    """Parse image files into OCR text blocks."""

    def __init__(self) -> None:
        enable_ocr = os.getenv("ACCEPT_ENABLE_IMAGE_OCR", "").strip().lower() in {"1", "true", "yes", "on"}
        if not enable_ocr:
            self.ocr = SimpleOCRProcessor()
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

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        rgb_image = ImageProcessor.to_rgb(file_data)
        try:
            text_blocks = await self.ocr.recognize(rgb_image, page=0)
        except Exception:
            text_blocks = []
        width, height = ImageProcessor.get_dimensions(rgb_image)
        return ParseResult(
            content=DocumentContent(text_blocks=text_blocks),
            pages=1,
            metadata={
                "width": width,
                "height": height,
                "parser": type(self.ocr).__name__,
                "total_blocks": len(text_blocks),
            },
        )

    async def extract_images(self, file_data: bytes) -> List[bytes]:
        return [file_data]
