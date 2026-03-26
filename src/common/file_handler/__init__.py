"""文件处理模块

提供统一的文件处理能力，包括 PDF 解析、图片处理、格式转换等。
"""
from .base import BaseFileParser, ParseResult
from .factory import get_parser, detect_file_type
from .image_processor import ImageProcessor
from .ocr import OCRProcessor
from .pdf_parser import PDFParser
from .docx_parser import DOCXParser

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
