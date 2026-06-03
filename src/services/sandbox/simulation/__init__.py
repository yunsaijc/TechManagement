"""Native sandbox simulation package."""

from .facade import (
    ScenarioExecutionBundle,
    compare_latest_result,
    compare_result,
    build_baseline_snapshot_from_sources,
    create_baseline_snapshot,
    explain_latest_result,
    explain_result,
    load_latest_baseline_snapshot,
    load_latest_scenario_result,
    run_scenario,
    run_scenario_contract,
)

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
