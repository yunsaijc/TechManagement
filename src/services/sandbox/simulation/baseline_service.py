"""Baseline services for native sandbox simulation."""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timezone

from src.common.models.simulation import BaselineSnapshot, BaselineTopicState
from src.services.sandbox.data import (
    build_topic_aggregates,
    build_topic_year_aggregates,
    inspect_graph_profile,
    load_graph_topic_metrics,
    load_topic_migration_edges,
    load_graph_window_metadata,
    load_project_facts,
    verify_graph_readiness,
)

from . import repository

DEFAULT_BASELINE_START_YEAR = 2020
SHARED_LAYER_BASELINE_KIND = "shared_layer"
MANUAL_INPUT_BASELINE_KIND = "manual_input"


@dataclass
class ProjectTopicAggregate:
    topic_key: str
    topic_label: str
    application_count: int
    funded_count: int
    funding_amount: float
    requested_funding_amount: float
    score_proxy: float | None


@dataclass
class GraphTopicAggregate:
    topic_key: str
    topic_label: str
    collaboration_density: float
    topic_centrality: float
    migration_strength: float


@dataclass
class ProjectTopicYearAggregate:
    topic_key: str
    topic_label: str
    year: int
    application_count: int
    funded_count: int
    funding_amount: float
    requested_funding_amount: float


@dataclass
class BaselineWindow:
    requested_start_year: int | None
    requested_end_year: int | None
    start_year: int
    end_year: int
    latest_project_year: int


def create_baseline_snapshot(
    *,
    baseline_id: str,
    forecast_window: str,
    topics: list[BaselineTopicState],
    assumptions: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    persist: bool = True,
) -> BaselineSnapshot:
    normalized_metadata = _normalize_baseline_metadata(
        metadata,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
    )
    snapshot = BaselineSnapshot(
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        topics=topics,
        assumptions=assumptions or [],
        metadata=normalized_metadata,
    )
    if persist:
        repository.save_baseline_snapshot(snapshot)
    return snapshot


