"""Sandbox 研发链路 API 路由。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.common.models.simulation import BaselineTopicState, PolicyShock, ScenarioDefinition
from src.services.sandbox.simulation.facade import (
    compare_latest_result,
    compare_result,
    build_baseline_snapshot_from_sources,
    create_baseline_snapshot,
    explain_result,
    explain_latest_result,
    load_latest_baseline_snapshot,
    load_latest_scenario_result,
    run_scenario,
)
from src.services.sandbox.simulation.debug_html import render_debug_html
from src.services.sandbox.simulation.debug_payload import build_debug_payload

router = APIRouter()
SIMULATION_DEBUG_DIR = Path("debug_sandbox/simulation")


class LeadershipForecastRequest(BaseModel):
    question: str | None = None
    runPreflight: bool = False
    mode: str = "quick"
    forceRefresh: bool = False


class SimulationTopicInput(BaseModel):
    topicId: str
    applicationCount: int
    fundedCount: int
    fundingAmount: float
    scoreProxy: float | None = None
    collaborationDensity: float = 0.0
    topicCentrality: float = 0.0
    migrationStrength: float = 0.0
    proxyRisk: float = 0.0


class SimulationPolicyShockInput(BaseModel):
    shockId: str
    shockType: str
    targetTopics: list[str] = Field(default_factory=list)
    intensity: float = 0.5
    coverage: float = 1.0
    lag: int = 0
    parameters: dict[str, object] = Field(default_factory=dict)


class SimulationBaselineRequest(BaseModel):
    baselineId: str = "baseline_default"
    forecastWindow: str
    topics: list[SimulationTopicInput] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class SimulationBaselineBuildRequest(BaseModel):
    baselineId: str
    startYear: int
    endYear: int
    persist: bool = True


class SimulationScenarioRequest(BaseModel):
    scenarioId: str
    baselineId: str
    forecastWindow: str
    policyShocks: list[SimulationPolicyShockInput] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SimulationScenarioComposeRequest(BaseModel):
    baselineId: str | None = None
    scenarioId: str | None = None
    forecastWindow: str | None = None
    topicId: str
    shockType: str = "funding_boost"
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    coverage: float = Field(default=0.8, ge=0.0, le=1.0)
    lag: int = Field(default=0, ge=0)
    enableSpillover: bool = True
    propagationStrength: float = Field(default=0.45, ge=0.0, le=1.0)
    minSimilarity: float = Field(default=0.35, ge=0.0, le=1.0)
    maxNeighbors: int = Field(default=12, ge=0)
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SimulationRunRequest(BaseModel):
    baseline: SimulationBaselineRequest
    scenario: SimulationScenarioRequest
    includeComparison: bool = True
    includeExplanation: bool = True
    persist: bool = True


def _run_step(step_name: str, fn) -> dict[str, object]:
    code = int(fn())
    if code != 0:
        raise HTTPException(status_code=500, detail=f"{step_name} 执行失败，退出码={code}")
    return {"step": step_name, "code": code, "status": "ok"}


def _build_baseline_topics(payload: SimulationBaselineRequest) -> list[BaselineTopicState]:
    return [
        BaselineTopicState(
            topic_id=item.topicId,
            application_count=item.applicationCount,
            funded_count=item.fundedCount,
            funding_amount=item.fundingAmount,
            score_proxy=item.scoreProxy,
            collaboration_density=item.collaborationDensity,
            topic_centrality=item.topicCentrality,
            migration_strength=item.migrationStrength,
            proxy_risk=item.proxyRisk,
        )
        for item in payload.topics
    ]


def _build_scenario_definition(payload: SimulationScenarioRequest) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id=payload.scenarioId,
        baseline_id=payload.baselineId,
        forecast_window=payload.forecastWindow,
        policy_shocks=[
            PolicyShock(
                shock_id=item.shockId,
                shock_type=item.shockType,
                target_topics=item.targetTopics,
                intensity=item.intensity,
                coverage=item.coverage,
                lag=item.lag,
                parameters=item.parameters,
            )
            for item in payload.policyShocks
        ],
        tags=payload.tags,
        assumptions=payload.assumptions,
    )


def _build_composed_scenario_definition(
    payload: SimulationScenarioComposeRequest,
    *,
    baseline_id: str,
    forecast_window: str,
) -> ScenarioDefinition:
    shock_id = f"shock_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    scenario_id = payload.scenarioId or f"scenario_builder_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    tags = payload.tags or ["builder", "interactive"]
    assumptions = payload.assumptions or ["interactive_builder_generated_policy_shock"]
    parameters: dict[str, object] = {
        "enable_spillover": payload.enableSpillover,
    }
    if payload.enableSpillover:
        parameters.update(
            {
                "propagation_strength": payload.propagationStrength,
                "min_similarity": payload.minSimilarity,
                "max_neighbors": payload.maxNeighbors,
            }
        )

    return ScenarioDefinition(
        scenario_id=scenario_id,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        policy_shocks=[
            PolicyShock(
                shock_id=shock_id,
                shock_type=payload.shockType,
                target_topics=[payload.topicId],
                intensity=payload.intensity,
                coverage=payload.coverage,
                lag=payload.lag,
                parameters=parameters,
            )
        ],
        tags=tags,
        assumptions=assumptions,
    )


def _build_debug_meta(*, source: str, title: str) -> dict[str, str]:
    return {
        "source": source,
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _save_simulation_debug_artifacts(
    *,
    artifact_name: str,
    payload: dict[str, Any],
    title: str,
) -> dict[str, str]:
    SIMULATION_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    json_path = SIMULATION_DEBUG_DIR / f"{artifact_name}.debug.json"
    html_path = SIMULATION_DEBUG_DIR / f"{artifact_name}.debug.html"

    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    html_path.write_text(render_debug_html(payload, title=title), encoding="utf-8")

    return {
        "debug_json_path": str(json_path.resolve()),
        "debug_json_url": f"/debug-sandbox/simulation/{json_path.name}",
        "debug_html_path": str(html_path.resolve()),
        "debug_html_url": f"/debug-sandbox/simulation/{html_path.name}",
    }


def _get_simulation_debug_artifacts(artifact_name: str) -> dict[str, str]:
    json_path = SIMULATION_DEBUG_DIR / f"{artifact_name}.debug.json"
    html_path = SIMULATION_DEBUG_DIR / f"{artifact_name}.debug.html"

    payload: dict[str, str] = {}
    if json_path.exists():
        payload["debug_json_path"] = str(json_path.resolve())
        payload["debug_json_url"] = f"/debug-sandbox/simulation/{json_path.name}"
    if html_path.exists():
        payload["debug_html_path"] = str(html_path.resolve())
        payload["debug_html_url"] = f"/debug-sandbox/simulation/{html_path.name}"
    return payload


def _build_baseline_debug_payload(
    *,
    snapshot,
    source: str,
    title: str,
) -> dict[str, Any]:
    payload = build_debug_payload(baseline=snapshot)
    payload["meta"] = _build_debug_meta(source=source, title=title)
    return payload


def _build_scenario_debug_payload(
    *,
    source: str,
    title: str,
    baseline=None,
    scenario: ScenarioDefinition | None = None,
    result=None,
    comparison=None,
    explanation=None,
) -> dict[str, Any]:
    payload = build_debug_payload(
        baseline=baseline,
        result=result,
        comparison=comparison,
        explanation=explanation,
    )
    if scenario is not None:
        payload["scenario"] = scenario.model_dump(mode="json")
    payload["meta"] = _build_debug_meta(source=source, title=title)
    return payload


def _match_latest_baseline(result) -> object | None:
    baseline = load_latest_baseline_snapshot()
    if baseline is None:
        return None
    if baseline.baseline_id != result.baseline_id:
        return None
    return baseline


def _build_scenario_response(
    *,
    source: str,
    title: str,
    scenario: ScenarioDefinition,
    result,
    baseline=None,
) -> dict[str, object]:
    resolved_baseline = baseline or _match_latest_baseline(result)
    comparison = compare_result(result)
    explanation = explain_result(result)
    debug_payload = _build_scenario_debug_payload(
        baseline=resolved_baseline,
        scenario=scenario,
        result=result,
        comparison=comparison,
        explanation=explanation,
        source=source,
        title=title,
    )
    debug_artifacts = _save_simulation_debug_artifacts(
        artifact_name="scenario_latest",
        payload=debug_payload,
        title=title,
    )
    return {
        "status": "ok",
        "source": source,
        "baseline": resolved_baseline.model_dump() if resolved_baseline is not None else None,
        "scenario": scenario.model_dump(),
        "result": result.model_dump(),
        "comparison": comparison.model_dump(),
        "explanation": explanation.model_dump(),
        **debug_artifacts,
    }


@router.get("/health")
async def sandbox_health() -> dict[str, str]:
    """Sandbox 路由健康检查。"""
    return {"status": "healthy", "service": "sandbox"}


@router.post("/step1/preflight")
async def run_step1_preflight() -> dict[str, object]:
    """执行 Step1：Neo4j + GDS 预检。"""
    from src.services.sandbox.neo4j_gds_preflight import main as step1_main

    return await run_in_threadpool(_run_step, "step1_preflight", step1_main)


@router.post("/step2/hotspot")
async def run_step2_hotspot() -> dict[str, object]:
    """执行 Step2：热点迁移分析。"""
    from src.services.sandbox.hotspot_migration_step2 import main as step2_main

    return await run_in_threadpool(_run_step, "step2_hotspot", step2_main)


@router.post("/step3/insight")
async def run_step3_insight() -> dict[str, object]:
    """执行 Step3：宏观研判规则引擎。"""
    from src.services.sandbox.macro_insight_step3 import main as step3_main

    return await run_in_threadpool(_run_step, "step3_insight", step3_main)


@router.post("/step4/briefing")
async def run_step4_briefing() -> dict[str, object]:
    """执行 Step4：领导简报编排。"""
    from src.services.sandbox.briefing_orchestrator_step4 import main as step4_main

    return await run_in_threadpool(_run_step, "step4_briefing", step4_main)


@router.post("/step5/graphrag")
async def run_step5_graphrag() -> dict[str, object]:
    """执行 Step5：GraphRAG。"""
    from src.services.sandbox.graph_rag_step5 import main as step5_main

    return await run_in_threadpool(_run_step, "step5_graphrag", step5_main)


@router.post("/pipeline/step3-5")
async def run_pipeline_step3_5() -> dict[str, object]:
    """串行执行 Step3 -> Step4 -> Step5。"""
    from src.services.sandbox.macro_insight_step3 import main as step3_main
    from src.services.sandbox.briefing_orchestrator_step4 import main as step4_main
    from src.services.sandbox.graph_rag_step5 import main as step5_main

    result_step3 = await run_in_threadpool(_run_step, "step3_insight", step3_main)
    result_step4 = await run_in_threadpool(_run_step, "step4_briefing", step4_main)
    result_step5 = await run_in_threadpool(_run_step, "step5_graphrag", step5_main)
    return {
        "status": "ok",
        "pipeline": "step3_5",
        "results": [result_step3, result_step4, result_step5],
    }


@router.post("/pipeline/leadership-forecast")
async def run_pipeline_leadership_forecast(payload: LeadershipForecastRequest) -> dict[str, object]:
    """执行 Step2 -> Step5 协同推演，输出领导视角趋势预判。"""
    from src.services.sandbox.leadership_sandbox_orchestrator import run_leadership_sandbox

    try:
        report = await run_in_threadpool(
            run_leadership_sandbox,
            payload.question,
            payload.runPreflight,
            payload.mode,
            payload.forceRefresh,
        )
        return report
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/pipeline/leadership-forecast/latest")
async def get_latest_leadership_forecast() -> dict[str, object]:
    """读取最新一次领导视角推演结果。"""
    from src.services.sandbox.leadership_sandbox_orchestrator import load_latest_leadership_report

    report = await run_in_threadpool(load_latest_leadership_report)
    if not report:
        raise HTTPException(status_code=404, detail="尚未生成领导推演结果")
    return {
        "status": "ok",
        "source": "latest_report",
        "report": report,
    }


@router.get("/simulation/baseline/latest")
async def get_latest_simulation_baseline() -> dict[str, object]:
    """读取最新一次 baseline snapshot。"""
    snapshot = await run_in_threadpool(load_latest_baseline_snapshot)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="尚未生成 baseline snapshot")
    return {
        "status": "ok",
        "source": "latest_baseline_snapshot",
        "baseline": snapshot.model_dump(),
        **_get_simulation_debug_artifacts("baseline_latest"),
    }


@router.post("/simulation/baseline")
async def run_simulation_baseline(payload: SimulationBaselineRequest) -> dict[str, object]:
    """执行一次 baseline snapshot 生成。"""
    topics = _build_baseline_topics(payload)
    snapshot = await run_in_threadpool(
        create_baseline_snapshot,
        baseline_id=payload.baselineId,
        forecast_window=payload.forecastWindow,
        topics=topics,
        assumptions=payload.assumptions,
        metadata=payload.metadata,
    )
    debug_payload = _build_baseline_debug_payload(
        snapshot=snapshot,
        source="create_baseline_snapshot",
        title="Sandbox Simulation Baseline Debug",
    )
    debug_artifacts = _save_simulation_debug_artifacts(
        artifact_name="baseline_latest",
        payload=debug_payload,
        title="Sandbox Simulation Baseline Debug",
    )

    return {
        "status": "ok",
        "source": "create_baseline_snapshot",
        "baseline": snapshot.model_dump(),
        **debug_artifacts,
    }


@router.post("/simulation/baseline/build")
async def build_simulation_baseline(payload: SimulationBaselineBuildRequest) -> dict[str, object]:
    """从项目库与图谱构建一次真实 baseline snapshot。"""
    try:
        snapshot = await run_in_threadpool(
            build_baseline_snapshot_from_sources,
            baseline_id=payload.baselineId,
            start_year=payload.startYear,
            end_year=payload.endYear,
            persist=payload.persist,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    debug_artifacts: dict[str, str] = {}
    if payload.persist:
        debug_payload = _build_baseline_debug_payload(
            snapshot=snapshot,
            source="build_baseline_snapshot_from_sources",
            title="Sandbox Simulation Baseline Debug",
        )
        debug_artifacts = _save_simulation_debug_artifacts(
            artifact_name="baseline_latest",
            payload=debug_payload,
            title="Sandbox Simulation Baseline Debug",
        )

    return {
        "status": "ok",
        "source": "build_baseline_snapshot_from_sources",
        "baseline": snapshot.model_dump(),
        **debug_artifacts,
    }


@router.post("/simulation/run")
async def run_simulation(payload: SimulationRunRequest) -> dict[str, object]:
    """执行一次完整 simulation run，并可附带 comparison/explanation。"""
    if payload.baseline.baselineId != payload.scenario.baselineId:
        raise HTTPException(status_code=400, detail="baselineId 与 scenario.baselineId 不一致")

    baseline = await run_in_threadpool(
        create_baseline_snapshot,
        baseline_id=payload.baseline.baselineId,
        forecast_window=payload.baseline.forecastWindow,
        topics=_build_baseline_topics(payload.baseline),
        assumptions=payload.baseline.assumptions,
        metadata=payload.baseline.metadata,
        persist=payload.persist,
    )

    try:
        result = await run_in_threadpool(
            run_scenario,
            scenario=_build_scenario_definition(payload.scenario),
            baseline=baseline,
            persist=payload.persist,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response: dict[str, object] = {
        "status": "ok",
        "source": "run_simulation",
        "baseline": baseline.model_dump(),
        "result": result.model_dump(),
    }
    comparison = None
    if payload.includeComparison:
        comparison = await run_in_threadpool(compare_result, result)
        response["comparison"] = comparison.model_dump()
    explanation = None
    if payload.includeExplanation:
        explanation = await run_in_threadpool(explain_result, result)
        response["explanation"] = explanation.model_dump()
    if payload.persist:
        scenario = _build_scenario_definition(payload.scenario)
        debug_payload = _build_scenario_debug_payload(
            baseline=baseline,
            scenario=scenario,
            result=result,
            comparison=comparison,
            explanation=explanation,
            source="run_simulation",
            title="Sandbox Simulation Scenario Debug",
        )
        response.update(
            _save_simulation_debug_artifacts(
                artifact_name="scenario_latest",
                payload=debug_payload,
                title="Sandbox Simulation Scenario Debug",
            )
        )
    return response


@router.get("/simulation/scenario/latest")
async def get_latest_simulation_scenario() -> dict[str, object]:
    """读取最新一次 scenario result。"""
    result = await run_in_threadpool(load_latest_scenario_result)
    if result is None:
        raise HTTPException(status_code=404, detail="尚未生成 scenario result")
    return {
        "status": "ok",
        "source": "latest_scenario_result",
        "result": result.model_dump(),
        **_get_simulation_debug_artifacts("scenario_latest"),
    }


@router.get("/simulation/scenario/latest/compare")
async def compare_latest_simulation_scenario() -> dict[str, object]:
    """比较最新一次 scenario 与 baseline 的结构变化。"""
    comparison = await run_in_threadpool(compare_latest_result)
    if comparison is None:
        raise HTTPException(status_code=404, detail="尚未生成 scenario result")
    return {
        "status": "ok",
        "source": "latest_scenario_comparison",
        "comparison": comparison.model_dump(),
    }


@router.get("/simulation/scenario/latest/explain")
async def explain_latest_simulation_scenario() -> dict[str, object]:
    """解释最新一次 scenario 的关键变化原因。"""
    explanation = await run_in_threadpool(explain_latest_result)
    if explanation is None:
        raise HTTPException(status_code=404, detail="尚未生成 scenario result")
    return {
        "status": "ok",
        "source": "latest_scenario_explanation",
        "explanation": explanation.model_dump(),
    }


@router.post("/simulation/scenario")
async def run_simulation_scenario(payload: SimulationScenarioRequest) -> dict[str, object]:
    """执行一次原生 policy scenario 推演。"""
    scenario = _build_scenario_definition(payload)

    try:
        result = await run_in_threadpool(
            run_scenario,
            scenario=scenario,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return await run_in_threadpool(
        _build_scenario_response,
        source="run_scenario",
        title="Sandbox Simulation Scenario Debug",
        scenario=scenario,
        result=result,
    )


@router.post("/simulation/scenario/compose")
async def compose_simulation_scenario(payload: SimulationScenarioComposeRequest) -> dict[str, object]:
    """用领导可选控件快速拼装一个 scenario，并直接执行推演。"""
    baseline = await run_in_threadpool(load_latest_baseline_snapshot)
    if baseline is None:
        raise HTTPException(status_code=404, detail="尚未生成 baseline snapshot，无法编排方案")

    baseline_id = payload.baselineId or baseline.baseline_id
    if baseline_id != baseline.baseline_id:
        raise HTTPException(status_code=400, detail="baselineId 与当前最新 baseline 不一致")

    forecast_window = payload.forecastWindow or baseline.forecast_window
    scenario = _build_composed_scenario_definition(
        payload,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
    )

    try:
        result = await run_in_threadpool(
            run_scenario,
            scenario=scenario,
            baseline=baseline,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return await run_in_threadpool(
        _build_scenario_response,
        source="compose_simulation_scenario",
        title="Sandbox Simulation Scenario Debug",
        scenario=scenario,
        result=result,
        baseline=baseline,
    )
