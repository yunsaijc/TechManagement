#!/usr/bin/env python3
"""生成“主题簇即节点”的热点迁移 HTML。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_INPUT_JSON = (
    PROJECT_ROOT
    / "src/services/sandbox/output/hotspot_migration_real_schema_2023_to_2024.json"
)
DEFAULT_OUTPUT_HTML = (
    PROJECT_ROOT
    / "src/services/sandbox/output/hotspot_migration_real_schema_2023_to_2024.cluster_nodes.html"
)

CANVAS_WIDTH = 3200
CANVAS_HEIGHT = 2400
CENTER_X = CANVAS_WIDTH / 2
TOP_CENTER_Y = 700
BOTTOM_CENTER_Y = 1700
MAX_RENDER_LINKS = 1200
MAX_LINKS_PER_SOURCE = 2
MAX_LINKS_PER_TARGET = 2
SESSION_KWARGS = {
    "notifications_disabled_classifications": ["DEPRECATION"],
}
REGION_PADDING_X = 120.0
REGION_PADDING_Y = 120.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成主题簇节点版热点迁移 HTML")
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT_JSON), help="Step2 全量输出 JSON")
    parser.add_argument("--output-html", default=str(DEFAULT_OUTPUT_HTML), help="HTML 输出路径")
    return parser.parse_args()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_full_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def build_driver() -> tuple[Any, str]:
    uri = getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687")
    user = getenv_required("NEO4J_USER", "neo4j")
    password = getenv_required("NEO4J_PASSWORD")
    database = getenv_required("NEO4J_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    return driver, database


def _batch(values: list[int], size: int = 500) -> list[list[int]]:
    return [values[idx: idx + size] for idx in range(0, len(values), size)]


def fetch_project_names(session: Any, node_ids: list[int]) -> dict[int, str]:
    if not node_ids:
        return {}

    query = """
    UNWIND $ids AS nid
    MATCH (n)
    WHERE id(n) = nid
    RETURN
      nid AS nodeId,
      coalesce(
        n.projectName,
        n.name,
        n.title,
        n.guideName,
        toString(id(n))
      ) AS projectName
    """

    result: dict[int, str] = {}
    for batch in _batch(sorted(set(node_ids))):
        for row in session.run(query, {"ids": batch}):
            result[int(row["nodeId"])] = str(row["projectName"] or row["nodeId"])
    return result


def _dedup_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedup_keywords(values: list[Any], limit: int = 5) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _community_display_name(item: dict[str, Any]) -> str:
    keywords = _dedup_keywords(item.get("topKeywords", []) or item.get("keywordSet", []), limit=3)
    if keywords:
        return keywords[0]
    community_id = item.get("communityId")
    return f"热点分组{community_id}" if community_id is not None else "未命名方向"


def build_community_payload(
    items: list[dict[str, Any]],
    period_label: str,
    project_name_map: dict[int, str],
) -> list[dict[str, Any]]:
    communities: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda x: int(x.get("rank", 0) or 0)):
        node_ids = [int(node_id) for node_id in (item.get("nodeIds", []) or [])]
        project_names = _dedup_keep_order([project_name_map.get(node_id, str(node_id)) for node_id in node_ids])
        communities.append(
            {
                "id": f"{period_label}-C{int(item.get('communityId'))}",
                "period": period_label,
                "communityId": int(item.get("communityId")),
                "rank": int(item.get("rank", 0) or 0),
                "size": int(item.get("size", 0) or 0),
                "name": _community_display_name(item),
                "topKeywords": _dedup_keep_order([str(x) for x in (item.get("topKeywords", []) or [])])[:8],
                "projectNames": project_names,
            }
        )
    return communities


def _stable_seed(*parts: Any) -> int:
    text = "||".join(str(part) for part in parts)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _scatter_positions(
    communities: list[dict[str, Any]],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    seed_key: str,
) -> list[dict[str, Any]]:
    placed: list[dict[str, Any]] = []
    occupied: list[dict[str, float]] = []
    if not communities:
        return placed

    ordered = sorted(
        communities,
        key=lambda item: (-int(item["size"]), int(item["rank"]), str(item["name"])),
    )
    base_rng = random.Random(_stable_seed(seed_key, len(ordered)))

    for index, item in enumerate(ordered):
        radius = 14 + math.sqrt(max(1, int(item["size"]))) * 5.6
        gap = 36.0 if index < 40 else 22.0 if index < 160 else 12.0
        best: tuple[float, float, float] | None = None
        item_rng = random.Random(_stable_seed(seed_key, item["communityId"], item["name"], item["size"]))

        for attempt in range(220):
            if attempt < 120:
                x = item_rng.uniform(min_x + radius, max_x - radius)
                y = item_rng.uniform(min_y + radius, max_y - radius)
            else:
                x = base_rng.uniform(min_x + radius, max_x - radius)
                y = base_rng.uniform(min_y + radius, max_y - radius)

            nearest = float("inf")
            valid = True
            for other in occupied:
                dx = x - other["x"]
                dy = y - other["y"]
                dist = math.hypot(dx, dy)
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
        placed.append(
            {
                **item,
                "x": round(x, 2),
                "y": round(y, 2),
                "radius": round(radius, 2),
            }
        )

    return placed


def place_communities(
    communities: list[dict[str, Any]],
    center_x: float,
    center_y: float,
) -> list[dict[str, Any]]:
    top_half = center_y < (CANVAS_HEIGHT / 2)
    min_x = REGION_PADDING_X
    max_x = CANVAS_WIDTH - REGION_PADDING_X
    if top_half:
        min_y = REGION_PADDING_Y
        max_y = CANVAS_HEIGHT / 2 - REGION_PADDING_Y
        seed_key = "top"
    else:
        min_y = CANVAS_HEIGHT / 2 + REGION_PADDING_Y
        max_y = CANVAS_HEIGHT - REGION_PADDING_Y
        seed_key = "bottom"
    return _scatter_positions(communities, min_x, max_x, min_y, max_y, seed_key)


def _parse_link_id(raw: str, prefix: str) -> int | None:
    text = str(raw or "")
    if text.startswith(prefix):
        text = text[len(prefix):]
    try:
        return int(text)
    except Exception:
        return None


def build_links(
    sankey_links: list[dict[str, Any]],
    communities_a: list[dict[str, Any]],
    communities_b: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    map_a = {int(item["communityId"]): item for item in communities_a}
    map_b = {int(item["communityId"]): item for item in communities_b}
    candidates: list[dict[str, Any]] = []

    for index, item in enumerate(sankey_links, start=1):
        source_id = _parse_link_id(str(item.get("source")), "A-")
        target_id = _parse_link_id(str(item.get("target")), "B-")
        if source_id is None or target_id is None:
            continue
        source = map_a.get(source_id)
        target = map_b.get(target_id)
        if not source or not target:
            continue
        candidates.append(
            {
                "id": f"link-{index}",
                "source": source["id"],
                "target": target["id"],
                "sourceName": source["name"],
                "targetName": target["name"],
                "sourceSize": int(source["size"]),
                "targetSize": int(target["size"]),
                "sourceRank": int(source["rank"]),
                "targetRank": int(target["rank"]),
                "value": int(item.get("value", 0) or 0),
                "jaccard": float(item.get("jaccard", 0.0) or 0.0),
            }
        )

    candidates.sort(
        key=lambda item: (
            int(item["value"]),
            float(item["jaccard"]),
            min(int(item["sourceSize"]), int(item["targetSize"])),
            int(item["sourceSize"]) + int(item["targetSize"]),
            -int(item["sourceRank"]),
            -int(item["targetRank"]),
        ),
        reverse=True,
    )

    links: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    for item in candidates:
        source_key = str(item["source"])
        target_key = str(item["target"])
        if source_counts.get(source_key, 0) >= MAX_LINKS_PER_SOURCE:
            continue
        if target_counts.get(target_key, 0) >= MAX_LINKS_PER_TARGET:
            continue
        links.append(
            {
                "id": str(item["id"]),
                "source": str(item["source"]),
                "target": str(item["target"]),
                "sourceName": str(item["sourceName"]),
                "targetName": str(item["targetName"]),
                "value": int(item["value"]),
                "jaccard": float(item["jaccard"]),
                "strokeWidth": round(1.2 + math.log1p(int(item["value"])) * 2.4, 2),
            }
        )
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        target_counts[target_key] = target_counts.get(target_key, 0) + 1
        if len(links) >= MAX_RENDER_LINKS:
            break
    return links


def build_payload(
    result: dict[str, Any],
    output_html_path: Path,
    project_name_map: dict[int, str],
    lite_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = result.get("meta", {}) or {}
    communities_block = result.get("communities", {}) or {}
    sankey = result.get("sankey", {}) or {}

    label_2023 = f"{int((meta.get('windowA', {}) or {}).get('start', 2023))}年"
    label_2024 = f"{int((meta.get('windowB', {}) or {}).get('start', 2024))}年"

    communities_2023 = build_community_payload(
        communities_block.get("windowA", []) or [],
        label_2023,
        project_name_map,
    )
    communities_2024 = build_community_payload(
        communities_block.get("windowB", []) or [],
        label_2024,
        project_name_map,
    )

    positioned_2024 = place_communities(communities_2024, CENTER_X, TOP_CENTER_Y)
    positioned_2023 = place_communities(communities_2023, CENTER_X, BOTTOM_CENTER_Y)
    all_communities = positioned_2024 + positioned_2023
    links = build_links(sankey.get("links", []) or [], positioned_2023, positioned_2024)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceJson": str(DEFAULT_INPUT_JSON),
        "outputHtml": str(output_html_path),
        "report": {
            "summary": (lite_payload or {}).get("summary", {}) or {},
            "overview": (lite_payload or {}).get("overview", {}) or {},
            "topGroups": (lite_payload or {}).get("topGroups", {}) or {},
            "keyChanges": (lite_payload or {}).get("keyChanges", []) or [],
            "insightDraft": (lite_payload or {}).get("insightDraft", []) or [],
        },
        "periods": {
            "top": {
                "label": label_2024,
                "communityCount": len(positioned_2024),
                "projectCount": sum(int(item["size"]) for item in positioned_2024),
            },
            "bottom": {
                "label": label_2023,
                "communityCount": len(positioned_2023),
                "projectCount": sum(int(item["size"]) for item in positioned_2023),
            },
        },
        "canvas": {
            "width": CANVAS_WIDTH,
            "height": CANVAS_HEIGHT,
        },
        "communities": all_communities,
        "links": links,
        "insightDraft": [
            f"每个球代表一个主题簇，球越大说明这个簇里的项目越多。",
            f"{label_2024}位于上半区，共 {len(positioned_2024)} 个主题簇；{label_2023}位于下半区，共 {len(positioned_2023)} 个主题簇。",
            f"为保证打开和交互流畅，虚线只保留了较重要的跨年联系，本图共展示 {len(links)} 条。",
            "簇内具体项目默认不展开，点击圆球后会在右侧显示该簇的项目清单。",
        ],
    }


class ClusterNodeHtmlBuilder:
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
  <title>主题簇节点图</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f4f7fb; color: #0f172a; }}
    .page {{ display: grid; grid-template-columns: minmax(0, 1fr) 420px; min-height: 100vh; }}
    .main {{ padding: 18px; }}
    .hero {{ padding: 18px 20px; border: 1px solid #dbe5f1; border-radius: 18px; background: linear-gradient(135deg, #ffffff 0%, #eef6ff 100%); box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05); }}
    .title {{ font-size: 26px; font-weight: 800; }}
    .subtitle {{ margin-top: 8px; color: #475569; font-size: 13px; line-height: 1.7; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }}
    .stat {{ padding: 12px 14px; border-radius: 14px; background: rgba(255,255,255,0.92); border: 1px solid #dbe5f1; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 4px; font-size: 22px; font-weight: 800; }}
    .controls {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }}
    .toggle {{ display: flex; gap: 8px; align-items: center; padding: 8px 10px; border-radius: 999px; background: #fff; border: 1px solid #dbe5f1; font-size: 13px; }}
    .graph-wrap {{ margin-top: 16px; padding: 14px; border-radius: 18px; background: #fff; border: 1px solid #dbe5f1; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04); }}
    .summary-title {{ font-size: 14px; font-weight: 800; margin: 12px 0 8px; }}
    .summary-empty {{ color: #94a3b8; font-size: 13px; }}
    .summary-list {{ display: grid; gap: 10px; }}
    .summary-item {{ padding: 12px 14px; border-radius: 12px; background: #f8fafc; border: 1px solid #e2e8f0; font-size: 13px; line-height: 1.7; }}
    .group-columns {{ display: grid; gap: 12px; }}
    .group-column {{ padding: 12px; border-radius: 14px; background: #f8fafc; border: 1px solid #e2e8f0; }}
    .group-column-title {{ font-size: 14px; font-weight: 800; margin-bottom: 10px; }}
    .group-items {{ display: grid; gap: 10px; }}
    .group-item {{ padding: 10px 12px; border-radius: 12px; background: #fff; border: 1px solid #e2e8f0; }}
    .group-item-name {{ font-size: 13px; font-weight: 800; line-height: 1.6; }}
    .group-item-meta {{ margin-top: 4px; color: #64748b; font-size: 12px; }}
    .group-item-desc {{ margin-top: 6px; color: #334155; font-size: 12px; line-height: 1.7; }}
    .group-keywords {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }}
    .keyword-chip {{ padding: 4px 8px; border-radius: 999px; background: #e9f2ff; color: #1d4ed8; font-size: 12px; }}
    .graph-toolbar {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }}
    .legend {{ display: flex; gap: 14px; flex-wrap: wrap; color: #475569; font-size: 12px; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
    .swatch {{ width: 24px; height: 12px; border-radius: 999px; display: inline-block; }}
    .canvas-shell {{ overflow: auto; max-height: calc(100vh - 230px); border-radius: 14px; border: 1px solid #e2e8f0; background: #f8fafc; }}
    svg {{ width: __WIDTH__px; height: __HEIGHT__px; display: block; background:
      radial-gradient(circle at 30% 18%, rgba(59,130,246,0.06), transparent 20%),
      radial-gradient(circle at 70% 82%, rgba(100,116,139,0.06), transparent 20%),
      linear-gradient(180deg, rgba(37,99,235,0.03) 0 48%, rgba(71,85,105,0.03) 52% 100%),
      #f8fafc; }}
    .side {{ border-left: 1px solid #dbe5f1; background: #ffffff; padding: 18px; overflow: auto; }}
    .panel {{ border: 1px solid #e2e8f0; border-radius: 16px; padding: 14px; background: #fff; }}
    .panel + .panel {{ margin-top: 14px; }}
    .panel-title {{ font-size: 15px; font-weight: 800; margin-bottom: 10px; }}
    .hint {{ font-size: 12px; color: #64748b; line-height: 1.7; }}
    .detail-title {{ font-size: 16px; font-weight: 800; line-height: 1.6; }}
    .detail-meta {{ margin-top: 8px; display: grid; gap: 6px; font-size: 13px; color: #334155; }}
    .project-list {{ margin-top: 12px; max-height: 420px; overflow: auto; display: grid; gap: 8px; }}
    .project-item {{ padding: 8px 10px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; font-size: 13px; line-height: 1.6; }}
    .search {{ width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid #dbe5f1; outline: none; }}
    .list {{ display: grid; gap: 8px; max-height: 360px; overflow: auto; margin-top: 12px; }}
    .list-item {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 12px; cursor: pointer; background: #fff; }}
    .list-item:hover {{ border-color: #93c5fd; background: #eff6ff; }}
    .list-item-title {{ font-size: 13px; font-weight: 700; line-height: 1.6; }}
    .list-item-meta {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
    .node-2024 {{ fill: rgba(37, 99, 235, 0.78); stroke: #1d4ed8; stroke-width: 2; cursor: pointer; }}
    .node-2023 {{ fill: rgba(71, 85, 105, 0.58); stroke: #334155; stroke-width: 2; cursor: pointer; }}
    .link {{ stroke: rgba(245, 158, 11, 0.40); stroke-dasharray: 8 8; fill: none; cursor: pointer; }}
    .label-pill {{ fill: rgba(255,255,255,0.82); stroke: rgba(148,163,184,0.22); stroke-width: 1; }}
    .label-text {{ font-size: 30px; font-weight: 800; fill: #0f172a; }}
    .dimmed {{ opacity: 0.09; }}
    .selected-node {{ opacity: 1 !important; stroke: #ef4444 !important; stroke-width: 4 !important; }}
    .selected-link {{ opacity: 1 !important; stroke: #ef4444 !important; stroke-width: 3.5 !important; }}
    @media (max-width: 1320px) {{
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
        <div class="title">主题簇节点图</div>
        <div class="subtitle">
          这张图不再展示单个项目节点，而是把每个主题簇视为一个球。球越大，说明该主题簇里包含的项目越多。点击球体后，右侧会展开该簇的项目清单。
        </div>
        <div class="stats" id="stats"></div>
        <div class="controls">
          <label class="toggle"><input type="checkbox" id="toggle-2024" checked />显示 2024 年主题簇</label>
          <label class="toggle"><input type="checkbox" id="toggle-2023" checked />显示 2023 年主题簇</label>
          <label class="toggle"><input type="checkbox" id="toggle-links" checked />显示跨年联系</label>
        </div>
      </section>

      <section class="graph-wrap">
        <div class="graph-toolbar">
          <div class="legend">
            <div class="legend-item"><span class="swatch" style="background:#2563eb;"></span>上半区：2024年主题簇</div>
            <div class="legend-item"><span class="swatch" style="background:#475569;"></span>下半区：2023年主题簇</div>
            <div class="legend-item"><span class="swatch" style="background:#f59e0b; border:1px dashed #f59e0b;"></span>跨年联系</div>
          </div>
          <div class="hint">簇内项目信息默认不显示，点击球体后在右侧查看。</div>
        </div>
        <div class="canvas-shell">
          <svg id="graph" viewBox="0 0 __WIDTH__ __HEIGHT__" xmlns="http://www.w3.org/2000/svg">
            <g id="year-labels"></g>
            <g id="links"></g>
            <g id="nodes-2024"></g>
            <g id="nodes-2023"></g>
          </svg>
        </div>
      </section>
    </main>

    <aside class="side">
      <section class="panel">
        <div class="panel-title">点击信息</div>
        <div id="detail" class="hint">先点击一个主题簇球体或一条跨年联系。</div>
      </section>
      <section class="panel">
        <div class="panel-title">主题簇查找</div>
        <input id="community-search" class="search" placeholder="输入主题簇名称筛选" />
        <div id="community-list" class="list"></div>
      </section>
      <section class="panel">
        <div class="panel-title">图示说明</div>
        <div id="insights" class="hint"></div>
      </section>
    </aside>
  </div>

  <script>
    const DATA = __DATA_JSON__;

    const statsEl = document.getElementById('stats');
    const detailEl = document.getElementById('detail');
    const insightsEl = document.getElementById('insights');
    const communitySearchEl = document.getElementById('community-search');
    const communityListEl = document.getElementById('community-list');

    const communityMap = new Map(DATA.communities.map((item) => [item.id, item]));
    const linkMap = new Map(DATA.links.map((item) => [item.id, item]));
    const domRefs = {{
      nodes: new Map(),
      links: new Map(),
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
      const top = DATA.periods.top;
      const bottom = DATA.periods.bottom;
      statsEl.innerHTML = [
        statCard(`${{top.label}}主题簇`, top.communityCount),
        statCard(`${{top.label}}项目数`, top.projectCount),
        statCard(`${{bottom.label}}主题簇`, bottom.communityCount),
        statCard(`${{bottom.label}}项目数`, bottom.projectCount),
        statCard('跨年联系', DATA.links.length),
      ].join('');
    }}

    function renderInsights() {{
      const rows = ((DATA.report || {{}}).insightDraft || []);
      const topGroups = ((DATA.report || {{}}).topGroups || {{}});
      const keyChanges = ((DATA.report || {{}}).keyChanges || []);
      const periods = Object.keys(topGroups);
      const graphTips = (DATA.insightDraft || []).map((line) => `<div>${{line}}</div>`).join('');
      const reportInsightHtml = rows.length
        ? rows.map((line) => `<div class="summary-item">${{line}}</div>`).join('')
        : '<div class="summary-empty">暂无结论摘要</div>';
      const topGroupHtml = periods.length
        ? `
          <div class="group-columns">
            ${{periods.map((period) => `
              <div class="group-column">
                <div class="group-column-title">${{period}}</div>
                <div class="group-items">
                  ${{
                    (topGroups[period] || []).length
                      ? (topGroups[period] || []).map((item) => `
                          <div class="group-item">
                            <div class="group-item-name">${{item.name || '未命名方向'}}</div>
                            <div class="group-item-meta">第${{item.rank || '-'}}位 · 约${{item.projectCount || 0}}个项目</div>
                            <div class="group-item-desc">${{item.description || ''}}</div>
                            <div class="group-keywords">
                              ${{
                                (item.keywords || []).map((kw) => `<span class="keyword-chip">${{kw}}</span>`).join('')
                              }}
                            </div>
                          </div>
                        `).join('')
                      : '<div class="summary-empty">暂无重点领域方向</div>'
                  }}
                </div>
              </div>
            `).join('')}}
          </div>
        `
        : '<div class="summary-empty">暂无重点领域方向</div>';
      const keyChangeHtml = keyChanges.length
        ? keyChanges.map((item) => `
            <div class="summary-item">
              <div><strong>${{item.rank || '-'}}.</strong> 从“${{item.from || '-'}}”到“${{item.to || '-'}}”</div>
              <div style="margin-top:6px;">${{item.description || ''}}</div>
            </div>
          `).join('')
        : '<div class="summary-empty">暂无重点趋势</div>';

      insightsEl.innerHTML = `
        <div>${{graphTips}}</div>
        <div class="summary-title">结论摘要</div>
        <div class="summary-list">${{reportInsightHtml}}</div>
        <div class="summary-title">重点领域方向</div>
        ${{topGroupHtml}}
        <div class="summary-title">重点趋势</div>
        <div class="summary-list">${{keyChangeHtml}}</div>
      `;
    }}

    function createSvgEl(tag, attrs = {{}}, text = '') {{
      const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
      if (text) el.textContent = text;
      return el;
    }}

    function renderYearLabels() {{
      const group = document.getElementById('year-labels');
      const labels = [
        {{ x: 90, y: 95, text: DATA.periods.top.label }},
        {{ x: 90, y: __HEIGHT__ - 105, text: DATA.periods.bottom.label }},
      ];

      labels.forEach((item) => {{
        const width = 180;
        const rect = createSvgEl('rect', {{
          x: item.x - 18,
          y: item.y - 38,
          rx: 28,
          ry: 28,
          width,
          height: 58,
          class: 'label-pill',
        }});
        const text = createSvgEl('text', {{
          x: item.x,
          y: item.y,
          class: 'label-text',
        }}, item.text);
        group.appendChild(rect);
        group.appendChild(text);
      }});
    }}

    function applyVisibility() {{
      const show2024 = document.getElementById('toggle-2024').checked;
      const show2023 = document.getElementById('toggle-2023').checked;
      const showLinks = document.getElementById('toggle-links').checked;

      document.getElementById('nodes-2024').style.display = show2024 ? '' : 'none';
      document.getElementById('nodes-2023').style.display = show2023 ? '' : 'none';
      document.getElementById('links').style.display = showLinks ? '' : 'none';
    }}

    function clearSelection() {{
      document.querySelectorAll('.dimmed').forEach((el) => el.classList.remove('dimmed'));
      document.querySelectorAll('.selected-node').forEach((el) => el.classList.remove('selected-node'));
      document.querySelectorAll('.selected-link').forEach((el) => el.classList.remove('selected-link'));
    }}

    function dimAll() {{
      [...domRefs.nodes.values(), ...domRefs.links.values()].forEach((el) => el.classList.add('dimmed'));
    }}

    function showCommunityDetail(communityId) {{
      const item = communityMap.get(communityId);
      if (!item) return;
      clearSelection();
      dimAll();
      const nodeEl = domRefs.nodes.get(communityId);
      if (nodeEl) {{
        nodeEl.classList.remove('dimmed');
        nodeEl.classList.add('selected-node');
      }}

      DATA.links.forEach((link) => {{
        if (link.source === communityId || link.target === communityId) {{
          const linkEl = domRefs.links.get(link.id);
          if (linkEl) {{
            linkEl.classList.remove('dimmed');
            linkEl.classList.add('selected-link');
          }}
          const another = link.source === communityId ? link.target : link.source;
          const anotherEl = domRefs.nodes.get(another);
          if (anotherEl) anotherEl.classList.remove('dimmed');
        }}
      }});

      const projects = (item.projectNames || []).map((name) => `<div class="project-item">${{name}}</div>`).join('');
      detailEl.innerHTML = `
        <div class="detail-title">${{item.name}}</div>
        <div class="detail-meta">
          <div><strong>所属年份：</strong>${{item.period}}</div>
          <div><strong>主题簇编号：</strong>C${{item.communityId}}</div>
          <div><strong>排序：</strong>第${{item.rank}}位</div>
          <div><strong>项目数量：</strong>${{item.size}}</div>
          <div><strong>代表关键词：</strong>${{(item.topKeywords || []).join('、') || '无'}}</div>
        </div>
        <div class="project-list">${{projects || '<div class="project-item">暂无项目明细</div>'}}</div>
      `;
    }}

    function showLinkDetail(linkId) {{
      const item = linkMap.get(linkId);
      if (!item) return;
      clearSelection();
      dimAll();
      const lineEl = domRefs.links.get(linkId);
      if (lineEl) {{
        lineEl.classList.remove('dimmed');
        lineEl.classList.add('selected-link');
      }}
      [item.source, item.target].forEach((communityId) => {{
        const nodeEl = domRefs.nodes.get(communityId);
        if (nodeEl) {{
          nodeEl.classList.remove('dimmed');
          nodeEl.classList.add('selected-node');
        }}
      }});

      detailEl.innerHTML = `
        <div class="detail-title">跨年联系</div>
        <div class="detail-meta">
          <div><strong>2023年主题簇：</strong>${{item.sourceName}}</div>
          <div><strong>2024年主题簇：</strong>${{item.targetName}}</div>
          <div><strong>重合强度：</strong>${{item.value}}</div>
          <div><strong>相似度：</strong>${{item.jaccard}}</div>
        </div>
      `;
    }}

    function renderLinks() {{
      const group = document.getElementById('links');
      DATA.links.forEach((item) => {{
        const source = communityMap.get(item.source);
        const target = communityMap.get(item.target);
        if (!source || !target) return;
        const line = createSvgEl('line', {{
          x1: source.x,
          y1: source.y,
          x2: target.x,
          y2: target.y,
          class: 'link',
          'stroke-width': item.strokeWidth,
        }});
        line.addEventListener('click', () => showLinkDetail(item.id));
        group.appendChild(line);
        domRefs.links.set(item.id, line);
      }});
    }}

    function renderNodes() {{
      DATA.communities.forEach((item) => {{
        const groupId = item.period === DATA.periods.top.label ? 'nodes-2024' : 'nodes-2023';
        const group = document.getElementById(groupId);
        const circle = createSvgEl('circle', {{
          cx: item.x,
          cy: item.y,
          r: item.radius,
          class: item.period === DATA.periods.top.label ? 'node-2024' : 'node-2023',
        }});
        circle.addEventListener('click', () => showCommunityDetail(item.id));
        group.appendChild(circle);
        domRefs.nodes.set(item.id, circle);
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
        el.addEventListener('click', () => showCommunityDetail(el.getAttribute('data-community-id')));
      }});
    }}

    communitySearchEl.addEventListener('input', (event) => renderCommunityList(event.target.value));
    document.getElementById('toggle-2024').addEventListener('change', applyVisibility);
    document.getElementById('toggle-2023').addEventListener('change', applyVisibility);
    document.getElementById('toggle-links').addEventListener('change', applyVisibility);

    renderStats();
    renderInsights();
    renderYearLabels();
    renderLinks();
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


def build_cluster_node_html_from_result(
    result: dict[str, Any],
    output_html_path: Path | str,
    lite_payload: dict[str, Any] | None = None,
) -> Path:
    output_html = Path(output_html_path).resolve()
    communities_block = result.get("communities", {}) or {}
    all_node_ids = [
        int(node_id)
        for period_key in ("windowA", "windowB")
        for item in (communities_block.get(period_key, []) or [])
        for node_id in (item.get("nodeIds", []) or [])
    ]

    driver, database = build_driver()
    try:
        with driver.session(database=database, **SESSION_KWARGS) as session:
            project_name_map = fetch_project_names(session, all_node_ids)
    finally:
        driver.close()

    payload = build_payload(result, output_html, project_name_map, lite_payload=lite_payload)
    return ClusterNodeHtmlBuilder().build(payload, output_html)


def main() -> int:
    args = parse_args()
    input_json = Path(args.input_json).resolve()
    output_html = Path(args.output_html).resolve()
    lite_json = input_json.with_name(f"{input_json.stem}.lite.json")

    print(f"[CLUSTER_HTML] load result | input={input_json}")
    result = load_full_result(input_json)
    lite_payload = load_optional_json(lite_json)
    if lite_payload is None:
        from src.services.sandbox.hotspot_migration_step2 import build_lite_result

        print("[CLUSTER_HTML] build lite payload from full result")
        lite_payload = build_lite_result(result, str(input_json))
    communities_block = result.get("communities", {}) or {}
    all_node_ids = [
        int(node_id)
        for period_key in ("windowA", "windowB")
        for item in (communities_block.get(period_key, []) or [])
        for node_id in (item.get("nodeIds", []) or [])
    ]

    driver, database = build_driver()
    print(f"[CLUSTER_HTML] connect neo4j | database={database}")
    try:
        with driver.session(database=database, **SESSION_KWARGS) as session:
            print(f"[CLUSTER_HTML] fetch project names | count={len(all_node_ids)}")
            project_name_map = fetch_project_names(session, all_node_ids)
    finally:
        driver.close()

    print("[CLUSTER_HTML] build payload")
    payload = build_payload(result, output_html, project_name_map, lite_payload=lite_payload)
    print("[CLUSTER_HTML] write html")
    ClusterNodeHtmlBuilder().build(payload, output_html)
    print(f"[CLUSTER_HTML] done | output={output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
