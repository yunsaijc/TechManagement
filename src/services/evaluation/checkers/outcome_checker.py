"""
预期成果检查器

评估项目预期成果的质量和价值。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class OutcomeChecker(BaseChecker):
    """预期成果检查器
    
    评估维度：
    - 成果量化
    - 技术指标
    - 成果质量
    - 成果可行性
    """
    
    dimension = EvaluationDimension.OUTCOME.value
    dimension_name = "预期成果"
    ALTERNATIVE_SECTION_KEYS = [
        "项目绩效评价考核目标及指标",
        "主要指标、效益",
        "建设目标",
        "核心建设内容",
        "科普基础设施建设",
        "科普内容产出",
        "科普活动开展",
    ]
    
    def __init__(self, llm=None, project_profile=None, dimension_overrides=None):
        super().__init__(llm, project_profile=project_profile, dimension_overrides=dimension_overrides)
        self._check_items = [
            {"name": "成果量化", "weight": 0.25, "description": "成果是否可量化考核"},
            {"name": "技术指标", "weight": 0.3, "description": "技术指标是否先进"},
            {"name": "成果质量", "weight": 0.25, "description": "预期成果质量如何"},
            {"name": "成果可行性", "weight": 0.2, "description": "成果目标是否可实现"},
        ]
        self._required_sections = ["预期成果", "考核指标", "技术指标", "成果形式"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行预期成果检查"""
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
                        opinion="该项目更偏平台建设或科普实施类，已基于绩效指标、内容产出和建设目标进行基础成果判断，不再强制要求独立预期成果章节。",
                        issues=["未设置独立预期成果章节，已按绩效指标与建设产出内容替代评估"],
                        highlights=[f"已识别章节：{name}" for name in matched_names[:3]],
                        items=[],
                    )
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到预期成果相关内容，无法进行有效评估",
                issues=["缺少预期成果或考核指标章节"],
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
        
        return f"""你是一位专业的项目评审专家，请对以下项目的预期成果进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **成果量化** (权重25%)
   - 成果是否可量化
   - 考核指标是否明确
   - 是否有具体的量化标准

2. **技术指标** (权重30%)
   - 技术指标是否先进
   - 指标是否具有挑战性
   - 与国内外水平对比

3. **成果质量** (权重25%)
   - 预期成果的水平
   - 成果的学术/应用价值
   - 成果的完整性

4. **成果可行性** (权重20%)
   - 成果目标是否可实现
   - 完成条件是否具备
   - 时间安排是否合理

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "成果量化", "score": 8, "comment": "成果指标明确可量化..."}},
        {{"name": "技术指标", "score": 7, "comment": "技术指标达到国内领先水平..."}},
        {{"name": "成果质量", "score": 8, "comment": "预期成果具有较高的应用价值..."}},
        {{"name": "成果可行性", "score": 7, "comment": "成果目标基本可实现..."}}
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
                weight = 0.25
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
