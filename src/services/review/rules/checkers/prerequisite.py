"""前置条件检查规则"""
from src.common.models.enums import DocumentType
from src.common.models.review import CheckResult, CheckStatus
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class PrerequisiteCheckRule(BaseRule):
    """前置条件检查规则"""

    name = "prerequisite"
    description = "检查前置条件文档是否上传"
    priority = 20

    # 文档类型 -> 前置条件映射
    PREREQUISITES = {
        DocumentType.PATENT_CERTIFICATE: [],
        DocumentType.PATENT_APPLICATION: [],
        DocumentType.ACCEPTANCE_REPORT: [
            DocumentType.LICENSE,
            DocumentType.RETRIEVAL_REPORT,
        ],
        DocumentType.LICENSE: [],
        DocumentType.RETRIEVAL_REPORT: [],
        DocumentType.AWARD_CERTIFICATE: [],
        DocumentType.CONTRACT: [],
        DocumentType.OTHER: [],
    }

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行前置条件检查"""
        from src.common.models.enums import DocumentType

        # 转换文档类型
        try:
            doc_type = DocumentType(context.document_type)
        except ValueError:
            doc_type = DocumentType.OTHER

        required = self.PREREQUISITES.get(doc_type, [])

        if not required:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="无前置条件要求",
            )

        # 检查已上传的文档
        uploaded_types = context.metadata.get("uploaded_types", [])

        missing = [t for t in required if t not in uploaded_types]

        if missing:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"缺少前置条件文档: {', '.join([t.value for t in missing])}",
                evidence={"missing_types": [t.value for t in missing]},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="前置条件满足",
        )
