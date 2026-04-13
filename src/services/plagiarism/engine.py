"""比对引擎 - Winnowing 算法实现

基于 N-gram 指纹索引的查重比对引擎。
采用 Winnowing 算法确保检测到连续的重复内容。
"""
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from src.services.plagiarism.ngram import NGram, NGramSplitter
from src.services.plagiarism.tokenizer import Sentence


@dataclass
class ExcludedRange:
    """被排除的位置区间"""
    start: int  # 起始位置（包含）
    end: int  # 结束位置（不包含）
    reason: str  # 排除原因


@dataclass
class Match:
    """匹配片段"""
    text: str  # 匹配的文本
    start_pos: int  # 在文档A中的起始位置
    end_pos: int  # 在文档A中的结束位置
    ngram_count: int  # 包含的 N-gram 数量
    source_doc: str  # 来源文档
    source_start: int  # 在来源文档中的起始位置
    source_end: int  # 在来源文档中的结束位置
    source_text: str = ""  # 来源文档的匹配文本
    similarity_score: float = 0.0  # 片段相似度分数（0-1）
    match_type: str = "exact"  # exact / paraphrase
    confidence: float = 1.0
    parent_match_id: Optional[str] = None


@dataclass
class ContinuousMatch:
    """连续匹配区间（Winnowing 算法用）"""
    start_a: int  # 文档A起始位置
    end_a: int  # 文档A结束位置
    start_b: int  # 文档B起始位置
    end_b: int  # 文档B结束位置
    match_count: int  # 连续匹配的N-gram数量


@dataclass
class DocumentSimilarity:
    """文档相似度"""
    doc_a: str
    doc_b: str
    similarity: float
    type: str  # "high", "medium", "low"
    total_chars: int
    duplicate_chars: int
    duplicate_segments: List[Match] = field(default_factory=list)


