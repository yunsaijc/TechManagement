"""必填项目字段检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class RequiredProjectFieldsRule(BaseProjectRule):
    """检查项目基础字段是否缺失"""

    name = "required_project_fields"
    description = "检查必填项目字段"
    priority = 100

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        required_fields = config.get("required_project_fields", [])
        missing = []
        info = context.project_info.model_dump()

        for field in required_fields:
            value = info.get(field)
            if value in (None, "", []):
                missing.append(field)

        if missing:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"缺少必填项目字段: {', '.join(missing)}",
                evidence={"missing_fields": missing},
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="必填项目字段完整",
            evidence={"required_fields": required_fields},
        )
