import asyncio
import unittest

from src.services.logicon.agent import LogicOnAgent


class LogicOnCoreTest(unittest.TestCase):
    def test_budget_sum_conflict(self):
        text = """
项目资金申请总额50万元。
资金安排明细：设备费30万元，材料费20万元，劳务费20万元。
"""
        agent = LogicOnAgent()
        result = asyncio.run(agent.check_text(text=text, doc_kind="declaration"))
        categories = {c.category.value for c in result.conflicts}
        self.assertIn("BUDGET_SUM", categories)

    def test_budget_sum_conflict_without_unit(self):
        text = """
资金申请总额：50
资金安排明细：设备费 30；材料费 20；劳务费 20
"""
        agent = LogicOnAgent()
        result = asyncio.run(agent.check_text(text=text, doc_kind="declaration"))
        categories = {c.category.value for c in result.conflicts}
        self.assertIn("BUDGET_SUM", categories)

    def test_time_span_conflict_years(self):
        text = """
项目整体执行期为2年。
详细任务进度安排：2025年完成立项，2026年完成样机，2027年完成验收。
"""
        agent = LogicOnAgent()
        result = asyncio.run(agent.check_text(text=text, doc_kind="declaration"))
        categories = {c.category.value for c in result.conflicts}
        self.assertIn("TIME_SPAN", categories)

    def test_time_span_conflict_dot_month(self):
        text = """
项目起止年月：2025.01-2026.12
详细任务进度安排：2027.03 完成验收
"""
        agent = LogicOnAgent()
        result = asyncio.run(agent.check_text(text=text, doc_kind="declaration"))
        categories = {c.category.value for c in result.conflicts}
        self.assertIn("TIME_SPAN", categories)


if __name__ == "__main__":
    unittest.main()
