"""Baseline services for native sandbox simulation."""

from __future__ import annotations

from src.common.models.simulation import BaselineSnapshot, BaselineTopicState

from . import repository


def create_baseline_snapshot(
    *,
    baseline_id: str,
    forecast_window: str,
    topics: list[BaselineTopicState],
    assumptions: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    persist: bool = True,
) -> BaselineSnapshot:
    snapshot = BaselineSnapshot(
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        topics=topics,
        assumptions=assumptions or [],
        metadata=metadata or {},
    )
    if persist:
        repository.save_baseline_snapshot(snapshot)
    return snapshot


def load_latest_baseline_snapshot() -> BaselineSnapshot | None:
    return repository.load_latest_baseline_snapshot()
