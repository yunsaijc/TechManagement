"""文件处理模块

提供统一的文件处理能力，包括 PDF 解析、图片处理、格式转换等。
"""
from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.file_handler.factory import get_parser, detect_file_type
from src.common.file_handler.image_processor import ImageProcessor
from src.common.file_handler.ocr import OCRProcessor
from src.common.file_handler.pdf_parser import PDFParser
from src.common.file_handler.docx_parser import DOCXParser

__all__ = [
    "BaseFileParser",
    "ParseResult",
    "PDFParser",
    "DOCXParser",
    "OCRProcessor",
    "ImageProcessor",
    "get_parser",
    "detect_file_type",
]
