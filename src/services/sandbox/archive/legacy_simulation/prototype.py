"""Minimal wrapper around the legacy leadership sandbox prototype."""

from dataclasses import dataclass
from typing import Mapping

from src.services.sandbox.leadership_sandbox_orchestrator import (
    load_latest_leadership_report,
    run_leadership_sandbox,
)


@dataclass
class ForecastOptions:
    question: str | None = None
    run_preflight: bool = False
    mode: str = "quick"
    force_refresh: bool = False

    def as_kwargs(self) -> Mapping[str, object]:
        return {
            "question": self.question,
            "run_preflight": self.run_preflight,
            "mode": self.mode,
            "force_refresh": self.force_refresh,
        }


def run_forecast(
    question: str | None = None,
    run_preflight: bool = False,
    mode: str = "quick",
    force_refresh: bool = False,
):
    """Run the leadership sandbox prototype without behavioral changes."""
    options = ForecastOptions(
        question=question,
        run_preflight=run_preflight,
        mode=mode,
        force_refresh=force_refresh,
    )
    return run_leadership_sandbox(**options.as_kwargs())


def load_latest_report():
    """Return the latest stored leadership sandbox report."""
    return load_latest_leadership_report()
