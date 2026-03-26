from src.services.perfcheck.service import PerfCheckService
from src.services.perfcheck.reporter import PerfCheckReporter
from src.services.perfcheck.parser import PerfCheckParser
from src.services.perfcheck.detector import PerfCheckDetector

_service = None

def get_perfcheck_service() -> PerfCheckService:
    """获取单例服务实例"""
    global _service
    if _service is None:
        _service = PerfCheckService()
    return _service

__all__ = ["get_perfcheck_service", "PerfCheckService", "PerfCheckReporter", "PerfCheckParser", "PerfCheckDetector"]
