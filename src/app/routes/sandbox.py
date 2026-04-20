"""Sandbox 研发链路 API 路由。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.common.models.simulation import (
    BaselineTopicState,
    EvaluationGoal,
    PolicyAction,
    PolicyShock,
    ScenarioConstraint,
    ScenarioContract,
    ScenarioDefinition,
    ScenarioIntent,
    ValidationSummary,
)
from src.services.sandbox.simulation import repository as simulation_repository
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
    run_scenario_contract,
)
from src.services.sandbox.simulation.llm_contract import draft_scenario_contract_from_prompt
from src.services.sandbox.simulation.scenario_compiler import compile_scenario_contract
from src.services.sandbox.simulation.scenario_contract import (
    adapt_legacy_compose_to_contract,
    adapt_legacy_policy_shocks_to_contract,
    build_compose_constraints,
    build_scenario_contract,
)

router = APIRouter()


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
    baselineId: str = "baseline_real_2020_latest"
    startYear: int | None = None
    endYear: int | None = None
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
    scenarioName: str | None = None
    forecastWindow: str | None = None
    question: str | None = None
    rawPolicyText: str | None = None
    scenarioContract: dict[str, object] | None = None
    topicId: str | None = None
    shockType: str = "funding_boost"
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    coverage: float = Field(default=0.8, ge=0.0, le=1.0)
    lag: int = Field(default=0, ge=0)
    enableSpillover: bool = True
    propagationStrength: float = Field(default=0.45, ge=0.0, le=1.0)
    minSimilarity: float = Field(default=0.35, ge=0.0, le=1.0)
    maxNeighbors: int = Field(default=12, ge=0)
    actions: list[SimulationPolicyShockInput] = Field(default_factory=list)
    budgetLimit: float | None = Field(default=None, ge=0.0)
    spilloverBudgetShare: float | None = Field(default=None, ge=0.0, le=1.0)
    maxRiskIncrease: float | None = Field(default=None, ge=0.0, le=1.0)
    constraints: list[dict[str, object]] = Field(default_factory=list)
    evaluationGoals: list[dict[str, object]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SimulationRunRequest(BaseModel):
    baseline: SimulationBaselineRequest | None = None
    scenario: SimulationScenarioRequest | None = None
    baselineId: str | None = None
    scenarioContract: dict[str, object] | None = None
    question: str | None = None
    includeComparison: bool = True
    includeExplanation: bool = True
    compareToBaseline: bool = True
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
            topic_label=item.topicId,
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
    resolved_topic_ids: list[str] | None = None,
) -> ScenarioDefinition:
    scenario_id = payload.scenarioId or f"scenario_builder_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    tags = payload.tags or ["builder", "interactive"]
    assumptions = payload.assumptions or ["interactive_builder_generated_policy_shock"]
    actions = payload.actions or _compose_request_actions(payload, resolved_topic_ids=resolved_topic_ids)

    return ScenarioDefinition(
        scenario_id=scenario_id,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        policy_shocks=[
            _compose_action_to_policy_shock(
                action,
                index=index,
                budget_limit=payload.budgetLimit,
                spillover_budget_share=payload.spilloverBudgetShare,
                max_risk_increase=payload.maxRiskIncrease,
            )
            for index, action in enumerate(actions, start=1)
        ],
        tags=tags,
        assumptions=assumptions,
    )


def _compose_request_actions(
    payload: SimulationScenarioComposeRequest,
    *,
    resolved_topic_ids: list[str] | None = None,
) -> list[SimulationPolicyShockInput]:
    if not payload.topicId:
        raise HTTPException(status_code=400, detail="组合方案缺少 topicId 或 actions")
    return [
        SimulationPolicyShockInput(
            shockId=f"shock_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            shockType=payload.shockType,
            targetTopics=resolved_topic_ids or [payload.topicId],
            intensity=payload.intensity,
            coverage=payload.coverage,
            lag=payload.lag,
            parameters={
                "enable_spillover": payload.enableSpillover,
                **(
                    {
                        "propagation_strength": payload.propagationStrength,
                        "min_similarity": payload.minSimilarity,
                        "max_neighbors": payload.maxNeighbors,
                    }
                    if payload.enableSpillover
                    else {}
                ),
            },
        )
    ]


def _compose_action_to_policy_shock(
    action: SimulationPolicyShockInput,
    *,
    index: int,
    budget_limit: float | None,
    spillover_budget_share: float | None,
    max_risk_increase: float | None,
) -> PolicyShock:
    parameters = dict(action.parameters)
    if budget_limit is not None and "budget_limit" not in parameters:
        parameters["budget_limit"] = budget_limit
    if spillover_budget_share is not None and "spillover_budget_share" not in parameters:
        parameters["spillover_budget_share"] = spillover_budget_share
    if max_risk_increase is not None and "max_risk_increase" not in parameters:
        parameters["max_risk_increase"] = max_risk_increase
    shock_id = action.shockId or f"shock_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{index}"
    return PolicyShock(
        shock_id=shock_id,
        shock_type=action.shockType,
        target_topics=action.targetTopics,
        intensity=action.intensity,
        coverage=action.coverage,
        lag=action.lag,
        parameters=parameters,
    )


def _resolve_topic_targets(selection: str | None, baseline) -> list[str] | None:
    if not selection:
        return None

    topics = list(getattr(baseline, "topics", []) or [])
    exact_ids = [topic.topic_id for topic in topics if topic.topic_id == selection]
    if exact_ids:
        return exact_ids

    matching_labels = [
        topic.topic_id
        for topic in topics
        if _baseline_topic_label(topic) == selection
    ]
    return matching_labels or None


def _baseline_topic_label(topic: BaselineTopicState) -> str:
    label = str(topic.topic_label or "").strip()
    if label:
        return label
    topic_id = str(topic.topic_id or "").strip()
    if "-" not in topic_id:
        return topic_id
    prefix, remainder = topic_id.split("-", 1)
    if prefix and remainder and len(prefix.replace("_", "")) >= 6 and prefix.isascii() and prefix.replace("_", "").isalnum():
        return remainder.strip()
    return topic_id


def _default_scenario_forecast_window(baseline) -> str:
    metadata = getattr(baseline, "metadata", {}) or {}
    end_year = metadata.get("endYear")
    if isinstance(end_year, int):
        return str(end_year)
    baseline_window = str(getattr(baseline, "forecast_window", "") or "").strip()
    if baseline_window.isdigit():
        return baseline_window
    if "-" in baseline_window:
        tail = baseline_window.split("-")[-1].strip()
        if tail.isdigit():
            return tail
    return baseline_window or "当前窗口"


def _extract_model_debug_artifacts(model) -> dict[str, str]:
    metadata = getattr(model, "metadata", {}) or {}
    debug_artifacts = metadata.get("debugArtifacts")
    if not isinstance(debug_artifacts, dict):
        return {}
    extracted: dict[str, str] = {}
    for key in ("debug_json_path", "debug_json_url", "debug_html_path", "debug_html_url"):
        value = debug_artifacts.get(key)
        if isinstance(value, str) and value:
            extracted[key] = value
    return extracted


def _build_scenario_response(
    *,
    source: str,
    scenario: ScenarioDefinition,
    result,
    baseline=None,
) -> dict[str, object]:
    comparison = compare_result(result)
    explanation = explain_result(result)
    return {
        "status": "ok",
        "source": source,
        "baseline": baseline.model_dump() if baseline is not None else None,
        "scenario": scenario.model_dump(),
        "result": result.model_dump(),
        "comparison": comparison.model_dump(),
        "explanation": explanation.model_dump(),
        **_extract_model_debug_artifacts(result),
    }


def _load_required_baseline(*, expected_baseline_id: str | None = None):
    baseline = load_latest_baseline_snapshot()
    if baseline is None:
        raise HTTPException(status_code=404, detail="尚未生成 baseline snapshot，无法执行正式 scenario contract")
    if expected_baseline_id is not None and expected_baseline_id != baseline.baseline_id:
        raise HTTPException(status_code=400, detail="baselineId 与当前可用 baseline 不一致")
    return baseline


def _parse_extra_constraints(payload: SimulationScenarioComposeRequest) -> list[ScenarioConstraint]:
    constraints = build_compose_constraints(
        budget_limit=payload.budgetLimit,
        spillover_budget_share=payload.spilloverBudgetShare,
        max_risk_increase=payload.maxRiskIncrease,
    )
    constraints.extend(ScenarioConstraint.model_validate(item) for item in payload.constraints)
    return constraints


def _parse_evaluation_goals(payload: SimulationScenarioComposeRequest) -> list[EvaluationGoal]:
    return [EvaluationGoal.model_validate(item) for item in payload.evaluationGoals]


def _normalize_contract(
    contract: ScenarioContract,
    *,
    baseline,
    forecast_window: str | None = None,
    question: str | None = None,
    scenario_name: str | None = None,
    tags: list[str] | None = None,
    assumptions: list[str] | None = None,
    constraints: list[ScenarioConstraint] | None = None,
    evaluation_goals: list[EvaluationGoal] | None = None,
) -> ScenarioContract:
    resolved_forecast_window = forecast_window or contract.forecast_window or _default_scenario_forecast_window(baseline)
    resolved_question = (question or "").strip()
    intent = contract.intent or ScenarioIntent()
    if resolved_question and not intent.question:
        intent = intent.model_copy(update={"question": resolved_question})

    merged_constraints = list(contract.constraints)
    if constraints:
        merged_constraints.extend(constraints)
    merged_goals = list(contract.evaluation_goals) or []
    if evaluation_goals:
        merged_goals.extend(evaluation_goals)
    validation = contract.validation or ValidationSummary()

    return contract.model_copy(
        update={
            "scenario_name": scenario_name or contract.scenario_name,
            "forecast_window": resolved_forecast_window,
            "baseline": contract.baseline.model_copy(
                update={
                    "baseline_id": contract.baseline.baseline_id or baseline.baseline_id,
                }
            ),
            "intent": intent,
            "tags": list(contract.tags) or list(tags or []),
            "assumptions": list(contract.assumptions) or list(assumptions or []),
            "constraints": merged_constraints,
            "evaluation_goals": merged_goals,
            "validation": validation,
        }
    )


def _build_contract_from_compose_request(
    payload: SimulationScenarioComposeRequest,
    *,
    baseline,
) -> ScenarioContract:
    forecast_window = payload.forecastWindow or _default_scenario_forecast_window(baseline)
    question = (payload.question or payload.rawPolicyText or "").strip()
    extra_constraints = _parse_extra_constraints(payload)
    evaluation_goals = _parse_evaluation_goals(payload)
    resolved_topic_ids = _resolve_topic_targets(payload.topicId, baseline) if payload.topicId else None

    if payload.scenarioContract is not None:
        contract = ScenarioContract.model_validate(payload.scenarioContract)
        return _normalize_contract(
            contract,
            baseline=baseline,
            forecast_window=forecast_window,
            question=question,
            scenario_name=payload.scenarioName,
            tags=payload.tags,
            assumptions=payload.assumptions,
            constraints=extra_constraints,
            evaluation_goals=evaluation_goals,
        )

    if question and not payload.topicId and not payload.actions:
        draft = draft_scenario_contract_from_prompt(
            question,
            baseline_id=baseline.baseline_id,
            forecast_window=forecast_window,
            scenario_id=payload.scenarioId,
        )
        contract = adapt_legacy_policy_shocks_to_contract(
            scenario_id=draft.scenario_id,
            baseline_id=baseline.baseline_id,
            forecast_window=draft.forecast_window,
            policy_shocks=[item.model_dump(mode="json") for item in draft.policy_package],
            tags=payload.tags,
            assumptions=list(payload.assumptions) + list(draft.assumptions),
            metadata={
                "draft_objective": draft.objective,
                "draft_summary": draft.summary,
                "draft_warnings": list(draft.warnings),
                "draft_generation_mode": draft.metadata.get("generationMode"),
            },
        )
        return _normalize_contract(
            contract,
            baseline=baseline,
            forecast_window=forecast_window,
            question=question,
            scenario_name=payload.scenarioName or draft.summary or draft.objective,
            tags=payload.tags,
            assumptions=list(payload.assumptions) + list(draft.assumptions),
            constraints=extra_constraints,
            evaluation_goals=evaluation_goals,
        )

    contract = adapt_legacy_compose_to_contract(
        scenario_id=payload.scenarioId or f"scenario_builder_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        baseline_id=baseline.baseline_id,
        forecast_window=forecast_window,
        topic_id=(
            resolved_topic_ids[0]
            if resolved_topic_ids and len(resolved_topic_ids) == 1
            else (None if resolved_topic_ids and len(resolved_topic_ids) > 1 else payload.topicId)
        ),
        shock_type=payload.shockType,
        intensity=payload.intensity,
        coverage=payload.coverage,
        lag=payload.lag,
        enable_spillover=payload.enableSpillover,
        propagation_strength=payload.propagationStrength,
        min_similarity=payload.minSimilarity,
        max_neighbors=payload.maxNeighbors,
        actions=(
            [
                {
                    "action_id": item.shockId,
                    "action_type": item.shockType,
                    "target_topics": list(item.targetTopics),
                    "intensity": item.intensity,
                    "coverage": item.coverage,
                    "lag": item.lag,
                    "parameters": dict(item.parameters),
                }
                for item in payload.actions
            ]
            if payload.actions
            else (
                [
                    {
                        "action_id": "action_legacy_compose",
                        "action_type": payload.shockType,
                        "target_topics": resolved_topic_ids,
                        "intensity": payload.intensity,
                        "coverage": payload.coverage,
                        "lag": payload.lag,
                        "parameters": {
                            "enable_spillover": payload.enableSpillover,
                            **(
                                {
                                    "propagation_strength": payload.propagationStrength,
                                    "min_similarity": payload.minSimilarity,
                                    "max_neighbors": payload.maxNeighbors,
                                }
                                if payload.enableSpillover
                                else {}
                            ),
                        },
                    }
                ]
                if resolved_topic_ids and len(resolved_topic_ids) > 1
                else None
            )
        ),
        constraints=extra_constraints,
        tags=payload.tags,
        assumptions=payload.assumptions,
        metadata={"compose_mode": "legacy_compatible"},
    )
    return _normalize_contract(
        contract,
        baseline=baseline,
        forecast_window=forecast_window,
        question=question,
        scenario_name=payload.scenarioName,
        tags=payload.tags,
        assumptions=payload.assumptions,
        constraints=extra_constraints,
        evaluation_goals=evaluation_goals,
    )


def _build_stage_impacts(result) -> list[dict[str, object]]:
    frames = list(getattr(result, "simulation_frames", []) or [])
    return [
        {
            "stage_id": frame.stage_id,
            "stage_label": frame.stage_label,
            "stage_order": frame.stage_order,
            "narrative": frame.narrative,
            "portfolio": frame.portfolio.model_dump(),
            "topic_count": len(frame.topics),
            "top_topics": [topic.model_dump() for topic in frame.topics[:5]],
        }
        for frame in frames
    ]


def _build_formal_simulation_response(
    *,
    source: str,
    baseline,
    contract: ScenarioContract,
    compiled,
    result,
    include_comparison: bool = True,
    include_explanation: bool = True,
    persist_debug_artifacts: bool = True,
) -> dict[str, object]:
    comparison = compare_result(result) if include_comparison else None
    explanation = explain_result(result) if include_explanation else None
    portfolio_assessment: dict[str, Any] | None = None
    if comparison is not None:
        metadata = comparison.metadata if isinstance(comparison.metadata, dict) else {}
        portfolio_assessment = metadata.get("managementSummary") if isinstance(metadata.get("managementSummary"), dict) else {}

    debug_artifacts: dict[str, str] = {}
    if persist_debug_artifacts:
        debug_artifacts = simulation_repository.save_scenario_debug_artifacts(
            result,
            baseline=baseline,
            scenario=compiled.scenario_definition,
            comparison=comparison,
            explanation=explanation,
            contract=contract,
            compiled=compiled,
        )

    return {
        "status": "ok",
        "source": source,
        "baseline": baseline.model_dump() if baseline is not None else None,
        "scenario_contract": contract.model_dump(),
        "compiled": compiled.model_dump(),
        "scenario": compiled.scenario_definition.model_dump(),
        "result": result.model_dump(),
        "comparison": comparison.model_dump() if comparison is not None else None,
        "explanation": explanation.model_dump() if explanation is not None else None,
        "stage_impacts": _build_stage_impacts(result),
        "counterfactual_comparison": comparison.model_dump() if comparison is not None else None,
        "portfolio_assessment": portfolio_assessment or {},
        "disclosures": [item.model_dump() for item in compiled.disclosures],
        **(_extract_model_debug_artifacts(result) if persist_debug_artifacts else {}),
        **debug_artifacts,
    }


def _build_contract_validation(contract: ScenarioContract, compiled) -> dict[str, object]:
    issues = [item.message for item in compiled.disclosures if item.severity == "error"]
    warnings = [item.message for item in compiled.disclosures if item.severity != "error"]
    return {
        "scenario_id": contract.scenario_id,
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "suggestions": [],
        "metadata": {
            "mode": "local_contract_validation",
            "support_level": compiled.support_level,
        },
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
        **(_extract_model_debug_artifacts(snapshot) or simulation_repository.get_baseline_debug_artifacts()),
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

    return {
        "status": "ok",
        "source": "create_baseline_snapshot",
        "baseline": snapshot.model_dump(),
        **_extract_model_debug_artifacts(snapshot),
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
        debug_artifacts = _extract_model_debug_artifacts(snapshot)

    return {
        "status": "ok",
        "source": "build_baseline_snapshot_from_sources",
        "baseline": snapshot.model_dump(),
        **debug_artifacts,
    }


@router.post("/simulation/run")
async def run_simulation(payload: SimulationRunRequest) -> dict[str, object]:
    """执行一次完整 simulation run，并可附带 comparison/explanation。"""
    if payload.scenarioContract is not None:
        baseline = await run_in_threadpool(_load_required_baseline, expected_baseline_id=payload.baselineId)
        contract = await run_in_threadpool(
            _normalize_contract,
            ScenarioContract.model_validate(payload.scenarioContract),
            baseline=baseline,
            question=payload.question,
        )
        try:
            bundle = await run_in_threadpool(
                run_scenario_contract,
                contract=contract,
                baseline=baseline,
                persist=payload.persist,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return await run_in_threadpool(
            _build_formal_simulation_response,
            source="run_simulation_contract",
            baseline=bundle.baseline,
            contract=bundle.compiled.contract,
            compiled=bundle.compiled,
            result=bundle.result,
            include_comparison=payload.includeComparison,
            include_explanation=payload.includeExplanation,
            persist_debug_artifacts=payload.persist,
        )

    if payload.baseline is None or payload.scenario is None:
        raise HTTPException(status_code=400, detail="缺少 baseline/scenario 或 scenarioContract")
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
            require_supported_baseline=False,
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
        response.update(_extract_model_debug_artifacts(result))
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
        **(_extract_model_debug_artifacts(result) or simulation_repository.get_scenario_debug_artifacts()),
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
        scenario=scenario,
        result=result,
    )


@router.post("/simulation/scenario/compose")
async def compose_simulation_scenario(payload: SimulationScenarioComposeRequest) -> dict[str, object]:
    """拼装正式 Scenario Contract，并兼容旧 compose 参数直接执行推演。"""
    baseline = await run_in_threadpool(_load_required_baseline, expected_baseline_id=payload.baselineId)
    if payload.topicId:
        resolved_topic_ids = _resolve_topic_targets(payload.topicId, baseline)
        if not resolved_topic_ids:
            raise HTTPException(status_code=400, detail="topicId 未匹配到当前 baseline 中的主题")

    contract = await run_in_threadpool(
        _build_contract_from_compose_request,
        payload,
        baseline=baseline,
    )
    compiled = await run_in_threadpool(compile_scenario_contract, contract, baseline=baseline)

    try:
        result = await run_in_threadpool(
            run_scenario,
            scenario=compiled.scenario_definition,
            baseline=baseline,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response = await run_in_threadpool(
        _build_formal_simulation_response,
        source="compose_simulation_scenario",
        baseline=baseline,
        contract=contract,
        compiled=compiled,
        result=result,
        persist_debug_artifacts=True,
    )
    response["validation"] = _build_contract_validation(contract, compiled)
    response["normalization_notes"] = [item["message"] for item in response["disclosures"]]
    return response
