"""合规性检查器测试"""

import pytest

from src.services.evaluation.checkers.compliance_checker import ComplianceChecker


class SequenceLLM:
    """按顺序返回固定响应"""

    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, prompt):
        return self._responses.pop(0)


class PartialFailLLM:
    """部分子项失败的模型"""

    def __init__(self):
        self._count = 0

    async def ainvoke(self, prompt):
        self._count += 1
        if self._count == 2:
            raise RuntimeError("Request timed out.")
        return '{"score": 7, "comment": "子项正常返回"}'


@pytest.mark.asyncio
async def test_compliance_checker_aggregates_item_level_results():
    """合规性检查器应按子项聚合总分，而不是一次性大请求"""
    llm = SequenceLLM(
        [
            '{"score": 8, "comment": "政策依据较充分"}',
            '{"score": 7, "comment": "伦理说明基本完整"}',
            '{"score": 6, "comment": "材料完整性仍需加强"}',
            '{"score": 5, "comment": "预算测算依据不足"}',
        ]
    )
    checker = ComplianceChecker(llm=llm)

    result = await checker.check(
        {
            "政策依据": "符合省级科技计划和行业规范要求。",
            "伦理审查": "项目不涉及高风险伦理问题。",
            "经费预算": "预算总额明确，但测算依据较粗。",
            "预算说明": "预算编制依据待细化。",
        }
    )

    assert result.score > 6.0
    assert len(result.items) == 4
    assert result.items[0].name == "政策符合性"
    assert any("预算测算依据不足" in issue for issue in result.issues)


@pytest.mark.asyncio
async def test_compliance_checker_keeps_partial_items_when_one_subitem_fails():
    """单个子项失败时，不应让整个合规性维度退化为空结果"""
    checker = ComplianceChecker(llm=PartialFailLLM())

    result = await checker.check(
        {
            "政策依据": "符合省级科技计划和行业规范要求。",
            "伦理审查": "项目不涉及高风险伦理问题。",
            "经费预算": "预算总额明确，但测算依据较粗。",
            "预算说明": "预算编制依据待细化。",
        }
    )

    assert len(result.items) == 4
    assert any("子项评审超时或异常" in item.comment for item in result.items)
    assert result.score >= 5.0
    assert result.opinion
