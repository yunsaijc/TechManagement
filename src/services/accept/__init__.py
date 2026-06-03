from src.services.accept.models import (
    AcceptanceCheckRow,
    AcceptanceCheckResult,
    AttachmentEvidence,
    KPICommitment,
)
from src.services.accept.service import (
    AcceptanceAttachmentInput,
    AcceptanceAttachmentTextInput,
    AcceptanceService,
)

_service: AcceptanceService | None = None


def get_accept_service() -> AcceptanceService:
    global _service
    if _service is None:
        _service = AcceptanceService()
    return _service


__all__ = [
    "AcceptanceAttachmentInput",
    "AcceptanceAttachmentTextInput",
    "AcceptanceCheckResult",
    "AcceptanceCheckRow",
    "AcceptanceService",
    "AttachmentEvidence",
    "KPICommitment",
    "get_accept_service",
]
