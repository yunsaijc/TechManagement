"""Baseline services for native sandbox simulation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.common.models.simulation import BaselineSnapshot, BaselineTopicState

from . import repository


@dataclass
class ProjectTopicAggregate:
    topic_key: str
    topic_label: str
    application_count: int
    funded_count: int
    funding_amount: float
    score_proxy: float | None


@dataclass
class GraphTopicAggregate:
    topic_key: str
    topic_label: str
    collaboration_density: float
    topic_centrality: float
    migration_strength: float


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
    start_year: int,
    end_year: int,
    persist: bool = True,
) -> BaselineSnapshot:
    if end_year < start_year:
        raise RuntimeError("end_year 不能小于 start_year")

    project_rows = _load_project_topic_aggregates(start_year=start_year, end_year=end_year)
    graph_rows = _load_graph_topic_aggregates(start_year=start_year, end_year=end_year)
    topics = _merge_topic_aggregates(project_rows, graph_rows)
    if not topics:
        raise RuntimeError("未从项目库和图谱中构建出任何 topic baseline")

    return create_baseline_snapshot(
        baseline_id=baseline_id,
        forecast_window=_format_window(start_year, end_year),
        topics=topics,
        assumptions=[
            "baseline_from_project_db_and_neo4j_graph",
            "topic_priority=guide_name_then_department_office",
            "proxy_risk_is_derived_from_observed_project_graph_metrics",
        ],
        metadata={
            "startYear": start_year,
            "endYear": end_year,
            "projectTopicCount": len(project_rows),
            "graphTopicCount": len(graph_rows),
            "topicCount": len(topics),
        },
        persist=persist,
    )


def load_latest_baseline_snapshot() -> BaselineSnapshot | None:
    return repository.load_latest_baseline_snapshot()


def _load_project_topic_aggregates(
    *,
    start_year: int,
    end_year: int,
) -> list[ProjectTopicAggregate]:
    from src.common.database.connection import project_execute

    sql = """
        SELECT
            COALESCE(
                NULLIF(LTRIM(RTRIM(zn.name)), ''),
                NULLIF(LTRIM(RTRIM(b.zxmc)), ''),
                NULLIF(LTRIM(RTRIM(b.zndm)), '')
            ) AS topic_label,
            COUNT(1) AS application_count,
            SUM(CASE WHEN ISNUMERIC(ps.SFLX) = 1 AND CAST(ps.SFLX AS INT) = 1 THEN 1 ELSE 0 END) AS funded_count,
            SUM(CASE WHEN ISNUMERIC(ps.LXJF) = 1 THEN CAST(ps.LXJF AS FLOAT) ELSE 0 END) AS funding_amount,
            AVG(
                CASE
                    WHEN ISNUMERIC(ps.FSFS) = 1 THEN CAST(ps.FSFS AS FLOAT)
                    WHEN ISNUMERIC(ps.WPFS) = 1 THEN CAST(ps.WPFS AS FLOAT)
                    ELSE NULL
                END
            ) AS score_proxy
        FROM Sb_Jbxx b
        LEFT JOIN PGPS_XMPSXX ps ON ps.XMBH = b.id
        LEFT JOIN sys_guide zn ON zn.id = b.zndm
        WHERE ISNUMERIC(b.year) = 1
          AND CAST(b.year AS INT) >= ?
          AND CAST(b.year AS INT) <= ?
        GROUP BY COALESCE(
            NULLIF(LTRIM(RTRIM(zn.name)), ''),
            NULLIF(LTRIM(RTRIM(b.zxmc)), ''),
            NULLIF(LTRIM(RTRIM(b.zndm)), '')
        )
    """
    rows = project_execute(sql, (start_year, end_year))
    aggregates: list[ProjectTopicAggregate] = []
    for row in rows:
        topic_label = _clean_topic_label(getattr(row, "topic_label", None))
        if not topic_label:
            continue
        aggregates.append(
            ProjectTopicAggregate(
                topic_key=_normalize_topic_key(topic_label),
                topic_label=topic_label,
                application_count=int(getattr(row, "application_count", 0) or 0),
                funded_count=int(getattr(row, "funded_count", 0) or 0),
                funding_amount=float(getattr(row, "funding_amount", 0.0) or 0.0),
                score_proxy=_as_float_or_none(getattr(row, "score_proxy", None)),
            )
        )
    return aggregates


def _load_graph_topic_aggregates(
    *,
    start_year: int,
    end_year: int,
) -> list[GraphTopicAggregate]:
    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    uri = _getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687")
    user = _getenv_required("NEO4J_USER", "neo4j")
    password = _getenv_required("NEO4J_PASSWORD")
    database = _getenv_required("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database, notifications_disabled_classifications=["DEPRECATION"]) as session:
            collaboration = {
                row["topic_key"]: row
                for row in session.run(
                    """
                    MATCH (person:Person)-[u:undertakes]->(p:Project)
                    WITH
                        coalesce(p.guideName, p.department, p.office) AS topic_label,
                        coalesce(toInteger(p.year_norm), toInteger(substring(toString(p.period), 0, 4))) AS year,
                        count(u) AS undertakes_edges,
                        count(DISTINCT person) AS person_count,
                        count(DISTINCT p) AS project_count
                    WHERE topic_label IS NOT NULL AND year >= $start_year AND year <= $end_year
                    WITH
                        topic_label,
                        sum(undertakes_edges) AS undertakes_edges,
                        sum(person_count) AS person_count,
                        sum(project_count) AS project_count
                    RETURN
                        toLower(trim(topic_label)) AS topic_key,
                        topic_label,
                        CASE
                            WHEN person_count * project_count = 0 THEN 0.0
                            ELSE toFloat(undertakes_edges) / toFloat(person_count * project_count)
                        END AS collaboration_density
                    """,
                    {"start_year": start_year, "end_year": end_year},
                )
            }
            centrality = {
                row["topic_key"]: row
                for row in session.run(
                    """
                    MATCH (p:Project)
                    OPTIONAL MATCH (p)-[:funded_by]->(f:`Fund/Program`)
                    WITH
                        coalesce(p.guideName, p.department, p.office) AS topic_label,
                        coalesce(toInteger(p.year_norm), toInteger(substring(toString(p.period), 0, 4))) AS year,
                        count(DISTINCT p) AS project_count,
                        count(DISTINCT f) AS fund_count
                    WHERE topic_label IS NOT NULL AND year >= $start_year AND year <= $end_year
                    WITH topic_label, sum(project_count) AS project_count, sum(fund_count) AS fund_count
                    RETURN
                        toLower(trim(topic_label)) AS topic_key,
                        topic_label,
                        CASE
                            WHEN project_count = 0 THEN 0.0
                            ELSE toFloat(fund_count) / toFloat(project_count)
                        END AS topic_centrality
                    """,
                    {"start_year": start_year, "end_year": end_year},
                )
            }
            migration = {
                row["topic_key"]: row
                for row in session.run(
                    """
                    MATCH (person:Person)-[:undertakes]->(p1:Project)
                    WITH
                        person,
                        coalesce(p1.guideName, p1.department, p1.office) AS topic_label,
                        coalesce(toInteger(p1.year_norm), toInteger(substring(toString(p1.period), 0, 4))) AS year
                    WHERE topic_label IS NOT NULL AND year >= $start_year AND year <= $end_year
                    MATCH (person)-[:undertakes]->(p2:Project)
                    WITH
                        topic_label,
                        year,
                        person,
                        collect(
                            DISTINCT CASE
                                WHEN coalesce(toInteger(p2.year_norm), toInteger(substring(toString(p2.period), 0, 4))) IN [year - 1, year + 1]
                                THEN coalesce(p2.guideName, p2.department, p2.office)
                                ELSE NULL
                            END
                        ) AS related_topics
                    WITH
                        topic_label,
                        count(DISTINCT person) AS person_count,
                        count(
                            DISTINCT CASE
                                WHEN any(item IN related_topics WHERE item IS NOT NULL AND item <> topic_label) THEN person
                                ELSE NULL
                            END
                        ) AS migrating_person_count
                    RETURN
                        toLower(trim(topic_label)) AS topic_key,
                        topic_label,
                        CASE
                            WHEN person_count = 0 THEN 0.0
                            ELSE toFloat(migrating_person_count) / toFloat(person_count)
                        END AS migration_strength
                    """,
                    {"start_year": start_year, "end_year": end_year},
                )
            }
    finally:
        driver.close()

    topic_keys = set(collaboration) | set(centrality) | set(migration)
    aggregates: list[GraphTopicAggregate] = []
    for topic_key in sorted(topic_keys):
        label = _coalesce_label(
            collaboration.get(topic_key, {}).get("topic_label"),
            centrality.get(topic_key, {}).get("topic_label"),
            migration.get(topic_key, {}).get("topic_label"),
        )
        if not label:
            continue
        aggregates.append(
            GraphTopicAggregate(
                topic_key=topic_key,
                topic_label=label,
                collaboration_density=_clamp_unit(
                    _as_float_or_zero(collaboration.get(topic_key, {}).get("collaboration_density"))
                ),
                topic_centrality=_clamp_unit(
                    _as_float_or_zero(centrality.get(topic_key, {}).get("topic_centrality"))
                ),
                migration_strength=_clamp_unit(
                    _as_float_or_zero(migration.get(topic_key, {}).get("migration_strength"))
                ),
            )
        )
    return aggregates


def _merge_topic_aggregates(
    project_rows: list[ProjectTopicAggregate],
    graph_rows: list[GraphTopicAggregate],
) -> list[BaselineTopicState]:
    graph_by_key = {row.topic_key: row for row in graph_rows}
    max_application = max((row.application_count for row in project_rows), default=1)

    topics: list[BaselineTopicState] = []
    for project_row in project_rows:
        graph_row = graph_by_key.get(project_row.topic_key)
        collaboration_density = graph_row.collaboration_density if graph_row else 0.0
        topic_centrality = graph_row.topic_centrality if graph_row else 0.0
        migration_strength = graph_row.migration_strength if graph_row else 0.0
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
                score_proxy=project_row.score_proxy,
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


def _format_window(start_year: int, end_year: int) -> str:
    return str(start_year) if start_year == end_year else f"{start_year}-{end_year}"


def _normalize_topic_key(value: str) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _clean_topic_label(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _coalesce_label(*values: object) -> str:
    for value in values:
        cleaned = _clean_topic_label(value)
        if cleaned:
            return cleaned
    return ""


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


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))


def _getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value
