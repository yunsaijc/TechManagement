from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from src.services.plagiarism.aggregator import Match, ResultAggregator


class ByFileIngestResultAggregator(ResultAggregator):
    """仅供 `/by-file` + `file_local_ingest` 语料使用的专属聚合器。"""

    def __init__(self, section_extractor=None, template_filter=None):
        super().__init__(section_extractor=section_extractor, template_filter=template_filter)
        self._doc_texts: Optional[Dict[str, str]] = None

    def aggregate(
        self,
        results,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        doc_texts: Optional[Dict[str, str]] = None,
        template_filter=None,
    ):
        self._doc_texts = doc_texts or {}
        try:
            result = super().aggregate(
                results,
                threshold_high=threshold_high,
                threshold_medium=threshold_medium,
                doc_texts=doc_texts,
                template_filter=template_filter,
            )
            self._reclassify_result_pairs(result, template_filter=template_filter)
            return result
        finally:
            self._doc_texts = None

    def format_debug_output(
        self,
        results,
        doc_texts: Dict[str, str],
        primary_doc_id: str,
        template_filter=None,
    ) -> dict:
        output = super().format_debug_output(
            results,
            doc_texts,
            primary_doc_id,
            template_filter=template_filter,
        )
        return self._reclassify_debug_output(output, template_filter=template_filter)

    def _source_excerpt_for_quality(self, match: Match) -> str:
        doc_texts = self._doc_texts or {}
        doc_id = str(match.source_doc or "")
        start = int(match.source_start or 0)
        end = int(match.source_end or 0)

        if doc_id and doc_id in doc_texts:
            text = doc_texts.get(doc_id) or ""
            if text and 0 <= start < end <= len(text):
                return text[start:end].replace("\n", " ").strip()

        return (match.source_text or "").replace("\n", " ").strip()

    def _filter_low_quality_segments(self, segments: List[Match]) -> Tuple[List[Match], List[Match]]:
        kept: List[Match] = []
        rejected: List[Match] = []

        for seg in segments:
            text = (seg.text or "").strip()
            source_text = self._source_excerpt_for_quality(seg)

            if self._is_reward_fixed_boilerplate(text) or self._is_reward_fixed_boilerplate(source_text):
                rejected.append(seg)
                continue
            if self._is_reference_like(text) or self._is_reference_like(source_text):
                rejected.append(seg)
                continue
            if self._is_instruction_like(text) or self._is_instruction_like(source_text):
                rejected.append(seg)
                continue
            if not source_text:
                rejected.append(seg)
                continue
            if self._has_major_entity_conflict(text, source_text):
                rejected.append(seg)
                continue

            aligned_score = self._aligned_similarity(text, source_text)
            matched_content_ratio = self._matched_content_ratio(text, source_text)

            short_relaxed = (
                len(text) < self.MIN_SHORT_SEGMENT_CHARS
                and len(re.findall(r"[\u4e00-\u9fff]", text)) >= 28
                and matched_content_ratio >= 0.72
            )
            quality_score = max(aligned_score, matched_content_ratio) if short_relaxed else aligned_score

            if len(text) < self.MIN_SHORT_SEGMENT_CHARS and (not short_relaxed) and aligned_score < self.MIN_SHORT_SEGMENT_SIMILARITY:
                rejected.append(seg)
                continue

            if (self._is_schedule_like(text) or self._is_schedule_like(source_text)) and quality_score < self.MIN_SCHEDULE_SIMILARITY:
                rejected.append(seg)
                continue

            source_span_len = max(int(seg.source_end or 0) - int(seg.source_start or 0), 0)
            if source_span_len > 0:
                source_ratio = len(source_text) / source_span_len
                if source_ratio < self.MIN_SOURCE_TEXT_SPAN_RATIO:
                    rejected.append(seg)
                    continue

            score = self._lexical_ratio(text, source_text)
            if self._is_strict_english_title_pair(text, source_text):
                if score < 0.55 or quality_score < 0.72 or matched_content_ratio < 0.55:
                    rejected.append(seg)
                    continue
            if score < self.MIN_LEXICAL_SIMILARITY:
                rejected.append(seg)
                continue
            if quality_score < self.MIN_ALIGNED_SIMILARITY:
                rejected.append(seg)
                continue

            overlap_ratio = self._common_substring_ratio(text, source_text)
            if overlap_ratio < self.MIN_COMMON_SUBSTRING_RATIO:
                rejected.append(seg)
                continue

            if matched_content_ratio < self.MIN_MATCHED_CONTENT_RATIO:
                rejected.append(seg)
                continue

            seg.source_text = source_text
            kept.append(seg)

        return kept, rejected

    def _get_pair_filter_reason(
        self,
        effective_segments: List[Match],
        template_segments: List[Match],
        effective_chars: int,
        total_chars: int,
        effective_similarity: float,
    ) -> Optional[str]:
        if not effective_segments:
            return "no_effective_segments"

        source_coverage = self._source_coverage_ratio(effective_segments)
        if source_coverage < self.MIN_SOURCE_COVERAGE:
            return "source_text_coverage_too_low"

        lexical_similarity = self._avg_lexical_similarity(effective_segments)
        if lexical_similarity < self.MIN_LEXICAL_SIMILARITY:
            return "lexical_similarity_too_low"

        if effective_chars < self.MIN_EFFECTIVE_CHARS:
            return "too_few_effective_chars"

        # by-file + file_local_ingest 场景下，单个来源文档覆盖率通常不高，
        # 继续沿用通用 20% pair 门槛会把真实命中全部过滤掉。
        if effective_similarity < 0.04:
            return "effective_similarity_too_low"

        if total_chars > 0:
            template_ratio = len(template_segments) / max(len(effective_segments) + len(template_segments), 1)
            if template_ratio >= self.MAX_TEMPLATE_RATIO:
                return "template_ratio_too_high"

        max_segment_len = max((len(m.text) for m in effective_segments), default=0)
        if max_segment_len < self.MIN_SEGMENT_LENGTH:
            return "segment_too_short"

        return None

    def _get_source_info(
        self,
        doc_id: str,
        match: Match,
        doc_texts: Optional[Dict[str, str]],
    ):
        start = int(match.source_start or 0)
        end = int(match.source_end or 0)

        if doc_texts and doc_id in doc_texts:
            text = doc_texts.get(doc_id) or ""
            if text and 0 <= start < end <= len(text):
                primary_text = (match.text or "").strip()
                if primary_text:
                    window = text[start:end]
                    idx = window.find(primary_text)
                    if idx != -1:
                        new_start = start + idx
                        new_end = new_start + len(primary_text)
                        line = text[:new_start].count("\n") + 1 if new_start > 0 else 1
                        snippet = text[new_start:new_end].replace("\n", " ").strip()
                        return line, snippet, new_start, new_end

                line = text[:start].count("\n") + 1 if start > 0 else 1
                snippet = text[start:end].replace("\n", " ").strip()
                return line, snippet, start, end

        return super()._get_source_info(doc_id, match, doc_texts)

    def _format_segments(
        self,
        matches: List[Match],
        doc_a: str,
        doc_b: str,
        doc_texts: Optional[Dict[str, str]],
        template_filter,
    ) -> List[dict]:
        formatted = super()._format_segments(matches, doc_a, doc_b, doc_texts, template_filter)
        if not formatted or not doc_texts or doc_a not in doc_texts or doc_b not in doc_texts:
            return formatted

        primary_full = doc_texts.get(doc_a) or ""
        source_full = doc_texts.get(doc_b) or ""
        if not primary_full or not source_full:
            return formatted

        normalized_segments: List[dict] = []
        for seg in formatted:
            sources = seg.get("sources") or []
            if not sources:
                normalized_segments.append(seg)
                continue

            cloned = dict(seg)
            source_info = dict(sources[0])
            primary_start = int(cloned.get("primary_start", 0) or 0)
            primary_end = int(cloned.get("primary_end", 0) or 0)
            source_start = int(source_info.get("start", 0) or 0)
            source_end = int(source_info.get("end", 0) or 0)

            primary_line_start, primary_line_end, primary_line_text = self._get_line_bounds_and_text(
                primary_full,
                primary_start,
                primary_end,
            )
            source_line_start, source_line_end, source_line_text = self._get_line_bounds_and_text(
                source_full,
                source_start,
                source_end,
            )

            use_full_line = (
                self._contains_substantial_english(primary_line_text)
                or self._contains_substantial_english(source_line_text)
            ) and self._english_lines_exact_match(primary_line_text, source_line_text)

            if use_full_line:
                primary_start, primary_end = primary_line_start, primary_line_end
                source_start, source_end = source_line_start, source_line_end
                primary_text = primary_line_text
                source_text = source_line_text
                primary_line = primary_full[:primary_start].count("\n") + 1 if primary_start > 0 else 1
                source_line = source_full[:source_start].count("\n") + 1 if source_start > 0 else 1
            else:
                primary_line, primary_text = self._get_line_info(doc_a, primary_start, primary_end, doc_texts)
                source_line = source_full[:source_start].count("\n") + 1 if source_start > 0 else 1
                source_text = source_full[source_start:source_end].replace("\n", " ").strip()

            display_similarity = self._aligned_similarity(primary_text, source_text) if source_text else 0.0
            cloned["primary_line"] = primary_line
            cloned["primary_text"] = primary_text
            cloned["primary_start"] = primary_start
            cloned["primary_end"] = primary_end
            cloned["char_count"] = max(0, len(primary_text))
            cloned["similarity_score"] = round(display_similarity, 4) if display_similarity else 0
            cloned["sources"] = [
                {
                    "doc": doc_b,
                    "line": source_line,
                    "text": source_text,
                    "start": source_start,
                    "end": source_end,
                }
            ]
            normalized_segments.append(cloned)

        normalized_segments.sort(
            key=lambda item: (int(item.get("primary_start", 0) or 0), -int(item.get("char_count", 0) or 0))
        )
        return normalized_segments

    def _segment_is_template(
        self,
        primary_text: str,
        source_text: str,
        template_filter,
    ) -> Tuple[bool, Optional[str]]:
        primary = re.sub(r"\s+", " ", str(primary_text or "")).strip()
        source = re.sub(r"\s+", " ", str(source_text or "")).strip()

        for text in (primary, source):
            if not text:
                continue
            if self._is_reward_fixed_boilerplate(text):
                return True, "fixed_boilerplate"
            if self._is_reference_like(text):
                return True, "reference_like"
            if self._is_instruction_like(text):
                return True, "instruction_like"
            if self._is_schedule_like(text):
                return True, "schedule_like"

            if template_filter:
                min_len = int(getattr(template_filter, "MIN_SENTENCE_LENGTH", 15))
                if len(text) < min_len and not self._contains_substantial_english(text):
                    return True, "short"
                if getattr(template_filter, "_is_heading", None) and template_filter._is_heading(text):
                    return True, "heading"
                if getattr(template_filter, "_is_table_related", None) and template_filter._is_table_related(text):
                    return True, "table"
                if getattr(template_filter, "_is_template", None) and template_filter._is_template(text):
                    return True, "whitelist"
                if getattr(template_filter, "_is_number_only", None) and template_filter._is_number_only(text):
                    return True, "number_only"

        return False, None

    def _segment_is_effective(
        self,
        primary_text: str,
        source_text: str,
        primary_span_len: int,
        source_span_len: int,
    ) -> Tuple[bool, Optional[str]]:
        primary = re.sub(r"\s+", " ", str(primary_text or "")).strip()
        source = re.sub(r"\s+", " ", str(source_text or "")).strip()
        if not primary:
            return False, "empty_primary"
        if not source:
            return False, "missing_source"
        if primary_span_len <= 0:
            return False, "empty_primary_span"
        if self._is_reward_fixed_boilerplate(primary) or self._is_reward_fixed_boilerplate(source):
            return False, "fixed_boilerplate"

        if self._is_reference_like(primary) or self._is_reference_like(source):
            return False, "reference_like"
        if self._is_instruction_like(primary) or self._is_instruction_like(source):
            return False, "instruction_like"
        if self._has_major_entity_conflict(primary, source):
            return False, "entity_conflict"

        aligned_score = self._aligned_similarity(primary, source)
        matched_content_ratio = self._matched_content_ratio(primary, source)

        short_relaxed = (
            len(primary) < self.MIN_SHORT_SEGMENT_CHARS
            and len(re.findall(r"[\u4e00-\u9fff]", primary)) >= 28
            and matched_content_ratio >= 0.72
        )
        quality_score = max(aligned_score, matched_content_ratio) if short_relaxed else aligned_score

        if len(primary) < self.MIN_SHORT_SEGMENT_CHARS and (not short_relaxed) and aligned_score < self.MIN_SHORT_SEGMENT_SIMILARITY:
            if len(primary) >= 220:
                lexical = self._lexical_ratio(primary, source)
                if lexical >= 0.55 and matched_content_ratio >= 0.50:
                    return True, "rescued"
            return False, "short_similarity_too_low"

        if (self._is_schedule_like(primary) or self._is_schedule_like(source)) and quality_score < self.MIN_SCHEDULE_SIMILARITY:
            return False, "schedule_similarity_too_low"

        if source_span_len > 0:
            source_ratio = len(source) / max(int(source_span_len), 1)
            if source_ratio < self.MIN_SOURCE_TEXT_SPAN_RATIO:
                return False, "source_span_ratio_too_low"

        lexical = self._lexical_ratio(primary, source)
        if self._contains_substantial_english(primary) or self._contains_substantial_english(source):
            if not self._english_lines_exact_match(primary, source):
                return False, "english_title_not_exact_match"
        if lexical < self.MIN_LEXICAL_SIMILARITY:
            return False, "lexical_similarity_too_low"

        if quality_score < self.MIN_ALIGNED_SIMILARITY:
            if len(primary) >= 220 and lexical >= 0.55 and matched_content_ratio >= 0.50:
                return True, "rescued"
            return False, "aligned_similarity_too_low"

        overlap_ratio = self._common_substring_ratio(primary, source)
        if overlap_ratio < self.MIN_COMMON_SUBSTRING_RATIO:
            return False, "common_substring_too_low"

        if matched_content_ratio < self.MIN_MATCHED_CONTENT_RATIO:
            return False, "matched_content_ratio_too_low"

        return True, None

    @staticmethod
    def _is_english_title_like(text: str) -> bool:
        sample = str(text or "").strip()
        if not sample:
            return False
        zh_count = len(re.findall(r"[\u4e00-\u9fff]", sample))
        alpha_count = len(re.findall(r"[A-Za-z]", sample))
        word_count = len(re.findall(r"[A-Za-z]{2,}", sample))
        return zh_count <= 4 and alpha_count >= 24 and word_count >= 5

    def _is_strict_english_title_pair(self, primary_text: str, source_text: str) -> bool:
        return self._is_english_title_like(primary_text) and self._is_english_title_like(source_text)

    @staticmethod
    def _contains_substantial_english(text: str) -> bool:
        sample = str(text or "").strip()
        alpha_count = len(re.findall(r"[A-Za-z]", sample))
        word_count = len(re.findall(r"[A-Za-z]{2,}", sample))
        return alpha_count >= 24 and word_count >= 5

    @staticmethod
    def _normalize_english_title(text: str) -> str:
        cleaned = str(text or "").strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s*([:;,.\-_/()])\s*", r"\1", cleaned)
        return cleaned

    def _english_lines_exact_match(self, primary_text: str, source_text: str) -> bool:
        return self._normalize_english_title(primary_text) == self._normalize_english_title(source_text)

    @staticmethod
    def _is_reward_fixed_boilerplate(text: str) -> bool:
        norm = re.sub(r"\s+", "", str(text or ""))
        if not norm:
            return False
        norm = re.sub(r"\[表格表头\d+\]", "", norm)
        norm = norm.replace("科技局限性", "")

        if "项目详细内容" in norm and "不超过6页" in norm:
            return True
        if "立项背景、主要科技创新" in norm and "知识产权及标准规范等情况" in norm:
            return True
        if (
            "立项背景" in norm
            and "主要科技创新" in norm
            and ("当前国内外同类技术主要参数" in norm or "市场竞争力的比较" in norm)
            and "知识产权及标准规范等情况" in norm
        ):
            return True
        return False

    @staticmethod
    def _has_major_entity_conflict(primary_text: str, source_text: str) -> bool:
        primary = str(primary_text or "")
        source = str(source_text or "")

        esophagus_tokens = ("食管", "食道")
        breast_tokens = ("乳腺", "乳房")

        primary_esophagus = any(token in primary for token in esophagus_tokens)
        source_esophagus = any(token in source for token in esophagus_tokens)
        primary_breast = any(token in primary for token in breast_tokens)
        source_breast = any(token in source for token in breast_tokens)

        if primary_esophagus and source_breast:
            return True
        if primary_breast and source_esophagus:
            return True
        return False

    @staticmethod
    def _get_line_bounds_and_text(text: str, start: int, end: int) -> Tuple[int, int, str]:
        if not text:
            return 0, 0, ""
        safe_start = max(0, min(int(start or 0), len(text)))
        safe_end = max(safe_start, min(int(end or 0), len(text)))
        line_start = text.rfind("\n", 0, safe_start) + 1
        line_end = text.find("\n", safe_end)
        if line_end == -1:
            line_end = len(text)
        line_text = text[line_start:line_end].strip()
        return line_start, line_end, line_text

    @staticmethod
    def _union_length_from_formatted(segments: List[dict]) -> int:
        spans = sorted(
            [
                (int(seg.get("primary_start", 0) or 0), int(seg.get("primary_end", 0) or 0))
                for seg in (segments or [])
                if int(seg.get("primary_end", 0) or 0) > int(seg.get("primary_start", 0) or 0)
            ],
            key=lambda item: item[0],
        )
        if not spans:
            return 0
        merged: list[tuple[int, int]] = []
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
                continue
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))
        return sum(e - s for s, e in merged)

    def _reclassify_debug_output(self, output: dict, template_filter=None) -> dict:
        all_segments = list(output.get("duplicate_segments", []) or []) + list(output.get("template_segments", []) or [])
        effective_segments: List[dict] = []
        template_segments: List[dict] = []

        for seg in all_segments:
            primary_text = str(seg.get("primary_text", "") or "")
            sources = seg.get("sources") or []
            source_text = str((sources[0].get("text") if sources else "") or "")
            is_template, template_reason = self._segment_is_template(
                primary_text=primary_text,
                source_text=source_text,
                template_filter=template_filter,
            )
            if not is_template:
                primary_span_len = int(seg.get("primary_end", 0) or 0) - int(seg.get("primary_start", 0) or 0)
                source_span_len = 0
                if sources:
                    source_span_len = int(sources[0].get("end", 0) or 0) - int(sources[0].get("start", 0) or 0)
                is_effective, ineffective_reason = self._segment_is_effective(
                    primary_text=primary_text,
                    source_text=source_text,
                    primary_span_len=primary_span_len,
                    source_span_len=source_span_len,
                )
                if not is_effective:
                    is_template = True
                    template_reason = ineffective_reason or "low_quality"

            seg["is_template"] = is_template
            seg["template_reason"] = template_reason
            if is_template:
                template_segments.append(seg)
            else:
                effective_segments.append(seg)

        effective_segments = self._dedupe_formatted_segments(effective_segments)
        template_segments = self._dedupe_formatted_segments(template_segments)

        effective_segments.sort(key=lambda seg: (int(seg.get("primary_start", 0) or 0), -int(seg.get("char_count", 0) or 0)))
        template_segments.sort(key=lambda seg: (int(seg.get("primary_start", 0) or 0), -int(seg.get("char_count", 0) or 0)))

        for idx, seg in enumerate(effective_segments, start=1):
            seg["match_id"] = f"m{idx:03d}"

        for idx, seg in enumerate(template_segments, start=1):
            seg["match_id"] = f"t{idx:03d}"

        output["duplicate_segments"] = effective_segments
        output["template_segments"] = template_segments
        output["report_groups"] = self._build_report_groups(effective_segments)

        summary = dict(output.get("summary") or {})
        summary["total_effective_segments"] = len(effective_segments)
        summary["total_template_segments"] = len(template_segments)
        summary["total_effective_chars"] = self._union_length_from_formatted(effective_segments)
        summary["total_template_chars"] = self._union_length_from_formatted(template_segments)
        summary.setdefault("total_filtered_pairs", len(output.get("filtered_pairs") or []))
        output["summary"] = summary
        return output

    def _reclassify_result_pairs(self, result, template_filter=None) -> None:
        filtered_pairs = list(result.filtered_pairs or [])
        new_high = []
        new_medium = []
        new_low = []

        def _reclassify_pair_dict(pair: dict) -> dict:
            segments = list(pair.get("duplicate_segments", []) or []) + list(pair.get("template_segments", []) or [])
            effective_segments: List[dict] = []
            template_segments: List[dict] = []
            for seg in segments:
                primary_text = str(seg.get("primary_text", "") or "")
                sources = seg.get("sources") or []
                source_text = str((sources[0].get("text") if sources else "") or "")
                is_template, template_reason = self._segment_is_template(
                    primary_text=primary_text,
                    source_text=source_text,
                    template_filter=template_filter,
                )
                if not is_template:
                    primary_span_len = int(seg.get("primary_end", 0) or 0) - int(seg.get("primary_start", 0) or 0)
                    source_span_len = 0
                    if sources:
                        source_span_len = int(sources[0].get("end", 0) or 0) - int(sources[0].get("start", 0) or 0)
                    is_effective, ineffective_reason = self._segment_is_effective(
                        primary_text=primary_text,
                        source_text=source_text,
                        primary_span_len=primary_span_len,
                        source_span_len=source_span_len,
                    )
                    if not is_effective:
                        is_template = True
                        template_reason = ineffective_reason or "low_quality"

                seg["is_template"] = is_template
                seg["template_reason"] = template_reason
                if is_template:
                    template_segments.append(seg)
                else:
                    effective_segments.append(seg)

            effective_segments = self._dedupe_formatted_segments(effective_segments)
            template_segments = self._dedupe_formatted_segments(template_segments)
            pair["duplicate_segments"] = effective_segments
            pair["template_segments"] = template_segments
            pair["report_groups"] = self._build_report_groups(effective_segments)

            total_chars = int(pair.get("total_chars", 0) or 0)
            effective_chars = self._union_length_from_formatted(effective_segments)
            template_chars = self._union_length_from_formatted(template_segments)
            total_duplicate_chars = self._union_length_from_formatted(effective_segments + template_segments)
            similarity = (total_duplicate_chars / total_chars) if total_chars > 0 else 0.0
            effective_similarity = (effective_chars / total_chars) if total_chars > 0 else 0.0

            pair["effective_chars"] = effective_chars
            pair["template_chars"] = template_chars
            pair["similarity"] = round(similarity, 4)
            pair["effective_similarity"] = round(effective_similarity, 4)

            if not effective_segments:
                pair["filter_reason"] = "no_effective_segments"

            return pair

        for pair in list(result.high_similarity or []):
            pair = _reclassify_pair_dict(pair)
            if pair.get("filter_reason"):
                filtered_pairs.append(pair)
            else:
                new_high.append(pair)

        for pair in list(result.medium_similarity or []):
            pair = _reclassify_pair_dict(pair)
            if pair.get("filter_reason"):
                filtered_pairs.append(pair)
            else:
                new_medium.append(pair)

        for pair in list(result.low_similarity or []):
            pair = _reclassify_pair_dict(pair)
            if pair.get("filter_reason"):
                filtered_pairs.append(pair)
            else:
                new_low.append(pair)

        filtered_pairs = [_reclassify_pair_dict(pair) for pair in filtered_pairs]

        seen = set()
        deduped_filtered = []
        for pair in filtered_pairs:
            key = (str(pair.get("doc_a", "")), str(pair.get("doc_b", "")))
            if key in seen:
                continue
            seen.add(key)
            deduped_filtered.append(pair)

        result.high_similarity = new_high
        result.medium_similarity = new_medium
        result.low_similarity = new_low
        result.filtered_pairs = deduped_filtered
