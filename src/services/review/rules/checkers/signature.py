"""签字检查规则"""
from src.common.models.document import BoundingBox
from src.common.models.review import CheckResult, CheckStatus
from src.common.vision import YOLODetector
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class SignatureCheckRule(BaseRule):
    """签字检查规则"""

    name = "signature"
    description = "检查文档中是否存在签字"
    priority = 10

    def __init__(self):
        self.min_regions = 1  # 最少签字区域数
        self.min_confidence = 0.7  # 最低置信度

    async def should_run(self, context: ReviewContext) -> bool:
        """根据文档类型判断"""
        # 某些文档类型不需要签字检查
        no_signature_types = ["retrieval_report"]
        return context.document_type not in no_signature_types

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行签字检查"""
        # 检测签名区域 - 使用通用目标检测
        detector = YOLODetector("yolov8n.pt")
        try:
            regions = await detector.detect(
                context.file_data,
                confidence=self.min_confidence,
            )
        except Exception:
            # 如果检测失败，返回警告
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="签名检测暂时不可用",
                evidence={},
            )

        # 过滤可能的签名区域（简化处理，实际需要专门模型）
        signature_regions = [r for r in regions if r.class_name in ["person", "hand"]]

        if len(signature_regions) >= self.min_regions:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"检测到 {len(signature_regions)} 个疑似签字区域",
                evidence={
                    "region_count": len(signature_regions),
                    "regions": [
                        {
                            "bbox": r.bbox.model_dump(),
                            "confidence": r.confidence,
                        }
                        for r in signature_regions
                    ],
                },
                confidence=0.6,  # 通用模型置信度较低
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未检测到签字",
                evidence={"region_count": 0},
            )
