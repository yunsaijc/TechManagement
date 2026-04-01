"""政策审查要点覆盖提示"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_policy_review_points
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class PolicyReviewPointsCheckRule(BaseProjectRule):
    """汇总当前仍需补数据源或人工复核的政策要点"""

    name = "policy_review_points_check"
    description = "提示当前未自动核验的政策审查要点"
    priority = 10

    async def check(self, context):
        review_points = get_policy_review_points(context.project_info.project_type)
        pending = []
        for point in review_points:
            automation = point.get("automation")
            if automation in {"requires_data", "manual"}:
                pending.append(
                    {
                        "code": point.get("code", ""),
                        "requirement": point.get("requirement", ""),
                        "automation": automation,
                        "reason": point.get("reason", ""),
                    }
                )

        if not pending:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="政策审查要点均已进入自动核验范围",
                evidence={},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.WARNING,
            message="部分政策审查要点当前未自动核验，已转为待补数据源或人工复核",
            evidence={"pending_review_points": pending},
        )
