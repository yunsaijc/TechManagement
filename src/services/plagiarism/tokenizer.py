"""句子级分词器

按标点符号（。！？；）将文本切分为句子，而非简单按行切分。
保留位置映射，便于后续追溯。
"""
import re
from dataclasses import dataclass
from typing import List


@dataclass
class Sentence:
    """句子"""
    text: str  # 句子文本
    start_pos: int  # 在原文中的起始位置
    end_pos: int  # 在原文中的结束位置
    line_number: int  # 起始行号
    is_from_table: bool = False  # 是否来自表格


class SentenceTokenizer:
    """中文句子分词器 - 按标点分句"""

    # 句末标点
    SENTENCE_ENDINGS = ['。', '！', '？', '；']

    # 句内分隔符（不分句，但标记位置）
    INTERNAL_SEPARATORS = ['，', '、', ':', '：', '(', ')', '（', '）']
    TABLE_ROW_MARKER = re.compile(r"\[表格行\d+\]")
    HEADING_BOUNDARY = re.compile(
        r"(第[一二三四五六七八九十]+部分|第一部分|第二部分|第三部分|项目简介|项目立项背景及意义|[一二三四五六七八九十]、|[（(][一二三四五六七八九十]+[）)])"
    )

    def tokenize(self, text: str) -> List[Sentence]:
        """
        将文本切分为句子列表

        规则:
        1. 按句末标点（。！？；）切分
        2. 表格内容按单元格切分
        3. 保留原始位置（start_pos, end_pos）

        Args:
            text: 原始文本

        Returns:
            句子列表
        """
        if not text:
            return []

        sentences = []
        current_text: List[str] = []
        line_offset = 0
        sentence_start_pos = 0

        def flush(end_pos: int) -> None:
            nonlocal current_text, sentence_start_pos
            sentence_text = ''.join(current_text).strip()
            if sentence_text:
                sentences.append(Sentence(
                    text=sentence_text,
                    start_pos=sentence_start_pos,
                    end_pos=end_pos,
                    line_number=line_offset + 1,
                ))
            current_text = []
            sentence_start_pos = end_pos

        i = 0
        while i < len(text):
            marker = self.TABLE_ROW_MARKER.match(text, i)
            if marker:
                # [表格行X] 视为结构边界：切断当前句，避免把多行表格与正文拼成超长句
                if current_text:
                    flush(i)
                i = marker.end()
                sentence_start_pos = i
                continue

            if current_text and self._is_heading_boundary(text, i):
                # 章节标题视为硬边界，避免把表格尾巴/上一段正文与标题和下一段正文粘成一个句子
                flush(i)
                continue

            char = text[i]
            if not current_text:
                sentence_start_pos = i

            if char in self.SENTENCE_ENDINGS:
                current_text.append(char)
                flush(i + 1)
            elif char == '\n':
                current_text.append(char)
                line_offset += 1
            else:
                current_text.append(char)
            i += 1

        if current_text:
            flush(len(text))

        return sentences

    def _is_heading_boundary(self, text: str, pos: int) -> bool:
        match = self.HEADING_BOUNDARY.match(text, pos)
        if not match:
            return False

        # 只在合理边界切开：文本开头、换行后，或当前字符前是空白/表格分隔
        if pos == 0:
            return True
        prev = text[pos - 1]
        if prev in {'\n', '\r', '\t', ' ', '|', '：', ':'}:
            return True
        return False

    def tokenize_by_paragraphs(self, text: str) -> List[Sentence]:
        """
        按段落分句（保留段落结构）

        适用于需要保留段落信息的场景。

        Args:
            text: 原始文本

        Returns:
            句子列表
        """
        paragraphs = text.split('\n\n')  # 双换行分割段落
        sentences = []
        current_pos = 0
        line_offset = 0

        for para in paragraphs:
            if not para.strip():
                line_offset += 2
                current_pos += 2
                continue

            # 对每个段落进行分句
            para_sentences = self.tokenize(para)

            # 调整位置
            for sent in para_sentences:
                sent.start_pos += current_pos
                sent.end_pos += current_pos
                sent.line_number += line_offset

            sentences.extend(para_sentences)

            # 更新位置
            current_pos += len(para)
            line_offset += para.count('\n')

        return sentences
