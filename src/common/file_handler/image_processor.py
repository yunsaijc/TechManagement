"""图片处理器"""
import io
from typing import Tuple

from PIL import Image


class ImageProcessor:
    """图片处理器"""

    @staticmethod
    def resize(
        image_data: bytes,
        max_size: Tuple[int, int] = (2048, 2048),
    ) -> bytes:
        """调整图片大小"""
        img = Image.open(io.BytesIO(image_data))

        # 保持比例缩放
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        img.save(output, format=img.format or "PNG")
        return output.getvalue()

    @staticmethod
    def to_rgb(image_data: bytes) -> bytes:
        """转换为 RGB 模式"""
        img = Image.open(io.BytesIO(image_data))

        if img.mode != "RGB":
            img = img.convert("RGB")

        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()

    @staticmethod
    def get_dimensions(image_data: bytes) -> Tuple[int, int]:
        """获取图片尺寸"""
        img = Image.open(io.BytesIO(image_data))
        return img.size
