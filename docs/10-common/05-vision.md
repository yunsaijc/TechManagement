# 👁️ 视觉能力

## 概述

提供视觉相关的能力，包括目标检测、图像分割、多模态 LLM 调用。

## 模块结构

```
src/common/vision/
├── __init__.py
├── base.py           # 抽象基类
├── detector.py       # 目标检测
├── segmenter.py      # 图像分割
└── multimodal.py     # 多模态 LLM 封装
```

## 目标检测

### 核心接口

```python
# src/common/vision/base.py
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
        **kwargs
    ) -> List[DetectionResult]:
        """检测目标"""
        pass
```

### YOLO 检测器

```python
# src/common/vision/detector.py
from typing import List
import cv2
import numpy as np
from ultralytics import YOLO
from src.common.vision.base import BaseDetector, DetectionResult
from src.common.models.document import BoundingBox


class YOLODetector(BaseDetector):
    """YOLO 目标检测器"""

    def __init__(self, model_path: str = "yolov8n.pt"):
        self.model = YOLO(model_path)

    async def detect(
        self,
        image_data: bytes,
        classes: List[str] = None,
        confidence: float = 0.5,
        **kwargs
    ) -> List[DetectionResult]:
        """检测目标"""
        # 转换图像
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 检测
        results = self.model(
            img,
            conf=confidence,
            classes=classes,
            verbose=False
        )

        detections = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls = int(box.cls[0])

                detections.append(DetectionResult(
                    class_name=result.names[cls],
                    bbox=BoundingBox(
                        x=x1, y=y1,
                        width=x2-x1, height=y2-y1
                    ),
                    confidence=conf
                ))

        return detections
```

### 专用检测器

```python
# src/common/vision/specialized.py
from src.common.vision.detector import YOLODetector


class SignatureDetector(YOLODetector):
    """签名检测器 - 预训练模型"""

    # 自定义类别
    CLASSES = ["signature", "handwriting"]

    def __init__(self):
        # 使用专门训练的模型
        super().__init__("models/signature_detector.pt")


class StampDetector(YOLODetector):
    """印章检测器"""

    CLASSES = ["stamp", "seal", "official_seal"]

    def __init__(self):
        super().__init__("models/stamp_detector.pt")
```

## 图像分割

```python
# src/common/vision/segmenter.py
import cv2
import numpy as np
from typing import List


class ImageSegmenter:
    """图像分割器"""

    @staticmethod
    def crop_region(
        image_data: bytes,
        bbox: "BoundingBox"  # 前向引用
    ) -> bytes:
        """裁剪区域"""
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        x, y, w, h = int(bbox.x), int(bbox.y), int(bbox.width), int(bbox.height)
        cropped = img[y:y+h, x:x+w]

        _, buffer = cv2.imencode('.png', cropped)
        return buffer.tobytes()

    @staticmethod
    def apply_mask(
        image_data: bytes,
        mask: np.ndarray,
        color: tuple = (0, 255, 0)
    ) -> bytes:
        """应用遮罩"""
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 合并遮罩
        mask_3c = cv2.merge([mask, mask, mask])
        masked = cv2.bitwise_and(img, mask_3c)

        _, buffer = cv2.imencode('.png', masked)
        return buffer.tobytes()
```

## 多模态 LLM

```python
# src/common/vision/multimodal.py
from typing import List, Any

from langchain_core.messages import HumanMessage


class MultimodalLLM:
    """多模态 LLM 封装 - 基于 LangChain"""

    def __init__(self, llm: Any):
        """初始化

        Args:
            llm: LangChain ChatModel 实例
        """
        self.llm = llm

    async def analyze_image(
        self,
        image_data: bytes,
        prompt: str,
        **kwargs
    ) -> str:
        """分析图像"""
        import base64

        # 转换为 base64
        b64_image = base64.b64encode(image_data).decode("utf-8")
        image_url = f"data:image/png;base64,{b64_image}"

        # 构建多模态消息
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        )

        response = await self.llm.ainvoke([message], **kwargs)
        return response.content

    async def describe_document(
        self,
        image_data: bytes,
        **kwargs
    ) -> str:
        """描述文档内容"""
        prompt = """请详细描述这张文档图片的内容，包括：
1. 文档类型
2. 主要文字内容
3. 是否有签名、印章
4. 版式结构
"""
        return await self.analyze_image(image_data, prompt, **kwargs)

    async def verify_signature(
        self,
        document_image: bytes,
        signature_image: bytes,
        **kwargs
    ) -> str:
        """验证签名"""
        import base64

        b64_doc = base64.b64encode(document_image).decode("utf-8")
        b64_sig = base64.b64encode(signature_image).decode("utf-8")

        prompt = """比较这两张图片：
- 图1：文档中的签名区域
- 图2：参考签名

请判断是否为同一人签名，置信度如何？"""

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_doc}"}},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_sig}"}}
            ]
        )

        response = await self.llm.ainvoke([message], **kwargs)
        return response.content
```

## 使用方式

```python
# 目标检测
from src.common.vision import SignatureDetector, StampDetector

signature_detector = SignatureDetector()
signatures = await signature_detector.detect(image_data)

stamp_detector = StampDetector()
stamps = await stamp_detector.detect(image_data)

# 图像分割
from src.common.vision.segmenter import ImageSegmenter

segmenter = ImageSegmenter()
cropped = segmenter.crop_region(image_data, bbox)

# 多模态分析
from src.common.vision.multimodal import MultimodalLLM
from src.common.llm import get_llm_client

llm = get_llm_client()
multi_llm = MultimodalLLM(llm)

description = await multi_llm.describe_document(image_data)
```

## 层次关系

| 层级 | 组件 | 职责 |
|------|------|------|
| Layer 3 | `YOLODetector`, `MultimodalLLM` | 纯底层能力，只管"检测到" |
| Layer 4 | `SignatureDetector`, `StampDetector` | 组合底层能力，输出结构化检测结果 |
| Layer 5 | `*Checker` (规则) | 调用检测器，判断"是否通过" |

## 架构分层说明

详见 [形式审查 - 规则引擎设计 →](../20-review/02-rules.md)
