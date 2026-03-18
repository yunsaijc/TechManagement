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
