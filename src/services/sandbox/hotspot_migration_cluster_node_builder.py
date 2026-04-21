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
    / "src/services/sandbox/output/step2/hotspot_migration_real_schema_2023_to_2024.json"
)
DEFAULT_OUTPUT_HTML = (
    PROJECT_ROOT
    / "src/services/sandbox/output/step2/hotspot_migration_real_schema_2023_to_2024.cluster_nodes.html"
)

CANVAS_WIDTH = 3600
CANVAS_HEIGHT = 2500
PLANE_WIDTH = 2550.0
PLANE_HEIGHT = 820.0
PLANE_PADDING_X = 120.0
PLANE_PADDING_Y = 90.0
LAYER_SKEW_X = 0.08
LAYER_SCALE_Y = 0.78
TOP_LAYER_OFFSET_X = 580.0
TOP_LAYER_OFFSET_Y = 220.0
BOTTOM_LAYER_OFFSET_X = 320.0
BOTTOM_LAYER_OFFSET_Y = 1360.0
MAX_RENDER_LINKS = 1200
MAX_LINKS_PER_SOURCE = 2
MAX_LINKS_PER_TARGET = 2
SESSION_KWARGS = {
    "notifications_disabled_classifications": ["DEPRECATION"],
}
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
                "keywordSet": _dedup_keep_order([str(x) for x in (item.get("keywordSet", []) or item.get("topKeywords", []) or [])])[:32],
                "projectNames": project_names,
            }
        )
    return communities


def _stable_seed(*parts: Any) -> int:
    text = "||".join(str(part) for part in parts)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _node_card_dimensions(size: int) -> tuple[float, float]:
    scale = math.sqrt(max(1, int(size)))
    diameter = min(230.0, max(118.0, 82.0 + scale * 7.6))
    return diameter, diameter


def _scatter_positions(
    communities: list[dict[str, Any]],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    seed_key: str,
) -> list[dict[str, Any]]:
    if not communities:
        return []

    ordered = sorted(
        communities,
        key=lambda item: (-int(item["size"]), int(item["rank"]), str(item["name"])),
    )
    max_diameter = max(_node_card_dimensions(int(item["size"]))[0] for item in ordered)
    column_count = 2 if len(ordered) <= 10 else 3
    row_count = max(1, math.ceil(len(ordered) / column_count))
    center_x = (min_x + max_x) / 2
    base_col_spacing = min((max_x - min_x) / max(column_count, 1), max_diameter * 1.95)
    col_spacing = max(max_diameter * 1.45, base_col_spacing)
    y_step = (max_y - min_y) / (row_count + 1)
    y_step = max(y_step, max_diameter * 1.22)
    total_height = y_step * max(row_count - 1, 0)
    start_y = ((min_y + max_y) / 2) - total_height / 2
    rng = random.Random(_stable_seed(seed_key, len(ordered)))
    x_centers = [
        center_x + (idx - (column_count - 1) / 2.0) * col_spacing
        for idx in range(column_count)
    ]

    placed: list[dict[str, Any]] = []
    for index, item in enumerate(ordered):
        diameter, _ = _node_card_dimensions(int(item["size"]))
        radius = diameter / 2
        col = index // row_count
        row = index % row_count
        x_jitter = rng.uniform(-18.0, 18.0)
        y_jitter = rng.uniform(-20.0, 20.0)
        x = _clamp(x_centers[min(col, column_count - 1)] + x_jitter, min_x + radius, max_x - radius)
        y = _clamp(start_y + row * y_step + y_jitter, min_y + radius, max_y - radius)
        placed.append(
            {
                **item,
                "x": round(x, 2),
                "y": round(y, 2),
                "radius": round(radius, 2),
                "cardWidth": round(diameter, 2),
                "cardHeight": round(diameter, 2),
            }
        )

    return placed


def _project_layer_point(x: float, y: float, layer: str) -> tuple[float, float]:
    if layer == "top":
        offset_x = TOP_LAYER_OFFSET_X
        offset_y = TOP_LAYER_OFFSET_Y
    else:
        offset_x = BOTTOM_LAYER_OFFSET_X
        offset_y = BOTTOM_LAYER_OFFSET_Y
    return (
        round(offset_x + x + y * LAYER_SKEW_X, 2),
        round(offset_y + y * LAYER_SCALE_Y, 2),
    )


