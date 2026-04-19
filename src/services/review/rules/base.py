"""规则基类"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

from src.common.models.review import CheckResult, CheckStatus
from src.services.review.doc_types import normalize_doc_type

if TYPE_CHECKING:
    from src.common.models.document import DocumentContent
    from src.services.review.extractor import ExtractedContent


class ReviewContext:
    """审查上下文

    用于在规则执行过程中传递数据。
    """

    def __init__(
        self,
        file_data: bytes,
        file_type: str,
        doc_type: str,
        content: "DocumentContent" = None,  # type: ignore[assignment]
        extracted: "ExtractedContent" = None,  # 预提取的内容
        metadata: Dict[str, Any] = None,  # type: ignore[assignment]
    ):
        self.file_data = file_data
        self.file_type = file_type
        self.doc_type = normalize_doc_type(doc_type)
        self.content = content  # 原始文档内容（保留兼容）
        self.extracted = extracted  # 预提取的内容
        self.metadata = metadata or {}

    @property
    def document_type(self) -> str:
        """兼容旧字段访问。"""
        return self.doc_type


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
