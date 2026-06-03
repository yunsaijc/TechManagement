"""Reward DB plagiarism runner backed by local ingest index."""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from src.services.plagiarism.aggregator import PlagiarismResult
from src.services.plagiarism.reward_field_aggregator import RewardFieldResultAggregator
from src.services.plagiarism.config import (
    PLAGIARISM_REWARD_CORPUS_ROOT,
    PLAGIARISM_REWARD_DICT_CONFIG,
    PLAGIARISM_REWARD_SCOPE_CONFIG,
    PLAGIARISM_REWARD_FIELD_EXTRA_TEMPLATE_PATTERNS,
)
from src.services.plagiarism.engine import ComparisonEngine
from src.services.plagiarism.multi_source_aggregator import MultiSourceAggregator
from src.services.plagiarism.reward_report_builder import RewardPlagiarismHtmlReportBuilder
from src.services.plagiarism.retrieval import RetrievalCandidate, RetrievalResult, RetrievalWindow
from src.services.plagiarism.reward_retrieval import RewardSourceRetriever
from src.services.plagiarism.reward_corpus_manager import RewardCorpusManager
from src.services.plagiarism.template_filter import TemplateFilter
from src.services.plagiarism.template_prefilter import TemplatePreFilter
from src.services.plagiarism.tokenizer import SentenceTokenizer


