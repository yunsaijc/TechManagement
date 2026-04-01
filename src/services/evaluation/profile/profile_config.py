"""项目画像配置"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from src.common.models.evaluation import EvaluationDimension

PROFILE_TECH_RND = "tech_rnd"
PROFILE_PLATFORM = "platform"
PROFILE_SCIENCE_POPULARIZATION = "science_popularization"
PROFILE_DEMONSTRATION = "demonstration"
PROFILE_GENERIC = "generic"


PROFILE_DIMENSION_OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    PROFILE_PLATFORM: {
        EvaluationDimension.FEASIBILITY.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "建设目标",
                "实施内容",
                "核心建设内容",
                "主要建设内容",
                "平台建设方案",
                "主要内容及实施地点",
            ],
        },
        EvaluationDimension.SCHEDULE.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "建设计划",
                "实施内容",
                "年度计划",
                "主要内容及实施地点",
                "项目绩效评价考核目标及指标",
            ],
        },
        EvaluationDimension.RISK_CONTROL.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "组织支撑条件",
                "资源支撑条件",
                "项目组织实施机制",
                "建设保障措施",
            ],
        },
        EvaluationDimension.OUTCOME.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "建设目标",
                "核心建设内容",
                "主要指标、效益",
                "项目绩效评价考核目标及指标",
            ],
        },
        EvaluationDimension.SOCIAL_BENEFIT.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "主要指标、效益",
                "应用前景",
                "普及前景",
                "模式可复制与推广",
            ],
        },
        EvaluationDimension.ECONOMIC_BENEFIT.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "主要指标、效益",
                "应用前景",
                "运营机制",
                "模式可复制与推广",
            ],
        },
    },
    PROFILE_SCIENCE_POPULARIZATION: {
        EvaluationDimension.FEASIBILITY.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "建设目标",
                "实施内容",
                "活动策划",
                "资源开发",
                "协同推广",
                "科普基础设施建设",
                "科普内容产出",
                "科普活动开展",
            ],
        },
        EvaluationDimension.SCHEDULE.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "活动安排",
                "科普活动开展",
                "科普内容产出",
                "项目绩效评价考核目标及指标",
                "项目组织实施机制",
            ],
        },
        EvaluationDimension.RISK_CONTROL.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "组织支撑条件",
                "资源支撑条件",
                "项目组织实施机制",
                "项目组主要成员",
                "项目绩效评价考核目标及指标",
            ],
        },
        EvaluationDimension.OUTCOME.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "主要指标、效益",
                "项目绩效评价考核目标及指标",
                "科普内容产出",
                "科普基础设施建设",
                "科普活动开展",
            ],
        },
        EvaluationDimension.SOCIAL_BENEFIT.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "主要指标、效益",
                "普及前景",
                "模式可复制与推广",
                "地域覆盖",
                "人群定位",
                "场景应用",
            ],
        },
        EvaluationDimension.ECONOMIC_BENEFIT.value: {
            "relax_missing_sections": True,
            "alternative_sections": [
                "主要指标、效益",
                "普及前景",
                "模式可复制与推广",
                "合作网络构建",
            ],
        },
    },
}


def get_profile_dimension_overrides(profile: str) -> Dict[str, Dict[str, Any]]:
    """返回画像对应的维度覆盖配置副本"""
    return deepcopy(PROFILE_DIMENSION_OVERRIDES.get(profile, {}))
