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

CANVAS_WIDTH = 3200
CANVAS_HEIGHT = 1500
TIMELINE_START_X = 360.0
TIMELINE_END_X = 3250.0
TIMELINE_BASELINE_Y = 1600.0
TIMELINE_TOP_Y = 180.0
TIMELINE_BOTTOM_Y = 1330.0
TIMELINE_BAND_HEIGHT = 960.0
TIMELINE_MONTHS = [
    "2023-01", "2023-02", "2023-03", "2023-04", "2023-05", "2023-06",
    "2023-07", "2023-08", "2023-09", "2023-10", "2023-11", "2023-12",
    "2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06",
    "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
]
HEAT_COLORS = ["#6c96c7", "#88b9b0", "#d9b86a", "#c85f51"]
MAX_RENDER_LINKS = 1200
MAX_LINKS_PER_SOURCE = 2
MAX_LINKS_PER_TARGET = 2
MAX_SAME_YEAR_LINKS_PER_NODE = 4
MIN_SAME_YEAR_LINK_SCORE = 0.72
VISIBLE_COMMUNITIES_PER_PERIOD = 25
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
    scale = max(1.0, float(size)) ** 0.62
    diameter = min(220.0, max(68.0, 40.0 + scale * 7.4))
    return diameter, diameter


def _color_bucket(rank: int, total: int, palette: list[str] | None = None) -> str:
    colors = palette or HEAT_COLORS
    if total <= 1:
        return colors[2]
    bucket = min(len(colors) - 1, int((rank / total) * len(colors)))
    return colors[bucket]


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    text = str(color).strip().lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    red, green, blue = rgb
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(red))),
        max(0, min(255, round(green))),
        max(0, min(255, round(blue))),
    )


def _mix_color(left: str, right: str, t: float) -> str:
    lt = _hex_to_rgb(left)
    rt = _hex_to_rgb(right)
    ratio = _clamp(float(t), 0.0, 1.0)
    return _rgb_to_hex(
        (
            lt[0] + (rt[0] - lt[0]) * ratio,
            lt[1] + (rt[1] - lt[1]) * ratio,
            lt[2] + (rt[2] - lt[2]) * ratio,
        )
    )


def _continuous_palette_color(value: float, minimum: float, maximum: float, palette: list[str] | None = None) -> str:
    colors = palette or HEAT_COLORS
    if len(colors) == 1 or maximum <= minimum:
        return colors[-1]
    ratio = _clamp((float(value) - minimum) / (maximum - minimum), 0.0, 1.0)
    scaled = ratio * (len(colors) - 1)
    index = min(len(colors) - 2, int(math.floor(scaled)))
    local_t = scaled - index
    return _mix_color(colors[index], colors[index + 1], local_t)


