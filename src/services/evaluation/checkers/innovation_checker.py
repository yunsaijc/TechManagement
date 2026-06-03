"""
创新性检查器

评估项目的创新程度和技术突破。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class InnovationChecker(BaseChecker):
    """创新性检查器
    
    评估维度：
    - 理论创新
    - 技术创新
    - 方法创新
    - 创新可行性
    """
    
    dimension = EvaluationDimension.INNOVATION.value
    dimension_name = "创新性"
    
    def __init__(self, llm=None, project_profile=None, dimension_overrides=None):
        super().__init__(llm, project_profile=project_profile, dimension_overrides=dimension_overrides)
        self._check_items = [
            {"name": "理论创新", "weight": 0.3, "description": "是否有理论创新"},
            {"name": "技术创新", "weight": 0.3, "description": "是否有技术创新"},
            {"name": "方法创新", "weight": 0.2, "description": "是否有方法创新"},
            {"name": "创新可行性", "weight": 0.2, "description": "创新点是否切实可行"},
        ]
        self._required_sections = ["创新点", "技术方案", "研究内容"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行创新性检查"""
        sections = self._extract_sections(content, self.required_sections)
        
        if not sections:
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到创新点相关内容，无法进行有效评估",
                issues=["缺少创新点或研究内容章节"],
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
        
        return f"""你是一位专业的项目评审专家，请对以下项目的创新性进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **理论创新** (权重30%)
   - 是否提出新的理论观点
   - 理论创新程度如何
   - 理论价值有多大

2. **技术创新** (权重30%)
   - 是否有技术突破
   - 技术创新程度如何
   - 技术先进性如何

3. **方法创新** (权重20%)
   - 研究方法是否有创新
   - 方法创新的价值
   - 是否可推广应用

4. **创新可行性** (权重20%)
   - 创新点是否切实可行
   - 实现创新的条件是否具备
   - 创新风险是否可控

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "理论创新", "score": 7, "comment": "提出了新的理论框架..."}},
        {{"name": "技术创新", "score": 8, "comment": "关键技术有突破..."}},
        {{"name": "方法创新", "score": 6, "comment": "研究方法有一定新意..."}},
        {{"name": "创新可行性", "score": 7, "comment": "创新点基本可行..."}}
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
