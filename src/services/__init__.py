"""基础服务模块

所有服务的基类和接口定义。
"""
from src.services.base.service import BaseService
from src.services.base.config import ServiceConfig

try:
    from src.services.grouping.service import GroupingService, get_grouping_service
except Exception:  # pragma: no cover - 可选依赖缺失时降级
    GroupingService = None
    get_grouping_service = None

try:
    from src.services.logicons.service import LogiConsService, get_logicons_service
except Exception:  # pragma: no cover - 可选依赖缺失时降级
    LogiConsService = None
    get_logicons_service = None

try:
    from src.services.perfcheck.service import PerfCheckService, get_perfcheck_service
except Exception:  # pragma: no cover - 可选依赖缺失时降级
    PerfCheckService = None
    get_perfcheck_service = None

__all__ = [
    "BaseService",
    "ServiceConfig",
]

if GroupingService is not None and get_grouping_service is not None:
    __all__.extend(["GroupingService", "get_grouping_service"])
if LogiConsService is not None and get_logicons_service is not None:
    __all__.extend(["LogiConsService", "get_logicons_service"])
if PerfCheckService is not None and get_perfcheck_service is not None:
    __all__.extend(["PerfCheckService", "get_perfcheck_service"])
