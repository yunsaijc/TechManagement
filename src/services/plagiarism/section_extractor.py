"""Section 区域提取器.

支持两种配置形态：
1. primary_scope: 单一主检测区域（推荐，Primary Only）
2. sections: 多段区域（兼容旧配置）
"""
import re
from typing import Any, Dict, List, Optional, Tuple


class SectionExtractor:
    """Section 区域提取器"""
    
    def __init__(self, section_config: Dict):
        """初始化
        
        Args:
            section_config: section 配置，包含 sections 列表
        """
        self.section_config = section_config or {}
        self.primary_scope = self.section_config.get("primary_scope", {})
        self.sections = self.section_config.get("sections", [])

    def extract(self, text: str) -> str:
        """从全文中提取目标 section 区域
        
        Args:
            text: 完整文档文本
            
        Returns:
            提取后的文本
        """
        extracted, _, _ = self.extract_with_meta(text)
        return extracted

    def extract_with_meta(self, text: str) -> Tuple[str, int, int]:
        """提取主检测区域并返回坐标.

        Returns:
            (提取文本, 起始坐标, 结束坐标)
            若未命中，返回 ("", -1, -1)
        """
        if not text:
            return "", -1, -1

        # 推荐路径：single primary scope
        if self.primary_scope:
            start_pattern = self.primary_scope.get("start_pattern")
            end_pattern = self.primary_scope.get("end_pattern")
            extracted, start, end = self._extract_single_scope(text, start_pattern, end_pattern)
            return extracted, start, end

        # 兼容旧配置：sections 多段拼接
        if not self.sections:
            return "", -1, -1

        results = []
        global_start = -1
        global_end = -1

        for section in self.sections:
            start_pattern = section.get("start_pattern")
            end_pattern = section.get("end_pattern")
            section_text, start_pos, end_pos = self._extract_single_scope(text, start_pattern, end_pattern)
            if section_text:
                results.append(section_text)
                if global_start < 0 or start_pos < global_start:
                    global_start = start_pos
                global_end = max(global_end, end_pos)

        return "\n".join(results), global_start, global_end

    def _extract_single_scope(
        self,
        text: str,
        start_pattern: Optional[str],
        end_pattern: Optional[str],
    ) -> Tuple[str, int, int]:
        if not start_pattern:
            return "", -1, -1

        start_match = re.compile(start_pattern).search(text)
        if not start_match:
            return "", -1, -1
        start_pos = start_match.start()

        if end_pattern:
            end_match = re.compile(end_pattern).search(text[start_pos + 1:])
            if not end_match:
                return "", -1, -1
            end_pos = start_pos + 1 + end_match.start()
        else:
            end_pos = len(text)

        if end_pos <= start_pos:
            return "", -1, -1
        section_text = text[start_pos:end_pos].strip()
        if not section_text:
            return "", -1, -1
        return section_text, start_pos, end_pos
    
    def filter_template_content(self, text: str) -> str:
        """过滤模板内容，只保留正文

        Args:
            text: 原始文本

        Returns:
            过滤后的正文
        """
        lines = text.split('\n')
        filtered_lines = []

        # 模板内容的正则模式
        patterns_to_skip = [
            # 章节标题：一、二、三 或 第X部分
            r'^[\u4e00-\u9fa5]\s*[、.]\s*\S+',
            r'^第[一二三四五六七八九十百]+部分',
            r'^第一部分\s*',
            r'^第二部分\s*',
            r'^第三部分\s*',
            # 表格行标记 [表格行X]
            r'^\[表格行\d+\]',
            # 纯表格表头（只有 | 分隔的）
            r'^[\u4e00-\u9fa5a-zA-Z]+\s*\|',
        ]

        skip_regexes = [re.compile(p) for p in patterns_to_skip]

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 过滤太短的内容（少于10个字符）
            if len(line) < 10:
                continue

            # 检查是否匹配任何模板模式
            is_template = False
            for regex in skip_regexes:
                if regex.match(line):
                    is_template = True
                    break

            if not is_template:
                filtered_lines.append(line)

        return "\n".join(filtered_lines)
    
    @staticmethod
    def validate_config(section_config: Dict) -> bool:
        """验证配置是否有效
        
        Args:
            section_config: section 配置
            
        Returns:
            是否有效
        """
        if not section_config:
            return False
        
        primary_scope = section_config.get("primary_scope")
        if isinstance(primary_scope, dict):
            return bool(primary_scope.get("start_pattern"))

        sections = section_config.get("sections", [])
        if sections:
            for section in sections:
                if not section.get("start_pattern"):
                    return False
            return True

        return False
