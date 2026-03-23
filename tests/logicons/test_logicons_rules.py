"""logicons 规则测试"""
import asyncio
import unittest

from src.services.logicons.agent import LogiConsAgent


def _sample_conflict_text() -> str:
    return """
一、项目基本信息
项目执行期：2年（2025年-2026年）
资金申请总额：50万元

四、详细任务进度安排
2025年完成方案设计
2026年完成样机开发
2028年完成系统联调

五、资金安排明细
设备费 30万元
材料费 20万元
测试费 20万元
"""


def _sample_consistent_text() -> str:
    return """
一、项目基本信息
项目执行期：2年（2025年-2026年）
资金申请总额：50万元

四、详细任务进度安排
2025年完成方案设计
2026年完成样机开发

五、资金安排明细
设备费 20万元
材料费 20万元
测试费 10万元
"""


class TestLogiConsRules(unittest.TestCase):
    def test_detect_timeline_and_budget_conflicts(self):
        agent = LogiConsAgent(budget_tolerance=0.01)
        result = asyncio.run(
            agent.run(
                check_id="test_001",
                project_id="p1",
                text=_sample_conflict_text(),
            )
        )

        codes = {item.rule_code for item in result.conflicts}
        self.assertTrue("T001" in codes or "T002" in codes)
        self.assertIn("B001", codes)
        self.assertGreaterEqual(result.summary.total, 2)

    def test_no_conflict_for_consistent_text(self):
        agent = LogiConsAgent(budget_tolerance=0.01)
        result = asyncio.run(
            agent.run(
                check_id="test_002",
                project_id="p2",
                text=_sample_consistent_text(),
            )
        )

        self.assertEqual(result.summary.total, 0)


if __name__ == "__main__":
    unittest.main()
