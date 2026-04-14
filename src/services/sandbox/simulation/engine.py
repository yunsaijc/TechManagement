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
    "funding_boost": {
        "application_count": 0.10,
        "funded_count": 0.08,
        "funding_amount": 0.18,
        "score_proxy": 0.03,
        "collaboration_density": 0.02,
        "topic_centrality": 0.03,
        "migration_strength": 0.04,
        "proxy_risk": -0.03,
    },
    "funding_cut": {
        "application_count": -0.08,
        "funded_count": -0.10,
        "funding_amount": -0.18,
        "score_proxy": -0.04,
        "collaboration_density": -0.02,
        "topic_centrality": -0.03,
        "migration_strength": -0.03,
        "proxy_risk": 0.05,
    },
    "topic_priority_shift": {
        "application_count": 0.12,
        "funded_count": 0.07,
        "funding_amount": 0.12,
        "score_proxy": 0.02,
        "collaboration_density": 0.01,
        "topic_centrality": 0.05,
        "migration_strength": 0.08,
        "proxy_risk": -0.01,
    },
    "collaboration_support": {
        "application_count": 0.04,
        "funded_count": 0.03,
        "funding_amount": 0.04,
        "score_proxy": 0.01,
        "collaboration_density": 0.10,
        "topic_centrality": 0.06,
        "migration_strength": 0.05,
        "proxy_risk": -0.03,
    },
    "quota_adjustment": {
        "application_count": 0.06,
        "funded_count": 0.09,
        "funding_amount": 0.07,
        "score_proxy": 0.01,
        "collaboration_density": 0.00,
        "topic_centrality": 0.02,
        "migration_strength": 0.03,
        "proxy_risk": -0.01,
    },
}


def run_policy_simulation(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> SimulationResult:
    impacts = [_simulate_topic(topic, scenario.policy_shocks, scenario.forecast_window) for topic in baseline.topics]
    impacts.sort(
        key=lambda item: abs(item.delta_funding_amount)
        + abs(item.delta_funded_count)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_proxy_risk),
        reverse=True,
    )

    return SimulationResult(
        run_id=datetime.now(UTC).isoformat(),
        scenario_id=scenario.scenario_id,
        baseline_id=baseline.baseline_id,
        forecast_window=scenario.forecast_window,
        impacts=impacts,
        assumptions=_merge_assumptions(baseline, scenario),
        metadata={
            "engine": "native_policy_simulation_v2_project_graph",
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
    application_count = float(topic.application_count)
    funded_count = float(topic.funded_count)
    funding_amount = topic.funding_amount
    score_proxy = _score_or_zero(topic.score_proxy)
    collaboration_density = topic.collaboration_density
    topic_centrality = topic.topic_centrality
    migration_strength = topic.migration_strength
    proxy_risk = topic.proxy_risk
    applied_shocks: list[str] = []

    for shock in shocks:
        if shock.target_topics and topic.topic_id not in shock.target_topics:
            continue

        rules = DEFAULT_RULES.get(
            shock.shock_type,
            {
                "application_count": 0.0,
                "funded_count": 0.0,
                "funding_amount": 0.0,
                "score_proxy": 0.0,
                "collaboration_density": 0.0,
                "topic_centrality": 0.0,
                "migration_strength": 0.0,
                "proxy_risk": 0.0,
            },
        )
        lag_factor = max(0.35, 1.0 - 0.15 * shock.lag)
        strength = shock.intensity * shock.coverage * lag_factor

        application_count += topic.application_count * rules["application_count"] * strength
        funded_count += max(topic.funded_count, 1) * rules["funded_count"] * strength
        funding_amount += topic.funding_amount * rules["funding_amount"] * strength
        score_proxy += score_proxy * rules["score_proxy"] * strength
        collaboration_density += rules["collaboration_density"] * strength
        topic_centrality += rules["topic_centrality"] * strength
        migration_strength += rules["migration_strength"] * strength
        proxy_risk += rules["proxy_risk"] * strength
        applied_shocks.append(shock.shock_id)

    projected_application_count = _round_count(application_count)
    projected_funded_count = _round_count(funded_count)
    projected_funding_amount = _round_amount(funding_amount)
    projected_score_proxy = _round_nullable(score_proxy)
    projected_collaboration_density = _clamp_unit(collaboration_density)
    projected_topic_centrality = _clamp_unit(topic_centrality)
    projected_migration_strength = _clamp_unit(migration_strength)
    projected_proxy_risk = _clamp_unit(proxy_risk)

    return SimulationTopicImpact(
        topic_id=topic.topic_id,
        forecast_window=forecast_window,
        baseline_application_count=topic.application_count,
        projected_application_count=projected_application_count,
        delta_application_count=projected_application_count - topic.application_count,
        baseline_funded_count=topic.funded_count,
        projected_funded_count=projected_funded_count,
        delta_funded_count=projected_funded_count - topic.funded_count,
        baseline_funding_amount=topic.funding_amount,
        projected_funding_amount=projected_funding_amount,
        delta_funding_amount=round(projected_funding_amount - topic.funding_amount, 6),
        baseline_score_proxy=topic.score_proxy,
        projected_score_proxy=projected_score_proxy,
        delta_score_proxy=_delta_nullable(projected_score_proxy, topic.score_proxy),
        baseline_collaboration_density=topic.collaboration_density,
        projected_collaboration_density=projected_collaboration_density,
        delta_collaboration_density=round(projected_collaboration_density - topic.collaboration_density, 6),
        baseline_topic_centrality=topic.topic_centrality,
        projected_topic_centrality=projected_topic_centrality,
        delta_topic_centrality=round(projected_topic_centrality - topic.topic_centrality, 6),
        baseline_migration_strength=topic.migration_strength,
        projected_migration_strength=projected_migration_strength,
        delta_migration_strength=round(projected_migration_strength - topic.migration_strength, 6),
        baseline_proxy_risk=topic.proxy_risk,
        projected_proxy_risk=projected_proxy_risk,
        delta_proxy_risk=round(projected_proxy_risk - topic.proxy_risk, 6),
        applied_shocks=applied_shocks,
    )


def _merge_assumptions(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> list[str]:
    assumptions = list(baseline.assumptions)
    assumptions.extend(scenario.assumptions)
    assumptions.append("project_graph_policy_shocks_apply_with_lag_discount")
    return assumptions


def _score_or_zero(value: float | None) -> float:
    return float(value or 0.0)


def _round_count(value: float) -> int:
    return max(0, int(round(value)))


def _round_amount(value: float) -> float:
    return round(max(0.0, value), 6)


def _round_nullable(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, value), 6)


def _delta_nullable(projected: float | None, baseline: float | None) -> float | None:
    if projected is None or baseline is None:
        if projected is None and baseline is None:
            return None
        return round((projected or 0.0) - (baseline or 0.0), 6)
    return round(projected - baseline, 6)


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))
