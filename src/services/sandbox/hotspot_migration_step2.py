#!/usr/bin/env python3
"""第二步：科研热点迁移最小闭环实现。

能力：
1. 基于两个时间窗构建主题图投影。
2. 运行 Leiden 社区发现识别热点簇。
3. 计算跨时间窗社区迁移流（可用于 Sankey）。
4. 输出机器可读 JSON 与自动研判摘要。

注意：
- 默认 Cypher 模板基于常见标签 Topic/Project/HAS_TOPIC。
- Step2 参数采用代码内默认配置，不依赖 HOTSPOT_* 环境变量。
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

# 自动加载项目根目录 .env
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


SESSION_KWARGS = {
    "notifications_disabled_classifications": ["DEPRECATION"],
}


DEFAULT_YEAR_A_START = 2023
DEFAULT_YEAR_A_END = 2023
DEFAULT_YEAR_B_START = 2024
DEFAULT_YEAR_B_END = 2024
DEFAULT_PREFERRED_STRATEGY = "auto"
DEFAULT_MIN_OVERLAP = 1
DEFAULT_MIN_JACCARD = 0.01
DEFAULT_MAX_EDGES = 150000
DEFAULT_TOP_COMMUNITIES = 8
DEFAULT_OUTPUT_PATH = "debug_sandbox/hotspot_migration_real_schema_2023_to_2024.json"
DEFAULT_COMMUNITY_EDGE_THRESHOLD = 200000

SCI_KG_LABELS = [
    "Concept",
    "Dataset",
    "DisciplineL1",
    "DisciplineL2",
    "DisciplineL3",
    "Method",
    "Policy",
    "SciEntity",
    "Theory",
    "Entity",
]

MGMT_KG_LABELS = [
    "Person",
    "Organization",
    "Org",
    "Project",
    "Output",
    "Paper",
    "Venue",
    "Fund/Program",
]

MGMT_CORE_RELATIONS = [
    "works_for",
    "undertakes",
    "produces",
    "authored_by",
    "funded_by",
    "published_in",
    "collaborates_with",
    "reviews",
]

SCI_RELATIONS = [
    "RELATES_TO_DISCIPLINE",
    "SUB_OF",
    "WD_FIELD_OF_WORK",
    "WD_INSTANCE_OF",
    "WD_MAIN_SUBJECT",
    "WD_PART_OF",
    "WD_RELEVANT_TOPIC",
    "WD_STUDIES",
    "WD_SUBCLASS_OF",
    "WD_TOPIC_MAIN_CATEGORY",
]

BRIDGE_RELATIONS = ["involves_concept"]

PROJECT_YEAR_EXPR = (
    "toInteger(p.year_norm)"
)
PROJECT1_YEAR_EXPR = (
    "toInteger(p1.year_norm)"
)
PROJECT2_YEAR_EXPR = (
    "toInteger(p2.year_norm)"
)

DEFAULT_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project)<-[:undertakes]-(person:Person)-[:undertakes]->"
    "(p2:Project)-[:funded_by]->(f2:`Fund/Program`) "
    "WHERE id(f1) < id(f2) "
    "WITH f1, f2, person, "
    f"{PROJECT1_YEAR_EXPR} AS y1, "
    f"{PROJECT2_YEAR_EXPR} AS y2 "
    "WHERE y1 >= {start_year} AND y1 <= {end_year} "
    "AND y2 >= {start_year} AND y2 <= {end_year} "
    "RETURN id(f1) AS source, id(f2) AS target, count(DISTINCT person) AS weight"
)

DEFAULT_GUIDE_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_GUIDE_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    "AND p1.guideName IS NOT NULL AND p1.guideName = p2.guideName "
    f"AND {PROJECT1_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT1_YEAR_EXPR} <= {{end_year}} "
    f"AND {PROJECT2_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT2_YEAR_EXPR} <= {{end_year}} "
    "RETURN id(f1) AS source, id(f2) AS target, count(*) AS weight"
)

DEFAULT_DEPARTMENT_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} AND p.department IS NOT NULL "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_DEPARTMENT_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    "AND p1.department IS NOT NULL AND p1.department = p2.department "
    f"AND {PROJECT1_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT1_YEAR_EXPR} <= {{end_year}} "
    f"AND {PROJECT2_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT2_YEAR_EXPR} <= {{end_year}} "
    "RETURN id(f1) AS source, id(f2) AS target, count(*) AS weight"
)

DEFAULT_OFFICE_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} AND p.office IS NOT NULL "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_OFFICE_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    "AND p1.office IS NOT NULL AND p1.office = p2.office "
    f"AND {PROJECT1_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT1_YEAR_EXPR} <= {{end_year}} "
    f"AND {PROJECT2_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT2_YEAR_EXPR} <= {{end_year}} "
    "RETURN id(f1) AS source, id(f2) AS target, count(*) AS weight"
)

RELATION_CHAIN_REQUIRED = ["undertakes", "produces", "authored_by", "funded_by"]

RELATION_CHAIN_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} "
    "RETURN DISTINCT id(f) AS id"
)

RELATION_CHAIN_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    f"WITH f1, f2, p1, p2, {PROJECT1_YEAR_EXPR} AS y1, {PROJECT2_YEAR_EXPR} AS y2 "
    "WHERE y1 >= {start_year} AND y1 <= {end_year} "
    "AND y2 >= {start_year} AND y2 <= {end_year} "
    "OPTIONAL MATCH (p1)<-[:undertakes]-(u:Person)-[:undertakes]->(p2) "
    "WITH f1, f2, p1, p2, collect(DISTINCT id(u)) AS undertake_people "
    "OPTIONAL MATCH (p1)-[:produces]->(o1)<-[:authored_by]-(a:Person)-[:authored_by]->(o2)<-[:produces]-(p2) "
    "WITH f1, f2, undertake_people, collect(DISTINCT id(a)) AS author_people "
    "WITH f1, f2, toFloat(size(undertake_people) + size(author_people)) AS weight "
    "WHERE weight > 0 "
    "RETURN id(f1) AS source, id(f2) AS target, weight"
)


@dataclass
class HotspotConfig:
    uri: str
    user: str
    password: str
    database: str
    year_a_start: int
    year_a_end: int
    year_b_start: int
    year_b_end: int
    node_query_template: str
    rel_query_template: str
    min_overlap_count: int
    min_jaccard: float
    top_community_count: int
    output_path: str
    preferred_strategy: str
    community_edge_threshold: int
    max_edges: int
    require_real_data: bool
    min_total_nodes: int
    min_total_relationships: int
    min_project_count: int
    min_undertakes_count: int
    min_year_norm_ratio: float


@dataclass
class ProjectionStrategy:
    name: str
    description: str
    node_query_template: str
    rel_query_template: str
    node_label_fields: list[str]


def getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_config() -> HotspotConfig:
    year_a_start = DEFAULT_YEAR_A_START
    year_a_end = DEFAULT_YEAR_A_END
    year_b_start = DEFAULT_YEAR_B_START
    year_b_end = DEFAULT_YEAR_B_END

    if year_a_end < year_a_start or year_b_end < year_b_start:
        raise ValueError("年份区间非法：结束年份不能小于开始年份")

    return HotspotConfig(
        uri=getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687"),
        user=getenv_required("NEO4J_USER", "neo4j"),
        password=getenv_required("NEO4J_PASSWORD"),
        database=getenv_required("NEO4J_DATABASE", "neo4j"),
        year_a_start=year_a_start,
        year_a_end=year_a_end,
        year_b_start=year_b_start,
        year_b_end=year_b_end,
        node_query_template=DEFAULT_NODE_TEMPLATE,
        rel_query_template=DEFAULT_REL_TEMPLATE,
        min_overlap_count=DEFAULT_MIN_OVERLAP,
        min_jaccard=DEFAULT_MIN_JACCARD,
        top_community_count=DEFAULT_TOP_COMMUNITIES,
        output_path=DEFAULT_OUTPUT_PATH,
        preferred_strategy=DEFAULT_PREFERRED_STRATEGY,
        community_edge_threshold=DEFAULT_COMMUNITY_EDGE_THRESHOLD,
        max_edges=DEFAULT_MAX_EDGES,
        require_real_data=env_bool("SANDBOX_REQUIRE_REAL_DATA", True),
        min_total_nodes=max(1, int(os.getenv("SANDBOX_REAL_MIN_TOTAL_NODES", "1000000"))),
        min_total_relationships=max(1, int(os.getenv("SANDBOX_REAL_MIN_TOTAL_RELATIONSHIPS", "1000000"))),
        min_project_count=max(1, int(os.getenv("SANDBOX_REAL_MIN_PROJECTS", "1000"))),
        min_undertakes_count=max(1, int(os.getenv("SANDBOX_REAL_MIN_UNDERTAKES", "1000"))),
        min_year_norm_ratio=max(0.0, min(1.0, float(os.getenv("SANDBOX_REAL_MIN_YEAR_NORM_RATIO", "0.95")))),
    )


def verify_real_data_snapshot(session: Any, cfg: HotspotConfig) -> dict[str, Any]:
    labels = sorted([str(r["label"]) for r in session.run("CALL db.labels() YIELD label RETURN label")])
    rel_types = sorted([str(r["relationshipType"]) for r in session.run(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
    )])

    total_nodes = int(session.run("MATCH (n) RETURN count(n) AS c").single()["c"])
    total_relationships = int(session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"])
    project_count = int(session.run("MATCH (p:Project) RETURN count(p) AS c").single()["c"])
    year_norm_filled = int(session.run(
        "MATCH (p:Project) RETURN sum(CASE WHEN p.year_norm IS NOT NULL THEN 1 ELSE 0 END) AS c"
    ).single()["c"] or 0)
    undertakes_count = int(session.run("MATCH ()-[r:undertakes]->() RETURN count(r) AS c").single()["c"])
    year_norm_ratio = (year_norm_filled / project_count) if project_count > 0 else 0.0

    required_labels = ["Project", "Person", "Output", "Fund/Program"]
    required_rels = ["undertakes", "funded_by", "produces"]
    missing_labels = [x for x in required_labels if x not in labels]
    missing_rels = [x for x in required_rels if x not in rel_types]

    checks = {
        "totalNodes": {
            "actual": total_nodes,
            "minRequired": cfg.min_total_nodes,
            "ok": total_nodes >= cfg.min_total_nodes,
        },
        "totalRelationships": {
            "actual": total_relationships,
            "minRequired": cfg.min_total_relationships,
            "ok": total_relationships >= cfg.min_total_relationships,
        },
        "projectCount": {
            "actual": project_count,
            "minRequired": cfg.min_project_count,
            "ok": project_count >= cfg.min_project_count,
        },
        "yearNormCoverage": {
            "actual": round(year_norm_ratio, 6),
            "filled": year_norm_filled,
            "total": project_count,
            "minRequired": cfg.min_year_norm_ratio,
            "ok": year_norm_ratio >= cfg.min_year_norm_ratio,
        },
        "undertakesCount": {
            "actual": undertakes_count,
            "minRequired": cfg.min_undertakes_count,
            "ok": undertakes_count >= cfg.min_undertakes_count,
        },
    }

    verified = (not missing_labels) and (not missing_rels) and all(v["ok"] for v in checks.values())
    return {
        "verified": verified,
        "requireRealData": cfg.require_real_data,
        "requiredLabels": required_labels,
        "requiredRelationshipTypes": required_rels,
        "missingLabels": missing_labels,
        "missingRelationshipTypes": missing_rels,
        "checks": checks,
    }


def _quote_label(label: str) -> str:
    return f"`{label}`" if "/" in label else label


def _count_nodes_by_labels(session: Any, labels: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        row = session.run(
            f"MATCH (n:{_quote_label(label)}) RETURN count(n) AS c"
        ).single()
        counts[label] = int(row["c"] or 0) if row else 0
    return counts


def _count_relationships_by_types(session: Any, rel_types: list[str]) -> dict[str, int]:
    existing_rel_types = {
        str(r["relationshipType"])
        for r in session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    }
    counts: dict[str, int] = {}
    for rel_type in rel_types:
        if rel_type not in existing_rel_types:
            counts[rel_type] = 0
            continue
        row = session.run(
            f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS c"
        ).single()
        counts[rel_type] = int(row["c"] or 0) if row else 0
    return counts


def collect_dual_layer_profile(session: Any) -> dict[str, Any]:
    sci_label_counts = _count_nodes_by_labels(session, SCI_KG_LABELS)
    mgmt_label_counts = _count_nodes_by_labels(session, MGMT_KG_LABELS)
    mgmt_rel_counts = _count_relationships_by_types(session, MGMT_CORE_RELATIONS)
    sci_rel_counts = _count_relationships_by_types(session, SCI_RELATIONS)
    bridge_rel_counts = _count_relationships_by_types(session, BRIDGE_RELATIONS)

    def _present_items(count_map: dict[str, int]) -> list[str]:
        return [name for name, count in count_map.items() if count > 0]

    def _missing_items(count_map: dict[str, int]) -> list[str]:
        return [name for name, count in count_map.items() if count <= 0]

    management_ready = len(_present_items(mgmt_label_counts)) >= 4 and len(_present_items(mgmt_rel_counts)) >= 3
    scientific_ready = len(_present_items(sci_label_counts)) >= 4 and len(_present_items(sci_rel_counts)) >= 2
    bridge_ready = bridge_rel_counts.get("involves_concept", 0) > 0

    reliability_notes: list[str] = []
    if not bridge_ready:
      reliability_notes.append("知识层与管理层之间尚未建立 involves_concept 桥接，结论主要依赖管理层属性与关系近似。")
    if mgmt_rel_counts.get("published_in", 0) <= 0:
      reliability_notes.append("期刊/会议发表链路未建，成果传播与载体分布判断仍不完整。")
    if mgmt_rel_counts.get("reviews", 0) <= 0:
      reliability_notes.append("评审活动链路未建，专家评审影响与评审结构无法闭环。")
    if mgmt_label_counts.get("Output", 0) <= 0 and mgmt_label_counts.get("Paper", 0) <= 0:
      reliability_notes.append("成果层覆盖不足，产出转化与作者协同判断会偏弱。")
    if sci_label_counts.get("Concept", 0) <= 0:
      reliability_notes.append("科学知识层核心概念节点不足，语义桥接和主题归并可靠性有限。")

    return {
        "scientificLayer": {
            "labels": sci_label_counts,
            "presentLabels": _present_items(sci_label_counts),
            "missingLabels": _missing_items(sci_label_counts),
            "ready": scientific_ready,
        },
        "managementLayer": {
            "labels": mgmt_label_counts,
            "presentLabels": _present_items(mgmt_label_counts),
            "missingLabels": _missing_items(mgmt_label_counts),
            "ready": management_ready,
        },
        "bridgeLayer": {
            "relationships": bridge_rel_counts,
            "ready": bridge_ready,
            "missingRelationships": _missing_items(bridge_rel_counts),
        },
        "relations": {
            "managementCore": mgmt_rel_counts,
            "scientificCore": sci_rel_counts,
            "bridge": bridge_rel_counts,
        },
        "overallReady": management_ready and scientific_ready and bridge_ready,
        "reliabilityNotes": reliability_notes,
    }


def build_strategy_catalog() -> list[ProjectionStrategy]:
    return [
        ProjectionStrategy(
            name="relation_chain_priority",
            description="关系链优先（undertakes+produces+authored_by+funded_by）迁移口径。",
            node_query_template=RELATION_CHAIN_NODE_TEMPLATE,
            rel_query_template=RELATION_CHAIN_REL_TEMPLATE,
            node_label_fields=["name", "基金名称", "label", "title"],
        ),
        ProjectionStrategy(
            name="project_guide_name",
            description="按 Project.guideName 共现构图，适合识别主题热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
                "WITH p.guideName AS grp, collect(id(p))[0..120] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["guideName", "projectName", "department", "office"],
        ),
        ProjectionStrategy(
            name="project_department",
            description="按 Project.department 共现构图，适合识别部门科研方向迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.department IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.department IS NOT NULL "
                "WITH p.department AS grp, collect(id(p))[0..120] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["department", "projectName", "guideName", "office"],
        ),
        ProjectionStrategy(
            name="project_office",
            description="按 Project.office 共现构图，适合识别区域/单位热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.office IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.office IS NOT NULL "
                "WITH p.office AS grp, collect(id(p))[0..120] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["office", "projectName", "guideName", "department"],
        ),
        ProjectionStrategy(
            name="topic_template",
            description="兼容旧的 Topic/HAS_TOPIC 模板。",
            node_query_template=DEFAULT_NODE_TEMPLATE,
            rel_query_template=DEFAULT_REL_TEMPLATE,
            node_label_fields=["name", "title", "keyword", "subject", "label"],
        ),
    ]


def _relation_chain_readiness(graph_profile: dict[str, Any]) -> dict[str, Any]:
    rel_counts = ((graph_profile.get("relations") or {}).get("managementCore") or {})
    missing = [name for name in RELATION_CHAIN_REQUIRED if int(rel_counts.get(name, 0) or 0) <= 0]
    return {
        "ready": not missing,
        "required": RELATION_CHAIN_REQUIRED,
        "missing": missing,
        "counts": {name: int(rel_counts.get(name, 0) or 0) for name in RELATION_CHAIN_REQUIRED},
    }


def drop_graph_if_exists(session: Any, graph_name: str) -> None:
    session.run(
        """
        CALL gds.graph.exists($graph_name)
        YIELD exists
        WITH exists
        WHERE exists
        CALL gds.graph.drop($graph_name, false)
        YIELD graphName
        RETURN graphName
        """,
        {"graph_name": graph_name},
    ).consume()


def build_projection(
    session: Any,
    cfg: HotspotConfig,
    graph_name: str,
    strategy: ProjectionStrategy,
    start: int,
    end: int,
) -> dict[str, int]:
    node_query = strategy.node_query_template.format(start_year=start, end_year=end)
    rel_query_base = strategy.rel_query_template.format(start_year=start, end_year=end)

    # 统一关系采样上限，避免大图投影在关系侧失控。
    if cfg.max_edges > 0:
        rel_query = (
            "CALL { "
            + rel_query_base
            + f" }} RETURN source, target, weight LIMIT {cfg.max_edges}"
        )
    else:
        rel_query = rel_query_base

    drop_graph_if_exists(session, graph_name)

    projection_query = f"""
    CALL {{
        CALL {{
            {node_query}
        }}
        RETURN id AS source, null AS target, 0.0 AS weight, true AS node_only
        UNION ALL
        CALL {{
            {rel_query}
        }}
        RETURN source AS source, target AS target, coalesce(weight, 1.0) AS weight, false AS node_only
    }}
    WITH gds.graph.project(
        $graph_name,
        source,
        target,
        CASE
            WHEN node_only THEN {{}}
            ELSE {{
                relationshipType: 'RELATED',
                relationshipProperties: {{weight: toFloat(weight)}}
            }}
        END,
        {{readConcurrency: 4}}
    ) AS g
    RETURN g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount
    """

    try:
        row = session.run(
            projection_query,
            {"graph_name": graph_name},
        ).single()
    except Neo4jError as exc:
        # 兼容旧版 GDS，避免升级窗口期功能中断。
        print(f"[WARN] 新版 Cypher 投影失败，回退旧写法: {exc}")
        row = session.run(
            """
            CALL gds.graph.project.cypher(
                $graph_name,
                $node_query,
                $rel_query,
                {validateRelationships: false}
            )
            YIELD nodeCount, relationshipCount
            RETURN nodeCount, relationshipCount
            """,
            {
                "graph_name": graph_name,
                "node_query": node_query,
                "rel_query": rel_query,
            },
        ).single()

    if not row:
        raise RuntimeError(f"图投影失败: {graph_name}")

    return {
        "nodeCount": int(row["nodeCount"]),
        "relationshipCount": int(row["relationshipCount"]),
    }


def select_strategy(
    session: Any,
    cfg: HotspotConfig,
    windows: list[tuple[int, int]],
    graph_profile: dict[str, Any],
) -> tuple[ProjectionStrategy, list[dict[str, Any]], dict[str, Any]]:
    catalog = build_strategy_catalog()
    ordered = catalog
    relation_gate = _relation_chain_readiness(graph_profile)

    catalog_by_name = {item.name: item for item in catalog}

    if cfg.preferred_strategy != "auto":
        preferred = [item for item in catalog if item.name == cfg.preferred_strategy]
        if preferred:
            ordered = preferred
    else:
        relation_first = [catalog_by_name["relation_chain_priority"]]
        attrs = [
            catalog_by_name["project_guide_name"],
            catalog_by_name["project_department"],
            catalog_by_name["project_office"],
            catalog_by_name["topic_template"],
        ]
        ordered = relation_first + attrs if relation_gate["ready"] else attrs

    attempts: list[dict[str, Any]] = []
    for strategy in ordered:
        window_stats: list[dict[str, Any]] = []
        try:
            for start, end in windows:
                graph_name = f"hotspot_probe_{strategy.name}_{start}_{end}_{uuid.uuid4().hex[:6]}"
                stats = build_projection(session, cfg, graph_name, strategy, start, end)
                window_stats.append({
                    "window": {"start": start, "end": end},
                    "nodeCount": stats["nodeCount"],
                    "relationshipCount": stats["relationshipCount"],
                })
                drop_graph_if_exists(session, graph_name)

            attempts.append({"strategy": strategy.name, "windows": window_stats})
            if all(item["nodeCount"] > 0 and item["relationshipCount"] > 0 for item in window_stats):
                print(f"[OK] 选中策略 {strategy.name}: {strategy.description}")
                return strategy, window_stats, {
                    "preferredMode": cfg.preferred_strategy,
                    "relationChainGate": relation_gate,
                    "fallbackToAttribute": strategy.name != "relation_chain_priority",
                    "orderedStrategies": [item.name for item in ordered],
                    "selectedStrategy": strategy.name,
                }
        except Exception as exc:
            attempts.append({"strategy": strategy.name, "error": str(exc), "windows": window_stats})
            continue

    raise RuntimeError(f"未找到可用的热点迁移策略，尝试记录: {attempts}")


def run_community_detection(session: Any, graph_name: str, prefer_louvain: bool = False) -> list[dict[str, int]]:
    leiden_queries = [
        """
        CALL gds.leiden.stream($graph_name, {relationshipWeightProperty: 'weight'})
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
        """
        CALL gds.leiden.stream($graph_name)
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
    ]

    last_error: Exception | None = None
    louvain_queries = [
        """
        CALL gds.louvain.stream($graph_name, {relationshipWeightProperty: 'weight'})
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
        """
        CALL gds.louvain.stream($graph_name)
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
    ]

    louvain_error: Exception | None = None
    ordered_queries = louvain_queries + leiden_queries if prefer_louvain else leiden_queries + louvain_queries

    for query in ordered_queries:
        try:
            return [
                {"nodeId": int(r["nodeId"]), "communityId": int(r["communityId"])}
                for r in session.run(query, {"graph_name": graph_name})
            ]
        except Exception as exc:
            if "leiden" in query.lower():
                last_error = exc
            else:
                louvain_error = exc
            continue

    raise RuntimeError(f"社区检测执行失败: leiden={last_error}; louvain={louvain_error}")


def fetch_node_names(session: Any, node_ids: list[int], strategy: ProjectionStrategy) -> dict[int, str]:
    if not node_ids:
        return {}

    fields = [
        *strategy.node_label_fields,
        "name",
        "title",
        "projectName",
        "guideName",
        "department",
        "office",
        "display_name_zh",
        "label_zh",
        "基金名称",
    ]
    label_exprs: list[str] = []
    for field in fields:
        if field in {"基金名称"}:
            label_exprs.append(f"n.`{field}`")
        else:
            label_exprs.append(f"n.{field}")

    label_exprs.append("toString(id(n))")

    query = """
        UNWIND $ids AS nid
        MATCH (n)
        WHERE id(n) = nid
        RETURN nid AS node_id,
               coalesce(
                   {label_exprs}
               ) AS node_name
        """.replace("{label_exprs}", ",\n                   ".join(label_exprs))

    rows = session.run(
        query,
        {"ids": node_ids},
    )
    return {int(r["node_id"]): str(r["node_name"]) for r in rows}


def summarize_communities(
    session: Any,
    assignments: list[dict[str, int]],
    top_community_count: int,
    strategy: ProjectionStrategy,
) -> dict[int, dict[str, Any]]:
    comm_map: dict[int, set[int]] = {}
    for row in assignments:
        comm_map.setdefault(row["communityId"], set()).add(row["nodeId"])

    all_node_ids = sorted({row["nodeId"] for row in assignments})
    name_map = fetch_node_names(session, all_node_ids, strategy)

    summary: dict[int, dict[str, Any]] = {}
    ranked = sorted(comm_map.items(), key=lambda item: len(item[1]), reverse=True)

    for idx, (cid, node_set) in enumerate(ranked):
        names = [name_map.get(nid, str(nid)) for nid in sorted(node_set)]
        keyword_set = sorted({str(name).strip() for name in names if str(name).strip()})
        summary[cid] = {
            "communityId": cid,
            "size": len(node_set),
            "nodeIds": sorted(node_set),
            "keywordSet": keyword_set,
            "topKeywords": names[:8],
            "rank": idx + 1,
            "isTopCommunity": idx < top_community_count,
        }

    return summary


def build_migration(
    comm_a: dict[int, dict[str, Any]],
    comm_b: dict[int, dict[str, Any]],
    min_overlap_count: int,
    min_jaccard: float,
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []

    for cid_a, info_a in comm_a.items():
        set_a = set(info_a.get("keywordSet", []))
        basis = "keywordSet"
        if not set_a:
            set_a = {str(x) for x in info_a.get("nodeIds", [])}
            basis = "nodeIds"
        if not set_a:
            continue

        for cid_b, info_b in comm_b.items():
            set_b = set(info_b.get("keywordSet", []))
            if not set_b:
                set_b = {str(x) for x in info_b.get("nodeIds", [])}
            if not set_b:
                continue

            overlap = len(set_a & set_b)
            if overlap < min_overlap_count:
                continue

            jaccard = overlap / len(set_a | set_b)
            if jaccard < min_jaccard:
                continue

            links.append(
                {
                    "source": str(cid_a),
                    "target": str(cid_b),
                    "overlap": overlap,
                    "jaccard": round(jaccard, 4),
                    "sourceSize": len(set_a),
                    "targetSize": len(set_b),
                    "basis": basis,
                }
            )

    links.sort(key=lambda x: (x["overlap"], x["jaccard"]), reverse=True)
    return links


def build_migration_with_fallback(
    comm_a: dict[int, dict[str, Any]],
    comm_b: dict[int, dict[str, Any]],
    min_overlap_count: int,
    min_jaccard: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    attempts = [
        {"minOverlapCount": int(min_overlap_count), "minJaccard": float(min_jaccard), "reason": "configured"},
        {"minOverlapCount": 1, "minJaccard": 0.005, "reason": "fallback_relaxed_jaccard"},
        {"minOverlapCount": 1, "minJaccard": 0.0, "reason": "fallback_no_jaccard"},
    ]

    dedup: list[dict[str, Any]] = []
    seen: set[tuple[int, float]] = set()
    for item in attempts:
        key = (int(item["minOverlapCount"]), float(item["minJaccard"]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)

    trace: list[dict[str, Any]] = []
    for item in dedup:
        links = build_migration(
            comm_a,
            comm_b,
            int(item["minOverlapCount"]),
            float(item["minJaccard"]),
        )
        trace.append(
            {
                "minOverlapCount": int(item["minOverlapCount"]),
                "minJaccard": float(item["minJaccard"]),
                "reason": str(item["reason"]),
                "linkCount": len(links),
            }
        )
        if links:
            return links, item, trace

    return [], dedup[-1], trace


def generate_brief(
    cfg: HotspotConfig,
    comm_a: dict[int, dict[str, Any]],
    comm_b: dict[int, dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []

    top_a = sorted(comm_a.values(), key=lambda x: x["size"], reverse=True)[:3]
    top_b = sorted(comm_b.values(), key=lambda x: x["size"], reverse=True)[:3]

    lines.append(
        f"时间窗A({cfg.year_a_start}-{cfg.year_a_end})识别到 {len(comm_a)} 个主题簇，"
        f"时间窗B({cfg.year_b_start}-{cfg.year_b_end})识别到 {len(comm_b)} 个主题簇。"
    )

    if top_a:
        lines.append(
            "A窗头部簇关键词：" + "；".join(
                [f"C{c['communityId']}[{', '.join(c['topKeywords'][:3])}]" for c in top_a]
            )
        )

    if top_b:
        lines.append(
            "B窗头部簇关键词：" + "；".join(
                [f"C{c['communityId']}[{', '.join(c['topKeywords'][:3])}]" for c in top_b]
            )
        )

    if links:
        top_links = links[:3]
        lines.append(
            "主要迁移流：" + "；".join(
                [
                    f"C{l['source']}→C{l['target']}"
                    f"(overlap={l['overlap']}, jaccard={l['jaccard']})"
                    for l in top_links
                ]
            )
        )
    else:
        lines.append("未识别到满足阈值的迁移流，建议在代码默认参数中适当降低 overlap/jaccard 阈值。")

    return lines


def ensure_output_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def run(cfg: HotspotConfig) -> dict[str, Any]:
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    run_suffix = uuid.uuid4().hex[:8]
    graph_a = f"hotspot_{cfg.year_a_start}_{cfg.year_a_end}_{run_suffix}"
    graph_b = f"hotspot_{cfg.year_b_start}_{cfg.year_b_end}_{run_suffix}"
    stale_graph_a = f"hotspot_{cfg.year_a_start}_{cfg.year_a_end}"
    stale_graph_b = f"hotspot_{cfg.year_b_start}_{cfg.year_b_end}"

    try:
        with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
            data_source = verify_real_data_snapshot(session, cfg)
            graph_profile = collect_dual_layer_profile(session)
            if cfg.require_real_data and not bool(data_source.get("verified", False)):
                raise RuntimeError(f"真实数据校验失败: {data_source}")

            # 清理旧版固定命名遗留图，避免 catalog 残留干扰。
            drop_graph_if_exists(session, stale_graph_a)
            drop_graph_if_exists(session, stale_graph_b)

            selected_strategy, probe_windows, strategy_selection = select_strategy(
                session,
                cfg,
                [
                    (cfg.year_a_start, cfg.year_a_end),
                    (cfg.year_b_start, cfg.year_b_end),
                ],
                graph_profile,
            )

            proj_a = build_projection(session, cfg, graph_a, selected_strategy, cfg.year_a_start, cfg.year_a_end)
            proj_b = build_projection(session, cfg, graph_b, selected_strategy, cfg.year_b_start, cfg.year_b_end)

            if proj_a["nodeCount"] == 0 or proj_b["nodeCount"] == 0:
                raise RuntimeError("至少一个时间窗投影为空，请检查模板或年份区间")

            prefer_louvain = max(proj_a["relationshipCount"], proj_b["relationshipCount"]) >= cfg.community_edge_threshold
            community_algorithm = "louvain" if prefer_louvain else "leiden"
            assign_a = run_community_detection(session, graph_a, prefer_louvain=prefer_louvain)
            assign_b = run_community_detection(session, graph_b, prefer_louvain=prefer_louvain)

            comm_a = summarize_communities(session, assign_a, cfg.top_community_count, selected_strategy)
            comm_b = summarize_communities(session, assign_b, cfg.top_community_count, selected_strategy)
            links, effective_threshold, threshold_attempts = build_migration_with_fallback(
                comm_a,
                comm_b,
                cfg.min_overlap_count,
                cfg.min_jaccard,
            )
            brief = generate_brief(cfg, comm_a, comm_b, links)

        result = {
            "meta": {
                "database": cfg.database,
                "analysisMode": selected_strategy.name,
                "analysisDescription": selected_strategy.description,
                "communityAlgorithm": community_algorithm,
                "windowA": {"start": cfg.year_a_start, "end": cfg.year_a_end},
                "windowB": {"start": cfg.year_b_start, "end": cfg.year_b_end},
                "threshold": {
                    "minOverlapCount": cfg.min_overlap_count,
                    "minJaccard": cfg.min_jaccard,
                    "maxEdges": cfg.max_edges,
                },
                "effectiveThreshold": {
                    "minOverlapCount": int(effective_threshold["minOverlapCount"]),
                    "minJaccard": float(effective_threshold["minJaccard"]),
                    "reason": str(effective_threshold["reason"]),
                },
                "thresholdAttempts": threshold_attempts,
                "probeWindows": probe_windows,
                "strategySelection": strategy_selection,
                "dataSource": data_source,
                "graphProfile": graph_profile,
            },
            "projection": {
                "windowA": proj_a,
                "windowB": proj_b,
            },
            "communities": {
                "windowA": sorted(comm_a.values(), key=lambda x: x["rank"]),
                "windowB": sorted(comm_b.values(), key=lambda x: x["rank"]),
            },
            "sankey": {
                "nodes": [
                    *[
                        {"id": f"A-{c['communityId']}", "label": f"A-C{c['communityId']}", "size": c["size"]}
                        for c in sorted(comm_a.values(), key=lambda x: x["rank"])
                    ],
                    *[
                        {"id": f"B-{c['communityId']}", "label": f"B-C{c['communityId']}", "size": c["size"]}
                        for c in sorted(comm_b.values(), key=lambda x: x["rank"])
                    ],
                ],
                "links": [
                    {
                        "source": f"A-{l['source']}",
                        "target": f"B-{l['target']}",
                        "value": l["overlap"],
                        "jaccard": l["jaccard"],
                    }
                    for l in links
                ],
            },
            "insightDraft": brief,
        }
        return result
    finally:
        try:
            with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
                drop_graph_if_exists(session, graph_a)
                drop_graph_if_exists(session, graph_b)
        except Exception as exc:
            print(f"[WARN] Step2 清理临时图失败: {exc}")
        driver.close()


def main() -> int:
    try:
        cfg = build_config()
    except Exception as exc:
        print(f"[ERROR] 配置错误: {exc}")
        return 2

    try:
        result = run(cfg)
        ensure_output_dir(cfg.output_path)
        with open(cfg.output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print("[SUCCESS] 第二步完成：热点迁移最小闭环已跑通")
        print(f"[OUTPUT] {cfg.output_path}")
        for line in result.get("insightDraft", []):
            print(f"[INSIGHT] {line}")
        return 0
    except Neo4jError as exc:
        print(f"[ERROR] Neo4j 执行失败: {exc}")
        print("请检查 Step2 代码默认模板是否与图谱 schema 一致。")
        return 1
    except Exception as exc:
        print(f"[ERROR] 运行失败: {exc}")
        print("请检查年份区间、模板 Cypher 与数据是否匹配。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
