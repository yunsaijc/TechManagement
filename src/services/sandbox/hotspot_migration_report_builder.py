"""热点迁移精简报告 HTML 生成器。"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List


class HotspotMigrationReportBuilder:
    """将 Step2 精简结果渲染为面向展示的 HTML 报告。"""

    def build_from_json_file(self, json_path: Path | str, output_html_path: Path | str) -> Path:
        json_path = Path(json_path)
        output_html_path = Path(output_html_path)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return self.build_from_payload(payload, output_html_path)

    def build_from_payload(self, payload: Dict[str, Any], output_html_path: Path | str) -> Path:
        output_html_path = Path(output_html_path)
        output_html_path.write_text(self.render_html(payload), encoding="utf-8")
        return output_html_path

    def render_html(self, payload: Dict[str, Any]) -> str:
        summary = payload.get("summary", {}) or {}
        overview = payload.get("overview", {}) or {}
        top_groups = payload.get("topGroups", {}) or {}
        key_changes = payload.get("keyChanges", []) or []
        insights = payload.get("insightDraft", []) or []
        cards = summary.get("cards", []) or []
        graph_scale = overview.get("graphScale", []) or []

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>热点变化简报</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f4f7fb; color: #0f172a; }}
    .page {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    .hero {{ background: linear-gradient(135deg, #ffffff 0%, #eef6ff 100%); border: 1px solid #d8e5f7; border-radius: 20px; padding: 24px; box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05); }}
    .title {{ font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }}
    .subtitle {{ margin-top: 8px; font-size: 13px; color: #475569; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .stat {{ background: rgba(255,255,255,0.92); border: 1px solid #dbe7f5; border-radius: 16px; padding: 14px 16px; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 6px; font-size: 24px; font-weight: 800; }}
    .section {{ margin-top: 18px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 18px; padding: 18px 20px; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04); }}
    .section-title {{ font-size: 16px; font-weight: 800; margin-bottom: 12px; }}
    .overview-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .overview-item {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; }}
    .overview-label {{ font-size: 11px; color: #64748b; }}
    .overview-value {{ margin-top: 6px; font-size: 14px; font-weight: 700; line-height: 1.6; }}
    .insight-list {{ display: grid; gap: 10px; }}
    .insight-item {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; line-height: 1.7; }}
    .two-col {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px; }}
    .card-title {{ font-size: 15px; font-weight: 800; margin-bottom: 10px; }}
    .group-list, .change-list {{ display: grid; gap: 10px; }}
    .group-item, .change-item {{ background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; }}
    .item-head {{ font-size: 14px; font-weight: 800; line-height: 1.5; }}
    .item-desc {{ margin-top: 8px; color: #334155; line-height: 1.7; font-size: 13px; }}
    .meta {{ margin-top: 8px; font-size: 12px; color: #64748b; }}
    .kw {{ display: inline-block; margin: 0 6px 6px 0; padding: 4px 8px; border-radius: 999px; background: #e9f2ff; color: #1d4ed8; font-size: 12px; }}
    .empty {{ color: #94a3b8; font-size: 13px; padding: 8px 0; }}
    @media (max-width: 1080px) {{
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .overview-grid {{ grid-template-columns: 1fr; }}
      .two-col {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 14px; }}
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="title">热点变化简报</div>
      <div class="subtitle">生成时间 {html.escape(str(payload.get("generatedAt", "")))} | 来源 {html.escape(str(payload.get("sourceOutputPath", "")))}</div>
      <div class="stats">
        {''.join(self._render_stat_card(card) for card in cards)}
      </div>
    </section>

    <section class="section">
      <div class="section-title">分析说明</div>
      <div class="overview-grid">
        {self._render_overview_item("起始年份", overview.get("startPeriod"))}
        {self._render_overview_item("对比年份", overview.get("comparisonPeriod"))}
        {self._render_overview_item("分析方法", overview.get("analysisMethod"))}
        {''.join(self._render_overview_item(item.get('label'), item.get('value')) for item in graph_scale)}
      </div>
    </section>

    <section class="section">
      <div class="section-title">结论摘要</div>
      <div class="insight-list">
        {self._render_insights(insights)}
      </div>
    </section>

    <section class="section">
      <div class="section-title">重点方向</div>
      <div class="two-col">
        {''.join(self._render_group_column(period, rows) for period, rows in top_groups.items())}
      </div>
    </section>

    <section class="section">
      <div class="section-title">重点趋势</div>
      <div class="change-list">
        {self._render_changes(key_changes)}
      </div>
    </section>
  </div>
</body>
</html>"""

    def _render_stat_card(self, card: Dict[str, Any]) -> str:
        return (
            '<div class="stat">'
            f'<div class="stat-label">{html.escape(str(card.get("label", "-")))}</div>'
            f'<div class="stat-value">{html.escape(str(card.get("value", "-")))}</div>'
            '</div>'
        )

    def _render_overview_item(self, label: Any, value: Any) -> str:
        return (
            '<div class="overview-item">'
            f'<div class="overview-label">{html.escape(str(label if label is not None else "-"))}</div>'
            f'<div class="overview-value">{html.escape(str(value if value is not None else "-"))}</div>'
            '</div>'
        )

    def _render_insights(self, insights: List[Any]) -> str:
        if not insights:
            return '<div class="empty">暂无结论摘要</div>'
        return "".join(
            f'<div class="insight-item">{html.escape(str(item))}</div>'
            for item in insights
        )

    def _render_group_column(self, period: str, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            body = '<div class="empty">暂无重点方向</div>'
        else:
            body = "".join(self._render_group_item(row) for row in rows)
        return (
            '<div class="card">'
            f'<div class="card-title">{html.escape(str(period))}</div>'
            f'<div class="group-list">{body}</div>'
            '</div>'
        )

    def _render_group_item(self, row: Dict[str, Any]) -> str:
        keywords = row.get("keywords", []) or []
        kw_html = "".join(f'<span class="kw">{html.escape(str(item))}</span>' for item in keywords)
        meta = f"排序第 {int(row.get('rank', 0) or 0)}，约 {int(row.get('projectCount', 0) or 0)} 个项目"
        return (
            '<div class="group-item">'
            f'<div class="item-head">{html.escape(str(row.get("name", "-")))}</div>'
            f'<div class="meta">{html.escape(meta)}</div>'
            f'<div class="item-desc">{html.escape(str(row.get("description", "")))}</div>'
            f'<div style="margin-top: 8px;">{kw_html}</div>'
            '</div>'
        )

    def _render_changes(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return '<div class="empty">暂无重点趋势</div>'
        return "".join(self._render_change_item(row) for row in rows)

    def _render_change_item(self, row: Dict[str, Any]) -> str:
        head = f"{row.get('rank', '-')}. 由“{row.get('from', '-')}”到“{row.get('to', '-')}”"
        return (
            '<div class="change-item">'
            f'<div class="item-head">{html.escape(head)}</div>'
            f'<div class="item-desc">{html.escape(str(row.get("description", "")))}</div>'
            '</div>'
        )
