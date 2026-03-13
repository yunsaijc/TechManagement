"""规则基类"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

from src.common.models.review import CheckResult, CheckStatus

if TYPE_CHECKING:
    from src.common.models.document import DocumentContent


class ReviewContext:
    """审查上下文

    用于在规则执行过程中传递数据。
    """

    def __init__(
        self,
        file_data: bytes,
        file_type: str,
        document_type: str,
        content: "DocumentContent" = None,  # type: ignore[assignment]
        metadata: Dict[str, Any] = None,  # type: ignore[assignment]
    ):
        self.file_data = file_data
        self.file_type = file_type
        self.document_type = document_type
        self.content = content
        self.metadata = metadata or {}


class BaseRule(ABC):
    """规则基类

    所有检查规则继承此类。
    """

    name: str = "base_rule"
    description: str = "基础规则"
    priority: int = 0  # 执行优先级，数字越大越先执行

    @abstractmethod
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行检查

        Args:
            context: 审查上下文

        Returns:
            CheckResult: 检查结果
        """
        pass

    async def should_run(self, context: ReviewContext) -> bool:
        """判断是否需要执行此规则

        Args:
            context: 审查上下文

        Returns:
            bool: 是否执行
        """
        return True

    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        return {}
