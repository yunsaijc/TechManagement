"""统一提取器入口。

避免在包初始化阶段强制加载 PIL / OCR 等重依赖。
"""

__all__ = ["FieldExtractor", "SignatureExtractor", "StampExtractor"]


def __getattr__(name: str):
    """按需加载具体提取器，兼容既有导入方式。"""
    if name == "FieldExtractor":
        from .field import FieldExtractor
        return FieldExtractor
    if name == "SignatureExtractor":
        from .signature import SignatureExtractor
        return SignatureExtractor
    if name == "StampExtractor":
        from .stamp import StampExtractor
        return StampExtractor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
