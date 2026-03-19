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
    逻辑：
    1. 从 LLM 提取的字段中获取工作单位、完成单位
    2. 从 LLM 印章描述中获取盖章单位
    3. 检查一致性：工作单位应在完成单位中，盖章单位应与完成单位一致
    """

    name = "work_unit_consistency"
    description = "工作单位与完成单位一致性检查"

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行检查"""
        extracted = context.extracted
        
        # 优先从 LLM 分析结果获取数据
        llm_analysis = extracted.get("llm_analysis")
        
        if not llm_analysis:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未找到 LLM 分析结果",
                evidence={"contributors": []},
            )
        
        # 从 LLM 提取的字段获取工作单位、完成单位
        fields = llm_analysis.get("extracted_fields", {})
        
        work_unit = fields.get("工作单位", "").strip()
        completion_unit = fields.get("完成单位", "").strip()
        
        # 从印章提取结果获取结构化印章单位
        stamp_result = llm_analysis.get("stamps_result", {})
        stamps = stamp_result.get("stamps", []) if stamp_result else []
        
        # 优先使用结构化印章数据，其次回退到解析描述文本
        if stamps:
            stamp_units = [s.get("unit", "") for s in stamps if s.get("unit")]
            stamp_source = "structure"
        else:
            stamp_units = self._parse_stamp_units(stamps_desc)
            stamp_source = "parse"
        
        if not work_unit and not completion_unit:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提取到工作单位或完成单位信息",
                evidence={"fields": fields},
            )
        
        # 一致性检查
        issues = []
        
        # 检查1：工作单位是否填写
        if not work_unit:
            issues.append("工作单位未填写")
        
        # 检查2：完成单位是否填写
        if not completion_unit:
            issues.append("完成单位未填写")
        
        # 检查3：工作单位是否在完成单位列表中（简化处理：检查是否包含）
        if work_unit and completion_unit:
            if work_unit not in completion_unit and completion_unit not in work_unit:
                issues.append(f"工作单位'{work_unit}'与完成单位'{completion_unit}'不一致")
        
        # 检查4：盖章单位应与完成单位一致
        if stamp_units and completion_unit:
            for stamp_unit in stamp_units:
                if stamp_unit and stamp_unit not in completion_unit and completion_unit not in stamp_unit:
                    issues.append(f"盖章单位'{stamp_unit}'与完成单位'{completion_unit}'不一致")
        
        # 注意：印章可能盖的是完成单位公章，不是工作单位公章
        # 因此不检查印章与工作单位的一致性
        
        if issues:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="; ".join(issues),
                evidence={
                    "work_unit": work_unit,
                    "completion_unit": completion_unit,
                    "stamp_units": stamp_units,
                    "stamp_source": stamp_source,
                    "issues": issues,
                },
            )
        
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message=f"工作单位'{work_unit}'与完成单位'{completion_unit}'一致",
            evidence={
                "work_unit": work_unit,
                "completion_unit": completion_unit,
                "stamp_units": stamp_units,
                "stamp_source": stamp_source,
            },
        )
    
    def _parse_stamp_units(self, stamps_desc: str) -> List[str]:
        """从印章描述中提取单位名称"""
        import re
        
        units = []
        
        # 匹配单位名称
        # 常见模式：XXX大学、XXX研究所、XXX公司、XXX学院等
        patterns = [
            r'([^，,\n]+大学)',
            r'([^，,\n]+研究所)',
            r'([^，,\n]+公司)',
            r'([^，,\n]+学院)',
            r'([^，,\n]+医院)',
            r'([^，,\n]+研究院)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, stamps_desc)
            units.extend(matches)
        
        # 去重
        return list(dict.fromkeys(units))
