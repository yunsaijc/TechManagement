"""统一提取器（Layer 4）

职责：统一提取器，能提取到则返回内容，提取不到返回 null
"""
from .field import FieldExtractor
from .signature import SignatureExtractor
from .stamp import StampExtractor

__all__ = [
    "FieldExtractor",
    "SignatureExtractor", 
    "StampExtractor",
]