def build_baseline_snapshot_from_sources(
    *,
    baseline_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    persist: bool = True,
) -> BaselineSnapshot:
    window = _resolve_baseline_window(start_year=start_year, end_year=end_year)

    total_started = time.perf_counter()

    project_load_started = time.perf_counter()
    project_facts = _load_project_facts_for_window(start_year=window.start_year, end_year=window.end_year)
    project_rows = _build_project_topic_aggregates(project_facts)
    project_year_rows = _build_project_topic_year_aggregates(project_facts)
    project_window_metadata = _build_project_window_metadata(project_facts, start_year=window.start_year, end_year=window.end_year)
    project_load_seconds = round(time.perf_counter() - project_load_started, 3)

    graph_load_started = time.perf_counter()
    graph_rows = _load_graph_topic_aggregates(start_year=window.start_year, end_year=window.end_year)
    graph_window_metadata = _load_graph_window_metadata(start_year=window.start_year, end_year=window.end_year)
    topic_migration_edges = _load_topic_migration_edges(start_year=window.start_year, end_year=window.end_year)
    graph_profile = _load_graph_profile()
    graph_readiness = _load_graph_readiness()
    graph_load_seconds = round(time.perf_counter() - graph_load_started, 3)
    elapsed_seconds = round(time.perf_counter() - total_started, 3)

    topics = _merge_topic_aggregates(project_rows, graph_rows, project_year_rows)
    if not topics:
        raise RuntimeError("未从项目库和图谱中构建出任何 topic baseline")

    default_start_year = min(DEFAULT_BASELINE_START_YEAR, window.latest_project_year)
    return create_baseline_snapshot(
        baseline_id=baseline_id,
        forecast_window=_format_window(window.start_year, window.end_year),
        topics=topics,
        assumptions=[
            "baseline_from_project_db_and_neo4j_graph",
            "default_window=2020_to_latest_project_year_when_not_specified",
            "topic_priority=guide_name_then_department_office",
            "review_score_from_ps_xmpsxx",
            "funded_flag_from_ht_xmlxxx_or_contract_presence",
            "funding_amount_from_ht_jfgs_fallback_ht_xmlxxx",
            "proxy_risk_is_derived_from_observed_project_graph_metrics",
            "topic_growth_momentum_from_project_year_panel",
        ],
        metadata={
            "baselineProvenance": {
                "kind": SHARED_LAYER_BASELINE_KIND,
                "source": "build_baseline_snapshot_from_sources",
                "baselineId": baseline_id,
                "forecastWindow": _format_window(window.start_year, window.end_year),
                "createdAt": _baseline_timestamp(),
                "startYear": window.start_year,
                "endYear": window.end_year,
            },
            "requestedStartYear": window.requested_start_year,
            "requestedEndYear": window.requested_end_year,
            "startYear": window.start_year,
            "endYear": window.end_year,
            "defaultStartYear": default_start_year,
            "latestProjectYear": window.latest_project_year,
            "windowAutoCompleted": window.requested_start_year is None or window.requested_end_year is None,
            "windowResolvedBy": "project_db_latest_year",
            "yearCount": window.end_year - window.start_year + 1,
            "migrationWindowEligible": window.start_year < window.end_year,
            "projectFactCount": len(project_facts),
            "projectTopicCount": len(project_rows),
            "projectTopicYearCount": len(project_year_rows),
            "graphTopicCount": len(graph_rows),
            "topicMigrationEdgeCount": len(topic_migration_edges),
            "topTopicMigrationEdges": _summarize_topic_migration_edges(topic_migration_edges),
            "graphProfile": asdict(graph_profile),
            "graphReadiness": asdict(graph_readiness),
            "topicCount": len(topics),
            "projectLoadSeconds": project_load_seconds,
            "graphLoadSeconds": graph_load_seconds,
            "elapsedSeconds": elapsed_seconds,
            **project_window_metadata,
            **graph_window_metadata,
        },
        persist=persist,
    )


def load_latest_baseline_snapshot() -> BaselineSnapshot | None:
    return repository.load_latest_baseline_snapshot()


def _resolve_baseline_window(
    *,
    start_year: int | None,
    end_year: int | None,
) -> BaselineWindow:
    latest_project_year = _load_latest_project_year()
    if latest_project_year is None:
        raise RuntimeError("项目库中未找到可用于 baseline 的年度数据")

    default_start_year = min(DEFAULT_BASELINE_START_YEAR, latest_project_year)
    resolved_start_year = default_start_year if start_year is None else max(start_year, DEFAULT_BASELINE_START_YEAR)
    resolved_end_year = latest_project_year if end_year is None else end_year

    if resolved_end_year < resolved_start_year:
        raise RuntimeError("end_year 不能小于 start_year")

    return BaselineWindow(
        requested_start_year=start_year,
        requested_end_year=end_year,
        start_year=resolved_start_year,
        end_year=resolved_end_year,
        latest_project_year=latest_project_year,
    )


def _load_latest_project_year() -> int | None:
    facts = _load_project_facts_for_window(
        start_year=DEFAULT_BASELINE_START_YEAR,
        end_year=datetime.now().year + 1,
    )
    if not facts:
        return None
    return max(item.application_year for item in facts)


def _normalize_baseline_metadata(
    metadata: dict[str, object] | None,
    *,
    baseline_id: str,
    forecast_window: str,
) -> dict[str, object]:
    normalized = dict(metadata or {})
    provenance = normalized.get("baselineProvenance")
    default_provenance = {
        "kind": MANUAL_INPUT_BASELINE_KIND,
        "source": "create_baseline_snapshot",
        "baselineId": baseline_id,
        "forecastWindow": forecast_window,
        "createdAt": _baseline_timestamp(),
    }
    if isinstance(provenance, dict):
        normalized["baselineProvenance"] = {
            **default_provenance,
            **provenance,
        }
    else:
        normalized["baselineProvenance"] = default_provenance
    return normalized


