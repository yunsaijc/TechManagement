"""
风险控制检查器

评估项目风险识别和控制措施。
"""
import re
import json
from typing import Any, Dict, List

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class RiskControlChecker(BaseChecker):
    """风险控制检查器
    
    评估维度：
    - 风险识别
    - 风险分析
    - 应对措施
    """
    
    dimension = EvaluationDimension.RISK_CONTROL.value
    dimension_name = "风险控制"
    RISK_TYPE_KEYWORDS = (
        "技术风险",
        "市场风险",
        "政策风险",
        "实施制约因素",
        "数据风险",
        "安全风险",
        "管理风险",
        "进度风险",
        "财务风险",
    )
    ANALYSIS_KEYWORDS = ("影响", "概率", "可能", "难度", "瓶颈", "制约", "挑战", "波动")
    MITIGATION_KEYWORDS = ("对策", "措施", "预案", "应急", "建立", "采用", "完善", "保障", "协调")
    ALTERNATIVE_SECTION_KEYS = [
        "项目简介",
        "主要内容及实施地点",
        "项目组织实施机制",
        "组织支撑条件",
        "资源支撑条件",
        "项目组主要成员",
        "项目绩效评价考核目标及指标",
    ]
    
    def __init__(self, llm=None, project_profile=None, dimension_overrides=None):
        super().__init__(llm, project_profile=project_profile, dimension_overrides=dimension_overrides)
        self._check_items = [
            {"name": "风险识别", "weight": 0.35, "description": "风险识别是否全面"},
            {"name": "风险分析", "weight": 0.3, "description": "风险分析是否深入"},
            {"name": "应对措施", "weight": 0.35, "description": "应对措施是否有效"},
        ]
        self._required_sections = ["风险分析", "风险控制", "风险管理", "风险应对"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行风险控制检查"""
        sections = self._extract_sections(content, self.required_sections)
        required_hits = self.get_required_evidence_hits(content)
        alternative_hits = self.get_alternative_evidence_hits(content)
        use_alternative_only = not required_hits and bool(alternative_hits)
        
        if not sections or use_alternative_only:
            if self.profile_matches(
                content,
                self.PROJECT_PROFILE_PLATFORM,
                self.PROJECT_PROFILE_SCIENCE_POPULARIZATION,
                "demonstration",
            ):
                alternative_sections = self._extract_sections(
                    content,
                    self.get_alternative_sections(self.ALTERNATIVE_SECTION_KEYS),
                )
                if alternative_sections:
                    matched_names = required_hits or alternative_hits or list(alternative_sections.keys())
                    return CheckResult(
                        dimension=self.dimension,
                        dimension_name=self.dimension_name,
                        score=6.0,
                        confidence=0.45,
                        opinion=(
                            "该项目更偏平台建设、科普实施或示范应用类，当前未命中独立风险章节，"
                            f"已基于{chr(12289).join(matched_names[:3])}等替代材料进行基础风险判断，不再强制要求独立风险章节。"
                        ),
                        issues=[f"未设置独立风险章节，已按{chr(12289).join(matched_names[:2])}等替代内容评估"],
                        highlights=[f"已识别章节：{name}" for name in matched_names[:3]],
                        items=[],
                    )
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到风险控制相关内容，无法进行有效评估",
                issues=["缺少风险分析或风险控制章节"],
                highlights=[],
                items=[],
            )

        return self._build_rule_based_result(content, sections)

    def _build_rule_based_result(self, content: Dict[str, Any], sections: Dict[str, Any]) -> CheckResult:
        """基于显式风险章节生成稳定结果"""
        raw_sections = {
            key: value
            for key, value in content.items()
            if not str(key).startswith("_") and isinstance(value, (str, int, float))
        }
        merged_text = self._merge_section_text(raw_sections or sections)
        risk_type_hits = self._collect_risk_type_hits(raw_sections or sections, merged_text)
        has_analysis = any(keyword in merged_text for keyword in self.ANALYSIS_KEYWORDS)
        has_probability = any(keyword in merged_text for keyword in ("概率", "可能", "影响"))
        has_mitigation = any(keyword in merged_text for keyword in self.MITIGATION_KEYWORDS)
        has_backup = any(keyword in merged_text for keyword in ("备选", "替代", "预案", "应急"))

        items: List[CheckItem] = [
            CheckItem(
                name="风险识别",
                score=self._score_risk_identification(risk_type_hits),
                weight=0.35,
                comment=self._comment_risk_identification(risk_type_hits),
            ),
            CheckItem(
                name="风险分析",
                score=self._score_risk_analysis(has_analysis, has_probability),
                weight=0.3,
                comment=self._comment_risk_analysis(has_analysis, has_probability),
            ),
            CheckItem(
                name="应对措施",
                score=self._score_mitigation(has_mitigation, has_backup),
                weight=0.35,
                comment=self._comment_mitigation(has_mitigation, has_backup),
            ),
        ]

        total_score = self._calculate_weighted_score(items)
        if total_score >= 7.5:
            opinion = "项目已识别主要风险并配套了较清晰的控制措施，整体风险控制基础较好。"
        elif total_score >= 6.0:
            opinion = "项目已识别部分主要风险并给出基础应对思路，但在分析深度或预案完整性上仍可加强。"
        else:
            opinion = "项目风险控制论证较弱，风险识别、分析或应对措施仍存在明显缺口。"

        issues = [item.comment for item in items if item.score <= 6.0][:3]
        highlights = [item.comment for item in items if item.score >= 7.0][:2]

        return CheckResult(
            dimension=self.dimension,
            dimension_name=self.dimension_name,
            score=total_score,
            confidence=0.72,
            opinion=opinion,
            issues=issues,
            highlights=highlights,
            items=items,
        )

    def _collect_risk_type_hits(self, sections: Dict[str, Any], merged_text: str) -> List[str]:
        """收集命中的风险类型"""
        hits: List[str] = []
        section_names = " ".join(sections.keys())
        for keyword in self.RISK_TYPE_KEYWORDS:
            if keyword in section_names or keyword in merged_text:
                hits.append(keyword)
        return hits

    def _score_risk_identification(self, risk_type_hits: List[str]) -> float:
        """风险识别评分"""
        unique_count = len(set(risk_type_hits))
        if unique_count >= 4:
            return 7.6
        if unique_count >= 3:
            return 7.0
        if unique_count >= 2:
            return 6.4
        if unique_count >= 1:
            return 5.8
        return 5.0

    def _comment_risk_identification(self, risk_type_hits: List[str]) -> str:
        """风险识别评语"""
        unique_hits = list(dict.fromkeys(risk_type_hits))
        if len(unique_hits) >= 3:
            return f"已覆盖{chr(12289).join(unique_hits[:3])}等主要风险类型，风险识别较为完整。"
        if len(unique_hits) == 2:
            return f"已识别{chr(12289).join(unique_hits)}两类主要风险，但覆盖面仍可继续拓展。"
        if len(unique_hits) == 1:
            return f"主要识别了{unique_hits[0]}，其余风险类型展开不足。"
        return "文中仅有原则性风险表述，未形成清晰的风险分类。"

    def _score_risk_analysis(self, has_analysis: bool, has_probability: bool) -> float:
        """风险分析评分"""
        if has_analysis and has_probability:
            return 6.8
        if has_analysis:
            return 6.1
        if has_probability:
            return 5.8
        return 5.2

    def _comment_risk_analysis(self, has_analysis: bool, has_probability: bool) -> str:
        """风险分析评语"""
        if has_analysis and has_probability:
            return "对风险影响和发生可能性均有一定分析，风险分析具备基础深度。"
        if has_analysis:
            return "对主要风险有定性分析，但发生概率或优先级判断仍不够明确。"
        if has_probability:
            return "提到了风险影响或可能性，但缺少更系统的原因分析。"
        return "风险分析以原则性描述为主，缺少影响程度或发生可能性的展开。"

    def _score_mitigation(self, has_mitigation: bool, has_backup: bool) -> float:
        """应对措施评分"""
        if has_mitigation and has_backup:
            return 7.2
        if has_mitigation:
            return 6.4
        if has_backup:
            return 6.0
        return 5.2

    def _comment_mitigation(self, has_mitigation: bool, has_backup: bool) -> str:
        """应对措施评语"""
        if has_mitigation and has_backup:
            return "已提出具体控制措施，并体现了一定的预案或替代安排。"
        if has_mitigation:
            return "已提出基础控制措施，但预案冗余和备选安排仍可加强。"
        if has_backup:
            return "提到了预案思路，但缺少与具体风险项对应的控制措施。"
        return "应对措施表述较少，尚未形成清晰的控制安排。"

    def _merge_section_text(self, sections: Dict[str, Any]) -> str:
        """合并章节文本"""
        return "\n".join(str(value or "") for value in sections.values())

    
    def _build_prompt(self, content: Dict[str, Any]) -> str:
        """构建提示词"""
        content_text = self._format_content_for_prompt(content)
        
        return f"""你是一位专业的项目评审专家，请对以下项目的风险控制进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下3个方面进行评估，每项给出1-10分的评分和简要评语：

1. **风险识别** (权重35%)
   - 风险识别是否全面
   - 是否涵盖技术、管理、财务等各方面
   - 潜在风险是否充分考虑

2. **风险分析** (权重30%)
   - 风险分析是否深入
   - 风险影响程度评估
   - 风险发生概率分析

3. **应对措施** (权重35%)
   - 应对措施是否有效
   - 措施是否具体可行
   - 是否有备选方案

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "风险识别", "score": 7, "comment": "识别了主要风险点，但遗漏了..."}},
        {{"name": "风险分析", "score": 6, "comment": "风险分析较为深入，但对...影响评估不足"}},
        {{"name": "应对措施", "score": 7, "comment": "应对措施基本可行，建议增加..."}}
    ],
    "opinion": "综合评价...",
    "issues": ["问题1"],
    "highlights": ["亮点1"],
    "confidence": 0.85
}}
```"""

    def _parse_result(self, llm_output: str) -> CheckResult:
        """解析LLM输出"""
        try:
            json_str = llm_output
            if "```json" in llm_output:
                json_str = llm_output.split("```json")[1].split("```")[0]
            elif "```" in llm_output:
                json_str = llm_output.split("```")[1].split("```")[0]
            
            data = json.loads(json_str.strip())
            
            items = []
            for item_data in data.get("items", []):
                weight = 0.33
                for check_item in self._check_items:
                    if check_item["name"] == item_data["name"]:
                        weight = check_item["weight"]
                        break
                
                items.append(CheckItem(
                    name=item_data["name"],
                    score=float(item_data.get("score", 5)),
                    weight=weight,
                    comment=item_data.get("comment", ""),
                ))
            
            total_score = self._calculate_weighted_score(items)
            
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=total_score,
                confidence=float(data.get("confidence", 0.7)),
                opinion=data.get("opinion", ""),
                issues=data.get("issues", []),
                highlights=data.get("highlights", []),
                items=items,
            )
            
        except Exception as e:
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion=f"评审解析失败: {str(e)}",
                issues=["评审结果解析异常"],
                highlights=[],
                items=[],
            )
