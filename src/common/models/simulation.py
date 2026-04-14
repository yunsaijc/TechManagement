"""Native models for sandbox simulation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BaselineTopicState(BaseModel):
    topic_id: str
    topic_share: float = Field(ge=0.0, le=1.0)
    conversion_rate: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    momentum_score: float = Field(default=0.5, ge=0.0, le=1.0)


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
    baseline_share: float
    projected_share: float
    delta_share: float
    baseline_conversion: float
    projected_conversion: float
    delta_conversion: float
    baseline_risk: float
    projected_risk: float
    delta_risk: float
    baseline_momentum: float
    projected_momentum: float
    delta_momentum: float
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
    avg_delta_share: float
    avg_delta_conversion: float
    avg_delta_risk: float
    avg_delta_momentum: float
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
