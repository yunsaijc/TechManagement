"""文件解析器工厂函数"""
from src.common.file_handler.base import BaseFileParser


def get_parser(file_type: str) -> BaseFileParser:
    """获取解析器

    Args:
        file_type: 文件类型，如 'pdf', 'docx', 'image'

    Returns:
        对应的解析器实例
    """
    ft = file_type.lower()
    if ft == "pdf":
        from src.common.file_handler.pdf_parser import PDFParser

        return PDFParser()
    if ft == "docx":
        from src.common.file_handler.docx_parser import DOCXParser

        return DOCXParser()
    raise ValueError(f"Unsupported file type: {file_type}")


def detect_file_type(filename: str) -> str:
    """根据文件名检测文件类型
    
    Args:
        filename: 文件名
        
    Returns:
        文件类型 (pdf, docx, etc.)
    """
    ext = filename.lower().split(".")[-1]
    return ext
