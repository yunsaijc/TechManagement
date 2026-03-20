"""结果聚合器

将比对引擎的结果聚合成最终的查重报告。
支持位置追溯、片段合并、分类输出。
"""
import difflib
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
    MIN_EFFECTIVE_RATIO = 0.35
    MIN_SEGMENT_LENGTH = 20
    MAX_TEMPLATE_RATIO = 0.7
    MIN_SOURCE_COVERAGE = 0.8
    MIN_LEXICAL_SIMILARITY = 0.30

    def __init__(self, section_extractor=None, template_filter=None):
        """
        初始化聚合器

        Args:
            section_extractor: Section 提取器（用于位置追溯）
            template_filter: 模板过滤器（用于后置过滤）
        """
        self.section_extractor = section_extractor
        self.template_filter = template_filter

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

            effective_segments, rejected_segments = self._filter_low_quality_segments(effective_segments)
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

            result_dict = {
                "doc_a": r.doc_a,
                "doc_b": r.doc_b,
                "similarity": round(r.similarity, 4),  # 总重复率
                "effective_similarity": round(effective_similarity, 4),  # 有效重复率
                "type": r.type,
                "total_chars": r.total_chars,
                "effective_chars": effective_chars,  # 有效重复字符
                "template_chars": total_chars - effective_chars if total_chars > 0 else 0,  # 模板重复字符
                "duplicate_segments": self._format_segments(
                    effective_segments,  # 只包含有效片段
                    r.doc_a,
                    r.doc_b,
                    doc_texts,
                    filter_obj,
                ),
                "template_segments": self._format_segments(
                    template_segments,  # 模板片段
                    r.doc_a,
                    r.doc_b,
                    doc_texts,
                    filter_obj,
                ) if template_segments else [],
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
            score = self._lexical_ratio(seg.text, source_text)
            if score < self.MIN_LEXICAL_SIMILARITY:
                rejected.append(seg)
                continue
            kept.append(seg)
        return kept, rejected

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
            # 获取主文档位置信息
            primary_line, primary_text = self._get_line_info(
                doc_a, match.start_pos, match.end_pos, doc_texts
            )

            # 获取来源文档位置信息
            source_line, source_text = self._get_line_info(
                doc_b, match.source_start, match.source_end, doc_texts
            )

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

            formatted.append({
                "primary_line": primary_line,
                "primary_text": primary_text,
                "primary_section": primary_section,
                "sources": [{
                    "doc": doc_b,
                    "line": source_line,
                    "text": source_text,
                }],
                "char_count": len(match.text),
                "ngram_count": match.ngram_count,
                "similarity_score": round(match.similarity_score, 4) if match.similarity_score else 0,
                "is_template": template_reason is not None,
                "template_reason": template_reason,
            })

        return formatted

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
            pair_effective_segments = []
            pair_template_segments = []
            pair_effective_chars = 0
            pair_template_chars = 0

            pair_filter_reason = None
            for match in r.duplicate_segments[:50]:
                # 获取位置信息
                primary_line, primary_text_seg = self._get_line_info(
                    primary_doc_id, match.start_pos, match.end_pos, doc_texts
                )

                source_line, source_text = self._get_line_info(
                    match.source_doc, match.source_start, match.source_end, doc_texts
                )

                # 检测是否是模板
                is_template = False
                template_reason = None
                if template_filter:
                    template_reason = template_filter.get_template_reason(match.text)
                    is_template = template_reason is not None

                seg_info = {
                    "primary_line": primary_line,
                    "primary_text": primary_text_seg,
                    "sources": [{
                        "doc": match.source_doc,
                        "line": source_line,
                        "text": source_text,
                    }],
                    "similarity_pair": f"{r.doc_a} vs {r.doc_b}",
                    "char_count": len(match.text),
                    "ngram_count": match.ngram_count,
                    "similarity_score": round(match.similarity_score, 4) if match.similarity_score else 0,
                    "is_template": is_template,
                    "template_reason": template_reason,
                }

                if is_template:
                    template_segments.append(seg_info)
                    pair_template_segments.append(match)
                    pair_template_chars += len(match.text)
                else:
                    source_text_raw = (match.source_text or "").strip()
                    lexical_score = self._lexical_ratio(match.text, source_text_raw)
                    if source_text_raw and lexical_score >= self.MIN_LEXICAL_SIMILARITY:
                        effective_segments.append(seg_info)
                        pair_effective_segments.append(match)
                        pair_effective_chars += len(match.text)
                    else:
                        seg_info["is_template"] = True
                        seg_info["template_reason"] = "lexical_mismatch"
                        template_segments.append(seg_info)
                        pair_template_segments.append(match)
                        pair_template_chars += len(match.text)

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

        output["duplicate_segments"] = effective_segments
        output["template_segments"] = template_segments
        output["filtered_pairs"] = filtered_pairs
        output["summary"] = {
            "total_effective_segments": len(effective_segments),
            "total_template_segments": len(template_segments),
            "total_effective_chars": total_effective_chars,
            "total_template_chars": total_template_chars,
            "total_filtered_pairs": len(filtered_pairs),
        }

        return output
