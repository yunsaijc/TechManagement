"""比对引擎

基于 N-gram 指纹索引的查重比对引擎。
支持连续匹配检测、滑动窗口匹配。
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from src.services.plagiarism.ngram import NGram, NGramSplitter
from src.services.plagiarism.tokenizer import Sentence


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
    """查重比对引擎"""

    def __init__(
        self,
        min_continuous_match: int = 5,
        ngram_size: int = 5,
    ):
        """
        初始化比对引擎

        Args:
            min_continuous_match: 连续匹配阈值（连续 ≥ N 个相同 N-gram 才计入）
            ngram_size: N-gram 大小
        """
        self.min_continuous_match = min_continuous_match
        self.ngram_size = ngram_size

    def compare(
        self,
        docs: Dict[str, List[Sentence]],
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
    ) -> List[DocumentSimilarity]:
        """
        执行文档间比对

        步骤:
        1. 切分 N-gram
        2. 构建指纹倒排索引
        3. 滑动窗口检测连续重复
        4. 计算相似度分数

        Args:
            docs: {doc_id: 句子列表}
            threshold_high: 高相似度阈值
            threshold_medium: 中相似度阈值

        Returns:
            文档相似度列表
        """
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
                matches = self._find_continuous_matches(
                    doc_a,
                    doc_b,
                    doc_ngrams,
                    fingerprint_index,
                )

                # 计算相似度
                total_chars = len(doc_texts[doc_a])
                duplicate_chars = sum(
                    len(m.text) for m in matches
                )
                similarity = duplicate_chars / total_chars if total_chars > 0 else 0

                # 合并相邻/重叠的匹配
                merged_matches = self._merge_overlapping_matches(matches)

                results.append(DocumentSimilarity(
                    doc_a=doc_a,
                    doc_b=doc_b,
                    similarity=similarity,
                    type=self._classify(similarity, threshold_high, threshold_medium),
                    total_chars=total_chars,
                    duplicate_chars=duplicate_chars,
                    duplicate_segments=merged_matches,
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

    def _find_continuous_matches(
        self,
        doc_a: str,
        doc_b: str,
        doc_ngrams: Dict[str, List[NGram]],
        fingerprint_index: Dict,
    ) -> List[Match]:
        """
        查找两个文档间的连续匹配片段

        Args:
            doc_a: 文档A ID
            doc_b: 文档B ID
            doc_ngrams: N-gram 索引
            fingerprint_index: 指纹倒排索引

        Returns:
            匹配片段列表
        """
        matches = []
        ngrams_a = doc_ngrams[doc_a]
        ngrams_b = doc_ngrams[doc_b]

        # 构建 doc_b 的指纹集合（按位置排序）
        fingerprints_b: Dict[int, List[int]] = defaultdict(list)
        for ng in ngrams_b:
            fp = self._generate_fingerprint(ng.text)
            fingerprints_b[fp].append(ng.position)

        # 滑动窗口检测连续匹配
        i = 0
        while i < len(ngrams_a):
            ng = ngrams_a[i]
            fp = self._generate_fingerprint(ng.text)

            if fp in fingerprints_b and doc_b in fingerprint_index[fp]:
                # 找到匹配，扩展窗口
                match_end = i
                while (match_end + 1 < len(ngrams_a)):
                    next_fp = self._generate_fingerprint(ngrams_a[match_end + 1].text)
                    if next_fp in fingerprints_b and doc_b in fingerprint_index[next_fp]:
                        match_end += 1
                    else:
                        break

                count = match_end - i + 1

                if count >= self.min_continuous_match:
                    # 构造匹配文本（N-gram 有 n-1 个字符重叠）
                    start_pos = ngrams_a[i].position
                    end_pos = ngrams_a[match_end].position + self.ngram_size

                    # 正确计算实际文本长度：第一个完整，后面每个只加最后一个字符
                    match_text = ngrams_a[i].text  # 第一个 N-gram
                    for k in range(i + 1, match_end + 1):
                        match_text += ngrams_a[k].text[-1]  # 只追加最后一个字符

                    # 查找来源文档位置：应该根据位置对齐，而不是取第一个
                    # 连续匹配时，doc_a 和 doc_b 的位置是对齐的
                    # 使用 doc_a 的起始位置在 doc_b 中找对应的位置
                    source_start = ngrams_a[i].position  # 假设位置对齐
                    source_end = source_start + len(match_text)

                    # 验证 source 位置是否真的匹配
                    # 如果 doc_b 在该位置不匹配，则取最近的匹配位置
                    actual_match_start = self._find_actual_source_position(
                        doc_b, source_start, match_text, ngrams_b
                    )

                    matches.append(Match(
                        text=match_text,
                        start_pos=start_pos,
                        end_pos=end_pos,
                        ngram_count=count,
                        source_doc=doc_b,
                        source_start=actual_match_start,
                        source_end=actual_match_start + len(match_text),
                        source_text="",  # 后续填充
                    ))

                i = match_end + 1
            else:
                i += 1

        return matches

    def _find_actual_source_position(
        self,
        doc_b: str,
        approximate_pos: int,
        match_text: str,
        ngrams_b: List[NGram],
    ) -> int:
        """
        查找实际的来源文档位置

        Args:
            doc_b: 来源文档 ID
            approximate_pos: 近似位置
            match_text: 匹配的文本
            ngrams_b: doc_b 的 N-gram 列表

        Returns:
            实际的起始位置
        """
        # 在 doc_b 中找到与 match_text 完全匹配的位置
        for ng in ngrams_b:
            if ng.text == match_text[:len(ng.text)]:
                # 找到了匹配的 N-gram
                return ng.position

        # 如果没找到精确匹配，使用近似位置
        # 在附近找最接近的位置
        best_match = None
        min_distance = float('inf')

        for ng in ngrams_b:
            distance = abs(ng.position - approximate_pos)
            if distance < min_distance:
                min_distance = distance
                best_match = ng

        if best_match and min_distance < self.ngram_size * 2:
            return best_match.position

        return approximate_pos

    def _merge_overlapping_matches(self, matches: List[Match]) -> List[Match]:
        """
        合并相邻/重叠的匹配片段

        Args:
            matches: 原始匹配列表

        Returns:
            合并后的匹配列表
        """
        if not matches:
            return []

        # 按起始位置排序
        sorted_matches = sorted(matches, key=lambda m: m.start_pos)

        merged = [sorted_matches[0]]

        for current in sorted_matches[1:]:
            last = merged[-1]

            # 如果有重叠或相邻（距离 < ngram_size），合并
            if current.start_pos <= last.end_pos + self.ngram_size:
                # 合并：计算实际不重叠的文本
                overlap_start = last.end_pos
                new_text = current.text
                # 如果有重叠，只取不重叠的部分
                if current.start_pos < last.end_pos:
                    new_text = current.text[last.end_pos - current.start_pos:]
                if last.text:
                    merged_text = last.text + new_text
                else:
                    merged_text = new_text

                merged[-1] = Match(
                    text=merged_text,
                    start_pos=last.start_pos,
                    end_pos=current.end_pos,
                    ngram_count=last.ngram_count + current.ngram_count,
                    source_doc=last.source_doc,
                    source_start=last.source_start,
                    source_end=current.source_end,
                    source_text="",
                )
            else:
                merged.append(current)

        return merged

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
