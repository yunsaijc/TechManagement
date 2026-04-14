"""
本地调试 matching 基础链路。

默认从同目录下的 grouping_result.json 读取全部分组结果，
逐组提取 subject_codes，并逐组执行一次专家召回。

运行方式:
    cd /home/tdkx/malin/TechManagement
    set -a && source .env && set +a
    uv run python -m src.services.grouping.0409test_main
"""

import json
from pathlib import Path

from src.services.grouping.grouping import agent
from src.common.models.grouping import GroupingResult
from src.services.grouping.matching.agent import MatchingAgent


def main() -> None:
    input_path = Path(__file__).with_name("grouping_result.json")
    if not input_path.exists():
        raise FileNotFoundError(f"未找到分组结果JSON文件: {input_path}")

    grouping_data = json.loads(input_path.read_text(encoding="utf-8"))
    grouping_result = GroupingResult.model_validate(grouping_data)
    if not grouping_result.groups:
        raise ValueError("grouping_result.json 中没有分组结果")

    matching_agent = MatchingAgent()
    all_group_subject_codes: list[list[str]] = []

    for group in grouping_result.groups:
        subject_codes = matching_agent._extract_subject_codes(group)
        all_group_subject_codes.append(subject_codes)

    print(f"分组结果读取自: {input_path}")
    print(f"分组总数: {len(grouping_result.groups)}")
    print(f"所有分组的 subject_codes: {all_group_subject_codes}")


    for index, group in enumerate(grouping_result.groups, start=1):
        subject_codes = all_group_subject_codes[index - 1]
        print("")
        print(f"[第{index}组] 分组ID: {group.group_id}")
        print(f"[第{index}组] 分组主题: {group.subject_code} {group.subject_name}")
        print(f"[第{index}组] 组内项目数: {group.count}")
        print(f"[第{index}组] 匹配召回学科代码: {subject_codes}")

        experts = matching_agent.expert_repo.get_experts(
            subject_codes=subject_codes,
            limit=10,
        )
        print(f"[第{index}组] 召回专家数: {len(experts)}")
        for expert in experts:
            print(expert)


if __name__ == "__main__":
    main()