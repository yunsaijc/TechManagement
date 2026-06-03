"""Reward 数据库字段文本查重 HTML 报告生成器。"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import List, Tuple


class RewardPlagiarismHtmlReportBuilder:
    """基于 debug JSON 生成 reward 字段文本专用 HTML 报告。"""

    def build_from_debug_file(self, debug_json_path: Path, output_html_path: Path) -> Path:
        data = json.loads(debug_json_path.read_text(encoding="utf-8"))
        html_content = self.build_html(data)
        output_html_path.write_text(html_content, encoding="utf-8")
        return output_html_path

    def build_html(self, data: dict) -> str:
        primary_doc = str(data.get("primary_doc") or "主文档")
        duplicate_segments = data.get("duplicate_segments", []) or []
        template_segments = data.get("template_segments", []) or []
        summary = data.get("summary", {}) or {}
        texts = data.get("documents", {}) or {}
        primary_text = str(texts.get(primary_doc) or "")

        source_docs = self._collect_source_docs(duplicate_segments, template_segments)
        source_label = html.escape(source_docs[0]) if len(source_docs) == 1 else f"共 {len(source_docs)} 个来源"

        stats = self._build_statistics(summary, primary_text, duplicate_segments, template_segments)
        left_html = self._render_full_document(primary_text, duplicate_segments, side="primary")
        right_html = self._render_source_documents(texts, duplicate_segments, source_docs)
        match_cards = self._build_match_nav(duplicate_segments)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>数据库字段文本查重报告 - {html.escape(primary_doc)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fb; color: #1f2937; }}
    .page {{ height: 100vh; display: flex; flex-direction: column; }}
    .toolbar {{ position: sticky; top: 0; z-index: 20; background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 14px 18px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
    .title {{ font-size: 18px; font-weight: 700; }}
    .meta {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 320px 1fr; gap: 12px; padding: 12px; align-items: stretch; }}
    .sidebar {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; overflow: auto; }}
    .content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; height: 100%; align-items: stretch; }}
    .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; display: flex; flex-direction: column; min-height: 0; height: 100%; }}
    .panel-header {{ padding: 12px 14px; border-bottom: 1px solid #e5e7eb; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; }}
    .panel-body {{ padding: 12px; overflow: auto; scroll-behavior: smooth; flex: 1; min-height: 0; }}
    .doc-table {{ display: flex; flex-direction: column; }}
    .doc-row {{ display: grid; grid-template-columns: 44px 1fr; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }}
    .doc-row:last-child {{ border-bottom: none; }}
    .row-no {{ color: #94a3b8; text-align: right; font-size: 12px; line-height: 1.9; user-select: none; font-variant-numeric: tabular-nums; }}
    .row-text {{ line-height: 1.9; font-size: 14px; white-space: pre-wrap; word-break: break-word; }}
    .source-doc {{ border: 1px solid #e5e7eb; border-radius: 10px; margin-bottom: 12px; overflow: hidden; }}
    .source-doc:last-child {{ margin-bottom: 0; }}
    .source-doc-header {{ padding: 10px 12px; background: #f8fafc; border-bottom: 1px solid #e5e7eb; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; }}
    .source-doc-body {{ padding: 0 12px 12px; }}
    .hit {{ background: rgba(239, 68, 68, .18); color: #111827; border-radius: 4px; padding: 0 1px; cursor: pointer; transition: all .15s ease; }}
    .hit.active {{ background: rgba(220, 38, 38, .34); box-shadow: 0 0 0 2px rgba(220,38,38,.12); color: #b91c1c; }}
    .nav-title {{ font-weight: 700; margin-bottom: 10px; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 10px; margin-bottom: 8px; cursor: pointer; }}
    .nav-item:hover {{ border-color: #fca5a5; background: #fff5f5; }}
    .nav-item small {{ display: block; color: #6b7280; margin-top: 4px; line-height: 1.6; }}
    .empty {{ color: #9ca3af; font-size: 13px; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; width: 100%; }}
    .stat-card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 4px; font-size: 20px; font-weight: 700; color: #0f172a; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="toolbar">
      <div>
        <div class="title">数据库字段文本查重报告</div>
        <div style="font-size: 13px; color: #6b7280; margin-top: 4px;">左侧主文档：{html.escape(primary_doc)} ｜ 右侧来源：{source_label}</div>
        <div class="stats">{stats}</div>
      </div>
      <div class="meta">
        <div class="pill">有效重复段：{summary.get("total_effective_segments", 0)}</div>
        <div class="pill">模板段：{summary.get("total_template_segments", 0)}</div>
        <div class="pill">有效字符：{summary.get("total_effective_chars", 0)}</div>
      </div>
    </div>
    <div class="main">
      <aside class="sidebar">
        <div class="nav-title">重复片段导航</div>
        {match_cards or '<div class="empty">暂无有效重复片段</div>'}
      </aside>
      <section class="content">
        <div class="panel">
          <div class="panel-header"><span>Primary</span><span>{html.escape(primary_doc)}</span></div>
          <div id="primary-panel" class="panel-body">{left_html or '<div class="empty">暂无内容</div>'}</div>
        </div>
        <div class="panel">
          <div class="panel-header"><span>Sources</span><span>{source_label}</span></div>
          <div id="source-panel" class="panel-body">{right_html or '<div class="empty">暂无内容</div>'}</div>
        </div>
      </section>
    </div>
  </div>
  <script>
    const activateMatch = (matchId) => {{
      document.querySelectorAll('.hit.active').forEach(el => el.classList.remove('active'));
      const targets = document.querySelectorAll(`[data-match-id="${{matchId}}"]`);
      targets.forEach(el => el.classList.add('active'));
      const primary = document.querySelector(`.hit[data-side="primary"][data-match-id="${{matchId}}"]`);
      const source = document.querySelector(`.hit[data-side="source"][data-match-id="${{matchId}}"]`);
      if (primary) primary.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      if (source) source.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    }};

    document.querySelectorAll('.hit, .nav-item').forEach(el => {{
      el.addEventListener('click', () => activateMatch(el.dataset.matchId));
    }});
  </script>
</body>
</html>
"""

    def _build_match_nav(self, segments: List[dict]) -> str:
        nav_parts: List[str] = []
        for idx, segment in enumerate(segments, start=1):
            match_id = self._segment_match_id(segment, idx)
            source = (segment.get("sources") or [{}])[0]
            similarity = segment.get("similarity_score", 0)
            primary_line = segment.get("primary_line", 0)
            source_line = source.get("line", 0)
            source_doc = source.get("doc", "")
            nav_parts.append(
                f'<button class="nav-item" data-match-id="{match_id}">#{idx} <small>{html.escape(str(source_doc))} ｜ Primary L{primary_line} → Source L{source_line} ｜ 相似度 {similarity}</small></button>'
            )
        return "".join(nav_parts)

    def _collect_source_docs(self, duplicate_segments: List[dict], template_segments: List[dict]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for pool in (duplicate_segments, template_segments):
            for segment in pool:
                sources = segment.get("sources") or []
                if not sources or not sources[0].get("doc"):
                    continue
                doc_id = str(sources[0]["doc"])
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                ordered.append(doc_id)
        return ordered

    def _build_statistics(self, summary: dict, primary_text: str, duplicate_segments: List[dict], template_segments: List[dict]) -> str:
        total_chars = len(primary_text)
        effective_chars = int(summary.get("total_effective_chars") or 0) or self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in duplicate_segments
        ])
        template_chars = int(summary.get("total_template_chars") or 0) or self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in template_segments
        ])
        total_duplicate_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in duplicate_segments + template_segments
        ])

        cards = [
            ("总重复率", self._ratio(total_duplicate_chars, total_chars)),
            ("有效重复率", self._ratio(effective_chars, total_chars)),
            ("模板重复率", self._ratio(template_chars, total_chars)),
            ("总字数", f"{total_chars}"),
            ("重复字数", f"{total_duplicate_chars}"),
            ("有效重复字数", f"{effective_chars}"),
        ]
        return "".join(
            f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>'
            for label, value in cards
        )

    def _render_source_documents(self, texts: dict, segments: List[dict], source_docs: List[str]) -> str:
        parts: List[str] = []
        for source_doc in source_docs:
            source_text = str(texts.get(source_doc) or "")
            source_segments = [
                segment
                for segment in segments
                if str(((segment.get("sources") or [{}])[0].get("doc") or "")) == source_doc
            ]
            rendered = self._render_full_document(source_text, source_segments, side="source")
            body_html = rendered or '<div class="empty">暂无内容</div>'
            parts.append(
                f'<div class="source-doc">'
                f'<div class="source-doc-header"><span>Source</span><span>{html.escape(source_doc)}</span></div>'
                f'<div class="source-doc-body">{body_html}</div>'
                f'</div>'
            )
        return "".join(parts)

    def _render_full_document(self, text: str, segments: List[dict], side: str) -> str:
        if not text:
            return ""

        ranges = []
        for idx, segment in enumerate(segments, start=1):
            match_id = self._segment_match_id(segment, idx)
            if side == "primary":
                start = int(segment.get("primary_start", 0) or 0)
                end = int(segment.get("primary_end", 0) or 0)
            else:
                source = (segment.get("sources") or [{}])[0]
                start = int(source.get("start", 0) or 0)
                end = int(source.get("end", 0) or 0)
            if end > start:
                ranges.append((start, end, match_id))

        ranges.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        merged = self._normalize_ranges(ranges)

        line_parts: List[str] = []
        for line_no, line_start, line_end, line_text in self._split_lines(text):
            line_ranges = []
            for start, end, match_id in merged:
                if end <= line_start or start >= line_end:
                    continue
                line_ranges.append(
                    (
                        max(start, line_start) - line_start,
                        min(end, line_end) - line_start,
                        match_id,
                    )
                )
            rendered_line = self._render_line_text(line_text, line_ranges, side)
            line_parts.append(
                f'<div class="doc-row"><div class="row-no">{line_no}</div><div class="row-text">{rendered_line}</div></div>'
            )

        return f'<div class="doc-table">{"".join(line_parts)}</div>'

    def _split_lines(self, text: str) -> List[Tuple[int, int, int, str]]:
        parts = text.split("\n")
        lines: List[Tuple[int, int, int, str]] = []
        offset = 0
        for idx, line in enumerate(parts, start=1):
            start = offset
            end = start + len(line)
            lines.append((idx, start, end, line))
            offset = end + 1
        return lines

    def _render_line_text(self, line_text: str, ranges: List[Tuple[int, int, str]], side: str) -> str:
        if not line_text:
            return "&nbsp;"

        parts: List[str] = []
        cursor = 0
        for start, end, match_id in self._normalize_ranges(ranges):
            if start > cursor:
                parts.append(html.escape(line_text[cursor:start]))
            frag = html.escape(line_text[start:end])
            parts.append(f'<span class="hit" data-side="{side}" data-match-id="{match_id}">{frag}</span>')
            cursor = end
        if cursor < len(line_text):
            parts.append(html.escape(line_text[cursor:]))
        return "".join(parts)

    def _segment_match_id(self, segment: dict, idx: int) -> str:
        value = str(segment.get("match_id") or "").strip()
        return value or f"m{idx:03d}"

    def _normalize_ranges(self, ranges: List[Tuple[int, int, str]]) -> List[Tuple[int, int, str]]:
        normalized: List[Tuple[int, int, str]] = []
        last_end = -1
        for start, end, match_id in ranges:
            if start < last_end:
                start = last_end
            if end <= start:
                continue
            normalized.append((start, end, match_id))
            last_end = end
        return normalized

    def _union_length(self, ranges: List[Tuple[int, int]]) -> int:
        valid = sorted((max(0, s), max(0, e)) for s, e in ranges if e > s)
        if not valid:
            return 0
        total = 0
        cur_start, cur_end = valid[0]
        for start, end in valid[1:]:
            if start <= cur_end:
                cur_end = max(cur_end, end)
                continue
            total += cur_end - cur_start
            cur_start, cur_end = start, end
        total += cur_end - cur_start
        return total

    def _ratio(self, numerator: int, denominator: int) -> str:
        if denominator <= 0:
            return "0.00%"
        return f"{(numerator / denominator) * 100:.2f}%"
