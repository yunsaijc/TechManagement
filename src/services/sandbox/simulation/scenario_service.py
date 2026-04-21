"""Scenario services for native sandbox simulation."""

from __future__ import annotations

from dataclasses import dataclass

from src.common.models.simulation import (
    BaselineSnapshot,
    CompiledScenario,
    ScenarioContract,
    ScenarioDefinition,
    SimulationResult,
)

from . import repository
from .engine import run_policy_simulation
from .scenario_compiler import compile_scenario_contract

SUPPORTED_BASELINE_PROVENANCE_KINDS = {"shared_layer"}


@dataclass(frozen=True)
class ScenarioExecutionBundle:
    baseline: BaselineSnapshot
    compiled: CompiledScenario
    result: SimulationResult


def run_scenario(
    *,
    scenario: ScenarioDefinition,
    baseline: BaselineSnapshot | None = None,
    persist: bool = True,
    require_supported_baseline: bool = True,
) -> SimulationResult:
    resolved_baseline = baseline or repository.load_latest_baseline_snapshot()
    if resolved_baseline is None:
        raise RuntimeError("缺少 baseline snapshot，无法执行 scenario 推演")
    if require_supported_baseline:
        _require_supported_baseline(resolved_baseline)
    if resolved_baseline.baseline_id != scenario.baseline_id:
        raise RuntimeError("scenario.baseline_id 与当前 baseline 不一致")

    result = run_policy_simulation(resolved_baseline, scenario)
    if persist:
        repository.save_scenario_definition(scenario)
        repository.save_scenario_result(
            result,
            baseline=resolved_baseline,
            scenario=scenario,
        )
    return result


def load_latest_scenario_result() -> SimulationResult | None:
    return repository.load_latest_scenario_result()


def run_scenario_contract(
    *,
    contract: ScenarioContract,
    baseline: BaselineSnapshot | None = None,
    persist: bool = True,
    require_supported_baseline: bool = True,
) -> ScenarioExecutionBundle:
    resolved_baseline = baseline or repository.load_latest_baseline_snapshot()
    if resolved_baseline is None:
        raise RuntimeError("缺少 baseline snapshot，无法执行 scenario 推演")
    if require_supported_baseline:
        _require_supported_baseline(resolved_baseline)

    compiled = compile_scenario_contract(contract, baseline=resolved_baseline)
    result = run_scenario(
        scenario=compiled.scenario_definition,
        baseline=resolved_baseline,
        persist=False,
        require_supported_baseline=require_supported_baseline,
    )
    if persist:
        repository.save_scenario_definition(compiled.scenario_definition)
        repository.save_scenario_result(
            result,
            baseline=resolved_baseline,
            scenario=compiled.scenario_definition,
            contract=contract,
            compiled=compiled,
        )
    return ScenarioExecutionBundle(
        baseline=resolved_baseline,
        compiled=compiled,
        result=result,
    )


def _require_supported_baseline(baseline: BaselineSnapshot) -> None:
    metadata = baseline.metadata or {}
    provenance = metadata.get("baselineProvenance")
    if isinstance(provenance, dict):
        kind = provenance.get("kind")
    else:
        kind = None
    if kind in SUPPORTED_BASELINE_PROVENANCE_KINDS:
        return

    provenance_text = "unknown"
    if isinstance(provenance, dict):
        source = provenance.get("source")
        provenance_text = str(kind or source or provenance_text)

    raise RuntimeError(
        "当前 scenario 推演只接受共享数据层构建的 baseline；"
        "请先调用 /api/v1/sandbox/simulation/baseline/build 生成真实 baseline。"
        f" 当前 baseline 来源={provenance_text}"
    )
