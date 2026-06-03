"""Read-only Neo4j knowledge graph adapter for the sandbox frontend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase, Query

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


DISPLAY_KEYS = (
    "projectName",
    "name",
    "title",
    "projectId",
    "guideName",
    "department",
    "office",
    "year_norm",
    "period",
    "projectStatus",
    "budget",
)

TYPE_LABELS = {
    "Project": "项目",
    "Person": "人员",
    "Organization": "机构",
    "Org": "机构",
    "Paper": "论文",
    "Concept": "概念",
    "DisciplineL1": "一级学科",
    "DisciplineL2": "二级学科",
    "DisciplineL3": "三级学科",
    "Fund/Program": "计划",
    "Policy": "政策",
    "Output": "成果",
    "Venue": "期刊/会议",
}

RELATION_LABELS = {
    "undertakes": "承担",
    "works_for": "任职/隶属",
    "authored_by": "作者",
    "produces": "产出",
    "published_in": "发表在",
    "funded_by": "资助",
    "collaborates_with": "协作",
    "reviews": "评审",
    "RELATES_TO_DISCIPLINE": "关联学科",
    "SUB_OF": "隶属",
}

RELATION_PATTERN = (
    "undertakes|works_for|authored_by|produces|published_in|funded_by|"
    "collaborates_with|reviews|RELATES_TO_DISCIPLINE|SUB_OF"
)

VIEW_RELATION_PATTERNS = {
    "all": RELATION_PATTERN,
    "project_person": "undertakes|authored_by|works_for|reviews|collaborates_with",
    "project_program": "funded_by",
    "project_output": "produces|published_in|authored_by",
    "discipline": "RELATES_TO_DISCIPLINE|SUB_OF",
    "organization": "undertakes|works_for|collaborates_with",
}

START_LABELS = {
    "project": "Project",
    "person": "Person",
    "organization": "Organization",
    "paper": "Paper",
    "concept": "Concept",
    "discipline": "DisciplineL2",
    "output": "Output",
    "venue": "Venue",
    "policy": "Policy",
}

TYPE_LABEL_TO_LABEL = {value: key for key, value in TYPE_LABELS.items()}


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str


def _config() -> Neo4jConfig:
    password = os.getenv("NEO4J_PASSWORD", "")
    if not password:
        raise RuntimeError("缺少 NEO4J_PASSWORD 配置")
    return Neo4jConfig(
        uri=os.getenv("NEO4J_URI", "neo4j://192.168.0.198:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=password,
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )


def _primary_label(labels: list[str]) -> str:
    for label in labels:
        if label in TYPE_LABELS:
            return label
    return labels[0] if labels else "Node"


def _node_title(props: dict[str, Any], labels: list[str], fallback_id: int) -> str:
    for key in ("projectName", "name", "title", "projectId", "displayName", "label"):
        value = props.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    label = _primary_label(labels)
    return f"{TYPE_LABELS.get(label, label)} #{fallback_id}"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _compact_props(props: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in DISPLAY_KEYS:
        value = props.get(key)
        if value is not None and str(value).strip():
            compact[key] = _json_safe(value)
    return compact


def _add_node(nodes: dict[int, dict[str, Any]], raw_node: Any) -> None:
    node_id = int(raw_node.element_id.split(":")[-1]) if ":" in raw_node.element_id else hash(raw_node.element_id)
    if node_id in nodes:
        return
    props = dict(raw_node)
    labels = list(raw_node.labels)
    primary = _primary_label(labels)
    nodes[node_id] = {
        "id": str(node_id),
        "elementId": raw_node.element_id,
        "label": _node_title(props, labels, node_id),
        "type": primary,
        "typeLabel": TYPE_LABELS.get(primary, primary),
        "labels": labels,
        "properties": _compact_props(props),
    }


def _add_relationship(edges: dict[str, dict[str, Any]], raw_rel: Any) -> None:
    rel_id = raw_rel.element_id
    if rel_id in edges:
        return
    rel_type = raw_rel.type
    start_id = int(raw_rel.start_node.element_id.split(":")[-1]) if ":" in raw_rel.start_node.element_id else hash(raw_rel.start_node.element_id)
    end_id = int(raw_rel.end_node.element_id.split(":")[-1]) if ":" in raw_rel.end_node.element_id else hash(raw_rel.end_node.element_id)
    edges[rel_id] = {
        "id": rel_id,
        "source": str(start_id),
        "target": str(end_id),
        "type": rel_type,
        "label": RELATION_LABELS.get(rel_type, rel_type),
        "properties": _json_safe(dict(raw_rel)),
    }


def _label_expr(label: str) -> str:
    return f"`{label}`"


def _summarize_graph(nodes: dict[int, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    node_rows = list(nodes.values())
    node_ids = {node["id"] for node in node_rows}
    edge_rows = [
        edge
        for edge in edges.values()
        if edge["source"] in node_ids and edge["target"] in node_ids
    ]
    type_counts: dict[str, int] = {}
    for node in node_rows:
        type_counts[node["typeLabel"]] = type_counts.get(node["typeLabel"], 0) + 1
    return node_rows, edge_rows, type_counts


def _query_payload(query: str, year: int | None, limit: int, offset: int, view: str, start: str) -> tuple[str, dict[str, Any]]:
    capped_limit = max(5, min(int(limit or 30), 120))
    capped_offset = max(0, int(offset or 0))
    safe_view = view if view in VIEW_RELATION_PATTERNS else "all"
    relation_pattern = VIEW_RELATION_PATTERNS[safe_view]
    safe_start = start if start in START_LABELS else "project"
    start_label = START_LABELS[safe_start]
    start_label_expr = _label_expr(start_label)
    params: dict[str, Any] = {
        "limit": capped_limit,
        "probeLimit": capped_limit + 1,
        "offset": capped_offset,
        "neighborLimit": capped_limit * 3,
        "relLimit": capped_limit * 3,
        "query": (query or "").strip(),
        "year": year,
        "view": safe_view,
        "start": safe_start,
    }
    project_year_filter = "seed.year_norm = $year AND" if safe_start == "project" and year is not None else ""
    if params["query"]:
        cypher = f"""
        MATCH (seed:{start_label_expr})
        WHERE {project_year_filter} (
          toLower(coalesce(seed.projectName, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.projectId, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.guideName, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.department, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.office, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.name, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.title, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.label, '')) CONTAINS toLower($query)
        )
        WITH seed ORDER BY elementId(seed) SKIP $offset LIMIT $probeLimit
        WITH collect(seed) AS probeSeeds
        WITH probeSeeds[0..$limit] AS pageSeeds, size(probeSeeds) > $limit AS hasMore
        UNWIND pageSeeds AS seed
        OPTIONAL MATCH (seed)-[r:{relation_pattern}]-(n)
        WITH collect(DISTINCT seed) AS projects,
             collect(DISTINCT n)[0..$neighborLimit] AS neighbors,
             collect(DISTINCT r)[0..$relLimit] AS relationships,
             hasMore
        RETURN projects,
               neighbors,
               relationships,
               hasMore
        """
        return cypher, params

    no_query_filter = "seed.year_norm = $year" if safe_start == "project" and year is not None else "true"
    cypher = f"""
    MATCH (seed:{start_label_expr})
    WHERE {no_query_filter}
    WITH seed ORDER BY elementId(seed) SKIP $offset LIMIT $probeLimit
    WITH collect(seed) AS probeSeeds
    WITH probeSeeds[0..$limit] AS pageSeeds, size(probeSeeds) > $limit AS hasMore
    UNWIND pageSeeds AS seed
    OPTIONAL MATCH (seed)-[r:{relation_pattern}]-(n)
    WITH collect(DISTINCT seed) AS projects,
         collect(DISTINCT n)[0..$neighborLimit] AS neighbors,
         collect(DISTINCT r)[0..$relLimit] AS relationships,
         hasMore
    RETURN projects,
           neighbors,
           relationships,
           hasMore
    """
    return cypher, params


def load_knowledge_graph(*, query: str = "", year: int | None = None, limit: int = 30, offset: int = 0, view: str = "all", start: str = "project") -> dict[str, Any]:
    """Load a bounded project-centered subgraph from Neo4j."""
    cfg = _config()
    cypher, params = _query_payload(query=query, year=year, limit=limit, offset=offset, view=view, start=start)
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    has_more = False
    try:
        with driver.session(database=cfg.database) as session:
            record = session.run(cypher, params).single()
            if record:
                has_more = bool(record.get("hasMore", False))
                for raw_node in list(record["projects"] or []) + list(record["neighbors"] or []):
                    if raw_node is not None:
                        _add_node(nodes, raw_node)
                for raw_rel in record["relationships"] or []:
                    if raw_rel is not None:
                        _add_relationship(edges, raw_rel)
    finally:
        driver.close()

    node_rows, edge_rows, type_counts = _summarize_graph(nodes, edges)

    return {
        "status": "ok",
        "source": cfg.uri,
        "query": params["query"],
        "year": year,
        "limit": params["limit"],
        "offset": params["offset"],
        "nextOffset": params["offset"] + params["limit"],
        "hasMore": has_more,
        "view": params["view"],
        "start": params["start"],
        "nodes": node_rows,
        "edges": edge_rows,
        "typeCounts": type_counts,
        "totals": {
            "nodes": len(node_rows),
            "relationships": len(edge_rows),
        },
    }


def _wide_query_payload(
    *,
    start: str,
    view: str,
    query: str,
    year: int | None,
    batch_limit: int,
    offset: int,
) -> tuple[str, dict[str, Any]]:
    safe_start = start if start in START_LABELS else "project"
    safe_view = view if view in VIEW_RELATION_PATTERNS else "all"
    start_label_expr = _label_expr(START_LABELS[safe_start])
    relation_pattern = VIEW_RELATION_PATTERNS[safe_view]
    params: dict[str, Any] = {
        "limit": max(5, min(int(batch_limit or 40), 120)),
        "perSeedRelLimit": max(2, min(int(batch_limit or 40) // 2, 12)),
        "offset": max(0, int(offset or 0)),
        "query": (query or "").strip(),
        "year": year,
    }
    project_year_filter = "seed.year_norm = $year AND" if safe_start == "project" and year is not None else ""
    if params["query"]:
        where_clause = f"""{project_year_filter} (
          toLower(coalesce(seed.projectName, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.projectId, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.guideName, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.department, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.office, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.name, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.title, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.label, '')) CONTAINS toLower($query)
        )"""
    else:
        where_clause = "seed.year_norm = $year" if safe_start == "project" and year is not None else "true"

    cypher = f"""
    MATCH (seed:{start_label_expr})
    WHERE {where_clause}
    WITH seed ORDER BY elementId(seed) SKIP $offset LIMIT $limit
    WITH collect(seed) AS seeds
    UNWIND seeds AS seed
    CALL {{
      WITH seed
      OPTIONAL MATCH (seed)-[r:{relation_pattern}]-(n)
      WITH r, n ORDER BY elementId(r) LIMIT $perSeedRelLimit
      RETURN collect(DISTINCT n) AS localNeighbors,
             collect(DISTINCT r) AS localRelationships
    }}
    WITH seeds,
         reduce(acc = [], chunk IN collect(localNeighbors) | acc + chunk) AS neighborChunks,
         reduce(acc = [], chunk IN collect(localRelationships) | acc + chunk) AS relationshipChunks
    RETURN seeds,
           [node IN neighborChunks WHERE node IS NOT NULL] AS neighbors,
           [rel IN relationshipChunks WHERE rel IS NOT NULL] AS relationships
    """
    return cypher, params


def load_knowledge_graph_wide(
    *,
    query: str = "",
    year: int | None = None,
    full_library: bool = False,
    batch_limit: int = 42,
    pages_per_combo: int = 8,
    offset_stride: int = 6,
    node_limit: int = 9000,
    edge_limit: int = 14000,
    timeout_seconds: float = 18.0,
    task_offset: int = 0,
    task_limit: int = 0,
) -> dict[str, Any]:
    """Load a broad, de-duplicated sample across labels and relationship views.

    The database can contain tens or hundreds of millions of nodes, so this is
    intentionally a bounded broad sample for frontend visualization rather than
    an all-at-once export.
    """
    cfg = _config()
    safe_batch_limit = max(5, min(int(batch_limit or 42), 120))
    safe_pages = max(1, min(int(pages_per_combo or 8), 24))
    safe_stride = max(1, min(int(offset_stride or 6), 500))
    safe_node_limit = max(100, min(int(node_limit or 9000), 20000))
    safe_edge_limit = max(100, min(int(edge_limit or 14000), 30000))
    safe_task_offset = max(0, int(task_offset or 0))
    safe_task_limit = max(0, min(int(task_limit or 0), 120))
    effective_query = "" if full_library else (query or "").strip()
    effective_year = None if full_library else year
    starts = list(START_LABELS)
    views = list(VIEW_RELATION_PATTERNS)
    all_tasks = [
        (start, view, page_index)
        for start in starts
        for view in views
        for page_index in range(safe_pages)
    ]
    selected_tasks = all_tasks[safe_task_offset:]
    if safe_task_limit:
        selected_tasks = selected_tasks[:safe_task_limit]
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    failed_pages: list[dict[str, Any]] = []
    scanned_pages = 0
    scanned_combos_set: set[tuple[str, str]] = set()
    reached_limit = False

    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            for start, view, page_index in selected_tasks:
                scanned_combos_set.add((start, view))
                offset = page_index * safe_batch_limit * safe_stride
                cypher, params = _wide_query_payload(
                    start=start,
                    view=view,
                    query=effective_query,
                    year=effective_year,
                    batch_limit=safe_batch_limit,
                    offset=offset,
                )
                scanned_pages += 1
                try:
                    record = session.run(Query(cypher, timeout=timeout_seconds), params).single()
                except Exception as exc:  # broad sampling should continue past slow combinations
                    failed_pages.append({
                        "start": start,
                        "view": view,
                        "offset": offset,
                        "reason": str(exc)[:180],
                    })
                    continue
                if not record:
                    continue
                for raw_node in list(record["seeds"] or []) + list(record["neighbors"] or []):
                    if raw_node is not None and len(nodes) < safe_node_limit:
                        _add_node(nodes, raw_node)
                for raw_rel in record["relationships"] or []:
                    if raw_rel is not None and len(edges) < safe_edge_limit:
                        _add_relationship(edges, raw_rel)
                if len(nodes) >= safe_node_limit or len(edges) >= safe_edge_limit:
                    reached_limit = True
                    break
    finally:
        driver.close()

    node_rows, edge_rows, type_counts = _summarize_graph(nodes, edges)
    next_task_offset = safe_task_offset + len(selected_tasks)
    has_more_tasks = next_task_offset < len(all_tasks)
    return {
        "status": "ok",
        "source": cfg.uri,
        "mode": "full_library" if full_library else "filtered_wide",
        "query": effective_query,
        "year": effective_year,
        "limit": safe_batch_limit,
        "offset": 0,
        "nextOffset": scanned_pages,
        "hasMore": has_more_tasks,
        "view": "wide",
        "start": "wide",
        "nodes": node_rows,
        "edges": edge_rows,
        "typeCounts": type_counts,
        "totals": {
            "nodes": len(node_rows),
            "relationships": len(edge_rows),
        },
        "coverage": {
            "combos": len(scanned_combos_set),
            "pages": scanned_pages,
            "failedPages": len(failed_pages),
            "failedPageSamples": failed_pages[:8],
            "starts": starts,
            "views": views,
            "batchLimit": safe_batch_limit,
            "pagesPerCombo": safe_pages,
            "offsetStride": safe_stride,
            "nodeLimit": safe_node_limit,
            "edgeLimit": safe_edge_limit,
            "reachedLimit": reached_limit,
            "taskOffset": safe_task_offset,
            "nextTaskOffset": next_task_offset,
            "taskLimit": safe_task_limit,
            "totalTasks": len(all_tasks),
            "hasMoreTasks": has_more_tasks,
        },
    }


def load_knowledge_graph_overview(*, sample_per_label: int = 24, sample_per_relation: int = 12) -> dict[str, Any]:
    """Fast whole-library overview using Neo4j count store plus small samples.

    This returns global counts for frontend cluster rendering, and only a small
    representative set of real nodes/relationships for drill-down. It avoids
    deep SKIP/OFFSET scans so the page can respond quickly on very large graphs.
    """
    cfg = _config()
    safe_node_sample = max(3, min(int(sample_per_label or 24), 60))
    safe_rel_sample = max(2, min(int(sample_per_relation or 12), 40))
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    label_counts: dict[str, int] = {}
    rel_type_counts: dict[str, int] = {}
    cluster_edges: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []

    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            for label in dict.fromkeys(START_LABELS.values()):
                label_expr = _label_expr(label)
                try:
                    count_record = session.run(
                        Query(f"MATCH (n:{label_expr}) RETURN count(n) AS total", timeout=12.0)
                    ).single()
                except Exception as exc:
                    warnings.append({"scope": f"label-count:{label}", "reason": str(exc)[:180]})
                    continue
                total = int(count_record["total"] or 0) if count_record else 0
                label_counts[TYPE_LABELS.get(label, label)] = total
                if total <= 0:
                    continue
                try:
                    sample_records = session.run(
                        Query(
                            f"MATCH (n:{label_expr}) "
                            "RETURN n LIMIT $limit",
                            timeout=6.0,
                        ),
                        {"limit": safe_node_sample},
                    )
                    for record in sample_records:
                        _add_node(nodes, record["n"])
                except Exception as exc:
                    warnings.append({"scope": f"label-sample:{label}", "reason": str(exc)[:180]})

            for rel_type in RELATION_PATTERN.split("|"):
                rel_expr = f"`{rel_type}`"
                try:
                    count_record = session.run(
                        Query(f"MATCH ()-[r:{rel_expr}]->() RETURN count(r) AS total", timeout=12.0)
                    ).single()
                except Exception as exc:
                    warnings.append({"scope": f"rel-count:{rel_type}", "reason": str(exc)[:180]})
                    continue
                total = int(count_record["total"] or 0) if count_record else 0
                rel_type_counts[RELATION_LABELS.get(rel_type, rel_type)] = total
                if total <= 0:
                    continue
                try:
                    sample_records = session.run(
                        Query(
                            f"MATCH (a)-[r:{rel_expr}]->(b) "
                            "RETURN a, r, b LIMIT $limit",
                            timeout=6.0,
                        ),
                        {"limit": safe_rel_sample},
                    )
                    for record in sample_records:
                        _add_node(nodes, record["a"])
                        _add_node(nodes, record["b"])
                        _add_relationship(edges, record["r"])
                        source_label = TYPE_LABELS.get(_primary_label(list(record["a"].labels)), _primary_label(list(record["a"].labels)))
                        target_label = TYPE_LABELS.get(_primary_label(list(record["b"].labels)), _primary_label(list(record["b"].labels)))
                        if source_label == target_label:
                            continue
                        key = " -> ".join(sorted([source_label, target_label]))
                        current = cluster_edges.get(key) or {
                            "id": f"overview:{key}",
                            "sourceLabel": source_label,
                            "targetLabel": target_label,
                            "label": "类型关联",
                            "type": "overview",
                            "count": 0,
                        }
                        current["count"] += 1
                        cluster_edges[key] = current
                except Exception as exc:
                    warnings.append({"scope": f"rel-sample:{rel_type}", "reason": str(exc)[:180]})
    finally:
        driver.close()

    node_rows, edge_rows, sample_type_counts = _summarize_graph(nodes, edges)
    return {
        "status": "ok",
        "source": cfg.uri,
        "mode": "overview",
        "query": "",
        "year": None,
        "limit": safe_node_sample,
        "offset": 0,
        "nextOffset": 0,
        "hasMore": False,
        "view": "overview",
        "start": "overview",
        "nodes": node_rows,
        "edges": edge_rows,
        "typeCounts": label_counts,
        "sampleTypeCounts": sample_type_counts,
        "relationshipTypeCounts": rel_type_counts,
        "clusterEdges": list(cluster_edges.values()),
        "totals": {
            "nodes": sum(label_counts.values()),
            "relationships": sum(rel_type_counts.values()),
            "sampleNodes": len(node_rows),
            "sampleRelationships": len(edge_rows),
        },
        "coverage": {
            "mode": "overview",
            "combos": len(label_counts),
            "pages": 1,
            "failedPages": 0,
            "warnings": warnings[:12],
            "warningCount": len(warnings),
            "samplePerLabel": safe_node_sample,
            "samplePerRelation": safe_rel_sample,
        },
    }


def _seed_text_filter(*, safe_start: str, year: int | None, query: str) -> str:
    project_year_filter = "seed.year_norm = $year AND" if safe_start == "project" and year is not None else ""
    text = (query or "").strip()
    if text:
        return f"""{project_year_filter} (
          toLower(coalesce(seed.projectName, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.projectId, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.guideName, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.department, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.office, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.name, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.title, '')) CONTAINS toLower($query)
          OR toLower(coalesce(seed.label, '')) CONTAINS toLower($query)
        )"""
    return "seed.year_norm = $year" if safe_start == "project" and year is not None else "true"


def _type_nodes_query_payload(
    *,
    type_label: str,
    query: str = "",
    year: int | None = None,
    limit: int = 80,
    offset: int = 0,
    view: str = "all",
    start: str = "project",
) -> tuple[str, dict[str, Any], bool]:
    """Build a bounded type-page query.

  Returns (cypher, params, scoped). When scoped is True, results are limited to
  nodes reachable from the current search seeds instead of scanning the whole label.
    """
    raw_label = TYPE_LABEL_TO_LABEL.get(type_label, type_label)
    if raw_label not in TYPE_LABELS:
        raise ValueError(f"不支持的节点类型：{type_label}")
    safe_limit = max(10, min(int(limit or 80), 500))
    safe_offset = max(0, int(offset or 0))
    safe_view = view if view in VIEW_RELATION_PATTERNS else "all"
    safe_start = start if start in START_LABELS else "project"
    start_label = START_LABELS[safe_start]
    start_label_expr = _label_expr(start_label)
    target_label_expr = _label_expr(raw_label)
    relation_pattern = VIEW_RELATION_PATTERNS[safe_view]
    params: dict[str, Any] = {
        "limit": safe_limit,
        "probeLimit": safe_limit + 1,
        "offset": safe_offset,
        "query": (query or "").strip(),
        "year": year,
        "view": safe_view,
        "start": safe_start,
    }
    scoped = bool(params["query"]) or (safe_start == "project" and year is not None)
    if not scoped:
        cypher = f"""
        MATCH (n:{target_label_expr})
        WITH n ORDER BY elementId(n) SKIP $offset LIMIT $probeLimit
        WITH collect(n) AS probeNodes
        WITH probeNodes[0..$limit] AS pageNodes, size(probeNodes) > $limit AS hasMore
        UNWIND pageNodes AS n
        RETURN collect(n) AS nodes, hasMore
        """
        return cypher, params, False

    seed_where = _seed_text_filter(safe_start=safe_start, year=year, query=query)
    if raw_label == start_label:
        cypher = f"""
        MATCH (seed:{start_label_expr})
        WHERE {seed_where}
        WITH seed ORDER BY elementId(seed) SKIP $offset LIMIT $probeLimit
        WITH collect(seed) AS probeNodes
        WITH probeNodes[0..$limit] AS pageNodes, size(probeNodes) > $limit AS hasMore
        UNWIND pageNodes AS n
        RETURN collect(n) AS nodes, hasMore
        """
        return cypher, params, True

    cypher = f"""
    MATCH (seed:{start_label_expr})
    WHERE {seed_where}
    MATCH (seed)-[:{relation_pattern}]-(n:{target_label_expr})
    WITH DISTINCT n
    ORDER BY elementId(n)
    SKIP $offset LIMIT $probeLimit
    WITH collect(n) AS probeNodes
    WITH probeNodes[0..$limit] AS pageNodes, size(probeNodes) > $limit AS hasMore
    UNWIND pageNodes AS n
    RETURN collect(n) AS nodes, hasMore
    """
    return cypher, params, True


def _run_neo4j_single(session, cypher: str, params: dict[str, Any], *, timeout_seconds: float, retries: int = 1):
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        current_timeout = timeout_seconds * (1.0 + 0.75 * attempt)
        try:
            return session.run(Query(cypher, timeout=current_timeout), params).single()
        except Exception as exc:
            last_exc = exc
            message = str(exc)
            if attempt >= retries or "TransactionTimedOut" not in message and "terminated" not in message.lower():
                raise
    if last_exc is not None:
        raise last_exc
    return None


def _load_type_nodes_from_context(
    *,
    type_label: str,
    context_element_ids: list[str],
    query: str = "",
    year: int | None = None,
    view: str = "all",
    start: str = "project",
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    cfg = _config()
    element_ids = [item.strip() for item in context_element_ids if str(item).strip()]
    if not element_ids:
        raise ValueError("缺少可展开的上下文节点")
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            record = _run_neo4j_single(
                session,
                """
                UNWIND $elementIds AS eid
                MATCH (n) WHERE elementId(n) = eid
                WITH collect(DISTINCT n) AS contextNodes
                UNWIND contextNodes AS n
                OPTIONAL MATCH (n)-[r]-(m)
                WHERE elementId(m) IN $elementIds
                WITH contextNodes, collect(DISTINCT r) AS relationships
                RETURN contextNodes AS nodes, [rel IN relationships WHERE rel IS NOT NULL] AS relationships
                """,
                {"elementIds": element_ids},
                timeout_seconds=max(10.0, float(timeout_seconds or 20.0)),
                retries=1,
            )
            if record:
                for raw_node in record.get("nodes") or []:
                    if raw_node is not None:
                        _add_node(nodes, raw_node)
                for raw_rel in record.get("relationships") or []:
                    if raw_rel is not None:
                        _add_relationship(edges, raw_rel)
    finally:
        driver.close()
    node_rows, edge_rows, type_counts = _summarize_graph(nodes, edges)
    return {
        "status": "ok",
        "source": cfg.uri,
        "mode": "type_page",
        "query": (query or "").strip(),
        "year": year,
        "limit": len(element_ids),
        "offset": 0,
        "nextOffset": len(node_rows),
        "hasMore": False,
        "view": view if view in VIEW_RELATION_PATTERNS else "all",
        "start": start if start in START_LABELS else "project",
        "scoped": True,
        "contextual": True,
        "nodes": node_rows,
        "edges": edge_rows,
        "typeCounts": type_counts,
        "totals": {"nodes": len(node_rows), "relationships": len(edge_rows)},
    }


def load_knowledge_graph_nodes_by_type(
    *,
    type_label: str,
    limit: int = 80,
    offset: int = 0,
    query: str = "",
    year: int | None = None,
    view: str = "all",
    start: str = "project",
    timeout_seconds: float = 28.0,
    context_element_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Load a small readable page of real nodes for a selected cluster/type."""
    if context_element_ids:
        return _load_type_nodes_from_context(
            type_label=type_label,
            context_element_ids=context_element_ids,
            query=query,
            year=year,
            view=view,
            start=start,
            timeout_seconds=timeout_seconds,
        )

    cfg = _config()
    cypher, params, scoped = _type_nodes_query_payload(
        type_label=type_label,
        query=query,
        year=year,
        limit=limit,
        offset=offset,
        view=view,
        start=start,
    )
    safe_limit = params["limit"]
    safe_offset = params["offset"]
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    has_more = False
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            record = _run_neo4j_single(
                session,
                cypher,
                params,
                timeout_seconds=max(12.0, min(75.0, float(timeout_seconds or 28.0) + safe_limit * 0.05)),
                retries=1 if scoped else 2,
            )
            if record:
                has_more = bool(record.get("hasMore", False))
                for raw_node in record.get("nodes") or []:
                    if raw_node is not None:
                        _add_node(nodes, raw_node)
    finally:
        driver.close()
    node_rows, edge_rows, type_counts = _summarize_graph(nodes, edges)
    if not node_rows and scoped:
        return load_knowledge_graph_nodes_by_type(
            type_label=type_label,
            limit=limit,
            offset=offset,
            query="",
            year=None,
            view=view,
            start=start,
            timeout_seconds=timeout_seconds,
            context_element_ids=None,
        )
    return {
        "status": "ok",
        "source": cfg.uri,
        "mode": "type_page",
        "query": params["query"],
        "year": year,
        "limit": safe_limit,
        "offset": safe_offset,
        "nextOffset": safe_offset + safe_limit,
        "hasMore": has_more or len(node_rows) >= safe_limit,
        "view": params["view"],
        "start": params["start"],
        "scoped": scoped,
        "nodes": node_rows,
        "edges": edge_rows,
        "typeCounts": type_counts,
        "totals": {"nodes": len(node_rows), "relationships": len(edge_rows)},
    }


