"""Baseline services for native sandbox simulation."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from src.common.models.simulation import BaselineSnapshot, BaselineTopicState
from src.services.sandbox.data import (
    build_topic_aggregates,
    build_topic_year_aggregates,
    load_graph_topic_metrics,
    load_graph_window_metadata,
    load_project_facts,
)

from . import repository

DEFAULT_BASELINE_START_YEAR = 2020


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
    snapshot = BaselineSnapshot(
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        topics=topics,
        assumptions=assumptions or [],
        metadata=metadata or {},
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
    project_rows = _load_project_topic_aggregates(start_year=window.start_year, end_year=window.end_year)
    project_year_rows = _load_project_topic_year_aggregates(start_year=window.start_year, end_year=window.end_year)
    project_window_metadata = _load_project_window_metadata(start_year=window.start_year, end_year=window.end_year)
    project_load_seconds = round(time.perf_counter() - project_load_started, 3)

    graph_load_started = time.perf_counter()
    graph_rows = _load_graph_topic_aggregates(start_year=window.start_year, end_year=window.end_year)
    graph_window_metadata = _load_graph_window_metadata(start_year=window.start_year, end_year=window.end_year)
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
            "projectTopicCount": len(project_rows),
            "projectTopicYearCount": len(project_year_rows),
            "graphTopicCount": len(graph_rows),
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
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    from src.common.database.connection import project_execute

    sql = """
        SELECT MAX(CAST(b.year AS INT)) AS latest_year
        FROM Sb_Jbxx b
        INNER JOIN Sb_Sbzt sbzt ON sbzt.onlysign = b.id
        WHERE sbzt.gkAudit = '1'
          AND ISNUMERIC(b.year) = 1
          AND CAST(b.year AS INT) >= 2020
    """
    rows = project_execute(sql)
    if not rows:
        return None
    latest_year = getattr(rows[0], "latest_year", None)
    if latest_year in (None, ""):
        return None
    return int(latest_year)


def _load_project_window_metadata(
    *,
    start_year: int,
    end_year: int,
) -> dict[str, object]:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    from src.common.database.connection import project_execute

    annual_sql = """
        WITH reviewed_projects AS (
            SELECT
                CAST(b.year AS INT) AS project_year,
                b.id AS project_id,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(zn.name)), ''),
                    NULLIF(LTRIM(RTRIM(zx.name)), ''),
                    NULLIF(LTRIM(RTRIM(b.zxmc)), ''),
                    NULLIF(LTRIM(RTRIM(b.zndm)), '')
                ) AS topic_label
            FROM Sb_Jbxx b
            INNER JOIN Sb_Sbzt sbzt ON sbzt.onlysign = b.id
            LEFT JOIN sys_guide zx ON zx.id = b.zxmc
            LEFT JOIN sys_guide zn ON zn.id = b.zndm
            WHERE sbzt.gkAudit = '1'
              AND ISNUMERIC(b.year) = 1
              AND CAST(b.year AS INT) >= ?
              AND CAST(b.year AS INT) <= ?
        ),
        review_scores AS (
            SELECT
                ps.XMBH AS project_id,
                AVG(
                    CASE
                        WHEN ISNUMERIC(ps.FSFS) = 1 THEN CAST(ps.FSFS AS FLOAT)
                        WHEN ISNUMERIC(ps.WPFS) = 1 THEN CAST(ps.WPFS AS FLOAT)
                        ELSE NULL
                    END
                ) AS score_proxy
            FROM PS_XMPSXX ps
            GROUP BY ps.XMBH
        ),
        contract_budget AS (
            SELECT
                htxx.onlysign AS project_id,
                MAX(CASE WHEN NULLIF(LTRIM(RTRIM(htxx.xmbh)), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_contract_number,
                SUM(CASE WHEN ISNUMERIC(htjf.zxjf) = 1 THEN CAST(htjf.zxjf AS FLOAT) ELSE 0 END) AS final_funding_amount
            FROM Ht_Jbxx htxx
            LEFT JOIN Ht_Jfgs htjf
                ON htjf.onlysign = htxx.id
               AND (
                    ISNUMERIC(CAST(htjf.yskmbh AS VARCHAR(32))) = 1
                    AND CAST(htjf.yskmbh AS INT) = 1
               )
            GROUP BY htxx.onlysign
        ),
        award_status AS (
            SELECT
                lx.XMBH AS project_id,
                MAX(CASE WHEN ISNUMERIC(CAST(lx.SFLX AS VARCHAR(32))) = 1 AND CAST(lx.SFLX AS INT) = 1 THEN 1 ELSE 0 END) AS funded_flag,
                MAX(CASE WHEN NULLIF(LTRIM(RTRIM(lx.LXBH)), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_award_number,
                MAX(CASE WHEN ISNUMERIC(lx.LXJF) = 1 THEN CAST(lx.LXJF AS FLOAT) ELSE 0 END) AS award_funding_amount
            FROM Ht_XMLXXX lx
            GROUP BY lx.XMBH
        ),
        project_metrics AS (
            SELECT
                rp.project_year,
                rp.topic_label,
                rp.project_id,
                CASE
                    WHEN COALESCE(award.funded_flag, 0) = 1 THEN 1
                    WHEN COALESCE(contract.has_contract_number, 0) = 1 THEN 1
                    WHEN COALESCE(award.has_award_number, 0) = 1 THEN 1
                    ELSE 0
                END AS funded_flag,
                CASE
                    WHEN COALESCE(contract.final_funding_amount, 0) > 0 THEN contract.final_funding_amount
                    WHEN COALESCE(award.award_funding_amount, 0) > 0 THEN award.award_funding_amount
                    ELSE 0.0
                END AS funding_amount,
                COALESCE(review.score_proxy, NULL) AS score_proxy
            FROM reviewed_projects rp
            LEFT JOIN review_scores review ON review.project_id = rp.project_id
            LEFT JOIN contract_budget contract ON contract.project_id = rp.project_id
            LEFT JOIN award_status award ON award.project_id = rp.project_id
        )
        SELECT
            project_year,
            COUNT(1) AS application_count,
            COUNT(DISTINCT topic_label) AS topic_count,
            SUM(funded_flag) AS funded_count,
            SUM(funding_amount) AS funding_amount,
            AVG(score_proxy) AS avg_score_proxy
        FROM project_metrics
        GROUP BY project_year
        ORDER BY project_year
    """
    annual_rows = project_execute(annual_sql, (start_year, end_year))
    yearly_stats = [
        {
            "year": int(getattr(row, "project_year", 0) or 0),
            "applicationCount": int(getattr(row, "application_count", 0) or 0),
            "topicCount": int(getattr(row, "topic_count", 0) or 0),
            "fundedCount": int(getattr(row, "funded_count", 0) or 0),
            "fundingAmount": round(float(getattr(row, "funding_amount", 0.0) or 0.0), 6),
            "avgScoreProxy": _as_float_or_none(getattr(row, "avg_score_proxy", None)),
        }
        for row in annual_rows
    ]

    span_sql = """
        WITH reviewed_projects AS (
            SELECT
                CAST(b.year AS INT) AS project_year,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(zn.name)), ''),
                    NULLIF(LTRIM(RTRIM(zx.name)), ''),
                    NULLIF(LTRIM(RTRIM(b.zxmc)), ''),
                    NULLIF(LTRIM(RTRIM(b.zndm)), '')
                ) AS topic_label
            FROM Sb_Jbxx b
            INNER JOIN Sb_Sbzt sbzt ON sbzt.onlysign = b.id
            LEFT JOIN sys_guide zx ON zx.id = b.zxmc
            LEFT JOIN sys_guide zn ON zn.id = b.zndm
            WHERE sbzt.gkAudit = '1'
              AND ISNUMERIC(b.year) = 1
              AND CAST(b.year AS INT) >= ?
              AND CAST(b.year AS INT) <= ?
        ),
        topic_span AS (
            SELECT
                topic_label,
                COUNT(DISTINCT project_year) AS active_year_count
            FROM reviewed_projects
            WHERE NULLIF(LTRIM(RTRIM(topic_label)), '') IS NOT NULL
            GROUP BY topic_label
        )
        SELECT
            COUNT(1) AS total_topic_count,
            SUM(CASE WHEN active_year_count = 1 THEN 1 ELSE 0 END) AS single_year_topic_count,
            SUM(CASE WHEN active_year_count >= 2 THEN 1 ELSE 0 END) AS multi_year_topic_count,
            AVG(CAST(active_year_count AS FLOAT)) AS avg_active_year_count,
            MAX(active_year_count) AS max_active_year_count
        FROM topic_span
    """
    span_rows = project_execute(span_sql, (start_year, end_year))
    span_row = span_rows[0] if span_rows else None

    years_covered = [item["year"] for item in yearly_stats]
    return {
        "projectYearsCovered": years_covered,
        "projectYearsCoveredCount": len(years_covered),
        "projectYearlyStats": yearly_stats,
        "projectTopicSpanStats": {
            "totalTopicCount": int(getattr(span_row, "total_topic_count", 0) or 0),
            "singleYearTopicCount": int(getattr(span_row, "single_year_topic_count", 0) or 0),
            "multiYearTopicCount": int(getattr(span_row, "multi_year_topic_count", 0) or 0),
            "avgActiveYearCount": round(_as_float_or_zero(getattr(span_row, "avg_active_year_count", 0.0)), 6),
            "maxActiveYearCount": int(getattr(span_row, "max_active_year_count", 0) or 0),
        },
    }


def _load_graph_window_metadata(
    *,
    start_year: int,
    end_year: int,
) -> dict[str, object]:
    return load_graph_window_metadata(start_year=start_year, end_year=end_year)


def _load_project_topic_aggregates(
    *,
    start_year: int,
    end_year: int,
) -> list[ProjectTopicAggregate]:
    project_facts = load_project_facts(start_year=start_year, end_year=end_year)
    return [
        ProjectTopicAggregate(
            topic_key=_normalize_topic_key(item.topic_id),
            topic_label=item.topic_name,
            application_count=item.application_count,
            funded_count=item.funded_count,
            funding_amount=item.funding_amount,
            requested_funding_amount=item.requested_funding_amount,
            score_proxy=item.score_proxy,
        )
        for item in build_topic_aggregates(project_facts)
        if item.topic_name
    ]


def _load_project_topic_year_aggregates(
    *,
    start_year: int,
    end_year: int,
) -> list[ProjectTopicYearAggregate]:
    project_facts = load_project_facts(start_year=start_year, end_year=end_year)
    return [
        ProjectTopicYearAggregate(
            topic_key=_normalize_topic_key(item.topic_id),
            topic_label=item.topic_name,
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
                topic_id=project_row.topic_label,
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
