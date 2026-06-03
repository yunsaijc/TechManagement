"""
技术可行性检查器

评估项目技术路线的可行性和合理性。
"""
import json
from typing import Any, Dict

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from .base import BaseChecker


class FeasibilityChecker(BaseChecker):
    """技术可行性检查器
    
    评估维度：
    - 技术路线清晰度
    - 关键技术成熟度
    - 资源保障充分性
    - 实施条件完备性
    """
    
    dimension = EvaluationDimension.FEASIBILITY.value
    dimension_name = "技术可行性"
    ALTERNATIVE_SECTION_KEYS = [
        "实施内容",
        "建设目标",
        "主要内容及实施地点",
        "活动策划",
        "资源开发",
        "协同推广",
        "基层能力辐射工程",
        "数字化资源库建设",
        "科普基础设施建设",
        "科普内容产出",
        "科普活动开展",
    ]
    
    def __init__(self, llm=None, project_profile=None, dimension_overrides=None):
        super().__init__(llm, project_profile=project_profile, dimension_overrides=dimension_overrides)
        self._check_items = [
            {"name": "技术路线清晰度", "weight": 0.3, "description": "技术路线是否清晰、具体"},
            {"name": "关键技术成熟度", "weight": 0.3, "description": "关键技术是否成熟可靠"},
            {"name": "资源保障充分性", "weight": 0.2, "description": "所需资源是否有保障"},
            {"name": "实施条件完备性", "weight": 0.2, "description": "实施条件是否完备"},
        ]
        self._required_sections = ["技术路线", "研究方案", "实施方案"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行技术可行性检查
        
        Args:
            content: 文档内容字典
            
        Returns:
            CheckResult: 检查结果
        """
        # 提取相关章节
        sections = self._extract_sections(content, self.required_sections)
        required_hits = self.get_required_evidence_hits(content)
        alternative_hits = self.get_alternative_evidence_hits(content)
        use_alternative_only = not required_hits and bool(alternative_hits)

        # 如果没有相关内容，返回默认结果
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
                            "该项目更偏平台建设、科普实施或示范应用类，当前未命中独立技术路线章节，"
                            f"已基于{chr(12289).join(matched_names[:3])}等替代材料进行基础可行性判断，不再强制要求独立技术路线章节。"
                        ),
                        issues=[f"未设置独立技术路线章节，已按{chr(12289).join(matched_names[:2])}等替代内容评估"],
                        highlights=[f"已识别章节：{name}" for name in matched_names[:3]],
                        items=[],
                    )
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion="未找到技术路线相关内容，无法进行有效评估",
                issues=["缺少技术路线或研究方案章节"],
                highlights=[],
                items=[],
            )
        
        # 构建提示词
        prompt = self._build_prompt(sections)
        
        # 调用LLM
        response = await self.llm.ainvoke(prompt)
        
        # 解析结果
        result = self._parse_result(response.content if hasattr(response, 'content') else str(response))
        
        return result

    
    def _build_prompt(self, content: Dict[str, Any]) -> str:
        """构建提示词"""
        content_text = self._format_content_for_prompt(content)
        
        prompt = f"""你是一位专业的项目评审专家，请对以下项目的技术可行性进行评估。

## 评审内容

{content_text}

## 评审要求

请从以下4个方面进行评估，每项给出1-10分的评分和简要评语：

1. **技术路线清晰度** (权重30%)
   - 技术路线是否清晰明确
   - 技术方案是否具体可行
   - 技术步骤是否逻辑连贯

2. **关键技术成熟度** (权重30%)
   - 关键技术是否已经验证
   - 技术难度是否可控
   - 是否有技术储备

3. **资源保障充分性** (权重20%)
   - 设备、资金是否有保障
   - 人力资源是否充足
   - 外部支持是否到位

4. **实施条件完备性** (权重20%)
   - 实验条件是否具备
   - 合作条件是否成熟
   - 管理制度是否健全

## 输出格式

请以JSON格式输出，格式如下：
```json
{{
    "items": [
        {{
            "name": "技术路线清晰度",
            "score": 8,
            "comment": "技术路线清晰，方案具体可行..."
        }},
        {{
            "name": "关键技术成熟度",
            "score": 7,
            "comment": "核心技术已有初步验证..."
        }},
        {{
            "name": "资源保障充分性",
            "score": 6,
            "comment": "资金基本到位，但设备采购..."
        }},
        {{
            "name": "实施条件完备性",
            "score": 8,
            "comment": "实验条件具备..."
        }}
    ],
    "opinion": "综合评价...",
    "issues": ["问题1", "问题2"],
    "highlights": ["亮点1", "亮点2"],
    "confidence": 0.85
}}
```

请确保输出为有效的JSON格式。"""
        return prompt
    
    def _parse_result(self, llm_output: str) -> CheckResult:
        """解析LLM输出"""
        try:
            # 尝试提取JSON
            json_str = llm_output
            if "```json" in llm_output:
                json_str = llm_output.split("```json")[1].split("```")[0]
            elif "```" in llm_output:
                json_str = llm_output.split("```")[1].split("```")[0]
            
            data = json.loads(json_str.strip())
            
            # 构建检查项
            items = []
            for item_data in data.get("items", []):
                # 查找对应的权重
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
            
            # 计算总分
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
            # 解析失败，返回默认结果
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
