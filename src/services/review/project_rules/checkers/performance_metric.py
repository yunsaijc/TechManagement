"""绩效指标设置要求检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class PerformanceMetricCountCheckRule(BaseProjectRule):
    """检查绩效指标数量及第一年度目标占比"""

    name = "performance_metric_count_check"
    description = "检查绩效指标总数和第一年度绩效目标占比"
    priority = 62

    async def check(self, context):
        metric_count = int(context.project_info.performance_metric_count or 0)
        ratio = context.project_info.performance_first_year_ratio
        rows = context.project_info.performance_metric_rows or []

        if metric_count <= 0:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提取到绩效指标明细，暂无法自动核验绩效指标要求",
                evidence={},
            )

        if metric_count < 5:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"绩效指标数量不足: {metric_count} 项，少于 5 项",
                evidence={
                    "performance_metric_count": metric_count,
                    "performance_metric_rows": rows[:10],
                },
            )

        if ratio is None:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="已识别绩效指标，但无法稳定计算第一年度目标占比",
                evidence={
                    "performance_metric_count": metric_count,
                    "performance_metric_rows": rows[:10],
                },
            )

        if ratio < 0.5:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"第一年度绩效目标占比不足: {ratio:.2%}，低于 50%",
                evidence={
                    "performance_metric_count": metric_count,
                    "performance_first_year_ratio": ratio,
                    "performance_metric_rows": rows[:10],
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="绩效指标数量和第一年度目标占比符合要求",
            evidence={
                "performance_metric_count": metric_count,
                "performance_first_year_ratio": ratio,
                "performance_metric_rows": rows[:10],
            },
        )
