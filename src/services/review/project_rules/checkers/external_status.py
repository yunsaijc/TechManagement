"""外部校验状态检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class ExternalStatusCheckRule(BaseProjectRule):
    """检查外部系统校验结果"""

    name = "external_status_check"
    description = "检查失信、重复申报等外部状态"
    priority = 50

    async def check(self, context):
        if not context.external_checks:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提供外部校验结果",
                evidence={},
            )

        issues = []
        checks = context.external_checks

        if checks.integrity_status and checks.integrity_status != "passed":
            issues.append(f"科研失信状态异常: {checks.integrity_status}")
        if checks.social_credit_status and checks.social_credit_status != "passed":
            issues.append(f"社会失信状态异常: {checks.social_credit_status}")
        if checks.duplicate_submission_status and checks.duplicate_submission_status != "passed":
            issues.append(f"重复申报状态异常: {checks.duplicate_submission_status}")

        if issues:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="; ".join(issues),
                evidence=checks.model_dump(),
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="外部校验结果正常",
            evidence=checks.model_dump(),
        )
