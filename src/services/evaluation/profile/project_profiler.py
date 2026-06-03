"""项目画像识别器"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .profile_config import (
    PROFILE_DEMONSTRATION,
    PROFILE_GENERIC,
    PROFILE_PLATFORM,
    PROFILE_SCIENCE_POPULARIZATION,
    PROFILE_TECH_RND,
    get_profile_dimension_overrides,
)


@dataclass(slots=True)
class ProjectProfileResult:
    """项目画像识别结果"""

    project_profile: str = PROFILE_GENERIC
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    dimension_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """转为可序列化字典"""
        return {
            "project_profile": self.project_profile,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "dimension_overrides": self.dimension_overrides,
        }


class ProjectProfiler:
    """基于规则推断项目画像"""

    PROFILE_KEYWORDS = {
        PROFILE_SCIENCE_POPULARIZATION: (
            "科普",
            "宣教",
            "义诊",
            "活动",
            "展览",
            "直播",
            "公众号",
            "视频号",
            "资源库",
            "普及",
        ),
        PROFILE_PLATFORM: (
            "平台建设",
            "平台",
            "资源平台",
            "服务平台",
            "数据库",
            "资源库",
            "共享平台",
            "公共服务",
            "能力建设",
            "基础设施",
        ),
        PROFILE_DEMONSTRATION: (
            "示范",
            "应用示范",
            "推广应用",
            "中试",
            "转化",
            "产业化",
            "推广",
        ),
        PROFILE_TECH_RND: (
            "技术路线",
            "算法",
            "模型",
            "机理",
            "传感器",
            "高光谱",
            "机器人",
            "研发",
            "系统研发",
            "研究内容",
        ),
    }

    def infer(self, sections: Dict[str, str]) -> ProjectProfileResult:
        """根据正文章节推断项目画像"""
        section_names = " ".join(sections.keys())
        merged = f"{section_names}\n" + "\n".join(str(value) for value in sections.values())

        scores: Dict[str, int] = {}
        evidence_map: Dict[str, List[str]] = {}
        for profile, keywords in self.PROFILE_KEYWORDS.items():
            hits = [keyword for keyword in keywords if keyword in merged]
            scores[profile] = len(hits)
            evidence_map[profile] = hits[:6]

        science_score = scores.get(PROFILE_SCIENCE_POPULARIZATION, 0)
        platform_score = scores.get(PROFILE_PLATFORM, 0)
        demonstration_score = scores.get(PROFILE_DEMONSTRATION, 0)
        tech_score = scores.get(PROFILE_TECH_RND, 0)

        if science_score >= 3 and science_score >= tech_score:
            profile = PROFILE_SCIENCE_POPULARIZATION
        elif platform_score >= 3 and platform_score >= tech_score:
            profile = PROFILE_PLATFORM
        elif demonstration_score >= 3 and demonstration_score > tech_score:
            profile = PROFILE_DEMONSTRATION
        elif tech_score >= 3:
            profile = PROFILE_TECH_RND
        else:
            profile = PROFILE_GENERIC

        top_score = max(scores.values(), default=0)
        sorted_scores = sorted(scores.values(), reverse=True)
        gap = top_score - (sorted_scores[1] if len(sorted_scores) > 1 else 0)

        if profile == PROFILE_GENERIC:
            confidence = 0.5
        elif top_score >= 5 and gap >= 2:
            confidence = 0.85
        elif top_score >= 3:
            confidence = 0.7
        else:
            confidence = 0.6

        evidence = evidence_map.get(profile, [])
        if not evidence:
            evidence = ["未命中显著画像关键词，按通用口径处理"]

        return ProjectProfileResult(
            project_profile=profile,
            confidence=confidence,
            evidence=[f"命中关键词: {', '.join(evidence)}"],
            dimension_overrides=get_profile_dimension_overrides(profile),
        )
