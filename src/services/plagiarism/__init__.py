"""查重服务."""

try:
    from src.services.plagiarism.agent import PlagiarismAgent, PlagiarismResult
except Exception:  # pragma: no cover - allow partial module imports during refactor
    PlagiarismAgent = None  # type: ignore[assignment]
    PlagiarismResult = None  # type: ignore[assignment]

__all__ = ["PlagiarismAgent", "PlagiarismResult"]
