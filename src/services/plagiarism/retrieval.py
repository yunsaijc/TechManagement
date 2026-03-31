"""Source retrieval for multi-source plagiarism checking.

This layer ranks source documents for a primary document before the
fine-grained matching kernel runs. It is intentionally recall-oriented
and does not replace the existing `engine.py` alignment logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from src.services.plagiarism.engine import ExcludedRange


@dataclass
class RetrievalWindow:
    primary_start: int
    primary_end: int
    score: float
    char_count: int
    overlap_char2: float
    overlap_char4: float
    overlap_char8: float


@dataclass
class RetrievalCandidate:
    doc_id: str
    document_suspiciousness: float
    max_window_score: float
    hit_window_count: int
    matched_windows: List[RetrievalWindow] = field(default_factory=list)


@dataclass
class RetrievalResult:
    primary_doc: str
    total_source_docs: int
    selected_source_docs: List[str]
    candidates: List[RetrievalCandidate] = field(default_factory=list)


class SourceRetriever:
    """Recall-oriented candidate ranking for source documents."""

    def __init__(
        self,
        window_chars: int = 240,
        window_step: int = 80,
        min_window_chars: int = 90,
        top_k_docs: int = 8,
        top_k_windows_per_doc: int = 6,
        min_window_score: float = 0.12,
        min_doc_score: float = 0.08,
    ):
        self.window_chars = window_chars
        self.window_step = window_step
        self.min_window_chars = min_window_chars
        self.top_k_docs = top_k_docs
        self.top_k_windows_per_doc = top_k_windows_per_doc
        self.min_window_score = min_window_score
        self.min_doc_score = min_doc_score

    def rank_sources(
        self,
        primary_doc: str,
        primary_text: str,
        source_texts: Dict[str, str],
        primary_excluded_ranges: Optional[Sequence[ExcludedRange]] = None,
        source_excluded_ranges: Optional[Dict[str, Sequence[ExcludedRange]]] = None,
    ) -> RetrievalResult:
        source_excluded_ranges = source_excluded_ranges or {}
        windows = self._build_primary_windows(primary_text, primary_excluded_ranges or [])

        candidates: List[RetrievalCandidate] = []
        for doc_id, source_text in source_texts.items():
            features = self._build_doc_features(
                source_text,
                source_excluded_ranges.get(doc_id, []),
            )
            if not features["char4"]:
                continue

            candidate = self._rank_single_source(doc_id, windows, features)
            if candidate:
                candidates.append(candidate)

        return self._finalize_retrieval_result(primary_doc, candidates, len(source_texts))

    def search_in_corpus(
        self,
        primary_doc: str,
        primary_text: str,
        corpus_documents: Dict[str, any],  # 传入 CorpusDocument 的 model_dump() 或对象
        primary_excluded_ranges: Optional[Sequence[ExcludedRange]] = None,
    ) -> RetrievalResult:
        """从库索引中搜索候选文档

        Args:
            primary_doc: 主文档 ID
            primary_text: 主文档提取后的正文
            corpus_documents: 库索引文档字典 {doc_id: CorpusDocument}
            primary_excluded_ranges: 排除区间

        Returns:
            检索结果
        """
        windows = self._build_primary_windows(primary_text, primary_excluded_ranges or [])
        candidates: List[RetrievalCandidate] = []

        for doc_id, doc_entry in corpus_documents.items():
            # 处理 features，确保是 Set[str] 用于评分
            # 支持传入 Pydantic 对象或 Dict
            raw_features = getattr(doc_entry, "features", {}) or doc_entry.get("features", {})
            features = {k: set(v) for k, v in raw_features.items()}
            
            if not features.get("char4"):
                continue

            candidate = self._rank_single_source(doc_id, windows, features)
            if candidate:
                candidates.append(candidate)

        return self._finalize_retrieval_result(primary_doc, candidates, len(corpus_documents))

    def _rank_single_source(
        self,
        doc_id: str,
        windows: List[dict],
        source_features: Dict[str, Set[str]],
    ) -> Optional[RetrievalCandidate]:
        """对单个来源文档进行窗口评分"""
        matched_windows: List[RetrievalWindow] = []
        for window in windows:
            score_info = self._score_window(window, source_features)
            if score_info["score"] < self.min_window_score:
                continue
            matched_windows.append(
                RetrievalWindow(
                    primary_start=window["start"],
                    primary_end=window["end"],
                    score=round(score_info["score"], 4),
                    char_count=window["char_count"],
                    overlap_char2=round(score_info["overlap_char2"], 4),
                    overlap_char4=round(score_info["overlap_char4"], 4),
                    overlap_char8=round(score_info["overlap_char8"], 4),
                )
            )

        if not matched_windows:
            return None

        matched_windows.sort(key=lambda item: (-item.score, item.primary_start))
        top_windows = matched_windows[: self.top_k_windows_per_doc]
        doc_score = self._score_document(top_windows, len(matched_windows), len(windows))
        
        if doc_score < self.min_doc_score:
            return None

        return RetrievalCandidate(
            doc_id=doc_id,
            document_suspiciousness=round(doc_score, 4),
            max_window_score=round(top_windows[0].score, 4),
            hit_window_count=len(matched_windows),
            matched_windows=top_windows,
        )

    def _finalize_retrieval_result(
        self,
        primary_doc: str,
        candidates: List[RetrievalCandidate],
        total_source_count: int,
    ) -> RetrievalResult:
        """对候选结果进行排序和筛选"""
        candidates.sort(
            key=lambda item: (
                -item.document_suspiciousness,
                -item.max_window_score,
                -item.hit_window_count,
                item.doc_id,
            )
        )

        selected = [candidate.doc_id for candidate in candidates[: self.top_k_docs]]
        return RetrievalResult(
            primary_doc=primary_doc,
            total_source_docs=total_source_count,
            selected_source_docs=selected,
            candidates=candidates,
        )

    def _build_primary_windows(
        self,
        text: str,
        excluded_ranges: Sequence[ExcludedRange],
    ) -> List[dict]:
        if not text:
            return []

        windows: List[dict] = []
        start = 0
        text_len = len(text)
        while start < text_len:
            end = min(text_len, start + self.window_chars)
            window_text = text[start:end]
            masked_text = self._mask_excluded_text(window_text, excluded_ranges, start)
            normalized = self._normalize(masked_text)
            if len(normalized) >= self.min_window_chars:
                windows.append(
                    {
                        "start": start,
                        "end": end,
                        "char_count": len(normalized),
                        "char2": self._char_ngrams(normalized, 2),
                        "char4": self._char_ngrams(normalized, 4),
                        "char8": self._char_ngrams(normalized, 8),
                    }
                )
            if end >= text_len:
                break
            start += self.window_step
        return windows

    def _build_doc_features(
        self,
        text: str,
        excluded_ranges: Sequence[ExcludedRange],
    ) -> Dict[str, Set[str]]:
        masked_text = self._mask_excluded_text(text, excluded_ranges, 0)
        normalized = self._normalize(masked_text)
        return {
            "char2": self._char_ngrams(normalized, 2),
            "char4": self._char_ngrams(normalized, 4),
            "char8": self._char_ngrams(normalized, 8),
        }

    def _score_window(self, window: dict, source_features: Dict[str, Set[str]]) -> Dict[str, float]:
        overlap_char2 = self._coverage_ratio(window["char2"], source_features["char2"])
        overlap_char4 = self._coverage_ratio(window["char4"], source_features["char4"])
        overlap_char8 = self._coverage_ratio(window["char8"], source_features["char8"])

        # Longer shingles are more indicative; shorter shingles keep recall.
        score = 0.15 * overlap_char2 + 0.35 * overlap_char4 + 0.50 * overlap_char8
        return {
            "score": score,
            "overlap_char2": overlap_char2,
            "overlap_char4": overlap_char4,
            "overlap_char8": overlap_char8,
        }

    def _score_document(
        self,
        top_windows: Sequence[RetrievalWindow],
        hit_window_count: int,
        total_window_count: int,
    ) -> float:
        if not top_windows:
            return 0.0

        scores = [window.score for window in top_windows]
        best = scores[0]
        top3_avg = sum(scores[:3]) / min(len(scores), 3)
        coverage_bonus = min(hit_window_count / max(total_window_count, 1), 1.0)
        return 0.55 * best + 0.35 * top3_avg + 0.10 * coverage_bonus

    def _mask_excluded_text(
        self,
        text: str,
        excluded_ranges: Sequence[ExcludedRange],
        base_offset: int,
    ) -> str:
        if not text or not excluded_ranges:
            return text

        chars = list(text)
        window_start = base_offset
        window_end = base_offset + len(text)
        for item in excluded_ranges:
            start = max(item.start, window_start)
            end = min(item.end, window_end)
            if end <= start:
                continue
            rel_start = start - window_start
            rel_end = end - window_start
            for idx in range(rel_start, rel_end):
                chars[idx] = " "
        return "".join(chars)

    def _normalize(self, text: str) -> str:
        text = re.sub(r"\[表格行\d+\]", " ", text or "")
        return re.sub(r"\s+", "", text)

    def _char_ngrams(self, text: str, n: int) -> Set[str]:
        if len(text) < n:
            return {text} if text else set()
        return {text[idx : idx + n] for idx in range(len(text) - n + 1)}

    def _coverage_ratio(self, left: Iterable[str], right: Set[str]) -> float:
        left_set = set(left)
        if not left_set or not right:
            return 0.0
        return len(left_set & right) / len(left_set)
