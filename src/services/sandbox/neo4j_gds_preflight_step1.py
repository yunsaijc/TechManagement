#!/usr/bin/env python3
"""Neo4j GDS 第一步预检实现。

用途：
1. 验证 Neo4j 连通性。
2. 验证 GDS 插件是否可用。
3. 验证关键算法是否可用（Leiden/Louvain/PageRank/Betweenness）。
4. 在小规模投影图上执行一次算法烟囱测试。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

# 自动加载项目根目录 .env，避免每次手工 export。
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


SESSION_KWARGS = {
    "notifications_disabled_classifications": ["DEPRECATION"],
}


@dataclass
class PreflightConfig:
    uri: str
    user: str
    password: str
    database: str
    graph_name: str
    sample_node_limit: int
    sample_rel_limit: int


def getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def build_config() -> PreflightConfig:
    return PreflightConfig(
        uri=getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687"),
        user=getenv_required("NEO4J_USER", "neo4j"),
        password=getenv_required("NEO4J_PASSWORD"),
        database=getenv_required("NEO4J_DATABASE", "neo4j"),
        graph_name=getenv_required("NEO4J_GDS_GRAPH", "gds_preflight_graph"),
        sample_node_limit=int(getenv_required("GDS_SAMPLE_NODE_LIMIT", "20000")),
        sample_rel_limit=int(getenv_required("GDS_SAMPLE_REL_LIMIT", "50000")),
    )


def run_single_value(session: Any, query: str, params: dict[str, Any] | None = None) -> Any:
    result = session.run(query, params or {})
    record = result.single()
    return record[0] if record else None


def check_connectivity(driver: Any, cfg: PreflightConfig) -> None:
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        value = run_single_value(session, "RETURN 1 AS ok")
        if value != 1:
            raise RuntimeError("连通性检测失败：RETURN 1 未返回预期结果")
    print("[OK] Neo4j 连通性通过")


def check_neo4j_components(driver: Any, cfg: PreflightConfig) -> None:
    query = """
    CALL dbms.components()
    YIELD name, versions, edition
    RETURN name, versions, edition
    """
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        rows = [dict(r) for r in session.run(query)]
    if not rows:
        raise RuntimeError("未获取到 Neo4j 组件信息")
    print("[OK] Neo4j 组件信息:")
    for row in rows:
        print(f"  - {row['name']} | versions={row['versions']} | edition={row['edition']}")


def check_gds_version(driver: Any, cfg: PreflightConfig) -> str:
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        # 不同 GDS 版本在 gds.version() 的返回字段可能不同，按顺序兼容。
        queries = [
            "CALL gds.version() YIELD version RETURN version",
            "CALL gds.version() YIELD gdsVersion RETURN gdsVersion",
            "CALL gds.version()",
            "RETURN gds.version() AS version",
        ]
        version = None
        last_error: Exception | None = None
        for query in queries:
            try:
                result = session.run(query)
                record = result.single()
                if record:
                    data = record.data()
                    version = data.get("version") or data.get("gdsVersion") or next(iter(data.values()), None)
                if version:
                    break
            except Exception as exc:
                last_error = exc
                continue

        if not version and last_error is not None:
            raise RuntimeError(f"GDS 版本查询失败: {last_error}")
    if not version:
        raise RuntimeError("GDS 版本查询为空，可能未安装或未启用")
    print(f"[OK] GDS 可用，版本: {version}")
    return str(version)


def list_gds_procedures(driver: Any, cfg: PreflightConfig) -> set[str]:
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        try:
            query = """
            SHOW PROCEDURES
            YIELD name
            WHERE name STARTS WITH 'gds.'
            RETURN name
            """
            names = {str(r["name"]) for r in session.run(query)}
            print(f"[OK] 检测到 GDS 过程数: {len(names)}")
            return names
        except Exception as exc:
            print(f"[WARN] 过程列表查询受限，跳过列表检测: {exc}")
            return set()


def check_required_algorithms(gds_names: Iterable[str]) -> None:
    required = {
        "gds.louvain.stream",
        "gds.leiden.stream",
        "gds.pageRank.stream",
        "gds.betweenness.stream",
    }
    current = set(gds_names)
    if not current:
        print("[WARN] 未获取到过程列表，将在后续投影/算法烟囱阶段继续验证可用性")
        return
    missing = sorted(required - current)
    if missing:
        print("[WARN] 以下算法过程未找到（可能版本差异导致命名不同）:")
        for item in missing:
            print(f"  - {item}")
        return
    print("[OK] 关键算法过程齐全（Louvain/Leiden/PageRank/Betweenness）")


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


def project_sample_graph(driver: Any, cfg: PreflightConfig) -> tuple[int, int]:
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        drop_graph_if_exists(session, cfg.graph_name)

        node_limit = max(1, int(cfg.sample_node_limit))
        rel_limit = max(1, int(cfg.sample_rel_limit))
        projection_query = """
        CALL {
          MATCH (n)
          WHERE id(n) < $node_limit
          RETURN id(n) AS source, null AS target, true AS node_only, null AS rel_type
          UNION ALL
          MATCH (a)-[r]->(b)
          WHERE id(a) < $node_limit AND id(b) < $node_limit
          RETURN id(a) AS source, id(b) AS target, false AS node_only, type(r) AS rel_type
          LIMIT $rel_limit
        }
        WITH gds.graph.project(
          $graph_name,
          source,
          target,
          CASE
            WHEN node_only THEN {}
            ELSE {relationshipType: rel_type}
          END,
          {readConcurrency: 4}
        ) AS g
        RETURN g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount
        """

        try:
            row = session.run(
                projection_query,
                {
                    "graph_name": cfg.graph_name,
                    "node_limit": node_limit,
                    "rel_limit": rel_limit,
                },
            ).single()
        except Neo4jError as exc:
            print(f"[WARN] 新版 Cypher 投影失败，回退旧写法: {exc}")
            node_query = f"MATCH (n) WHERE id(n) < {node_limit} RETURN id(n) AS id"
            rel_query = (
                f"MATCH (a)-[r]->(b) "
                f"WHERE id(a) < {node_limit} AND id(b) < {node_limit} "
                f"RETURN id(a) AS source, id(b) AS target LIMIT {rel_limit}"
            )

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
                    "graph_name": cfg.graph_name,
                    "node_query": node_query,
                    "rel_query": rel_query,
                },
            ).single()

    if not row:
        raise RuntimeError("样本图投影失败，未返回统计信息")

    node_count = int(row["nodeCount"])
    rel_count = int(row["relationshipCount"])
    print(f"[OK] 样本图投影成功: nodes={node_count}, relationships={rel_count}")
    return node_count, rel_count


def smoke_test_pagerank(driver: Any, cfg: PreflightConfig) -> None:
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        query = """
        CALL gds.pageRank.stream($graph_name, {maxIterations: 20, dampingFactor: 0.85})
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId) AS n, score
        ORDER BY score DESC
        LIMIT 3
        """
        rows = [dict(r) for r in session.run(query, {"graph_name": cfg.graph_name})]

    if not rows:
        raise RuntimeError("PageRank 烟囱测试未返回结果")

    print("[OK] PageRank 烟囱测试通过，Top3:")
    for idx, row in enumerate(rows, start=1):
        node = row["n"]
        labels = list(node.labels) if hasattr(node, "labels") else []
        print(f"  {idx}. labels={labels}, score={row['score']:.6f}")


def cleanup_graph(driver: Any, cfg: PreflightConfig) -> None:
    with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
        drop_graph_if_exists(session, cfg.graph_name)
    print(f"[OK] 清理临时图完成: {cfg.graph_name}")


def main() -> int:
    try:
        cfg = build_config()
    except Exception as exc:
        print(f"[ERROR] 配置错误: {exc}")
        print("提示：请至少设置 NEO4J_PASSWORD 环境变量")
        return 2

    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))

    try:
        check_connectivity(driver, cfg)
        check_neo4j_components(driver, cfg)
        check_gds_version(driver, cfg)
        names = list_gds_procedures(driver, cfg)
        check_required_algorithms(names)

        node_count, rel_count = project_sample_graph(driver, cfg)
        if node_count == 0 or rel_count == 0:
            print("[WARN] 样本投影图为空，跳过算法烟囱测试")
        else:
            smoke_test_pagerank(driver, cfg)

        print("\n[SUCCESS] 第一步完成：Neo4j + GDS 环境已可用于后续图算法研发")
        return 0
    except Neo4jError as exc:
        print(f"[ERROR] Neo4j/GDS 执行失败: {exc}")
        print("若错误与 gds.* 相关，通常表示 GDS 插件未安装或未启用")
        return 1
    except Exception as exc:
        print(f"[ERROR] 预检失败: {exc}")
        return 1
    finally:
        try:
            cleanup_graph(driver, cfg)
        except Exception as exc:
            print(f"[WARN] 清理临时图失败: {exc}")
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
