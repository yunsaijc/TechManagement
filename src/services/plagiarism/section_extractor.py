"""Section 区域提取器

使用正则表达式从文档中提取指定的 section 区域。
"""
import re
from typing import Dict, List, Optional


class SectionExtractor:
    """Section 区域提取器"""
    
    def __init__(self, section_config: Dict):
        """初始化
        
        Args:
            section_config: section 配置，包含 sections 列表
        """
        self.sections = section_config.get("sections", [])
    
    def extract(self, text: str) -> str:
        """从全文中提取目标 section 区域
        
        Args:
            text: 完整文档文本
            
        Returns:
            提取后的文本
        """
        if not self.sections:
            # 无配置，返回全文
            return text
        
        results = []
        
        for section in self.sections:
            start_pattern = section.get("start_pattern")
            end_pattern = section.get("end_pattern")
            
            if not start_pattern:
                continue
            
            # 编译正则表达式
            start_regex = re.compile(start_pattern)
            
            # 查找起始位置
            start_match = start_regex.search(text)
            if not start_match:
                continue
            
            start_pos = start_match.start()
            
            # 查找结束位置
            if end_pattern:
                end_regex = re.compile(end_pattern)
                end_match = end_regex.search(text[start_pos + 1:])
                
                if end_match:
                    end_pos = start_pos + 1 + end_match.start()
                else:
                    # 没找到结束标记，跳过
                    continue
            else:
                # 无结束模式，提取到文档结尾
                end_pos = len(text)
            
            # 提取区域内容
            section_text = text[start_pos:end_pos].strip()
            if section_text:
                results.append(section_text)
        
        return "\n".join(results)
    
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
        
        sections = section_config.get("sections", [])
        if not sections:
            return False
        
        for section in sections:
            if not section.get("start_pattern"):
                return False
        
        return True
