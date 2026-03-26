"""模板内容过滤器

多层过滤机制，去除标题、表格头、模板句式等非正文内容。
"""
import re
from typing import List, Set, Optional

from src.services.plagiarism.tokenizer import Sentence


class TemplateFilter:
    """模板内容过滤器"""

    # 白名单：常见模板句式（不计入重复）
    TEMPLATE_PHRASES = [
        r"为了认真贯彻落实.*?要求",
        r"根据.*?规定",
        r"特制定本.*?",
        r"本办法适用于",
        r"现将.*?情况汇报如下",
        r"\d+[万千百亿].*?元",  # 金额模板
        r"^\d+\.\d+[^\w]",  # 数字编号开头
    ]

    # 标题模式
    HEADING_PATTERNS = [
        r"^第[一二三四五六七八九十百]+[章节部分篇]",  # 第一章、第二部分
        r"^[一二三四五六七八九十]、",  # 一、二、三
        r"^\d+\.\d+",  # 1.2.3
        r"^[A-Z][\.、]",  # A. B. C.
        r"^\([a-zA-Z0-9一二三四五六七八九十]+\)",  # (1) (一)
        r"^【[^】]+】",  # 【标题】
        r"^\d+[、\.．:：]\s*\S+",  # 1、项目组织实施机制
    ]

    # 表格相关（使用 search 匹配任意位置）
    # 注意：只排除纯表格结构内容，保留表格中的正文
    TABLE_PATTERNS = [
        r'^\s*\[表格行\d+\]\s*$',  # 只有表格行标记，没有内容
        r'^\s*\[表格行\d+\]\s*[^\w\s]{0,10}\s*$',  # 表格行标记+少量符号
        r'^表格序号',  # 表格表头
    ]

    # 表格正文的最小长度阈值（包含表格标记）
    TABLE_CONTENT_MIN_LENGTH = 50
    TABLE_MARKER_MIN_COUNT = 2

    # 短句过滤阈值
    MIN_SENTENCE_LENGTH = 15

    # 纯数字/符号模式
    NUMBER_ONLY_PATTERN = re.compile(r'^[\d\s,，。.．:：%％]+$')

    def __init__(self, whitelist_patterns: List[str] = None):
        """
        初始化过滤器

        Args:
            whitelist_patterns: 自明白名单模式列表
        """
        self.template_phrases = self.TEMPLATE_PHRASES.copy()
        if whitelist_patterns:
            self.template_phrases.extend(whitelist_patterns)

        # 编译正则表达式
        self._heading_compiled = [re.compile(p) for p in self.HEADING_PATTERNS]
        self._table_compiled = [re.compile(p) for p in self.TABLE_PATTERNS]
        self._template_compiled = [re.compile(p) for p in self.template_phrases]

    def filter(self, sentences: List[Sentence]) -> List[Sentence]:
        """
        过滤模板内容

        策略:
        1. 白名单匹配 → 跳过
        2. 标题检测 → 跳过
        3. 短句过滤（< 15字）→ 跳过
        4. 纯数字/符号 → 跳过
        5. 表格相关 → 跳过

        Args:
            sentences: 句子列表

        Returns:
            过滤后的句子列表
        """
        filtered = []

        for sent in sentences:
            if self._is_template(sent.text):
                continue
            if self._is_heading(sent.text):
                continue
            if self._is_too_short(sent.text):
                continue
            if self._is_number_only(sent.text):
                continue
            if self._is_table_related(sent.text):
                continue
            filtered.append(sent)

        return filtered

    def filter_text(self, text: str) -> str:
        """
        过滤文本中的模板内容（兼容旧接口）

        Args:
            text: 原始文本

        Returns:
            过滤后的文本
        """
        from src.services.plagiarism.tokenizer import SentenceTokenizer

        tokenizer = SentenceTokenizer()
        sentences = tokenizer.tokenize(text)
        filtered = self.filter(sentences)

        return '\n'.join(sent.text for sent in filtered)

    def _is_template(self, text: str) -> bool:
        """检查是否匹配白名单模板"""
        for regex in self._template_compiled:
            if regex.match(text):
                return True
        return False

    def _is_heading(self, text: str) -> bool:
        """检查是否标题"""
        # 检查长度，太短的不一定是大标题
        if len(text) < 5:
            return False

        # 如果文本很长（超过50字），不太可能是标题，可能是正文中的编号
        if len(text) > 50:
            return False

        for regex in self._heading_compiled:
            if regex.match(text):
                return True
        return False

    def _is_too_short(self, text: str) -> bool:
        """检查是否过短（独立句子）"""
        # 只有很短的才过滤，避免误杀正常短句
        return len(text) < self.MIN_SENTENCE_LENGTH

    def _is_number_only(self, text: str) -> bool:
        """检查是否纯数字/符号"""
        return bool(self.NUMBER_ONLY_PATTERN.match(text))

    def _is_table_related(self, text: str) -> bool:
        """检查是否表格相关内容

        策略：
        1. 如果文本很短且只包含表格标记，认为是表格结构内容，排除
        2. 如果文本包含表格标记但有足够的正文内容，保留参与查重
        """
        has_table_marker = '[表格行' in text
        table_marker_count = text.count('[表格行')
        pipe_count = text.count('|')

        # 明显的表格骨架文本：多行表格标记 + 多列分隔符
        # 这类内容即使字符较长，也更接近模板结构而非正文。
        if table_marker_count >= self.TABLE_MARKER_MIN_COUNT and pipe_count >= 4:
            return True

        if not has_table_marker:
            # 检查其他表格模式
            for regex in self._table_compiled:
                if regex.search(text):
                    return True
            return False

        # 包含表格标记，判断是否只是结构内容
        # 如果文本长度超过阈值，认为是包含正文的表格内容，保留
        if len(text) >= self.TABLE_CONTENT_MIN_LENGTH and pipe_count <= 2:
            return False

        # 短文本，检查是否是纯表格结构
        for regex in self._table_compiled:
            if regex.search(text):
                return True

        return False

    def is_template(self, text: str) -> bool:
        """
        检查文本片段是否是模板内容（用于后置过滤）

        Args:
            text: 待检查的文本片段

        Returns:
            True 如果是模板内容
        """
        if self._is_heading(text):
            return True
        if self._is_too_short(text):
            return True
        if self._is_table_related(text):
            return True
        if self._is_template(text):
            return True
        if self._is_number_only(text):
            return True
        return False

    def get_template_reason(self, text: str) -> Optional[str]:
        """
        获取文本片段被判定为模板的原因

        Args:
            text: 待检查的文本片段

        Returns:
            模板原因字符串，如果是有效内容则返回 None
        """
        if self._is_heading(text):
            return "heading"
        if self._is_too_short(text):
            return "short"
        if self._is_table_related(text):
            return "table"
        if self._is_template(text):
            return "whitelist"
        if self._is_number_only(text):
            return "number_only"
        return None

    def get_filter_stats(self, sentences: List[Sentence]) -> dict:
        """
        获取过滤统计信息

        Args:
            sentences: 原始句子列表

        Returns:
            统计信息
        """
        stats = {
            "total": len(sentences),
            "filtered": 0,
            "reasons": {
                "template": 0,
                "heading": 0,
                "short": 0,
                "number_only": 0,
                "table": 0,
            }
        }

        for sent in sentences:
            reasons = []
            if self._is_template(sent.text):
                reasons.append("template")
            if self._is_heading(sent.text):
                reasons.append("heading")
            if self._is_too_short(sent.text):
                reasons.append("short")
            if self._is_number_only(sent.text):
                reasons.append("number_only")
            if self._is_table_related(sent.text):
                reasons.append("table")

            if reasons:
                stats["filtered"] += 1
                for r in reasons:
                    stats["reasons"][r] += 1

        stats["passed"] = stats["total"] - stats["filtered"]
        return stats
