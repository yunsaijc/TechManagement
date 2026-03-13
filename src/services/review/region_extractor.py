"""区域提取器

从图像中提取签名、印章等特定区域。
"""
from typing import List

from src.common.models import BoundingBox, ImageRegion
from src.common.vision import YOLODetector


class RegionExtractor:
    """区域提取器"""

    async def extract_signature_regions(
        self,
        image_data: bytes,
        detection_results: List,
    ) -> List[ImageRegion]:
        """提取签名区域

        Args:
            image_data: 图像数据
            detection_results: 检测结果

        Returns:
            签名区域列表
        """
        regions = []

        for detection in detection_results:
            if detection.class_name in ["signature", "handwriting", "person"]:
                region = ImageRegion(
                    type="signature",
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                )
                regions.append(region)

        return regions

    async def extract_stamp_regions(
        self,
        image_data: bytes,
        detection_results: List,
    ) -> List[ImageRegion]:
        """提取印章区域

        Args:
            image_data: 图像数据
            detection_results: 检测结果

        Returns:
            印章区域列表
        """
        regions = []

        for detection in detection_results:
            if detection.class_name in ["stamp", "seal"]:
                region = ImageRegion(
                    type="stamp",
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                )
                regions.append(region)

        return regions