def load_knowledge_graph_node_neighbors(*, element_id: str, limit: int = 80, timeout_seconds: float = 24.0) -> dict[str, Any]:
    """Load a readable one-hop neighborhood for a selected real node."""
    cfg = _config()
    safe_limit = max(10, min(int(limit or 80), 180))
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            record = _run_neo4j_single(
                session,
                "MATCH (center) WHERE elementId(center) = $elementId "
                "OPTIONAL MATCH (center)-[r]-(n) "
                "WITH center, r, n LIMIT $limit "
                "RETURN center, collect(DISTINCT n) AS neighbors, collect(DISTINCT r) AS relationships",
                {"elementId": element_id, "limit": safe_limit},
                timeout_seconds=max(12.0, float(timeout_seconds or 24.0)),
                retries=1,
            )
            if record:
                _add_node(nodes, record["center"])
                for raw_node in record["neighbors"] or []:
                    if raw_node is not None:
                        _add_node(nodes, raw_node)
                for raw_rel in record["relationships"] or []:
                    if raw_rel is not None:
                        _add_relationship(edges, raw_rel)
    finally:
        driver.close()
    node_rows, edge_rows, type_counts = _summarize_graph(nodes, edges)
    return {
        "status": "ok",
        "source": cfg.uri,
        "mode": "neighbors",
        "query": "",
        "year": None,
        "limit": safe_limit,
        "offset": 0,
        "nextOffset": 0,
        "hasMore": False,
        "view": "neighbors",
        "start": element_id,
        "nodes": node_rows,
        "edges": edge_rows,
        "typeCounts": type_counts,
        "totals": {"nodes": len(node_rows), "relationships": len(edge_rows)},
    }
