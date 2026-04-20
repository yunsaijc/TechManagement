#!/usr/bin/env python3
"""生成热点迁移投影叠层图 HTML。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.services.sandbox.hotspot_migration_step2 import (  # noqa: E402
    SESSION_KWARGS,
    build_config,
    build_strategy_catalog,
    _community_display_name,
)


DEFAULT_INPUT_JSON = (
    PROJECT_ROOT
    / "src/services/sandbox/output/hotspot_migration_real_schema_2023_to_2024.json"
)
DEFAULT_OUTPUT_HTML = (
    PROJECT_ROOT
    / "src/services/sandbox/output/hotspot_migration_real_schema_2023_to_2024.projection_overlay.html"
)

CANVAS_WIDTH = 3600
CANVAS_HEIGHT = 2600
CANVAS_CENTER_X = CANVAS_WIDTH / 2
CANVAS_CENTER_Y = CANVAS_HEIGHT / 2
SCATTER_PADDING_X = 180.0
SCATTER_PADDING_Y = 160.0


def _stable_seed(*parts: Any) -> int:
    text = "||".join(str(part) for part in parts)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成热点迁移投影叠层图 HTML")
    parser.add_argument(
        "--input-json",
        default=str(DEFAULT_INPUT_JSON),
        help="Step2 全量输出 JSON 路径",
    )
    parser.add_argument(
        "--output-html",
        default=str(DEFAULT_OUTPUT_HTML),
        help="投影叠层图 HTML 输出路径",
    )
    return parser.parse_args()


def load_full_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def pick_strategy(strategy_name: str):
    for strategy in build_strategy_catalog():
        if strategy.name == strategy_name:
            return strategy
    raise ValueError(f"未找到构图策略: {strategy_name}")


def fetch_projection_edges(
    session: Any,
    rel_query_template: str,
    start_year: int,
    end_year: int,
    max_edges: int,
) -> list[dict[str, Any]]:
    rel_query_base = rel_query_template.format(start_year=start_year, end_year=end_year)
    if max_edges > 0:
        query = f"CALL {{ {rel_query_base} }} RETURN source, target, weight LIMIT {int(max_edges)}"
    else:
        query = rel_query_base
    rows = session.run(query)
    return [
        {
            "source": int(row["source"]),
            "target": int(row["target"]),
            "weight": float(row["weight"] or 1.0),
        }
        for row in rows
    ]


def _node_batches(node_ids: list[int], batch_size: int = 500) -> list[list[int]]:
    return [node_ids[idx: idx + batch_size] for idx in range(0, len(node_ids), batch_size)]


def fetch_node_details(session: Any, node_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not node_ids:
        return {}

    query = """
    UNWIND $ids AS nid
    MATCH (n)
    WHERE id(n) = nid
    RETURN
        nid AS nodeId,
        labels(n) AS labels,
        coalesce(
            n.projectName,
            n.name,
            n.title,
            n.guideName,
            n.department,
            n.office,
            n.display_name_zh,
            n.label_zh,
            n.`基金名称`,
            toString(id(n))
        ) AS title,
        n.projectName AS projectName,
        n.guideName AS guideName,
        n.department AS department,
        n.office AS office
    """

    details: dict[int, dict[str, Any]] = {}
    for batch in _node_batches(sorted(set(node_ids))):
        for row in session.run(query, {"ids": batch}):
            node_id = int(row["nodeId"])
            details[node_id] = {
                "nodeId": node_id,
                "labels": [str(item) for item in (row["labels"] or [])],
                "title": str(row["title"] or node_id),
                "projectName": str(row["projectName"] or "").strip(),
                "guideName": str(row["guideName"] or "").strip(),
                "department": str(row["department"] or "").strip(),
                "office": str(row["office"] or "").strip(),
            }
    return details


def build_community_context(items: list[dict[str, Any]], period: str) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    communities: list[dict[str, Any]] = []
    node_to_comm: dict[int, dict[str, Any]] = {}
    for item in sorted(items, key=lambda x: int(x.get("rank", 0) or 0)):
        community = {
            "period": period,
            "communityId": int(item.get("communityId")),
            "rank": int(item.get("rank", 0) or 0),
            "size": int(item.get("size", 0) or 0),
            "name": _community_display_name(item),
            "topKeywords": [str(x) for x in (item.get("topKeywords", []) or [])],
            "nodeIds": [int(x) for x in (item.get("nodeIds", []) or [])],
        }
        communities.append(community)
        for node_id in community["nodeIds"]:
            node_to_comm[node_id] = community
    return communities, node_to_comm


def build_name_base_positions(communities: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    name_sizes: dict[str, int] = {}
    for community in communities:
        key = community["name"]
        name_sizes[key] = max(name_sizes.get(key, 0), int(community["size"]))

    names = sorted(name_sizes, key=lambda x: (-name_sizes[x], x))
    base_positions: dict[str, tuple[float, float]] = {}
    if not names:
        return base_positions
    occupied: list[dict[str, float]] = []
    rng = random.Random(_stable_seed("overlay-base", len(names)))
    min_x = SCATTER_PADDING_X
    max_x = CANVAS_WIDTH - SCATTER_PADDING_X
    min_y = SCATTER_PADDING_Y
    max_y = CANVAS_HEIGHT - SCATTER_PADDING_Y

    for index, name in enumerate(names):
        radius = 90.0 if index < 40 else 72.0 if index < 120 else 54.0
        gap = 70.0 if index < 40 else 42.0 if index < 120 else 24.0
        best: tuple[float, float, float] | None = None
        name_rng = random.Random(_stable_seed("overlay-base", name, index))
        for attempt in range(220):
            picker = name_rng if attempt < 120 else rng
            x = picker.uniform(min_x, max_x)
            y = picker.uniform(min_y, max_y)
            nearest = float("inf")
            valid = True
            for other in occupied:
                dist = math.hypot(x - other["x"], y - other["y"])
                min_dist = radius + other["radius"] + gap
                nearest = min(nearest, dist - (radius + other["radius"]))
                if dist < min_dist:
                    valid = False
            if valid:
                best = (x, y, nearest if nearest != float("inf") else 9999.0)
                break
            candidate = (x, y, nearest if nearest != float("inf") else -9999.0)
            if best is None or candidate[2] > best[2]:
                best = candidate
        assert best is not None
        x, y, _ = best
        occupied.append({"x": x, "y": y, "radius": radius})
        base_positions[name] = (round(x, 2), round(y, 2))
    return base_positions


def build_community_positions(
    communities: list[dict[str, Any]],
    base_positions: dict[str, tuple[float, float]],
) -> dict[tuple[str, int], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for community in communities:
        grouped[community["name"]].append(community)

    positioned: dict[tuple[str, int], dict[str, Any]] = {}
    for name, rows in grouped.items():
        rows = sorted(rows, key=lambda item: (item["period"], item["rank"], item["communityId"]))
        base_x, base_y = base_positions[name]
        for idx, row in enumerate(rows):
            if idx == 0:
                x, y = base_x, base_y
            else:
                local_radius = 34 + 22 * ((idx - 1) // 8)
                local_angle = (idx - 1) * (2 * math.pi / 8)
                x = base_x + local_radius * math.cos(local_angle)
                y = base_y + local_radius * math.sin(local_angle)
            radius = 18 + math.sqrt(max(1, row["size"])) * 8
            positioned[(row["period"], row["communityId"])] = {
                **row,
                "x": round(x, 2),
                "y": round(y, 2),
                "radius": round(radius, 2),
                "showLabel": bool(row["rank"] <= 80 or row["size"] >= 3),
            }
    return positioned


def build_node_positions(
    community_positions: dict[tuple[str, int], dict[str, Any]],
    node_lookup: dict[int, dict[str, Any]],
    node_to_comm: dict[int, dict[str, Any]],
    period: str,
) -> dict[int, dict[str, Any]]:
    grouped_nodes: dict[tuple[str, int], list[int]] = defaultdict(list)
    for node_id, community in node_to_comm.items():
        grouped_nodes[(period, int(community["communityId"]))].append(int(node_id))

    positioned_nodes: dict[int, dict[str, Any]] = {}
    for key, node_ids in grouped_nodes.items():
        community = community_positions[key]
        node_ids = sorted(node_ids, key=lambda nid: (node_lookup.get(nid, {}).get("title", ""), nid))
        spacing = 14.0
        cx = float(community["x"])
        cy = float(community["y"])
        if len(node_ids) == 1:
            node_id = node_ids[0]
            positioned_nodes[node_id] = {
                **node_lookup[node_id],
                "period": period,
                "communityId": int(community["communityId"]),
                "communityName": str(community["name"]),
                "communityRank": int(community["rank"]),
                "x": round(cx, 2),
                "y": round(cy, 2),
            }
            continue

        placed = 0
        ring = 0
        while placed < len(node_ids):
            ring += 1
            ring_radius = spacing * ring
            capacity = max(6, int((2 * math.pi * ring_radius) / spacing))
            segment = node_ids[placed: placed + capacity]
            for idx, node_id in enumerate(segment):
                angle = idx * (2 * math.pi / max(1, len(segment)))
                x = cx + ring_radius * math.cos(angle)
                y = cy + ring_radius * math.sin(angle)
                positioned_nodes[node_id] = {
                    **node_lookup[node_id],
                    "period": period,
                    "communityId": int(community["communityId"]),
                    "communityName": str(community["name"]),
                    "communityRank": int(community["rank"]),
                    "x": round(x, 2),
                    "y": round(y, 2),
                }
            placed += len(segment)
    return positioned_nodes


def build_edges(
    raw_edges: list[dict[str, Any]],
    node_lookup: dict[int, dict[str, Any]],
    period: str,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for index, edge in enumerate(raw_edges, start=1):
        source_id = int(edge["source"])
        target_id = int(edge["target"])
        source = node_lookup.get(source_id)
        target = node_lookup.get(target_id)
        if not source or not target:
            continue
        source_name = source.get("projectName") or source.get("title") or str(source_id)
        target_name = target.get("projectName") or target.get("title") or str(target_id)
        shared_topic = source.get("guideName") or target.get("guideName") or source.get("communityName") or ""
        edges.append(
            {
                "id": f"{period}-edge-{index}",
                "kind": "intra",
                "period": period,
                "source": source_id,
                "target": target_id,
                "weight": float(edge.get("weight", 1.0) or 1.0),
                "sourceName": source_name,
                "targetName": target_name,
                "sourceCommunity": source.get("communityName", ""),
                "targetCommunity": target.get("communityName", ""),
                "sharedTopic": shared_topic,
            }
        )
    return edges


def _cross_year_key(node: dict[str, Any]) -> str:
    for value in (
        node.get("guideName"),
        node.get("communityName"),
        node.get("title"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return str(node["nodeId"])


def build_cross_year_edges(
    nodes_a: dict[int, dict[str, Any]],
    nodes_b: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped_a: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_b: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes_a.values():
        grouped_a[_cross_year_key(node)].append(node)
    for node in nodes_b.values():
        grouped_b[_cross_year_key(node)].append(node)

    cross_edges: list[dict[str, Any]] = []
    keys = sorted(set(grouped_a) & set(grouped_b))
    index = 1
    for key in keys:
        rows_a = sorted(grouped_a[key], key=lambda x: (x.get("projectName") or x.get("title") or "", int(x["nodeId"])))
        rows_b = sorted(grouped_b[key], key=lambda x: (x.get("projectName") or x.get("title") or "", int(x["nodeId"])))
        pair_count = min(len(rows_a), len(rows_b))
        for idx in range(pair_count):
            source = rows_a[idx]
            target = rows_b[idx]
            cross_edges.append(
                {
                    "id": f"cross-edge-{index}",
                    "kind": "cross",
                    "period": "cross",
                    "source": int(source["nodeId"]),
                    "target": int(target["nodeId"]),
                    "sourceName": source.get("projectName") or source.get("title") or str(source["nodeId"]),
                    "targetName": target.get("projectName") or target.get("title") or str(target["nodeId"]),
                    "sourceCommunity": source.get("communityName", ""),
                    "targetCommunity": target.get("communityName", ""),
                    "sharedTopic": key,
                    "weight": 1.0,
                }
            )
            index += 1
    return cross_edges


def build_overlay_insights(
    periods: dict[str, Any],
    communities_a: list[dict[str, Any]],
    communities_b: list[dict[str, Any]],
    cross_edges: list[dict[str, Any]],
) -> list[str]:
    label_a = str(periods["windowA"]["label"])
    label_b = str(periods["windowB"]["label"])
    top_a = "、".join(item["name"] for item in communities_a[:3]) if communities_a else "暂无"
    top_b = "、".join(item["name"] for item in communities_b[:3]) if communities_b else "暂无"
    return [
        f"本图把 {label_a} 和 {label_b} 的项目关联网络叠放在同一张图上，便于直接比较两个年份的热点分布。",
        f"{label_a}识别出 {len(communities_a)} 个主题簇，{label_b}识别出 {len(communities_b)} 个主题簇。",
        f"{label_a}较集中的方向主要有：{top_a}。",
        f"{label_b}较集中的方向主要有：{top_b}。",
        f"图中的虚线一共 {len(cross_edges)} 条，表示两个年份之间共享同一关键词或指南名的项目延续关系。",
    ]


def build_payload(
    result: dict[str, Any],
    output_html_path: Path,
    node_lookup_a: dict[int, dict[str, Any]],
    node_lookup_b: dict[int, dict[str, Any]],
    edges_a_raw: list[dict[str, Any]],
    edges_b_raw: list[dict[str, Any]],
) -> dict[str, Any]:
    meta = result.get("meta", {}) or {}
    communities_block = result.get("communities", {}) or {}
    window_a_label = str((meta.get("windowA", {}) or {}).get("start", "2023")) + "年"
    window_b_label = str((meta.get("windowB", {}) or {}).get("start", "2024")) + "年"

    communities_a, node_to_comm_a = build_community_context(communities_block.get("windowA", []) or [], window_a_label)
    communities_b, node_to_comm_b = build_community_context(communities_block.get("windowB", []) or [], window_b_label)
    all_communities = communities_a + communities_b
    base_positions = build_name_base_positions(all_communities)
    community_positions = build_community_positions(all_communities, base_positions)

    nodes_a = build_node_positions(community_positions, node_lookup_a, node_to_comm_a, window_a_label)
    nodes_b = build_node_positions(community_positions, node_lookup_b, node_to_comm_b, window_b_label)

    all_nodes_lookup = {**nodes_a, **nodes_b}
    edges_a = build_edges(edges_a_raw, all_nodes_lookup, window_a_label)
    edges_b = build_edges(edges_b_raw, all_nodes_lookup, window_b_label)
    cross_edges = build_cross_year_edges(nodes_a, nodes_b)

    periods = {
        "windowA": {
            "label": window_a_label,
            "nodeCount": len(nodes_a),
            "edgeCount": len(edges_a),
            "communityCount": len(communities_a),
        },
        "windowB": {
            "label": window_b_label,
            "nodeCount": len(nodes_b),
            "edgeCount": len(edges_b),
            "communityCount": len(communities_b),
        },
    }

    rendered_communities = []
    for key in sorted(community_positions, key=lambda item: (community_positions[item]["period"], community_positions[item]["rank"])):
        row = community_positions[key]
        rendered_communities.append(
            {
                "id": f"{row['period']}-community-{row['communityId']}",
                "period": row["period"],
                "communityId": int(row["communityId"]),
                "rank": int(row["rank"]),
                "size": int(row["size"]),
                "name": str(row["name"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "radius": float(row["radius"]),
                "showLabel": bool(row["showLabel"]),
                "topKeywords": row.get("topKeywords", []),
            }
        )

    rendered_nodes = []
    for node in sorted(all_nodes_lookup.values(), key=lambda x: (x["period"], x.get("communityRank", 0), x.get("title", ""))):
        rendered_nodes.append(
            {
                "id": int(node["nodeId"]),
                "period": str(node["period"]),
                "title": str(node.get("title") or node["nodeId"]),
                "projectName": str(node.get("projectName") or ""),
                "guideName": str(node.get("guideName") or ""),
                "department": str(node.get("department") or ""),
                "office": str(node.get("office") or ""),
                "communityId": int(node["communityId"]),
                "communityName": str(node["communityName"]),
                "communityRank": int(node.get("communityRank", 0)),
                "x": float(node["x"]),
                "y": float(node["y"]),
            }
        )

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceJson": str(DEFAULT_INPUT_JSON),
        "outputHtml": str(output_html_path),
        "analysisMode": str(meta.get("analysisMode") or ""),
        "analysisDescription": str(meta.get("analysisDescription") or ""),
        "periods": periods,
        "canvas": {
            "width": CANVAS_WIDTH,
            "height": CANVAS_HEIGHT,
        },
        "communities": rendered_communities,
        "nodes": rendered_nodes,
        "edges": {
            "windowA": edges_a,
            "windowB": edges_b,
            "crossYear": cross_edges,
        },
        "insightDraft": build_overlay_insights(periods, communities_a, communities_b, cross_edges),
    }
    return payload


class ProjectionOverlayHtmlBuilder:
    def build(self, payload: dict[str, Any], output_html_path: Path) -> Path:
        ensure_parent_dir(output_html_path)
        output_html_path.write_text(self.render_html(payload), encoding="utf-8")
        return output_html_path

    def render_html(self, payload: dict[str, Any]) -> str:
        data_json = json.dumps(payload, ensure_ascii=False)
        template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>热点迁移投影叠层图</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f3f6fb; color: #0f172a; }}
    .page {{ display: grid; grid-template-columns: minmax(0, 1fr) 380px; min-height: 100vh; }}
    .main {{ padding: 18px; }}
    .hero {{ padding: 18px 20px; border: 1px solid #dbe5f1; border-radius: 18px; background: linear-gradient(135deg, #ffffff 0%, #eef5ff 100%); box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05); }}
    .title {{ font-size: 26px; font-weight: 800; }}
    .subtitle {{ margin-top: 6px; color: #475569; font-size: 13px; line-height: 1.7; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }}
    .stat {{ padding: 12px 14px; border-radius: 14px; background: rgba(255,255,255,0.9); border: 1px solid #dbe5f1; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 4px; font-size: 22px; font-weight: 800; }}
    .controls {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }}
    .toggle {{ display: flex; gap: 8px; align-items: center; padding: 8px 10px; border-radius: 999px; background: #fff; border: 1px solid #dbe5f1; font-size: 13px; }}
    .graph-wrap {{ margin-top: 16px; padding: 14px; border-radius: 18px; background: #fff; border: 1px solid #dbe5f1; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04); }}
    .graph-toolbar {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }}
    .legend {{ display: flex; gap: 14px; flex-wrap: wrap; color: #475569; font-size: 12px; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
    .swatch {{ width: 26px; height: 10px; border-radius: 999px; display: inline-block; }}
    .canvas-shell {{ overflow: auto; max-height: calc(100vh - 240px); border-radius: 14px; border: 1px solid #e2e8f0; background: #f8fafc; }}
    svg {{ width: __WIDTH__px; height: __HEIGHT__px; display: block; background:
      radial-gradient(circle at 20% 15%, rgba(59,130,246,0.06), transparent 18%),
      radial-gradient(circle at 78% 20%, rgba(15,118,110,0.06), transparent 18%),
      radial-gradient(circle at 50% 80%, rgba(245,158,11,0.06), transparent 22%),
      #f8fafc; }}
    .side {{ border-left: 1px solid #dbe5f1; background: #ffffff; padding: 18px; overflow: auto; }}
    .panel {{ border: 1px solid #e2e8f0; border-radius: 16px; padding: 14px; background: #fff; }}
    .panel + .panel {{ margin-top: 14px; }}
    .panel-title {{ font-size: 15px; font-weight: 800; margin-bottom: 10px; }}
    .hint {{ font-size: 12px; color: #64748b; line-height: 1.7; }}
    .detail-title {{ font-size: 16px; font-weight: 800; line-height: 1.6; }}
    .detail-meta {{ margin-top: 8px; display: grid; gap: 6px; font-size: 13px; color: #334155; }}
    .search {{ width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid #dbe5f1; outline: none; }}
    .list {{ display: grid; gap: 8px; max-height: 360px; overflow: auto; margin-top: 12px; }}
    .list-item {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 12px; cursor: pointer; background: #fff; }}
    .list-item:hover {{ border-color: #93c5fd; background: #eff6ff; }}
    .list-item-title {{ font-size: 13px; font-weight: 700; line-height: 1.6; }}
    .list-item-meta {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
    .community-label {{ font-size: 13px; font-weight: 700; fill: #0f172a; cursor: pointer; paint-order: stroke; stroke: rgba(255,255,255,0.92); stroke-width: 4px; stroke-linejoin: round; }}
    .community-anchor {{ cursor: pointer; }}
    .edge-2023 {{ stroke: rgba(71, 85, 105, 0.45); stroke-width: 1.6; }}
    .edge-2024 {{ stroke: rgba(37, 99, 235, 0.30); stroke-width: 1.7; }}
    .edge-cross {{ stroke: rgba(245, 158, 11, 0.42); stroke-width: 1.4; stroke-dasharray: 6 6; }}
    .node-2023 {{ fill: rgba(255,255,255,0.92); stroke: #475569; stroke-width: 1.8; }}
    .node-2024 {{ fill: rgba(37,99,235,0.82); stroke: #1d4ed8; stroke-width: 1.6; }}
    .community-ring-2023 {{ fill: rgba(148, 163, 184, 0.06); stroke: rgba(100, 116, 139, 0.22); }}
    .community-ring-2024 {{ fill: rgba(59, 130, 246, 0.05); stroke: rgba(59, 130, 246, 0.20); }}
    .dimmed {{ opacity: 0.08; }}
    .selected {{ opacity: 1 !important; stroke: #ef4444 !important; stroke-width: 3.2 !important; }}
    .selected-node {{ opacity: 1 !important; stroke: #ef4444 !important; stroke-width: 3.2 !important; }}
    .selected-community {{ opacity: 1 !important; stroke: #ef4444 !important; stroke-width: 2.8 !important; }}
    .click-tip {{ margin-top: 8px; color: #64748b; font-size: 12px; }}
    @media (max-width: 1280px) {{
      .page {{ grid-template-columns: 1fr; }}
      .side {{ border-left: 0; border-top: 1px solid #dbe5f1; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <main class="main">
      <section class="hero">
        <div class="title">热点迁移投影叠层图</div>
        <div class="subtitle">
          2023年投影图在底层，2024年投影图在上层；同一年内的项目关联使用实线，跨年度的同主题延续关系使用虚线。点击节点、边或主题簇轮廓，可以在右侧查看详细名称。
        </div>
        <div class="stats" id="stats"></div>
        <div class="controls">
          <label class="toggle"><input type="checkbox" id="toggle-2023" checked />显示 2023 年图层</label>
          <label class="toggle"><input type="checkbox" id="toggle-2024" checked />显示 2024 年图层</label>
          <label class="toggle"><input type="checkbox" id="toggle-cross" checked />显示跨年度虚线</label>
        </div>
      </section>

      <section class="graph-wrap">
        <div class="graph-toolbar">
          <div class="legend">
            <div class="legend-item"><span class="swatch" style="background:#64748b;"></span>2023年项目与边</div>
            <div class="legend-item"><span class="swatch" style="background:#2563eb;"></span>2024年项目与边</div>
            <div class="legend-item"><span class="swatch" style="background:linear-gradient(90deg,#f59e0b 0 50%, transparent 50%); border:1px dashed #f59e0b;"></span>跨年度虚线连接</div>
          </div>
          <div class="hint">提示：浏览器可直接缩放页面，图内可滚动浏览。</div>
        </div>
        <div class="canvas-shell">
          <svg id="graph" viewBox="0 0 __WIDTH__ __HEIGHT__" xmlns="http://www.w3.org/2000/svg">
            <g id="community-rings-2023"></g>
            <g id="edges-2023"></g>
            <g id="nodes-2023"></g>
            <g id="community-labels-2023"></g>
            <g id="edges-cross"></g>
            <g id="community-rings-2024"></g>
            <g id="edges-2024"></g>
            <g id="nodes-2024"></g>
            <g id="community-labels-2024"></g>
          </svg>
        </div>
      </section>
    </main>

    <aside class="side">
      <section class="panel">
        <div class="panel-title">点击信息</div>
        <div id="detail" class="hint">先点击一个节点、边或主题簇轮廓。</div>
        <div class="click-tip">节点名称和主题簇名称默认都不显示，点击后在这里查看。</div>
      </section>
      <section class="panel">
        <div class="panel-title">主题簇查找</div>
        <input id="community-search" class="search" placeholder="输入主题簇名称筛选" />
        <div id="community-list" class="list"></div>
      </section>
      <section class="panel">
        <div class="panel-title">结论摘要</div>
        <div id="insights" class="hint"></div>
      </section>
    </aside>
  </div>

  <script>
    const DATA = __DATA_JSON__;

    const statsEl = document.getElementById('stats');
    const detailEl = document.getElementById('detail');
    const insightsEl = document.getElementById('insights');
    const communityListEl = document.getElementById('community-list');
    const communitySearchEl = document.getElementById('community-search');

    const allEdges = [
      ...DATA.edges.windowA,
      ...DATA.edges.windowB,
      ...DATA.edges.crossYear
    ];

    const nodeMap = new Map(DATA.nodes.map((node) => [node.id, node]));
    const communityMap = new Map(DATA.communities.map((item) => [item.id, item]));
    const edgeMap = new Map(allEdges.map((edge) => [edge.id, edge]));

    const domRefs = {{
      node: new Map(),
      edge: new Map(),
      community: new Map(),
    }};

    function statCard(label, value) {{
      return `
        <div class="stat">
          <div class="stat-label">${{label}}</div>
          <div class="stat-value">${{value}}</div>
        </div>
      `;
    }}

    function renderStats() {{
      const pA = DATA.periods.windowA;
      const pB = DATA.periods.windowB;
      statsEl.innerHTML = [
        statCard(`${{pA.label}}项目节点`, pA.nodeCount),
        statCard(`${{pA.label}}项目关联`, pA.edgeCount),
        statCard(`${{pB.label}}项目节点`, pB.nodeCount),
        statCard(`${{pB.label}}项目关联`, pB.edgeCount),
        statCard('主题簇总数', pA.communityCount + pB.communityCount),
        statCard('跨年度虚线连接', DATA.edges.crossYear.length),
      ].join('');
    }}

    function renderInsights() {{
      insightsEl.innerHTML = (DATA.insightDraft || []).map((line) => `<div>${{line}}</div>`).join('');
    }}

    function createSvgEl(tag, attrs = {{}}, text = '') {{
      const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
      if (text) el.textContent = text;
      return el;
    }}

    function nodeRadius(period) {{
      return period === DATA.periods.windowB.label ? 4.2 : 3.8;
    }}

    function communityGroupId(period) {{
      return period === DATA.periods.windowA.label ? 'community-labels-2023' : 'community-labels-2024';
    }}

    function communityRingId(period) {{
      return period === DATA.periods.windowA.label ? 'community-rings-2023' : 'community-rings-2024';
    }}

    function nodeGroupId(period) {{
      return period === DATA.periods.windowA.label ? 'nodes-2023' : 'nodes-2024';
    }}

    function edgeGroupId(period) {{
      if (period === 'cross') return 'edges-cross';
      return period === DATA.periods.windowA.label ? 'edges-2023' : 'edges-2024';
    }}

    function showDetail(title, rows) {{
      detailEl.innerHTML = `
        <div class="detail-title">${{title}}</div>
        <div class="detail-meta">
          ${rows.map((row) => `<div><strong>${{row.label}}：</strong>${{row.value}}</div>`).join('')}
        </div>
      `;
    }}

    function clearSelection() {{
      document.querySelectorAll('.dimmed').forEach((el) => el.classList.remove('dimmed'));
      document.querySelectorAll('.selected').forEach((el) => el.classList.remove('selected'));
      document.querySelectorAll('.selected-node').forEach((el) => el.classList.remove('selected-node'));
      document.querySelectorAll('.selected-community').forEach((el) => el.classList.remove('selected-community'));
    }}

    function dimAll() {{
      [...domRefs.edge.values(), ...domRefs.node.values(), ...domRefs.community.values()].forEach((el) => {{
        el.classList.add('dimmed');
      }});
    }}

    function selectNode(nodeId) {{
      const node = nodeMap.get(nodeId);
      if (!node) return;
      clearSelection();
      dimAll();
      const nodeEl = domRefs.node.get(nodeId);
      if (nodeEl) {{
        nodeEl.classList.remove('dimmed');
        nodeEl.classList.add('selected-node');
      }}
      domRefs.community.forEach((el, key) => {{
        const item = communityMap.get(key);
        if (item && item.period === node.period && item.communityId === node.communityId) {{
          el.classList.remove('dimmed');
          el.classList.add('selected-community');
        }}
      }});
      allEdges.forEach((edge) => {{
        if (edge.source === nodeId || edge.target === nodeId) {{
          const edgeEl = domRefs.edge.get(edge.id);
          if (edgeEl) {{
            edgeEl.classList.remove('dimmed');
            edgeEl.classList.add('selected');
          }}
          const other = edge.source === nodeId ? edge.target : edge.source;
          const otherEl = domRefs.node.get(other);
          if (otherEl) otherEl.classList.remove('dimmed');
        }}
      }});

      showDetail(node.projectName || node.title, [
        {{ label: '所属年份', value: node.period }},
        {{ label: '项目名称', value: node.projectName || node.title }},
        {{ label: '关键词/指南名', value: node.guideName || '无' }},
        {{ label: '主题簇名称', value: node.communityName }},
        {{ label: '主题簇排序', value: `第 ${{node.communityRank}}` }},
        {{ label: '部门', value: node.department || '无' }},
        {{ label: '单位', value: node.office || '无' }},
        {{ label: '节点 ID', value: String(node.id) }},
      ]);
    }}

    function selectEdge(edgeId) {{
      const edge = edgeMap.get(edgeId);
      if (!edge) return;
      clearSelection();
      dimAll();
      const edgeEl = domRefs.edge.get(edgeId);
      if (edgeEl) {{
        edgeEl.classList.remove('dimmed');
        edgeEl.classList.add('selected');
      }}
      [edge.source, edge.target].forEach((nodeId) => {{
        const nodeEl = domRefs.node.get(nodeId);
        if (nodeEl) {{
          nodeEl.classList.remove('dimmed');
          nodeEl.classList.add('selected-node');
        }}
      }});

      const edgeType = edge.kind === 'cross' ? '跨年度虚线连接' : `${edge.period}内部实线关联`;
      showDetail(edge.sharedTopic || edgeType, [
        {{ label: '连线类型', value: edgeType }},
        {{ label: '起点项目', value: edge.sourceName }},
        {{ label: '终点项目', value: edge.targetName }},
        {{ label: '起点主题簇', value: edge.sourceCommunity || '无' }},
        {{ label: '终点主题簇', value: edge.targetCommunity || '无' }},
        {{ label: '关联关键词', value: edge.sharedTopic || '无' }},
      ]);
    }}

    function selectCommunity(communityId) {{
      const community = communityMap.get(communityId);
      if (!community) return;
      clearSelection();
      dimAll();
      const communityEl = domRefs.community.get(communityId);
      if (communityEl) {{
        communityEl.classList.remove('dimmed');
        communityEl.classList.add('selected-community');
      }}

      DATA.nodes.forEach((node) => {{
        if (node.period === community.period && node.communityId === community.communityId) {{
          const nodeEl = domRefs.node.get(node.id);
          if (nodeEl) nodeEl.classList.remove('dimmed');
        }}
      }});

      allEdges.forEach((edge) => {{
        const source = nodeMap.get(edge.source);
        const target = nodeMap.get(edge.target);
        const hit = (source && source.period === community.period && source.communityId === community.communityId)
          || (target && target.period === community.period && target.communityId === community.communityId);
        if (hit) {{
          const edgeEl = domRefs.edge.get(edge.id);
          if (edgeEl) edgeEl.classList.remove('dimmed');
        }}
      }});

      showDetail(community.name, [
        {{ label: '所属年份', value: community.period }},
        {{ label: '主题簇名称', value: community.name }},
        {{ label: '主题簇排序', value: `第 ${{community.rank}}` }},
        {{ label: '项目数量', value: String(community.size) }},
        {{ label: '代表关键词', value: (community.topKeywords || []).slice(0, 5).join('、') || '无' }},
      ]);
    }}

    function renderCommunities() {{
      DATA.communities.forEach((community) => {{
        const ringGroup = document.getElementById(communityRingId(community.period));
        const labelGroup = document.getElementById(communityGroupId(community.period));
        const ringClass = community.period === DATA.periods.windowA.label ? 'community-ring-2023' : 'community-ring-2024';

        const ring = createSvgEl('circle', {{
          cx: community.x,
          cy: community.y,
          r: community.radius,
          class: `${{ringClass}} community-anchor`,
          'data-community-id': community.id,
        }});
        ring.addEventListener('click', () => selectCommunity(community.id));
        ringGroup.appendChild(ring);
        domRefs.community.set(community.id, ring);

      }});
    }}

    function renderEdges() {{
      allEdges.forEach((edge) => {{
        const source = nodeMap.get(edge.source);
        const target = nodeMap.get(edge.target);
        if (!source || !target) return;
        const group = document.getElementById(edgeGroupId(edge.period));
        let cls = 'edge-cross';
        if (edge.period === DATA.periods.windowA.label) cls = 'edge-2023';
        if (edge.period === DATA.periods.windowB.label) cls = 'edge-2024';
        const line = createSvgEl('line', {{
          x1: source.x,
          y1: source.y,
          x2: target.x,
          y2: target.y,
          class: cls,
          'data-edge-id': edge.id,
        }});
        line.addEventListener('click', () => selectEdge(edge.id));
        group.appendChild(line);
        domRefs.edge.set(edge.id, line);
      }});
    }}

    function renderNodes() {{
      DATA.nodes.forEach((node) => {{
        const group = document.getElementById(nodeGroupId(node.period));
        const cls = node.period === DATA.periods.windowA.label ? 'node-2023' : 'node-2024';
        const circle = createSvgEl('circle', {{
          cx: node.x,
          cy: node.y,
          r: nodeRadius(node.period),
          class: cls,
          'data-node-id': node.id,
        }});
        circle.addEventListener('click', () => selectNode(node.id));
        group.appendChild(circle);
        domRefs.node.set(node.id, circle);
      }});
    }}

    function renderCommunityList(filterText = '') {{
      const text = filterText.trim().toLowerCase();
      const rows = DATA.communities
        .filter((item) => !text || item.name.toLowerCase().includes(text))
        .sort((a, b) => {{
          if (a.period !== b.period) return a.period.localeCompare(b.period);
          if (a.rank !== b.rank) return a.rank - b.rank;
          return a.name.localeCompare(b.name);
        }});

      communityListEl.innerHTML = rows.map((item) => `
        <div class="list-item" data-community-id="${{item.id}}">
          <div class="list-item-title">${{item.name}}</div>
          <div class="list-item-meta">${{item.period}} · 第${{item.rank}}位 · ${{item.size}}个项目</div>
        </div>
      `).join('');

      communityListEl.querySelectorAll('.list-item').forEach((el) => {{
        el.addEventListener('click', () => selectCommunity(el.getAttribute('data-community-id')));
      }});
    }}

    function applyVisibility() {{
      const show2023 = document.getElementById('toggle-2023').checked;
      const show2024 = document.getElementById('toggle-2024').checked;
      const showCross = document.getElementById('toggle-cross').checked;

      ['community-rings-2023', 'edges-2023', 'nodes-2023', 'community-labels-2023'].forEach((id) => {{
        document.getElementById(id).style.display = show2023 ? '' : 'none';
      }});
      ['community-rings-2024', 'edges-2024', 'nodes-2024', 'community-labels-2024'].forEach((id) => {{
        document.getElementById(id).style.display = show2024 ? '' : 'none';
      }});
      document.getElementById('edges-cross').style.display = showCross ? '' : 'none';
    }}

    document.getElementById('toggle-2023').addEventListener('change', applyVisibility);
    document.getElementById('toggle-2024').addEventListener('change', applyVisibility);
    document.getElementById('toggle-cross').addEventListener('change', applyVisibility);
    communitySearchEl.addEventListener('input', (event) => renderCommunityList(event.target.value));

    renderStats();
    renderInsights();
    renderCommunities();
    renderEdges();
    renderNodes();
    renderCommunityList();
    applyVisibility();
  </script>
</body>
</html>"""
        return (
            template
            .replace("{{", "{")
            .replace("}}", "}")
            .replace("__DATA_JSON__", data_json)
            .replace("__WIDTH__", str(CANVAS_WIDTH))
            .replace("__HEIGHT__", str(CANVAS_HEIGHT))
        )


