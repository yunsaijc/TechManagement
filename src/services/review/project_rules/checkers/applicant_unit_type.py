"""申报单位类型检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class ApplicantUnitTypeCheckRule(BaseProjectRule):
    """检查申报单位类型"""

    name = "applicant_unit_type_check"
    description = "检查申报单位类型是否符合要求"
    priority = 60

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        constraints = config.get("constraints", {})
        allowed = constraints.get("allowed_applicant_unit_types")
        unit_type = context.project_info.applicant_unit_type

        if not allowed:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="未配置申报单位类型限制",
                evidence={},
            )

        if unit_type not in allowed:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"申报单位类型不符合要求: {unit_type}",
                evidence={"applicant_unit_type": unit_type, "allowed_types": allowed},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="申报单位类型符合要求",
            evidence={"applicant_unit_type": unit_type, "allowed_types": allowed},
        )