def _baseline_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_project_facts_for_window(
    *,
    start_year: int,
    end_year: int,
) -> list[object]:
    return load_project_facts(start_year=start_year, end_year=end_year)


def _build_project_window_metadata(
    project_facts: list[object],
    *,
    start_year: int,
    end_year: int,
) -> dict[str, object]:
    yearly_stats_map: dict[int, dict[str, object]] = {}
    topic_years: dict[str, set[int]] = {}

    for fact in project_facts:
        year = int(fact.application_year)
        topic_name = _normalize_topic_label(fact.topic_id, fact.topic_name)
        year_state = yearly_stats_map.setdefault(
            year,
            {
                "year": year,
                "applicationCount": 0,
                "topicLabels": set(),
                "fundedCount": 0,
                "fundingAmount": 0.0,
                "scoreValues": [],
            },
        )
        year_state["applicationCount"] = int(year_state["applicationCount"]) + 1
        if topic_name:
            topic_labels = year_state["topicLabels"]
            assert isinstance(topic_labels, set)
            topic_labels.add(topic_name)
            topic_years.setdefault(topic_name, set()).add(year)
        year_state["fundedCount"] = int(year_state["fundedCount"]) + (1 if fact.funded_flag else 0)
        year_state["fundingAmount"] = float(year_state["fundingAmount"]) + float(fact.final_funding_amount)
        if fact.score_proxy is not None:
            score_values = year_state["scoreValues"]
            assert isinstance(score_values, list)
            score_values.append(float(fact.score_proxy))

    yearly_stats = []
    for year in sorted(yearly_stats_map):
        state = yearly_stats_map[year]
        score_values = state["scoreValues"]
        yearly_stats.append(
            {
                "year": year,
                "applicationCount": int(state["applicationCount"]),
                "topicCount": len(state["topicLabels"]),
                "fundedCount": int(state["fundedCount"]),
                "fundingAmount": round(float(state["fundingAmount"]), 6),
                "avgScoreProxy": _average_or_none(score_values),
            }
        )

    active_year_counts = [len(years) for years in topic_years.values()]
    years_covered = [item["year"] for item in yearly_stats]
    return {
        "projectYearsCovered": years_covered,
        "projectYearsCoveredCount": len(years_covered),
        "projectYearlyStats": yearly_stats,
        "projectTopicSpanStats": {
            "totalTopicCount": len(topic_years),
            "singleYearTopicCount": sum(1 for count in active_year_counts if count == 1),
            "multiYearTopicCount": sum(1 for count in active_year_counts if count >= 2),
            "avgActiveYearCount": round(sum(active_year_counts) / len(active_year_counts), 6)
            if active_year_counts
            else 0.0,
            "maxActiveYearCount": max(active_year_counts, default=0),
            "requestedWindowSpan": max(end_year - start_year + 1, 1),
        },
    }


def _load_graph_window_metadata(
    *,
    start_year: int,
    end_year: int,
) -> dict[str, object]:
    return load_graph_window_metadata(start_year=start_year, end_year=end_year)


def _build_project_topic_aggregates(project_facts: list[object]) -> list[ProjectTopicAggregate]:
    return [
        ProjectTopicAggregate(
            topic_key=_normalize_topic_key(item.topic_id),
            topic_label=_normalize_topic_label(item.topic_id, item.topic_name),
            application_count=item.application_count,
            funded_count=item.funded_count,
            funding_amount=item.funding_amount,
            requested_funding_amount=item.requested_funding_amount,
            score_proxy=item.score_proxy,
        )
        for item in build_topic_aggregates(project_facts)
        if item.topic_name
    ]


