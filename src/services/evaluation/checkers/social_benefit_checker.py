"""
社会效益检查器

评估项目的社会效益和推广应用价值。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class SocialBenefitChecker(BaseChecker):
    """社会效益检查器
    
    评估维度：
    - 社会贡献
    - 推广价值
    - 人才培养
    - 学科发展
    """
    
    dimension = EvaluationDimension.SOCIAL_BENEFIT.value
    dimension_name = "社会效益"
    
    def __init__(self, llm=None):
        super().__init__(llm)
        self._check_items = [
            {"name": "社会贡献", "weight": 0.3, "description": "对社会发展的贡献"},
            {"name": "推广价值", "weight": 0.3, "description": "成果推广应用价值"},
            {"name": "人才培养", "weight": 0.2, "description": "对人才培养的贡献"},
            {"name": "学科发展", "weight": 0.2, "description": "对学科发展的推动"},
        ]
        self._required_sections = ["预期效益", "社会效益", "推广应用", "效益分析"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行社会效益检查"""
        sections = self._extract_sections(content, self._required_sections)
        
        if not sections:
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到社会效益相关内容，无法进行有效评估",
                issues=["缺少预期效益或社会效益章节"],
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
        
        return f"""你是一位专业的项目评审专家，请对以下项目的社会效益进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **社会贡献** (权重30%)
   - 对社会发展有何贡献
   - 能否解决社会问题
   - 社会影响力如何

2. **推广价值** (权重30%)
   - 成果能否推广应用
   - 应用范围有多广
   - 推广可行性如何

3. **人才培养** (权重20%)
   - 对人才培养的贡献
   - 研究生培养计划
   - 团队能力提升

4. **学科发展** (权重20%)
   - 对学科发展的推动
   - 学术影响力
   - 学科交叉融合

## 输出格式

请以JSON格式输出：
```json
{{
    "items": [
        {{"name": "社会贡献", "score": 7, "comment": "项目能够解决...社会问题"}},
        {{"name": "推广价值", "score": 8, "comment": "成果可在...领域推广应用"}},
        {{"name": "人才培养", "score": 7, "comment": "预计培养研究生..."}},
        {{"name": "学科发展", "score": 6, "comment": "对学科发展有一定推动作用"}}
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