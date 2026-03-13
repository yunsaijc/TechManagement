"""基础服务抽象"""
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from src.services.base.config import ServiceConfig

T = TypeVar("T")
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseService(ABC, Generic[InputT, OutputT]):
    """服务基类

    所有服务继承此类，实现业务逻辑。

    Args:
        InputT: 输入类型
        OutputT: 输出类型
    """

    def __init__(self, config: ServiceConfig = None):
        """初始化服务

        Args:
            config: 服务配置
        """
        self.config = config or ServiceConfig(name=self.__class__.__name__)
        self._initialized = False

    @property
    def name(self) -> str:
        """服务名称"""
        return self.config.name

    @property
    def version(self) -> str:
        """服务版本"""
        return self.config.version

    @abstractmethod
    async def process(self, input_data: InputT) -> OutputT:
        """处理业务逻辑

        Args:
            input_data: 输入数据

        Returns:
            输出数据
        """
        pass

    async def initialize(self) -> None:
        """初始化服务（可选实现）"""
        self._initialized = True

    async def shutdown(self) -> None:
        """关闭服务（可选实现）"""
        pass

    async def health_check(self) -> bool:
        """健康检查

        Returns:
            是否健康
        """
        return self._initialized


class ServiceInput(BaseModel):
    """服务输入基类"""
    pass


class ServiceOutput(BaseModel):
    """服务输出基类"""
    pass
