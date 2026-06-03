"""
团队能力检查器

评估项目团队的整体能力和结构。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class TeamChecker(BaseChecker):
    """团队能力检查器
    
    评估维度：
    - 负责人资质
    - 团队结构
    - 成员经验
    - 分工明确性
    """
    
    dimension = EvaluationDimension.TEAM.value
    dimension_name = "团队能力"
    
    def __init__(self, llm=None, project_profile=None, dimension_overrides=None):
        super().__init__(llm, project_profile=project_profile, dimension_overrides=dimension_overrides)
        self._check_items = [
            {"name": "负责人资质", "weight": 0.3, "description": "负责人资质和业绩"},
            {"name": "团队结构", "weight": 0.25, "description": "团队结构是否合理"},
            {"name": "成员经验", "weight": 0.25, "description": "团队成员相关经验"},
            {"name": "分工明确性", "weight": 0.2, "description": "分工是否明确"},
        ]
        self._required_sections = ["项目团队", "人员分工", "成员简介", "团队介绍"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行团队能力检查"""
        sections = self._extract_sections(content, self.required_sections)
        
        if not sections:
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到团队相关内容，无法进行有效评估",
                issues=["缺少项目团队或人员分工章节"],
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
        
        return f"""你是一位专业的项目评审专家，请对以下项目团队的能力进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **负责人资质** (权重30%)
   - 负责人学术背景是否雄厚
   - 是否有相关研究经验
   - 以往科研成果如何

2. **团队结构** (权重25%)
   - 团队人员配置是否合理
   - 专业结构是否互补
   - 年龄/职称结构是否合理

3. **成员经验** (权重25%)
   - 成员是否有相关研究经验
   - 成员能力是否匹配任务
   - 团队协作历史

4. **分工明确性** (权重20%)
   - 任务分工是否明确
   - 责任划分是否清晰
   - 协作机制是否健全

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "负责人资质", "score": 8, "comment": "负责人具有丰富的研究经验..."}},
        {{"name": "团队结构", "score": 7, "comment": "团队结构合理，专业互补..."}},
        {{"name": "成员经验", "score": 7, "comment": "成员均有相关研究经历..."}},
        {{"name": "分工明确性", "score": 8, "comment": "分工明确，责任清晰..."}}
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
