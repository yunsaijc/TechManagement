"""前置模板过滤器 - 标记应忽略的位置区间

在正式比对前过滤掉模板内容，避免将模板内容计入重复率。
相比后置过滤，前置过滤可以：
1. 减少指纹索引大小
2. 避免模板内容干扰连续匹配
3. 提高比对效率
"""
from dataclasses import dataclass
from typing import List

from src.services.plagiarism.tokenizer import Sentence
from src.services.plagiarism.template_filter import TemplateFilter


@dataclass
class ExcludedRange:
    """被排除的位置区间"""
    start: int  # 起始位置（包含）
    end: int  # 结束位置（不包含）
    reason: str  # 排除原因


class TemplatePreFilter:
    """
    前置模板过滤器
    
    在 N-gram 切分前标记应忽略的位置区间，
    使得后续比对时自动跳过这些位置。
    """

    def __init__(self, template_filter: TemplateFilter = None):
        """
        初始化前置过滤器
        
        Args:
            template_filter: 模板过滤器实例
        """
        self.template_filter = template_filter or TemplateFilter()
        
        # 预编译的正则表达式
        self._table_row_pattern = self.template_filter._table_compiled[0] if self.template_filter._table_compiled else None
        self._vertical_bar_pattern = self.template_filter._table_compiled[1] if len(self.template_filter._table_compiled) > 1 else None
        
        # 前置过滤专用的额外模式
        import re
        self._prefilter_patterns = [
            re.compile(r'^填写说明'),
            re.compile(r'^一{1,3}、|^二{1,3}、|^三{1,3}、'),  # 一、二、三
            re.compile(r'^\d+[、\.]+\s*\S+'),  # 1、项目  2. 内容（仅短行过滤）
            re.compile(r'^进度安排'),
            re.compile(r'^预期成果'),
            re.compile(r'^省级财政'),
            re.compile(r'^项目名称'),
            re.compile(r'^申报单位'),
        ]
        
    def mark_excluded_ranges(
        self, 
        sentences: List[Sentence],
        min_length: int = 15,
    ) -> List[ExcludedRange]:
        """
        标记所有应被排除的位置区间
        
        标记规则：
        1. 短句（< 15字符）→ 整个句子排除
        2. 模板句式 → 整个句子排除
        3. 标题模式 → 整个句子排除
        4. 表格内容 → 整个句子排除
        5. 纯数字/符号 → 整个句子排除
        
        Args:
            sentences: 句子列表
            min_length: 短句阈值
            
        Returns:
            排除区间列表（按 start 排序，不重叠）
        """
        excluded = []
        
        for sent in sentences:
            # 短句过滤
            if len(sent.text) < min_length:
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason="short_text",
                ))
                continue
            
            # 模板检测
            reason = self.template_filter.get_template_reason(sent.text)
            if reason:
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason=f"template:{reason}",
                ))
                continue
            
            # 标题检测
            if self.template_filter._is_heading(sent.text):
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason="heading",
                ))
                continue
            
            # 前置过滤专用模板模式
            matched_prefilter = False
            for idx, pattern in enumerate(self._prefilter_patterns):
                if pattern.match(sent.text.strip()):
                    # 枚举句（1、2、3）不能一刀切为模板。
                    # 仅把“短枚举行/表格化枚举行”排除，长正文枚举保留进入查重。
                    if idx == 2 and not self._should_exclude_numbered_sentence(sent):
                        continue
                    excluded.append(ExcludedRange(
                        start=sent.start_pos,
                        end=sent.end_pos,
                        reason="prefilter_template",
                    ))
                    matched_prefilter = True
                    break
            
            if matched_prefilter:
                continue
            
            # 表格行标记
            if self._table_row_pattern and self._table_row_pattern.search(sent.text):
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason="table_row",
                ))
                continue
            
            # 表格分隔符模式（中文 | 中文）
            if self._vertical_bar_pattern and self._vertical_bar_pattern.search(sent.text):
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason="table_content",
                ))
                continue
            
            # 来自表格的句子
            if sent.is_from_table:
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason="from_table",
                ))
                continue
            
            # 纯数字/符号
            if self.template_filter._is_number_only(sent.text):
                excluded.append(ExcludedRange(
                    start=sent.start_pos,
                    end=sent.end_pos,
                    reason="number_only",
                ))
                continue
        
        # 合并重叠区间
        return self._merge_ranges(excluded)

    def _should_exclude_numbered_sentence(self, sent: Sentence) -> bool:
        text = sent.text.strip()
        if len(text) <= 35:
            return True
        if sent.is_from_table:
            return True
        if "|" in text:
            return True
        if "[表格行" in text:
            return True
        return False
    
    def _merge_ranges(self, ranges: List[ExcludedRange]) -> List[ExcludedRange]:
        """
        合并重叠的区间
        
        Args:
            ranges: 区间列表
            
        Returns:
            合并后的区间列表
        """
        if not ranges:
            return []
        
        # 按起始位置排序
        sorted_ranges = sorted(ranges, key=lambda x: x.start)
        merged = [sorted_ranges[0]]
        
        for current in sorted_ranges[1:]:
            last = merged[-1]
            
            # 如果有重叠，合并
            if current.start <= last.end:
                merged[-1] = ExcludedRange(
                    start=last.start,
                    end=max(last.end, current.end),
                    reason=last.reason,
                )
            else:
                merged.append(current)
        
        return merged
