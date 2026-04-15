"""专家匹配 HTML 报告生成器。"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List


class MatchingReportBuilder:
    """将专家匹配结果渲染为适配当前业务的 HTML 报告。"""

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
        run_config = payload.get("run_config", {}) or {}
        results = payload.get("results", []) or []

        project_cards = [self._render_project_card(idx, item) for idx, item in enumerate(results, start=1)]

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>专家匹配报告</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f3f6fb; color: #0f172a; }}
    .page {{ max-width: 1360px; margin: 0 auto; padding: 24px; }}
    .hero {{ background: linear-gradient(135deg, #ffffff 0%, #eef4ff 100%); border: 1px solid #dbe7ff; border-radius: 20px; padding: 24px; box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06); }}
    .title {{ font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }}
    .subtitle {{ margin-top: 8px; font-size: 13px; color: #475569; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 20px; }}
    .stat {{ background: rgba(255, 255, 255, 0.82); border: 1px solid #dbe7ff; border-radius: 16px; padding: 14px 16px; }}
    .stat-label {{ font-size: 12px; color: #475569; }}
    .stat-value {{ margin-top: 8px; font-size: 24px; font-weight: 800; color: #0f172a; }}
    .section {{ margin-top: 18px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 18px; padding: 18px 20px; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04); }}
    .section-title {{ font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 12px; }}
    .config-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }}
    .config-item {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 12px; }}
    .config-label {{ font-size: 11px; color: #64748b; }}
    .config-value {{ margin-top: 6px; font-size: 15px; font-weight: 700; }}
    .cards {{ display: grid; gap: 16px; margin-top: 18px; }}
    .card {{ background: #ffffff; border: 1px solid #e2e8f0; border-radius: 18px; overflow: hidden; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04); }}
    .card-header {{ padding: 18px 20px; background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }}
    .card-title {{ font-size: 18px; font-weight: 800; color: #0f172a; }}
    .card-meta {{ margin-top: 8px; font-size: 12px; color: #64748b; display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ background: #e8f0ff; color: #1d4ed8; border-radius: 999px; padding: 6px 10px; font-size: 12px; white-space: nowrap; }}
    .body {{ padding: 18px 20px 20px; }}
    .query {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; font-size: 13px; color: #334155; }}
    .query-label {{ color: #64748b; margin-right: 8px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }}
    .mini-stat {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; }}
    .mini-label {{ font-size: 11px; color: #64748b; }}
    .mini-value {{ margin-top: 6px; font-size: 18px; font-weight: 800; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
    th, td {{ text-align: left; padding: 12px 10px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
    th {{ color: #475569; background: #f8fafc; font-size: 12px; }}
    tr:hover td {{ background: #fbfdff; }}
    .expert-name {{ font-weight: 700; color: #0f172a; }}
    .expert-id {{ margin-top: 4px; font-size: 11px; color: #64748b; }}
    .empty {{ padding: 20px; text-align: center; color: #94a3b8; font-size: 13px; }}
    @media (max-width: 1100px) {{
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .config-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 760px) {{
      .page {{ padding: 14px; }}
      .card-header {{ flex-direction: column; }}
      .stats {{ grid-template-columns: 1fr; }}
      .config-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="title">专家匹配报告</div>
      <div class="subtitle">生成时间 {html.escape(str(payload.get("generated_at", "")))} | group_id {html.escape(str(payload.get("group_id", "")))}</div>
      <div class="stats">
        <div class="stat"><div class="stat-label">项目总数</div><div class="stat-value">{int(summary.get("project_count", 0) or 0)}</div></div>
        <div class="stat"><div class="stat-label">已匹配项目</div><div class="stat-value">{int(summary.get("matched_project_count", 0) or 0)}</div></div>
        <div class="stat"><div class="stat-label">未匹配项目</div><div class="stat-value">{int(summary.get("unmatched_project_count", 0) or 0)}</div></div>
        <div class="stat"><div class="stat-label">平均 Top1 分</div><div class="stat-value">{float(summary.get("avg_top1_score", 0.0) or 0.0):.2f}</div></div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">运行参数</div>
      <div class="config-grid">
        {self._render_config_item("top_k", run_config.get("top_k"))}
        {self._render_config_item("expert_limit", run_config.get("expert_limit"))}
        {self._render_config_item("llm_candidate_limit", run_config.get("llm_candidate_limit"))}
        {self._render_config_item("search_timeout", run_config.get("search_timeout"))}
        {self._render_config_item("max_concurrency", run_config.get("max_concurrency"))}
        {self._render_config_item("max_llm_concurrency", run_config.get("max_llm_concurrency"))}
      </div>
    </section>

    <section class="cards">
      {"".join(project_cards) if project_cards else '<div class="empty">暂无匹配结果</div>'}
    </section>
  </div>
</body>
</html>"""

    def _render_config_item(self, label: str, value: Any) -> str:
        return (
            '<div class="config-item">'
            f'<div class="config-label">{html.escape(str(label))}</div>'
            f'<div class="config-value">{html.escape(str(value if value is not None else "-"))}</div>'
            '</div>'
        )

    def _render_project_card(self, idx: int, item: Dict[str, Any]) -> str:
        top_experts = item.get("top_experts", []) or []
        top1_score = float(top_experts[0].get("match_score", 0.0) or 0.0) if top_experts else 0.0
        avg_score = (
            sum(float(expert.get("match_score", 0.0) or 0.0) for expert in top_experts) / len(top_experts)
            if top_experts else 0.0
        )

        expert_rows = [self._render_expert_row(rank, expert) for rank, expert in enumerate(top_experts, start=1)]

        return f"""
        <article class="card">
          <div class="card-header">
            <div>
              <div class="card-title">#{idx} {html.escape(str(item.get("project_title", "") or item.get("project_id", "")))}</div>
              <div class="card-meta">
                <span>project_id: {html.escape(str(item.get("project_id", "")))}</span>
                <span>subject: {html.escape(str(item.get("subject_name", "") or "-"))}</span>
              </div>
            </div>
            <div class="pill">候选专家数 {int(item.get("expert_count", 0) or 0)}</div>
          </div>
          <div class="body">
            <div class="query"><span class="query-label">检索词</span>{html.escape(str(item.get("query_text", "") or "-"))}</div>
            <div class="summary-grid">
              <div class="mini-stat"><div class="mini-label">Top-K 数量</div><div class="mini-value">{len(top_experts)}</div></div>
              <div class="mini-stat"><div class="mini-label">Top1 分数</div><div class="mini-value">{top1_score:.2f}</div></div>
              <div class="mini-stat"><div class="mini-label">Top-K 平均分</div><div class="mini-value">{avg_score:.2f}</div></div>
            </div>
            {self._render_expert_table(expert_rows)}
          </div>
        </article>
        """

    def _render_expert_row(self, rank: int, expert: Dict[str, Any]) -> str:
        return (
            "<tr>"
            f"<td>{rank}</td>"
            f"<td><div class=\"expert-name\">{html.escape(str(expert.get('expert_name', '')))}</div>"
            f"<div class=\"expert-id\">ID: {html.escape(str(expert.get('expert_id', '')))}</div></td>"
            f"<td>{float(expert.get('match_score', 0.0) or 0.0):.2f}</td>"
            "</tr>"
        )

    def _render_expert_table(self, rows: List[str]) -> str:
        if not rows:
            return '<div class="empty">未匹配到专家</div>'
        return (
            "<table>"
            "<thead><tr><th>#</th><th>专家</th><th>匹配分</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