def _build_project_topic_year_aggregates(project_facts: list[object]) -> list[ProjectTopicYearAggregate]:
    return [
        ProjectTopicYearAggregate(
            topic_key=_normalize_topic_key(item.topic_id),
            topic_label=_normalize_topic_label(item.topic_id, item.topic_name),
            year=item.year,
            application_count=item.application_count,
            funded_count=item.funded_count,
            funding_amount=item.funding_amount,
            requested_funding_amount=item.requested_funding_amount,
        )
        for item in build_topic_year_aggregates(project_facts)
        if item.topic_name and item.year > 0
    ]


def _load_graph_topic_aggregates(
    *,
    start_year: int,
    end_year: int,
) -> list[GraphTopicAggregate]:
    return [
        GraphTopicAggregate(
            topic_key=item.topic_key,
            topic_label=item.topic_label,
            collaboration_density=item.collaboration_density,
            topic_centrality=item.topic_centrality,
            migration_strength=item.migration_strength,
        )
        for item in load_graph_topic_metrics(start_year=start_year, end_year=end_year)
    ]


def _load_topic_migration_edges(
    *,
    start_year: int,
    end_year: int,
) -> list[object]:
    return load_topic_migration_edges(start_year=start_year, end_year=end_year)


def _load_graph_profile():
    return inspect_graph_profile()


def _load_graph_readiness():
    return verify_graph_readiness()


def _merge_topic_aggregates(
    project_rows: list[ProjectTopicAggregate],
    graph_rows: list[GraphTopicAggregate],
    project_year_rows: list[ProjectTopicYearAggregate],
) -> list[BaselineTopicState]:
    graph_by_key = {row.topic_key: row for row in graph_rows}
    year_rows_by_key: dict[str, list[ProjectTopicYearAggregate]] = {}
    for row in project_year_rows:
        year_rows_by_key.setdefault(row.topic_key, []).append(row)
    max_application = max((row.application_count for row in project_rows), default=1)

    topics: list[BaselineTopicState] = []
    for project_row in project_rows:
        graph_row = graph_by_key.get(project_row.topic_key)
        yearly_rows = sorted(year_rows_by_key.get(project_row.topic_key, []), key=lambda item: item.year)
        collaboration_density = graph_row.collaboration_density if graph_row else 0.0
        topic_centrality = graph_row.topic_centrality if graph_row else 0.0
        migration_strength = graph_row.migration_strength if graph_row else 0.0
        funded_ratio = _clamp_unit(project_row.funded_count / max(project_row.application_count, 1))
        avg_funding_per_award = round(project_row.funding_amount / max(project_row.funded_count, 1), 6)
        growth_momentum = _derive_growth_momentum(yearly_rows)
        recent_share = _derive_recent_share(yearly_rows)
        proxy_risk = _derive_proxy_risk(
            project_row=project_row,
            collaboration_density=collaboration_density,
            topic_centrality=topic_centrality,
            max_application=max_application,
        )
        topics.append(
            BaselineTopicState(
                topic_id=project_row.topic_key,
                topic_label=project_row.topic_label,
                application_count=project_row.application_count,
                funded_count=project_row.funded_count,
                funding_amount=round(project_row.funding_amount, 6),
                requested_funding_amount=round(project_row.requested_funding_amount, 6),
                score_proxy=project_row.score_proxy,
                funded_ratio=funded_ratio,
                avg_funding_per_award=avg_funding_per_award,
                growth_momentum=growth_momentum,
                recent_share=recent_share,
                collaboration_density=collaboration_density,
                topic_centrality=topic_centrality,
                migration_strength=migration_strength,
                proxy_risk=proxy_risk,
            )
        )

    topics.sort(key=lambda item: (item.application_count, item.funding_amount), reverse=True)
    return topics


