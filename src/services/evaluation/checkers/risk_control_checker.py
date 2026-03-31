"""
风险控制检查器

评估项目风险识别和控制措施。
"""
import json
from typing import Any, Dict

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
        
        if not sections:
            if self.profile_matches(
                content,
                self.PROJECT_PROFILE_PLATFORM,
                self.PROJECT_PROFILE_SCIENCE_POPULARIZATION,
            ):
                alternative_sections = self._extract_sections(
                    content,
                    self.get_alternative_sections(self.ALTERNATIVE_SECTION_KEYS),
                )
                if alternative_sections:
                    matched_names = list(alternative_sections.keys())
                    return CheckResult(
                        dimension=self.dimension,
                        dimension_name=self.dimension_name,
                        score=6.0,
                        confidence=0.45,
                        opinion="该项目更偏平台建设或科普实施类，已基于组织保障、实施安排和资源配置进行基础风险判断，不再强制要求独立风险章节。",
                        issues=["未设置独立风险章节，已按组织实施与保障内容替代评估"],
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
        
        prompt = self._build_prompt(sections)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_result(response.content if hasattr(response, 'content') else str(response))
        
        return result

    
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
