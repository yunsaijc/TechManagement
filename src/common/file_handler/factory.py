"""文件解析器工厂函数"""
from src.common.file_handler.base import BaseFileParser
from src.common.file_handler.pdf_parser import PDFParser


def get_parser(file_type: str) -> BaseFileParser:
    """获取解析器

    Args:
        file_type: 文件类型，如 'pdf', 'image'

    Returns:
        对应的解析器实例
    """
    parsers = {
        "pdf": PDFParser,
    }

    parser_class = parsers.get(file_type.lower())
    if not parser_class:
        raise ValueError(f"Unsupported file type: {file_type}")

    return parser_class()
