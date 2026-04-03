"""Batch HTML report index for multi-primary plagiarism results."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any, Dict, List


class BatchPlagiarismReportBuilder:
    """Build an index page that reuses original per-project mammoth reports."""

    def _render(
        self,
        results: List[Dict[str, Any]],
        failed_projects: List[Dict[str, Any]],
        output_dir: Path,
    ) -> str:
        total_groups = sum(len((item.get("result") or {}).get("match_groups") or []) for item in results)
        total_effective_chars = sum(int((item.get("result") or {}).get("effective_duplicate_chars") or 0) for item in results)

        nav_items: List[str] = []
        first_report = ""
        for idx, item in enumerate(results, 1):
            project = item.get("project") or {}
            result = item.get("result") or {}
            debug = item.get("debug") or {}
            report_path = str(debug.get("report_html_path") or "")
            if not report_path:
                continue
            rel_report = os.path.relpath(report_path, output_dir)
            if not first_report:
                first_report = rel_report
            project_id = str(project.get("id") or f"project-{idx}")
            xmmc = str(project.get("xmmc") or project_id)
            groups = result.get("match_groups") or []
            nav_items.append(
                f'<button class="nav-item" data-report="{html.escape(rel_report)}">'
                f'<div class="nav-title">{html.escape(xmmc)}</div>'
                f'<div class="nav-meta">{html.escape(project_id)} · {len(groups)} 段</div>'
                "</button>"
            )

        failed_html = ""
        if failed_projects:
            failed_items = "".join(
                f"<li><strong>{html.escape(str(item.get('id') or '-'))}</strong> - {html.escape(str(item.get('xmmc') or '-'))}"
                f"<br><span>{html.escape(str(item.get('error') or '-'))}</span></li>"
                for item in failed_projects
            )
            failed_html = f"<section class=\"failed\"><h2>失败项目</h2><ul>{failed_items}</ul></section>"

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>批量查重报告</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif; background: #f5f7fb; color: #1f2937; }}
    .page {{ display: grid; grid-template-columns: 300px 1fr; min-height: 100vh; gap: 12px; padding: 12px; }}
    .sidebar {{ position: sticky; top: 12px; align-self: start; max-height: calc(100vh - 24px); overflow: auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; }}
    .main {{ min-width: 0; display: flex; flex-direction: column; gap: 12px; }}
    .hero {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; }}
    .hero h1 {{ margin: 0 0 8px; font-size: 22px; }}
    .stats {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .pill {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .nav-item {{ display: block; width: 100%; text-align: left; border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; margin-bottom: 8px; background: #fff; cursor: pointer; }}
    .nav-item:hover {{ border-color: #93c5fd; background: #f8fbff; }}
    .nav-item.active {{ border-color: #3b82f6; background: #eff6ff; }}
    .nav-title {{ font-size: 13px; font-weight: 700; margin-bottom: 4px; }}
    .nav-meta {{ font-size: 11px; color: #64748b; line-height: 1.5; }}
    .viewer-wrap {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 10px; min-height: 70vh; }}
    .viewer {{ width: 100%; height: calc(100vh - 220px); border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }}
    .empty {{ color: #94a3b8; font-size: 12px; }}
    .failed {{ background: #fff; border: 1px solid #fecaca; border-radius: 12px; padding: 16px; }}
    .failed h2 {{ margin-top: 0; color: #991b1b; }}
    .failed li {{ margin-bottom: 10px; }}
  </style>
</head>
<body>
  <div class="page">
    <aside class="sidebar">
      <h3>Primary 文档</h3>
      {''.join(nav_items) or '<div class="empty">无成功项目</div>'}
    </aside>
    <main class="main">
      <section class="hero">
        <h1>批量查重报告</h1>
        <div>右侧直接复用原来的单项目报告页面（高亮和跳转逻辑保持原样）。</div>
        <div class="stats">
          <span class="pill">成功项目 {len(results)}</span>
          <span class="pill">失败项目 {len(failed_projects)}</span>
          <span class="pill">重复段 {total_groups}</span>
          <span class="pill">有效重复字符 {total_effective_chars}</span>
        </div>
      </section>
      <section class="viewer-wrap">
        <iframe id="report-frame" class="viewer" src="{html.escape(first_report)}"></iframe>
      </section>
      {failed_html}
    </main>
  </div>
  <script>
    (function() {{
      const buttons = Array.from(document.querySelectorAll('.nav-item[data-report]'));
      const frame = document.getElementById('report-frame');
      if (!buttons.length || !frame) return;
      function activate(btn) {{
        buttons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const path = btn.getAttribute('data-report') || '';
        frame.setAttribute('src', path);
      }}
      buttons.forEach(btn => btn.addEventListener('click', () => activate(btn)));
      activate(buttons[0]);
    }})();
  </script>
</body>
</html>"""

    def build(
        self,
        results: List[Dict[str, Any]],
        failed_projects: List[Dict[str, Any]],
        output_html_path: Path | str,
    ) -> Path:
        output_html_path = Path(output_html_path)
        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        output_html_path.write_text(
            self._render(results, failed_projects, output_html_path.parent),
            encoding="utf-8",
        )
        return output_html_path
