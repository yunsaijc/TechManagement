"""
合规性检查器

评估项目的合规性和规范性。
"""
import asyncio
import json
import re
from typing import Any, Dict, List

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
    MAX_PROMPT_SECTIONS = 3
    MAX_PROMPT_SECTION_CHARS = 1200
    MAX_PROMPT_TOTAL_CHARS = 3200
    ITEM_SECTION_MAP = {
        "政策符合性": ["政策依据"],
        "伦理合规": ["伦理审查"],
        "规范完整": ["政策依据", "伦理审查", "预算说明"],
        "预算合理性": ["经费预算", "预算说明"],
    }
    POLICY_TITLE_PATTERN = re.compile(r"《[^》]{2,40}》")
    AMOUNT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*万元")
    PLACEHOLDER_PATTERN = re.compile(r"(请填写|待补充|模板|示例|此处填写|XXXX|xxx)")
    
    def __init__(self, llm=None, project_profile=None, dimension_overrides=None):
        super().__init__(llm, project_profile=project_profile, dimension_overrides=dimension_overrides)
        self._check_items = [
            {"name": "政策符合性", "weight": 0.3, "description": "是否符合相关政策"},
            {"name": "伦理合规", "weight": 0.25, "description": "是否符合伦理要求"},
            {"name": "规范完整", "weight": 0.25, "description": "文档是否规范完整"},
            {"name": "预算合理性", "weight": 0.2, "description": "预算是否合理合规"},
        ]
        self._required_sections = ["政策依据", "经费预算", "伦理审查", "预算说明"]
    
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行合规性检查"""
        sections = self._extract_sections(content, self.required_sections)
        
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

        items = await self._evaluate_items(sections)
        return self._build_result_from_items(items)
    
    def _build_prompt(self, content: Dict[str, Any]) -> str:
        """构建兼容旧路径的完整提示词"""
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

    async def _evaluate_items(self, sections: Dict[str, Any]) -> List[CheckItem]:
        """按检查项拆分小请求，降低超时概率"""
        tasks = [
            asyncio.create_task(self._evaluate_single_item(item, sections))
            for item in self._check_items
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items: List[CheckItem] = []
        for item_config, result in zip(self._check_items, results):
            if isinstance(result, Exception):
                items.append(
                    CheckItem(
                        name=item_config["name"],
                        score=5.0,
                        weight=item_config["weight"],
                        comment=f"子项评审超时或异常：{str(result)}",
                    )
                )
                continue
            items.append(result)
        return items

    async def _evaluate_single_item(self, item: Dict[str, Any], sections: Dict[str, Any]) -> CheckItem:
        """执行单个检查项评估"""
        item_name = item["name"]
        item_sections = self._select_item_sections(sections, item_name)
        rule_item = self._evaluate_item_by_rule(
            item_name=item_name,
            weight=float(item["weight"]),
            item_sections=item_sections,
            all_sections=sections,
        )
        if rule_item:
            return rule_item

        prompt = self._build_item_prompt(item_name, item["description"], item_sections)
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = self._parse_item_result(response.content if hasattr(response, "content") else str(response))
            return CheckItem(
                name=item_name,
                score=parsed["score"],
                weight=item["weight"],
                comment=parsed["comment"],
            )
        except Exception as exc:
            return CheckItem(
                name=item_name,
                score=5.0,
                weight=item["weight"],
                comment=f"子项评审超时或异常：{str(exc)}",
            )

    def _select_item_sections(self, sections: Dict[str, Any], item_name: str) -> Dict[str, Any]:
        """为单个检查项选择最相关章节"""
        selected: Dict[str, Any] = {}
        for section_name in self.ITEM_SECTION_MAP.get(item_name, []):
            if section_name in sections:
                selected[section_name] = sections[section_name]
        if selected:
            return selected

        if item_name != "规范完整":
            return {}

        for section_name, text in list(sections.items())[:2]:
            selected[section_name] = text
        return selected

    def _evaluate_item_by_rule(
        self,
        item_name: str,
        weight: float,
        item_sections: Dict[str, Any],
        all_sections: Dict[str, Any],
    ) -> CheckItem:
        """基于显式材料证据生成更稳定的合规性子项结果"""
        handlers = {
            "政策符合性": self._evaluate_policy_item,
            "伦理合规": self._evaluate_ethics_item,
            "规范完整": self._evaluate_completeness_item,
            "预算合理性": self._evaluate_budget_item,
        }
        handler = handlers.get(item_name)
        if not handler:
            return CheckItem(name=item_name, score=5.0, weight=weight, comment="未配置该合规检查项规则。")
        score, comment = handler(item_sections=item_sections, all_sections=all_sections)
        return CheckItem(
            name=item_name,
            score=max(1.0, min(10.0, round(score, 2))),
            weight=weight,
            comment=comment,
        )

    def _evaluate_policy_item(
        self,
        item_sections: Dict[str, Any],
        all_sections: Dict[str, Any],
    ) -> tuple[float, str]:
        """评估政策符合性"""
        if not item_sections:
            return 5.0, "文中未见明确政策依据或指南条款对应说明。"

        text = self._merge_section_text(item_sections)
        title_hits = self.POLICY_TITLE_PATTERN.findall(text)
        keyword_hits = sum(
            1
            for keyword in ("政策", "规划", "意见", "通知", "办法", "指南", "战略", "行动计划", "法律")
            if keyword in text
        )

        if len(title_hits) >= 2 or keyword_hits >= 4:
            return 7.5, "列举了多项政策或规划依据，政策符合性基础较明确，建议补充与指南条款的对应关系。"
        if len(title_hits) >= 1 or keyword_hits >= 2:
            return 6.5, "提到了相关政策依据，但与本次申报指南的对应关系仍可进一步细化。"
        return 6.0, "有政策表述，但政策名称或条款依据不够具体。"

    def _evaluate_ethics_item(
        self,
        item_sections: Dict[str, Any],
        all_sections: Dict[str, Any],
    ) -> tuple[float, str]:
        """评估伦理合规"""
        if not item_sections:
            return 5.0, "文中未见独立伦理审查、知情同意或数据隐私说明。"

        text = self._merge_section_text(item_sections)
        positive_hits = sum(
            1
            for keyword in ("伦理委员会", "伦理审查", "知情同意", "隐私保护", "数据安全", "匿名化")
            if keyword in text
        )
        if "不涉及" in text and any(keyword in text for keyword in ("人体", "动物", "伦理", "遗传资源")):
            return 7.0, "文中说明不涉及高风险伦理事项，但仍建议补充数据合规边界说明。"
        if positive_hits >= 2:
            return 7.5, "已提及伦理审查或数据隐私控制安排，伦理合规基础较明确。"
        if positive_hits == 1:
            return 6.3, "提到了伦理或数据合规要求，但审批方式或责任边界仍不够明确。"
        return 5.5, "文中提到伦理相关内容较少，未见明确审批或隐私保护安排。"

    def _evaluate_completeness_item(
        self,
        item_sections: Dict[str, Any],
        all_sections: Dict[str, Any],
    ) -> tuple[float, str]:
        """评估规范完整性"""
        present_sections = [name for name in self._required_sections if name in all_sections]
        missing_sections = [name for name in self._required_sections if name not in all_sections]
        merged_text = self._merge_section_text(all_sections)
        placeholder_hits = bool(self.PLACEHOLDER_PATTERN.search(merged_text))

        if len(present_sections) >= 3 and not placeholder_hits:
            return 7.2, "政策、预算等合规材料基本齐备，整体完整性较好。"
        if len(present_sections) >= 2:
            return 6.0, f"已提供部分合规材料，但仍缺少{chr(12289).join(missing_sections[:2])}等直接说明。"
        if len(present_sections) == 1:
            return 5.2, f"仅提供了{present_sections[0]}相关材料，合规性说明仍不完整。"
        return 5.0, "合规性材料较少，完整性不足。"

    def _evaluate_budget_item(
        self,
        item_sections: Dict[str, Any],
        all_sections: Dict[str, Any],
    ) -> tuple[float, str]:
        """评估预算合理性"""
        if not item_sections:
            return 5.0, "文中未见明确预算表或预算测算说明。"

        text = self._merge_section_text(item_sections)
        amount_hits = len(self.AMOUNT_PATTERN.findall(text)) + text.count("金额:")
        has_measurement = any(keyword in text for keyword in ("测算说明", "预算合理性说明", "预算编制", "单价"))
        has_total = "合计" in text or "预算总额" in text

        if amount_hits >= 4 and has_measurement and has_total:
            return 7.6, "预算科目、金额和测算依据较完整，预算合理性基础较好。"
        if amount_hits >= 3 and has_total:
            return 6.8, "预算科目和金额已列出，但测算依据仍可进一步细化。"
        if amount_hits >= 1:
            return 5.8, "给出了预算框架，但金额分解或测算依据还不够完整。"
        return 4.8, "预算表结构存在，但缺少可核验的金额或测算说明。"

    def _merge_section_text(self, sections: Dict[str, Any]) -> str:
        """合并章节文本，供规则判断使用"""
        return "\n".join(str(value or "") for value in sections.values())

    def _build_item_prompt(self, item_name: str, description: str, content: Dict[str, Any]) -> str:
        """构建单检查项提示词"""
        content_text = self._format_content_for_prompt(content)
        return f"""你是一位专业的项目评审专家，请仅评估“{item_name}”这一项。

