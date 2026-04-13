"""单位注册时间检查"""
from datetime import date, datetime

from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class RegisteredDateLimitRule(BaseProjectRule):
    """检查单位注册时间限制"""

    name = "registered_date_limit"
    description = "检查单位注册时间是否晚于政策要求"
    priority = 95

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        constraints = config.get("constraints", {})
        limit_text = constraints.get("registered_after")
        if not limit_text:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="未配置注册时间限制",
                evidence={},
            )

        registered_date = self._parse_date(context.project_info.registered_date)
        limit_date = self._parse_date(limit_text)
        if not limit_date:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="注册时间限制配置无效",
                evidence={"registered_after": limit_text},
            )
        if not registered_date:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提供单位注册时间，无法自动核验注册时间限制",
                evidence={"registered_after": limit_text},
            )

        if registered_date > limit_date:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"单位注册时间不符合要求: {registered_date} 晚于 {limit_date}",
                evidence={
                    "registered_date": registered_date.isoformat(),
                    "registered_after": limit_date.isoformat(),
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="单位注册时间符合要求",
            evidence={
                "registered_date": registered_date.isoformat(),
                "registered_after": limit_date.isoformat(),
            },
        )

    def _parse_date(self, value: str | date | None) -> date | None:
        """解析日期"""
        if not value:
            return None
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None
