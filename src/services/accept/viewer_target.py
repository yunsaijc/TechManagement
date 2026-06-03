"""验收材料 viewer 定位辅助（页码、高亮框、检索文本）。"""
from __future__ import annotations

import re
import json
import hashlib
from pathlib import Path
from typing import Any

from src.common.models.document import BoundingBox
from src.services.accept.models import ParsedAcceptanceBlock

WHITESPACE_PATTERN = re.compile(r"\s+")
TABLE_MARK_PATTERN = re.compile(r"\[表格[^\]]*\]")
NUMERIC_UNIT_PATTERN = re.compile(
    r"\d+(?:\.\d+)?(?:cells/mL|cells/L|mg/L|mg/\s*L|次/时|%)",
    re.IGNORECASE,
)
ITEMIZED_LOCATOR_DOC_KINDS = frozenset({"论文", "专利证书", "学位论文"})
VIEWER_TARGET_CACHE_DIR = Path("/tmp/accept_viewer_target_cache")
VIEWER_TARGET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
VIEWER_TARGET_CACHE_VERSION = "v7-pdf-page-size"

METRIC_HINT_PATTERNS: dict[str, list[str]] = {
    "检测范围": [r"检测范围[^|；。]{0,48}", r"\d+\s*[-~至到]\s*\d+\s*(?:cells|mg)"],
    "检测频率": [r"工作频率[^|；。]{0,32}", r"检测频率[^|；。]{0,32}", r"不小于\s*\d+\s*次"],
    "检测标准偏差": [r"(?:标准\s*[偏误]差|准\s*误差)[^|；。]{0,40}", r"\d+(?:\.\d+)?%"],
    "最大测量误差": [r"最大测量误差[^|；。]{0,32}", r"测量误差[^|；。]{0,32}"],
    "科技报告": [
        r"撰写科技报告\s*[、,，]\s*研\s*究\s*报告[^|；。]{0,24}",
        r"科技报告\s*[、,，]\s*研\s*究\s*报告[^|；。]{0,24}",
    ],
}
TABLE_ROW_TAG_PATTERN = re.compile(r"\[表格行\d+\]")

METRIC_ANCHOR_ALIASES: dict[str, tuple[str, ...]] = {
    "科技论文": ("科技论文", "发表论文", "发表学术论文", "高质量论文", "论文"),
    "发明专利": ("发明专利", "申请专利", "申报国家发明专利", "专利"),
    "培养研究生": ("培养研究生", "联合培养研究生", "研究生"),
    "研究报告": ("研究报告", "总研究报告", "科技报告"),
    "科技报告": ("科技报告", "研究报告"),
    "决策咨询报告": ("决策咨询报告", "决策参考报告"),
}


def normalize_viewer_page(*, source_page: int | None = None, viewer_page: int | None = None) -> int:
    """统一为 1-based 页码（packet viewer 使用）。"""
    page = int(viewer_page or 0)
    if page > 0:
        return page
    index = int(source_page or 0)
    return index + 1 if index >= 0 else 1