## 相关内容

{content_text}

## 评审要求

- 评估项：{item_name}
- 关注点：{description}
- 只能基于给定材料作答；若材料未明确出现，不得臆断为“已获批”或“存在违规”，应写“文中未见明确说明”
- 输出 1-10 分
- 评语控制在 80 字以内，直接指出结论与主要问题

## 输出格式

请以 JSON 输出：
```json
{{
  "score": 7,
  "comment": "简要评价"
}}
```"""

    def _parse_item_result(self, llm_output: str) -> Dict[str, Any]:
        """解析单检查项结果"""
        try:
            json_str = llm_output
            if "```json" in llm_output:
                json_str = llm_output.split("```json")[1].split("```")[0]
            elif "```" in llm_output:
                json_str = llm_output.split("```")[1].split("```")[0]
            
            data = json.loads(json_str.strip())
            return {
                "score": float(data.get("score", 5)),
                "comment": data.get("comment", ""),
            }
        except Exception as e:
            return {
                "score": 5.0,
                "comment": f"子项输出格式异常：{str(e)}",
            }

    def _build_result_from_items(self, items: List[CheckItem]) -> CheckResult:
        """根据单项结果聚合合规性总结果"""
        total_score = self._calculate_weighted_score(items)
        issues = [item.comment for item in items if item.score <= 6 and item.comment][:3]
        highlights = [item.comment for item in items if item.score >= 8 and item.comment][:2]

        if total_score >= 8:
            opinion = "项目整体合规性较好，政策、伦理与预算基础较完整。"
        elif total_score >= 6:
            opinion = "项目合规性基础基本具备，但仍有部分内容需要补充或细化。"
        else:
            opinion = "项目合规性基础较弱，政策、伦理或预算论证仍存在明显缺口。"

        confidence = round(
            sum(
                1
                for item in items
                if item.comment
                and "子项输出格式异常" not in item.comment
                and "子项评审超时或异常" not in item.comment
            ) / max(len(items), 1),
            2,
        )

        return CheckResult(
            dimension=self.dimension,
            dimension_name=self.dimension_name,
            score=total_score,
            confidence=confidence,
            opinion=opinion,
            issues=issues,
            highlights=highlights,
            items=items,
        )