class ComparisonEngine:
    """查重比对引擎 - Winnowing + 连续区间合并"""

    def __init__(
        self,
        min_continuous_match: int = 5,
        ngram_size: int = 8,
        winnowing_window: int = 8,
        min_match_length: int = 30,
        max_fingerprint_frequency: int = 200,
    ):
        """
        初始化比对引擎
        
        Args:
            min_continuous_match: 连续匹配阈值（连续 ≥ N 个相同指纹才算匹配）
            ngram_size: N-gram 大小
            winnowing_window: Winnowing 窗口大小
            min_match_length: 最小匹配长度（字符数），小于此长度的匹配会被过滤
            max_fingerprint_frequency: 单文档内同一指纹最大保留次数（抑制高频噪声）
        """
        self.min_continuous_match = min_continuous_match
        self.ngram_size = ngram_size
        self.winnowing_window = winnowing_window
        self.min_match_length = min_match_length
        self.max_fingerprint_frequency = max_fingerprint_frequency
        self.sentence_expand_window = 6
        self.sentence_similarity_threshold = 0.40
        self.gap_block_min_length = 50
        self._hard_boundary_pattern = re.compile(
            r"\[表格行\d+\]\s*(项目简介|项目立项背景及意义|第一部分|第二部分|第三部分|一、|二、|三、)[^\n]*\n?"
            r"|(?:^|\n)\s*(项目简介|项目立项背景及意义|第一部分|第二部分|第三部分|一、|二、|三、)[^\n]*\n?",
            re.MULTILINE,
        )

    def compare(
        self,
        docs: Dict[str, List[Sentence]],
        excluded_ranges: Optional[Dict[str, List[ExcludedRange]]] = None,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        raw_texts: Optional[Dict[str, str]] = None,
    ) -> List[DocumentSimilarity]:
        """
        执行文档间比对 - Winnowing 算法
        
        步骤:
        1. 切分 N-gram
        2. 构建指纹倒排索引
        3. Winnowing 窗口检测连续匹配
        4. 合并相邻匹配区间
        5. 计算相似度分数
        
        Args:
            docs: {doc_id: 句子列表}
            excluded_ranges: {doc_id: 排除区间列表}，前置过滤排除的位置
            threshold_high: 高相似度阈值
            threshold_medium: 中相似度阈值
            
        Returns:
            文档相似度列表
        """
        # 预处理：建立位置到区间的映射
        excluded_ranges = excluded_ranges or {}
        
        # Step 1: 切分 N-gram
        splitter = NGramSplitter(n=self.ngram_size)
        doc_ngrams = {}
        doc_texts = {}  # 保存原文用于计算
        
        for doc_id, sentences in docs.items():
            doc_ngrams[doc_id] = splitter.split(sentences)
            if raw_texts and isinstance(raw_texts.get(doc_id), str):
                doc_texts[doc_id] = raw_texts[doc_id]
            else:
                doc_texts[doc_id] = '\n'.join(s.text for s in sentences)
        
        # Step 2: 构建指纹倒排索引
        fingerprint_index = self._build_fingerprint_index(doc_ngrams)
        
        # Step 3: 查找连续匹配
        results = []
        doc_ids = list(docs.keys())
        
        for i, doc_a in enumerate(doc_ids):
            for doc_b in doc_ids[i + 1:]:
                # 查找连续匹配区间
                continuous_ranges = self._find_continuous_ranges(
                    doc_a,
                    doc_b,
                    doc_ngrams,
                    fingerprint_index,
                    excluded_ranges.get(doc_a, []),
                    excluded_ranges.get(doc_b, []),
                )

                text_a = doc_texts.get(doc_a, "")
                text_b = doc_texts.get(doc_b, "")
                
                # 合并相邻/重叠的区间
                merged_ranges = self._merge_continuous_ranges(continuous_ranges, text_a, text_b)

                merged_ranges = [
                    self._expand_continuous_range(r, text_a, text_b)
                    for r in merged_ranges
                ]
                merged_ranges = [
                    r for r in merged_ranges
                    if (r.end_a - r.start_a) >= self.min_match_length
                    and (r.end_b - r.start_b) >= self.min_match_length
                ]
                
                # 转换为 Match 对象
                matches = self._ranges_to_matches(
                    merged_ranges,
                    doc_a,
                    doc_b,
                    doc_texts,
                )
                matches = self._expand_matches_by_sentence_similarity(
                    matches,
                    docs.get(doc_a, []),
                    docs.get(doc_b, []),
                    text_a,
                    text_b,
                )
                matches = self._realign_matches_by_source_continuity(
                    matches,
                    text_a,
                    text_b,
                )
                matches.extend(
                    self._rescue_unmatched_primary_gaps(
                        matches,
                        text_a,
                        text_b,
                        doc_b,
                    )
                )
                matches = self._dedupe_and_filter_matches(matches)
                
                # 计算相似度
                total_chars = len(doc_texts[doc_a])
                duplicate_chars = sum(len(m.text) for m in matches)
                similarity = duplicate_chars / total_chars if total_chars > 0 else 0
                
                results.append(DocumentSimilarity(
                    doc_a=doc_a,
                    doc_b=doc_b,
                    similarity=similarity,
                    type=self._classify(similarity, threshold_high, threshold_medium),
                    total_chars=total_chars,
                    duplicate_chars=duplicate_chars,
                    duplicate_segments=matches,
                ))
        
        return results

    def _build_fingerprint_index(
        self,
        doc_ngrams: Dict[str, List[NGram]],
    ) -> Dict[int, Dict[str, List[int]]]:
        """
        构建指纹倒排索引

        Args:
            doc_ngrams: {doc_id: N-gram列表}

        Returns:
            {fingerprint: {doc_id: [positions]}}
        """
        index = defaultdict(lambda: defaultdict(list))

        for doc_id, ngrams in doc_ngrams.items():
            for ng in ngrams:
                fingerprint = self._generate_fingerprint(ng.text)
                index[fingerprint][doc_id].append(ng.position)

        return index

    def _find_continuous_ranges(
        self,
        doc_a: str,
        doc_b: str,
        doc_ngrams: Dict[str, List[NGram]],
        fingerprint_index: Dict,
        excluded_a: List[ExcludedRange],
        excluded_b: List[ExcludedRange],
    ) -> List[ContinuousMatch]:
        """
        查找两个文档间的连续匹配区间 - Winnowing 算法
        
        核心思想：
        1. 如果两个文档有 t 个连续位置都匹配了相同的指纹，
           则这些位置应该被合并为一个连续匹配区间
        2. 使用滑动窗口确保检测到连续的匹配
        
        Args:
            doc_a: 文档A ID
            doc_b: 文档B ID
            doc_ngrams: N-gram 索引
            fingerprint_index: 指纹倒排索引
            excluded_a: 文档A的排除区间
            excluded_b: 文档B的排除区间
            
        Returns:
            连续匹配区间列表
        """
        ngrams_a = doc_ngrams[doc_a]
        ngrams_b = doc_ngrams[doc_b]

        # 构建 doc_b 的指纹到 N-gram 下标映射
        fp_to_indices_b: Dict[int, List[int]] = defaultdict(list)
        for idx_b, ng in enumerate(ngrams_b):
            fp = self._generate_fingerprint(ng.text)
            fp_to_indices_b[fp].append(idx_b)

        # 生成候选匹配对：
        # 1) 不再用“单一路径贪心”选 idx_b，避免漏检
        # 2) 对高频指纹限流，抑制模板噪声导致的误连
        matched_positions: List[Tuple[int, int]] = []
        for idx_a, ng_a in enumerate(ngrams_a):
            if self._is_position_excluded(ng_a.position, excluded_a):
                continue

            fp = self._generate_fingerprint(ng_a.text)
            if doc_b not in fingerprint_index.get(fp, {}):
                continue

            idx_candidates = fp_to_indices_b.get(fp, [])
            if not idx_candidates:
                continue

            if len(idx_candidates) > self.max_fingerprint_frequency:
                continue

            for idx_b in idx_candidates:
                pos_b = ngrams_b[idx_b].position
                if self._is_position_excluded(pos_b, excluded_b):
                    continue
                matched_positions.append((idx_a, idx_b))

        if not matched_positions:
            return []

        # 先按“对角线偏移”分桶，再做窗口连续性检测。
        # 这样能显著减少跨段错连，并提升插入/删除场景的召回。
        bucket_size = max(1, self.winnowing_window)
        diagonal_buckets: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for idx_a, idx_b in matched_positions:
            delta = idx_a - idx_b
            bucket = delta // bucket_size
            diagonal_buckets[bucket].append((idx_a, idx_b))

        continuous_ranges: List[ContinuousMatch] = []
        for pairs in diagonal_buckets.values():
            ranges = self._winnowing_window(
                pairs,
                ngrams_a,
                ngrams_b,
                self.min_continuous_match,
            )
            continuous_ranges.extend(ranges)

        if not continuous_ranges:
            return []

        continuous_ranges.sort(key=lambda r: (r.start_a, r.start_b, -r.match_count))
        return self._dedupe_ranges(continuous_ranges)

    def _dedupe_ranges(
        self,
        ranges: List[ContinuousMatch],
    ) -> List[ContinuousMatch]:
        """去除高度重叠的重复区间，保留更长、更稳定的匹配。"""
        deduped: List[ContinuousMatch] = []
        for current in ranges:
            replaced = False
            for i, kept in enumerate(deduped):
                overlap_a = min(current.end_a, kept.end_a) - max(current.start_a, kept.start_a)
                overlap_b = min(current.end_b, kept.end_b) - max(current.start_b, kept.start_b)
                if overlap_a <= 0 or overlap_b <= 0:
                    continue

                len_cur = max(current.end_a - current.start_a, 1)
                len_kept = max(kept.end_a - kept.start_a, 1)
                overlap_ratio = overlap_a / min(len_cur, len_kept)
                if overlap_ratio < 0.8:
                    continue

                if len_cur > len_kept or (
                    len_cur == len_kept and current.match_count > kept.match_count
                ):
                    deduped[i] = current
                replaced = True
                break

            if not replaced:
                deduped.append(current)
        return deduped
    
    def _winnowing_window(
        self,
        matched_positions: List[Tuple[int, int]],
        ngrams_a: List[NGram],
        ngrams_b: List[NGram],
        min_continuous: int,
    ) -> List[ContinuousMatch]:
        """
        Winnowing 滑动窗口检测连续匹配
        
        核心算法：
        1. 按 doc_a 的位置排序匹配对
        2. 使用滑动窗口检测连续的匹配
        3. 如果窗口内有 min_continuous 个连续位置，则报告一个匹配
        
        Args:
            matched_positions: [(pos_a, pos_b), ...] 匹配位置对
            ngrams_a: 文档A的N-gram列表
            min_continuous: 最小连续匹配数
            
        Returns:
            连续匹配区间列表
        """
        if not matched_positions:
            return []
        
        # 按 pos_a 排序
        sorted_matches = sorted(matched_positions, key=lambda x: x[0])
        
        ranges = []
        window_size = self.winnowing_window
        
        i = 0
        while i < len(sorted_matches):
            run = [sorted_matches[i]]
            j = i + 1

            while j < len(sorted_matches):
                prev_a, prev_b = run[-1]
                curr_a, curr_b = sorted_matches[j]

                gap_a = curr_a - prev_a
                gap_b = curr_b - prev_b

                if gap_a <= window_size and gap_b <= window_size:
                    run.append(sorted_matches[j])
                    j += 1
                    continue
                break

            if len(run) >= min_continuous:
                pos_a_list = [m[0] for m in run]
                pos_b_list = [m[1] for m in run]
                start_a = ngrams_a[pos_a_list[0]].position
                end_a = ngrams_a[pos_a_list[-1]].position + self.ngram_size
                start_b = ngrams_b[pos_b_list[0]].position
                end_b = ngrams_b[pos_b_list[-1]].position + self.ngram_size

                ranges.append(ContinuousMatch(
                    start_a=start_a,
                    end_a=end_a,
                    start_b=start_b,
                    end_b=end_b,
                    match_count=len(run),
                ))

            i = j if len(run) > 1 else i + 1
        
        return ranges

    def _expand_continuous_range(
        self,
        match_range: ContinuousMatch,
        text_a: str,
        text_b: str,
    ) -> ContinuousMatch:
        """把锚点片段向两侧扩展到更自然的边界。"""
        start_a, end_a = self._expand_to_sentence_boundary(text_a, match_range.start_a, match_range.end_a)
        start_b, end_b = self._expand_to_sentence_boundary(text_b, match_range.start_b, match_range.end_b)
        start_a = self._clip_start_after_hard_boundary(text_a, start_a, end_a)
        start_b = self._clip_start_after_hard_boundary(text_b, start_b, end_b)
        # 注意：不要在这里裁掉“双边共同前后缀”。
        # 之前的 _trim_to_shared_core 会把开头/结尾相同句子去掉，导致
        # “明明整段相同却只命中中间短句”的问题（用户反馈的 m001 场景）。
        # 这里保留完整扩展边界，后续由句级扩展与聚合阶段再做稳健收敛。

        return ContinuousMatch(
            start_a=start_a,
            end_a=end_a,
            start_b=start_b,
            end_b=end_b,
            match_count=match_range.match_count,
        )

    def _expand_to_sentence_boundary(
        self,
        text: str,
        start: int,
        end: int,
        max_expand: int = 60,
    ) -> Tuple[int, int]:
        """向两侧扩展到更自然的句子/段落边界。"""
        if not text:
            return start, end

        boundary_chars = '。！？；;：:\n\r'
        start = max(0, min(start, len(text)))
        end = max(start, min(end, len(text)))

        left_bound = start
        left_limit = max(0, start - max_expand)
        for idx in range(start - 1, left_limit - 1, -1):
            if text[idx] in boundary_chars:
                left_bound = idx + 1
                break
        else:
            left_bound = left_limit

        right_bound = end
        right_limit = min(len(text), end + max_expand)
        for idx in range(end, right_limit):
            if text[idx] in boundary_chars:
                right_bound = idx + 1
                break
        else:
            right_bound = right_limit

        while left_bound < right_bound and text[left_bound] in '、，,：:；; ':
            left_bound += 1

        return left_bound, right_bound

    def _trim_to_shared_core(
        self,
        text_a: str,
        start_a: int,
        end_a: int,
        text_b: str,
        start_b: int,
        end_b: int,
    ) -> Tuple[int, int, int, int]:
        """按双边共有的前后缀收紧边界，避免一边扩得过长。"""
        segment_a = text_a[start_a:end_a]
        segment_b = text_b[start_b:end_b]

        norm_a = self._normalize_for_alignment(segment_a)
        norm_b = self._normalize_for_alignment(segment_b)
        if not norm_a or not norm_b:
            return start_a, end_a, start_b, end_b

        prefix_len = self._common_prefix_length(norm_a, norm_b)
        suffix_len = self._common_suffix_length(norm_a[prefix_len:], norm_b[prefix_len:])

        min_anchor = max(self.ngram_size * 2, 12)
        shared_core = len(norm_a) - prefix_len - suffix_len
        if prefix_len < min_anchor and suffix_len < min_anchor and shared_core < min_anchor:
            return start_a, end_a, start_b, end_b

        trim_left_a = self._map_normalized_offset_to_original(segment_a, prefix_len)
        trim_left_b = self._map_normalized_offset_to_original(segment_b, prefix_len)

        keep_end_a = self._map_normalized_suffix_to_original_end(segment_a, suffix_len)
        keep_end_b = self._map_normalized_suffix_to_original_end(segment_b, suffix_len)

        new_start_a = start_a + trim_left_a
        new_start_b = start_b + trim_left_b
        new_end_a = start_a + keep_end_a
        new_end_b = start_b + keep_end_b

        if new_end_a - new_start_a < self.min_match_length or new_end_b - new_start_b < self.min_match_length:
            return start_a, end_a, start_b, end_b

        return new_start_a, new_end_a, new_start_b, new_end_b

    def _normalize_for_alignment(self, text: str) -> str:
        """归一化文本，用于比较共同前后缀。"""
        return re.sub(r'\s+', '', text)

    def _common_prefix_length(self, a: str, b: str) -> int:
        limit = min(len(a), len(b))
        i = 0
        while i < limit and a[i] == b[i]:
            i += 1
        return i

    def _common_suffix_length(self, a: str, b: str) -> int:
        limit = min(len(a), len(b))
        i = 0
        while i < limit and a[-(i + 1)] == b[-(i + 1)]:
            i += 1
        return i

    def _map_normalized_offset_to_original(self, text: str, normalized_offset: int) -> int:
        if normalized_offset <= 0:
            return 0

        count = 0
        for idx, char in enumerate(text):
            if char.isspace():
                continue
            count += 1
            if count >= normalized_offset:
                return idx + 1
        return len(text)

    def _map_normalized_suffix_to_original_end(self, text: str, normalized_suffix_len: int) -> int:
        if normalized_suffix_len <= 0:
            return len(text)

        count = 0
        for idx in range(len(text) - 1, -1, -1):
            if text[idx].isspace():
                continue
            count += 1
            if count >= normalized_suffix_len:
                return idx
        return 0
    
    def _is_position_excluded(
        self,
        pos: int,
        excluded_ranges: List[ExcludedRange],
    ) -> bool:
        """检查位置是否被排除"""
        for r in excluded_ranges:
            if r.start <= pos < r.end:
                return True
        return False

    def _merge_continuous_ranges(
        self,
        ranges: List[ContinuousMatch],
        text_a: str,
        text_b: str,
        max_gap: int = 20,
    ) -> List[ContinuousMatch]:
        """
        合并相邻/重叠的连续匹配区间
        
        合并条件：
        1. 两个区间在 doc_a 中相邻（间隔 <= max_gap）
        2. 两个区间在 doc_b 中也相邻（间隔 <= max_gap）
        
        Args:
            ranges: 连续匹配区间列表
            max_gap: 最大允许间隔
            
        Returns:
            合并后的区间列表
        """
        if not ranges:
            return []
        
        # 按 start_a 排序
        sorted_ranges = sorted(ranges, key=lambda x: x.start_a)
        merged = [sorted_ranges[0]]
        
        for current in sorted_ranges[1:]:
            last = merged[-1]
            
            # 检查是否可以合并
            gap_a = current.start_a - last.end_a
            gap_b = current.start_b - last.end_b

            crosses_boundary = (
                self._has_hard_boundary_between(text_a, last.end_a, current.start_a)
                or self._has_hard_boundary_between(text_b, last.end_b, current.start_b)
            )

            if gap_a <= max_gap and gap_b <= max_gap and not crosses_boundary:
                # 合并：扩展区间
                merged[-1] = ContinuousMatch(
                    start_a=last.start_a,
                    end_a=current.end_a,
                    start_b=last.start_b,
                    end_b=max(last.end_b, current.end_b),
                    match_count=last.match_count + current.match_count,
                )
            else:
                merged.append(current)
        
        # 过滤长度不足的
        return [
            r for r in merged 
            if r.end_b >= r.start_b
            if r.end_a - r.start_a >= self.min_match_length
        ]

    def _has_hard_boundary_between(self, text: str, left: int, right: int) -> bool:
        if not text:
            return False
        left = max(0, min(left, len(text)))
        right = max(0, min(right, len(text)))
        if right <= left:
            return False

        for m in self._hard_boundary_pattern.finditer(text):
            if left < m.start() < right:
                return True
        return False

    def _clip_start_after_hard_boundary(self, text: str, start: int, end: int) -> int:
        """如果片段跨越章节/标题硬边界，则把起点收敛到边界之后。"""
        if not text or end <= start:
            return start
        start = max(0, min(start, len(text)))
        end = max(0, min(end, len(text)))

        clipped = start
        for m in self._hard_boundary_pattern.finditer(text):
            if start <= m.start() < end:
                clipped = max(clipped, m.end())
        return min(clipped, end)
    
    def _ranges_to_matches(
        self,
        ranges: List[ContinuousMatch],
        doc_a: str,
        doc_b: str,
        doc_texts: Dict[str, str],
    ) -> List[Match]:
        """
        将连续匹配区间转换为 Match 对象
        
        Args:
            ranges: 连续匹配区间列表
            doc_a: 文档A ID
            doc_b: 文档B ID
            doc_texts: 文档原文
            
        Returns:
            Match 列表
        """
        matches = []
        
        text_a = doc_texts.get(doc_a, "")
        text_b = doc_texts.get(doc_b, "")
        
        for r in ranges:
            # 提取 doc_a 的文本
            if r.start_a < len(text_a) and r.end_a <= len(text_a):
                text = text_a[r.start_a:r.end_a].replace('\n', ' ').strip()
            else:
                text = ""
            
            # 计算相似度分数
            score = r.match_count * self.ngram_size / (r.end_a - r.start_a) if r.end_a > r.start_a else 0
            
            # 获取 doc_b 的对应文本（扩展到句子边界）
            source_text = self._extract_source_text(text_b, r.start_b, r.end_b)
            
            matches.append(Match(
                text=text,
                start_pos=r.start_a,
                end_pos=r.end_a,
                ngram_count=r.match_count,
                source_doc=doc_b,
                source_start=r.start_b,
                source_end=r.end_b,
                source_text=source_text,
                similarity_score=min(score, 1.0),
            ))
        
        return matches

    def _extract_source_text(
        self,
        text_b: str,
        start_b: int,
        end_b: int,
    ) -> str:
        """
        提取来源文档文本，扩展到完整句子边界
        
        Args:
            text_b: 来源文档全文
            start_b: 起始位置
            end_b: 结束位置
            
        Returns:
            扩展到完整句子的文本
        """
        if start_b >= len(text_b):
            return ""

        start, end = self._expand_to_sentence_boundary(text_b, start_b, end_b)
        if end > start:
            return text_b[start:end].replace('\n', ' ').strip()
        return ""

    def _expand_matches_by_sentence_similarity(
        self,
        matches: List[Match],
        sentences_a: List[Sentence],
        sentences_b: List[Sentence],
        text_a: str,
        text_b: str,
    ) -> List[Match]:
        """在已有 exact 命中邻域做句级补全，改善改写场景边界。"""
        if not matches or not sentences_a or not sentences_b:
            return matches

        expanded: List[Match] = []
        for match in matches:
            expanded.append(
                self._expand_single_match_by_sentences(
                    match,
                    sentences_a,
                    sentences_b,
                    text_a,
                    text_b,
                )
            )
        return expanded

    def _dedupe_and_filter_matches(self, matches: List[Match]) -> List[Match]:
        """去重并过滤过短片段，减少重复高亮与噪声片段。"""
        if not matches:
            return []

        deduped: List[Match] = []
        for m in sorted(
            matches,
            key=lambda x: (
                x.start_pos,
                -(x.end_pos - x.start_pos),
                x.source_start,
                -(x.source_end - x.source_start),
            ),
        ):
            if (m.end_pos - m.start_pos) < self.min_match_length:
                continue
            if self._is_heading_only_segment(m.text) and self._is_heading_only_segment(m.source_text):
                continue
            replaced = False
            for i, kept in enumerate(deduped):
                if kept.source_doc != m.source_doc:
                    continue
                overlap_a = min(m.end_pos, kept.end_pos) - max(m.start_pos, kept.start_pos)
                overlap_b = min(m.source_end, kept.source_end) - max(m.source_start, kept.source_start)
                if overlap_a <= 0 or overlap_b <= 0:
                    continue
                ratio_a = overlap_a / max(min(m.end_pos - m.start_pos, kept.end_pos - kept.start_pos), 1)
                ratio_b = overlap_b / max(min(m.source_end - m.source_start, kept.source_end - kept.source_start), 1)
                if ratio_a < 0.85 or ratio_b < 0.70:
                    continue
                score_new = self._match_quality_score(m)
                score_old = self._match_quality_score(kept)
                if score_new > score_old:
                    deduped[i] = m
                replaced = True
                break
            if replaced:
                continue
            deduped.append(m)
        return deduped

    def _match_quality_score(self, match: Match) -> float:
        primary_len = max(match.end_pos - match.start_pos, 1)
        source_len = max(match.source_end - match.source_start, 1)
        lexical = self._segment_similarity(match.text or "", match.source_text or "")
        return lexical + min(primary_len, source_len) / 1000.0

    def _realign_matches_by_source_continuity(
        self,
        matches: List[Match],
        text_a: str,
        text_b: str,
    ) -> List[Match]:
        """当 primary 相邻而 source 跳段时，优先回贴到 source 邻近连续区。"""
        if len(matches) < 2 or not text_a or not text_b:
            return matches

        ordered = sorted(matches, key=lambda m: (m.start_pos, m.end_pos))
        realigned: List[Match] = [ordered[0]]

        for current in ordered[1:]:
            previous = realigned[-1]
            primary_gap = current.start_pos - previous.end_pos
            source_gap = current.source_start - previous.source_end
            if (
                current.source_doc != previous.source_doc
                or primary_gap < 0
                or primary_gap > 220
                or source_gap <= 260
            ):
                realigned.append(current)
                continue

            primary_text = (text_a[current.start_pos:current.end_pos] or "").strip()
            if len(primary_text) < 40:
                realigned.append(current)
                continue

            current_source_text = (text_b[current.source_start:current.source_end] or "").strip()
            current_score = self._segment_similarity(primary_text, current_source_text)

            best = self._find_best_local_source_window(
                primary_text=primary_text,
                source_text=text_b,
                near_pos=previous.source_end,
                search_back=40,
                search_forward=900,
                step=3,
            )
            if not best:
                realigned.append(current)
                continue

            best_start, best_end, best_score = best
            # 仅在明显更优时重锚，避免抖动
            if best_score < 0.62 or best_score < current_score + 0.12:
                realigned.append(current)
                continue

            new_source = text_b[best_start:best_end].replace("\n", " ").strip()
            realigned.append(Match(
                text=current.text,
                start_pos=current.start_pos,
                end_pos=current.end_pos,
                ngram_count=current.ngram_count,
                source_doc=current.source_doc,
                source_start=best_start,
                source_end=best_end,
                source_text=new_source,
                similarity_score=max(current.similarity_score, best_score),
                match_type=current.match_type,
                confidence=max(current.confidence, best_score),
                parent_match_id=current.parent_match_id,
            ))

        return realigned

    def _rescue_unmatched_primary_gaps(
        self,
        matches: List[Match],
        text_a: str,
        text_b: str,
        source_doc: str,
    ) -> List[Match]:
        """对已有命中之间的大段空白做定向补召回。"""
        if not text_a or not text_b:
            return []

        ordered = sorted(matches, key=lambda m: (m.start_pos, m.end_pos))
        gaps: List[Tuple[int, int, Optional[Match], Optional[Match]]] = []
        cursor = 0

        for idx, match in enumerate(ordered):
            if match.start_pos - cursor >= self.gap_block_min_length:
                prev_match = ordered[idx - 1] if idx > 0 else None
                gaps.append((cursor, match.start_pos, prev_match, match))
            cursor = max(cursor, match.end_pos)

        if len(text_a) - cursor >= self.gap_block_min_length:
            prev_match = ordered[-1] if ordered else None
            gaps.append((cursor, len(text_a), prev_match, None))

        rescued: List[Match] = []
        for gap_start, gap_end, prev_match, next_match in gaps:
            if gap_end - gap_start < self.gap_block_min_length:
                continue
            for block_start, block_end in self._build_gap_blocks(text_a, gap_start, gap_end):
                block_text = text_a[block_start:block_end].strip()
                if not block_text:
                    continue
                search_start, search_end = self._source_search_window(
                    text_b,
                    prev_match,
                    next_match,
                )
                if search_end - search_start < 60:
                    continue
                best = self._find_best_source_window_for_block(
                    primary_text=block_text,
                    source_text=text_b,
                    search_start=search_start,
                    search_end=search_end,
                )
                if not best:
                    continue

                source_start, source_end, best_score = best
                source_segment = text_b[source_start:source_end].replace("\n", " ").strip()
                if not source_segment:
                    continue

                similarity = self._segment_similarity(block_text, source_segment)
                threshold = self._gap_rescue_threshold(block_text)
                if similarity < threshold:
                    continue

                rescued.append(Match(
                    text=block_text.replace("\n", " ").strip(),
                    start_pos=block_start,
                    end_pos=block_end,
                    ngram_count=max(len(block_text) // max(self.ngram_size, 1), 1),
                    source_doc=source_doc,
                    source_start=source_start,
                    source_end=source_end,
                    source_text=source_segment,
                    similarity_score=max(best_score, similarity),
                    match_type="paraphrase",
                    confidence=max(best_score, similarity),
                ))
        return rescued

    def _build_gap_blocks(
        self,
        text: str,
        gap_start: int,
        gap_end: int,
    ) -> List[Tuple[int, int]]:
        lines = list(self._iter_lines(text, gap_start, gap_end))
        blocks: List[Tuple[int, int]] = []
        pending_heading: Optional[Tuple[int, int]] = None
        i = 0

        while i < len(lines):
            line_start, line_end, line_text = lines[i]
            stripped = line_text.strip()
            if not stripped:
                pending_heading = None
                i += 1
                continue
            if self._is_structural_noise_line(stripped):
                pending_heading = None
                i += 1
                continue
            if self._looks_like_heading(stripped):
                pending_heading = (line_start, line_end)
                i += 1
                continue
            if not self._is_gap_block_candidate(stripped):
                pending_heading = None
                i += 1
                continue

            block_start = pending_heading[0] if pending_heading else line_start
            block_end = line_end
            j = i + 1
            while j < len(lines):
                next_start, next_end, next_text = lines[j]
                next_stripped = next_text.strip()
                if not next_stripped:
                    break
                if self._is_structural_noise_line(next_stripped) or self._looks_like_heading(next_stripped):
                    break
                if not self._is_gap_block_candidate(next_stripped):
                    break
                block_end = next_end
                j += 1

            block_text = text[block_start:block_end].strip()
            if len(self._normalize_sentence(block_text)) >= self.gap_block_min_length:
                blocks.append((block_start, block_end))
            pending_heading = None
            i = j

        return blocks

    def _iter_lines(
        self,
        text: str,
        start: int,
        end: int,
    ) -> Iterable[Tuple[int, int, str]]:
        cursor = start
        while cursor < end:
            next_break = text.find("\n", cursor, end)
            if next_break == -1:
                yield cursor, end, text[cursor:end]
                break
            line_end = next_break + 1
            yield cursor, line_end, text[cursor:line_end]
            cursor = line_end

    def _source_search_window(
        self,
        text_b: str,
        prev_match: Optional[Match],
        next_match: Optional[Match],
    ) -> Tuple[int, int]:
        if prev_match and next_match and prev_match.source_doc == next_match.source_doc:
            start = max(0, prev_match.source_end - 100)
            end = min(len(text_b), next_match.source_start + 100)
            if end - start >= 120:
                return start, end

        if prev_match:
            start = max(0, prev_match.source_end - 120)
            end = min(len(text_b), prev_match.source_end + 2400)
            return start, end

        if next_match:
            start = max(0, next_match.source_start - 2400)
            end = min(len(text_b), next_match.source_start + 120)
            return start, end

        return 0, len(text_b)

    def _find_best_source_window_for_block(
        self,
        primary_text: str,
        source_text: str,
        search_start: int,
        search_end: int,
    ) -> Optional[Tuple[int, int, float]]:
        primary_norm = self._normalize_sentence(primary_text)
        if len(primary_norm) < self.gap_block_min_length:
            return None

        length = len(primary_text)
        candidate_lengths = []
        for factor in (0.70, 0.85, 1.0, 1.15, 1.30):
            cand_len = int(length * factor)
            if cand_len >= 40:
                candidate_lengths.append(cand_len)

        best: Optional[Tuple[int, int, float]] = None
        max_pos = max(search_start, search_end - 30)
        for pos in range(search_start, max_pos, 4):
            for cand_len in candidate_lengths:
                cand_end = min(search_end, pos + cand_len)
                if cand_end - pos < 40:
                    continue
                if self._has_hard_boundary_inside(source_text, pos, cand_end):
                    continue
                candidate = source_text[pos:cand_end]
                score = self._segment_similarity(primary_text, candidate)
                if best is None or score > best[2]:
                    best = (pos, cand_end, score)

        if best is None:
            return None

        start, end, score = best
        start, end = self._expand_source_window(source_text, start, end, search_start, search_end)
        final_text = source_text[start:end]
        final_score = self._segment_similarity(primary_text, final_text)
        return start, end, max(score, final_score)

    def _expand_source_window(
        self,
        text: str,
        start: int,
        end: int,
        lower_bound: int,
        upper_bound: int,
    ) -> Tuple[int, int]:
        start, end = self._expand_to_sentence_boundary(text, start, end, max_expand=80)
        start = max(lower_bound, self._clip_start_after_hard_boundary(text, start, end))
        end = min(upper_bound, self._clip_end_before_hard_boundary(text, start, end))
        if end <= start:
            return max(lower_bound, start), min(upper_bound, max(start, end))
        return start, end

    def _clip_end_before_hard_boundary(self, text: str, start: int, end: int) -> int:
        if not text or end <= start:
            return end
        clipped = end
        for m in self._hard_boundary_pattern.finditer(text):
            if start < m.start() < end:
                clipped = min(clipped, m.start())
                break
        return max(start, clipped)

    def _has_hard_boundary_inside(self, text: str, start: int, end: int) -> bool:
        if end - start <= 1:
            return False
        for m in self._hard_boundary_pattern.finditer(text):
            if start < m.start() < end:
                return True
        return False

    def _gap_rescue_threshold(self, text: str) -> float:
        norm_len = len(self._normalize_sentence(text))
        if norm_len >= 220:
            return 0.42
        if norm_len >= 120:
            return 0.46
        return 0.52

    def _looks_like_heading(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if not normalized:
            return False
        return bool(re.match(
            r"^(项目简介|项目立项背景及意义|第[一二三四五六七八九十百]+部分|第一部分|第二部分|第三部分|"
            r"[一二三四五六七八九十]+、|\d+[、\.．:：])",
            normalized,
        )) and len(normalized) <= 40

    def _is_heading_only_segment(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if not normalized:
            return True
        return self._looks_like_heading(normalized) and len(normalized) <= 45

    def _is_structural_noise_line(self, text: str) -> bool:
        if not text:
            return True
        if "[表格行" in text:
            return True
        if "|" in text:
            return True
        cleaned = re.sub(r"\s+", "", text)
        if len(cleaned) < 8:
            return True
        if len(re.findall(r"\d", cleaned)) > max(10, len(cleaned) // 3):
            return True
        return False

    def _is_gap_block_candidate(self, text: str) -> bool:
        cleaned = self._clean_sentence_for_semantic_match(text)
        cleaned = re.sub(r"\s+", "", cleaned)
        if len(cleaned) < self.gap_block_min_length:
            return False
        if self._looks_like_heading(cleaned):
            return False
        if len(re.findall(r"\d", cleaned)) > max(12, len(cleaned) // 3):
            return False
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
        if cjk_chars < max(18, int(len(cleaned) * 0.45)):
            return False
        return True

    def _expand_single_match_by_sentences(
        self,
        match: Match,
        sentences_a: List[Sentence],
        sentences_b: List[Sentence],
        text_a: str,
        text_b: str,
    ) -> Match:
        anchor_a = self._sentence_index_range(sentences_a, match.start_pos, match.end_pos)
        anchor_b = self._sentence_index_range(sentences_b, match.source_start, match.source_end)
        if anchor_a is None or anchor_b is None:
            return match

        a_start, a_end = anchor_a
        b_start, b_end = anchor_b
        anchor_text_a = " ".join(s.text for s in sentences_a[a_start:a_end + 1])
        anchor_text_b = " ".join(s.text for s in sentences_b[b_start:b_end + 1])
        if not self._is_narrative_sentence(anchor_text_a) or not self._is_narrative_sentence(anchor_text_b):
            return match

        new_a_start, new_a_end = a_start, a_end
        new_b_start, new_b_end = b_start, b_end
        anchor_delta = ((a_start + a_end) // 2) - ((b_start + b_end) // 2)
        step_scores: List[float] = []

        # 向左扩展：仅允许邻接句配对，避免跨段误连
        left_steps = 0
        while left_steps < self.sentence_expand_window:
            candidates: List[Tuple[int, int, float]] = []
            for cand_a, cand_b in (
                (new_a_start - 1, new_b_start - 1),
                (new_a_start - 1, new_b_start),
                (new_a_start, new_b_start - 1),
            ):
                if cand_a < 0 or cand_b < 0:
                    continue
                if abs((cand_a - cand_b) - anchor_delta) > 1:
                    continue
                if not self._is_narrative_sentence(sentences_a[cand_a].text):
                    continue
                if not self._is_narrative_sentence(sentences_b[cand_b].text):
                    continue
                score = self._sentence_similarity(sentences_a[cand_a].text, sentences_b[cand_b].text)
                candidates.append((cand_a, cand_b, score))
            if not candidates:
                break
            best_a, best_b, best_score = max(candidates, key=lambda x: x[2])
            if best_score < self.sentence_similarity_threshold:
                break
            new_a_start = min(new_a_start, best_a)
            new_b_start = min(new_b_start, best_b)
            step_scores.append(best_score)
            left_steps += 1

        # 向右扩展：同样保持局部连续
        right_steps = 0
        while right_steps < self.sentence_expand_window:
            candidates = []
            for cand_a, cand_b in (
                (new_a_end + 1, new_b_end + 1),
                (new_a_end + 1, new_b_end),
                (new_a_end, new_b_end + 1),
            ):
                if cand_a >= len(sentences_a) or cand_b >= len(sentences_b):
                    continue
                if abs((cand_a - cand_b) - anchor_delta) > 1:
                    continue
                if not self._is_narrative_sentence(sentences_a[cand_a].text):
                    continue
                if not self._is_narrative_sentence(sentences_b[cand_b].text):
                    continue
                score = self._sentence_similarity(sentences_a[cand_a].text, sentences_b[cand_b].text)
                candidates.append((cand_a, cand_b, score))
            if not candidates:
                break
            best_a, best_b, best_score = max(candidates, key=lambda x: x[2])
            if best_score < self.sentence_similarity_threshold:
                break
            new_a_end = max(new_a_end, best_a)
            new_b_end = max(new_b_end, best_b)
            step_scores.append(best_score)
            right_steps += 1

        new_start_a = sentences_a[new_a_start].start_pos
        new_end_a = sentences_a[new_a_end].end_pos
        new_start_b = sentences_b[new_b_start].start_pos
        new_end_b = sentences_b[new_b_end].end_pos

        # 限制单次扩展跨度，避免误扩到其他段落
        if (new_end_a - new_start_a) > 1200 or (new_end_b - new_start_b) > 1200:
            return match

        new_start_b = sentences_b[new_b_start].start_pos

        # 至少放大一侧且长度有效，避免误扩
        if (
            new_start_a >= match.start_pos
            and new_end_a <= match.end_pos
            and new_start_b >= match.source_start
            and new_end_b <= match.source_end
        ):
            return match

        if new_end_a - new_start_a < self.min_match_length or new_end_b - new_start_b < self.min_match_length:
            return match

        expanded_text = text_a[new_start_a:new_end_a].replace("\n", " ").strip()
        expanded_source = self._extract_source_text(text_b, new_start_b, new_end_b)
        if not self._is_narrative_sentence(expanded_text) or not self._is_narrative_sentence(expanded_source):
            return match
        if not step_scores:
            return match
        confidence = sum(step_scores) / max(len(step_scores), 1)

        return Match(
            text=expanded_text,
            start_pos=new_start_a,
            end_pos=new_end_a,
            ngram_count=match.ngram_count,
            source_doc=match.source_doc,
            source_start=new_start_b,
            source_end=new_end_b,
            source_text=expanded_source,
            similarity_score=max(match.similarity_score, min(confidence, 1.0)),
            match_type="paraphrase" if (new_end_a - new_start_a) > (match.end_pos - match.start_pos) + 40 else match.match_type,
            confidence=min(confidence, 1.0),
            parent_match_id=match.parent_match_id,
        )

    def _sentence_index_range(
        self,
        sentences: List[Sentence],
        start_pos: int,
        end_pos: int,
    ) -> Optional[Tuple[int, int]]:
        indexes = []
        for idx, sentence in enumerate(sentences):
            if sentence.end_pos <= start_pos:
                continue
            if sentence.start_pos >= end_pos:
                continue
            indexes.append(idx)

        if not indexes:
            return None
        return indexes[0], indexes[-1]

    def _sentence_similarity(self, text_a: str, text_b: str) -> float:
        norm_a = self._normalize_sentence(text_a)
        norm_b = self._normalize_sentence(text_b)
        if len(norm_a) < 8 or len(norm_b) < 8:
            return 0.0

        ratio = self._sequence_ratio(norm_a, norm_b)
        overlap = self._matched_char_ratio(norm_a, norm_b)
        return max(ratio, overlap)

    def _segment_similarity(self, text_a: str, text_b: str) -> float:
        norm_a = self._normalize_sentence(text_a)
        norm_b = self._normalize_sentence(text_b)
        if len(norm_a) < 8 or len(norm_b) < 8:
            return 0.0
        ratio = self._sequence_ratio(norm_a, norm_b)
        overlap = self._matched_char_ratio(norm_a, norm_b)
        return max(ratio, overlap)

    def _find_best_local_source_window(
        self,
        primary_text: str,
        source_text: str,
        near_pos: int,
        search_back: int = 40,
        search_forward: int = 900,
        step: int = 3,
    ) -> Optional[Tuple[int, int, float]]:
        target_len = max(len(primary_text), 1)
        start = max(0, near_pos - search_back)
        end = min(len(source_text), near_pos + search_forward)
        if end - start < 20:
            return None

        best: Optional[Tuple[int, int, float]] = None
        probe_end = max(start, end - 20)
        for pos in range(start, probe_end, max(step, 1)):
            cand_end = min(len(source_text), pos + target_len)
            if cand_end - pos < max(20, target_len // 3):
                continue
            cand = source_text[pos:cand_end]
            score = self._segment_similarity(primary_text, cand)
            if best is None or score > best[2]:
                best = (pos, cand_end, score)
        return best

    def _normalize_sentence(self, text: str) -> str:
        cleaned = self._clean_sentence_for_semantic_match(text)
        cleaned = re.sub(r"\s+", "", cleaned)
        cleaned = re.sub(r"[，。；：、！？,.!?;:\"'“”‘’（）()\[\]【】<>《》]", "", cleaned)
        return cleaned.lower()

    def _sequence_ratio(self, a: str, b: str) -> float:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio()

    def _matched_char_ratio(self, a: str, b: str) -> float:
        from difflib import SequenceMatcher

        matcher = SequenceMatcher(None, a, b)
        matched = sum(block.size for block in matcher.get_matching_blocks())
        base = max(min(len(a), len(b)), 1)
        return matched / base

    def _is_narrative_sentence(self, text: str) -> bool:
        if not text:
            return False
        cleaned = self._clean_sentence_for_semantic_match(text)
        cleaned = re.sub(r"\s+", "", cleaned)
        if len(cleaned) < 24:
            return False

        if len(re.findall(r"\d", cleaned)) > max(8, len(cleaned) // 4):
            return False

        enum_markers = len(re.findall(r"\d+[）\)\.、]", cleaned))
        if enum_markers >= 3:
            return False

        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
        if cjk_chars < max(12, int(len(cleaned) * 0.4)):
            return False
        return True

    def _clean_sentence_for_semantic_match(self, text: str) -> str:
        """清洗句子中的结构噪声，仅用于语义判断/扩边，不影响坐标。"""
        if not text:
            return ""

        # 先按行切分，过滤表格行噪声
        lines = []
        for line in text.splitlines():
            line = re.sub(r"\[表格行\d+\]", "", line).strip()
            if not line:
                continue
            # 典型表格字段行，直接丢弃（避免和正文混在同一句）
            if "|" in line:
                continue
            lines.append(line)

        cleaned = " ".join(lines).strip()
        if not cleaned:
            cleaned = re.sub(r"\[表格行\d+\]", "", text)
            cleaned = cleaned.replace("|", " ")
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # 去掉常见标题前缀，保留正文句
        cleaned = re.sub(r"^(项目立项背景及意义|项目简介|第一部分|第二部分|第三部分)\s*", "", cleaned)
        return cleaned

    def _generate_fingerprint(self, text: str) -> int:
        """生成指纹"""
        return int(hashlib.md5(text.encode('utf-8')).hexdigest()[:8], 16)

    def _classify(
        self,
        similarity: float,
        threshold_high: float,
        threshold_medium: float,
    ) -> str:
        """根据相似度分类"""
        if similarity >= threshold_high:
            return "high"
        elif similarity >= threshold_medium:
            return "medium"
        return "low"