class RewardCorpusPlagiarismService:
    """Run plagiarism checks using reward DB text fields."""

    def __init__(self, db_name: str = "xmsbnew"):
        self.db_name = db_name
        self.debug_report_root = Path("/home/tdkx/ljh/Tech/debug_plagiarism/text")
        self.manager = RewardCorpusManager(db_name=db_name)

        self.tokenizer = SentenceTokenizer()
        self.template_filter = TemplateFilter(
            whitelist_patterns=list(PLAGIARISM_REWARD_FIELD_EXTRA_TEMPLATE_PATTERNS or [])
        )
        self.template_prefilter = TemplatePreFilter(template_filter=self.template_filter)
        self.source_retriever = RewardSourceRetriever()
        self.html_report_builder = RewardPlagiarismHtmlReportBuilder()
        self.comparison_engine = ComparisonEngine(
            min_continuous_match=5,
            ngram_size=8,
            winnowing_window=8,
            min_match_length=30,
        )
        self.result_aggregator = RewardFieldResultAggregator(template_filter=self.template_filter)
        self.multi_source_aggregator = MultiSourceAggregator()

    def get_current_nomination_year(self) -> str | None:
        return self.manager.get_current_nomination_year()

    def get_scope_project_ids(self, scope: str, current_nd: str | None) -> List[str]:
        return self.manager.get_scope_project_ids(scope=scope, current_nd=current_nd)

    def load_field_texts(self, dict_type: str, project_ids: List[str]) -> Dict[str, str]:
        return self.manager.fetch_field_texts(dict_type=dict_type, project_ids=project_ids)

    def _merge_field_items_by_project(
        self,
        items: List[dict],
    ) -> Tuple[Dict[str, str], Dict[str, dict], List[dict]]:
        project_texts: Dict[str, str] = {}
        record_offsets: Dict[str, dict] = {}
        cleaned_items: List[dict] = []
        for raw in items or []:
            record_id = str(raw.get("id") or raw.get("record_id") or "").strip()
            xmbh = str(raw.get("xmbh") or "").strip()
            if not record_id or not xmbh:
                continue
            text = html_lib.unescape(str(raw.get("text") or raw.get("content") or "")).replace("\u00a0", " ").strip()
            if not text:
                continue
            base_text = project_texts.get(xmbh, "")
            offset = len(base_text) + (1 if base_text else 0)
            project_texts[xmbh] = f"{base_text}\n{text}" if base_text else text
            record_offsets[record_id] = {
                "xmbh": xmbh,
                "start": offset,
            }
            item = dict(raw)
            item["id"] = record_id
            item["xmbh"] = xmbh
            item["text"] = text
            cleaned_items.append(item)
        return project_texts, record_offsets, cleaned_items

    def _run_pairwise_comparison(
        self,
        *,
        primary_id: str,
        primary_text: str,
        source_texts: Dict[str, str],
        threshold_high: float,
        threshold_medium: float,
    ) -> Tuple[PlagiarismResult, dict]:
        processed_texts = {primary_id: primary_text, **{sid: txt for sid, txt in source_texts.items() if txt}}
        sentences_map = {
            doc_id: self.tokenizer.tokenize(text)
            for doc_id, text in processed_texts.items()
            if text
        }
        excluded_ranges = {}
        for doc_id, sentences in sentences_map.items():
            ranges = self.template_prefilter.mark_excluded_ranges(sentences)
            if ranges:
                excluded_ranges[doc_id] = ranges

        similarities = self.comparison_engine.compare(
            docs=sentences_map,
            excluded_ranges=excluded_ranges,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            raw_texts=processed_texts,
            primary_doc_only=primary_id,
        )
        result = self.result_aggregator.aggregate(
            similarities,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            doc_texts=processed_texts,
            template_filter=self.template_filter,
        )
        pairwise_debug = self.result_aggregator.format_debug_output(
            similarities,
            processed_texts,
            primary_id,
            template_filter=self.template_filter,
        )
        return result, pairwise_debug

    def _build_cxd_short_text_retriever(self, primary_text: str) -> RewardSourceRetriever:
        text_len = len(str(primary_text or "").strip())
        if text_len >= 120:
            return self.source_retriever
        return RewardSourceRetriever(
            window_chars=min(120, max(48, text_len)),
            window_step=30,
            min_window_chars=max(24, min(48, text_len // 2 if text_len > 0 else 24)),
            top_k_docs=max(int(self.source_retriever.top_k_docs or 50), 50),
            top_k_windows_per_doc=max(int(self.source_retriever.top_k_windows_per_doc or 6), 8),
            min_window_score=0.03,
            min_doc_score=0.02,
        )

    @staticmethod
    def _normalize_zscq_english_text(text: str) -> str:
        cleaned = str(text or "").strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s*([:;,.\-_/()])\s*", r"\1", cleaned)
        return cleaned

    @staticmethod
    def _is_zscq_english_exact_match_mode(text: str) -> bool:
        sample = str(text or "").strip()
        if not sample:
            return False
        zh_count = len(re.findall(r"[\u4e00-\u9fff]", sample))
        alpha_count = len(re.findall(r"[A-Za-z]", sample))
        return zh_count == 0 and alpha_count >= 4

    def _build_zscq_english_exact_index(self, items: List[dict]) -> Dict[str, List[str]]:
        index: Dict[str, List[str]] = {}
        for item in items or []:
            item_id = str(item.get("id") or "").strip()
            item_text = str(item.get("text") or "")
            if not item_id or not self._is_zscq_english_exact_match_mode(item_text):
                continue
            normalized = self._normalize_zscq_english_text(item_text)
            if not normalized:
                continue
            index.setdefault(normalized, []).append(item_id)
        return index

    def _build_exact_match_pairwise_result(
        self,
        *,
        primary_id: str,
        primary_text: str,
        selected_ids: List[str],
        source_texts: Dict[str, str],
    ) -> Tuple[PlagiarismResult, dict]:
        primary_clean = str(primary_text or "")
        primary_len = len(primary_clean)
        sources = []
        high_similarity = []
        documents = {primary_id: primary_clean}
        for sid in selected_ids:
            source_text = str(source_texts.get(sid) or "")
            if not source_text:
                continue
            documents[str(sid)] = source_text
            sources.append(
                {
                    "doc": str(sid),
                    "line": 1,
                    "text": source_text,
                    "start": 0,
                    "end": len(source_text),
                }
            )
            high_similarity.append(
                {
                    "doc_a": primary_id,
                    "doc_b": str(sid),
                    "similarity": 1.0,
                    "effective_similarity": 1.0,
                    "effective_chars": primary_len,
                    "template_chars": 0,
                    "filter_reason": None,
                    "bucket": "high_similarity",
                    "duplicate_segments": [],
                    "template_segments": [],
                }
            )

        duplicate_segments = []
        if sources:
            duplicate_segments.append(
                {
                    "match_id": "m001",
                    "primary_line": 1,
                    "primary_text": primary_clean,
                    "primary_start": 0,
                    "primary_end": primary_len,
                    "primary_section": "",
                    "char_count": primary_len,
                    "ngram_count": max(primary_len, 1),
                    "similarity_score": 1.0,
                    "is_template": False,
                    "template_reason": None,
                    "sources": sources,
                }
            )

        result = PlagiarismResult(
            id=f"plagiarism_{int(time.time() * 1000)}",
            total_pairs=len(high_similarity),
            high_similarity=high_similarity,
            medium_similarity=[],
            low_similarity=[],
            processing_time=0.0,
            filtered_pairs=[],
        )
        pairwise_debug = {
            "primary_doc": primary_id,
            "documents": documents,
            "duplicate_segments": duplicate_segments,
            "template_segments": [],
            "filtered_pairs": [],
            "summary": {
                "total_effective_segments": len(duplicate_segments),
                "total_template_segments": 0,
                "total_effective_chars": primary_len if duplicate_segments else 0,
                "total_template_chars": 0,
                "total_filtered_pairs": 0,
            },
        }
        return result, pairwise_debug

    def _remap_segment_to_project_view(
        self,
        *,
        segment: dict,
        primary_offset: int,
        primary_doc_id: str,
        primary_doc_text: str,
        primary_section: str,
        source_record_offsets: Dict[str, dict],
        source_project_texts: Dict[str, str],
        source_item_meta: Dict[str, dict],
    ) -> dict:
        mapped = dict(segment)
        start = int(mapped.get("primary_start", 0) or 0) + primary_offset
        end = int(mapped.get("primary_end", 0) or 0) + primary_offset
        mapped["doc_a"] = primary_doc_id
        mapped["primary_start"] = start
        mapped["primary_end"] = end
        mapped["primary_line"] = primary_doc_text[:start].count("\n") + 1 if start > 0 else 1
        mapped["primary_section"] = primary_section

        remapped_sources = []
        for source in list(mapped.get("sources") or []):
            source_item_id = str(source.get("doc") or "").strip()
            source_meta = source_item_meta.get(source_item_id, {})
            source_offset_info = source_record_offsets.get(source_item_id, {})
            source_doc_id = str(source_meta.get("xmbh") or source_offset_info.get("xmbh") or source_item_id)
            source_base_start = int(source.get("start", 0) or 0)
            source_base_end = int(source.get("end", 0) or 0)
            source_offset = int(source_offset_info.get("start", 0) or 0)
            remapped_start = source_base_start + source_offset
            remapped_end = source_base_end + source_offset
            source_doc_text = source_project_texts.get(source_doc_id, "")
            remapped_source = dict(source)
            remapped_source["doc"] = source_doc_id
            remapped_source["start"] = remapped_start
            remapped_source["end"] = remapped_end
            remapped_source["line"] = source_doc_text[:remapped_start].count("\n") + 1 if remapped_start > 0 else 1
            remapped_sources.append(remapped_source)
        mapped["sources"] = remapped_sources
        return mapped

    def save_scope_corpus(
        self,
        dict_type: str,
        scope: str,
        current_nd: str | None,
        text_map: Dict[str, str],
    ) -> str:
        corpus_root = Path(PLAGIARISM_REWARD_CORPUS_ROOT)
        corpus_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "dict_type": dict_type,
            "dict_label": PLAGIARISM_REWARD_DICT_CONFIG[dict_type]["label"],
            "scope": scope,
            "scope_label": PLAGIARISM_REWARD_SCOPE_CONFIG[scope],
            "current_nomination_year": current_nd,
            "saved_at": int(time.time()),
            "document_count": len(text_map),
            "documents": [{"xmbh": xmbh, "text": text} for xmbh, text in text_map.items()],
        }
        output_path = corpus_root / f"reward_{dict_type}_{scope}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(output_path)

    def _retrieve_source_candidates(
        self,
        *,
        primary_id: str,
        primary_text: str,
        source_corpus_docs: Dict[str, dict],
        primary_excluded: List[tuple[int, int]] | None,
        retriever: RewardSourceRetriever | None = None,
    ) -> tuple[RetrievalResult, List[dict], str, List[str]]:
        active_retriever = retriever or self.source_retriever
        retrieval_result = active_retriever.search_in_corpus(
            primary_doc=primary_id,
            primary_text=primary_text,
            corpus_documents=source_corpus_docs,
            primary_excluded_ranges=primary_excluded,
        )
        retrieval_attempts = [
            {
                "attempt": 1,
                "min_window_score": active_retriever.min_window_score,
                "min_doc_score": active_retriever.min_doc_score,
                "window_chars": active_retriever.window_chars,
                "min_window_chars": active_retriever.min_window_chars,
                "candidate_count": len(retrieval_result.candidates or []),
                "selected_count": len(retrieval_result.selected_source_docs or []),
            }
        ]

        selected_ids = list(retrieval_result.selected_source_docs or [])
        fallback_mode = "normal"
        if not selected_ids:
            relaxed_configs = [
                (
                    max(0.02, active_retriever.min_window_score * 0.7),
                    max(0.02, active_retriever.min_doc_score * 0.7),
                ),
                (
                    max(0.01, active_retriever.min_window_score * 0.5),
                    max(0.01, active_retriever.min_doc_score * 0.5),
                ),
            ]
            for idx, (min_window_score, min_doc_score) in enumerate(relaxed_configs, start=2):
                relaxed_retriever = RewardSourceRetriever(
                    window_chars=active_retriever.window_chars,
                    window_step=active_retriever.window_step,
                    min_window_chars=active_retriever.min_window_chars,
                    top_k_docs=active_retriever.top_k_docs,
                    top_k_windows_per_doc=active_retriever.top_k_windows_per_doc,
                    min_window_score=min_window_score,
                    min_doc_score=min_doc_score,
                )
                relaxed_result = relaxed_retriever.search_in_corpus(
                    primary_doc=primary_id,
                    primary_text=primary_text,
                    corpus_documents=source_corpus_docs,
                    primary_excluded_ranges=primary_excluded,
                )
                retrieval_attempts.append(
                    {
                        "attempt": idx,
                        "min_window_score": min_window_score,
                        "min_doc_score": min_doc_score,
                        "window_chars": relaxed_retriever.window_chars,
                        "min_window_chars": relaxed_retriever.min_window_chars,
                        "candidate_count": len(relaxed_result.candidates or []),
                        "selected_count": len(relaxed_result.selected_source_docs or []),
                    }
                )
                if relaxed_result.selected_source_docs:
                    retrieval_result = relaxed_result
                    selected_ids = list(relaxed_result.selected_source_docs or [])
                    fallback_mode = "relaxed_thresholds"
                    break

        if not selected_ids:
            windows = active_retriever._build_primary_windows(primary_text, primary_excluded or [])
            top_k = int(active_retriever.top_k_docs or 8)
            positive_candidates = 0
            heap = []

            if windows:
                import heapq

                for doc_id, doc_entry in source_corpus_docs.items():
                    raw_features = getattr(doc_entry, "features", {}) if doc_entry is not None else {}
                    if isinstance(doc_entry, dict):
                        raw_features = doc_entry.get("features", {}) or raw_features
                    features = {k: set(v) for k, v in (raw_features or {}).items()}
                    if not features.get("char4"):
                        continue

                    matched_windows: List[RetrievalWindow] = []
                    for window in windows:
                        score_info = active_retriever._score_window(window, features)
                        if float(score_info.get("score") or 0.0) <= 0.0:
                            continue
                        matched_windows.append(
                            RetrievalWindow(
                                primary_start=int(window["start"]),
                                primary_end=int(window["end"]),
                                score=round(float(score_info["score"]), 4),
                                char_count=int(window["char_count"]),
                                overlap_char2=round(float(score_info["overlap_char2"]), 4),
                                overlap_char4=round(float(score_info["overlap_char4"]), 4),
                                overlap_char8=round(float(score_info["overlap_char8"]), 4),
                            )
                        )

                    if not matched_windows:
                        continue

                    matched_windows.sort(key=lambda item: (-item.score, item.primary_start))
                    top_windows = matched_windows[: int(active_retriever.top_k_windows_per_doc or 6)]
                    doc_score = float(
                        active_retriever._score_document(top_windows, len(matched_windows), len(windows))
                    )
                    if doc_score <= 0.0:
                        continue

                    positive_candidates += 1
                    max_window_score = float(top_windows[0].score) if top_windows else 0.0
                    hit_window_count = len(matched_windows)
                    key = (doc_score, max_window_score, hit_window_count, str(doc_id))
                    payload = (key, top_windows, hit_window_count)
                    if len(heap) < top_k:
                        heapq.heappush(heap, payload)
                        continue
                    if key > heap[0][0]:
                        heapq.heapreplace(heap, payload)

            retrieval_attempts.append(
                {
                    "attempt": len(retrieval_attempts) + 1,
                    "mode": "best_effort_topk",
                    "min_window_score": 0.0,
                    "min_doc_score": 0.0,
                    "window_chars": active_retriever.window_chars,
                    "min_window_chars": active_retriever.min_window_chars,
                    "candidate_count": positive_candidates,
                    "selected_count": min(len(heap), top_k),
                }
            )

            if heap:
                heap.sort(key=lambda item: item[0], reverse=True)
                selected_candidates: List[RetrievalCandidate] = []
                selected_ids = []
                for key, top_windows, hit_window_count in heap:
                    doc_score, max_window_score, _, doc_id = key
                    selected_ids.append(str(doc_id))
                    selected_candidates.append(
                        RetrievalCandidate(
                            doc_id=str(doc_id),
                            document_suspiciousness=round(float(doc_score), 4),
                            max_window_score=round(float(max_window_score), 4),
                            hit_window_count=int(hit_window_count),
                            matched_windows=list(top_windows or []),
                        )
                    )
                retrieval_result = RetrievalResult(
                    primary_doc=primary_id,
                    total_source_docs=len(source_corpus_docs),
                    selected_source_docs=list(selected_ids),
                    candidates=selected_candidates,
                )
                fallback_mode = "best_effort_topk"

        if not selected_ids:
            selected_ids = list(source_corpus_docs.keys())[: active_retriever.top_k_docs]
            fallback_mode = "fallback_first_k"

        has_candidate_hits = bool(getattr(retrieval_result, "candidates", None))
        if (not has_candidate_hits) and len(selected_ids) < 8:
            added = set(selected_ids)
            for doc_id in source_corpus_docs.keys():
                if doc_id != primary_id and doc_id not in added:
                    selected_ids.append(doc_id)
                    added.add(doc_id)
                    if len(selected_ids) >= 8:
                        break

        return retrieval_result, retrieval_attempts, fallback_mode, selected_ids

    def _build_result_payload(
        self,
        *,
        primary_id: str,
        primary_text: str,
        source_texts: Dict[str, str],
        selected_ids: List[str],
        dict_type: str,
        scope: str,
        current_nd: str | None,
        scope_ids: List[str],
        threshold_high: float,
        threshold_medium: float,
        retrieval_result: RetrievalResult,
        retrieval_attempts: List[dict],
        fallback_mode: str,
        report_id: str,
        document_metadata: Dict[str, dict] | None = None,
    ) -> dict:
        if not source_texts:
            raise ValueError("候选来源缺少可用文本，无法执行精比对")

        processed_texts = {primary_id: primary_text, **{sid: source_texts.get(sid, "") for sid in selected_ids}}
        corpus_path = self.save_scope_corpus(
            dict_type=dict_type,
            scope=scope,
            current_nd=current_nd,
            text_map={sid: txt for sid, txt in source_texts.items() if txt},
        )
        result, pairwise_debug = self._run_pairwise_comparison(
            primary_id=primary_id,
            primary_text=primary_text,
            source_texts={sid: processed_texts.get(sid, "") for sid in selected_ids},
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
        )
        multi_summary = self.multi_source_aggregator.build_summary(
            pairwise_debug,
            primary_scope_chars=len(primary_text),
            primary_scope_text=primary_text,
        )
        result.effective_duplicate_rate = multi_summary.get("effective_duplicate_rate", 0.0)
        result.effective_duplicate_chars = multi_summary.get("effective_duplicate_chars", 0)
        result.primary_scope_chars = multi_summary.get("primary_scope_chars", 0)
        result.source_rankings = multi_summary.get("source_rankings", [])
        result.match_groups = multi_summary.get("match_groups", [])

        report_payload = dict(pairwise_debug)
        report_payload["thresholds"] = {
            "threshold_high": threshold_high,
            "threshold_medium": threshold_medium,
        }
        report_payload["retrieval"] = {
            "primary_doc": retrieval_result.primary_doc,
            "total_source_docs": retrieval_result.total_source_docs,
            "selected_source_docs": list(retrieval_result.selected_source_docs or []),
            "fallback_mode": fallback_mode,
            "attempts": retrieval_attempts,
            "params": {
                "window_chars": self.source_retriever.window_chars,
                "window_step": self.source_retriever.window_step,
                "min_window_chars": self.source_retriever.min_window_chars,
                "top_k_docs": self.source_retriever.top_k_docs,
                "top_k_windows_per_doc": self.source_retriever.top_k_windows_per_doc,
                "min_window_score": self.source_retriever.min_window_score,
                "min_doc_score": self.source_retriever.min_doc_score,
            },
            "candidates": [
                {
                    "doc_id": c.doc_id,
                    "document_suspiciousness": c.document_suspiciousness,
                    "max_window_score": c.max_window_score,
                    "hit_window_count": c.hit_window_count,
                    "matched_windows": [
                        {
                            "primary_start": w.primary_start,
                            "primary_end": w.primary_end,
                            "score": w.score,
                            "char_count": w.char_count,
                            "overlap_char2": w.overlap_char2,
                            "overlap_char4": w.overlap_char4,
                            "overlap_char8": w.overlap_char8,
                        }
                        for w in (c.matched_windows or [])
                    ],
                }
                for c in (retrieval_result.candidates or [])
            ],
        }
        pairwise_pairs = []
        for bucket in ("high_similarity", "medium_similarity", "low_similarity", "filtered_pairs"):
            items = list(getattr(result, bucket, None) or [])
            for item in items:
                pairwise_pairs.append(
                    {
                        "doc_a": item.get("doc_a"),
                        "doc_b": item.get("doc_b"),
                        "type": item.get("type"),
                        "similarity": item.get("similarity"),
                        "effective_similarity": item.get("effective_similarity"),
                        "effective_chars": item.get("effective_chars"),
                        "template_chars": item.get("template_chars"),
                        "filter_reason": item.get("filter_reason"),
                        "bucket": bucket,
                    }
                )
        pairwise_pairs.sort(
            key=lambda row: (
                0 if str(row.get("type", "")) == "high" else (1 if str(row.get("type", "")) == "medium" else 2),
                -float(row.get("effective_similarity") or 0),
                -float(row.get("similarity") or 0),
                str(row.get("doc_b") or ""),
            )
        )
        report_payload["pairwise_pairs"] = pairwise_pairs
        report_payload["documents"] = processed_texts
        report_payload["summary"] = {
            **dict(report_payload.get("summary") or {}),
            "primary_scope_chars": result.primary_scope_chars,
            "effective_duplicate_chars": result.effective_duplicate_chars,
            "effective_duplicate_rate": result.effective_duplicate_rate,
        }
        if document_metadata:
            report_payload["document_metadata"] = document_metadata
        html_report_path = self._build_html_report(
            xmbh=report_id,
            dict_type=dict_type,
            scope=scope,
            pairwise_debug=report_payload,
        )

        loaded_source_texts = sum(1 for value in source_texts.values() if value)
        return {
            "current_nomination_year": current_nd,
            "scope_total_projects": len(scope_ids),
            "loaded_text_projects": loaded_source_texts,
            "selected_source_docs": selected_ids,
            "corpus_saved_path": corpus_path,
            "html_report_path": html_report_path,
            "result": result,
        }

    def check_by_scope(
        self,
        xmbh: str,
        dict_type: str,
        scope: str,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        max_sources: int | None = None,
    ) -> dict:
        normalized_dict_type = dict_type.strip().lower()
        if normalized_dict_type in {"cxd", "zscq", "jhmc"}:
            return self.check_project_items_by_scope(
                xmbh=xmbh,
                dict_type=normalized_dict_type,
                scope=scope,
                threshold_high=threshold_high,
                threshold_medium=threshold_medium,
                max_sources=max_sources,
            )

        primary_id = xmbh.strip()
        current_nd = self.manager.get_current_nomination_year()
        scope_ids = self.manager.get_scope_project_ids(scope, current_nd=current_nd)
        if max_sources is not None and max_sources > 0:
            scope_ids = scope_ids[:max_sources]

        source_ids = [sid for sid in scope_ids if sid != primary_id]
        self.manager.ensure_documents(dict_type=dict_type, project_ids=source_ids)

        primary_text = (
            self.manager.fetch_field_texts(dict_type=dict_type, project_ids=[primary_id]).get(primary_id)
            or self.manager.get_text_by_xmbh(dict_type=dict_type, xmbh=primary_id)
        )
        if primary_text:
            primary_text = html_lib.unescape(primary_text).replace("\u00a0", " ")
        if not primary_text:
            raise ValueError(f"未找到项目 {primary_id} 在字典 {dict_type} 对应字段的内容")

        source_corpus_docs = self.manager.get_retrieval_documents(dict_type=dict_type, xmbh_ids=source_ids)
        if not source_corpus_docs:
            raise ValueError("在指定查询范围内没有可比对的有效文本")

        primary_sentences = self.tokenizer.tokenize(primary_text)
        primary_excluded = self.template_prefilter.mark_excluded_ranges(primary_sentences)
        retrieval_result, retrieval_attempts, fallback_mode, selected_ids = self._retrieve_source_candidates(
            primary_id=primary_id,
            primary_text=primary_text,
            source_corpus_docs=source_corpus_docs,
            primary_excluded=primary_excluded,
        )
        if not selected_ids:
            raise ValueError("在指定查询范围内没有召回到候选来源")

        source_texts = self.manager.fetch_field_texts(dict_type=dict_type, project_ids=selected_ids)
        if not source_texts:
            source_texts = self.manager.get_texts(dict_type=dict_type, xmbh_ids=selected_ids)
        if source_texts:
            source_texts = {
                doc_id: html_lib.unescape(text).replace("\u00a0", " ") if text else ""
                for doc_id, text in source_texts.items()
            }
        return self._build_result_payload(
            primary_id=primary_id,
            primary_text=primary_text,
            source_texts=source_texts,
            selected_ids=selected_ids,
            dict_type=dict_type,
            scope=scope,
            current_nd=current_nd,
            scope_ids=scope_ids,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            retrieval_result=retrieval_result,
            retrieval_attempts=retrieval_attempts,
            fallback_mode=fallback_mode,
            report_id=primary_id,
        )

    def check_project_items_by_scope(
        self,
        xmbh: str,
        dict_type: str,
        scope: str,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        max_sources: int | None = None,
    ) -> dict:
        normalized_dict_type = dict_type.strip().lower()
        dict_label = PLAGIARISM_REWARD_DICT_CONFIG[normalized_dict_type]["label"]
        item_label = "创新点" if normalized_dict_type == "cxd" else dict_label
        primary_id = xmbh.strip()
        current_nd = self.manager.get_current_nomination_year()
        scope_ids = self.manager.get_scope_project_ids(scope, current_nd=current_nd)
        if max_sources is not None and max_sources > 0:
            scope_ids = scope_ids[:max_sources]

        primary_raw_items = self.manager.fetch_field_items_by_project_ids(normalized_dict_type, [primary_id])
        primary_project_texts, primary_record_offsets, primary_items = self._merge_field_items_by_project(primary_raw_items)
        primary_text = primary_project_texts.get(primary_id, "")
        if not primary_text or not primary_items:
            raise ValueError(f"未找到项目 {primary_id} 的可比对{dict_label}内容")

        source_project_ids = [sid for sid in scope_ids if sid != primary_id]
        source_raw_items = self.manager.fetch_field_items_by_project_ids(normalized_dict_type, source_project_ids)
        source_project_texts, source_record_offsets, source_items = self._merge_field_items_by_project(source_raw_items)
        if not source_project_texts or not source_items:
            raise ValueError(f"在指定查询范围内没有可比对的{dict_label}记录")

        source_texts_by_record = {
            str(item["id"]): str(item.get("text") or "")
            for item in source_items
            if item.get("id") and item.get("text")
        }
        source_corpus_docs = self.manager.build_retrieval_documents_from_text_map(source_texts_by_record)
        if not source_corpus_docs:
            raise ValueError(f"在指定查询范围内没有可比对的有效{dict_label}文本")

        source_item_meta = {str(item["id"]): item for item in source_items if item.get("id")}
        zscq_english_exact_index = (
            self._build_zscq_english_exact_index(source_items)
            if normalized_dict_type == "zscq"
            else {}
        )
        merged_effective_segments: List[dict] = []
        merged_template_segments: List[dict] = []
        merged_high_pairs: List[dict] = []
        merged_medium_pairs: List[dict] = []
        merged_low_pairs: List[dict] = []
        merged_filtered_pairs: List[dict] = []
        selected_source_record_ids: List[str] = []

        for primary_item in primary_items:
            item_record_id = str(primary_item.get("id") or "").strip()
            item_text = str(primary_item.get("text") or "")
            if not item_record_id or not item_text:
                continue

            if normalized_dict_type == "zscq" and self._is_zscq_english_exact_match_mode(item_text):
                normalized_text = self._normalize_zscq_english_text(item_text)
                selected_ids = list(zscq_english_exact_index.get(normalized_text, []))
                item_source_texts = {
                    sid: source_texts_by_record.get(sid, "")
                    for sid in selected_ids
                    if source_texts_by_record.get(sid, "")
                }
                item_result, item_debug = self._build_exact_match_pairwise_result(
                    primary_id=item_record_id,
                    primary_text=item_text,
                    selected_ids=list(item_source_texts.keys()),
                    source_texts=item_source_texts,
                )
            else:
                primary_sentences = self.tokenizer.tokenize(item_text)
                primary_excluded = self.template_prefilter.mark_excluded_ranges(primary_sentences)
                active_retriever = self._build_cxd_short_text_retriever(item_text)
                _, _, _, selected_ids = self._retrieve_source_candidates(
                    primary_id=item_record_id,
                    primary_text=item_text,
                    source_corpus_docs=source_corpus_docs,
                    primary_excluded=primary_excluded,
                    retriever=active_retriever,
                )
                if not selected_ids:
                    continue

                item_source_texts = {
                    sid: source_texts_by_record.get(sid, "")
                    for sid in selected_ids
                    if source_texts_by_record.get(sid, "")
                }
                if not item_source_texts:
                    continue

                item_result, item_debug = self._run_pairwise_comparison(
                    primary_id=item_record_id,
                    primary_text=item_text,
                    source_texts=item_source_texts,
                    threshold_high=threshold_high,
                    threshold_medium=threshold_medium,
                )
                selected_ids = list(item_source_texts.keys())
            if not selected_ids:
                continue

            selected_source_record_ids.extend(selected_ids)

            primary_offset = int(primary_record_offsets.get(item_record_id, {}).get("start", 0) or 0)
            primary_section = f"{item_label} {primary_item.get('xh') or item_record_id}"

            for segment in list(item_debug.get("duplicate_segments", []) or []):
                merged_effective_segments.append(
                    self._remap_segment_to_project_view(
                        segment=segment,
                        primary_offset=primary_offset,
                        primary_doc_id=primary_id,
                        primary_doc_text=primary_text,
                        primary_section=primary_section,
                        source_record_offsets=source_record_offsets,
                        source_project_texts=source_project_texts,
                        source_item_meta=source_item_meta,
                    )
                )
            for segment in list(item_debug.get("template_segments", []) or []):
                merged_template_segments.append(
                    self._remap_segment_to_project_view(
                        segment=segment,
                        primary_offset=primary_offset,
                        primary_doc_id=primary_id,
                        primary_doc_text=primary_text,
                        primary_section=primary_section,
                        source_record_offsets=source_record_offsets,
                        source_project_texts=source_project_texts,
                        source_item_meta=source_item_meta,
                    )
                )

            bucket_map = {
                "high_similarity": merged_high_pairs,
                "medium_similarity": merged_medium_pairs,
                "low_similarity": merged_low_pairs,
                "filtered_pairs": merged_filtered_pairs,
            }
            for bucket_name, bucket_target in bucket_map.items():
                for pair in list(getattr(item_result, bucket_name, None) or []):
                    source_doc = str(pair.get("doc_b") or "")
                    source_meta = source_item_meta.get(source_doc, {})
                    remapped = dict(pair)
                    remapped["doc_a"] = primary_id
                    remapped["doc_b"] = str(source_meta.get("xmbh") or source_doc)
                    remapped["primary_section"] = primary_section
                    bucket_target.append(remapped)

        merged_effective_segments = self.result_aggregator._dedupe_formatted_segments(merged_effective_segments)
        merged_template_segments = self.result_aggregator._dedupe_formatted_segments(merged_template_segments)
        for idx, seg in enumerate(merged_effective_segments, start=1):
            seg["match_id"] = f"d{idx:03d}"
        for idx, seg in enumerate(merged_template_segments, start=1):
            seg["match_id"] = f"t{idx:03d}"

        merged_debug = {
            "primary_doc": primary_id,
            "documents": {
                primary_id: primary_text,
                **source_project_texts,
            },
            "duplicate_segments": merged_effective_segments,
            "template_segments": merged_template_segments,
            "summary": {
                "total_effective_segments": len(merged_effective_segments),
                "total_template_segments": len(merged_template_segments),
                "total_effective_chars": self.result_aggregator._union_length_from_formatted(merged_effective_segments),
                "total_template_chars": self.result_aggregator._union_length_from_formatted(merged_template_segments),
                "total_filtered_pairs": len(merged_filtered_pairs),
            },
        }
        multi_summary = self.multi_source_aggregator.build_summary(
            merged_debug,
            primary_scope_chars=len(primary_text),
            primary_scope_text=primary_text,
        )

        result = PlagiarismResult(
            id=f"plagiarism_{int(time.time() * 1000)}",
            total_pairs=len(multi_summary.get("source_rankings", []) or []),
            high_similarity=merged_high_pairs,
            medium_similarity=merged_medium_pairs,
            low_similarity=merged_low_pairs,
            processing_time=0.0,
            filtered_pairs=merged_filtered_pairs,
        )
        result.effective_duplicate_rate = multi_summary.get("effective_duplicate_rate", 0.0)
        result.effective_duplicate_chars = multi_summary.get("effective_duplicate_chars", 0)
        result.primary_scope_chars = multi_summary.get("primary_scope_chars", 0)
        result.source_rankings = multi_summary.get("source_rankings", [])
        result.match_groups = multi_summary.get("match_groups", [])

        merged_debug["summary"].update(
            {
                "primary_scope_chars": result.primary_scope_chars,
                "effective_duplicate_chars": result.effective_duplicate_chars,
                "effective_duplicate_rate": result.effective_duplicate_rate,
            }
        )
        merged_debug["pairwise_pairs"] = [
            {
                "doc_a": primary_id,
                "doc_b": str(((segment.get("sources") or [{}])[0].get("doc") or "")),
                "type": "high",
                "similarity": segment.get("similarity_score"),
                "effective_similarity": segment.get("similarity_score"),
                "effective_chars": segment.get("char_count"),
                "template_chars": 0,
                "filter_reason": None,
                "bucket": "duplicate_segments",
            }
            for segment in merged_effective_segments
        ]
        merged_debug["retrieval"] = {
            "primary_doc": primary_id,
            "total_source_docs": len(source_corpus_docs),
            "selected_source_docs": sorted({str(source_item_meta.get(rid, {}).get("xmbh") or "") for rid in selected_source_record_ids if rid}),
            "fallback_mode": "project_item_merge",
            "params": {
                "window_chars": self.source_retriever.window_chars,
                "window_step": self.source_retriever.window_step,
                "min_window_chars": self.source_retriever.min_window_chars,
                "top_k_docs": self.source_retriever.top_k_docs,
                "top_k_windows_per_doc": self.source_retriever.top_k_windows_per_doc,
                "min_window_score": self.source_retriever.min_window_score,
                "min_doc_score": self.source_retriever.min_doc_score,
            },
        }
        merged_debug["document_metadata"] = {
            primary_id: {
                "xmbh": primary_id,
                "is_primary": True,
                "item_count": len(primary_items),
            },
            **{
                xmbh_key: {
                    "xmbh": xmbh_key,
                    "is_primary": False,
                    "item_count": sum(1 for item in source_items if str(item.get("xmbh") or "") == xmbh_key),
                }
                for xmbh_key in source_project_texts.keys()
            },
        }

        corpus_path = self.save_scope_corpus(
            dict_type=normalized_dict_type,
            scope=scope,
            current_nd=current_nd,
            text_map=source_project_texts,
        )
        html_report_path = self._build_html_report(
            xmbh=primary_id,
            dict_type=normalized_dict_type,
            scope=scope,
            pairwise_debug=merged_debug,
        )

        selected_source_projects = sorted(
            {
                str(source_item_meta.get(record_id, {}).get("xmbh") or "").strip()
                for record_id in selected_source_record_ids
                if str(source_item_meta.get(record_id, {}).get("xmbh") or "").strip()
            }
        )

        return {
            "current_nomination_year": current_nd,
            "scope_total_projects": len(scope_ids),
            "loaded_text_projects": len(source_project_texts),
            "loaded_text_items": len(source_texts_by_record),
            "selected_source_docs": selected_source_projects,
            "corpus_saved_path": corpus_path,
            "html_report_path": html_report_path,
            "result": result,
        }

    def check_cxd_project_by_scope(
        self,
        xmbh: str,
        scope: str,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        max_sources: int | None = None,
    ) -> dict:
        return self.check_project_items_by_scope(
            xmbh=xmbh,
            dict_type="cxd",
            scope=scope,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            max_sources=max_sources,
        )

    def check_innovation_item_by_scope(
        self,
        record_id: str,
        scope: str,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        max_sources: int | None = None,
    ) -> dict:
        primary_id = record_id.strip()
        current_nd = self.manager.get_current_nomination_year()
        scope_ids = self.manager.get_scope_project_ids(scope, current_nd=current_nd)
        if max_sources is not None and max_sources > 0:
            scope_ids = scope_ids[:max_sources]

        primary_item = self.manager.get_innovation_item_by_id(primary_id)
        if not primary_item:
            raise ValueError(f"未找到创新点记录 {primary_id}")

        primary_text = html_lib.unescape(primary_item.get("text") or "").replace("\u00a0", " ")
        if not primary_text:
            raise ValueError(f"创新点记录 {primary_id} 缺少可比对文本")

        source_items = self.manager.fetch_innovation_items_by_project_ids(
            scope_ids,
            exclude_record_ids=[primary_id],
        )
        if not source_items:
            raise ValueError("在指定查询范围内没有可比对的创新点记录")

        source_texts = {
            str(item["id"]): html_lib.unescape(item.get("text") or "").replace("\u00a0", " ")
            for item in source_items
            if item.get("id")
        }
        source_corpus_docs = self.manager.build_retrieval_documents_from_text_map(source_texts)
        if not source_corpus_docs:
            raise ValueError("在指定查询范围内没有可比对的有效创新点文本")

        primary_sentences = self.tokenizer.tokenize(primary_text)
        primary_excluded = self.template_prefilter.mark_excluded_ranges(primary_sentences)
        active_retriever = self._build_cxd_short_text_retriever(primary_text)
        retrieval_result, retrieval_attempts, fallback_mode, selected_ids = self._retrieve_source_candidates(
            primary_id=primary_id,
            primary_text=primary_text,
            source_corpus_docs=source_corpus_docs,
            primary_excluded=primary_excluded,
            retriever=active_retriever,
        )
        if not selected_ids:
            raise ValueError("在指定查询范围内没有召回到候选创新点来源")

        document_metadata: Dict[str, dict] = {
            primary_id: {
                "record_id": primary_id,
                "xmbh": primary_item.get("xmbh"),
                "xh": primary_item.get("xh"),
                "nd": primary_item.get("nd"),
                "is_primary": True,
            }
        }
        selected_source_items: List[dict] = []
        source_meta_map = {str(item["id"]): item for item in source_items if item.get("id")}
        for sid in selected_ids:
            meta = source_meta_map.get(str(sid))
            if not meta:
                continue
            document_metadata[str(sid)] = {
                "record_id": str(sid),
                "xmbh": meta.get("xmbh"),
                "xh": meta.get("xh"),
                "nd": meta.get("nd"),
                "is_primary": False,
            }
            selected_source_items.append(
                {
                    "record_id": str(sid),
                    "xmbh": meta.get("xmbh"),
                    "xh": meta.get("xh"),
                    "nd": meta.get("nd"),
                }
            )

        payload = self._build_result_payload(
            primary_id=primary_id,
            primary_text=primary_text,
            source_texts=source_texts,
            selected_ids=selected_ids,
            dict_type="cxd",
            scope=scope,
            current_nd=current_nd,
            scope_ids=scope_ids,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            retrieval_result=retrieval_result,
            retrieval_attempts=retrieval_attempts,
            fallback_mode=fallback_mode,
            report_id=f"{primary_item.get('xmbh')}_{primary_id}",
            document_metadata=document_metadata,
        )
        payload["loaded_text_items"] = payload.get("loaded_text_projects", 0)
        payload["primary_record"] = {
            "record_id": primary_id,
            "xmbh": primary_item.get("xmbh"),
            "xh": primary_item.get("xh"),
            "nd": primary_item.get("nd"),
        }
        payload["selected_source_items"] = selected_source_items
        return payload

    def _build_html_report(
        self,
        xmbh: str,
        dict_type: str,
        scope: str,
        pairwise_debug: dict,
    ) -> str:
        self.debug_report_root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"plagiarism_reward_{xmbh}_{dict_type}_{scope}_{ts}"
        debug_json_path = self.debug_report_root / f"{base_name}.json"
        html_path = self.debug_report_root / f"{base_name}.html"
        debug_json_path.write_text(
            json.dumps(pairwise_debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.html_report_builder.build_from_debug_file(debug_json_path, html_path)
        return str(html_path)
