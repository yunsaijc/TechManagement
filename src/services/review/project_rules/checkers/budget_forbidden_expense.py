"""经费禁列项检查"""
from src.common.models import CheckResult, CheckStatus
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class BudgetForbiddenExpenseCheckRule(BaseProjectRule):
    """检查预算中是否包含禁列项"""

    name = "budget_forbidden_expense_check"
    description = "检查预算科目中是否出现间接经费、绩效支出及禁列用途"
    priority = 63

    FORBIDDEN_TERMS = [
        "间接经费",
        "绩效支出",
        "罚款",
        "捐款",
        "赞助",
        "投资",
        "偿还债务",
    ]

    async def check(self, context):
        budget_lines = [str(line).strip() for line in context.project_info.budget_line_items if str(line).strip()]
        if not budget_lines:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提取到预算科目明细，暂无法自动核验经费禁列项",
                evidence={},
            )

        hits = []
        for line in budget_lines:
            normalized = line.replace(" ", "")
            for term in self.FORBIDDEN_TERMS:
                if term in normalized:
                    hits.append({"term": term, "line": line})

        if hits:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="预算中发现疑似禁列项",
                evidence={
                    "forbidden_hits": hits[:20],
                    "budget_line_count": len(budget_lines),
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="预算中未发现禁列项关键词",
            evidence={
                "budget_line_count": len(budget_lines),
                "checked_terms": self.FORBIDDEN_TERMS,
                "sample_budget_lines": budget_lines[:10],
            },
        )