def _build_layer_plane(layer: str, label: str) -> dict[str, Any]:
    corners = [
        _project_layer_point(0.0, 0.0, layer),
        _project_layer_point(PLANE_WIDTH, 0.0, layer),
        _project_layer_point(PLANE_WIDTH, PLANE_HEIGHT, layer),
        _project_layer_point(0.0, PLANE_HEIGHT, layer),
    ]
    label_point = _project_layer_point(36.0, 34.0, layer)
    return {
        "id": f"plane-{layer}",
        "layer": layer,
        "label": label,
        "corners": [{"x": x, "y": y} for x, y in corners],
        "labelPoint": {"x": label_point[0], "y": label_point[1]},
    }


def place_communities(
    communities: list[dict[str, Any]],
    layer: str,
) -> list[dict[str, Any]]:
    local = _scatter_positions(
        communities,
        PLANE_PADDING_X,
        PLANE_WIDTH - PLANE_PADDING_X,
        PLANE_PADDING_Y,
        PLANE_HEIGHT - PLANE_PADDING_Y,
        layer,
    )
    projected: list[dict[str, Any]] = []
    for item in local:
        x, y = _project_layer_point(float(item["x"]), float(item["y"]), layer)
        projected.append(
            {
                **item,
                "layer": layer,
                "x": x,
                "y": y,
                "localX": float(item["x"]),
                "localY": float(item["y"]),
            }
        )
    return projected


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
                "kind": "cross_year",
                "layer": "bridge",
                "source": str(item["source"]),
                "target": str(item["target"]),
                "sourceName": str(item["sourceName"]),
                "targetName": str(item["targetName"]),
                "value": int(item["value"]),
                "jaccard": float(item["jaccard"]),
                "strokeWidth": round(1.2 + math.log1p(int(item["value"])) * 2.4, 2),
                "relationLabel": "跨年迁移",
            }
        )
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        target_counts[target_key] = target_counts.get(target_key, 0) + 1
        if len(links) >= MAX_RENDER_LINKS:
            break
    return links


def _community_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[int, float]:
    left_keywords = {str(x).strip() for x in (left.get("keywordSet", []) or []) if str(x).strip()}
    right_keywords = {str(x).strip() for x in (right.get("keywordSet", []) or []) if str(x).strip()}
    overlap = len(left_keywords & right_keywords)
    if overlap <= 0 and str(left.get("name", "")) != str(right.get("name", "")):
        return 0, 0.0
    if str(left.get("name", "")) == str(right.get("name", "")):
        overlap = max(overlap, 1)
    union = len(left_keywords | right_keywords)
    jaccard = (overlap / union) if union > 0 else 0.0
    return overlap, round(jaccard, 4)


