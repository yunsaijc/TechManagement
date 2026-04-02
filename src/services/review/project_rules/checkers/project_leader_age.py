"""项目负责人年龄限制检查"""
from datetime import date, datetime

from src.common.models import CheckResult, CheckStatus
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class ProjectLeaderAgeCheckRule(BaseProjectRule):
    """检查项目负责人年龄限制"""

    name = "project_leader_age_check"
    description = "检查项目负责人是否满足出生日期限制"
    priority = 94
    LIMIT_DATE = date(1967, 1, 1)

    async def check(self, context):
        birth_date = self._parse_date(context.project_info.project_leader_birth_date)
        if not birth_date:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提供项目负责人出生日期，无法自动核验年龄限制",
                evidence={"limit_birth_date": self.LIMIT_DATE.isoformat()},
            )

        if birth_date < self.LIMIT_DATE:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"项目负责人出生日期不符合要求: {birth_date} 早于 {self.LIMIT_DATE}",
                evidence={
                    "project_leader_birth_date": birth_date.isoformat(),
                    "limit_birth_date": self.LIMIT_DATE.isoformat(),
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="项目负责人年龄符合要求",
            evidence={
                "project_leader_birth_date": birth_date.isoformat(),
                "limit_birth_date": self.LIMIT_DATE.isoformat(),
            },
        )

    def _parse_date(self, value: str | date | None) -> date | None:
        """解析日期"""
        if not value:
            return None
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m", "%Y.%m"):
            try:
                parsed = datetime.strptime(text, fmt)
                if fmt in {"%Y-%m", "%Y/%m", "%Y.%m"}:
                    return date(parsed.year, parsed.month, 1)
                return parsed.date()
            except ValueError:
                continue
        return None
