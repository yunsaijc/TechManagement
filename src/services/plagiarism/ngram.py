"""N-gram 滑动窗口切分 + 指纹生成

将句子切分为 N-gram 片段，并生成 SimHash 指纹用于快速比对。
"""
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Set

from src.services.plagiarism.tokenizer import Sentence


# 默认停用词
DEFAULT_STOP_WORDS: Set[str] = {
    '的', '了', '和', '与', '对', '在', '是', '为', '以', '及',
    '等', '于', '用', '可', '能', '会', '有', '也', '但', '或',
    '把', '被', '让', '使', '将', '要', '这', '那', '其', '所',
    '从', '到', '由', '向', '往', '至', '比', '给', '还', '再',
}


@dataclass
class NGram:
    """N-gram 片段"""
    text: str  # N-gram 文本
    position: int  # 在原文中的字符位置
    sentence_idx: int  # 所属句子索引
    sentence_text: str  # 所属句子原文（用于回溯）


class NGramSplitter:
    """N-gram 滑动窗口切分 + 指纹生成"""

    def __init__(
        self,
        n: int = 5,
        stop_words: Set[str] = None,
        use_fingerprint: bool = True,
        remove_stop_words: bool = False,  # 默认不去停用词，保持位置对齐
    ):
        """
        初始化 N-gram 切分器

        Args:
            n: N-gram 大小，默认 5
            stop_words: 停用词集合
            use_fingerprint: 是否生成指纹
            remove_stop_words: 是否去除停用词（默认 False，保持位置对齐）
        """
        self.n = n
        self.stop_words = stop_words or DEFAULT_STOP_WORDS
        self.use_fingerprint = use_fingerprint
        self.remove_stop_words = remove_stop_words

    def split(self, sentences: List[Sentence]) -> List[NGram]:
        """
        将句子列表切分为 N-gram

        示例（5-gram）:
        输入: "项目组织及参与单位拥有成熟的科学家团队"
        输出: [
            NGram(text="项目组织及参与单位拥有成熟", position=0, ...),
            NGram(text="织及参与单位拥有成熟的科学", position=1, ...),
            ...
        ]

        Args:
            sentences: 句子列表

        Returns:
            N-gram 列表
        """
        ngrams = []

        for sent_idx, sent in enumerate(sentences):
            # 预处理：可选去停用词
            text = sent.text
            if self.remove_stop_words:
                text = self._remove_stop_words(text)

            if len(text) < self.n:
                # 句子太短，无法生成完整的 N-gram
                # 保留原句作为单个片段
                if text:
                    ngrams.append(NGram(
                        text=text,
                        position=sent.start_pos,
                        sentence_idx=sent_idx,
                        sentence_text=sent.text,
                    ))
                continue

            # 滑动窗口生成 N-gram
            for pos in range(len(text) - self.n + 1):
                gram_text = text[pos:pos + self.n]

                ngrams.append(NGram(
                    text=gram_text,
                    position=sent.start_pos + pos,
                    sentence_idx=sent_idx,
                    sentence_text=sent.text,
                ))

        return ngrams

    def split_text(self, text: str) -> List[NGram]:
        """
        直接对文本切分（兼容旧接口）

        Args:
            text: 原始文本

        Returns:
            N-gram 列表
        """
        from src.services.plagiarism.tokenizer import SentenceTokenizer

        tokenizer = SentenceTokenizer()
        sentences = tokenizer.tokenize(text)
        return self.split(sentences)

    def _remove_stop_words(self, text: str) -> str:
        """去除停用词"""
        return ''.join(c for c in text if c not in self.stop_words)

    def _generate_fingerprint(self, text: str) -> int:
        """
        生成 SimHash 指纹

        Args:
            text: 文本

        Returns:
            指纹值
        """
        if not self.use_fingerprint:
            return hash(text)

        # 简化实现：使用 MD5 哈希的前 8 位作为指纹
        return int(hashlib.md5(text.encode('utf-8')).hexdigest()[:8], 16)

    def get_fingerprint(self, text: str) -> int:
        """获取文本的指纹"""
        return self._generate_fingerprint(text)


class NGramIndex:
    """N-gram 指纹索引"""

    def __init__(self):
        # 指纹 -> {doc_id: [positions]}
        self.index: Dict[int, Dict[str, List[int]]] = {}

        # 文档的 N-gram 集合
        self.doc_ngrams: Dict[str, List[NGram]] = {}

    def add_document(self, doc_id: str, ngrams: List[NGram]):
        """
        添加文档到索引

        Args:
            doc_id: 文档 ID
            ngrams: N-gram 列表
        """
        self.doc_ngrams[doc_id] = ngrams

        for ng in ngrams:
            fingerprint = self._generate_fingerprint(ng.text)

            if fingerprint not in self.index:
                self.index[fingerprint] = {}

            if doc_id not in self.index[fingerprint]:
                self.index[fingerprint][doc_id] = []

            self.index[fingerprint][doc_id].append(ng.position)

    def find_match(self, doc_id: str, ngram: NGram) -> List[dict]:
        """
        查找匹配的文档位置

        Args:
            doc_id: 当前文档 ID
            ngram: N-gram

        Returns:
            匹配位置列表 [{doc_id, position}]
        """
        fingerprint = self._generate_fingerprint(ngram.text)

        if fingerprint not in self.index:
            return []

        matches = []
        for other_doc_id, positions in self.index[fingerprint].items():
            if other_doc_id == doc_id:
                continue

            for pos in positions:
                matches.append({
                    "doc_id": other_doc_id,
                    "position": pos,
                })

        return matches

    def _generate_fingerprint(self, text: str) -> int:
        """生成指纹"""
        import hashlib
        return int(hashlib.md5(text.encode('utf-8')).hexdigest()[:8], 16)

    def get_common_fingerprints(self, doc_ids: List[str]) -> Dict[int, List[str]]:
        """
        获取多个文档共有的指纹

        Args:
            doc_ids: 文档 ID 列表

        Returns:
            {fingerprint: [doc_ids]}
        """
        if not doc_ids:
            return {}

        # 获取第一个文档的指纹集合
        first_doc = doc_ids[0]
        if first_doc not in self.doc_ngrams:
            return {}

        common = {}
        first_fingerprints = set()

        for ng in self.doc_ngrams[first_doc]:
            fp = self._generate_fingerprint(ng.text)
            first_fingerprints.add(fp)
            common[fp] = [first_doc]

        # 与其他文档交集
        for doc_id in doc_ids[1:]:
            if doc_id not in self.doc_ngrams:
                continue

            doc_fps = set()
            for ng in self.doc_ngrams[doc_id]:
                fp = self._generate_fingerprint(ng.text)
                doc_fps.add(fp)

                if fp in common:
                    common[fp].append(doc_id)

            # 只保留所有文档都有的指纹
            common = {
                fp: docs for fp, docs in common.items()
                if fp in doc_fps and len(docs) == len(doc_ids)
            }

        return common
