"""Scenario services for native sandbox simulation."""

from __future__ import annotations

from src.common.models.simulation import BaselineSnapshot, ScenarioDefinition, SimulationResult

from . import repository
from .engine import run_policy_simulation


def run_scenario(
    *,
    scenario: ScenarioDefinition,
    baseline: BaselineSnapshot | None = None,
    persist: bool = True,
) -> SimulationResult:
    resolved_baseline = baseline or repository.load_latest_baseline_snapshot()
    if resolved_baseline is None:
        raise RuntimeError("缺少 baseline snapshot，无法执行 scenario 推演")
    if resolved_baseline.baseline_id != scenario.baseline_id:
        raise RuntimeError("scenario.baseline_id 与当前 baseline 不一致")

    result = run_policy_simulation(resolved_baseline, scenario)
    if persist:
        repository.save_scenario_definition(scenario)
        repository.save_scenario_result(result)
    return result


def load_latest_scenario_result() -> SimulationResult | None:
    return repository.load_latest_scenario_result()
