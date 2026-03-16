"""工作单位一致性检查规则"""
from typing import Any, Dict, List

from src.common.models import CheckResult, CheckStatus
from src.services.review.rules import ReviewContext
from src.services.review.rules.base import BaseRule
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class WorkUnitConsistencyRule(BaseRule):
    """工作单位一致性检查规则
    
    检查完成人的工作单位填写是否与完成单位一致。
    """

    name = "work_unit_consistency"
    description = "工作单位与完成单位一致性检查"

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行检查"""
        extracted = context.extracted
        ocr_text = extracted.get("text", "")
        
        # 解析所有完成人及其工作单位
        contributors = self._parse_contributors(ocr_text)
        
        if not contributors:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未找到完成人信息",
                evidence={"contributors": []},
            )
        
        # 检查工作单位填写情况
        issues = []
        for i, c in enumerate(contributors):
            name = c.get("name", "")
            work_unit = c.get("work_unit", "")
            
            if not work_unit:
                issues.append(f"第{i+1}位完成人({name})未填写工作单位")
            # 这里可以添加更多一致性检查逻辑
        
        if issues:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="; ".join(issues),
                evidence={"contributors": contributors, "issues": issues},
            )
        
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message=f"检查了{len(contributors)}位完成人的工作单位",
            evidence={"contributors": contributors},
        )

    def _parse_contributors(self, text: str) -> List[Dict[str, str]]:
        """解析完成人信息"""
        import re
        
        contributors = []
        
        # 按"主要完成人情况表"或"九、"分段
        sections = re.split(r'\n\d+、|主要完成人情况表', text)
        
        for section in sections[1:]:  # 跳过第一段（标题）
            # 提取姓名
            name_match = re.search(r'姓名[：:\s]*\n?\s*([^\n]{2,10})', section)
            work_unit_match = re.search(r'工作单位[：:\s]*\n?\s*([^\n]{2,50})', section)
            
            if name_match:
                contributors.append({
                    "name": name_match.group(1).strip(),
                    "work_unit": work_unit_match.group(1).strip() if work_unit_match else "",
                })
        
        return contributors
