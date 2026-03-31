"""项目级规则注册表"""
from typing import Dict, List, Type

from src.services.review.project_rules.base import BaseProjectRule


class ProjectRuleRegistry:
    """项目级规则注册表"""

    _rules: Dict[str, Type[BaseProjectRule]] = {}

    @classmethod
    def register(cls, rule_class: Type[BaseProjectRule]):
        """注册规则"""
        instance = rule_class()
        cls._rules[instance.name] = rule_class
        return rule_class

    @classmethod
    def get_rule(cls, name: str) -> Type[BaseProjectRule] | None:
        """获取规则类"""
        return cls._rules.get(name)

    @classmethod
    def create_chain(cls, rule_names: List[str]) -> List[BaseProjectRule]:
        """按名称创建规则链"""
        rules: List[BaseProjectRule] = []
        for name in rule_names:
            rule_class = cls.get_rule(name)
            if not rule_class:
                continue
            rules.append(rule_class())
        rules.sort(key=lambda rule: rule.priority, reverse=True)
        return rules
