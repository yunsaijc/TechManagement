"""图像预处理器

提供图像增强、边界检测等功能。
"""
import cv2
import numpy as np


class ImagePreprocessor:
    """图像预处理器"""

    @staticmethod
    def enhance_for_ocr(image_data: bytes) -> bytes:
        """增强图像以提高 OCR 准确率

        Args:
            image_data: 原始图像数据

        Returns:
            增强后的图像数据
        """
        # 读取图像
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 灰度化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 去噪声
        denoised = cv2.fastNlMeansDenoising(gray)

        # 自适应阈值
        thresh = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )

        # 转回 BGR
        result = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)

        _, buffer = cv2.imencode(".png", result)
        return buffer.tobytes()

    @staticmethod
    def detect_document_boundary(image_data: bytes) -> dict:
        """检测文档边界

        Args:
            image_data: 图像数据

        Returns:
            边界信息
        """
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 边缘检测
        edges = cv2.Canny(gray, 50, 150)

        # 找轮廓
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if contours:
            # 取最大轮廓
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            return {"x": x, "y": y, "width": w, "height": h}

        # 返回默认值
        return {
            "x": 0,
            "y": 0,
            "width": img.shape[1],
            "height": img.shape[0],
        }
