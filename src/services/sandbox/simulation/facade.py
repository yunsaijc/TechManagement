"""Public facade for native sandbox simulation."""

from __future__ import annotations

from .baseline_service import (
    build_baseline_snapshot_from_sources,
    create_baseline_snapshot,
    load_latest_baseline_snapshot,
)
from .compare_service import compare_latest_result, compare_result
from .explain_service import explain_latest_result, explain_result
from .scenario_service import ScenarioExecutionBundle, load_latest_scenario_result, run_scenario, run_scenario_contract

__all__ = [
    "create_baseline_snapshot",
    "build_baseline_snapshot_from_sources",
    "load_latest_baseline_snapshot",
    "run_scenario",
    "run_scenario_contract",
    "ScenarioExecutionBundle",
    "load_latest_scenario_result",
    "compare_result",
    "compare_latest_result",
    "explain_result",
    "explain_latest_result",
]
