from __future__ import annotations

from typing import List

from src.services.plagiarism.retrieval import RetrievalCandidate, RetrievalResult, SourceRetriever


class RewardSourceRetriever(SourceRetriever):
    def __init__(self, **kwargs):
        kwargs["top_k_docs"] = 50
        super().__init__(**kwargs)

    def _finalize_retrieval_result(
        self,
        primary_doc: str,
        candidates: List[RetrievalCandidate],
        total_source_count: int,
    ) -> RetrievalResult:
        candidates.sort(
            key=lambda item: (
                -item.document_suspiciousness,
                -item.max_window_score,
                -item.hit_window_count,
                item.doc_id,
            )
        )

        base_top_k = 50
        max_candidates = 1000
        plateau_ratio = 0.85
        cliff_ratio = 0.70
        high_score_threshold = 0.5

        selected_candidates: List[RetrievalCandidate] = []
        if candidates:
            selected_candidates = candidates[: min(base_top_k, len(candidates))]

            if len(selected_candidates) >= base_top_k:
                boundary_score = float(selected_candidates[-1].document_suspiciousness or 0.0)
                i = base_top_k
                if (
                    i < len(candidates)
                    and boundary_score > 0.0
                    and float(candidates[i].document_suspiciousness or 0.0) >= boundary_score * plateau_ratio
                ):
                    while i < len(candidates) and len(selected_candidates) < max_candidates:
                        score = float(candidates[i].document_suspiciousness or 0.0)
                        prev_score = float(candidates[i - 1].document_suspiciousness or 0.0)
                        if score < prev_score * cliff_ratio:
                            break
                        selected_candidates.append(candidates[i])
                        i += 1

            if len(selected_candidates) < max_candidates:
                seen = {c.doc_id for c in selected_candidates}
                for candidate in candidates[base_top_k:]:
                    if len(selected_candidates) >= max_candidates:
                        break
                    score = float(candidate.document_suspiciousness or 0.0)
                    if score < high_score_threshold:
                        break
                    if candidate.doc_id in seen:
                        continue
                    selected_candidates.append(candidate)
                    seen.add(candidate.doc_id)

        selected = [candidate.doc_id for candidate in selected_candidates]
        return RetrievalResult(
            primary_doc=primary_doc,
            total_source_docs=total_source_count,
            selected_source_docs=selected,
            candidates=candidates,
        )
