"""文件处理模块

提供统一的文件处理能力，包括 PDF 解析、图片处理、格式转换等。
"""
from .base import BaseFileParser, ParseResult
from .factory import get_parser, detect_file_type
from .ocr import OCRProcessor

try:
    from .image_processor import ImageProcessor
except Exception:
    ImageProcessor = None

try:
    from .pdf_parser import PDFParser
except Exception:
    PDFParser = None

try:
    from .docx_parser import DOCXParser
except Exception:
    DOCXParser = None

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
