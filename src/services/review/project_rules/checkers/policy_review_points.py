"""政策审查要点覆盖提示"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_effective_policy_review_points
from src.services.review.project_rules.checkers._attachment_kinds import collect_specific_doc_kinds
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class PolicyReviewPointsCheckRule(BaseProjectRule):
    """汇总当前仍需补数据源或人工复核的政策要点"""

    name = "policy_review_points_check"
    description = "提示当前未自动核验的政策审查要点"
    priority = 10

    async def check(self, context):
        review_points = get_effective_policy_review_points(
            context.project_info.project_type,
            context.notice_context,
        )
        pending = []
        for point in review_points:
            automation = point.get("automation")
            if not self._is_point_applicable(context, point):
                continue
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

    def _is_point_applicable(self, context, point) -> bool:
        """过滤已被自动规则覆盖或当前不适用的要点"""
        code = point.get("code", "")
        existing_doc_kinds = collect_specific_doc_kinds(context.attachments)

        if code == "registered_date_limit":
            return not bool(context.project_info.registered_date)
        if code == "cooperation_agreement_required":
            return bool(context.project_info.has_cooperation_unit) and "cooperation_agreement" not in existing_doc_kinds
        if code == "recommendation_letter_required":
            return bool(context.project_info.has_cooperation_unit) and "recommendation_letter" not in existing_doc_kinds
        if code == "cooperation_region_check":
            return bool(context.project_info.has_cooperation_unit)
        if code == "ethics_approval_required":
            return bool(context.project_info.has_clinical_research) and "ethics_approval" not in existing_doc_kinds
        if code == "industry_permit_required":
            return bool(context.project_info.has_special_industry_requirement) and "industry_permit" not in existing_doc_kinds
        if code == "biosafety_commitment_required":
            return bool(context.project_info.has_biosafety_activity) and "biosafety_commitment" not in existing_doc_kinds
        if code == "commitment_letter_required":
            return "commitment_letter" not in existing_doc_kinds
        if code == "base_staff_proof_required":
            return "base_staff_proof" not in existing_doc_kinds
        return True
