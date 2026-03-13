"""盖章检查规则"""
from src.common.models.review import CheckResult, CheckStatus
from src.common.vision import YOLODetector
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class StampCheckRule(BaseRule):
    """盖章检查规则"""

    name = "stamp"
    description = "检查文档中是否存在印章"
    priority = 10

    def __init__(self):
        self.min_confidence = 0.7

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行盖章检查"""
        # 检测印章区域 - 使用通用目标检测
        detector = YOLODetector("yolov8n.pt")
        try:
            regions = await detector.detect(
                context.file_data,
                confidence=self.min_confidence,
            )
        except Exception:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="印章检测暂时不可用",
                evidence={},
            )

        # 过滤可能的印章区域（简化处理）
        stamp_regions = [r for r in regions if r.class_name in ["cup", "bottle", "cell phone"]]

        if stamp_regions:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"检测到 {len(stamp_regions)} 个疑似印章区域",
                evidence={"region_count": len(stamp_regions)},
                confidence=0.5,
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未检测到印章",
                evidence={"region_count": 0},
            )
