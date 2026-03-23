"""查重 HTML 报告生成器。"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, List, Tuple


class PlagiarismHtmlReportBuilder:
    """基于 debug JSON 生成可离线查看的双栏查重 HTML 报告。"""

    def build_from_debug_file(self, debug_json_path: Path, output_html_path: Path) -> Path:
        data = json.loads(debug_json_path.read_text(encoding="utf-8"))
        html_content = self.build_html(data)
        output_html_path.write_text(html_content, encoding="utf-8")
        return output_html_path

    def build_html(self, data: dict) -> str:
        primary_doc = data.get("primary_doc", "主文档")
        duplicate_segments = data.get("duplicate_segments", []) or []
        template_segments = data.get("template_segments", []) or []
        summary = data.get("summary", {}) or {}
        texts = data.get("documents", {}) or {}
        primary_text = texts.get(primary_doc, "")

        source_doc = self._pick_source_doc(duplicate_segments, template_segments)
        source_text = texts.get(source_doc, "")

        stats = self._build_statistics(summary, primary_text, duplicate_segments, template_segments)
        left_html = self._render_full_document(primary_text, duplicate_segments, side="primary")
        right_html = self._render_full_document(source_text, duplicate_segments, side="source")
        match_cards = self._build_match_nav(duplicate_segments)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>查重可视化报告 - {html.escape(primary_doc)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fb; color: #1f2937; }}
    .page {{ height: 100vh; display: flex; flex-direction: column; }}
    .toolbar {{ position: sticky; top: 0; z-index: 20; background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 14px 18px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
    .title {{ font-size: 18px; font-weight: 700; }}
    .meta {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 280px 1fr; gap: 12px; padding: 12px; }}
    .sidebar {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; overflow: auto; }}
    .content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; }}
    .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; display: flex; flex-direction: column; min-height: 0; }}
    .panel-header {{ padding: 12px 14px; border-bottom: 1px solid #e5e7eb; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; }}
    .panel-body {{ padding: 12px; overflow: auto; scroll-behavior: smooth; }}
    .doc-text {{ line-height: 1.9; font-size: 14px; white-space: pre-wrap; word-break: break-word; }}
    .hit {{ background: rgba(239, 68, 68, .18); color: #991b1b; border-radius: 4px; padding: 0 1px; cursor: pointer; transition: all .15s ease; }}
    .hit.template {{ background: rgba(245, 158, 11, .18); color: #92400e; }}
    .hit.active {{ background: rgba(220, 38, 38, .34); box-shadow: 0 0 0 2px rgba(220,38,38,.12); }}
    .nav-title {{ font-weight: 700; margin-bottom: 10px; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 10px; margin-bottom: 8px; cursor: pointer; }}
    .nav-item:hover {{ border-color: #fca5a5; background: #fff5f5; }}
    .nav-item small {{ display: block; color: #6b7280; margin-top: 4px; }}
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
        <div class="title">查重可视化报告</div>
        <div style="font-size: 13px; color: #6b7280; margin-top: 4px;">左侧主文档：{html.escape(primary_doc)} ｜ 右侧来源文档：{html.escape(source_doc)}</div>
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
          <div class="panel-header"><span>Source</span><span>{html.escape(source_doc)}</span></div>
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
            match_id = f"m{idx:03d}"
            source = (segment.get("sources") or [{}])[0]
            similarity = segment.get("similarity_score", 0)
            primary_line = segment.get("primary_line", 0)
            source_line = source.get("line", 0)
            nav_parts.append(
              f'<button class="nav-item" data-match-id="{match_id}">#{idx} <small>Primary L{primary_line} → Source L{source_line} ｜ 相似度 {similarity}</small></button>'
            )

        return "".join(nav_parts)

    def _pick_source_doc(self, duplicate_segments: List[dict], template_segments: List[dict]) -> str:
        for pool in (duplicate_segments, template_segments):
            for segment in pool:
                sources = segment.get("sources") or []
                if sources and sources[0].get("doc"):
                    return sources[0]["doc"]
        return "来源文档"

    def _build_statistics(self, summary: dict, primary_text: str, duplicate_segments: List[dict], template_segments: List[dict]) -> str:
        total_chars = len(primary_text)
        effective_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in duplicate_segments
        ])
        template_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in template_segments
        ])
        total_duplicate_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in duplicate_segments + template_segments
        ])

        total_rate = self._ratio(total_duplicate_chars, total_chars)
        effective_rate = self._ratio(effective_chars, total_chars)
        template_rate = self._ratio(template_chars, total_chars)

        cards = [
            ("总重复率", total_rate),
            ("有效重复率", effective_rate),
            ("模板重复率", template_rate),
            ("总字数", f"{total_chars}"),
            ("重复字数", f"{total_duplicate_chars}"),
            ("有效重复字数", f"{effective_chars}"),
        ]
        return "".join(
            f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>'
            for label, value in cards
        )

    def _render_full_document(self, text: str, segments: List[dict], side: str) -> str:
        if not text:
            return ""

        ranges = []
        for idx, segment in enumerate(segments, start=1):
            match_id = f"m{idx:03d}"
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

        parts: List[str] = []
        cursor = 0
        for start, end, match_id in merged:
            if start > cursor:
                parts.append(html.escape(text[cursor:start]))
            frag = html.escape(text[start:end])
            parts.append(f'<span class="hit" data-side="{side}" data-match-id="{match_id}">{frag}</span>')
            cursor = end
        if cursor < len(text):
            parts.append(html.escape(text[cursor:]))
        return f'<div class="doc-text">{"".join(parts)}</div>'

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