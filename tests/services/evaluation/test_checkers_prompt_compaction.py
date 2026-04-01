"""检查器提示词压缩测试"""

from src.services.evaluation.checkers.compliance_checker import ComplianceChecker


def test_compliance_checker_compacts_long_budget_tables_for_prompt():
    """合规性维度构建提示词时应裁剪长预算表和表格噪声"""
    checker = ComplianceChecker(llm=object())

    long_budget_lines = "\n".join(
        f"[表格行{i}] 预算科目 | 金额 | 说明 | 备注 | 其他字段"
        for i in range(1, 80)
    )
    content = {
        "政策依据": "符合省级科技计划和行业规范要求。" * 80,
        "经费预算": long_budget_lines + "\n" + ("预算说明文字。" * 200),
        "伦理审查": "项目不涉及高风险伦理问题，但需补充数据安全说明。" * 80,
        "预算说明": "项目预算编制依据充分，自筹资金来源明确。" * 120,
    }

    prompt = checker._build_prompt(content)

    assert len(prompt) < 5000
    assert prompt.count("\n## 政策依据") + prompt.count("\n## 经费预算") + prompt.count("\n## 伦理审查") + prompt.count("\n## 预算说明") <= checker.MAX_PROMPT_SECTIONS
    assert "[表格行1]" not in prompt
    assert "[内容已截断]" in prompt
