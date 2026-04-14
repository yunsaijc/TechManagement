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

    avg_delta_share = _avg(item.delta_share for item in impacts)
    avg_delta_conversion = _avg(item.delta_conversion for item in impacts)
    avg_delta_risk = _avg(item.delta_risk for item in impacts)
    avg_delta_momentum = _avg(item.delta_momentum for item in impacts)

    opportunities = sorted(
        impacts,
        key=lambda item: item.delta_share + item.delta_conversion - item.delta_risk + item.delta_momentum,
        reverse=True,
    )[:3]
    risks = sorted(
        impacts,
        key=lambda item: item.delta_risk - item.delta_conversion - item.delta_share - item.delta_momentum,
        reverse=True,
    )[:3]

    return SimulationComparison(
        scenario_id=result.scenario_id,
        baseline_id=result.baseline_id,
        forecast_window=result.forecast_window,
        topic_count=topic_count,
        avg_delta_share=avg_delta_share,
        avg_delta_conversion=avg_delta_conversion,
        avg_delta_risk=avg_delta_risk,
        avg_delta_momentum=avg_delta_momentum,
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
    net_score = round(item.delta_share + item.delta_conversion - item.delta_risk + item.delta_momentum, 6)
    dominant_change = max(
        (
            ("share", abs(item.delta_share)),
            ("conversion", abs(item.delta_conversion)),
            ("risk", abs(item.delta_risk)),
            ("momentum", abs(item.delta_momentum)),
        ),
        key=lambda pair: pair[1],
    )[0]
    return SimulationComparisonTopic(
        topic_id=item.topic_id,
        net_score=net_score,
        dominant_change=dominant_change,
        applied_shocks=list(item.applied_shocks),
    )


def _avg(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)
