"""财政资金与自筹资金比例检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class FundingRatioCheckRule(BaseProjectRule):
    """检查财政资金与自筹资金比例"""

    name = "funding_ratio_check"
    description = "检查财政资金与自筹资金比例是否符合要求"
    priority = 68

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        constraints = config.get("constraints", {})
        project_type = context.project_info.project_type
        fiscal = float(context.project_info.fiscal_funding or 0.0)
        self_funding = float(context.project_info.self_funding or 0.0)
        applicant_unit_type = str(context.project_info.applicant_unit_type or "").strip()
        cooperation_info = context.cooperation_info
        cooperation_types = list((cooperation_info.cooperation_unit_types if cooperation_info else []) or [])

        if fiscal <= 0:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提取到有效财政资金金额，无法自动核验资金配比",
                evidence={},
            )

        min_ratio = None
        exempt = False
        reason = ""

        if project_type == "regional_innovation":
            min_ratio = float(constraints.get("min_self_funding_ratio", 1.0))
            if applicant_unit_type in {"institution", "university", "research_institute", "hospital"}:
                if not cooperation_types:
                    exempt = True
                    reason = "申报单位为事业单位且无合作单位，自筹资金要求豁免"
                elif all(unit_type in {"institution", "university", "research_institute", "hospital"} for unit_type in cooperation_types):
                    exempt = True
                    reason = "申报单位与合作单位均为事业单位，自筹资金要求豁免"
        elif project_type == "innovation_base":
            ratio_map = constraints.get("funding_ratio_by_applicant_type", {})
            min_ratio = ratio_map.get(applicant_unit_type)
            if min_ratio is None:
                min_ratio = ratio_map.get("default")
        elif project_type == "achievement_transformation":
            min_ratio = float(constraints.get("min_self_funding_ratio", 3.0))
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="当前项目类型未配置资金配比要求",
                evidence={},
            )

        evidence = {
            "fiscal_funding": fiscal,
            "self_funding": self_funding,
            "applicant_unit_type": applicant_unit_type,
            "cooperation_unit_types": cooperation_types,
        }

        if exempt:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=reason,
                evidence=evidence,
            )

        if min_ratio is None:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未能识别适用的资金配比门槛",
                evidence=evidence,
            )

        if self_funding <= 0:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="自筹资金不足，未满足资金配比要求",
                evidence={**evidence, "required_ratio": min_ratio},
            )

        actual_ratio = round(self_funding / fiscal, 4)
        evidence.update({"required_ratio": min_ratio, "actual_ratio": actual_ratio})
        if actual_ratio < float(min_ratio):
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"资金配比不符合要求: 当前 {actual_ratio:.2f}，要求不低于 {float(min_ratio):.2f}",
                evidence=evidence,
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="资金配比符合要求",
            evidence=evidence,
        )
