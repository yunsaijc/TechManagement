"""Pure-function baseline view for sandbox simulation."""

from __future__ import annotations

from typing import Any, Mapping

from src.common.models.simulation import BaselineSnapshot, BaselineTopicSnapshot

DEFAULT_BASELINE_ID = "legacy_leadership_baseline"


def run_baseline_snapshot(
    *,
    baseline_id: str = DEFAULT_BASELINE_ID,
    question: str | None = None,
    run_preflight: bool = False,
    mode: str = "quick",
    force_refresh: bool = False,
) -> BaselineSnapshot:
    """Run the legacy prototype and expose its baseline-shaped view."""
    from src.services.sandbox.simulation.prototype import run_forecast

    report = run_forecast(
        question=question,
        run_preflight=run_preflight,
        mode=mode,
        force_refresh=force_refresh,
    )
    return report_to_baseline_snapshot(report, baseline_id=baseline_id)


def load_latest_baseline_snapshot(
    *,
    baseline_id: str = DEFAULT_BASELINE_ID,
) -> BaselineSnapshot | None:
    """Load the latest legacy report and expose its baseline-shaped view."""
    from src.services.sandbox.simulation.prototype import load_latest_report

    report = load_latest_report()
    if not report:
        return None
    return report_to_baseline_snapshot(report, baseline_id=baseline_id)


def report_to_baseline_snapshot(
    report: Mapping[str, Any],
    *,
    baseline_id: str = DEFAULT_BASELINE_ID,
) -> BaselineSnapshot:
    """Convert a legacy leadership forecast report into a lightweight baseline snapshot."""
    meta = _as_mapping(report.get("meta"))
    future = _as_mapping(report.get("futureJudgement"))
    forecast_window = _resolve_forecast_window(report)

    return BaselineSnapshot(
        baseline_id=baseline_id,
        run_id=_resolve_run_id(report),
        forecast_window=forecast_window,
        topics=_extract_topics(report, forecast_window),
        metadata={
            "sourcePipeline": report.get("pipeline"),
            "sourceStatus": report.get("status"),
            "generatedAt": meta.get("generatedAt"),
            "mode": meta.get("mode"),
            "question": meta.get("question"),
            "runPreflight": meta.get("runPreflight"),
            "futureJudgement": {
                "riskLevel": future.get("riskLevel"),
                "riskIndex": future.get("riskIndex"),
                "summary": _as_mapping(future.get("summary")),
            },
            "leadershipBrief": _as_mapping(report.get("leadershipBrief")),
            "reportPaths": _as_mapping(meta.get("paths")),
        },
    )


def _extract_topics(
    report: Mapping[str, Any],
    forecast_window: str,
) -> list[BaselineTopicSnapshot]:
    future = _as_mapping(report.get("futureJudgement"))
    priority_topics = future.get("priorityTopics")
    if not isinstance(priority_topics, list):
        return []

    topics: list[BaselineTopicSnapshot] = []
    for item in priority_topics:
        topic_entry = _as_mapping(item)
        topic_id = str(topic_entry.get("topic") or "").strip()
        if not topic_id:
            continue
        evidence = _as_mapping(topic_entry.get("evidence"))
        topics.append(
            BaselineTopicSnapshot(
                topic_id=topic_id,
                forecast_window=forecast_window,
                topic_share=_first_float(
                    evidence,
                    "baselineShare",
                    "topicShare",
                    "share",
                    "currentShare",
                ),
                conversion_rate=_first_float(
                    evidence,
                    "baselineConversion",
                    "conversionB",
                    "conversion",
                    "currentConversion",
                ),
                risk_score=_first_float(
                    evidence,
                    "baselineRisk",
                    "riskScore",
                    "currentRisk",
                ),
            )
        )
    return topics


def _resolve_run_id(report: Mapping[str, Any]) -> str:
    meta = _as_mapping(report.get("meta"))
    generated_at = str(meta.get("generatedAt") or "").strip()
    if generated_at:
        return generated_at
    pipeline = str(report.get("pipeline") or "").strip()
    if pipeline:
        return pipeline
    return DEFAULT_BASELINE_ID


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
