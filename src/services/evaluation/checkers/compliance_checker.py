"""
合规性检查器

评估项目的合规性和规范性。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class ComplianceChecker(BaseChecker):
    """合规性检查器
    
    评估维度：
    - 政策符合性
    - 伦理合规
    - 规范完整
    - 预算合理性
    """
    
    dimension = EvaluationDimension.COMPLIANCE.value
    dimension_name = "合规性"
    
    def __init__(self, llm=None):
        super().__init__(llm)
        self._check_items = [
            {"name": "政策符合性", "weight": 0.3, "description": "是否符合相关政策"},
            {"name": "伦理合规", "weight": 0.25, "description": "是否符合伦理要求"},
            {"name": "规范完整", "weight": 0.25, "description": "文档是否规范完整"},
            {"name": "预算合理性", "weight": 0.2, "description": "预算是否合理合规"},
        ]
        self._required_sections = ["政策依据", "经费预算", "伦理审查", "预算说明"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行合规性检查"""
        sections = self._extract_sections(content, self._required_sections)
        
        if not sections:
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到合规性相关内容，无法进行有效评估",
                issues=["缺少政策依据或经费预算章节"],
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
        
        return f"""你是一位专业的项目评审专家，请对以下项目的合规性进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **政策符合性** (权重30%)
   - 是否符合国家/地方政策
   - 是否符合行业规范
   - 是否符合资助方要求

2. **伦理合规** (权重25%)
   - 是否符合科研伦理要求
   - 涉及人体/动物实验是否合规
   - 数据安全与隐私保护

3. **规范完整** (权重25%)
   - 申报材料是否规范
   - 内容是否完整
   - 格式是否符合要求

4. **预算合理性** (权重20%)
   - 预算编制是否合理
   - 经费分配是否合规
   - 是否符合资助方预算要求

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "政策符合性", "score": 8, "comment": "符合国家相关政策，符合行业规范..."}},
        {{"name": "伦理合规", "score": 7, "comment": "符合科研伦理要求，已获得伦理审批..."}},
        {{"name": "规范完整", "score": 8, "comment": "申报材料规范完整，格式正确..."}},
        {{"name": "预算合理性", "score": 7, "comment": "预算编制合理，经费分配合规..."}}
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