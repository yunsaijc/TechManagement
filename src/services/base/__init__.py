"""服务基模块"""
from src.services.base.config import ServiceConfig
from src.services.base.service import BaseService, ServiceInput, ServiceOutput

__all__ = ["BaseService", "ServiceConfig", "ServiceInput", "ServiceOutput"]
