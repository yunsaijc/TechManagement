"""Shared sandbox simulation and scenario models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SandboxModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BaselineTopicState(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    application_count: int = Field(ge=0)
    funded_count: int = Field(ge=0)
    funding_amount: float = Field(ge=0.0)
    requested_funding_amount: float = Field(default=0.0, ge=0.0)
    score_proxy: float | None = None
    funded_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_funding_per_award: float = Field(default=0.0, ge=0.0)
    growth_momentum: float = Field(default=0.0, ge=-1.0, le=1.0)
    recent_share: float = Field(default=0.0, ge=0.0, le=1.0)
    collaboration_density: float = Field(default=0.0, ge=0.0, le=1.0)
    topic_centrality: float = Field(default=0.0, ge=0.0, le=1.0)
    migration_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    proxy_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class BaselineSnapshot(SandboxModel):
    baseline_id: str
    forecast_window: str
    topics: list[BaselineTopicState] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyShock(SandboxModel):
    shock_id: str
    shock_type: str
    target_topics: list[str] = Field(default_factory=list)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    lag: int = Field(default=0, ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioConstraints(SandboxModel):
    budget_limit: float | None = Field(default=None, ge=0.0)
    spillover_budget_share: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_risk_increase: float | None = Field(default=None, ge=0.0, le=1.0)


class ScenarioIntent(SandboxModel):
    question: str = ""
    decision_context: str = ""
    intent_id: str | None = None
    policy_problem: str | None = None
    desired_outcome: str | None = None
    narrative: str | None = None
    owner: str | None = None


class BaselineScope(SandboxModel):
    baseline_id: str | None = None
    anchor_year: int | None = Field(default=None, ge=1900, le=2100)
    forecast_years: list[int] = Field(default_factory=list)
    topic_scope: list[str] = Field(default_factory=list)
    program_scope: list[str] = Field(default_factory=list)
    population_scope: str = ""
    topic_ids: list[str] = Field(default_factory=list)
    topic_labels: list[str] = Field(default_factory=list)
    cohort: str | None = None
    metadata_filters: dict[str, Any] = Field(default_factory=dict)


class TargetScope(SandboxModel):
    topic_ids: list[str] = Field(default_factory=list)
    topic_labels: list[str] = Field(default_factory=list)
    guide_ids: list[str] = Field(default_factory=list)
    guide_labels: list[str] = Field(default_factory=list)
    program_ids: list[str] = Field(default_factory=list)
    institution_ids: list[str] = Field(default_factory=list)
    institution_labels: list[str] = Field(default_factory=list)
    enable_spillover: bool = False
    propagation_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    max_neighbors: int | None = Field(default=None, ge=0)


class PolicyRule(SandboxModel):
    operator: str | None = None
    operation: str | None = None
    metric: str | None = None
    value: float | int | str | bool | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class PolicyAction(SandboxModel):
    action_id: str
    action_type: str
    target_scope: TargetScope = Field(default_factory=TargetScope)
    basis_document_ids: list[str] = Field(default_factory=list)
    stage: str | None = None
    rule: PolicyRule | None = None
    effective_window: dict[str, int] = Field(default_factory=dict)
    support_level: str = "proxy_supported"
    evidence_requirement: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    lag: int = Field(default=0, ge=0)
    rules: list[PolicyRule] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioConstraint(SandboxModel):
    constraint_type: str
    basis_document_ids: list[str] = Field(default_factory=list)
    operator: str = "hold"
    value: Any = None
    hard_limit: bool = False
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioConstraintItem(ScenarioConstraint):
    """Backward-compatible alias for older contract payloads."""


class EvaluationGoal(SandboxModel):
    metric: str
    direction: str
    target_value: float | int | None = None
    weight: float = Field(default=1.0, ge=0.0)
    goal_id: str | None = None
    description: str | None = None
    notes: str = ""


class ValidationSummary(SandboxModel):
    observed_metrics: list[str] = Field(default_factory=list)
    proxy_metrics: list[str] = Field(default_factory=list)
    structural_assumptions: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


class ValidationDisclosure(SandboxModel):
    code: str
    severity: Literal["info", "warning", "error"] = "info"
    message: str
    field_path: str | None = None


class BasisDocumentRef(SandboxModel):
    document_id: str = ""
    document_type: str = ""
    title: str = ""
    publish_date: str | None = None
    source_system: str | None = None
    support_scope: list[str] = Field(default_factory=list)
    link_keys: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ScenarioContract(SandboxModel):
    scenario_id: str
    forecast_window: str = ""
    scenario_name: str = ""
    baseline: BaselineScope = Field(
        default_factory=BaselineScope,
        validation_alias=AliasChoices("baseline", "baseline_scope"),
    )
    intent: ScenarioIntent | None = Field(default_factory=ScenarioIntent)
    basis_documents: list[BasisDocumentRef] = Field(default_factory=list)
    actions: list[PolicyAction] = Field(
        default_factory=list,
        validation_alias=AliasChoices("actions", "policy_package"),
    )
    constraints: list[ScenarioConstraint] = Field(default_factory=list)
    evaluation_goals: list[EvaluationGoal] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validation: ValidationSummary = Field(default_factory=ValidationSummary)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompiledPolicyAction(SandboxModel):
    action_id: str
    action_type: str
    stage: str | None = None
    support_level: str = "proxy_supported"
    basis_document_ids: list[str] = Field(default_factory=list)
    resolved_topic_ids: list[str] = Field(default_factory=list)
    resolved_topic_labels: list[str] = Field(default_factory=list)
    rule: PolicyRule | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    compiled_guardrails: dict[str, Any] = Field(default_factory=dict)
    evidence_requirement: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScenarioDefinition(SandboxModel):
    scenario_id: str
    baseline_id: str
    forecast_window: str
    policy_shocks: list[PolicyShock] = Field(default_factory=list)
    constraints: ScenarioConstraints | None = None
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompiledScenario(SandboxModel):
    contract: ScenarioContract
    scenario_definition: ScenarioDefinition
    support_level: Literal["supported", "legacy_compatible", "partial", "unsupported"] = "supported"
    disclosures: list[ValidationDisclosure] = Field(default_factory=list)
    baseline_topic_ids: list[str] = Field(default_factory=list)
    action_target_topic_ids: dict[str, list[str]] = Field(default_factory=dict)
    basis_document_ids: list[str] = Field(default_factory=list)
    compiled_actions: list[CompiledPolicyAction] = Field(default_factory=list)


class SimulationTopicImpact(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    forecast_window: str
    baseline_application_count: int
    projected_application_count: int
    delta_application_count: int
    baseline_funded_count: int
    projected_funded_count: int
    delta_funded_count: int
    baseline_funding_amount: float
    projected_funding_amount: float
    delta_funding_amount: float
    baseline_score_proxy: float | None = None
    projected_score_proxy: float | None = None
    delta_score_proxy: float | None = None
    baseline_collaboration_density: float
    projected_collaboration_density: float
    delta_collaboration_density: float
    baseline_topic_centrality: float
    projected_topic_centrality: float
    delta_topic_centrality: float
    baseline_migration_strength: float
    projected_migration_strength: float
    delta_migration_strength: float
    baseline_proxy_risk: float
    projected_proxy_risk: float
    delta_proxy_risk: float
    applied_shocks: list[str] = Field(default_factory=list)
    direct_shocks: list[str] = Field(default_factory=list)
    spillover_shocks: list[str] = Field(default_factory=list)
    impact_origin: str = "none"


class SimulationReplayTopic(SimulationTopicImpact):
    active_constraints: list[str] = Field(default_factory=list)


class SimulationReplayPortfolio(SandboxModel):
    topic_count: int = Field(ge=0)
    impacted_topic_count: int = Field(ge=0)
    positive_funding_topic_count: int = Field(ge=0)
    negative_funding_topic_count: int = Field(ge=0)
    positive_risk_topic_count: int = Field(ge=0)
    net_delta_funding_amount: float = 0.0
    net_delta_funded_count: int = 0
    avg_delta_proxy_risk: float = 0.0
    direct_topic_count: int = Field(ge=0)
    spillover_topic_count: int = Field(ge=0)
    mixed_topic_count: int = Field(ge=0)
    constrained_topic_count: int = Field(ge=0)


class SimulationReplayFrame(SandboxModel):
    stage_id: str
    stage_label: str
    stage_order: int = Field(ge=0)
    narrative: str
    portfolio: SimulationReplayPortfolio
    topics: list[SimulationReplayTopic] = Field(default_factory=list)


class SimulationStageTopicState(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    application_count: int = Field(default=0, ge=0)
    funded_count: int = Field(default=0, ge=0)
    funding_amount: float = Field(default=0.0, ge=0.0)
    requested_funding_amount: float = Field(default=0.0, ge=0.0)
    score_proxy: float | None = None
    collaboration_density: float = Field(default=0.0, ge=0.0)
    topic_centrality: float = Field(default=0.0, ge=0.0)
    migration_strength: float = Field(default=0.0, ge=0.0)
    proxy_risk: float = Field(default=0.0, ge=0.0)
    evidence_level: str = "observed"
    applied_actions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SimulationStageResult(SandboxModel):
    stage_id: str
    stage_label: str
    stage_order: int = Field(ge=0)
    narrative: str = ""
    topic_count: int = Field(default=0, ge=0)
    impacted_topic_count: int = Field(default=0, ge=0)
    metrics: dict[str, float | int] = Field(default_factory=dict)
    topics: list[SimulationStageTopicState] = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)


class SimulationGoalEvaluation(SandboxModel):
    metric: str
    direction: str
    baseline_value: float = 0.0
    scenario_value: float = 0.0
    delta_value: float = 0.0
    status: str = "hold"
    summary: str = ""


class CounterfactualComparison(SandboxModel):
    total_topics: int = Field(default=0, ge=0)
    material_topic_count: int = Field(default=0, ge=0)
    net_delta_application_count: float = 0.0
    net_delta_funded_count: float = 0.0
    net_delta_funding_amount: float = 0.0
    avg_delta_proxy_risk: float = 0.0
    goal_attainment: list[SimulationGoalEvaluation] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class SimulationOutcomeTopic(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    delta_funded_count: float = 0.0
    delta_funding_amount: float = 0.0
    delta_proxy_risk: float = 0.0
    rationale: str = ""
    evidence_level: str = "proxy_supported"


class SimulationCrowdingOutItem(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    displaced_by: list[str] = Field(default_factory=list)
    delta_funded_count: float = 0.0
    delta_funding_amount: float = 0.0
    rationale: str = ""


class SimulationRiskShiftItem(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    risk_change: float = 0.0
    risk_type: str = "proxy_risk"
    rationale: str = ""


class SimulationResult(SandboxModel):
    run_id: str
    scenario_id: str
    baseline_id: str
    forecast_window: str
    impacts: list[SimulationTopicImpact] = Field(default_factory=list)
    simulation_frames: list[SimulationReplayFrame] = Field(default_factory=list)
    stage_results: list[SimulationStageResult] = Field(default_factory=list)
    counterfactual_comparison: CounterfactualComparison | None = None
    winners_and_losers: list[SimulationOutcomeTopic] = Field(default_factory=list)
    crowding_out: list[SimulationCrowdingOutItem] = Field(default_factory=list)
    risk_shift: list[SimulationRiskShiftItem] = Field(default_factory=list)
    evidence_backed_recommendations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationComparisonTopic(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    net_score: float
    dominant_change: str
    applied_shocks: list[str] = Field(default_factory=list)


class SimulationComparison(SandboxModel):
    scenario_id: str
    baseline_id: str
    forecast_window: str
    topic_count: int
    avg_delta_application_count: float
    avg_delta_funded_count: float
    avg_delta_funding_amount: float
    avg_delta_collaboration_density: float
    avg_delta_topic_centrality: float
    avg_delta_migration_strength: float
    avg_delta_proxy_risk: float
    top_opportunities: list[SimulationComparisonTopic] = Field(default_factory=list)
    top_risks: list[SimulationComparisonTopic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationTopicExplanation(SandboxModel):
    topic_id: str
    topic_label: str | None = None
    headline: str
    reasons: list[str] = Field(default_factory=list)
    action_hint: str


class SimulationExplanation(SandboxModel):
    scenario_id: str
    baseline_id: str
    forecast_window: str
    summary: list[str] = Field(default_factory=list)
    topics: list[SimulationTopicExplanation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