def _derive_proxy_risk(
    *,
    project_row: ProjectTopicAggregate,
    collaboration_density: float,
    topic_centrality: float,
    max_application: int,
) -> float:
    funded_ratio = project_row.funded_count / max(project_row.application_count, 1)
    score_ratio = min(max((project_row.score_proxy or 0.0) / 100.0, 0.0), 1.0)
    scale_ratio = min(max(project_row.application_count / max(max_application, 1), 0.0), 1.0)
    stability = (
        0.35 * funded_ratio
        + 0.25 * score_ratio
        + 0.20 * collaboration_density
        + 0.10 * topic_centrality
        + 0.10 * scale_ratio
    )
    return _clamp_unit(1.0 - stability)


def _derive_growth_momentum(rows: list[ProjectTopicYearAggregate]) -> float:
    if len(rows) < 2:
        return 0.0
    first = rows[0]
    last = rows[-1]
    application_growth = _safe_signed_change(first.application_count, last.application_count)
    funding_growth = _safe_signed_change(first.funding_amount, last.funding_amount)
    return _clamp_signed(0.6 * application_growth + 0.4 * funding_growth)


def _derive_recent_share(rows: list[ProjectTopicYearAggregate]) -> float:
    if not rows:
        return 0.0
    latest_year = max(row.year for row in rows)
    recent_application_count = sum(row.application_count for row in rows if row.year >= latest_year - 1)
    total_application_count = sum(row.application_count for row in rows)
    return _clamp_unit(_safe_ratio(recent_application_count, total_application_count))


def _format_window(start_year: int, end_year: int) -> str:
    return str(start_year) if start_year == end_year else f"{start_year}-{end_year}"


def _normalize_topic_key(value: str) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _clean_topic_label(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_topic_label(topic_key: object, topic_label: object) -> str:
    key = _clean_topic_label(topic_key)
    label = _clean_topic_label(topic_label)
    if not label:
        return _fallback_topic_label(key)
    _, remainder = _split_topic_label_prefix(label)
    return remainder


def _split_topic_label_prefix(label: str) -> tuple[str | None, str]:
    if "-" not in label:
        return None, label
    prefix, remainder = label.split("-", 1)
    prefix = _clean_topic_label(prefix)
    remainder = _clean_topic_label(remainder)
    normalized_prefix = prefix.replace("_", "")
    if (
        prefix
        and remainder
        and len(normalized_prefix) >= 6
        and prefix.isascii()
        and normalized_prefix.isalnum()
    ):
        return prefix, remainder
    return None, label


def _fallback_topic_label(topic_id: str) -> str:
    _, remainder = _split_topic_label_prefix(_clean_topic_label(topic_id))
    return remainder


def _summarize_topic_migration_edges(edges: list[object], limit: int = 12) -> list[dict[str, object]]:
    ranked = sorted(
        edges,
        key=lambda item: (item.migrating_person_count, item.flow_strength, item.target_capture_ratio),
        reverse=True,
    )
    return [
        {
            "sourceTopicKey": item.source_topic_key,
            "sourceTopicLabel": item.source_topic_label,
            "sourceYear": item.source_year,
            "targetTopicKey": item.target_topic_key,
            "targetTopicLabel": item.target_topic_label,
            "targetYear": item.target_year,
            "migratingPersonCount": item.migrating_person_count,
            "sourcePersonCount": item.source_person_count,
            "targetPersonCount": item.target_person_count,
            "flowStrength": item.flow_strength,
            "targetCaptureRatio": item.target_capture_ratio,
        }
        for item in ranked[:limit]
    ]


def _as_float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float_or_zero(value: object) -> float:
    parsed = _as_float_or_none(value)
    return 0.0 if parsed is None else parsed


def _average_or_none(values: object) -> float | None:
    if not isinstance(values, list) or not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 6)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator in (0, 0.0):
        return 0.0
    return float(numerator) / float(denominator)


def _safe_signed_change(previous: float, current: float) -> float:
    return (float(current) - float(previous)) / max(abs(float(previous)), abs(float(current)), 1.0)


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))


def _clamp_signed(value: float) -> float:
    return max(-1.0, min(1.0, round(value, 6)))


def _getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value
