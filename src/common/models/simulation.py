"""Native models for sandbox simulation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BaselineTopicState(BaseModel):
    topic_id: str
    application_count: int = Field(ge=0)
    funded_count: int = Field(ge=0)
    funding_amount: float = Field(ge=0.0)
    score_proxy: float | None = None
    collaboration_density: float = Field(default=0.0, ge=0.0, le=1.0)
    topic_centrality: float = Field(default=0.0, ge=0.0, le=1.0)
    migration_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    proxy_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class BaselineSnapshot(BaseModel):
    baseline_id: str
    forecast_window: str
    topics: list[BaselineTopicState] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyShock(BaseModel):
    shock_id: str
    shock_type: str
    target_topics: list[str] = Field(default_factory=list)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    lag: int = Field(default=0, ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioDefinition(BaseModel):
    scenario_id: str
    baseline_id: str
    forecast_window: str
    policy_shocks: list[PolicyShock] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SimulationTopicImpact(BaseModel):
    topic_id: str
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


class SimulationResult(BaseModel):
    run_id: str
    scenario_id: str
    baseline_id: str
    forecast_window: str
    impacts: list[SimulationTopicImpact] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationComparisonTopic(BaseModel):
    topic_id: str
    net_score: float
    dominant_change: str
    applied_shocks: list[str] = Field(default_factory=list)


class SimulationComparison(BaseModel):
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


class SimulationTopicExplanation(BaseModel):
    topic_id: str
    headline: str
    reasons: list[str] = Field(default_factory=list)
    action_hint: str


class SimulationExplanation(BaseModel):
    scenario_id: str
    baseline_id: str
    forecast_window: str
    summary: list[str] = Field(default_factory=list)
    topics: list[SimulationTopicExplanation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
