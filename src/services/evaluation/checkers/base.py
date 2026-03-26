"""
检查器基类

定义所有检查器的公共接口和基础实现。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from src.common.llm import get_default_llm_client


class BaseChecker(ABC):
    """检查器基类
    
    所有维度检查器的抽象基类，定义公共接口。
    """
    
    # 子类必须指定维度代码
    dimension: str = ""
    dimension_name: str = ""
    
    def __init__(self, llm: Optional[Any] = None):
        """初始化检查器
        
        Args:
            llm: LLM实例，如未指定则使用默认配置
        """
        self.llm = llm or get_default_llm_client()
        self._check_items: List[Dict[str, str]] = []
        self._required_sections: List[str] = []
    
    @property
    def check_items(self) -> List[Dict[str, str]]:
        """获取检查项列表"""
        return self._check_items
    
    @property
    def required_sections(self) -> List[str]:
        """获取依赖的文档章节"""
        return self._required_sections
    
    @abstractmethod
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行检查
        
        Args:
            content: 包含文档内容的字典，key为章节名，value为章节内容
            
        Returns:
            CheckResult: 检查结果
        """
        pass
    
    def _build_prompt(self, content: Dict[str, Any]) -> str:
        """构建LLM提示词
        
        Args:
            content: 文档内容
            
        Returns:
            str: 构建好的提示词
        """
        raise NotImplementedError("子类应实现此方法")
    
    def _parse_result(self, llm_output: str) -> CheckResult:
        """解析LLM输出
        
        Args:
            llm_output: LLM的输出文本
            
        Returns:
            CheckResult: 解析后的检查结果
        """
        raise NotImplementedError("子类应实现此方法")
    
    def _extract_sections(
        self, 
        content: Dict[str, Any], 
        section_names: List[str]
    ) -> Dict[str, Any]:
        """提取指定章节的内容
        
        Args:
            content: 完整文档内容
            section_names: 需要提取的章节名列表
            
        Returns:
            Dict[str, Any]: 提取的章节内容
        """
        result = {}
        for name in section_names:
            # 尝试精确匹配
            if name in content:
                result[name] = content[name]
                continue
            
            # 尝试模糊匹配（章节名可能包含空格或格式差异）
            for key in content:
                if name in key or key in name:
                    result[name] = content[key]
                    break
        
        return result
    
    def _format_content_for_prompt(self, content: Dict[str, Any]) -> str:
        """格式化内容用于提示词
        
        Args:
            content: 文档内容
            
        Returns:
            str: 格式化后的文本
        """
        lines = []
        for section, text in content.items():
            lines.append(f"## {section}")
            lines.append(str(text))
            lines.append("")
        return "\n".join(lines)
    
    def _calculate_weighted_score(self, items: List[CheckItem]) -> float:
        """计算加权得分
        
        Args:
            items: 检查项列表
            
        Returns:
            float: 加权平均分
        """
        if not items:
            return 5.0  # 默认中等分数
        
        total_weight = sum(item.weight for item in items)
        if total_weight == 0:
            return 5.0
        
        weighted_sum = sum(item.score * item.weight for item in items)
        return round(weighted_sum / total_weight, 2)
    
    def _aggregate_confidence(self, items: List[CheckItem]) -> float:
        """聚合置信度
        
        Args:
            items: 检查项列表
            
        Returns:
            float: 平均置信度
        """
        if not items:
            return 0.5
        
        return round(sum(item.weight for item in items) / len(items), 2)