def main() -> int:
    args = parse_args()
    input_json = Path(args.input_json).resolve()
    output_html = Path(args.output_html).resolve()
    print(f"[OVERLAY] load full result | input={input_json}")
    result = load_full_result(input_json)

    meta = result.get("meta", {}) or {}
    analysis_mode = str(meta.get("analysisMode") or "").strip()
    strategy = pick_strategy(analysis_mode)
    cfg = build_config()

    communities = result.get("communities", {}) or {}
    node_ids_a = [int(node_id) for item in (communities.get("windowA", []) or []) for node_id in (item.get("nodeIds", []) or [])]
    node_ids_b = [int(node_id) for item in (communities.get("windowB", []) or []) for node_id in (item.get("nodeIds", []) or [])]

    print(f"[OVERLAY] connect neo4j | database={cfg.database}")
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
            print(f"[OVERLAY] fetch node details | {meta.get('windowA', {}).get('start')}")
            node_lookup_a = fetch_node_details(session, node_ids_a)
            print(f"[OVERLAY] fetch node details | {meta.get('windowB', {}).get('start')}")
            node_lookup_b = fetch_node_details(session, node_ids_b)

            window_a = meta.get("windowA", {}) or {}
            window_b = meta.get("windowB", {}) or {}
            print(f"[OVERLAY] fetch edges | {window_a.get('start')}-{window_a.get('end')}")
            edges_a_raw = fetch_projection_edges(
                session,
                strategy.rel_query_template,
                int(window_a.get("start")),
                int(window_a.get("end")),
                int((meta.get("threshold", {}) or {}).get("maxEdges", cfg.max_edges)),
            )
            print(f"[OVERLAY] fetch edges | {window_b.get('start')}-{window_b.get('end')}")
            edges_b_raw = fetch_projection_edges(
                session,
                strategy.rel_query_template,
                int(window_b.get("start")),
                int(window_b.get("end")),
                int((meta.get("threshold", {}) or {}).get("maxEdges", cfg.max_edges)),
            )
    finally:
        driver.close()

    print("[OVERLAY] build overlay payload")
    payload = build_payload(result, output_html, node_lookup_a, node_lookup_b, edges_a_raw, edges_b_raw)
    print("[OVERLAY] write html")
    ProjectionOverlayHtmlBuilder().build(payload, output_html)
    print(f"[OVERLAY] done | output={output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
