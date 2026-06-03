"""前置条件检查规则"""
from src.common.models.review import CheckResult, CheckStatus
from src.services.review.doc_types import normalize_doc_type
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class PrerequisiteCheckRule(BaseRule):
    """前置条件检查规则"""

    name = "prerequisite"
    description = "检查前置条件文档是否上传"
    priority = 20

    PREREQUISITES = {
        "reward_acceptance_report": [
            "project_retrieval_report",
        ],
    }

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行前置条件检查"""
        required = self.PREREQUISITES.get(normalize_doc_type(context.doc_type), [])

        if not required:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="无前置条件要求",
            )

        uploaded_types = [normalize_doc_type(item) for item in context.metadata.get("uploaded_types", [])]
        missing = [item for item in required if item not in uploaded_types]

        if missing:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"缺少前置条件文档: {', '.join(missing)}",
                evidence={"missing_doc_types": missing, "missing_types": missing},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="前置条件满足",
        )
