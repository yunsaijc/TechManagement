"""Native policy simulation engine for sandbox."""

from __future__ import annotations

from datetime import UTC, datetime

from src.common.models.simulation import (
    BaselineSnapshot,
    BaselineTopicState,
    PolicyShock,
    ScenarioDefinition,
    SimulationResult,
    SimulationTopicImpact,
)

DEFAULT_RULES: dict[str, dict[str, float]] = {
    "funding_boost": {"share": 0.08, "conversion": 0.03, "risk": -0.02, "momentum": 0.05},
    "talent_program": {"share": 0.04, "conversion": 0.06, "risk": -0.04, "momentum": 0.05},
    "commercialization_push": {"share": 0.03, "conversion": 0.08, "risk": -0.03, "momentum": 0.04},
    "collaboration_program": {"share": 0.05, "conversion": 0.04, "risk": -0.02, "momentum": 0.05},
    "regulation_tightening": {"share": -0.05, "conversion": 0.01, "risk": -0.03, "momentum": -0.02},
    "budget_cut": {"share": -0.06, "conversion": -0.04, "risk": 0.05, "momentum": -0.06},
}


def run_policy_simulation(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> SimulationResult:
    impacts = [_simulate_topic(topic, scenario.policy_shocks, scenario.forecast_window) for topic in baseline.topics]
    impacts.sort(key=lambda item: abs(item.delta_risk) + abs(item.delta_share), reverse=True)

    return SimulationResult(
        run_id=datetime.now(UTC).isoformat(),
        scenario_id=scenario.scenario_id,
        baseline_id=baseline.baseline_id,
        forecast_window=scenario.forecast_window,
        impacts=impacts,
        assumptions=_merge_assumptions(baseline, scenario),
        metadata={
            "engine": "native_policy_simulation_v1",
            "shockCount": len(scenario.policy_shocks),
            "topicCount": len(baseline.topics),
            "scenarioTags": list(scenario.tags),
        },
    )


def _simulate_topic(
    topic: BaselineTopicState,
    shocks: list[PolicyShock],
    forecast_window: str,
) -> SimulationTopicImpact:
    share = topic.topic_share
    conversion = topic.conversion_rate
    risk = topic.risk_score
    momentum = topic.momentum_score
    applied_shocks: list[str] = []

    for shock in shocks:
        if shock.target_topics and topic.topic_id not in shock.target_topics:
            continue

        rules = DEFAULT_RULES.get(shock.shock_type, {"share": 0.0, "conversion": 0.0, "risk": 0.0, "momentum": 0.0})
        lag_factor = max(0.35, 1.0 - 0.15 * shock.lag)
        strength = shock.intensity * shock.coverage * lag_factor

        share += rules["share"] * strength
        conversion += rules["conversion"] * strength
        risk += rules["risk"] * strength
        momentum += rules["momentum"] * strength
        applied_shocks.append(shock.shock_id)

    projected_share = _clamp(share)
    projected_conversion = _clamp(conversion)
    projected_risk = _clamp(risk)
    projected_momentum = _clamp(momentum)

    return SimulationTopicImpact(
        topic_id=topic.topic_id,
        forecast_window=forecast_window,
        baseline_share=topic.topic_share,
        projected_share=projected_share,
        delta_share=projected_share - topic.topic_share,
        baseline_conversion=topic.conversion_rate,
        projected_conversion=projected_conversion,
        delta_conversion=projected_conversion - topic.conversion_rate,
        baseline_risk=topic.risk_score,
        projected_risk=projected_risk,
        delta_risk=projected_risk - topic.risk_score,
        baseline_momentum=topic.momentum_score,
        projected_momentum=projected_momentum,
        delta_momentum=projected_momentum - topic.momentum_score,
        applied_shocks=applied_shocks,
    )


def _merge_assumptions(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> list[str]:
    assumptions = list(baseline.assumptions)
    assumptions.extend(scenario.assumptions)
    assumptions.append("policy_shocks_apply_linearly_with_lag_discount")
    return assumptions


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))
