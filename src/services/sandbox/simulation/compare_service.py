"""Comparison service for native sandbox simulation results."""

from __future__ import annotations

from src.common.models.simulation import (
    SimulationComparison,
    SimulationComparisonTopic,
    SimulationResult,
)

from . import repository


def compare_result(result: SimulationResult) -> SimulationComparison:
    impacts = list(result.impacts)
    topic_count = len(impacts)

    avg_delta_application_count = _avg(item.delta_application_count for item in impacts)
    avg_delta_funded_count = _avg(item.delta_funded_count for item in impacts)
    avg_delta_funding_amount = _avg(item.delta_funding_amount for item in impacts)
    avg_delta_collaboration_density = _avg(item.delta_collaboration_density for item in impacts)
    avg_delta_topic_centrality = _avg(item.delta_topic_centrality for item in impacts)
    avg_delta_migration_strength = _avg(item.delta_migration_strength for item in impacts)
    avg_delta_proxy_risk = _avg(item.delta_proxy_risk for item in impacts)

    opportunities = sorted(impacts, key=_opportunity_score, reverse=True)[:3]
    risks = sorted(impacts, key=_risk_score, reverse=True)[:3]

    return SimulationComparison(
        scenario_id=result.scenario_id,
        baseline_id=result.baseline_id,
        forecast_window=result.forecast_window,
        topic_count=topic_count,
        avg_delta_application_count=avg_delta_application_count,
        avg_delta_funded_count=avg_delta_funded_count,
        avg_delta_funding_amount=avg_delta_funding_amount,
        avg_delta_collaboration_density=avg_delta_collaboration_density,
        avg_delta_topic_centrality=avg_delta_topic_centrality,
        avg_delta_migration_strength=avg_delta_migration_strength,
        avg_delta_proxy_risk=avg_delta_proxy_risk,
        top_opportunities=[_to_summary(item) for item in opportunities],
        top_risks=[_to_summary(item) for item in risks],
        metadata={
            "sourceRunId": result.run_id,
            "engine": result.metadata.get("engine"),
        },
    )


def compare_latest_result() -> SimulationComparison | None:
    latest = repository.load_latest_scenario_result()
    if latest is None:
        return None
    return compare_result(latest)


def _to_summary(item) -> SimulationComparisonTopic:
    net_score = round(_opportunity_score(item), 6)
    dominant_change = max(
        (
            ("application_count", abs(_safe_ratio(item.delta_application_count, item.baseline_application_count))),
            ("funded_count", abs(_safe_ratio(item.delta_funded_count, item.baseline_funded_count))),
            ("funding_amount", abs(_safe_ratio(item.delta_funding_amount, item.baseline_funding_amount))),
            ("collaboration_density", abs(item.delta_collaboration_density)),
            ("topic_centrality", abs(item.delta_topic_centrality)),
            ("migration_strength", abs(item.delta_migration_strength)),
            ("proxy_risk", abs(item.delta_proxy_risk)),
        ),
        key=lambda pair: pair[1],
    )[0]
    return SimulationComparisonTopic(
        topic_id=item.topic_id,
        net_score=net_score,
        dominant_change=dominant_change,
        applied_shocks=list(item.applied_shocks),
    )


def _opportunity_score(item) -> float:
    return (
        _safe_ratio(item.delta_application_count, item.baseline_application_count)
        + _safe_ratio(item.delta_funded_count, item.baseline_funded_count)
        + _safe_ratio(item.delta_funding_amount, item.baseline_funding_amount)
        + item.delta_collaboration_density
        + item.delta_topic_centrality
        + item.delta_migration_strength
        - item.delta_proxy_risk
        + _safe_ratio(item.delta_score_proxy or 0.0, item.baseline_score_proxy or 1.0)
    )


def _risk_score(item) -> float:
    return (
        item.delta_proxy_risk
        - _safe_ratio(item.delta_funded_count, item.baseline_funded_count)
        - _safe_ratio(item.delta_application_count, item.baseline_application_count)
        - item.delta_topic_centrality
        - item.delta_collaboration_density
    )


def _safe_ratio(delta: float, baseline: float) -> float:
    return round(delta / max(abs(float(baseline)), 1.0), 6)


def _avg(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)
