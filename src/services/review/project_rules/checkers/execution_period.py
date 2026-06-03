"""执行期检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class ExecutionPeriodLimitRule(BaseProjectRule):
    """检查执行期上限"""

    name = "execution_period_limit"
    description = "检查执行期是否超限"
    priority = 70

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        constraints = config.get("constraints", {})
        max_years = constraints.get("max_execution_period_years")
        years = context.project_info.execution_period_years

        if max_years is None:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="未配置执行期约束",
                evidence={},
            )

        if years > max_years:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"执行期超过限制: {years} 年 > {max_years} 年",
                evidence={"execution_period_years": years, "max_execution_period_years": max_years},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="执行期符合要求",
            evidence={"execution_period_years": years, "max_execution_period_years": max_years},
        )
