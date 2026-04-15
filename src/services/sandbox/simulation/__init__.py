"""Native sandbox simulation package."""

from .facade import (
    compare_latest_result,
    compare_result,
    build_baseline_snapshot_from_sources,
    create_baseline_snapshot,
    explain_latest_result,
    explain_result,
    load_latest_baseline_snapshot,
    load_latest_scenario_result,
    run_scenario,
)

__all__ = [
    "create_baseline_snapshot",
    "build_baseline_snapshot_from_sources",
    "load_latest_baseline_snapshot",
    "run_scenario",
    "load_latest_scenario_result",
    "compare_result",
    "compare_latest_result",
    "explain_result",
    "explain_latest_result",
]