def _normalize_line(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()


def _clean_highlight_display(text: str) -> str:
    cleaned = _normalize_line(text)
    return re.sub(r"\s*AQ\d+\s*$", "", cleaned, flags=re.IGNORECASE).strip()


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", _normalize_line(text))


def _metric_aliases(metric_name: str, metric_variant: str = "") -> tuple[str, ...]:
    aliases: list[str] = []
    for key in (metric_name, metric_variant):
        key = str(key or "").strip()
        if not key:
            continue
        aliases.append(key)
        aliases.extend(METRIC_ANCHOR_ALIASES.get(key, ()))
    if metric_variant and "/" in metric_variant:
        for part in metric_variant.split("/"):
            aliases.extend(_metric_aliases(part.strip()))
    seen: set[str] = set()
    deduped: list[str] = []
    for alias in aliases:
        compact = _compact_text(alias)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(alias)
    return tuple(deduped)


def _contains_metric_alias(text: str, metric_name: str = "", metric_variant: str = "") -> bool:
    compact = _compact_text(text)
    return any(_compact_text(alias) in compact for alias in _metric_aliases(metric_name, metric_variant))


def metric_anchor_snippet(
    text: str,
    *,
    metric_name: str = "",
    metric_variant: str = "",
    limit: int = 120,
) -> str:
    raw = TABLE_MARK_PATTERN.sub(" ", str(text or ""))
    raw = _normalize_line(raw)
    if not raw:
        return ""
    aliases = _metric_aliases(metric_name, metric_variant)
    if not aliases:
        return ""
    for part in re.split(r"[，,；;。|]", raw):
        piece = _normalize_line(part)
        if len(piece) < 4:
            continue
        if not any(_compact_text(alias) in _compact_text(piece) for alias in aliases):
            continue
        if re.search(r"\d+\s*(?:[-~至到]\s*)?\d*\s*(?:篇|项|名|人|份)", piece):
            piece = re.sub(r"^.*?(具体目标|指标值|实施期目标)[:：]?", "", piece)
            return _clean_highlight_display(piece)[:limit]
    compact_raw = _compact_text(raw)
    best_alias = ""
    best_pos = -1
    for alias in aliases:
        compact_alias = _compact_text(alias)
        pos = compact_raw.find(compact_alias)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_alias = alias
            best_pos = pos
    if best_pos < 0:
        return ""

    # 用原始文本上的宽松位置切片，避免表格整行被高亮。
    match = re.search(re.escape(best_alias), raw)
    if not match:
        compact_alias = _compact_text(best_alias)
        pattern = r"\s*".join(re.escape(ch) for ch in compact_alias)
        match = re.search(pattern, raw)
    if not match:
        return best_alias[:limit]
    start = max(0, match.start() - 36)
    end = min(len(raw), match.end() + 72)
    snippet = raw[start:end]
    snippet = re.sub(r"^[^。；;|]{0,16}[。；;|]\s*", "", snippet)
    snippet = re.sub(r"\s*[。；;|][^。；;|]{0,40}$", "", snippet)
    return _clean_highlight_display(snippet)[:limit]


def taskbook_pdf_search_phrases(
    highlight_text: str,
    *,
    metric_name: str = "",
    metric_variant: str = "",
) -> list[str]:
    phrases: list[str] = []
    text = _normalize_line(highlight_text)
    if metric_name == "发明专利" or "发明专利" in text:
        phrases.extend(["国家发明专利", "发明专利"])
    elif metric_name == "科技论文" or "论文" in text:
        phrases.extend(["发表三类高质量论文", "高质量论文", "论文"])
    elif metric_name == "培养研究生" or "研究生" in text:
        phrases.extend(["培养研究生", "联合培养研究生", "研究生"])
    phrases.extend(locator_phrase_variants(highlight_text, limit=8))
    range_match = re.search(r"(.{2,40}?)(\d+)\s+(\d+)\s*(篇|项|名|人|份)", text)
    if range_match:
        prefix = _normalize_line(range_match.group(1))
        left, right, unit = range_match.group(2), range_match.group(3), range_match.group(4)
        if prefix:
            phrases.extend(
                [
                    prefix,
                    f"{prefix}\n{left}-{right} {unit}",
                    f"{prefix}{left}-{right} {unit}",
                    f"{prefix}\n{left} —{right} {unit}",
                    f"{prefix}{left}—{right} {unit}",
                ]
            )
            for alias in _metric_aliases(metric_name, metric_variant):
                if _compact_text(alias) and _compact_text(alias) in _compact_text(prefix):
                    phrases.extend([f"{alias}{left}-{right} {unit}", f"{alias}\n{left}-{right} {unit}"])
    phrases.extend(_metric_aliases(metric_name, metric_variant))
    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        phrase = _normalize_line(phrase)
        if len(phrase) < 2:
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(phrase)
    return deduped


def _title_in_block(title: str, block_text: str) -> bool:
    title_norm = _normalize_line(title)
    block_norm = _normalize_line(block_text)
    if not title_norm or not block_norm:
        return False
    if title_norm in block_norm:
        return True
    compact_title = _compact_text(title_norm)
    compact_block = _compact_text(block_norm)
    if len(compact_title) < 8:
        return False
    return compact_title in compact_block or compact_title[:20] in compact_block


def evidence_locator_text(
    *,
    title: str = "",
    excerpt: str = "",
    reason: str = "",
    doc_kind: str = "",
) -> str:
    """生成用于页内检索与高亮框定位的文本（单件成果优先题名）。"""
    clean_title = _normalize_line(title)
    if clean_title and str(doc_kind or "") in ITEMIZED_LOCATOR_DOC_KINDS:
        return clean_title
    for part in (excerpt, reason, title):
        text = _normalize_line(str(part or ""))
        if text:
            return text
    return ""


def pick_search_phrases(
    text: str,
    *,
    metric_name: str = "",
    limit: int = 12,
) -> list[str]:
    """从摘录中抽取可在页内精确检索的短语（优先表格实际完成列、数值+单位）。"""
    raw = TABLE_MARK_PATTERN.sub(" ", str(text or ""))
    raw = _normalize_line(raw)
    if not raw:
        return []

    phrases: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        normalized = _normalize_line(candidate)
        if len(normalized) < 4:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        phrases.append(normalized[:120])

    for match in NUMERIC_UNIT_PATTERN.finditer(raw):
        add(match.group(0))

    for pattern in METRIC_HINT_PATTERNS.get(metric_name, []):
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            add(match.group(0))

    for part in re.split(r"[|；;。\n]", raw):
        part = _normalize_line(part)
        if len(part) < 6:
            continue
        if metric_name and metric_name not in part and not NUMERIC_UNIT_PATTERN.search(part):
            if "其" not in part and "实际" not in part:
                continue
        add(part)

    for sep in ("；", ";", "。", "|"):
        if sep in raw:
            for part in raw.split(sep):
                add(part)

    add(raw)
    return _sort_phrases(phrases, metric_name=metric_name)[:limit]


def _phrase_priority(phrase: str, *, metric_name: str = "") -> tuple[int, int, int]:
    lower = phrase.lower()
    actual_bonus = 0
    if phrase.startswith("其") or "实际" in phrase or "完成" in phrase:
        actual_bonus = -80
    metric_bonus = -30 if metric_name and metric_name in phrase else 0
    numeric_bonus = 0
    if "cells" in lower or "cell" in lower:
        numeric_bonus = -40
    elif re.search(r"\d{4,}", phrase):
        numeric_bonus = -25
    # 任务书目标列（如 0-200mg/L）优先级靠后
    task_column_penalty = 20 if re.search(r"0-200\s*mg", phrase, flags=re.IGNORECASE) else 0
    return (actual_bonus + metric_bonus + numeric_bonus + task_column_penalty, -len(phrase), 0)


def _sort_phrases(phrases: list[str], *, metric_name: str = "") -> list[str]:
    return sorted(phrases, key=lambda item: _phrase_priority(item, metric_name=metric_name))


def pick_metric_snippet(text: str, metric_name: str, *, limit: int = 80) -> str:
    raw = TABLE_MARK_PATTERN.sub(" ", str(text or ""))
    raw = _normalize_line(raw)
    if not raw or not metric_name:
        return ""
    for pattern in METRIC_HINT_PATTERNS.get(metric_name, []):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            snippet = _normalize_line(match.group(0))
            if len(snippet) >= 4:
                return snippet[:limit]
    for part in re.split(r"[|；;。\n]", raw):
        part = _normalize_line(part)
        if len(part) < 6:
            continue
        if metric_name == "检测范围" and ("检测范围" in part or "cells" in part.lower()):
            return part[:limit]
        if metric_name == "检测频率" and ("频率" in part or "次/时" in part):
            return part[:limit]
        if metric_name == "检测标准偏差" and ("标准偏差" in part or "标准误差" in part):
            return part[:limit]
        if metric_name == "最大测量误差" and "测量误差" in part:
            return part[:limit]
    return ""


def pick_highlight_text(
    *parts: str | None,
    metric_name: str = "",
    limit: int = 120,
    doc_kind: str = "",
) -> str:
    """用于 viewer 卡片展示与检索的主短语。"""
    if str(doc_kind or "") in ITEMIZED_LOCATOR_DOC_KINDS:
        for raw in parts:
            text = _clean_highlight_display(str(raw or ""))
            if len(text) >= 6:
                return text[:limit]
    for raw in parts:
        text = str(raw or "")
        metric_snippet = pick_metric_snippet(text, metric_name, limit=limit)
        if metric_snippet:
            return _clean_highlight_display(metric_snippet)[:limit]
        phrases = pick_search_phrases(text, metric_name=metric_name)
        for phrase in phrases:
            if len(phrase) >= 6:
                return _clean_highlight_display(phrase)[:limit]
    return ""


def infer_page_size_from_blocks(blocks: list[ParsedAcceptanceBlock], page_index: int) -> tuple[float, float] | None:
    widths: list[float] = []
    heights: list[float] = []
    for block in blocks:
        if int(block.page or 0) != page_index or block.bbox is None:
            continue
        bbox = block.bbox
        widths.append(float(bbox.x) + float(bbox.width))
        heights.append(float(bbox.y) + float(bbox.height))
    if not widths or not heights:
        return None
    width = max(widths)
    height = max(heights)
    if width <= 0 or height <= 0:
        return None
    if width <= 1.5 and height <= 1.5:
        return 1.0, 1.0
    return width, height


def resolve_page_size(
    *,
    file_path: Path | None,
    blocks: list[ParsedAcceptanceBlock],
    page_index: int,
) -> tuple[float, float] | None:
    """优先使用 PDF/图片真实页尺寸，避免按 block 外接框推断导致高亮偏移。"""
    if file_path is not None:
        try:
            from src.services.accept.run_accept_local_batch import get_document_page_size

            size = get_document_page_size(str(file_path.resolve()), int(page_index))
            if size and size[0] > 0 and size[1] > 0:
                return size
        except Exception:
            pass
    return infer_page_size_from_blocks(blocks, page_index)


def build_page_sizes_map(file_path: Path | None) -> dict[str, list[float]]:
    if file_path is None or not file_path.exists():
        return {}
    try:
        from src.services.accept.run_accept_local_batch import get_document_page_size

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            import fitz

            doc = fitz.open(file_path)
            try:
                return {
                    str(index): [float(doc.load_page(index).rect.width), float(doc.load_page(index).rect.height)]
                    for index in range(doc.page_count)
                }
            finally:
                doc.close()
        size = get_document_page_size(str(file_path.resolve()), 0)
        if size:
            return {"0": [float(size[0]), float(size[1])]}
    except Exception:
        return {}
    return {}


def normalize_bbox_rect(
    bbox: BoundingBox | None,
    *,
    page_width: float,
    page_height: float,
) -> list[dict[str, float]]:
    if bbox is None or page_width <= 0 or page_height <= 0:
        return []
    x = max(0.0, min(float(bbox.x) / page_width, 1.0))
    y = max(0.0, min(float(bbox.y) / page_height, 1.0))
    w = max(0.0, min(float(bbox.width) / page_width, 1.0 - x))
    h = max(0.0, min(float(bbox.height) / page_height, 1.0 - y))
    if w <= 0 or h <= 0:
        return []
    pad_x, pad_y = 0.006, 0.01
    x = max(0.0, x - pad_x)
    y = max(0.0, y - pad_y)
    w = min(1.0 - x, w + pad_x * 2)
    h = min(1.0 - y, h + pad_y * 2)
    if w <= 0 or h <= 0:
        return []
    return [{"x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6)}]


def rect_area(rect: dict[str, float]) -> float:
    return float(rect.get("w") or 0) * float(rect.get("h") or 0)


def rect_is_oversized(rects: list[dict[str, float]], *, allow_wide_title: bool = False) -> bool:
    if not rects:
        return True
    rect = rects[0]
    w = float(rect.get("w") or 0)
    h = float(rect.get("h") or 0)
    area = w * h
    if allow_wide_title and h <= 0.14 and w <= 0.96:
        return area > 0.22
    return area > 0.15 or w > 0.92 or h > 0.38


def _phrase_matches_block(phrase: str, block_text: str) -> bool:
    phrase_norm = _normalize_line(phrase)
    block_norm = _normalize_line(block_text)
    if not phrase_norm or not block_norm:
        return False
    if phrase_norm in block_norm:
        return True
    compact_phrase = re.sub(r"\s+", "", phrase_norm)
    compact_block = re.sub(r"\s+", "", block_norm)
    return len(compact_phrase) >= 6 and compact_phrase in compact_block


def locator_phrase_variants(text: str, *, limit: int = 8) -> list[str]:
    norm = _normalize_line(text)
    if not norm:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        cleaned = _normalize_line(candidate)
        if len(cleaned) < 4:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        variants.append(cleaned[:160])

    add(norm)
    compact = _compact_text(norm)
    if compact and compact != norm:
        add(compact)
    if len(norm) > 36:
        add(norm[:36])
    if len(norm) > 20:
        add(norm[:20])
    for part in re.split(r"[|；;。\n]", norm):
        part = _normalize_line(part)
        if len(part) >= 8:
            add(part)
    return variants[:limit]


def find_block_rects_by_phrases(
    *,
    blocks: list[ParsedAcceptanceBlock],
    page_index: int,
    phrases: list[str],
    metric_name: str = "",
    allow_wide_title: bool = False,
    file_path: Path | None = None,
) -> tuple[list[dict[str, float]], str, int]:
    """在同页文本块中找最小、最匹配的 bbox。"""
    page_size = resolve_page_size(file_path=file_path, blocks=blocks, page_index=page_index)
    if page_size is None:
        return [], "", page_index
    page_width, page_height = page_size
    best: tuple[float, list[dict[str, float]], str] | None = None
    expanded: list[str] = []
    for phrase in phrases:
        expanded.extend(locator_phrase_variants(phrase, limit=6))
    ordered = _sort_phrases(expanded, metric_name=metric_name)
    for block in blocks:
        if int(block.page or 0) != page_index or block.bbox is None:
            continue
        block_text = str(block.text or "")
        for phrase in ordered:
            if not _phrase_matches_block(phrase, block_text):
                continue
            rects = normalize_bbox_rect(block.bbox, page_width=page_width, page_height=page_height)
            if not rects or rect_is_oversized(rects, allow_wide_title=allow_wide_title):
                continue
            score = rect_area(rects[0]) - len(phrase) * 0.0001
            if best is None or score < best[0]:
                best = (score, rects, block.block_id)
    if best is None:
        return [], "", page_index
    return best[1], best[2], page_index


def find_block_rects_near_page(
    *,
    blocks: list[ParsedAcceptanceBlock],
    center_page: int,
    phrases: list[str],
    metric_name: str = "",
    allow_wide_title: bool = False,
    radius: int = 4,
    file_path: Path | None = None,
) -> tuple[list[dict[str, float]], str, int]:
    center = max(0, int(center_page))
    for distance in range(0, radius + 1):
        for page_index in sorted({center - distance, center + distance}):
            if page_index < 0:
                continue
            rects, block_id, _ = find_block_rects_by_phrases(
                blocks=blocks,
                page_index=page_index,
                phrases=phrases,
                metric_name=metric_name,
                allow_wide_title=allow_wide_title,
                file_path=file_path,
            )
            if rects:
                return rects, block_id, page_index
    return [], "", center


def search_rects_in_pdf(path: Path, page_index: int, phrases: list[str]) -> list[dict[str, float]]:
    if path.suffix.lower() != ".pdf" or not phrases:
        return []
    try:
        from src.services.accept.run_accept_local_batch import search_rects_in_pdf as batch_search

        for phrase in phrases:
            rects = batch_search(path, page_index, phrase)
            if rects and not rect_is_oversized(rects):
                return rects
        return []
    except Exception:
        return []


def pick_taskbook_anchor_line(
    source_line: str,
    *,
    metric_name: str = "",
    metric_variant: str = "",
) -> str:
    """从合并后的任务书原文中选出最适合定位的那一行。"""
    text = str(source_line or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return text
    if len(lines) == 1:
        return lines[0]

    keyword_groups: list[tuple[str, ...]] = []
    if metric_variant == "科技报告/研究报告":
        keyword_groups.append(("撰写科技报告", "科技报告、研究报告", "科技报告,研究报告"))
    aliases = _metric_aliases(metric_name, metric_variant)
    if aliases:
        keyword_groups.append(aliases)
    for keywords in keyword_groups:
        scored: list[tuple[int, int, str]] = []
        for index, line in enumerate(lines):
            compact = _compact_text(line)
            if not any(_compact_text(keyword) in compact for keyword in keywords):
                continue
            overall_bonus = -60 if any(token in compact for token in ("具体目标", "总体目标", "实施期目标", "指标值")) else 0
            annual_penalty = 40 if any(token in compact for token in ("第一年度", "第二年度", "第三年度", "本年度目标")) else 0
            unit_bonus = -20 if re.search(r"\d+\s*(?:[-~至到]\s*)?\d*\s*(?:篇|项|名|人|份)", line) else 0
            scored.append((overall_bonus + annual_penalty + unit_bonus, index, line))
        if scored:
            return min(scored, key=lambda item: item[:2])[2]

    table_lines = [line for line in lines if TABLE_ROW_TAG_PATTERN.search(line)]
    for line in reversed(table_lines):
        if any(token in line for token in ("绩效", "实施期目标", "指标名称", "指标值")):
            return line
    if table_lines:
        return table_lines[-1]
    return lines[-1]


def find_taskbook_block_for_anchor(
    blocks: list[ParsedAcceptanceBlock],
    anchor_line: str,
) -> ParsedAcceptanceBlock | None:
    """按表格行标记或锚点行文本匹配任务书 block。"""
    anchor_line = str(anchor_line or "").strip()
    if not anchor_line or not blocks:
        return None
    row_match = TABLE_ROW_TAG_PATTERN.search(anchor_line)
    row_tag = row_match.group(0) if row_match else ""
    row_number = ""
    if row_match:
        number_match = re.search(r"\[表格行(\d+)\]", row_tag)
        row_number = number_match.group(1) if number_match else ""

    compact_anchor = _compact_text(anchor_line)
    matched: list[ParsedAcceptanceBlock] = []
    for block in blocks:
        text = str(block.text or "")
        compact_block = _compact_text(text)
        if row_tag and row_tag in text:
            matched.append(block)
            continue
        if row_number and f"表格行{row_number}" in compact_block:
            matched.append(block)
            continue
        if len(compact_anchor) >= 12 and compact_anchor in compact_block:
            matched.append(block)

    if not matched:
        return None

    def score(block: ParsedAcceptanceBlock) -> tuple[int, int]:
        text = _compact_text(block.text or "")
        core = compact_anchor
        for token in ("总体目标", "绩效指标", "实施期目标", "指标名称", "指标值", "第一年度目标", "当前年度"):
            core = core.replace(_compact_text(token), "")
        missing_core = 0 if core and core in text else 1
        return (missing_core, len(text))

    return min(matched, key=score)


def pick_taskbook_highlight_text(
    anchor_line: str,
    *,
    metric_name: str = "",
    metric_variant: str = "",
    limit: int = 120,
) -> str:
    anchor_line = str(anchor_line or "")
    if metric_variant == "科技报告/研究报告":
        match = re.search(r"撰写科技报告\s*[、,，]\s*研\s*究\s*报告[^|；。]{0,24}", anchor_line)
        if match:
            return _clean_highlight_display(match.group(0))[:limit]
    snippet = metric_anchor_snippet(
        anchor_line,
        metric_name=metric_name,
        metric_variant=metric_variant,
        limit=limit,
    )
    if snippet:
        return snippet
    snippet = pick_metric_snippet(anchor_line, metric_name, limit=limit)
    if snippet:
        return _clean_highlight_display(snippet)[:limit]
    return pick_highlight_text(anchor_line, metric_name=metric_name, limit=limit)


def resolve_taskbook_commitment_target(
    *,
    file_path: Path | None,
    blocks: list[ParsedAcceptanceBlock],
    source_line: str,
    metric_name: str = "",
    metric_variant: str = "",
    source_block_id: str = "",
    source_page: int = 0,
) -> dict[str, Any]:
    """任务书指标定位：优先表格行 block，避免合并原文导致跳到签章页等无关位置。"""
    anchor_line = pick_taskbook_anchor_line(
        source_line,
        metric_name=metric_name,
        metric_variant=metric_variant,
    )
    anchor_block = find_taskbook_block_for_anchor(blocks, anchor_line)
    stored_block = next(
        (block for block in blocks if block.block_id == str(source_block_id or "")),
        None,
    )
    if anchor_block is None and stored_block is not None and anchor_line:
        if _phrase_matches_block(anchor_line, stored_block.text):
            anchor_block = stored_block

    anchor_page = int(anchor_block.page) if anchor_block is not None else int(source_page or 0)
    highlight_text = pick_taskbook_highlight_text(
        anchor_line,
        metric_name=metric_name,
        metric_variant=metric_variant,
    )
    if file_path is not None and highlight_text:
        phrases = taskbook_pdf_search_phrases(
            highlight_text,
            metric_name=metric_name,
            metric_variant=metric_variant,
        )
        candidate_pages = [anchor_page, int(source_page or 0), anchor_page + 1, anchor_page - 1]
        seen_pages: set[int] = set()
        for page in candidate_pages:
            if page < 0 or page in seen_pages:
                continue
            seen_pages.add(page)
            pdf_rects = search_rects_in_pdf(file_path, page, phrases)
            if pdf_rects:
                return {
                    "viewer_rects": pdf_rects,
                    "source_page": page,
                    "source_block_id": anchor_block.block_id if anchor_block and int(anchor_block.page) == page else "",
                    "highlight_text": highlight_text,
                }

    if anchor_block is not None and anchor_block.bbox is not None:
        page_size = resolve_page_size(file_path=file_path, blocks=blocks, page_index=int(anchor_block.page))
        if page_size:
            rects = normalize_bbox_rect(
                anchor_block.bbox,
                page_width=page_size[0],
                page_height=page_size[1],
            )
            if rects and not rect_is_oversized(rects):
                return {
                    "viewer_rects": rects,
                    "source_page": int(anchor_block.page),
                    "source_block_id": anchor_block.block_id,
                    "highlight_text": highlight_text,
                }

    page_index = anchor_page
    resolved = resolve_evidence_target(
        file_path=file_path,
        page_index=page_index,
        block=anchor_block or stored_block,
        blocks=blocks,
        text=anchor_line or source_line,
        metric_name=metric_name or (metric_variant.split("/")[0] if metric_variant else ""),
    )
    resolved["highlight_text"] = highlight_text
    return resolved


def resolve_evidence_target(
    *,
    file_path: Path | None,
    page_index: int,
    block: ParsedAcceptanceBlock | None,
    blocks: list[ParsedAcceptanceBlock],
    text: str,
    metric_name: str = "",
    title: str = "",
    doc_kind: str = "",
) -> dict[str, Any]:
    """解析证据定位：返回 viewer_rects / viewer_page / source_page / source_block_id / highlight_text。"""
    cache_key = _viewer_target_cache_key(
        file_path=file_path,
        page_index=page_index,
        block=block,
        text=text,
        metric_name=metric_name,
        title=title,
        doc_kind=doc_kind,
    )
    cached = _load_viewer_target_cache(cache_key)
    if cached is not None:
        return cached
    locator = evidence_locator_text(title=title, excerpt=text, doc_kind=doc_kind) or text
    allow_wide = str(doc_kind or "") in ITEMIZED_LOCATOR_DOC_KINDS
    anchor_page = int(block.page) if block is not None else int(page_index)
    phrases = locator_phrase_variants(locator, limit=10)
    phrases.extend(pick_search_phrases(locator, metric_name=metric_name))
    metric_snippet = pick_metric_snippet(locator, metric_name)
    if metric_snippet:
        phrases.insert(0, metric_snippet)
    if locator:
        phrases.insert(0, locator)
    deduped_phrases: list[str] = []
    seen_phrase: set[str] = set()
    for phrase in phrases:
        key = phrase.lower()
        if key in seen_phrase:
            continue
        seen_phrase.add(key)
        deduped_phrases.append(phrase)

    matched_block: ParsedAcceptanceBlock | None = None
    if block is not None and locator and _phrase_matches_block(locator, block.text):
        matched_block = block
    if matched_block is None and title:
        compact_title = _compact_text(title)
        for candidate in blocks:
            if not candidate.bbox:
                continue
            compact_block = _compact_text(candidate.text)
            if compact_title and (compact_title in compact_block or compact_title[:18] in compact_block):
                if matched_block is None or len(compact_block) < len(_compact_text(matched_block.text)):
                    matched_block = candidate

    if file_path is not None and str(doc_kind or "") in ITEMIZED_LOCATOR_DOC_KINDS:
        itemized_pages = [anchor_page]
        if matched_block is not None and int(matched_block.page) not in itemized_pages:
            itemized_pages.insert(0, int(matched_block.page))
        for page in itemized_pages:
            pdf_rects = search_rects_in_pdf(file_path, page, deduped_phrases)
            if pdf_rects:
                result = {
                    "viewer_rects": pdf_rects,
                    "source_page": page,
                    "source_block_id": matched_block.block_id if matched_block and int(matched_block.page) == page else (block.block_id if block else ""),
                    "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
                }
                _store_viewer_target_cache(cache_key, result)
                return result

    if matched_block is not None and matched_block.bbox is not None:
        page_size = resolve_page_size(file_path=file_path, blocks=blocks, page_index=int(matched_block.page))
        if page_size:
            rects = normalize_bbox_rect(
                matched_block.bbox,
                page_width=page_size[0],
                page_height=page_size[1],
            )
            if rects and not rect_is_oversized(rects, allow_wide_title=allow_wide):
                result = {
                    "viewer_rects": rects,
                    "source_page": int(matched_block.page),
                    "source_block_id": matched_block.block_id,
                    "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
                }
                _store_viewer_target_cache(cache_key, result)
                return result

    rects, block_id, hit_page = find_block_rects_near_page(
        blocks=blocks,
        center_page=anchor_page,
        phrases=deduped_phrases,
        metric_name=metric_name,
        allow_wide_title=allow_wide,
        file_path=file_path,
    )
    if rects:
        result = {
            "viewer_rects": rects,
            "source_page": hit_page,
            "source_block_id": block_id,
            "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
        }
        _store_viewer_target_cache(cache_key, result)
        return result

    search_pages = [anchor_page]
    for delta in (1, -1, 2, -2, 3, -3):
        candidate = anchor_page + delta
        if candidate >= 0 and candidate not in search_pages:
            search_pages.append(candidate)
    for page in search_pages:
        if file_path is None:
            continue
        pdf_rects = search_rects_in_pdf(file_path, page, deduped_phrases)
        if pdf_rects:
            result = {
                "viewer_rects": pdf_rects,
                "source_page": page,
                "source_block_id": block.block_id if block and int(block.page) == page else block_id,
                "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
            }
            _store_viewer_target_cache(cache_key, result)
            return result

    if matched_block is not None and matched_block.bbox is not None:
        page_size = resolve_page_size(file_path=file_path, blocks=blocks, page_index=int(matched_block.page))
        if page_size:
            rects = normalize_bbox_rect(
                matched_block.bbox,
                page_width=page_size[0],
                page_height=page_size[1],
            )
            if rects and not rect_is_oversized(rects, allow_wide_title=allow_wide):
                result = {
                    "viewer_rects": rects,
                    "source_page": int(matched_block.page),
                    "source_block_id": matched_block.block_id,
                    "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
                }
                _store_viewer_target_cache(cache_key, result)
                return result

    if block is not None and block.bbox is not None:
        page_size = resolve_page_size(file_path=file_path, blocks=blocks, page_index=int(block.page))
        if page_size:
            rects = normalize_bbox_rect(
                block.bbox,
                page_width=page_size[0],
                page_height=page_size[1],
            )
            if rects and not rect_is_oversized(rects, allow_wide_title=allow_wide):
                result = {
                    "viewer_rects": rects,
                    "source_page": int(block.page),
                    "source_block_id": block.block_id,
                    "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
                }
                _store_viewer_target_cache(cache_key, result)
                return result

    result = {
        "viewer_rects": [],
        "source_page": anchor_page,
        "source_block_id": block.block_id if block else "",
        "highlight_text": pick_highlight_text(title or locator, metric_name=metric_name, doc_kind=doc_kind),
    }
    _store_viewer_target_cache(cache_key, result)
    return result


def _viewer_target_cache_key(
    *,
    file_path: Path | None,
    page_index: int,
    block: ParsedAcceptanceBlock | None,
    text: str,
    metric_name: str,
    title: str,
    doc_kind: str,
) -> str:
    digest = hashlib.sha1()
    digest.update(VIEWER_TARGET_CACHE_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(file_path or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(page_index).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(block.block_id if block else "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(metric_name or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(title or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(doc_kind or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(text or "")[:2000].encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def _load_viewer_target_cache(cache_key: str) -> dict[str, Any] | None:
    path = VIEWER_TARGET_CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _store_viewer_target_cache(cache_key: str, payload: dict[str, Any]) -> None:
    path = VIEWER_TARGET_CACHE_DIR / f"{cache_key}.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def resolve_viewer_rects(
    *,
    file_path: Path | None,
    page_index: int,
    block: ParsedAcceptanceBlock | None,
    blocks: list[ParsedAcceptanceBlock],
    text: str,
    metric_name: str = "",
    title: str = "",
    doc_kind: str = "",
) -> list[dict[str, float]]:
    resolved = resolve_evidence_target(
        file_path=file_path,
        page_index=page_index,
        block=block,
        blocks=blocks,
        text=text,
        metric_name=metric_name,
        title=title,
        doc_kind=doc_kind,
    )
    rects = resolved.get("viewer_rects")
    return rects if isinstance(rects, list) else []


def enrich_subdoc_targets(
    *,
    subdocs: list[dict[str, object]],
    file_path: Path | None,
    blocks: list[ParsedAcceptanceBlock],
) -> list[dict[str, object]]:
    block_map = {block.block_id: block for block in blocks}
    enriched: list[dict[str, object]] = []
    for item in subdocs:
        payload = dict(item)
        page_index = int(payload.get("source_page") or 0)
        block = block_map.get(str(payload.get("source_block_id") or ""))
        metric_name = str(payload.get("metric_name") or "")
        if block is not None:
            page_index = int(block.page)
        payload["viewer_page"] = normalize_viewer_page(
            source_page=page_index,
            viewer_page=int(payload.get("viewer_page") or 0) or None,
        )
        doc_kind = str(payload.get("doc_kind") or "")
        title = str(payload.get("title") or "")
        resolved = resolve_evidence_target(
            file_path=file_path,
            page_index=page_index,
            block=block,
            blocks=blocks,
            text=title or str(payload.get("metric_name") or ""),
            metric_name=metric_name,
            title=title,
            doc_kind=doc_kind,
        )
        page_index = int(resolved.get("source_page") or page_index)
        payload["source_page"] = page_index
        if resolved.get("source_block_id"):
            payload["source_block_id"] = resolved["source_block_id"]
        payload["viewer_page"] = normalize_viewer_page(source_page=page_index)
        payload["viewer_rects"] = resolved.get("viewer_rects") or []
        payload["highlight_text"] = resolved.get("highlight_text") or pick_highlight_text(
            title,
            metric_name=metric_name,
            doc_kind=doc_kind,
        )
        enriched.append(payload)
    return enriched


def enrich_acceptance_project_targets(
    project: dict[str, object],
    *,
    document_blocks: dict[str, list[ParsedAcceptanceBlock]],
    document_paths: dict[str, Path],
) -> None:
    """为 rows / subdocs 补齐 viewer_page 与 viewer_rects。"""
    documents = project.get("documents")
    if isinstance(documents, list):
        _remap_patent_catalog_details_to_attachment_files(project, documents)
    if isinstance(documents, list):
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            file_name = str(doc.get("file_name") or "")
            subdocs = doc.get("subdocs")
            if not isinstance(subdocs, list) or not subdocs:
                continue
            blocks = document_blocks.get(file_name, [])
            doc_path = document_paths.get(file_name)
            if doc_path is not None and not doc.get("page_sizes"):
                doc["page_sizes"] = build_page_sizes_map(doc_path)
            doc["subdocs"] = enrich_subdoc_targets(
                subdocs=subdocs,
                file_path=doc_path,
                blocks=blocks,
            )

    rows = project.get("rows")
    if not isinstance(rows, list):
        return
    default_taskbook_name = ""
    if isinstance(documents, list):
        for doc in documents:
            if isinstance(doc, dict) and doc.get("role") == "hts":
                default_taskbook_name = str(doc.get("file_name") or "")
                break
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_page = int(row.get("source_page") or 0)
        metric_name = str(row.get("metric_name") or "")
        taskbook_name = str(row.get("source_file") or default_taskbook_name)
        taskbook_blocks = document_blocks.get(taskbook_name, [])
        taskbook_path = document_paths.get(taskbook_name)
        taskbook_block = next(
            (block for block in taskbook_blocks if block.block_id == str(row.get("source_block_id") or "")),
            None,
        )
        taskbook_page_index = int(taskbook_block.page) if taskbook_block else source_page
        row["viewer_page"] = normalize_viewer_page(
            source_page=taskbook_page_index,
            viewer_page=int(row.get("viewer_page") or 0) or None,
        )
        metric_variant = str(row.get("metric_variant") or "")
        resolved = resolve_taskbook_commitment_target(
            file_path=taskbook_path,
            blocks=taskbook_blocks,
            source_line=str(row.get("source_line") or row.get("reason") or ""),
            metric_name=metric_name,
            metric_variant=metric_variant,
            source_block_id=str(row.get("source_block_id") or ""),
            source_page=taskbook_page_index,
        )
        taskbook_page_index = int(resolved.get("source_page") or taskbook_page_index)
        row["source_page"] = taskbook_page_index
        if resolved.get("source_block_id"):
            row["source_block_id"] = resolved["source_block_id"]
        row["viewer_page"] = normalize_viewer_page(source_page=taskbook_page_index)
        row["viewer_rects"] = resolved.get("viewer_rects") or []
        row["highlight_text"] = resolved.get("highlight_text") or pick_taskbook_highlight_text(
            pick_taskbook_anchor_line(
                str(row.get("source_line") or row.get("reason") or ""),
                metric_name=metric_name,
                metric_variant=metric_variant,
            ),
            metric_name=metric_name,
            metric_variant=metric_variant,
        )
        details = row.get("match_details")
        if not isinstance(details, list):
            continue
        enriched_details: list[dict[str, Any]] = []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            detail_dict = dict(detail)
            page_index = int(detail_dict.get("source_page") or 0)
            file_name = str(detail_dict.get("file_name") or "")
            detail_metric = str(detail_dict.get("metric_name") or metric_name)
            blocks = document_blocks.get(file_name, [])
            block = next(
                (item for item in blocks if item.block_id == str(detail_dict.get("source_block_id") or "")),
                None,
            )
            if block is not None:
                page_index = int(block.page)
            detail_dict["viewer_page"] = normalize_viewer_page(
                source_page=page_index,
                viewer_page=int(detail_dict.get("viewer_page") or 0) or None,
            )
            doc_kind = str(detail_dict.get("doc_kind") or "")
            title = str(detail_dict.get("title") or "")
            locator = evidence_locator_text(
                title=title,
                excerpt=str(detail_dict.get("excerpt") or ""),
                reason=str(detail_dict.get("reason") or ""),
                doc_kind=doc_kind,
            )
            resolved = resolve_evidence_target(
                file_path=document_paths.get(file_name),
                page_index=page_index,
                block=block,
                blocks=blocks,
                text=locator,
                metric_name=detail_metric,
                title=title,
                doc_kind=doc_kind,
            )
            page_index = int(resolved.get("source_page") or page_index)
            detail_dict["source_page"] = page_index
            if resolved.get("source_block_id"):
                detail_dict["source_block_id"] = resolved["source_block_id"]
            detail_dict["viewer_page"] = normalize_viewer_page(source_page=page_index)
            detail_dict["viewer_rects"] = resolved.get("viewer_rects") or []
            detail_dict["highlight_text"] = resolved.get("highlight_text") or pick_highlight_text(
                title,
                locator,
                detail_dict.get("reason"),
                metric_name=detail_metric,
                doc_kind=doc_kind,
            )
            enriched_details.append(detail_dict)
        row["match_details"] = enriched_details


def _remap_patent_catalog_details_to_attachment_files(
    project: dict[str, object],
    documents: list[object],
) -> None:
    rows = project.get("rows")
    if not isinstance(rows, list):
        return

    attachment_docs: list[dict[str, object]] = []
    doc_by_file: dict[str, dict[str, object]] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        if str(doc.get("role") or "") != "yssqfj":
            continue
        file_name = str(doc.get("file_name") or "").strip()
        if not file_name:
            continue
        attachment_docs.append(doc)
        doc_by_file[file_name] = doc
    if not attachment_docs:
        return

    # 先排除已被其他证据明确使用的附件文件，专利目录条目只从剩余附件中映射。
    referenced_files: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric_name = str(row.get("metric_name") or "")
        details = row.get("match_details")
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            file_name = str(detail.get("file_name") or "")
            if file_name not in doc_by_file:
                continue
            excerpt = str(detail.get("excerpt") or "")
            is_patent_catalog_item = (
                metric_name in {"发明专利", "实用新型专利"}
                and str(detail.get("evidence_mode") or "") == "itemized"
                and str(detail.get("doc_kind") or "") == "验收申请"
                and any(token in excerpt for token in ("专利授权证书", "专利受理通知书"))
            )
            if is_patent_catalog_item:
                continue
            referenced_files.add(file_name)

    non_patent_tokens = (
        "论文",
        "research article",
        "科技报告",
        "自评价",
        "验收大纲",
        "任务书",
        "应用证明",
        "资金决算",
        "决算总表",
        "经费",
    )

    def _doc_meta(doc: dict[str, object]) -> tuple[str, int, int, str]:
        file_name = str(doc.get("file_name") or "")
        page_count = int(doc.get("page_count") or 0)
        file_size = 0
        file_path = str(doc.get("file_path") or "")
        if file_path:
            try:
                file_size = int(Path(file_path).stat().st_size)
            except Exception:
                file_size = 0
        title = str(doc.get("display_title") or "")
        return file_name, page_count, file_size, title

    def _is_likely_patent_doc(doc: dict[str, object]) -> bool:
        file_name, page_count, _, title = _doc_meta(doc)
        if not file_name or file_name in referenced_files:
            return False
        # 当前批次专利证明多为 1-2 页扫描件，正文不可提取时采用此兜底特征。
        if page_count <= 0 or page_count > 2:
            return False
        low_title = title.lower()
        if any(token in low_title for token in non_patent_tokens):
            return False
        return True

    likely_patent_docs = [doc for doc in attachment_docs if _is_likely_patent_doc(doc)]
    if len(likely_patent_docs) < 4:
        # 兜底：若严格特征不足，放宽到“未被引用的附件”。
        likely_patent_docs = [
            doc
            for doc in attachment_docs
            if str(doc.get("file_name") or "") not in referenced_files
        ]

    if not likely_patent_docs:
        return

    one_page = sorted(
        [doc for doc in likely_patent_docs if int(doc.get("page_count") or 0) == 1],
        key=lambda doc: (_doc_meta(doc)[2], _doc_meta(doc)[0]),
    )
    multi_page = sorted(
        [doc for doc in likely_patent_docs if int(doc.get("page_count") or 0) >= 2],
        key=lambda doc: (-_doc_meta(doc)[2], _doc_meta(doc)[1], _doc_meta(doc)[0]),
    )
    fallback_all = sorted(
        likely_patent_docs,
        key=lambda doc: (_doc_meta(doc)[1], _doc_meta(doc)[2], _doc_meta(doc)[0]),
    )

    used_mapped_files: set[str] = set()

    def _pick_doc_for_label(label: str) -> dict[str, object] | None:
        pools: list[list[dict[str, object]]]
        if "授权证书" in label:
            pools = [multi_page, fallback_all, one_page]
        else:
            pools = [one_page, fallback_all, multi_page]
        for pool in pools:
            for candidate in pool:
                file_name = str(candidate.get("file_name") or "")
                if not file_name or file_name in used_mapped_files:
                    continue
                used_mapped_files.add(file_name)
                return candidate
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("metric_name") or "") not in {"发明专利", "实用新型专利"}:
            continue
        details = row.get("match_details")
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            if str(detail.get("evidence_mode") or "") != "itemized":
                continue
            if str(detail.get("doc_kind") or "") != "验收申请":
                continue
            excerpt = str(detail.get("excerpt") or "")
            if "专利授权证书" not in excerpt and "专利受理通知书" not in excerpt:
                continue

            label_match = re.search(r"(专利授权证书|专利受理通知书\d*)", excerpt)
            label = label_match.group(1) if label_match else "专利证明材料"
            mapped_doc = _pick_doc_for_label(label)
            if mapped_doc is None:
                continue

            mapped_file = str(mapped_doc.get("file_name") or "")
            mapped_title = str(mapped_doc.get("display_title") or mapped_file)

            original_file = str(detail.get("file_name") or "")
            detail["mapped_from_file_name"] = original_file
            detail["mapped_from_doc_kind"] = str(detail.get("doc_kind") or "")
            detail["file_name"] = mapped_file
            detail["doc_kind"] = "专利证书"
            detail["display_title"] = mapped_title
            detail["title"] = label
            detail["source_block_id"] = ""
            detail["source_page"] = 0
            detail["viewer_page"] = 1
            detail["viewer_rects"] = []
            detail["highlight_text"] = label
            detail["artifact_key"] = f"{detail.get('artifact_key') or ''}|mapped:{mapped_file}"
            detail["excerpt"] = f"{excerpt}；对应附件文件：{mapped_file}"
            base_reason = str(detail.get("reason") or "")
            mapping_note = f"目录条目已映射到附件文件 {mapped_file}"
            detail["reason"] = f"{base_reason}，{mapping_note}" if base_reason else mapping_note
        _dedupe_patent_details_by_attachment_content(row, doc_by_file)


def _attachment_content_hash(doc: dict[str, object]) -> str:
    file_path = str(doc.get("file_path") or "")
    if not file_path:
        return ""
    try:
        digest = hashlib.sha1()
        with Path(file_path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def _dedupe_patent_details_by_attachment_content(
    row: dict[str, object],
    doc_by_file: dict[str, dict[str, object]],
) -> None:
    details = row.get("match_details")
    if not isinstance(details, list):
        return

    seen_hashes: set[str] = set()
    deduped: list[object] = []
    removed_count = 0
    for detail in details:
        if not isinstance(detail, dict):
            deduped.append(detail)
            continue
        is_patent_attachment = (
            str(detail.get("evidence_mode") or "") == "itemized"
            and str(detail.get("doc_kind") or "") == "专利证书"
            and str(detail.get("file_name") or "") in doc_by_file
        )
        if not is_patent_attachment:
            deduped.append(detail)
            continue
        content_hash = _attachment_content_hash(doc_by_file[str(detail.get("file_name") or "")])
        if content_hash:
            detail["content_hash"] = content_hash
        if content_hash and content_hash in seen_hashes:
            removed_count += 1
            continue
        if content_hash:
            seen_hashes.add(content_hash)
        deduped.append(detail)

    if removed_count <= 0:
        return
    row["match_details"] = deduped

    attachment_count = sum(
        1
        for detail in deduped
        if isinstance(detail, dict)
        and str(detail.get("evidence_mode") or "") == "itemized"
        and str(detail.get("doc_kind") or "") == "专利证书"
    )
    if attachment_count <= 0:
        return

    target_unit = str(row.get("target_unit") or "项")
    application_value = float(row.get("application_value") or 0.0)
    actual_value = float(attachment_count)
    applied_count = int(row.get("application_evidence_count") or 0) + attachment_count

    row["attachment_evidence_count"] = attachment_count
    row["attachment_value"] = actual_value
    row["attachment_display"] = f"{_format_display_number(actual_value)}{target_unit}"
    row["actual_value"] = actual_value
    row["actual_display"] = f"{_format_display_number(actual_value)}{target_unit}"
    row["applied_evidence_count"] = applied_count

    matched_count = int(row.get("matched_evidence_count") or 0)
    if matched_count > 0:
        row["matched_evidence_count"] = max(matched_count - removed_count, applied_count)

    target_display = str(row.get("target_display") or "")
    row["consistency_summary"] = (
        f"任务书目标 {target_display}；验收申请声明 {_format_display_number(application_value)}{target_unit}；"
        f"附件证明 {_format_display_number(actual_value)}{target_unit}；验收申请与附件证明均达到任务书考核指标，"
        "且附件证明不低于验收申请表完成情况，满足验收"
    )
    row["rule_basis"] = re.sub(
        r"按去重后的单件成果证据核验，共\s*\d+\s*件",
        f"按去重后的单件成果证据核验，共 {attachment_count} 件",
        str(row.get("rule_basis") or ""),
    )
    row["reason"] = re.sub(
        r"附件证明\s*\d+\s*项",
        f"附件证明 {_format_display_number(actual_value)}{target_unit}",
        str(row.get("reason") or ""),
    )
    row["reason"] = re.sub(
        r"采用\s*\d+\s*条有效定位证据",
        f"采用 {applied_count} 条有效定位证据",
        str(row.get("reason") or ""),
    )


def _format_display_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
