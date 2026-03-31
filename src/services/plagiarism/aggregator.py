"""结果聚合器

将比对引擎的结果聚合成最终的查重报告。
支持位置追溯、片段合并、分类输出。
"""
import difflib
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.services.plagiarism.engine import DocumentSimilarity, Match


@dataclass
class PlagiarismResult:
    """查重结果"""
    id: str
    total_pairs: int
    high_similarity: List[dict]
    medium_similarity: List[dict]
    low_similarity: List[dict]
    processing_time: float
    filtered_pairs: List[dict] = field(default_factory=list)
    
    # 多源聚合字段
    effective_duplicate_rate: float = 0.0
    effective_duplicate_chars: int = 0
    primary_scope_chars: int = 0
    source_rankings: List[dict] = field(default_factory=list)
    match_groups: List[dict] = field(default_factory=list)


@dataclass
class DuplicateSegmentDetail:
    """重复片段详情"""
    primary_line: int  # 主文档行号
    primary_text: str  # 主文档文本
    primary_section: str = ""  # 主文档所属 Section
    sources: List[dict] = field(default_factory=list)  # 来源文档信息


class ResultAggregator:
    """查重结果聚合器 - 后置过滤模式"""

    MIN_EFFECTIVE_CHARS = 30
    MIN_EFFECTIVE_RATIO = 0.20  # 降低阈值，保留更多有效匹配
    MIN_SEGMENT_LENGTH = 20
    MAX_TEMPLATE_RATIO = 0.7
    MIN_SOURCE_COVERAGE = 0.8
    MIN_LEXICAL_SIMILARITY = 0.20  # 降低阈值，n-gram匹配已经验证过相似性
    MIN_COMMON_SUBSTRING_RATIO = 0.04  # 允许改写场景（同义替换）通过
    MIN_MATCHED_CONTENT_RATIO = 0.30   # 降低阈值，允许更多变体匹配
    MAX_MERGE_BACKTRACK = 12  # 允许少量坐标回退（重叠），禁止跨段倒序拼接
    MIN_SOURCE_TEXT_SPAN_RATIO = 0.18  # source_text 与 source span 明显失配时判为低质量
    MIN_ALIGNED_SIMILARITY = 0.28


    def __init__(self, section_extractor=None, template_filter=None):
        """
        初始化聚合器

        Args:
            section_extractor: Section 提取器（用于位置追溯）
            template_filter: 模板过滤器（用于后置过滤）
        """
        self.section_extractor = section_extractor
        self.template_filter = template_filter

    def _merge_adjacent_matches(self, matches: List[Match], max_gap: int = 25) -> List[Match]:
        """合并同一来源下相邻或轻微间隔的匹配片段。"""
        if not matches:
            return []

        sorted_matches = sorted(matches, key=lambda m: (m.start_pos, m.source_start))
        merged: List[Match] = [sorted_matches[0]]

        for current in sorted_matches[1:]:
            last = merged[-1]
            if current.source_doc != last.source_doc:
                merged.append(current)
                continue

            # 改写补全片段不做跨句拼接，避免误扩成超长段
            if "paraphrase" in {getattr(last, "match_type", "exact"), getattr(current, "match_type", "exact")}:
                merged.append(current)
                continue

            gap_primary = current.start_pos - last.end_pos
            gap_source = current.source_start - last.source_end
            primary_monotonic = gap_primary >= -self.MAX_MERGE_BACKTRACK
            source_monotonic = gap_source >= -self.MAX_MERGE_BACKTRACK

            # 关键约束：primary 与 source 必须同向、近邻，禁止 source 倒序大跨段合并。
            if (
                primary_monotonic
                and source_monotonic
                and gap_primary <= max_gap
                and gap_source <= max_gap
            ):
                merged[-1] = Match(
                    text=(last.text + " " + current.text).strip(),
                    start_pos=min(last.start_pos, current.start_pos),
                    end_pos=max(last.end_pos, current.end_pos),
                    ngram_count=last.ngram_count + current.ngram_count,
                    source_doc=last.source_doc,
                    source_start=min(last.source_start, current.source_start),
                    source_end=max(last.source_end, current.source_end),
                    source_text=(last.source_text + " " + current.source_text).strip(),
                    similarity_score=min(
                        ((last.ngram_count + current.ngram_count) * 1.0) / max(max(last.end_pos, current.end_pos) - min(last.start_pos, current.start_pos), 1),
                        1.0,
                    ),
                    match_type="paraphrase" if ("paraphrase" in {last.match_type, current.match_type}) else "exact",
                    confidence=max(last.confidence, current.confidence),
                    parent_match_id=last.parent_match_id or current.parent_match_id,
                )
            else:
                merged.append(current)

        return merged

    def _build_report_groups(
        self,
        formatted_segments: List[dict],
    ) -> List[dict]:
        """按 section 组织成更像查重报告的分组结构。"""
        groups: Dict[str, dict] = {}

        for segment in formatted_segments:
            section = segment.get("primary_section") or "未分组"
            group = groups.setdefault(section, {
                "primary_section": section,
                "segment_count": 0,
                "total_chars": 0,
                "segments": [],
            })
            group["segments"].append(segment)
            group["segment_count"] += 1
            group["total_chars"] += segment.get("char_count", 0)

        ordered_groups = sorted(
            groups.values(),
            key=lambda item: (-item["total_chars"], item["primary_section"]),
        )
        for group in ordered_groups:
            group["segments"] = sorted(group["segments"], key=lambda seg: (seg.get("primary_line", 0), seg.get("char_count", 0)))
        return ordered_groups

    def _dedupe_formatted_segments(self, segments: List[dict]) -> List[dict]:
        deduped: List[dict] = []
        for seg in sorted(segments, key=lambda x: (int(x.get("primary_start", 0) or 0), -int(x.get("char_count", 0) or 0))):
            replaced = False
            for i, kept in enumerate(deduped):
                overlap = min(int(seg.get("primary_end", 0) or 0), int(kept.get("primary_end", 0) or 0)) - max(
                    int(seg.get("primary_start", 0) or 0),
                    int(kept.get("primary_start", 0) or 0),
                )
                if overlap <= 0:
                    continue
                min_len = max(
                    min(
                        int(seg.get("char_count", 0) or 0),
                        int(kept.get("char_count", 0) or 0),
                    ),
                    1,
                )
                if overlap / min_len < 0.85:
                    continue

                score_new = float(seg.get("similarity_score", 0) or 0) + int(seg.get("char_count", 0) or 0) / 1000.0
                score_old = float(kept.get("similarity_score", 0) or 0) + int(kept.get("char_count", 0) or 0) / 1000.0
                if score_new > score_old:
                    deduped[i] = seg
                replaced = True
                break
            if not replaced:
                deduped.append(seg)
        return deduped

    def aggregate(
        self,
        results: List[DocumentSimilarity],
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        doc_texts: Optional[Dict[str, str]] = None,
        template_filter=None,
    ) -> PlagiarismResult:
        """
        聚合比对结果 - 后置过滤模式

        步骤:
        1. 遍历每个文档对的匹配结果
        2. 对每个匹配片段进行模板检测
        3. 区分"模板重复"和"有效重复"
        4. 计算总相似度和有效相似度

        Args:
            results: 比对结果列表
            threshold_high: 高相似度阈值
            threshold_medium: 中相似度阈值
            doc_texts: 文档原文 {doc_id: text}（用于位置追溯）
            template_filter: 模板过滤器（优先使用）

        Returns:
            查重结果
        """
        # 优先使用传入的过滤器，否则使用初始化时的过滤器
        filter_obj = template_filter or self.template_filter

        high = []
        medium = []
        low = []
        filtered_pairs = []

        for r in results:
            # 分离模板片段和有效片段
            template_segments = []
            effective_segments = []

            for m in r.duplicate_segments:
                # 检测是否是模板内容
                if filter_obj and filter_obj.is_template(m.text):
                    template_segments.append(m)
                else:
                    effective_segments.append(m)

            effective_segments = self._merge_adjacent_matches(effective_segments)
            template_segments = self._merge_adjacent_matches(template_segments)

            effective_segments, rejected_segments = self._filter_low_quality_segments(effective_segments)
            rescued_segments, rejected_segments = self._rescue_high_similarity_segments(rejected_segments)
            effective_segments.extend(rescued_segments)
            # 将被拒绝的片段标记为低质量，而不是模板
            for seg in rejected_segments:
                seg.is_low_quality = True
            template_segments.extend(rejected_segments)

            # 计算有效重复字符数（排除模板）
            effective_chars = sum(len(m.text) for m in effective_segments)
            total_chars = sum(len(m.text) for m in r.duplicate_segments)
            effective_similarity = effective_chars / r.total_chars if r.total_chars > 0 else 0

            pair_filter_reason = self._get_pair_filter_reason(
                effective_segments=effective_segments,
                template_segments=template_segments,
                effective_chars=effective_chars,
                total_chars=total_chars,
                effective_similarity=effective_similarity,
            )

            formatted_effective_segments = self._format_segments(
                effective_segments,
                r.doc_a,
                r.doc_b,
                doc_texts,
                filter_obj,
            )
            formatted_template_segments = self._format_segments(
                template_segments,
                r.doc_a,
                r.doc_b,
                doc_texts,
                filter_obj,
            ) if template_segments else []

            result_dict = {
                "doc_a": r.doc_a,
                "doc_b": r.doc_b,
                "similarity": round(r.similarity, 4),  # 总重复率
                "effective_similarity": round(effective_similarity, 4),  # 有效重复率
                "type": r.type,
                "total_chars": r.total_chars,
                "effective_chars": effective_chars,  # 有效重复字符
                "template_chars": total_chars - effective_chars if total_chars > 0 else 0,  # 模板重复字符
                "duplicate_segments": formatted_effective_segments,
                "template_segments": formatted_template_segments,
                "report_groups": self._build_report_groups(formatted_effective_segments),
                "filter_reason": pair_filter_reason,
            }

            if pair_filter_reason:
                filtered_pairs.append(result_dict)
                continue

            if r.type == "high":
                high.append(result_dict)
            elif r.type == "medium":
                medium.append(result_dict)
            else:
                low.append(result_dict)

        return PlagiarismResult(
            id=f"plagiarism_{int(time.time() * 1000)}",
            total_pairs=len(results),
            high_similarity=high,
            medium_similarity=medium,
            low_similarity=low,
            processing_time=0,  # 由外部计时
            filtered_pairs=filtered_pairs,
        )

    def _get_pair_filter_reason(
        self,
        effective_segments: List[Match],
        template_segments: List[Match],
        effective_chars: int,
        total_chars: int,
        effective_similarity: float,
    ) -> Optional[str]:
        """判断 pair 是否应被过滤，并返回原因。"""
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

        if effective_similarity < self.MIN_EFFECTIVE_RATIO:
            return "effective_similarity_too_low"

        if total_chars > 0:
            template_ratio = len(template_segments) / max(len(effective_segments) + len(template_segments), 1)
            if template_ratio >= self.MAX_TEMPLATE_RATIO:
                return "template_ratio_too_high"

        max_segment_len = max((len(m.text) for m in effective_segments), default=0)
        if max_segment_len < self.MIN_SEGMENT_LENGTH:
            return "segment_too_short"

        return None

    def _filter_low_quality_segments(self, segments: List[Match]) -> Tuple[List[Match], List[Match]]:
        """将明显错配的片段从有效片段中剔除。"""
        kept = []
        rejected = []
        for seg in segments:
            source_text = (seg.source_text or "").strip()
            if not source_text:
                rejected.append(seg)
                continue
            source_span_len = max(int(seg.source_end or 0) - int(seg.source_start or 0), 0)
            if source_span_len > 0:
                source_ratio = len(source_text) / source_span_len
                if source_ratio < self.MIN_SOURCE_TEXT_SPAN_RATIO:
                    rejected.append(seg)
                    continue
            score = self._lexical_ratio(seg.text, source_text)
            if score < self.MIN_LEXICAL_SIMILARITY:
                rejected.append(seg)
                continue
            aligned_score = self._aligned_similarity(seg.text, source_text)
            if aligned_score < self.MIN_ALIGNED_SIMILARITY:
                rejected.append(seg)
                continue
            overlap_ratio = self._common_substring_ratio(seg.text, source_text)
            if overlap_ratio < self.MIN_COMMON_SUBSTRING_RATIO:
                rejected.append(seg)
                continue
            matched_content_ratio = self._matched_content_ratio(seg.text, source_text)
            if matched_content_ratio < self.MIN_MATCHED_CONTENT_RATIO:
                rejected.append(seg)
                continue
            kept.append(seg)
        return kept, rejected

    def _rescue_high_similarity_segments(self, rejected: List[Match]) -> Tuple[List[Match], List[Match]]:
        """从被拒绝片段中挽救“长文本+高相似”的改写段。"""
        rescued: List[Match] = []
        still_rejected: List[Match] = []
        for seg in rejected:
            if len(seg.text or "") < 220:
                still_rejected.append(seg)
                continue
            source_text = (seg.source_text or "").strip()
            if not source_text:
                still_rejected.append(seg)
                continue
            lexical = self._lexical_ratio(seg.text, source_text)
            matched = self._matched_content_ratio(seg.text, source_text)
            if lexical >= 0.55 and matched >= 0.50:
                rescued.append(seg)
                continue
            still_rejected.append(seg)
        return rescued, still_rejected

    def _source_coverage_ratio(self, segments: List[Match]) -> float:
        if not segments:
            return 0.0
        ok = sum(1 for s in segments if (s.source_text or "").strip())
        return ok / len(segments)

    def _avg_lexical_similarity(self, segments: List[Match]) -> float:
        if not segments:
            return 0.0
        scores = [
            self._lexical_ratio(s.text, s.source_text)
            for s in segments
            if (s.source_text or "").strip()
        ]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    @staticmethod
    def _lexical_ratio(text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0
        return difflib.SequenceMatcher(None, text_a, text_b).ratio()

    @staticmethod
    def _common_substring_ratio(text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0

        matcher = difflib.SequenceMatcher(None, text_a, text_b)
        match = matcher.find_longest_match(0, len(text_a), 0, len(text_b))
        if match.size <= 0:
            return 0.0

        base = max(min(len(text_a), len(text_b)), 1)
        return match.size / base

    @staticmethod
    def _matched_content_ratio(text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0

        matcher = difflib.SequenceMatcher(None, text_a, text_b)
        matched_size = sum(block.size for block in matcher.get_matching_blocks())
        if matched_size <= 0:
            return 0.0

        base = max(min(len(text_a), len(text_b)), 1)
        return matched_size / base

    def _aligned_similarity(self, text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0

        norm_a = re.sub(r"\s+", "", text_a)
        norm_b = re.sub(r"\s+", "", text_b)
        if not norm_a or not norm_b:
            return 0.0

        base_score = max(
            self._lexical_ratio(text_a, text_b),
            self._matched_content_ratio(text_a, text_b),
        )
        length_balance = min(len(norm_a), len(norm_b)) / max(len(norm_a), len(norm_b), 1)
        return base_score * length_balance

    def _format_segments(
        self,
        matches: List[Match],
        doc_a: str,
        doc_b: str,
        doc_texts: Optional[Dict[str, str]],
        template_filter=None,
    ) -> List[dict]:
        """
        格式化匹配片段

        Args:
            matches: 匹配列表
            doc_a: 主文档 ID
            doc_b: 来源文档 ID
            doc_texts: 文档原文
            template_filter: 模板过滤器

        Returns:
            格式化后的片段列表
        """
        formatted = []

        for match in matches[:50]:  # 限制数量
            primary_start = int(match.start_pos or 0)
            primary_end = int(match.end_pos or 0)
            if doc_texts and doc_a in doc_texts:
                primary_start, primary_end = self._trim_primary_leading_heading(
                    doc_texts[doc_a],
                    primary_start,
                    primary_end,
                    match.source_text or "",
                )

            # 获取主文档位置信息
            primary_line, primary_text = self._get_line_info(
                doc_a, primary_start, primary_end, doc_texts
            )

            # 获取来源文档位置信息
            source_line, source_text, source_start, source_end = self._get_source_info(
                doc_b, match, doc_texts
            )

            display_similarity = self._aligned_similarity(primary_text, source_text) if source_text else 0

            # 获取主文档 Section 信息
            primary_section = ""
            if self.section_extractor and doc_texts and doc_a in doc_texts:
                primary_section = self._find_section_for_position(
                    doc_texts[doc_a], match.start_pos
                )

            # 获取模板原因
            template_reason = None
            if template_filter:
                template_reason = template_filter.get_template_reason(match.text)
                if template_reason is None and template_filter.is_template(match.text):
                    template_reason = "template"
            
            # 检查是否是低质量片段（被拒绝的匹配）
            is_low_quality = getattr(match, 'is_low_quality', False)
            if is_low_quality and template_reason is None:
                template_reason = "low_quality"

            formatted.append({
                "primary_line": primary_line,
                "primary_text": primary_text,
                "primary_section": primary_section,
                "primary_start": primary_start,
                "primary_end": primary_end,
                "sources": [{
                    "doc": doc_b,
                    "line": source_line,
                    "text": source_text,
                    "start": source_start,
                    "end": source_end,
                }],
                "char_count": len(match.text),
                "ngram_count": match.ngram_count,
                "similarity_score": round(display_similarity, 4) if display_similarity else 0,
                "match_type": getattr(match, "match_type", "exact"),
                "confidence": round(getattr(match, "confidence", 1.0), 4),
                "parent_match_id": getattr(match, "parent_match_id", None),
                "is_template": template_reason is not None,
                "template_reason": template_reason,
            })

        return formatted

    def _trim_primary_leading_heading(
        self,
        text: str,
        start: int,
        end: int,
        source_text: str,
    ) -> Tuple[int, int]:
        if not text or end <= start or not source_text:
            return start, end

        segment = text[start:end]
        first_break = segment.find("\n")
        if first_break == -1:
            return start, end

        first_line = segment[:first_break].strip()
        if not self._looks_like_heading_line(first_line):
            return start, end

        heading_norm = self._normalize_heading_for_compare(first_line)
        source_norm = self._normalize_heading_for_compare(source_text)
        if heading_norm and heading_norm in source_norm:
            return start, end

        new_start = start + first_break + 1
        while new_start < end and text[new_start] in {"\n", "\r", " "}:
            new_start += 1
        return (new_start, end) if end - new_start >= self.MIN_SEGMENT_LENGTH else (start, end)

    def _looks_like_heading_line(self, text: str) -> bool:
        normalized = self._normalize_heading_for_compare(text)
        if not normalized:
            return False
        return bool(re.match(
            r"^(项目简介|项目立项背景及意义|第[一二三四五六七八九十百]+部分|第一部分|第二部分|第三部分|第四部分|第五部分|"
            r"[一二三四五六七八九十]+[、\.．]|[（(][一二三四五六七八九十]+[）)]|"
            r"\d+[、\.．]|[（(]\d+[）)])",
            normalized,
        ))

    def _normalize_heading_for_compare(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", text or "")
        normalized = normalized.replace("（", "(").replace("）", ")")
        return normalized

    def _get_source_info(
        self,
        doc_id: str,
        match: Match,
        doc_texts: Optional[Dict[str, str]],
    ) -> Tuple[int, str, int, int]:
        """获取来源文档行号、文本和可展示坐标。"""
        start = int(match.source_start or 0)
        end = int(match.source_end or 0)

        if not doc_texts or doc_id not in doc_texts:
            source_text = (match.source_text or "").replace('\n', ' ').strip()
            return 0, source_text, start, max(start, end)

        text = doc_texts[doc_id]
        if not text:
            source_text = (match.source_text or "").replace('\n', ' ').strip()
            return 0, source_text, start, max(start, end)

        if match.source_text:
            candidate = match.source_text.replace('\n', ' ').strip()
            found_start = self._find_source_start_by_text(text, candidate, start)
            if found_start != -1:
                found_end = min(len(text), found_start + len(candidate))
                line = text[:found_start].count('\n') + 1 if found_start > 0 else 1
                return line, candidate, found_start, found_end

        line, source_text = self._get_line_info(doc_id, start, end, doc_texts)
        return line, source_text, start, max(start, end)

    def _find_source_start_by_text(self, text: str, candidate: str, anchor_start: int) -> int:
        if not candidate:
            return -1

        best = -1
        best_dist = None

        # 先在锚点附近搜索，避免命中同句的远处重复。
        local_left = max(0, anchor_start - 1500)
        local_right = min(len(text), anchor_start + 1500)
        pos = text.find(candidate, local_left, local_right)
        while pos != -1:
            dist = abs(pos - anchor_start)
            if best_dist is None or dist < best_dist:
                best = pos
                best_dist = dist
            pos = text.find(candidate, pos + 1, local_right)
        if best != -1:
            return best

        # 兜底全局搜索
        pos = text.find(candidate)
        while pos != -1:
            dist = abs(pos - anchor_start)
            if best_dist is None or dist < best_dist:
                best = pos
                best_dist = dist
            pos = text.find(candidate, pos + 1)
        return best

    def _get_line_info(
        self,
        doc_id: str,
        start_pos: int,
        end_pos: int,
        doc_texts: Optional[Dict[str, str]],
    ) -> Tuple[int, str]:
        """
        根据字符位置获取行号和文本

        Args:
            doc_id: 文档 ID
            start_pos: 起始位置
            end_pos: 结束位置
            doc_texts: 文档原文

        Returns:
            (行号, 文本)
        """
        if not doc_texts or doc_id not in doc_texts:
            return 0, ""

        text = doc_texts[doc_id]

        # 提取片段
        if start_pos < len(text) and end_pos <= len(text):
            segment_text = text[start_pos:end_pos]
        else:
            segment_text = ""

        # 计算行号（从起始位置到片段开始的换行符数量 + 1）
        line_number = text[:start_pos].count('\n') + 1 if start_pos > 0 else 1

        # 清理文本（去换行）
        cleaned_text = segment_text.replace('\n', ' ').strip()

        return line_number, cleaned_text

    def _find_section_for_position(self, text: str, position: int) -> str:
        """
        根据字符位置查找所属 Section

        Args:
            text: 文档全文
            position: 字符位置

        Returns:
            Section 名称
        """
        if not self.section_extractor:
            return ""

        sections = self.section_extractor.sections
        if not sections:
            return ""

        for section in sections:
            start_pattern = section.get("start_pattern", "")
            if not start_pattern:
                continue

            import re
            start_regex = re.compile(start_pattern)
            start_match = start_regex.search(text)

            if not start_match:
                continue

            start_pos = start_match.start()
            end_pattern = section.get("end_pattern")

            if end_pattern:
                end_regex = re.compile(end_pattern)
                end_match = end_regex.search(text[start_pos + 1:])
                if end_match:
                    end_pos = start_pos + 1 + end_match.start()
                else:
                    end_pos = len(text)
            else:
                end_pos = len(text)

            # 检查是否在范围内
            if start_pos <= position < end_pos:
                return section.get("name", "")

        return ""

    def format_debug_output(
        self,
        results: List[DocumentSimilarity],
        doc_texts: Dict[str, str],
        primary_doc_id: str,
        template_filter=None,
    ) -> dict:
        """
        格式化 debug 输出

        Args:
            results: 比对结果
            doc_texts: 文档原文
            primary_doc_id: 主文档 ID
            template_filter: 模板过滤器

        Returns:
            debug 输出字典
        """
        primary_text = doc_texts.get(primary_doc_id, "")

        output = {
            "primary_doc": primary_doc_id,
            "total_docs": len(doc_texts),
            "text_lengths": {doc_id: len(text) for doc_id, text in doc_texts.items()},
            "processing": {
                "total_sentences": primary_text.count('。') + primary_text.count('！') + primary_text.count('？'),
            },
        }

        # 添加 Section 信息
        if self.section_extractor:
            sections_info = []
            for section in self.section_extractor.sections:
                start_pattern = section.get("start_pattern", "")
                end_pattern = section.get("end_pattern")

                import re
                start_regex = re.compile(start_pattern)
                start_match = start_regex.search(primary_text)

                if start_match:
                    start_pos = start_match.start()
                    if end_pattern:
                        end_regex = re.compile(end_pattern)
                        end_match = end_regex.search(primary_text[start_pos + 1:])
                        if end_match:
                            end_pos = start_pos + 1 + end_match.start()
                        else:
                            end_pos = len(primary_text)
                    else:
                        end_pos = len(primary_text)

                    section_text = primary_text[start_pos:end_pos]
                    lines = section_text.split('\n')
                    start_line = primary_text[:start_pos].count('\n') + 1
                    end_line = start_line + len(lines) - 1

                    sections_info.append({
                        "name": section.get("name", ""),
                        "start_line": start_line,
                        "end_line": end_line,
                        "char_count": len(section_text),
                    })

            output["sections_info"] = sections_info

        # 添加重复片段（应用后置过滤）
        effective_segments = []
        template_segments = []
        total_effective_chars = 0
        total_template_chars = 0

        filtered_pairs = []

        for r in results:
            raw_template_segments = []
            raw_effective_segments = []

            for match in r.duplicate_segments[:50]:
                if template_filter and template_filter.is_template(match.text):
                    raw_template_segments.append(match)
                else:
                    raw_effective_segments.append(match)

            raw_effective_segments = self._merge_adjacent_matches(raw_effective_segments)
            raw_template_segments = self._merge_adjacent_matches(raw_template_segments)

            pair_effective_segments, rejected_segments = self._filter_low_quality_segments(raw_effective_segments)
            rescued_segments, rejected_segments = self._rescue_high_similarity_segments(rejected_segments)
            pair_effective_segments.extend(rescued_segments)
            pair_template_segments = raw_template_segments + rejected_segments

            pair_effective_chars = sum(len(m.text) for m in pair_effective_segments)
            pair_template_chars = sum(len(m.text) for m in pair_template_segments)

            formatted_effective_segments = self._format_segments(
                pair_effective_segments,
                r.doc_a,
                r.doc_b,
                doc_texts,
                template_filter,
            )
            formatted_template_segments = self._format_segments(
                pair_template_segments,
                r.doc_a,
                r.doc_b,
                doc_texts,
                template_filter,
            ) if pair_template_segments else []

            for seg_info in formatted_effective_segments:
                seg_info["similarity_pair"] = f"{r.doc_a} vs {r.doc_b}"
                effective_segments.append(seg_info)

            for seg_info in formatted_template_segments:
                seg_info["similarity_pair"] = f"{r.doc_a} vs {r.doc_b}"
                template_segments.append(seg_info)

            pair_filter_reason = self._get_pair_filter_reason(
                effective_segments=pair_effective_segments,
                template_segments=pair_template_segments,
                effective_chars=pair_effective_chars,
                total_chars=sum(len(m.text) for m in r.duplicate_segments),
                effective_similarity=(pair_effective_chars / sum(len(m.text) for m in r.duplicate_segments)) if r.duplicate_segments else 0,
            )

            if pair_filter_reason:
                filtered_pairs.append({
                    "pair": f"{r.doc_a} vs {r.doc_b}",
                    "reason": pair_filter_reason,
                })

            total_effective_chars += pair_effective_chars
            total_template_chars += pair_template_chars

        effective_segments = self._dedupe_formatted_segments(effective_segments)
        template_segments = self._dedupe_formatted_segments(template_segments)

        def _segment_sort_key(seg: dict) -> tuple:
            text = str(seg.get("primary_text", "") or "")
            is_meta = (
                "申报书" in text
                or "填 报 说 明" in text
                or "单位名称" in text
                or "指南代码" in text
            )
            return (
                1 if is_meta else 0,
                int(seg.get("primary_start", 0) or 0),
                -int(seg.get("char_count", 0) or 0),
            )

        effective_segments.sort(key=_segment_sort_key)
        template_segments.sort(key=_segment_sort_key)

        for idx, seg in enumerate(effective_segments, start=1):
            seg["match_id"] = f"m{idx:03d}"

        for idx, seg in enumerate(template_segments, start=1):
            seg["match_id"] = f"t{idx:03d}"

        output["duplicate_segments"] = effective_segments
        output["template_segments"] = template_segments
        output["report_groups"] = self._build_report_groups(effective_segments)
        output["filtered_pairs"] = filtered_pairs
        output["summary"] = {
            "total_effective_segments": len(effective_segments),
            "total_template_segments": len(template_segments),
            "total_effective_chars": total_effective_chars,
            "total_template_chars": total_template_chars,
            "total_filtered_pairs": len(filtered_pairs),
        }

        return output
