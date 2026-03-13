"""目标检测器"""
from typing import List, Optional

import cv2
import numpy as np

from src.common.models.document import BoundingBox
from src.common.vision.base import BaseDetector, DetectionResult


class YOLODetector(BaseDetector):
    """YOLO 目标检测器

    依赖 ultralytics 库，需要安装: pip install ultralytics
    """

    def __init__(self, model_path: str = "yolov8n.pt"):
        """初始化

        Args:
            model_path: 模型路径或模型名称
        """
        self.model_path = model_path
        self._model = None

    def _get_model(self):
        """延迟加载模型"""
        if self._model is None:
            from ultralytics import YOLO
            self._model = YOLO(self.model_path)
        return self._model

    async def detect(
        self,
        image_data: bytes,
        classes: Optional[List[str]] = None,
        confidence: float = 0.5,
        **kwargs,
    ) -> List[DetectionResult]:
        """检测目标"""
        # 转换图像
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 获取模型并检测
        model = self._get_model()
        results = model(
            img,
            conf=confidence,
            verbose=False,
            **kwargs,
        )

        detections = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls = int(box.cls[0])

                detections.append(
                    DetectionResult(
                        class_name=result.names[cls],
                        bbox=BoundingBox(
                            x=x1,
                            y=y1,
                            width=x2 - x1,
                            height=y2 - y1,
                        ),
                        confidence=conf,
                    )
                )

        return detections
