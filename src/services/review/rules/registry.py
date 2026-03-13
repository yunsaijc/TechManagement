"""规则注册表"""
from typing import Dict, List, Type

from src.services.review.rules.base import BaseRule


class RuleRegistry:
    """规则注册表

    管理所有规则的注册和获取。
    """

    _rules: Dict[str, Type[BaseRule]] = {}

    @classmethod
    def register(cls, rule_class: Type[BaseRule]):
        """注册规则

        Args:
            rule_class: 规则类
        """
        instance = rule_class()
        cls._rules[instance.name] = rule_class
        return rule_class

    @classmethod
    def get_rule(cls, name: str) -> Type[BaseRule]:
        """获取规则类

        Args:
            name: 规则名称

        Returns:
            规则类
        """
        return cls._rules.get(name)

    @classmethod
    def get_all_rules(cls) -> List[Type[BaseRule]]:
        """获取所有规则

        Returns:
            规则类列表
        """
        return list(cls._rules.values())

    @classmethod
    def create_chain(cls, document_type: str = None) -> List[BaseRule]:
        """创建规则链

        Args:
            document_type: 文档类型

        Returns:
            规则实例列表
        """
        rules = []
        for rule_class in cls._rules.values():
            instance = rule_class()
            rules.append(instance)

        # 按优先级排序
        rules.sort(key=lambda r: r.priority, reverse=True)
        return rules
