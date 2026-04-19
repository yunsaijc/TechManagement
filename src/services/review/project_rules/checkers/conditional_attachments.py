"""条件性附件检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.doc_types import doc_type_to_legacy_doc_kind
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.checkers._attachment_kinds import collect_specific_doc_types
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class ConditionalAttachmentsRule(BaseProjectRule):
    """检查条件性附件"""

    name = "conditional_attachments"
    description = "检查条件性附件是否齐全"
    priority = 80

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        conditional_rules = config.get("conditional_doc_rules", [])
        info = context.project_info.model_dump()
        existing_doc_types = collect_specific_doc_types(context.attachments)

        missing = []
        for rule in conditional_rules:
            condition_field = rule.get("when")
            doc_type = rule.get("doc_type")
            reason = rule.get("reason", "")
            if info.get(condition_field) and doc_type not in existing_doc_types:
                missing.append(
                    {
                        "doc_type": doc_type,
                        "doc_kind": doc_type_to_legacy_doc_kind(doc_type),
                        "reason": reason,
                    }
                )

        if missing:
            if context.attachments and not context.attachment_classification_reliable:
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.WARNING,
                    message="附件类型识别不可靠，无法自动确认条件性附件是否齐全",
                    evidence={"missing_conditional_attachments": missing},
                )
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="条件性附件不完整",
                evidence={"missing_conditional_attachments": missing},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="条件性附件完整",
            evidence={},
        )
