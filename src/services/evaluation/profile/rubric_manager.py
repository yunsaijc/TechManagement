"""Rubric 管理器

基于项目画像和检查器默认配置，生成维度级评审口径。
"""

from __future__ import annotations

from typing import Any, Dict, List

from .project_profiler import ProjectProfileResult


class RubricManager:
    """生成维度级 rubric 配置"""

    def build_dimension_rubric(
        self,
        dimension: str,
        checker: Any,
        profile_result: ProjectProfileResult,
    ) -> Dict[str, Any]:
        """构建单维度 rubric"""
        alternative_section_keys = getattr(checker, "ALTERNATIVE_SECTION_KEYS", [])
        alternative_sections = checker.get_alternative_sections(alternative_section_keys)
        relax_missing_sections = bool(checker.dimension_overrides.get("relax_missing_sections", False))

        return {
            "dimension": dimension,
            "dimension_name": checker.dimension_name,
            "project_profile": profile_result.project_profile,
            "required_sections": list(checker.required_sections),
            "alternative_sections": list(alternative_sections),
            "relax_missing_sections": relax_missing_sections,
            "evidence_minimum": 1,
            "profile_evidence": list(profile_result.evidence),
        }

    def build_dimension_rubrics(
        self,
        dimensions: List[str],
        checker_map: Dict[str, Any],
        profile_result: ProjectProfileResult,
    ) -> Dict[str, Dict[str, Any]]:
        """批量构建维度 rubric"""
        rubrics: Dict[str, Dict[str, Any]] = {}
        for dimension in dimensions:
            checker = checker_map.get(dimension)
            if checker is None:
                continue
            rubrics[dimension] = self.build_dimension_rubric(
                dimension=dimension,
                checker=checker,
                profile_result=profile_result,
            )
        return rubrics