def build_same_year_links(
    communities: list[dict[str, Any]],
    layer: str,
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for idx, left in enumerate(communities):
        for right in communities[idx + 1:]:
            overlap, jaccard = _community_similarity(left, right)
            if overlap <= 0:
                continue
            links.append(
                {
                    "id": f"{layer}-internal-{left['communityId']}-{right['communityId']}",
                    "kind": "same_year",
                    "layer": layer,
                    "source": str(left["id"]),
                    "target": str(right["id"]),
                    "sourceName": str(left["name"]),
                    "targetName": str(right["name"]),
                    "value": int(overlap),
                    "jaccard": float(jaccard),
                    "strokeWidth": round(1.0 + math.log1p(int(overlap)) * 1.6, 2),
                    "relationLabel": "同年簇关联",
                }
            )
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

    positioned_2024 = place_communities(communities_2024, "top")
    positioned_2023 = place_communities(communities_2023, "bottom")
    all_communities = positioned_2024 + positioned_2023
    cross_year_links = build_links(sankey.get("links", []) or [], positioned_2023, positioned_2024)
    same_year_links = [
        *build_same_year_links(positioned_2024, "top"),
        *build_same_year_links(positioned_2023, "bottom"),
    ]
    links = [*same_year_links, *cross_year_links]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceJson": str(DEFAULT_INPUT_JSON),
        "outputHtml": str(output_html_path),
        "width": CANVAS_WIDTH,
        "height": CANVAS_HEIGHT,
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
        "planes": {
            "top": _build_layer_plane("top", label_2024),
            "bottom": _build_layer_plane("bottom", label_2023),
        },
        "communities": all_communities,
        "links": links,
        "insightDraft": [
            f"每个圆形节点代表一个主题簇，{label_2024}和{label_2023}分别位于两个年度区域。",
            f"圆形越大说明该簇包含的项目越多；同年簇关联与跨年迁移会同时显示。",
            f"当前共展示 {len(same_year_links)} 条同年关系与 {len(cross_year_links)} 条跨年迁移关系。",
            "点击圆形节点可查看该主题簇的项目清单，点击关系边可查看对应联系说明。",
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
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: radial-gradient(circle at 15% 12%, rgba(37,99,235,0.08), transparent 20%), linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%); color: #0f172a; }}
    .page {{ width: min(100%, 1960px); margin: 0 auto; padding: 20px; display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 24px; align-items: start; min-height: 100vh; }}
    .main {{ min-width: 0; width: 100%; display: grid; gap: 16px; }}
    .hero {{ padding: 22px 24px; border: 1px solid #d8e5f5; border-radius: 22px; background: linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(237,246,255,0.98) 100%); box-shadow: 0 16px 40px rgba(15, 23, 42, 0.07); }}
    .title {{ font-size: 28px; font-weight: 900; letter-spacing: -0.02em; }}
    .subtitle {{ margin-top: 8px; color: #475569; font-size: 13px; line-height: 1.8; max-width: 1040px; }}
    .stats {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }}
    .stat {{ padding: 14px 16px; border-radius: 16px; background: rgba(255,255,255,0.94); border: 1px solid #dbe5f1; box-shadow: inset 0 1px 0 rgba(255,255,255,0.7); }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 6px; font-size: 24px; font-weight: 800; }}
    .controls {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }}
    .toggle {{ display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-radius: 999px; background: rgba(255,255,255,0.96); border: 1px solid #dbe5f1; font-size: 13px; box-shadow: 0 6px 16px rgba(15,23,42,0.04); }}
    .graph-wrap {{ min-width: 0; overflow: hidden; padding: 16px; border-radius: 22px; background: rgba(255,255,255,0.98); border: 1px solid #dbe5f1; box-shadow: 0 16px 38px rgba(15, 23, 42, 0.05); }}
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
    .graph-toolbar {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }}
    .legend {{ display: flex; gap: 14px; flex-wrap: wrap; color: #475569; font-size: 12px; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
    .swatch {{ width: 18px; height: 18px; border-radius: 999px; display: inline-block; }}
    .swatch-sphere-2024 {{ background: #3b82f6; border: 2px solid #1e3a8a; }}
    .swatch-sphere-2023 {{ background: #64748b; border: 2px solid #1f2937; }}
    .canvas-shell {{ width: 100%; max-width: 100%; overflow: auto; max-height: calc(100vh - 220px); border-radius: 18px; border: 1px solid #d8e2ef; background: #f8fafc; overscroll-behavior: contain; }}
    .graph-stage {{ position: relative; width: __WIDTH__px; height: __HEIGHT__px; transform-origin: top left; }}
    svg {{ width: __WIDTH__px; height: __HEIGHT__px; display: block; transform-origin: top left; background:
      radial-gradient(circle at 18% 18%, rgba(37,99,235,0.08), transparent 24%),
      radial-gradient(circle at 78% 72%, rgba(245,158,11,0.08), transparent 24%),
      linear-gradient(rgba(148,163,184,0.14) 1px, transparent 1px),
      linear-gradient(90deg, rgba(148,163,184,0.14) 1px, transparent 1px),
      linear-gradient(180deg, rgba(37,99,235,0.025) 0 48%, rgba(71,85,105,0.025) 52% 100%),
      #f8fafc; }}
    svg {{ background-size: auto, auto, 80px 80px, 80px 80px, auto, auto; user-select: none; -webkit-user-select: none; }}
    .side {{ width: 100%; min-width: 0; max-width: 400px; justify-self: stretch; display: grid; gap: 14px; align-content: start; position: sticky; top: 20px; height: fit-content; max-height: calc(100vh - 40px); overflow: auto; padding-left: 20px; border-left: 1px solid rgba(148,163,184,0.28); }}
    .panel {{ border: 1px solid #dbe5f1; border-radius: 18px; padding: 16px; background: rgba(255,255,255,0.98); box-shadow: 0 14px 32px rgba(15,23,42,0.05); }}
    .panel + .panel {{ margin-top: 0; }}
    .panel-title {{ font-size: 15px; font-weight: 800; margin-bottom: 10px; }}
    .hint {{ font-size: 12px; color: #64748b; line-height: 1.8; }}
    .detail-title {{ font-size: 17px; font-weight: 800; line-height: 1.6; }}
    .detail-meta {{ margin-top: 10px; display: grid; gap: 8px; font-size: 13px; color: #334155; }}
    .project-list {{ margin-top: 14px; max-height: 380px; overflow: auto; display: grid; gap: 8px; }}
    .project-item {{ padding: 8px 10px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; font-size: 13px; line-height: 1.6; }}
    .search {{ width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid #dbe5f1; outline: none; }}
    .list {{ display: grid; gap: 8px; max-height: 360px; overflow: auto; margin-top: 12px; }}
    .list-item {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 12px; cursor: pointer; background: #fff; }}
    .list-item:hover {{ border-color: #93c5fd; background: #eff6ff; }}
    .list-item-title {{ font-size: 13px; font-weight: 700; line-height: 1.6; }}
    .list-item-meta {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
    .kg-node {{ cursor: grab; touch-action: none; }}
    .kg-node.dragging {{ cursor: grabbing; }}
    .kg-node-hit {{ fill: transparent; pointer-events: all; cursor: grab; }}
    .kg-node.dragging .kg-node-hit {{ cursor: grabbing; }}
    .kg-node-circle {{ stroke-width: 3; pointer-events: none; }}
    .kg-node-circle-2024 {{ fill: #3b82f6; stroke: #1e3a8a; }}
    .kg-node-circle-2023 {{ fill: #64748b; stroke: #1f2937; }}
    .relation-cross {{ stroke: #f59e0b; stroke-dasharray: 10 8; fill: none; cursor: pointer; }}
    .relation-same {{ stroke: #6366f1; fill: none; cursor: pointer; }}
    .relation-label-bg {{ fill: rgba(255,255,255,0.92); stroke-width: 1; }}
    .relation-label-bg-cross {{ stroke: rgba(245,158,11,0.40); }}
    .relation-label-bg-top {{ stroke: rgba(37,99,235,0.30); }}
    .relation-label-bg-bottom {{ stroke: rgba(71,85,105,0.24); }}
    .relation-label {{ font-size: 16px; font-weight: 800; pointer-events: none; }}
    .relation-label-cross {{ fill: #92400e; }}
    .relation-label-top {{ fill: #1d4ed8; }}
    .relation-label-bottom {{ fill: #334155; }}
    .label-pill {{ fill: rgba(255,255,255,0.82); stroke: rgba(148,163,184,0.22); stroke-width: 1; }}
    .label-text {{ font-size: 30px; font-weight: 800; fill: #0f172a; }}
    .dimmed {{ opacity: 0.42; }}
    .selected-node {{ opacity: 1 !important; }}
    .selected-node .kg-node-circle {{ stroke: #ef4444 !important; stroke-width: 5 !important; }}
    .selected-link {{ opacity: 1 !important; }}
    .selected-link path,
    .selected-link line {{ stroke: #ef4444 !important; stroke-width: 3.5 !important; }}
    .selected-link .relation-label-bg {{ stroke: rgba(239,68,68,0.42) !important; }}
    .selected-link .relation-label {{ fill: #b91c1c !important; }}
    @media (max-width: 1680px) {{
      .page {{ grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; }}
      .side {{ max-width: 360px; padding-left: 16px; }}
    }}
    @media (max-width: 1480px) {{
      .page {{ grid-template-columns: 1fr; }}
      .side {{ position: static; max-height: none; max-width: none; padding-left: 0; border-left: none; }}
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
          这张图把每个主题簇视为知识图谱中的一个独立圆形节点。两年主题簇会分别排布在上下两个年度区域，同年簇关联和跨年迁移会同时显示；点击圆形节点后，右侧会展开该簇详情。
        </div>
        <div class="stats" id="stats"></div>
        <div class="controls">
          <label class="toggle"><input type="checkbox" id="toggle-2024" checked />显示 2024 年主题簇</label>
          <label class="toggle"><input type="checkbox" id="toggle-2023" checked />显示 2023 年主题簇</label>
          <label class="toggle"><input type="checkbox" id="toggle-links" checked />显示全部关系边</label>
        </div>
      </section>

      <section class="graph-wrap">
        <div class="graph-toolbar">
          <div class="legend">
            <div class="legend-item"><span class="swatch swatch-sphere-2024"></span>2024 主题簇</div>
            <div class="legend-item"><span class="swatch swatch-sphere-2023"></span>2023 主题簇</div>
            <div class="legend-item"><span class="swatch" style="background:#6366f1;"></span>同年簇关联</div>
            <div class="legend-item"><span class="swatch" style="background:#f59e0b;"></span>跨年迁移</div>
          </div>
          <div class="hint">圆形节点代表主题簇，边表示簇间联系；拖动圆形节点可调整位置，滚轮可缩放左侧图，点击节点或边可在右侧查看详细说明。</div>
        </div>
        <div class="canvas-shell">
          <div id="graph-stage" class="graph-stage">
            <svg id="graph" viewBox="0 0 __WIDTH__ __HEIGHT__" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <marker id="arrowhead" markerWidth="18" markerHeight="14" refX="16" refY="7" orient="auto" markerUnits="strokeWidth">
                  <path d="M 0 0 L 18 7 L 0 14 z" fill="#f59e0b"></path>
                </marker>
              </defs>
              <g id="planes"></g>
              <g id="year-labels"></g>
              <g id="links"></g>
              <g id="nodes-2024"></g>
              <g id="nodes-2023"></g>
            </svg>
          </div>
        </div>
      </section>
    </main>

    <aside class="side">
      <section class="panel">
        <div class="panel-title">关系详情</div>
        <div id="detail" class="hint">先点击一个主题实体或一条关系边。</div>
      </section>
      <section class="panel">
        <div class="panel-title">主题簇查找</div>
        <input id="community-search" class="search" placeholder="输入主题簇名称筛选" />
        <div id="community-list" class="list"></div>
      </section>
      <section class="panel">
        <div class="panel-title">图谱说明</div>
        <div id="insights" class="hint"></div>
      </section>
    </aside>
  </div>

  <script>
    const DATA = __DATA_JSON__;

    const graphEl = document.getElementById('graph');
    const graphStageEl = document.getElementById('graph-stage');
    const canvasShellEl = document.querySelector('.canvas-shell');
    const statsEl = document.getElementById('stats');
    const detailEl = document.getElementById('detail');
    const insightsEl = document.getElementById('insights');
    const communitySearchEl = document.getElementById('community-search');
    const communityListEl = document.getElementById('community-list');

    const communityMap = new Map(DATA.communities.map((item) => [item.id, item]));
    const linkMap = new Map(DATA.links.map((item) => [item.id, item]));
    const GRAPH_WIDTH = Number((DATA.canvas || {{}}).width || DATA.width || __WIDTH__);
    const GRAPH_HEIGHT = Number((DATA.canvas || {{}}).height || DATA.height || __HEIGHT__);
    const domRefs = {{
      nodes: new Map(),
      links: new Map(),
    }};
    const zoomState = {{
      scale: 1,
      min: 0.28,
      max: 1.95,
      step: 0.16,
    }};
    const selectionState = {{
      type: null,
      id: null,
    }};
    const dragState = {{
      communityId: null,
      moved: false,
      nodeEl: null,
      startClientX: 0,
      startClientY: 0,
      startX: 0,
      startY: 0,
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
      const sameYearCount = DATA.links.filter((item) => item.kind === 'same_year').length;
      const crossYearCount = DATA.links.filter((item) => item.kind === 'cross_year').length;
      statsEl.innerHTML = [
        statCard(`${{top.label}}主题簇`, top.communityCount),
        statCard(`${{bottom.label}}主题簇`, bottom.communityCount),
        statCard('同年关系', sameYearCount),
        statCard('跨年迁移', crossYearCount),
        statCard('总项目数', top.projectCount + bottom.projectCount),
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

    function clamp(value, min, max) {{
      return Math.min(max, Math.max(min, value));
    }}

    function nodeCardSize(item) {{
      const width = Number(item.cardWidth || 160);
      const height = Number(item.cardHeight || width);
      const radius = Math.max(width, height) / 2;
      return {{
        width,
        height,
        radius,
      }};
    }}

    function edgePoint(from, to, offset) {{
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const length = Math.sqrt(dx * dx + dy * dy) || 1;
      return {{
        x: from.x + (dx / length) * offset,
        y: from.y + (dy / length) * offset,
      }};
    }}

    function svgPointFromEvent(event) {{
      const rect = graphEl.getBoundingClientRect();
      return {{
        x: ((event.clientX - rect.left) / Math.max(rect.width, 1)) * GRAPH_WIDTH,
        y: ((event.clientY - rect.top) / Math.max(rect.height, 1)) * GRAPH_HEIGHT,
      }};
    }}

    function updateGraphScale() {{
      graphStageEl.style.width = `${{Math.round(GRAPH_WIDTH * zoomState.scale)}}px`;
      graphStageEl.style.height = `${{Math.round(GRAPH_HEIGHT * zoomState.scale)}}px`;
      graphEl.style.width = `${{GRAPH_WIDTH}}px`;
      graphEl.style.height = `${{GRAPH_HEIGHT}}px`;
      graphEl.style.transform = `scale(${{zoomState.scale}})`;
    }}

    function handleGraphWheel(event) {{
      event.preventDefault();
      const rect = canvasShellEl.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const pointerY = event.clientY - rect.top;
      const logicalX = (canvasShellEl.scrollLeft + pointerX) / zoomState.scale;
      const logicalY = (canvasShellEl.scrollTop + pointerY) / zoomState.scale;
      const zoomFactor = event.deltaY < 0 ? (1 + zoomState.step) : (1 / (1 + zoomState.step));
      const nextScale = clamp(
        zoomState.scale * zoomFactor,
        zoomState.min,
        zoomState.max,
      );
      if (nextScale === zoomState.scale) return;
      zoomState.scale = nextScale;
      updateGraphScale();
      requestAnimationFrame(() => {{
        canvasShellEl.scrollLeft = logicalX * zoomState.scale - pointerX;
        canvasShellEl.scrollTop = logicalY * zoomState.scale - pointerY;
      }});
    }}

    function renderYearLabels() {{
      const group = document.getElementById('year-labels');
      const labels = [
        {{ x: DATA.planes.top.labelPoint.x, y: DATA.planes.top.labelPoint.y, text: DATA.periods.top.label }},
        {{ x: DATA.planes.bottom.labelPoint.x, y: DATA.planes.bottom.labelPoint.y, text: DATA.periods.bottom.label }},
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

    function renderPlanes() {{
      const group = document.getElementById('planes');
      group.replaceChildren();
    }}

    function applyVisibility() {{
      const show2024 = document.getElementById('toggle-2024').checked;
      const show2023 = document.getElementById('toggle-2023').checked;
      const showLinks = document.getElementById('toggle-links').checked;

      document.getElementById('nodes-2024').style.display = show2024 ? '' : 'none';
      document.getElementById('nodes-2023').style.display = show2023 ? '' : 'none';
      document.getElementById('links').style.display = showLinks ? '' : 'none';

      domRefs.links.forEach((el, id) => {{
        const item = linkMap.get(id);
        if (!item) return;
        const visible = showLinks
          && ((item.layer === 'top' && show2024)
            || (item.layer === 'bottom' && show2023)
            || (item.layer === 'bridge' && show2024 && show2023));
        el.style.display = visible ? '' : 'none';
      }});
    }}

    function clearSelection() {{
      document.querySelectorAll('.dimmed').forEach((el) => el.classList.remove('dimmed'));
      document.querySelectorAll('.selected-node').forEach((el) => el.classList.remove('selected-node'));
      document.querySelectorAll('.selected-link').forEach((el) => el.classList.remove('selected-link'));
    }}

    function dimAll() {{
      [...domRefs.nodes.values(), ...domRefs.links.values()].forEach((el) => el.classList.add('dimmed'));
    }}

    function highlightCommunity(communityId) {{
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
    }}

    function showCommunityDetail(communityId) {{
      const item = communityMap.get(communityId);
      if (!item) return;
      selectionState.type = 'community';
      selectionState.id = communityId;
      highlightCommunity(communityId);
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

    function highlightLink(linkId) {{
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
    }}

    function showLinkDetail(linkId) {{
      const item = linkMap.get(linkId);
      if (!item) return;
      selectionState.type = 'link';
      selectionState.id = linkId;
      highlightLink(linkId);
      detailEl.innerHTML = `
        <div class="detail-title">${{item.kind === 'cross_year' ? '跨年迁移关系' : '同年簇关系'}}</div>
        <div class="detail-meta">
          <div><strong>来源主题簇：</strong>${{item.sourceName}}</div>
          <div><strong>目标主题簇：</strong>${{item.targetName}}</div>
          <div><strong>关系类型：</strong>${{item.relationLabel || '主题联系'}}</div>
          <div><strong>重合强度：</strong>${{item.value}}</div>
          <div><strong>相似度：</strong>${{item.jaccard}}</div>
        </div>
      `;
    }}

    function refreshSelection() {{
      if (selectionState.type === 'community' && selectionState.id) {{
        highlightCommunity(selectionState.id);
        return;
      }}
      if (selectionState.type === 'link' && selectionState.id) {{
        highlightLink(selectionState.id);
      }}
    }}

    function renderLinks() {{
      const group = document.getElementById('links');
      group.replaceChildren();
      domRefs.links.clear();
      DATA.links.forEach((item) => {{
        const source = communityMap.get(item.source);
        const target = communityMap.get(item.target);
        if (!source || !target) return;
        const linkGroup = createSvgEl('g', {{ class: 'relation-group' }});
        const sourceSize = nodeCardSize(source);
        const targetSize = nodeCardSize(target);
        const sourceOffset = sourceSize.radius + (item.kind === 'cross_year' ? 16 : 12);
        const targetOffset = targetSize.radius + (item.kind === 'cross_year' ? 16 : 12);
        const start = edgePoint(source, target, sourceOffset);
        const end = edgePoint(target, source, targetOffset);
        const midX = (start.x + end.x) / 2;
        const midY = (start.y + end.y) / 2;
        const curvature = item.kind === 'cross_year' ? 0 : (item.layer === 'top' ? -72 : 72);
        const controlX = midX + (item.kind === 'cross_year' ? 0 : 18);
        const controlY = midY + curvature;
        const path = createSvgEl('path', {{
          d: item.kind === 'cross_year'
            ? `M ${{start.x}} ${{start.y}} L ${{end.x}} ${{end.y}}`
            : `M ${{start.x}} ${{start.y}} Q ${{controlX}} ${{controlY}} ${{end.x}} ${{end.y}}`,
          class: item.kind === 'cross_year'
            ? 'relation-cross'
            : 'relation-same',
          'stroke-width': item.strokeWidth,
          'marker-end': item.kind === 'cross_year' ? 'url(#arrowhead)' : '',
        }});
        const label = `${{item.relationLabel || '关系'}} · ${{item.jaccard}}`;
        linkGroup.appendChild(path);
        if (item.kind === 'cross_year') {{
          const labelWidth = Math.max(128, label.length * 16);
          const labelBg = createSvgEl('rect', {{
            x: midX - labelWidth / 2,
            y: midY - 18,
            rx: 16,
            ry: 16,
            width: labelWidth,
            height: 34,
            class: 'relation-label-bg relation-label-bg-cross',
          }});
          const labelText = createSvgEl('text', {{
            x: midX,
            y: midY + 6,
            'text-anchor': 'middle',
            class: 'relation-label relation-label-cross',
          }}, label);
          linkGroup.appendChild(labelBg);
          linkGroup.appendChild(labelText);
        }}
        linkGroup.addEventListener('click', () => showLinkDetail(item.id));
        group.appendChild(linkGroup);
        domRefs.links.set(item.id, linkGroup);
      }});
      refreshSelection();
    }}

    function setNodeTransform(item) {{
      const node = domRefs.nodes.get(item.id);
      if (!node) return;
      node.setAttribute('transform', `translate(${{item.x}}, ${{item.y}})`);
    }}

    function clampNodePosition(item, nextX, nextY) {{
      const size = nodeCardSize(item);
      return {{
        x: clamp(nextX, size.radius + 28, GRAPH_WIDTH - size.radius - 28),
        y: clamp(nextY, size.radius + 28, GRAPH_HEIGHT - size.radius - 28),
      }};
    }}

    function beginNodeDrag(event, item, nodeEl) {{
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      dragState.communityId = item.id;
      dragState.moved = false;
      dragState.nodeEl = nodeEl;
      dragState.startClientX = event.clientX;
      dragState.startClientY = event.clientY;
      dragState.startX = Number(item.x);
      dragState.startY = Number(item.y);
      nodeEl.classList.add('dragging');
      nodeEl.parentNode.appendChild(nodeEl);
    }}

    function moveNodeDrag(event) {{
      if (!dragState.communityId) return;
      event.preventDefault();
      const item = communityMap.get(dragState.communityId);
      if (!item) return;
      const deltaX = (event.clientX - dragState.startClientX) / zoomState.scale;
      const deltaY = (event.clientY - dragState.startClientY) / zoomState.scale;
      const next = clampNodePosition(item, dragState.startX + deltaX, dragState.startY + deltaY);
      if (
        Math.abs(event.clientX - dragState.startClientX) > 3
        || Math.abs(event.clientY - dragState.startClientY) > 3
      ) {{
        dragState.moved = true;
      }}
      item.x = Number(next.x.toFixed(2));
      item.y = Number(next.y.toFixed(2));
      setNodeTransform(item);
      renderLinks();
    }}

    function endNodeDrag(event) {{
      if (!dragState.communityId) return;
      if (event) event.preventDefault();
      const item = communityMap.get(dragState.communityId);
      const nodeEl = dragState.nodeEl;
      if (nodeEl) {{
        nodeEl.classList.remove('dragging');
      }}
      const moved = dragState.moved;
      dragState.communityId = null;
      dragState.moved = false;
      dragState.nodeEl = null;
      dragState.startClientX = 0;
      dragState.startClientY = 0;
      dragState.startX = 0;
      dragState.startY = 0;
      if (!moved && item) {{
        showCommunityDetail(item.id);
      }}
    }}

    function closestNodeEl(target) {{
      let current = target;
      while (current && current !== graphEl) {{
        if (current.classList && current.classList.contains('kg-node')) {{
          return current;
        }}
        current = current.parentNode;
      }}
      return null;
    }}

    function handleGraphMouseDown(event) {{
      const nodeEl = closestNodeEl(event.target);
      if (!nodeEl) return;
      const communityId = nodeEl.getAttribute('data-community-id');
      const item = communityMap.get(communityId);
      if (!item) return;
      beginNodeDrag(event, item, nodeEl);
    }}

    function renderNodes() {{
      DATA.communities.forEach((item) => {{
        const groupId = item.period === DATA.periods.top.label ? 'nodes-2024' : 'nodes-2023';
        const group = document.getElementById(groupId);
        const isTopPeriod = item.period === DATA.periods.top.label;
        const size = nodeCardSize(item);
        const node = createSvgEl('g', {{
          class: 'kg-node',
          transform: `translate(${{item.x}}, ${{item.y}})`,
          draggable: 'false',
          'data-community-id': item.id,
        }});
        const circle = createSvgEl('circle', {{
          cx: 0,
          cy: 0,
          r: size.radius,
          class: isTopPeriod ? 'kg-node-circle kg-node-circle-2024' : 'kg-node-circle kg-node-circle-2023',
        }});
        const hitArea = createSvgEl('circle', {{
          cx: 0,
          cy: 0,
          r: size.radius + 10,
          class: 'kg-node-hit',
        }});
        node.appendChild(circle);
        node.appendChild(hitArea);
        group.appendChild(node);
        domRefs.nodes.set(item.id, node);
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
    canvasShellEl.addEventListener('wheel', handleGraphWheel, {{ passive: false }});
    graphEl.addEventListener('mousedown', handleGraphMouseDown, true);
    window.addEventListener('mousemove', moveNodeDrag);
    window.addEventListener('mouseup', endNodeDrag);

    renderStats();
    renderInsights();
    updateGraphScale();
    renderPlanes();
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
