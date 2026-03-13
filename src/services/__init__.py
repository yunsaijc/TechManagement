"""基础服务模块

所有服务的基类和接口定义。
"""
from src.services.base.service import BaseService
from src.services.base.config import ServiceConfig

__all__ = ["BaseService", "ServiceConfig"]
