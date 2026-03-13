"""文档内容模型"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """边界框"""
    x: float
    y: float
    width: float
    height: float

    def to_xyxy(self) -> tuple:
        """转换为 xyxy 格式"""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


class TextBlock(BaseModel):
    """文本块"""
    text: str
    bbox: BoundingBox
    page: int
    confidence: float = 1.0


class ImageRegion(BaseModel):
    """图像区域"""
    type: str  # "signature", "stamp", "text", "table"
    bbox: BoundingBox
    confidence: float = 1.0
    content: Optional[str] = None


class DocumentContent(BaseModel):
    """文档内容"""
    text_blocks: List[TextBlock] = Field(default_factory=list)
    image_regions: List[ImageRegion] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
