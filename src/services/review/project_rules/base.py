"""项目级规则基类"""
from abc import ABC, abstractmethod
from typing import Any, Dict

from src.common.models import CheckResult, ProjectReviewContext


class BaseProjectRule(ABC):
    """项目级规则基类"""

    name: str = "base_project_rule"
    description: str = "基础项目规则"
    priority: int = 0

    @abstractmethod
    async def check(self, context: ProjectReviewContext) -> CheckResult:
        """执行检查"""

    async def should_run(self, context: ProjectReviewContext) -> bool:
        """判断是否执行"""
        return True

    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        return {}
