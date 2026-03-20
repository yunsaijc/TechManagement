"""比对引擎 - Winnowing 算法实现

基于 N-gram 指纹索引的查重比对引擎。
采用 Winnowing 算法确保检测到连续的重复内容。
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
    ):
        """
        初始化比对引擎
        
        Args:
            min_continuous_match: 连续匹配阈值（连续 ≥ N 个相同指纹才算匹配）
            ngram_size: N-gram 大小
            winnowing_window: Winnowing 窗口大小
            min_match_length: 最小匹配长度（字符数），小于此长度的匹配会被过滤
        """
        self.min_continuous_match = min_continuous_match
        self.ngram_size = ngram_size
        self.winnowing_window = winnowing_window
        self.min_match_length = min_match_length

    def compare(
        self,
        docs: Dict[str, List[Sentence]],
        excluded_ranges: Optional[Dict[str, List[ExcludedRange]]] = None,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
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
                merged_ranges = self._merge_continuous_ranges(continuous_ranges)

                merged_ranges = [
                    self._expand_continuous_range(r, text_a, text_b)
                    for r in merged_ranges
                ]
                
                # 转换为 Match 对象
                matches = self._ranges_to_matches(
                    merged_ranges,
                    doc_a,
                    doc_b,
                    doc_texts,
                )
                
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
        
        # 查找所有匹配的指纹位置对
        matched_positions: List[Tuple[int, int]] = []  # [(idx_a, idx_b), ...]
        
        for i, ng in enumerate(ngrams_a):
            fp = self._generate_fingerprint(ng.text)
            
            # 检查位置是否在排除区间内
            if self._is_position_excluded(ng.position, excluded_a):
                continue
            
            if fp in fp_to_indices_b and doc_b in fingerprint_index.get(fp, {}):
                for idx_b in fp_to_indices_b[fp]:
                    # 检查 doc_b 的字符位置是否在排除区间内
                    pos_b = ngrams_b[idx_b].position
                    if not self._is_position_excluded(pos_b, excluded_b):
                        matched_positions.append((i, idx_b))
                        break  # 只取第一个匹配位置
        
        # 使用滑动窗口检测连续匹配
        continuous_ranges = self._winnowing_window(
            matched_positions,
            ngrams_a,
            ngrams_b,
            self.min_continuous_match,
        )

        continuous_ranges = [
            r
            for r in continuous_ranges
        ]
        
        return continuous_ranges
    
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
        boundary_chars = '。！？；;\n\r'

        def expand(text: str, start: int, end: int) -> Tuple[int, int]:
            if not text:
                return start, end

            start = max(0, min(start, len(text)))
            end = max(start, min(end, len(text)))

            left_steps = 0
            while start > 0 and left_steps < max_expand:
                if text[start - 1] in boundary_chars:
                    break
                start -= 1
                left_steps += 1

            right_steps = 0
            while end < len(text) and right_steps < max_expand:
                current = text[end]
                end += 1
                right_steps += 1
                if current in boundary_chars:
                    break

            return start, end

        start_a, end_a = expand(text_a, match_range.start_a, match_range.end_a)
        start_b, end_b = expand(text_b, match_range.start_b, match_range.end_b)

        return ContinuousMatch(
            start_a=start_a,
            end_a=end_a,
            start_b=start_b,
            end_b=end_b,
            match_count=match_range.match_count,
        )
    
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
            
            if gap_a <= max_gap and gap_b <= max_gap:
                # 合并：扩展区间
                merged[-1] = ContinuousMatch(
                    start_a=last.start_a,
                    end_a=current.end_a,
                    start_b=last.start_b,
                    end_b=current.end_b,
                    match_count=last.match_count + current.match_count,
                )
            else:
                merged.append(current)
        
        # 过滤长度不足的
        return [
            r for r in merged 
            if r.end_a - r.start_a >= self.min_match_length
        ]
    
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
        
        # 确保不越界
        actual_end = min(end_b, len(text_b))

        # 向后扩展到句子边界（句号、换行等）
        while actual_end < len(text_b):
            c = text_b[actual_end]
            if c in '。！？；\n':
                actual_end += 1
                break
            actual_end += 1
        
        if actual_end > start_b:
            return text_b[start_b:actual_end].replace('\n', ' ').strip()
        return ""

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
