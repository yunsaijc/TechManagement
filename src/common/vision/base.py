"""视觉能力基类"""
from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel

from src.common.models.document import BoundingBox


class DetectionResult(BaseModel):
    """检测结果"""
    class_name: str
    bbox: BoundingBox
    confidence: float


class BaseDetector(ABC):
    """目标检测器基类"""

    @abstractmethod
    async def detect(
        self,
        image_data: bytes,
        classes: List[str] = None,
        **kwargs,
    ) -> List[DetectionResult]:
        """检测目标"""
        pass
