"""Primary-centered aggregation for multi-source plagiarism results."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Dict, List, Tuple


class MultiSourceAggregator:
    """Build a primary-centered view on top of pairwise duplicate segments."""

    MERGE_GAP = 20
    MIN_OVERLAP_RATIO = 0.55
    SOURCE_MERGE_GAP = 80
    SOURCE_BACKTRACK_TOL = 8

    def build_summary(
        self,
        pairwise_debug_output: Dict,
        primary_scope_chars: int,
    ) -> Dict:
        segments = list(pairwise_debug_output.get("duplicate_segments", []) or [])
        grouped = self._group_segments(segments)
        source_rankings = self._build_source_rankings(grouped, primary_scope_chars)
        effective_duplicate_chars = self._union_length([
            (int(group.get("primary_start", 0) or 0), int(group.get("primary_end", 0) or 0))
            for group in grouped
        ])
        effective_duplicate_rate = (
            effective_duplicate_chars / primary_scope_chars if primary_scope_chars > 0 else 0.0
        )
        return {
            "primary_scope_chars": primary_scope_chars,
            "effective_duplicate_chars": effective_duplicate_chars,
            "effective_duplicate_rate": round(effective_duplicate_rate, 4),
            "group_count": len(grouped),
            "source_count": len(source_rankings),
            "source_rankings": source_rankings,
            "match_groups": grouped,
        }

    def _group_segments(self, segments: List[Dict]) -> List[Dict]:
        sorted_segments = sorted(
            segments,
            key=lambda seg: (
                int(seg.get("primary_start", 0) or 0),
                -int(seg.get("char_count", 0) or 0),
            ),
        )
        groups: List[Dict] = []
        for segment in sorted_segments:
            if not groups or not self._should_merge(groups[-1], segment):
                groups.append(self._new_group(segment, len(groups) + 1))
                continue
            self._merge_into_group(groups[-1], segment)

        for group in groups:
            group["sources"].sort(
                key=lambda item: (
                    -float(item.get("similarity_score", 0) or 0),
                    item.get("doc", ""),
                    int(item.get("start", 0) or 0),
                )
            )
            group["source_count"] = len(group["sources"])
            group["similarity_score"] = round(
                max((float(item.get("similarity_score", 0) or 0) for item in group["sources"]), default=0.0),
                4,
            )
            group["char_count"] = max(0, int(group["primary_end"]) - int(group["primary_start"]))
        return groups

    def _new_group(self, segment: Dict, index: int) -> Dict:
        primary_start = int(segment.get("primary_start", 0) or 0)
        primary_end = int(segment.get("primary_end", 0) or 0)
        return {
            "group_id": f"g{index:03d}",
            "primary_start": primary_start,
            "primary_end": primary_end,
            "primary_text": segment.get("primary_text", ""),
            "primary_section": segment.get("primary_section", ""),
            "match_ids": [segment.get("match_id")] if segment.get("match_id") else [],
            "sources": self._extract_sources(segment),
        }

    def _merge_into_group(self, group: Dict, segment: Dict) -> None:
        group["primary_start"] = min(int(group["primary_start"]), int(segment.get("primary_start", 0) or 0))
        group["primary_end"] = max(int(group["primary_end"]), int(segment.get("primary_end", 0) or 0))
        group["match_ids"].extend([segment.get("match_id")] if segment.get("match_id") else [])

        text_candidates = [
            group.get("primary_text", ""),
            segment.get("primary_text", ""),
        ]
        text_candidates = [text for text in text_candidates if text]
        if text_candidates:
            group["primary_text"] = max(text_candidates, key=len)

        source_index = {
            (
                item.get("doc", ""),
                int(item.get("start", 0) or 0),
                int(item.get("end", 0) or 0),
            ): item
            for item in group["sources"]
        }
        for source in self._extract_sources(segment):
            key = (
                source.get("doc", ""),
                int(source.get("start", 0) or 0),
                int(source.get("end", 0) or 0),
            )
            if key in source_index:
                if float(source.get("similarity_score", 0) or 0) > float(source_index[key].get("similarity_score", 0) or 0):
                    source_index[key]["similarity_score"] = source.get("similarity_score", 0)
                continue
            group["sources"].append(source)
            source_index[key] = source

    def _extract_sources(self, segment: Dict) -> List[Dict]:
        result = []
        for source in segment.get("sources", []) or []:
            result.append(
                {
                    "doc": source.get("doc", ""),
                    "line": source.get("line", 0),
                    "text": source.get("text", ""),
                    "start": int(source.get("start", 0) or 0),
                    "end": int(source.get("end", 0) or 0),
                    "similarity_score": float(segment.get("similarity_score", 0) or 0),
                }
            )
        return result

    def _should_merge(self, group: Dict, segment: Dict) -> bool:
        group_start = int(group.get("primary_start", 0) or 0)
        group_end = int(group.get("primary_end", 0) or 0)
        seg_start = int(segment.get("primary_start", 0) or 0)
        seg_end = int(segment.get("primary_end", 0) or 0)
        if seg_end <= seg_start:
            return False

        if group.get("primary_section") and segment.get("primary_section"):
            if group["primary_section"] != segment["primary_section"]:
                return False

        if not self._has_compatible_source_progression(group, segment):
            return False

        overlap = min(group_end, seg_end) - max(group_start, seg_start)
        if overlap > 0:
            shorter = max(min(group_end - group_start, seg_end - seg_start), 1)
            return (overlap / shorter) >= self.MIN_OVERLAP_RATIO

        gap = seg_start - group_end
        return 0 <= gap <= self.MERGE_GAP

    def _has_compatible_source_progression(self, group: Dict, segment: Dict) -> bool:
        group_sources = list(group.get("sources", []) or [])
        seg_sources = self._extract_sources(segment)
        if not group_sources or not seg_sources:
            return False

        group_docs = {str(item.get("doc", "")) for item in group_sources if item.get("doc")}
        seg_docs = {str(item.get("doc", "")) for item in seg_sources if item.get("doc")}
        common_docs = group_docs & seg_docs
        if not common_docs:
            # 核心约束：无共同来源文档时禁止并组，避免跨来源误合并。
            return False

        for doc in common_docs:
            group_doc_spans = [
                (
                    int(item.get("start", 0) or 0),
                    int(item.get("end", 0) or 0),
                )
                for item in group_sources
                if str(item.get("doc", "")) == doc
            ]
            seg_doc_spans = [
                (
                    int(item.get("start", 0) or 0),
                    int(item.get("end", 0) or 0),
                )
                for item in seg_sources
                if str(item.get("doc", "")) == doc
            ]
            if not group_doc_spans or not seg_doc_spans:
                continue

            group_last_end = max(end for _, end in group_doc_spans)
            for seg_src_start, seg_src_end in seg_doc_spans:
                if seg_src_end <= seg_src_start:
                    continue
                if seg_src_start < group_last_end - self.SOURCE_BACKTRACK_TOL:
                    continue
                source_gap = seg_src_start - group_last_end
                if source_gap <= self.SOURCE_MERGE_GAP:
                    return True
        return False

    def _build_source_rankings(self, groups: List[Dict], primary_scope_chars: int) -> List[Dict]:
        source_ranges: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        source_group_count: Dict[str, int] = defaultdict(int)
        source_max_similarity: Dict[str, float] = defaultdict(float)

        for group in groups:
            group_start = int(group.get("primary_start", 0) or 0)
            group_end = int(group.get("primary_end", 0) or 0)
            seen_docs = set()
            for source in group.get("sources", []) or []:
                doc_id = source.get("doc", "")
                if not doc_id:
                    continue
                source_ranges[doc_id].append((group_start, group_end))
                source_max_similarity[doc_id] = max(
                    source_max_similarity[doc_id],
                    float(source.get("similarity_score", 0) or 0),
                )
                if doc_id not in seen_docs:
                    source_group_count[doc_id] += 1
                    seen_docs.add(doc_id)

        rankings = []
        for doc_id, ranges in source_ranges.items():
            contribution_chars = self._union_length(ranges)
            contribution_rate = contribution_chars / primary_scope_chars if primary_scope_chars > 0 else 0.0
            rankings.append(
                {
                    "doc_id": doc_id,
                    "contribution_chars": contribution_chars,
                    "contribution_rate": round(contribution_rate, 4),
                    "matched_group_count": source_group_count.get(doc_id, 0),
                    "max_similarity_score": round(source_max_similarity.get(doc_id, 0.0), 4),
                }
            )

        rankings.sort(
            key=lambda item: (
                -int(item.get("contribution_chars", 0) or 0),
                -float(item.get("max_similarity_score", 0) or 0),
                item.get("doc_id", ""),
            )
        )
        return rankings

    def _union_length(self, ranges: List[Tuple[int, int]]) -> int:
        valid = sorted((max(0, start), max(0, end)) for start, end in ranges if end > start)
        if not valid:
            return 0

        total = 0
        cur_start, cur_end = valid[0]
        for start, end in valid[1:]:
            if start <= cur_end:
                cur_end = max(cur_end, end)
                continue
            total += cur_end - cur_start
            cur_start, cur_end = start, end
        total += cur_end - cur_start
        return total
