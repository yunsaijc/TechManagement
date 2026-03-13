"""文件解析器基类"""
from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel

from src.common.models.document import DocumentContent


class ParseResult(BaseModel):
    """解析结果"""
    content: DocumentContent
    pages: int
    metadata: dict = {}


class BaseFileParser(ABC):
    """文件解析器基类"""

    @abstractmethod
    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析文件"""
        pass

    @abstractmethod
    async def extract_images(self, file_data: bytes) -> List[bytes]:
        """提取图片"""
        pass