def _node_heat_styles(communities: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    styles: dict[str, tuple[str, str]] = {}
    if not communities:
        return styles
    ordered = sorted(
        communities,
        key=lambda item: (int(item.get("size", 0) or 0), -int(item.get("rank", 0) or 0)),
    )
    total = max(1, len(ordered) - 1)
    for idx, item in enumerate(ordered):
        ratio = idx / total if total > 0 else 0.5
        fill = _continuous_palette_color(
            ratio,
            0.0,
            1.0,
            palette=["#76aeea", "#8fc8cf", "#e2cc70", "#ef9355", "#cc5a4c"],
        )
        stroke = _mix_color(fill, "#2b3442", 0.34)
        styles[str(item["id"])] = (fill, stroke)
    return styles


def _topic_name_tokens(text: str) -> set[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return set()
    tokens: set[str] = {raw}
    if len(raw) <= 4:
        tokens.add(raw)
    for idx in range(max(0, len(raw) - 1)):
        token = raw[idx: idx + 2].strip()
        if token:
            tokens.add(token)
    return tokens


def _timeline_month_slot(index: int) -> dict[str, Any]:
    slot_width = (TIMELINE_END_X - TIMELINE_START_X) / max(len(TIMELINE_MONTHS) - 1, 1)
    x = TIMELINE_START_X + index * slot_width
    return {
        "index": index,
        "label": TIMELINE_MONTHS[index],
        "x": round(x, 2),
    }


def build_time_axis() -> dict[str, Any]:
    months = [_timeline_month_slot(index) for index in range(len(TIMELINE_MONTHS))]
    year_sections = [
        {
            "label": "2023年",
            "startX": months[0]["x"],
            "endX": months[11]["x"],
            "centerX": round((months[0]["x"] + months[11]["x"]) / 2, 2),
        },
        {
            "label": "2024年",
            "startX": months[12]["x"],
            "endX": months[23]["x"],
            "centerX": round((months[12]["x"] + months[23]["x"]) / 2, 2),
        },
    ]
    return {
        "months": months,
        "yearSections": year_sections,
        "baselineY": TIMELINE_BASELINE_Y,
        "topY": TIMELINE_TOP_Y,
        "bottomY": TIMELINE_BOTTOM_Y,
    }


def place_communities_on_timeline(
    communities: list[dict[str, Any]],
    period_label: str,
    start_month_index: int,
    end_month_index: int,
    lane: str,
) -> list[dict[str, Any]]:
    if not communities:
        return []

    ordered = sorted(
        communities,
        key=lambda item: (-int(item["size"]), int(item["rank"]), str(item["name"])),
    )
    slot_count = max(1, end_month_index - start_month_index + 1)
    lane_seed = random.Random(_stable_seed(period_label, lane, len(ordered)))
    lane_base_y = TIMELINE_TOP_Y if lane == "top" else (TIMELINE_TOP_Y + TIMELINE_BAND_HEIGHT * 0.58)
    lane_span = TIMELINE_BAND_HEIGHT * (0.36 if lane == "top" else 0.30)

    placed: list[dict[str, Any]] = []
    for index, item in enumerate(ordered):
        diameter, _ = _node_card_dimensions(int(item["size"]))
        radius = diameter / 2
        month_offset = round(index * (slot_count - 1) / max(len(ordered) - 1, 1))
        month_index = start_month_index + month_offset
        slot = _timeline_month_slot(month_index)
        x_jitter = lane_seed.uniform(-18.0, 18.0)
        band_position = (index % 5) / 4 if len(ordered) > 1 else 0.5
        y = lane_base_y + band_position * lane_span + lane_seed.uniform(-16.0, 16.0)
        x = _clamp(slot["x"] + x_jitter, TIMELINE_START_X + radius, TIMELINE_END_X - radius)
        y = _clamp(y, TIMELINE_TOP_Y + radius, TIMELINE_BOTTOM_Y - radius - 120.0)
        placed.append(
            {
                **item,
                "layer": lane,
                "x": round(x, 2),
                "y": round(y, 2),
                "monthIndex": month_index,
                "monthLabel": slot["label"],
                "radius": round(radius, 2),
                "cardWidth": round(diameter, 2),
                "cardHeight": round(diameter, 2),
            }
        )

    return placed


def resolve_node_collisions(
    communities: list[dict[str, Any]],
    iterations: int = 80,
) -> list[dict[str, Any]]:
    if not communities:
        return communities

    items = [{**item} for item in communities]
    for _ in range(iterations):
        moved = False
        for idx, left in enumerate(items):
            for right in items[idx + 1:]:
                dx = float(right["x"]) - float(left["x"])
                dy = float(right["y"]) - float(left["y"])
                distance = math.sqrt(dx * dx + dy * dy) or 0.01
                min_gap = float(left["radius"]) + float(right["radius"]) + 10.0
                if distance >= min_gap:
                    continue
                overlap = (min_gap - distance) / 2.0
                nx = dx / distance
                ny = dy / distance
                if abs(dx) < 0.1 and abs(dy) < 0.1:
                    nx = 1.0 if int(left["communityId"]) % 2 == 0 else -1.0
                    ny = 0.35 if left["layer"] == "top" else -0.35
                for item, sign in ((left, -1.0), (right, 1.0)):
                    new_x = _clamp(
                        float(item["x"]) + nx * overlap * sign,
                        TIMELINE_START_X + float(item["radius"]),
                        TIMELINE_END_X - float(item["radius"]),
                    )
                    new_y = _clamp(
                        float(item["y"]) + ny * overlap * sign,
                        TIMELINE_TOP_Y + float(item["radius"]),
                        TIMELINE_BOTTOM_Y - float(item["radius"]) - 92.0,
                    )
                    item["x"] = round(new_x, 2)
                    item["y"] = round(new_y, 2)
                moved = True
        if not moved:
            break
    return items


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


def _same_year_link_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float]:
    overlap, jaccard = _community_similarity(left, right)
    left_tokens = _topic_name_tokens(str(left.get("name", "")))
    right_tokens = _topic_name_tokens(str(right.get("name", "")))
    name_overlap = len(left_tokens & right_tokens)
    rank_gap = abs(int(left.get("rank", 0) or 0) - int(right.get("rank", 0) or 0))
    left_size = int(left.get("size", 0) or 0)
    right_size = int(right.get("size", 0) or 0)
    max_size = max(left_size, right_size, 1)
    size_similarity = 1.0 - abs(left_size - right_size) / max_size
    if overlap <= 0 and name_overlap <= 0:
        score = 0.0
    else:
        score = (
            overlap * 1.55
            + jaccard * 2.35
            + min(name_overlap, 3) * 0.8
            + max(0.0, 1.0 - rank_gap / 10.0) * 0.45
            + max(0.0, size_similarity) * 0.35
        )
    return {
        "overlap": float(overlap),
        "jaccard": float(jaccard),
        "nameOverlap": float(name_overlap),
        "score": float(score),
    }


def build_same_year_links(
    communities: list[dict[str, Any]],
    layer: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for idx, left in enumerate(communities):
        for right in communities[idx + 1:]:
            metrics = _same_year_link_metrics(left, right)
            overlap = int(metrics["overlap"])
            jaccard = float(metrics["jaccard"])
            score = float(metrics["score"])
            if score < MIN_SAME_YEAR_LINK_SCORE:
                continue
            candidates.append(
                {
                    "id": f"{layer}-internal-{left['communityId']}-{right['communityId']}",
                    "kind": "same_year",
                    "layer": layer,
                    "source": str(left["id"]),
                    "target": str(right["id"]),
                    "sourceName": str(left["name"]),
                    "targetName": str(right["name"]),
                    "value": max(overlap, int(round(score))),
                    "jaccard": round(max(jaccard, min(score / 6.0, 0.95)), 4),
                    "score": round(score, 4),
                    "strokeWidth": round(0.95 + math.log1p(max(overlap, 1)) * 1.2 + min(score, 4.0) * 0.28, 2),
                    "relationLabel": "同年簇关联",
                }
            )
    candidates.sort(
        key=lambda item: (
            float(item.get("score", 0.0) or 0.0),
            float(item.get("jaccard", 0.0) or 0.0),
            int(item.get("value", 0) or 0),
        ),
        reverse=True,
    )
    links: list[dict[str, Any]] = []
    degree: dict[str, int] = {}
    for item in candidates:
        source = str(item["source"])
        target = str(item["target"])
        if degree.get(source, 0) >= MAX_SAME_YEAR_LINKS_PER_NODE:
            continue
        if degree.get(target, 0) >= MAX_SAME_YEAR_LINKS_PER_NODE:
            continue
        links.append(item)
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1
    return links


def select_larger_half(communities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not communities:
        return []
    ordered = sorted(
        communities,
        key=lambda item: (
            int(item.get("size", 0) or 0),
            -int(item.get("rank", 0) or 0),
        ),
        reverse=True,
    )
    keep_count = max(1, math.ceil(len(ordered) * 0.5))
    kept = ordered[:keep_count]
    kept_ids = {str(item["id"]) for item in kept}
    return [item for item in communities if str(item["id"]) in kept_ids]


def select_top_n_communities(communities: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not communities:
        return []
    ordered = sorted(
        communities,
        key=lambda item: (
            int(item.get("size", 0) or 0),
            -int(item.get("rank", 0) or 0),
        ),
        reverse=True,
    )
    kept = ordered[:max(1, int(limit))]
    kept_ids = {str(item["id"]) for item in kept}
    return [item for item in communities if str(item["id"]) in kept_ids]


def trim_smallest_communities(
    communities_2023: list[dict[str, Any]],
    communities_2024: list[dict[str, Any]],
    remove_count: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    combined = sorted(
        [*communities_2023, *communities_2024],
        key=lambda item: (
            int(item.get("size", 0) or 0),
            int(item.get("rank", 0) or 0),
        ),
    )
    drop_ids = {str(item["id"]) for item in combined[:max(0, remove_count)]}
    return (
        [item for item in communities_2023 if str(item["id"]) not in drop_ids],
        [item for item in communities_2024 if str(item["id"]) not in drop_ids],
    )


def apply_link_heat_colors(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not links:
        return links

    ordered = sorted(
        enumerate(links),
        key=lambda pair: (
            int(pair[1].get("value", 0) or 0),
            float(pair[1].get("jaccard", 0.0) or 0.0),
        ),
    )
    total = len(ordered)
    for rank, (_, item) in enumerate(ordered):
        color = _color_bucket(rank, total)
        item["strokeColor"] = color
        item["labelStrokeColor"] = color
    return links


def build_evidence_series(
    communities_2023: list[dict[str, Any]],
    communities_2024: list[dict[str, Any]],
    cross_year_links: list[dict[str, Any]],
    bucket_count: int = 12,
) -> dict[str, Any]:
    labels = [f"Q{index + 1:02d}" for index in range(bucket_count)]

    def bucket_values(items: list[dict[str, Any]]) -> list[int]:
        ordered = sorted(
            items,
            key=lambda item: (
                int(item.get("rank", 0) or 0),
                -int(item.get("size", 0) or 0),
            ),
        )
        values = [0] * bucket_count
        if not ordered:
            return values
        for index, item in enumerate(ordered):
            bucket_index = min(bucket_count - 1, int(index * bucket_count / len(ordered)))
            values[bucket_index] += int(item.get("size", 0) or 0)
        return values

    rank_to_bucket_2023: dict[str, int] = {}
    rank_to_bucket_2024: dict[str, int] = {}
    for index, item in enumerate(sorted(communities_2023, key=lambda row: int(row.get("rank", 0) or 0))):
        rank_to_bucket_2023[str(item["id"])] = min(bucket_count - 1, int(index * bucket_count / max(1, len(communities_2023))))
    for index, item in enumerate(sorted(communities_2024, key=lambda row: int(row.get("rank", 0) or 0))):
        rank_to_bucket_2024[str(item["id"])] = min(bucket_count - 1, int(index * bucket_count / max(1, len(communities_2024))))

    relation_strength = [0] * bucket_count
    for item in cross_year_links:
        source_bucket = rank_to_bucket_2023.get(str(item.get("source")))
        target_bucket = rank_to_bucket_2024.get(str(item.get("target")))
        if source_bucket is None or target_bucket is None:
            continue
        bucket_index = max(0, min(bucket_count - 1, round((source_bucket + target_bucket) / 2)))
        relation_strength[bucket_index] += int(item.get("value", 0) or 0)

    return {
        "labels": labels,
        "series": [
            {"key": "volume2023", "label": "2023主题簇规模", "color": "#4c9fe6", "values": bucket_values(communities_2023)},
            {"key": "volume2024", "label": "2024主题簇规模", "color": "#f0a63a", "values": bucket_values(communities_2024)},
            {"key": "migration", "label": "跨年关系强度", "color": "#4eaf6f", "values": relation_strength},
        ],
    }


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
    raw_count_2023 = len(communities_2023)
    raw_count_2024 = len(communities_2024)
    communities_2023 = select_top_n_communities(communities_2023, VISIBLE_COMMUNITIES_PER_PERIOD)
    communities_2024 = select_top_n_communities(communities_2024, VISIBLE_COMMUNITIES_PER_PERIOD)

    positioned_2023 = place_communities_on_timeline(
        communities_2023,
        label_2023,
        0,
        11,
        "bottom",
    )
    positioned_2024 = place_communities_on_timeline(
        communities_2024,
        label_2024,
        12,
        23,
        "top",
    )
    positioned_2023 = resolve_node_collisions(positioned_2023)
    positioned_2024 = resolve_node_collisions(positioned_2024)
    cross_year_links = build_links(sankey.get("links", []) or [], positioned_2023, positioned_2024)
    same_year_links = [
        *build_same_year_links(positioned_2024, "top"),
        *build_same_year_links(positioned_2023, "bottom"),
    ]
    all_communities = [*positioned_2024, *positioned_2023]
    links = apply_link_heat_colors([*same_year_links, *cross_year_links])
    evidence_series = build_evidence_series(positioned_2023, positioned_2024, cross_year_links)
    node_styles = _node_heat_styles(all_communities)
    for item in all_communities:
        fill, stroke = node_styles.get(str(item["id"]), ("#88b9b0", "#5f8f87"))
        item["nodeColor"] = fill
        item["nodeStroke"] = stroke
    same_year_count = len([item for item in links if str(item.get("kind")) == "same_year"])
    cross_year_count = len([item for item in links if str(item.get("kind")) == "cross_year"])

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
                "communityCount": raw_count_2024,
                "visibleCommunityCount": len(positioned_2024),
                "projectCount": sum(int(item["size"]) for item in positioned_2024),
            },
            "bottom": {
                "label": label_2023,
                "communityCount": raw_count_2023,
                "visibleCommunityCount": len(positioned_2023),
                "projectCount": sum(int(item["size"]) for item in positioned_2023),
            },
        },
        "canvas": {
            "width": CANVAS_WIDTH,
            "height": CANVAS_HEIGHT,
        },
        "layoutMode": "reference_cluster",
        "evidenceSeries": evidence_series,
        "timeline": build_time_axis(),
        "communities": all_communities,
        "links": links,
        "insightDraft": [
            "图谱按主题簇关系进行中心辐射式排布，突出核心主题与外围关联主题。",
            "圆形越大说明该簇包含的项目越多，节点颜色按规模从蓝绿过渡到橙红。",
            f"当前共展示 {same_year_count} 条同年关系与 {cross_year_count} 条跨年迁移关系。",
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
        default_topic = ""
        communities = payload.get("communities", []) or []
        if communities:
            default_topic = str(communities[0].get("name") or "").strip()
        template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>主题簇节点图</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; overflow: hidden; }}
    body {{ margin: 0; font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: linear-gradient(180deg, #dfeaf7 0%, #edf3fa 12%, #f4f7fb 100%); color: #111827; }}
    .shell {{ height: 100vh; display: grid; grid-template-rows: 52px 1fr; overflow: hidden; }}
    .topbar {{ display: flex; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid #d5dfeb; background: linear-gradient(180deg, #edf4fb 0%, #dfeaf7 100%); box-shadow: inset 0 -1px 0 rgba(255,255,255,0.7); }}
    .brand {{ display: flex; align-items: center; gap: 12px; font-size: 18px; font-weight: 900; }}
    .brand-badge {{ width: 28px; height: 28px; border-radius: 8px; background: linear-gradient(135deg, #5aa0ff, #2f69d9); display: inline-flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; }}
    .topbar-meta {{ display: flex; align-items: center; gap: 14px; color: #475569; font-size: 13px; }}
    .page {{ width: min(100%, 1980px); height: calc(100vh - 52px); margin: 0 auto; padding: 8px 10px; display: grid; grid-template-columns: 286px minmax(0, 1fr) 316px; gap: 8px; align-items: stretch; overflow: hidden; }}
    .left-rail, .right-rail, .center-stage {{ min-width: 0; }}
    .left-rail, .right-rail {{ display: grid; gap: 8px; align-content: start; min-height: 0; overflow: hidden; }}
    .right-rail {{ grid-template-rows: minmax(0, 0.9fr) minmax(0, 0.95fr) minmax(0, 1.15fr); }}
    .panel {{ border: 2px solid #d8a764; border-radius: 14px; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,250,252,0.98)); box-shadow: 0 10px 24px rgba(15,23,42,0.06); overflow: hidden; }}
    .panel-head {{ padding: 8px 12px; font-size: 12px; font-weight: 900; border-bottom: 1px solid #e4e9f0; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(245,248,252,0.95)); }}
    .panel-body {{ padding: 10px 12px; }}
    .hero {{ border: 2px solid #d8a764; border-radius: 14px; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,253,0.98)); box-shadow: 0 10px 24px rgba(15,23,42,0.06); overflow: hidden; }}
    .hero-title-wrap {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px 4px; border-bottom: 1px solid #e3e9f1; }}
    .hero-main-title {{ font-size: 18px; font-weight: 900; }}
    .stats {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }}
    .stat {{ padding: 10px 12px; border-radius: 10px; background: #fff; border: 1px solid #dce4ef; display: grid; justify-items: center; gap: 6px; min-height: 76px; }}
    .stat-label {{ font-size: 11px; color: #64748b; letter-spacing: 1px; line-height: 1.2; text-align: center; }}
    .stat-value {{ font-size: 20px; font-weight: 900; line-height: 1; }}
    .controls {{ display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }}
    .toggle {{ display: flex; gap: 8px; align-items: center; padding: 6px 10px; border-radius: 999px; background: #fff; border: 1px solid #dce4ef; font-size: 11px; }}
    .graph-wrap {{ min-width: 0; overflow: hidden; padding: 6px 10px 6px; background: transparent; }}
    .summary-title {{ font-size: 13px; font-weight: 800; margin: 10px 0 6px; }}
    .summary-empty {{ color: #94a3b8; font-size: 13px; }}
    .summary-list {{ display: grid; gap: 8px; }}
    .summary-item {{ padding: 10px 12px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; font-size: 11px; line-height: 1.6; }}
    .group-columns {{ display: grid; gap: 10px; }}
    .group-column {{ padding: 10px; border-radius: 12px; background: #f8fafc; border: 1px solid #e2e8f0; }}
    .group-column-title {{ font-size: 12px; font-weight: 800; margin-bottom: 8px; }}
    .group-items {{ display: grid; gap: 6px; max-height: 150px; overflow: auto; }}
    .group-item {{ padding: 8px 10px; border-radius: 10px; background: #fff; border: 1px solid #e2e8f0; }}
    .group-item-name {{ font-size: 12px; font-weight: 800; line-height: 1.45; }}
    .group-item-meta {{ margin-top: 3px; color: #64748b; font-size: 11px; }}
    .group-item-desc {{ margin-top: 4px; color: #334155; font-size: 11px; line-height: 1.55; }}
    .group-keywords {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }}
    .keyword-chip {{ padding: 3px 7px; border-radius: 999px; background: #e9f2ff; color: #1d4ed8; font-size: 10px; }}
    .graph-toolbar {{ display: flex; justify-content: flex-start; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }}
    .legend {{ display: flex; gap: 14px; flex-wrap: wrap; color: #475569; font-size: 12px; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
    .swatch {{ width: 18px; height: 18px; border-radius: 999px; display: inline-block; }}
    .swatch-sphere-2024 {{ background: #3b82f6; border: 2px solid #1e3a8a; }}
    .swatch-sphere-2023 {{ background: #64748b; border: 2px solid #1f2937; }}
    .canvas-shell {{ width: 100%; max-width: 100%; height: min(68vh, 800px); overflow: hidden; border-radius: 0; border: 0; background: radial-gradient(circle at 50% 42%, rgba(255,255,255,0.96), rgba(236,243,249,0.82)); overscroll-behavior: contain; }}
    .graph-stage {{ position: relative; width: __WIDTH__px; height: __HEIGHT__px; transform-origin: top left; }}
    svg {{ width: __WIDTH__px; height: __HEIGHT__px; display: block; transform-origin: top left; background: transparent; user-select: none; -webkit-user-select: none; }}
    .panel-title {{ font-size: 15px; font-weight: 800; margin-bottom: 10px; }}
    .hint {{ font-size: 12px; color: #64748b; line-height: 1.8; }}
    .detail-title {{ font-size: 17px; font-weight: 800; line-height: 1.6; }}
    .detail-meta {{ margin-top: 10px; display: grid; gap: 8px; font-size: 13px; color: #334155; }}
    .project-list {{ margin-top: 10px; max-height: 180px; overflow: auto; display: grid; gap: 8px; }}
    .project-item {{ padding: 8px 10px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; font-size: 13px; line-height: 1.6; }}
    .search {{ width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid #dbe5f1; outline: none; }}
    .list {{ display: grid; gap: 8px; max-height: 170px; overflow: auto; margin-top: 10px; }}
    .list-item {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 12px; cursor: pointer; background: #fff; }}
    .list-item:hover {{ border-color: #93c5fd; background: #eff6ff; }}
    .list-item-title {{ font-size: 13px; font-weight: 700; line-height: 1.6; }}
    .list-item-meta {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
    .kg-node {{ cursor: grab; touch-action: none; }}
    .kg-node.dragging {{ cursor: grabbing; }}
    .kg-node-hit {{ fill: transparent; pointer-events: all; cursor: grab; }}
    .kg-node.dragging .kg-node-hit {{ cursor: grabbing; }}
    .kg-node-circle {{ stroke-width: 3; pointer-events: none; }}
    .kg-node-label {{ font-size: 18px; font-weight: 700; fill: #334155; pointer-events: none; }}
    .kg-node-label-shadow {{ fill: rgba(255,255,255,0.92); stroke: rgba(203,213,225,0.7); stroke-width: 1; }}
    .relation-cross {{ fill: none; cursor: pointer; }}
    .relation-same {{ fill: none; cursor: pointer; opacity: 0.88; }}
    .relation-label-bg {{ fill: rgba(255,255,255,0.92); stroke-width: 1; }}
    .relation-label-bg-cross {{ }}
    .relation-label-bg-top {{ }}
    .relation-label-bg-bottom {{ }}
    .relation-label {{ font-size: 16px; font-weight: 800; pointer-events: none; }}
    .relation-label-cross {{ fill: #92400e; }}
    .relation-label-top {{ fill: #1d4ed8; }}
    .relation-label-bottom {{ fill: #334155; }}
    .label-pill {{ fill: rgba(255,255,255,0.82); stroke: rgba(148,163,184,0.22); stroke-width: 1; }}
    .label-text {{ font-size: 30px; font-weight: 800; fill: #0f172a; }}
    .cluster-title {{ font-size: 34px; font-weight: 900; fill: rgba(51,65,85,0.2); letter-spacing: 4px; }}
    .timeline-axis {{ stroke: #94a3b8; stroke-width: 2; }}
    .timeline-tick {{ stroke: #cbd5e1; stroke-width: 1.5; }}
    .timeline-month {{ font-size: 16px; fill: #475569; font-weight: 700; }}
    .timeline-year-pill {{ fill: rgba(255,255,255,0.92); stroke: rgba(148,163,184,0.42); stroke-width: 1.5; }}
    .timeline-year-text {{ font-size: 24px; fill: #0f172a; font-weight: 900; }}
    .timeline-band {{ fill: rgba(255,255,255,0.42); stroke: rgba(148,163,184,0.16); stroke-width: 1.5; }}
    .dimmed {{ opacity: 0.42; }}
    .selected-node {{ opacity: 1 !important; }}
    .selected-node .kg-node-circle {{ stroke: #ef4444 !important; stroke-width: 5 !important; }}
    .selected-link {{ opacity: 1 !important; }}
    .selected-link path,
    .selected-link line {{ stroke: #ef4444 !important; stroke-width: 3.5 !important; }}
    .selected-link .relation-label-bg {{ stroke: rgba(239,68,68,0.42) !important; }}
    .selected-link .relation-label {{ fill: #b91c1c !important; }}
    .left-mini-grid {{ display: grid; gap: 10px; }}
    .evidence-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .evidence-table th, .evidence-table td {{ padding: 6px 4px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }}
    .evidence-table th {{ color: #475569; font-weight: 800; }}
    .evidence-badge {{ display: inline-flex; min-width: 48px; justify-content: center; padding: 3px 8px; border-radius: 8px; font-size: 11px; font-weight: 800; line-height: 1.2; }}
    .evidence-badge-low {{ background: #e4f1ea; color: #44715f; }}
    .evidence-badge-mid {{ background: #e2eef5; color: #456b86; }}
    .evidence-badge-high {{ background: #efe6f6; color: #6d5b8c; }}
    .evidence-badge-top {{ background: #f2e8de; color: #8a6a52; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 8px; }}
    .metric-chip {{ padding: 8px 10px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; font-size: 12px; }}
    .right-title {{ font-size: 16px; font-weight: 900; text-align: center; line-height: 1.5; }}
    .right-actions {{ display: block; }}
    .action-card {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px 10px; background: #fff; font-size: 10px; line-height: 1.55; }}
    .insight-section {{ margin-top: 6px; }}
    .insight-index {{ display: inline-flex; width: 18px; height: 18px; align-items: center; justify-content: center; border-radius: 999px; margin-right: 8px; background: #e8eef7; color: #1e3a5f; font-size: 11px; font-weight: 900; }}
    .pager {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 8px; }}
    .pager-btn {{ min-width: 56px; height: 28px; border: 1px solid #cfd9e6; border-radius: 999px; background: #fff; color: #334155; font-size: 11px; cursor: pointer; }}
    .pager-btn:disabled {{ opacity: 0.42; cursor: default; }}
    .pager-indicator {{ font-size: 11px; color: #64748b; }}
    .center-stage {{ display: grid; gap: 8px; min-height: 0; overflow: hidden; grid-template-rows: minmax(0, 1fr) minmax(0, 240px); }}
    .bottom-strip {{ display: grid; grid-template-columns: 1fr; gap: 8px; min-height: 0; }}
    .trend-card {{ border: 2px solid #d8a764; border-radius: 14px; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,253,0.98)); overflow: hidden; box-shadow: 0 10px 24px rgba(15,23,42,0.06); }}
    .trend-body {{ padding: 8px 10px; max-height: 100%; overflow: auto; }}
    .chart-legend {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; font-size: 11px; color: #475569; }}
    .fake-line-label {{ display: inline-flex; align-items: center; gap: 6px; }}
    .fake-line-swatch {{ width: 18px; height: 4px; border-radius: 999px; display: inline-block; }}
    .blue {{ background: #3b82f6; }}
    .gold {{ background: #f59e0b; }}
    .green {{ background: #22c55e; }}
    .evidence-chart-shell {{ border: 1px solid #dbe5f1; border-radius: 12px; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(246,249,252,0.96)); overflow: hidden; }}
    .evidence-chart-svg {{ width: 100%; height: 156px; display: block; }}
    .timeline-note {{ display: none; }}
    #left-evidence {{ max-height: 270px; overflow: auto; }}
    #trend-insights {{ max-height: 220px; overflow: auto; }}
    #insights {{ max-height: 220px; overflow: auto; }}
    #detail {{ max-height: 100%; overflow: auto; }}
    .detail-panel-body {{ height: 100%; overflow: auto; }}
    @media (max-width: 1680px) {{
      .page {{ grid-template-columns: 280px minmax(0, 1fr) 300px; }}
    }}
    @media (max-width: 1480px) {{
      .page {{ grid-template-columns: 1fr; }}
      .hero-title-wrap {{ flex-direction: column; align-items: flex-start; }}
      .controls {{ justify-content: flex-start; }}
      .bottom-strip {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="brand-badge">▲</span>
        <span>全省科技治理政策研判系统</span>
      </div>
      <div class="topbar-meta">
        <span>主题迁移研判</span>
        <span>用户：soptum-info</span>
      </div>
    </header>
    <div class="page">
      <aside class="left-rail">
        <section class="panel">
          <div class="panel-head">事实层与关系层证据底座</div>
          <div class="panel-body">
            <div id="stats" class="stats"></div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">项目实体样本</div>
          <div class="panel-body" id="left-evidence"></div>
        </section>
        <section class="panel">
          <div class="panel-head">机构关系与主题簇检索</div>
          <div class="panel-body">
            <input id="community-search" class="search" placeholder="输入主题簇名称筛选" />
            <div id="community-list" class="list"></div>
          </div>
        </section>
      </aside>

      <main class="center-stage">
        <section class="hero">
          <div class="hero-title-wrap">
            <div class="hero-main-title">核心推演区：技术主题与机构网络演化图</div>
            <div class="controls">
              <label class="toggle"><input type="checkbox" id="toggle-2024" checked />显示 2024 年主题簇</label>
              <label class="toggle"><input type="checkbox" id="toggle-2023" checked />显示 2023 年主题簇</label>
              <label class="toggle"><input type="checkbox" id="toggle-links" checked />显示全部关系边</label>
            </div>
          </div>
          <section class="graph-wrap">
            <div class="graph-toolbar">
              <div class="legend">
                <div class="legend-item"><span class="swatch" style="background:linear-gradient(90deg,#c7dcf5,#7fa9d8,#355f9e);"></span>边权重热度</div>
              </div>
            </div>
            <div class="canvas-shell">
              <div id="graph-stage" class="graph-stage">
                <svg id="graph" viewBox="0 0 __WIDTH__ __HEIGHT__" xmlns="http://www.w3.org/2000/svg">
                  <defs>
                    <marker id="arrowhead" markerWidth="4.2" markerHeight="3.3" refX="3.6" refY="1.65" orient="auto" markerUnits="strokeWidth">
                      <path d="M 0 0 L 4.2 1.65 L 0 3.3 z" fill="context-stroke"></path>
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
        </section>

        <div class="bottom-strip">
          <section class="trend-card">
            <div class="panel-head">队列与统计层证据</div>
            <div class="trend-body">
              <div class="chart-legend">
                <span class="fake-line-label"><span class="fake-line-swatch blue"></span>2023主题簇规模</span>
                <span class="fake-line-label"><span class="fake-line-swatch gold"></span>2024主题簇规模</span>
                <span class="fake-line-label"><span class="fake-line-swatch green"></span>跨年关系强度</span>
              </div>
              <div class="evidence-chart-shell">
                <svg id="evidence-chart" class="evidence-chart-svg" viewBox="0 0 980 156" preserveAspectRatio="none"></svg>
              </div>
            </div>
          </section>
        </div>
      </main>

      <aside class="right-rail">
        <section class="panel">
          <div class="panel-head">关系详情</div>
          <div class="panel-body detail-panel-body">
            <div id="detail" class="hint">先点击一个主题实体或一条关系边。</div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">项目事实追溯</div>
          <div class="panel-body" id="trend-insights"></div>
        </section>
        <section class="panel">
          <div class="panel-head">热点迁移研判归纳</div>
          <div class="panel-body">
            <div id="insights" class="right-actions"></div>
          </div>
        </section>
      </aside>
    </div>
  </div>

  <script>
    const DATA = __DATA_JSON__;

    const graphEl = document.getElementById('graph');
    const graphStageEl = document.getElementById('graph-stage');
    const canvasShellEl = document.querySelector('.canvas-shell');
    const statsEl = document.getElementById('stats');
    const detailEl = document.getElementById('detail');
    const insightsEl = document.getElementById('insights');
    const leftEvidenceEl = document.getElementById('left-evidence');
    const trendInsightsEl = document.getElementById('trend-insights');
    const evidenceChartEl = document.getElementById('evidence-chart');
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
    const pagerState = {{
      keyChangePage: 0,
      pageSize: 1,
    }};

    function statCard(label, value) {{
      return `
        <div class="stat">
          <div class="stat-label">${{label}}</div>
          <div class="stat-value">${{value}}</div>
        </div>
      `;
    }}

    function projectCountBadge(value) {{
      const count = Number(value || 0);
      const sizes = (DATA.communities || []).map((item) => Number(item.size || 0));
      const min = Math.min(...sizes);
      const max = Math.max(...sizes);
      const ratio = max > min ? (count - min) / (max - min) : 0.5;
      const bg = ratio <= 0.5
        ? `rgb(${{Math.round(245 - ratio * 30)}}, ${{Math.round(235 + ratio * 20)}}, ${{Math.round(160 - ratio * 20)}})`
        : `rgb(${{Math.round(230 - (ratio - 0.5) * 120)}}, ${{Math.round(245 - (ratio - 0.5) * 10)}}, ${{Math.round(150 + (ratio - 0.5) * 60)}})`;
      const color = ratio > 0.62 ? '#1f5f38' : '#6b5b17';
      return `<span class="evidence-badge" style="background:${{bg}};color:${{color}};">${{count}}</span>`;
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
      const reportInsightHtml = `
        <div class="action-card">
          <div class="insight-section"><span class="insight-index">1</span>${{rows[0] || '暂无归纳内容'}}</div>
          <div class="insight-section"><span class="insight-index">2</span>${{rows[1] || (DATA.insightDraft || [])[0] || '暂无补充说明'}}</div>
          <div class="insight-section"><span class="insight-index">3</span>图上当前展示 ${{DATA.periods.bottom.visibleCommunityCount || DATA.periods.bottom.communityCount}} 个 2023 主题簇、${{DATA.periods.top.visibleCommunityCount || DATA.periods.top.communityCount}} 个 2024 主题簇。</div>
          <div class="insight-section"><span class="insight-index">4</span>跨年迁移边共 ${{DATA.links.filter((item) => item.kind === 'cross_year').length}} 条，重点关系支持点击追溯。</div>
        </div>
      `;
      const topGroupHtml = periods.length
        ? `
          <div class="group-columns">
            ${{periods.map((period) => `
              <div class="group-column">
                <div class="group-column-title">${{period}}</div>
                <div class="group-items">
                  ${{
                    (topGroups[period] || []).length
                      ? (topGroups[period] || []).slice(0, 4).map((item) => `
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
      const totalKeyPages = Math.max(1, Math.ceil(Math.max(keyChanges.length, 1) / pagerState.pageSize));
      pagerState.keyChangePage = Math.min(pagerState.keyChangePage, totalKeyPages - 1);
      const currentKeyItems = keyChanges.length
        ? keyChanges.slice(
            pagerState.keyChangePage * pagerState.pageSize,
            (pagerState.keyChangePage + 1) * pagerState.pageSize,
          )
        : [];
      const keyChangeHtml = currentKeyItems.length
        ? currentKeyItems.map((item) => `
            <div class="summary-item">
              <div><strong>${{item.rank || '-'}}.</strong> 从“${{item.from || '-'}}”到“${{item.to || '-'}}”</div>
              <div style="margin-top:6px;">${{item.description || ''}}</div>
            </div>
          `).join('')
        : '<div class="summary-empty">暂无重点趋势</div>';

      const allProjects = DATA.communities
        .slice()
        .sort((a, b) => Number(b.size || 0) - Number(a.size || 0))
        .slice(0, 4);
      leftEvidenceEl.innerHTML = `
        <table class="evidence-table">
          <thead>
            <tr><th>ID</th><th>主题簇</th><th>年度</th><th>项目量</th></tr>
          </thead>
          <tbody>
            ${{
              allProjects.map((item, index) => `
                <tr>
                  <td>${{index + 301}}</td>
                  <td>${{item.name}}</td>
                  <td>${{item.period}}</td>
                  <td>${{projectCountBadge(item.size)}}</td>
                </tr>
              `).join('')
            }}
          </tbody>
        </table>
      `;
      insightsEl.innerHTML = reportInsightHtml || '<div class="summary-empty">暂无归纳内容</div>';
      trendInsightsEl.innerHTML = `
        <div class="summary-title">重点领域方向</div>
        ${{topGroupHtml}}
        <div class="summary-title">热点迁移说明</div>
        <div class="summary-list">${{keyChangeHtml}}</div>
        <div class="pager">
          <button class="pager-btn" id="prev-keychange" ${{pagerState.keyChangePage <= 0 ? 'disabled' : ''}}>上一页</button>
          <div class="pager-indicator">${{totalKeyPages === 0 ? 0 : pagerState.keyChangePage + 1}} / ${{totalKeyPages}}</div>
          <button class="pager-btn" id="next-keychange" ${{pagerState.keyChangePage >= totalKeyPages - 1 ? 'disabled' : ''}}>下一页</button>
        </div>
      `;
      const prevBtn = document.getElementById('prev-keychange');
      const nextBtn = document.getElementById('next-keychange');
      if (prevBtn) prevBtn.onclick = () => {{ pagerState.keyChangePage = Math.max(0, pagerState.keyChangePage - 1); renderInsights(); }};
      if (nextBtn) nextBtn.onclick = () => {{ pagerState.keyChangePage = Math.min(totalKeyPages - 1, pagerState.keyChangePage + 1); renderInsights(); }};
    }}

    function createSvgEl(tag, attrs = {{}}, text = '') {{
      const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
      if (text) el.textContent = text;
      return el;
    }}

    function buildSmoothLinePath(points) {{
      if (!points.length) return '';
      if (points.length === 1) return `M ${{points[0][0]}} ${{points[0][1]}}`;
      let d = `M ${{points[0][0]}} ${{points[0][1]}}`;
      for (let index = 0; index < points.length - 1; index += 1) {{
        const prev = points[index - 1] || points[index];
        const curr = points[index];
        const next = points[index + 1];
        const nextNext = points[index + 2] || next;
        const cp1x = curr[0] + (next[0] - prev[0]) / 6;
        const cp1y = curr[1] + (next[1] - prev[1]) / 6;
        const cp2x = next[0] - (nextNext[0] - curr[0]) / 6;
        const cp2y = next[1] - (nextNext[1] - curr[1]) / 6;
        d += ` C ${{cp1x}} ${{cp1y}}, ${{cp2x}} ${{cp2y}}, ${{next[0]}} ${{next[1]}}`;
      }}
      return d;
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

    function fitGraphToViewport() {{
      const availableWidth = Math.max(240, canvasShellEl.clientWidth - 8);
      const availableHeight = Math.max(220, canvasShellEl.clientHeight - 8);
      const fitScale = Math.min(
        availableWidth / GRAPH_WIDTH,
        availableHeight / GRAPH_HEIGHT,
        1,
      );
      zoomState.scale = clamp(fitScale, zoomState.min, 1);
      updateGraphScale();
      const scaledWidth = GRAPH_WIDTH * zoomState.scale;
      canvasShellEl.scrollLeft = Math.max(0, (scaledWidth - canvasShellEl.clientWidth) / 2);
      canvasShellEl.scrollTop = 0;
    }}

    function polarPoint(cx, cy, radius, angle) {{
      return {{
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
      }};
    }}

    function applyReferenceLayout() {{
      const groups = [
        {{
          period: DATA.periods.bottom.label,
          centerX: GRAPH_WIDTH * 0.34,
          centerY: GRAPH_HEIGHT * 0.52,
          rotation: Math.PI * 0.94,
        }},
        {{
          period: DATA.periods.top.label,
          centerX: GRAPH_WIDTH * 0.68,
          centerY: GRAPH_HEIGHT * 0.48,
          rotation: Math.PI * 0.08,
        }},
      ];
      groups.forEach((group) => {{
        const items = DATA.communities
          .filter((item) => item.period === group.period)
          .sort((a, b) => Number(a.rank || 0) - Number(b.rank || 0));
        if (!items.length) return;
        items.forEach((item, index) => {{
          const size = nodeCardSize(item);
          item.cardWidth = size.width;
          item.cardHeight = size.height;
          item.radius = Number(size.radius.toFixed(2));
          item.layoutGroup = group.period;
          if (index === 0) {{
            item.x = Number(group.centerX.toFixed(2));
            item.y = Number(group.centerY.toFixed(2));
            return;
          }}
          const offsetIndex = index - 1;
          let ring = 0;
          let ringIndex = offsetIndex;
          let ringCount = 6;
          if (offsetIndex >= 6 && offsetIndex < 14) {{
            ring = 1;
            ringIndex = offsetIndex - 6;
            ringCount = 8;
          }} else if (offsetIndex >= 14) {{
            ring = 2;
            ringIndex = offsetIndex - 14;
            ringCount = Math.max(1, items.length - 14);
          }}
          const baseRadius = [175, 315, 455][ring] + size.radius * 0.08;
          const angleStep = (Math.PI * 2) / ringCount;
          const angle = group.rotation + ringIndex * angleStep + (ring % 2 ? angleStep * 0.18 : 0);
          const point = polarPoint(group.centerX, group.centerY, baseRadius, angle);
          item.x = Number(clamp(point.x, size.radius + 40, GRAPH_WIDTH - size.radius - 40).toFixed(2));
          item.y = Number(clamp(point.y, size.radius + 60, GRAPH_HEIGHT - size.radius - 60).toFixed(2));
        }});
      }});
      normalizeGraphFootprint();
      renderReferenceCollisions();
      normalizeGraphFootprint();
    }}

    function normalizeGraphFootprint() {{
      const items = DATA.communities || [];
      if (!items.length) return;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      items.forEach((item) => {{
        const radius = Number(item.radius || nodeCardSize(item).radius || 0);
        minX = Math.min(minX, Number(item.x) - radius);
        maxX = Math.max(maxX, Number(item.x) + radius);
        minY = Math.min(minY, Number(item.y) - radius);
        maxY = Math.max(maxY, Number(item.y) + radius);
      }});
      const target = {{
        left: GRAPH_WIDTH * 0.06,
        right: GRAPH_WIDTH * 0.94,
        top: GRAPH_HEIGHT * 0.12,
        bottom: GRAPH_HEIGHT * 0.9,
      }};
      const sourceWidth = Math.max(1, maxX - minX);
      const sourceHeight = Math.max(1, maxY - minY);
      const targetWidth = target.right - target.left;
      const targetHeight = target.bottom - target.top;
      const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
      items.forEach((item) => {{
        item.x = Number((target.left + (Number(item.x) - minX) * scale).toFixed(2));
        item.y = Number((target.top + (Number(item.y) - minY) * scale).toFixed(2));
        item.radius = Number((Number(item.radius || 0) * scale).toFixed(2));
        item.cardWidth = Number((Number(item.cardWidth || 0) * scale).toFixed(2));
        item.cardHeight = Number((Number(item.cardHeight || 0) * scale).toFixed(2));
      }});
    }}

    function renderReferenceCollisions() {{
      for (let iteration = 0; iteration < 90; iteration += 1) {{
        let moved = false;
        const items = DATA.communities.slice();
        for (let i = 0; i < items.length; i += 1) {{
          for (let j = i + 1; j < items.length; j += 1) {{
            const left = items[i];
            const right = items[j];
            if (left.period !== right.period) continue;
            const dx = Number(right.x) - Number(left.x);
            const dy = Number(right.y) - Number(left.y);
            const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
            const minGap = Number(left.radius || 0) + Number(right.radius || 0) + 26;
            if (dist >= minGap) continue;
            const push = (minGap - dist) / 2;
            const nx = dx / dist;
            const ny = dy / dist;
            left.x = Number((left.x - nx * push).toFixed(2));
            left.y = Number((left.y - ny * push).toFixed(2));
            right.x = Number((right.x + nx * push).toFixed(2));
            right.y = Number((right.y + ny * push).toFixed(2));
            moved = true;
          }}
        }}
        if (!moved) break;
      }}
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

    function renderPlanes() {{
      const group = document.getElementById('year-labels');
      group.replaceChildren();
      [
        {{ label: DATA.periods.bottom.label, x: GRAPH_WIDTH * 0.34, y: GRAPH_HEIGHT * 0.11 }},
        {{ label: DATA.periods.top.label, x: GRAPH_WIDTH * 0.68, y: GRAPH_HEIGHT * 0.11 }},
      ].forEach((item) => {{
        group.appendChild(createSvgEl('text', {{
          x: item.x,
          y: item.y,
          'text-anchor': 'middle',
          class: 'cluster-title',
        }}, item.label));
      }});
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
          <div><strong>位置分组：</strong>${{item.layoutGroup || item.period}}</div>
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

    function renderEvidenceChart() {{
      if (!evidenceChartEl) return;
      evidenceChartEl.replaceChildren();
      const chart = DATA.evidenceSeries || {{}};
      const labels = chart.labels || [];
      const series = chart.series || [];
      const width = 980;
      const height = 156;
      const padding = {{ left: 44, right: 18, top: 16, bottom: 28 }};
      const innerWidth = width - padding.left - padding.right;
      const innerHeight = height - padding.top - padding.bottom;
      const maxValue = Math.max(
        1,
        ...series.flatMap((item) => item.values || []).map((value) => Number(value || 0)),
      );
      for (let row = 0; row <= 4; row += 1) {{
        const y = padding.top + (innerHeight / 4) * row;
        evidenceChartEl.appendChild(createSvgEl('line', {{
          x1: padding.left,
          y1: y,
          x2: width - padding.right,
          y2: y,
          stroke: row === 4 ? '#94a3b8' : 'rgba(148,163,184,0.18)',
          'stroke-width': row === 4 ? 1.4 : 1,
        }}));
      }}
      labels.forEach((label, index) => {{
        const x = padding.left + (innerWidth * index) / Math.max(1, labels.length - 1);
        evidenceChartEl.appendChild(createSvgEl('text', {{
          x,
          y: height - 8,
          'text-anchor': 'middle',
          fill: '#64748b',
          'font-size': 10,
          'font-weight': 700,
        }}, label));
      }});
      series.forEach((item) => {{
        const values = item.values || [];
        const points = values.map((value, index) => {{
          const x = padding.left + (innerWidth * index) / Math.max(1, values.length - 1);
          const y = padding.top + innerHeight - (Number(value || 0) / maxValue) * innerHeight;
          return [x, y];
        }});
        const areaPoints = [
          [points[0][0], padding.top + innerHeight],
          ...points,
          [points[points.length - 1][0], padding.top + innerHeight],
        ];
        evidenceChartEl.appendChild(createSvgEl('path', {{
          d: `${{buildSmoothLinePath(areaPoints)}} Z`,
          fill: `${{item.color || '#3b82f6'}}22`,
          stroke: 'none',
        }}));
        evidenceChartEl.appendChild(createSvgEl('path', {{
          d: buildSmoothLinePath(points),
          fill: 'none',
          stroke: item.color || '#3b82f6',
          'stroke-width': 2.6,
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
        }}));
        points.forEach((point) => {{
          evidenceChartEl.appendChild(createSvgEl('circle', {{
            cx: point[0],
            cy: point[1],
            r: 2.8,
            fill: item.color || '#3b82f6',
            stroke: '#ffffff',
            'stroke-width': 1.4,
          }}));
        }});
      }});
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
        const sourceOffset = sourceSize.radius + (item.kind === 'cross_year' ? 8 : 10);
        const targetOffset = targetSize.radius + (item.kind === 'cross_year' ? 10 : 10);
        const start = edgePoint(source, target, sourceOffset);
        const end = edgePoint(target, source, targetOffset);
        const midX = (start.x + end.x) / 2;
        const midY = (start.y + end.y) / 2;
        const path = createSvgEl('path', {{
          d: `M ${{start.x}} ${{start.y}} L ${{end.x}} ${{end.y}}`,
          class: item.kind === 'cross_year'
            ? 'relation-cross'
            : 'relation-same',
          'stroke-width': item.strokeWidth,
          stroke: item.strokeColor || '#22c55e',
          'marker-end': item.kind === 'cross_year' ? 'url(#arrowhead)' : '',
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
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
            stroke: item.labelStrokeColor || item.strokeColor || '#22c55e',
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
          class: 'kg-node-circle',
          fill: item.nodeColor || '#22c55e',
          stroke: item.nodeStroke || '#15803d',
        }});
        const hitArea = createSvgEl('circle', {{
          cx: 0,
          cy: 0,
          r: size.radius + 10,
          class: 'kg-node-hit',
        }});
        node.appendChild(circle);
        node.appendChild(hitArea);
        if (Number(item.rank || 0) <= 6) {{
          const labelX = item.period === DATA.periods.top.label ? size.radius + 18 : -(size.radius + 18);
          const labelWidth = Math.max(76, String(item.name || '').length * 18);
          node.appendChild(createSvgEl('rect', {{
            x: item.period === DATA.periods.top.label ? labelX - 8 : labelX - labelWidth + 8,
            y: -18,
            width: labelWidth,
            height: 28,
            rx: 14,
            ry: 14,
            class: 'kg-node-label-shadow',
          }}));
          node.appendChild(createSvgEl('text', {{
            x: labelX,
            y: 1,
            'text-anchor': item.period === DATA.periods.top.label ? 'start' : 'end',
            class: 'kg-node-label',
          }}, item.name || ''));
        }}
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
        }})
        .slice(0, text ? 12 : 4);

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
    window.addEventListener('resize', fitGraphToViewport);

    applyReferenceLayout();
    renderStats();
    renderInsights();
    renderEvidenceChart();
    fitGraphToViewport();
    renderPlanes();
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
            .replace("__DEFAULT_TOPIC__", default_topic or "Auto Topic")
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
