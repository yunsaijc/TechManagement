"""合规性检查器测试"""

import pytest

from src.services.evaluation.checkers.compliance_checker import ComplianceChecker


@pytest.mark.asyncio
async def test_compliance_checker_builds_stable_rule_based_items_from_direct_evidence():
    """合规性应优先基于明确章节证据给出稳定判断"""
    checker = ComplianceChecker(llm=object())

    result = await checker.check(
        {
            "政策依据": "依据《全民科学素质行动计划纲要》《健康中国行动》及省级科技计划指南开展实施。",
            "伦理审查": "项目不涉及高风险伦理事项，依托医院伦理委员会开展过程管理，并补充数据安全说明。",
            "经费预算": "合计25.00万元，金额:25.00；金额:10.75；金额:10.00；金额:2.00。",
            "预算说明": "预算合理性说明：设备费、业务费和劳务费均有测算说明与单价依据。",
        }
    )

    assert len(result.items) == 4
    assert result.score >= 6.5
    assert any(item.name == "预算合理性" and item.score >= 6.8 for item in result.items)
    assert any(item.name == "政策符合性" and "政策" in item.comment for item in result.items)


@pytest.mark.asyncio
async def test_compliance_checker_does_not_hallucinate_ethics_violation_when_section_missing():
    """缺少伦理章节时，应提示文中未见明确说明，而不是臆断存在违规"""
    checker = ComplianceChecker(llm=object())

    result = await checker.check(
        {
            "经费预算": "合计25.00万元，金额:25.00；金额:10.75；金额:10.00；金额:2.00。",
            "预算说明": "预算合理性说明：设备费、业务费和劳务费均有测算说明与单价依据。",
        }
    )

    ethics_item = next(item for item in result.items if item.name == "伦理合规")
    assert ethics_item.score == 5.0
    assert "文中未见独立伦理审查" in ethics_item.comment
    assert "违规" not in ethics_item.comment


@pytest.mark.asyncio
async def test_compliance_checker_marks_completeness_by_missing_required_sections():
    """完整性应根据直接缺失的合规材料来判断"""
    checker = ComplianceChecker(llm=object())

    result = await checker.check(
        {
            "政策依据": "依据《河北省科技计划管理办法》开展项目申报。",
            "经费预算": "金额:10.00；金额:5.00；合计15.00万元。",
        }
    )

    completeness_item = next(item for item in result.items if item.name == "规范完整")
    assert completeness_item.score <= 6.0
    assert "仍缺少" in completeness_item.comment
