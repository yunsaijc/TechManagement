from src.services.logicon.service import LogicOnService

_service = None


def get_logicon_service() -> LogicOnService:
    global _service
    if _service is None:
        _service = LogicOnService()
    return _service


__all__ = ["get_logicon_service", "LogicOnService"]
