"""OCR 文字识别处理器"""
from typing import List

from src.common.models.document import BoundingBox, TextBlock


class OCRProcessor:
    """OCR 处理器 - 基于 EasyOCR 实现"""

    def __init__(self, languages: List[str] = None):
        """初始化 OCR 处理器

        Args:
            languages: 语言列表，默认 ['ch_sim', 'en']
        """
        self.languages = languages or ["ch_sim", "en"]
        self._reader = None

    def _get_reader(self):
        """延迟加载 reader"""
        if self._reader is None:
            # 使用 EasyOCR 作为后备方案（比 PaddleOCR 更容易安装）
            import easyocr

            self._reader = easyocr.Reader(self.languages, gpu=False, verbose=False)
        return self._reader

    async def recognize(
        self,
        image_data: bytes,
        page: int = 0,
    ) -> List[TextBlock]:
        """识别文字

        Args:
            image_data: 图片数据
            page: 页码

        Returns:
            文本块列表
        """
        import numpy as np

        # 转为 numpy 数组
        nparr = np.frombuffer(image_data, dtype=np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        reader = self._get_reader()

        # OCR 识别
        result = reader.readtext(img)

        text_blocks = []
        for bbox, text, confidence in result:
            # bbox 是四个点的坐标
            x_coords = [p[0] for p in bbox]
            y_coords = [p[1] for p in bbox]
            x_min, x_max = min(x_coords), max(x_coords)
            y_min, y_max = min(y_coords), max(y_coords)

            text_blocks.append(
                TextBlock(
                    text=text,
                    bbox=BoundingBox(
                        x=x_min,
                        y=y_min,
                        width=x_max - x_min,
                        height=y_max - y_min,
                    ),
                    page=page,
                    confidence=confidence,
                )
            )

        return text_blocks


# 简单回退实现
class SimpleOCRProcessor:
    """简单的 OCR 处理器 - 当其他 OCR 不可用时使用"""

    async def recognize(
        self,
        image_data: bytes,
        page: int = 0,
    ) -> List[TextBlock]:
        """识别文字 - 占位实现"""
        # 返回空列表，实际使用时需要安装 PaddleOCR 或 EasyOCR
        return []


# 尝试导入 cv2
try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore
