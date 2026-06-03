"""视觉能力模块

提供目标检测、图像分割、多模态 LLM 调用等视觉相关能力。
"""
from src.common.vision.base import BaseDetector, DetectionResult
from src.common.vision.multimodal import MultimodalLLM

try:
    from src.common.vision.detector import YOLODetector
except Exception:  # pragma: no cover - 允许无 cv2 环境下继续使用多模态能力
    YOLODetector = None

try:
    from src.common.vision.segmenter import ImageSegmenter
except Exception:  # pragma: no cover - 允许无 cv2 环境下继续使用多模态能力
    ImageSegmenter = None

__all__ = [
    "BaseDetector",
    "DetectionResult",
    "YOLODetector",
    "ImageSegmenter",
    "MultimodalLLM",
]
