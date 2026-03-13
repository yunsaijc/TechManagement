"""图像分割器"""
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from src.common.models.document import BoundingBox


class ImageSegmenter:
    """图像分割器"""

    @staticmethod
    def crop_region(
        image_data: bytes,
        bbox: "BoundingBox",
    ) -> bytes:
        """裁剪区域

        Args:
            image_data: 图像数据
            bbox: 边界框

        Returns:
            裁剪后的图像数据
        """
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        x = int(bbox.x)
        y = int(bbox.y)
        w = int(bbox.width)
        h = int(bbox.height)

        # 边界检查
        h_img, w_img = img.shape[:2]
        x = max(0, min(x, w_img - 1))
        y = max(0, min(y, h_img - 1))
        w = min(w, w_img - x)
        h = min(h, h_img - y)

        cropped = img[y : y + h, x : x + w]

        _, buffer = cv2.imencode(".png", cropped)
        return buffer.tobytes()

    @staticmethod
    def apply_mask(
        image_data: bytes,
        mask: np.ndarray,
        color: tuple = (0, 255, 0),
    ) -> bytes:
        """应用遮罩

        Args:
            image_data: 图像数据
            mask: 遮罩
            color: 颜色

        Returns:
            应用遮罩后的图像数据
        """
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 确保 mask 与图像大小匹配
        if mask.shape[:2] != img.shape[:2]:
            mask = cv2.resize(mask, (img.shape[1], img.shape[0]))

        # 创建彩色遮罩
        mask_3c = cv2.merge([mask, mask, mask])

        # 应用遮罩
        masked = cv2.bitwise_and(img, mask_3c)

        _, buffer = cv2.imencode(".png", masked)
        return buffer.tobytes()
