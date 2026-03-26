"""
经济效益检查器

评估项目的经济效益和产业化前景。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class EconomicBenefitChecker(BaseChecker):
    """经济效益检查器
    
    评估维度：
    - 直接经济效益
    - 间接经济效益
    - 产业化前景
    - 经济效益可行性
    """
    
    dimension = EvaluationDimension.ECONOMIC_BENEFIT.value
    dimension_name = "经济效益"
    
    def __init__(self, llm=None):
        super().__init__(llm)
        self._check_items = [
            {"name": "直接经济效益", "weight": 0.3, "description": "直接产生的经济效益"},
            {"name": "间接经济效益", "weight": 0.25, "description": "间接带来的经济效益"},
            {"name": "产业化前景", "weight": 0.25, "description": "产业化应用前景"},
            {"name": "经济效益可行性", "weight": 0.2, "description": "效益预期是否合理"},
        ]
        self._required_sections = ["预期效益", "经济效益", "产业化", "效益分析"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行经济效益检查"""
        sections = self._extract_sections(content, self._required_sections)
        
        if not sections:
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到经济效益相关内容，无法进行有效评估",
                issues=["缺少预期效益或经济效益章节"],
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
        
        return f"""你是一位专业的项目评审专家，请对以下项目的经济效益进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **直接经济效益** (权重30%)
   - 直接产生的经济效益大小
   - 经济效益的量化指标
   - 效益实现的时间周期

2. **间接经济效益** (权重25%)
   - 带动相关产业发展
   - 创造就业机会
   - 技术溢出效应

3. **产业化前景** (权重25%)
   - 产业化应用的可能性
   - 市场需求规模
   - 竞争优势

4. **经济效益可行性** (权重20%)
   - 效益预期是否合理
   - 实现条件是否具备
   - 风险因素分析

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "直接经济效益", "score": 7, "comment": "预计产生直接经济效益...万元"}},
        {{"name": "间接经济效益", "score": 6, "comment": "可带动相关产业..."}},
        {{"name": "产业化前景", "score": 7, "comment": "产业化应用前景较好..."}},
        {{"name": "经济效益可行性", "score": 6, "comment": "效益预期基本合理..."}}
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