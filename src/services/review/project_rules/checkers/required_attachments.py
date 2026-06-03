"""必需附件检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.doc_types import doc_type_to_legacy_doc_kind
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.checkers._attachment_kinds import collect_specific_doc_types
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class RequiredAttachmentsRule(BaseProjectRule):
    """检查必需附件"""

    name = "required_attachments"
    description = "检查必需附件是否齐全"
    priority = 90

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        required_doc_types = config.get("required_doc_types", [])
        existing_doc_types = collect_specific_doc_types(context.attachments)
        missing = [doc_type for doc_type in required_doc_types if doc_type not in existing_doc_types]
        missing_doc_kinds = [doc_type_to_legacy_doc_kind(doc_type) for doc_type in missing]
        required_doc_kinds = [doc_type_to_legacy_doc_kind(doc_type) for doc_type in required_doc_types]

        if missing:
            if context.attachments and not context.attachment_classification_reliable:
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.WARNING,
                    message="附件类型识别不可靠，无法自动确认必需附件是否齐全",
                    evidence={"missing_doc_types": missing, "missing_doc_kinds": missing_doc_kinds},
                )
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"缺少必需附件: {', '.join(missing)}",
                evidence={"missing_doc_types": missing, "missing_doc_kinds": missing_doc_kinds},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="必需附件齐全",
            evidence={"required_doc_types": required_doc_types, "required_doc_kinds": required_doc_kinds},
        )
