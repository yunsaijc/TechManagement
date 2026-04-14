"""Pure-function service layer for sandbox simulation scenarios."""

from __future__ import annotations

from typing import Any, Mapping

from src.common.models.simulation import (
    ScenarioDefinition,
    SimulationResult,
    SimulationTopicDelta,
)

DEFAULT_SCENARIO_ID = "legacy_leadership_forecast"
DEFAULT_BASELINE_ID = "legacy_leadership_baseline"


def run_scenario(
    scenario: ScenarioDefinition | None = None,
    *,
    question: str | None = None,
    run_preflight: bool = False,
    mode: str = "quick",
    force_refresh: bool = False,
) -> SimulationResult:
    """Run the legacy prototype and map its report into lightweight simulation models."""
    from src.services.sandbox.simulation.prototype import run_forecast

    report = run_forecast(
        question=question,
        run_preflight=run_preflight,
        mode=mode,
        force_refresh=force_refresh,
    )
    resolved_scenario = scenario or build_default_scenario()
    return report_to_simulation_result(report, scenario=resolved_scenario)


def load_latest_scenario_result(
    scenario: ScenarioDefinition | None = None,
) -> SimulationResult | None:
    """Load the latest legacy report and map it into a simulation result."""
    from src.services.sandbox.simulation.prototype import load_latest_report

    report = load_latest_report()
    if not report:
        return None
    resolved_scenario = scenario or build_default_scenario()
    return report_to_simulation_result(report, scenario=resolved_scenario)


def build_default_scenario(
    *,
    scenario_id: str = DEFAULT_SCENARIO_ID,
    baseline_id: str = DEFAULT_BASELINE_ID,
) -> ScenarioDefinition:
    """Create a minimal scenario envelope for the legacy prototype."""
    return ScenarioDefinition(
        scenario_id=scenario_id,
        baseline_id=baseline_id,
    )


def report_to_simulation_result(
    report: Mapping[str, Any],
    *,
    scenario: ScenarioDefinition,
) -> SimulationResult:
    """Convert a legacy leadership forecast report into a lightweight simulation result."""
    future = _as_mapping(report.get("futureJudgement"))
    meta = _as_mapping(report.get("meta"))

    return SimulationResult(
        run_id=_resolve_run_id(report),
        scenario_id=scenario.scenario_id,
        baseline_id=scenario.baseline_id,
        topic_deltas=_extract_topic_deltas(report),
        metadata={
            "sourcePipeline": report.get("pipeline"),
            "sourceStatus": report.get("status"),
            "generatedAt": meta.get("generatedAt"),
            "mode": meta.get("mode"),
            "question": meta.get("question"),
            "runPreflight": meta.get("runPreflight"),
            "reportPaths": _as_mapping(meta.get("paths")),
            "futureJudgement": {
                "riskLevel": future.get("riskLevel"),
                "riskIndex": future.get("riskIndex"),
                "summary": _as_mapping(future.get("summary")),
                "topRiskTypes": future.get("topRiskTypes"),
            },
            "leadershipBrief": _as_mapping(report.get("leadershipBrief")),
            "scenarioTags": list(scenario.tags),
            "instrumentIds": [item.instrument_id for item in scenario.instruments],
        },
    )


def _extract_topic_deltas(report: Mapping[str, Any]) -> list[SimulationTopicDelta]:
    future = _as_mapping(report.get("futureJudgement"))
    priority_topics = future.get("priorityTopics")
    if not isinstance(priority_topics, list):
        return []

    forecast_window = _resolve_forecast_window(report)
    topic_deltas: list[SimulationTopicDelta] = []
    for item in priority_topics:
        topic_entry = _as_mapping(item)
        topic_id = str(topic_entry.get("topic") or "").strip()
        if not topic_id:
            continue

        evidence = _as_mapping(topic_entry.get("evidence"))
        topic_deltas.append(
            SimulationTopicDelta(
                topic_id=topic_id,
                forecast_window=forecast_window,
                baseline_share=_first_float(
                    evidence,
                    "baselineShare",
                    "topicShare",
                    "share",
                    "currentShare",
                ),
                delta_share=_first_float(
                    evidence,
                    "deltaShare",
                    "shareDelta",
                ),
                baseline_conversion=_first_float(
                    evidence,
                    "baselineConversion",
                    "conversionB",
                    "conversion",
                    "currentConversion",
                ),
                delta_conversion=_first_float(
                    evidence,
                    "deltaConversion",
                    "conversionDelta",
                    "recoveryDelta",
                ),
                baseline_risk=_first_float(
                    evidence,
                    "baselineRisk",
                    "riskScore",
                    "currentRisk",
                ),
                delta_risk=_first_float(
                    evidence,
                    "deltaRisk",
                    "riskDelta",
                    "riskChange",
                ),
            )
        )
    return topic_deltas


def _resolve_run_id(report: Mapping[str, Any]) -> str:
    meta = _as_mapping(report.get("meta"))
    generated_at = str(meta.get("generatedAt") or "").strip()
    if generated_at:
        return generated_at
    pipeline = str(report.get("pipeline") or "").strip()
    if pipeline:
        return pipeline
    return DEFAULT_SCENARIO_ID


def _resolve_forecast_window(report: Mapping[str, Any]) -> str:
    raw = _as_mapping(report.get("raw"))
    step2 = _as_mapping(raw.get("step2"))
    step2_meta = _as_mapping(step2.get("meta"))
    window_b = _as_mapping(step2_meta.get("windowB"))
    start = window_b.get("start")
    end = window_b.get("end")
    if start is not None and end is not None:
        start_str = str(start)
        end_str = str(end)
        return start_str if start_str == end_str else f"{start_str}-{end_str}"

    meta = _as_mapping(report.get("meta"))
    generated_at = str(meta.get("generatedAt") or "").strip()
    if generated_at:
        return generated_at[:10]
    return "unknown"


def _first_float(values: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in values:
            continue
        value = values.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}
