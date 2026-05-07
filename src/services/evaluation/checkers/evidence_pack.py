"""维度证据包构建器

在进入 checker 前，先按维度 rubric 预选相关章节，减少噪声干扰。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .base import BaseChecker


class EvidencePackBuilder:
    """构建维度级章节证据包"""

    NOISE_SECTION_PATTERNS = (
        "封面",
        "封皮",
        "目录",
        "附件目录",
        "填报说明",
        "填表说明",
        "申报说明",
        "注意事项",
    )

    NOISE_TEXT_PATTERNS = (
        "请勿填写",
        "填写说明",
        "此页无正文",
    )

    def build(
        self,
        sections: Dict[str, str],
        rubric: Dict[str, Any],
    ) -> Dict[str, Any]:
        """按 rubric 构建维度证据包"""
        required_sections = list(rubric.get("required_sections") or [])
        alternative_sections = list(rubric.get("alternative_sections") or [])

        filtered_sections = {
            name: text
            for name, text in sections.items()
            if self._is_business_section(name, text)
        }

        query_matches: Dict[str, List[str]] = {}
        selected_sections: Dict[str, str] = {}

        for query in self._dedupe(required_sections + alternative_sections):
            matched_names = self._find_matches(filtered_sections, query)
            if not matched_names:
                continue
            query_matches[query] = matched_names
            for name in matched_names:
                selected_sections[name] = filtered_sections[name]

        required_hits = [name for name in required_sections if query_matches.get(name)]
        alternative_hits = [name for name in alternative_sections if query_matches.get(name)]
        evidence_minimum = int(rubric.get("evidence_minimum") or 1)

        return {
            "dimension": rubric.get("dimension", ""),
            "project_profile": rubric.get("project_profile", ""),
            "required_sections": required_sections,
            "alternative_sections": alternative_sections,
            "query_matches": query_matches,
            "required_hits": required_hits,
            "alternative_hits": alternative_hits,
            "sections": selected_sections,
            "evidence_sufficient": len(required_hits) >= evidence_minimum or bool(alternative_hits),
            "candidate_count": len(selected_sections),
        }

    def _find_matches(self, sections: Dict[str, str], query: str) -> List[str]:
        """查找某个查询章节命中的实际章节名"""
        candidates = [query] + BaseChecker.SECTION_ALIASES.get(query, [])
        matched: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            for actual_name in sections:
                if actual_name in seen:
                    continue
                if self._section_matches(actual_name, candidate):
                    matched.append(actual_name)
                    seen.add(actual_name)

        if query == "进度安排":
            for actual_name in sections:
                if actual_name in seen:
                    continue
                if self._is_schedule_timeline_section(actual_name):
                    matched.append(actual_name)
                    seen.add(actual_name)

        return matched

    def _is_business_section(self, section_name: str, text: str) -> bool:
        """过滤显著噪声章节"""
        normalized_name = re.sub(r"\s+", "", str(section_name or ""))
        if not normalized_name:
            return False
        if any(pattern in normalized_name for pattern in self.NOISE_SECTION_PATTERNS):
            return False

        text_str = str(text or "").strip()
        if not text_str:
            return False
        compact = re.sub(r"\s+", "", text_str)
        if any(pattern in compact for pattern in self.NOISE_TEXT_PATTERNS):
            return False
        return True

    def _section_matches(self, actual_name: str, expected_name: str) -> bool:
        """判断章节名是否匹配"""
        normalized_actual = re.sub(r"\s+", "", str(actual_name or ""))
        normalized_expected = re.sub(r"\s+", "", str(expected_name or ""))
        return (
            normalized_actual == normalized_expected
            or normalized_expected in normalized_actual
            or normalized_actual in normalized_expected
        )

    def _is_schedule_timeline_section(self, section_name: str) -> bool:
        """识别按时间段命名的进度章节"""
        normalized = re.sub(r"\s+", "", str(section_name or ""))
        return bool(re.fullmatch(r"\d{4}年\d{1,2}月[-—至]+\d{4}年\d{1,2}月", normalized))

    def _dedupe(self, values: List[str]) -> List[str]:
        """保持顺序去重"""
        result: List[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            result.append(value)
            seen.add(value)
        return result
