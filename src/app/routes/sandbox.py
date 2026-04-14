"""Sandbox 研发链路 API 路由。"""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.common.models.simulation import BaselineTopicState, PolicyShock, ScenarioDefinition
from src.services.sandbox.simulation.facade import (
    create_baseline_snapshot,
    load_latest_baseline_snapshot,
    load_latest_scenario_result,
    run_scenario,
)

router = APIRouter()


class LeadershipForecastRequest(BaseModel):
    question: str | None = None
    runPreflight: bool = False
    mode: str = "quick"
    forceRefresh: bool = False


class SimulationTopicInput(BaseModel):
    topicId: str
    topicShare: float
    conversionRate: float
    riskScore: float
    momentumScore: float = 0.5


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


class SimulationScenarioRequest(BaseModel):
    scenarioId: str
    baselineId: str
    forecastWindow: str
    policyShocks: list[SimulationPolicyShockInput] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def _run_step(step_name: str, fn) -> dict[str, object]:
    code = int(fn())
    if code != 0:
        raise HTTPException(status_code=500, detail=f"{step_name} 执行失败，退出码={code}")
    return {"step": step_name, "code": code, "status": "ok"}


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
    }


@router.post("/simulation/baseline")
async def run_simulation_baseline(payload: SimulationBaselineRequest) -> dict[str, object]:
    """执行一次 baseline snapshot 生成。"""
    topics = [
        BaselineTopicState(
            topic_id=item.topicId,
            topic_share=item.topicShare,
            conversion_rate=item.conversionRate,
            risk_score=item.riskScore,
            momentum_score=item.momentumScore,
        )
        for item in payload.topics
    ]
    snapshot = await run_in_threadpool(
        create_baseline_snapshot,
        baseline_id=payload.baselineId,
        forecast_window=payload.forecastWindow,
        topics=topics,
        assumptions=payload.assumptions,
        metadata=payload.metadata,
    )

    return {
        "status": "ok",
        "source": "create_baseline_snapshot",
        "baseline": snapshot.model_dump(),
    }


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
    }


@router.post("/simulation/scenario")
async def run_simulation_scenario(payload: SimulationScenarioRequest) -> dict[str, object]:
    """执行一次原生 policy scenario 推演。"""
    scenario = ScenarioDefinition(
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

    try:
        result = await run_in_threadpool(
            run_scenario,
            scenario=scenario,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "ok",
        "source": "run_scenario",
        "result": result.model_dump(),
    }
