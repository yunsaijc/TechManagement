"""Native policy simulation engine for sandbox."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeAlias

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

ShockApplication: TypeAlias = tuple[PolicyShock, float]


def run_policy_simulation(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> SimulationResult:
    shock_applications = _build_shock_applications(baseline.topics, scenario.policy_shocks)
    impacts = [
        _simulate_topic(
            topic,
            shock_applications.get(topic.topic_id, []),
            scenario.forecast_window,
        )
        for topic in baseline.topics
    ]
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
            "spilloverEnabledShockCount": sum(1 for shock in scenario.policy_shocks if _spillover_enabled(shock)),
            "topicCount": len(baseline.topics),
            "impactedTopicCount": sum(1 for item in impacts if _impact_signal(item) > 0.0),
            "scenarioTags": list(scenario.tags),
        },
    )


def _build_shock_applications(
    topics: list[BaselineTopicState],
    shocks: list[PolicyShock],
) -> dict[str, list[ShockApplication]]:
    topic_by_id = {topic.topic_id: topic for topic in topics}
    applications: dict[str, list[ShockApplication]] = {topic.topic_id: [] for topic in topics}

    for shock in shocks:
        base_strength = _shock_strength(shock)
        if base_strength <= 0.0:
            continue

        if shock.target_topics:
            target_ids = [topic_id for topic_id in shock.target_topics if topic_id in topic_by_id]
        else:
            target_ids = [topic.topic_id for topic in topics]

        if not target_ids:
            continue

        for topic_id in target_ids:
            applications[topic_id].append((shock, base_strength))

        if not _spillover_enabled(shock) or not shock.target_topics:
            continue

        propagation_strength = _shock_parameter_float(shock, "propagation_strength", 0.35)
        min_similarity = _shock_parameter_float(shock, "min_similarity", 0.55)
        max_neighbors = max(0, int(_shock_parameter_float(shock, "max_neighbors", 8)))
        if propagation_strength <= 0.0 or max_neighbors == 0:
            continue

        spillover_scores: dict[str, float] = {}
        direct_ids = set(target_ids)
        for target_id in target_ids:
            source = topic_by_id[target_id]
            for candidate in topics:
                if candidate.topic_id in direct_ids:
                    continue
                similarity = _topic_similarity(source, candidate)
                if similarity < min_similarity:
                    continue
                spillover_strength = base_strength * propagation_strength * similarity
                current = spillover_scores.get(candidate.topic_id, 0.0)
                if spillover_strength > current:
                    spillover_scores[candidate.topic_id] = spillover_strength

        for topic_id, spillover_strength in sorted(
            spillover_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:max_neighbors]:
            if spillover_strength > 0.0:
                applications[topic_id].append((shock, spillover_strength))

    return applications


def _simulate_topic(
    topic: BaselineTopicState,
    shock_applications: list[ShockApplication],
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

    for shock, strength in shock_applications:
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
    if any(_spillover_enabled(shock) for shock in scenario.policy_shocks):
        assumptions.append("project_graph_policy_shocks_apply_similarity_spillover")
    return assumptions


def _impact_signal(item: SimulationTopicImpact) -> float:
    return (
        abs(item.delta_application_count)
        + abs(item.delta_funded_count)
        + abs(item.delta_funding_amount)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_migration_strength)
        + abs(item.delta_proxy_risk)
    )


def _shock_strength(shock: PolicyShock) -> float:
    lag_factor = max(0.35, 1.0 - 0.15 * shock.lag)
    return shock.intensity * shock.coverage * lag_factor


def _spillover_enabled(shock: PolicyShock) -> bool:
    return bool(shock.parameters.get("enable_spillover", False))


def _shock_parameter_float(shock: PolicyShock, key: str, default: float) -> float:
    value = shock.parameters.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _topic_similarity(source: BaselineTopicState, candidate: BaselineTopicState) -> float:
    code_similarity = _topic_code_similarity(source.topic_id, candidate.topic_id)
    graph_similarity = _mean(
        [
            1.0 - abs(source.collaboration_density - candidate.collaboration_density),
            1.0 - abs(source.topic_centrality - candidate.topic_centrality),
            1.0 - abs(source.migration_strength - candidate.migration_strength),
            1.0 - abs(source.proxy_risk - candidate.proxy_risk),
        ]
    )
    score_similarity = _score_similarity(source.score_proxy, candidate.score_proxy)
    return max(0.0, min(1.0, 0.35 * code_similarity + 0.50 * graph_similarity + 0.15 * score_similarity))


def _topic_code_similarity(source_topic_id: str, candidate_topic_id: str) -> float:
    source_code = _topic_code(source_topic_id)
    candidate_code = _topic_code(candidate_topic_id)
    if not source_code or not candidate_code:
        return 0.0

    max_len = min(len(source_code), len(candidate_code))
    prefix_len = 0
    for index in range(max_len):
        if source_code[index] != candidate_code[index]:
            break
        prefix_len += 1
    return prefix_len / max_len if max_len else 0.0


def _topic_code(topic_id: str) -> str:
    head = str(topic_id).split("-", 1)[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    return digits


def _score_similarity(source: float | None, candidate: float | None) -> float:
    if source is None or candidate is None:
        return 0.5
    return max(0.0, 1.0 - abs(source - candidate) / 30.0)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


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
