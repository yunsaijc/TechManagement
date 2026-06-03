"""Batch HTML report index for multi-primary plagiarism results."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List


class BatchPlagiarismReportBuilder:
    """Build a direct side-by-side batch report without nested iframes."""

    _NAV_RE = re.compile(r'<div class="nav-list" id="nav-list">(?P<nav>.*?)</div>\s*</aside>', re.S)

    def _is_nonempty_group(self, group: Any) -> bool:
        if not isinstance(group, dict):
            return False
        for value in group.values():
            if value in (None, "", [], {}, 0, 0.0):
                continue
            return True
        return False

    def _valid_groups(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        groups = result.get("match_groups") or []
        return [group for group in groups if self._is_nonempty_group(group)]

    def _extract_panel_name(self, text: str, label: str) -> str:
        match = re.search(
            rf'<div class="panel-header"><span>{re.escape(label)}</span><span(?:\s[^>]*)?>(.*?)</span></div>',
            text,
            re.S,
        )
        if not match:
            return ""
        return html.unescape(match.group(1)).strip()

    def _extract_panel_body(self, text: str, panel_id: str) -> str:
        marker = f'<div id="{panel_id}" class="panel-body">'
        start = text.find(marker)
        if start < 0:
            return ""

        body_start = start + len(marker)
        depth = 1
        for match in re.finditer(r"<div\b[^>]*>|</div>", text[body_start:], re.I):
            token = match.group(0)
            if token.startswith("</div"):
                depth -= 1
            else:
                depth += 1
            if depth == 0:
                body_end = body_start + match.start()
                return text[body_start:body_end].strip()
        return ""

    def _extract_report_detail(self, report_path: Path) -> Dict[str, str]:
        text = report_path.read_text(encoding="utf-8")
        nav_match = self._NAV_RE.search(text)

        detail = {
            "primary_name": "",
            "primary_body": '<div class="docx-content"><p class="empty">无内容</p></div>',
            "source_name": "",
            "source_body": '<div class="docx-content"><p class="empty">无内容</p></div>',
            "nav_list_html": '<p class="empty">无重复片段</p>',
        }
        primary_name = self._extract_panel_name(text, "主文档")
        primary_body = self._extract_panel_body(text, "primary-panel")
        source_name = self._extract_panel_name(text, "来源文档")
        source_body = self._extract_panel_body(text, "source-panel")
        if primary_name:
            detail["primary_name"] = primary_name
        if primary_body:
            detail["primary_body"] = primary_body
        if source_name:
            detail["source_name"] = source_name
        if source_body:
            detail["source_body"] = source_body
        if nav_match:
            detail["nav_list_html"] = nav_match.group("nav").strip() or detail["nav_list_html"]
        return detail

    def _normalize_result(self, item: Dict[str, Any], idx: int) -> Dict[str, Any]:
        project = item.get("project") or {}
        item_data = item.get("data") or {}
        result = item.get("result") or item_data.get("result") or {}
        debug = item.get("debug") or {"report_html_path": item_data.get("debug_report_path")}

        file_path = str(
            item.get("file_path")
            or item_data.get("word_path")
            or project.get("file_path")
            or ""
        )
        file_name = Path(file_path).name if file_path else f"project-{idx}.docx"
        project_id = str(project.get("id") or Path(file_name).stem or f"project-{idx}")
        xmmc = str(project.get("xmmc") or file_name)
        doc_type_name = str(item.get("doc_type_name") or item.get("doc_type") or "")

        return {
            "project": {
                "id": project_id,
                "xmmc": xmmc,
                "doc_type_name": doc_type_name,
            },
            "result": result,
            "debug": debug,
        }

    def _build_project_assets(
        self,
        results: List[Dict[str, Any]],
        output_dir: Path,
        assets_dir: Path,
    ) -> tuple[List[Dict[str, Any]], int, int]:
        normalized_results = [self._normalize_result(item, idx) for idx, item in enumerate(results, 1)]
        total_groups = sum(len(self._valid_groups(item.get("result") or {})) for item in normalized_results)
        total_effective_chars = sum(int((item.get("result") or {}).get("effective_duplicate_chars") or 0) for item in normalized_results)

        project_metas: List[Dict[str, Any]] = []
        for item in normalized_results:
            project = item.get("project") or {}
            result = item.get("result") or {}
            debug = item.get("debug") or {}
            report_path_str = str(debug.get("report_html_path") or "")
            if not report_path_str:
                continue

            report_path = Path(report_path_str)
            if not report_path.exists():
                continue

            payload_index = len(project_metas)
            data_key = f"p{payload_index:03d}"
            data_file = assets_dir / f"{data_key}.js"
            rel_report = os.path.relpath(report_path, output_dir)
            rel_data_file = os.path.relpath(data_file, output_dir)
            detail = self._extract_report_detail(report_path)
            groups = self._valid_groups(result)

            payload = {
                "project_id": str(project.get("id") or f"project-{payload_index + 1}"),
                "xmmc": str(project.get("xmmc") or ""),
                "doc_type_name": str(project.get("doc_type_name") or ""),
                "match_group_count": len(groups),
                "effective_duplicate_chars": int(result.get("effective_duplicate_chars") or 0),
                "effective_duplicate_rate": float(result.get("effective_duplicate_rate") or 0),
                "duplicate_chars": int(result.get("duplicate_chars") or 0),
                "duplicate_rate": float(result.get("duplicate_rate") or 0),
                "total_chars": int(result.get("total_chars") or result.get("primary_scope_chars") or 0),
                "report_rel_path": rel_report,
                **detail,
            }
            payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
            data_file.write_text(
                "window.__BATCH_REPORT_CACHE = window.__BATCH_REPORT_CACHE || {};\n"
                f"window.__BATCH_REPORT_CACHE[{json.dumps(data_key, ensure_ascii=False)}] = {payload_json};\n",
                encoding="utf-8",
            )
            cache_bust = data_file.stat().st_mtime_ns

            project_metas.append(
                {
                    "data_key": data_key,
                    "data_js_path": f"{rel_data_file}?v={cache_bust}",
                    "project_id": payload["project_id"],
                    "xmmc": payload["xmmc"],
                    "doc_type_name": payload["doc_type_name"],
                    "match_group_count": payload["match_group_count"],
                    "effective_duplicate_chars": payload["effective_duplicate_chars"],
                    "effective_duplicate_rate": payload["effective_duplicate_rate"],
                    "duplicate_chars": payload["duplicate_chars"],
                    "duplicate_rate": payload["duplicate_rate"],
                    "total_chars": payload["total_chars"],
                    "report_rel_path": payload["report_rel_path"],
                }
            )

        return project_metas, total_groups, total_effective_chars

    def _render(
        self,
        project_metas: List[Dict[str, Any]],
        failed_projects: List[Dict[str, Any]],
        total_groups: int,
        total_effective_chars: int,
    ) -> str:
        project_buttons = [
            (
                f'<button class="project-item" type="button" data-idx="{idx}">'
                f'<div class="project-title">{html.escape(str(meta.get("xmmc") or meta.get("project_id") or "-"))}</div>'
                f'<div class="project-meta">{html.escape(str(meta.get("project_id") or "-"))} · {int(meta.get("match_group_count") or 0)} 段</div>'
                "</button>"
            )
            for idx, meta in enumerate(project_metas)
        ]

        failed_html = ""
        if failed_projects:
            failed_items = "".join(
                f"<li><strong>{html.escape(str(item.get('id') or '-'))}</strong> - {html.escape(str(item.get('xmmc') or '-'))}"
                f"<br><span>{html.escape(str(item.get('error') or '-'))}</span></li>"
                for item in failed_projects
            )
            failed_html = f"<section class=\"failed\"><h2>失败项目</h2><ul>{failed_items}</ul></section>"

        project_json = json.dumps(project_metas, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>批量查重报告</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-2: #f8fafc;
      --line: #e5e7eb;
      --line-2: rgba(148, 163, 184, 0.22);
      --ink: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --danger: #ef4444;
      --warn: #f59e0b;
      --ok: #16a34a;
      --radius: 12px;
      --shadow: 0 10px 28px rgba(15, 23, 42, 0.10);
      --compare-panel-height: clamp(480px, calc(100vh - 320px), 980px);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif; background: var(--bg); color: var(--ink); }}
    .page {{ display: grid; grid-template-columns: 300px 1fr; min-height: 100vh; gap: 12px; padding: 12px; }}
    .sidebar {{ position: sticky; top: 12px; align-self: start; max-height: calc(100vh - 24px); overflow: auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; box-shadow: var(--shadow); }}
    .sidebar h3 {{ margin: 0 0 10px; font-size: 16px; }}
    .main {{ min-width: 0; min-height: calc(100vh - 24px); display: flex; flex-direction: column; gap: 12px; }}
    .hero {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px 16px; box-shadow: var(--shadow); }}
    .hero h1 {{ margin: 0 0 6px; font-size: 22px; }}
    .stats {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .pill {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700; }}
    .project-item {{ display: block; width: 100%; text-align: left; border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; margin-bottom: 8px; background: #fff; cursor: pointer; }}
    .project-item:hover {{ border-color: #93c5fd; background: #f8fbff; }}
    .project-item.active {{ border-color: #3b82f6; background: #eff6ff; }}
    .project-title {{ font-size: 13px; font-weight: 700; margin-bottom: 4px; }}
    .project-meta {{ font-size: 11px; color: #64748b; line-height: 1.5; }}
    .detail {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; flex: 1; display: flex; flex-direction: column; min-height: 0; box-shadow: var(--shadow); }}
    .detail-header {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; padding: 4px 2px 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); }}
    .detail-title {{ font-size: 20px; font-weight: 900; }}
    .detail-sub {{ margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.6; }}
    .detail-status {{ margin-top: 6px; color: #475569; font-size: 13px; line-height: 1.6; }}
    .detail-actions {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .btn, .detail-link {{ display: inline-flex; align-items: center; justify-content: center; height: 36px; padding: 0 14px; border-radius: 10px; border: 1px solid rgba(148, 163, 184, 0.28); background: #fff; color: #0f172a; text-decoration: none; font-size: 13px; font-weight: 700; cursor: pointer; }}
    .btn:hover, .detail-link:hover {{ border-color: rgba(37, 99, 235, 0.35); background: rgba(37, 99, 235, 0.04); }}
    .btn:disabled {{ opacity: 0.55; cursor: not-allowed; }}
    .detail-stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }}
    .stat-card {{ background: var(--panel); border: 1px solid var(--line-2); border-radius: 12px; padding: 10px; }}
    .stat-label {{ font-size: 12px; color: var(--muted); font-weight: 800; }}
    .stat-value {{ margin-top: 6px; font-size: 18px; font-weight: 900; color: var(--ink); }}
    .detail-main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 320px 1fr; gap: 12px; margin-top: 12px; }}
    .match-sidebar {{ background: var(--panel); border: 1px solid var(--line-2); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); display: flex; flex-direction: column; min-height: 0; }}
    .match-top {{ padding: 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); background: var(--panel-2); }}
    .match-title {{ font-weight: 900; font-size: 14px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
    .match-counter {{ font-size: 12px; font-weight: 900; color: #334155; background: rgba(148, 163, 184, 0.12); border: 1px solid rgba(148, 163, 184, 0.22); padding: 2px 8px; border-radius: 999px; }}
    .match-search {{ width: 100%; margin-top: 10px; border: 1px solid rgba(148, 163, 184, 0.28); border-radius: 10px; padding: 9px 10px; font-size: 13px; outline: none; }}
    .match-search:focus {{ border-color: rgba(37, 99, 235, 0.45); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }}
    .filters {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }}
    .chip {{ border: 1px solid rgba(148, 163, 184, 0.28); background: #ffffff; color: #334155; border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 900; cursor: pointer; }}
    .chip.active {{ background: rgba(37, 99, 235, 0.10); border-color: rgba(37, 99, 235, 0.35); color: #1e3a8a; }}
    .nav-list {{ padding: 10px; overflow: auto; min-height: 0; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid rgba(148, 163, 184, 0.22); background: #fff; border-radius: 12px; padding: 10px; margin-bottom: 8px; cursor: pointer; font-size: 13px; transition: all 160ms ease; }}
    .nav-item:hover {{ border-color: rgba(37, 99, 235, 0.35); background: rgba(37, 99, 235, 0.04); }}
    .nav-item.active {{ border-color: rgba(239, 68, 68, 0.55); background: rgba(239, 68, 68, 0.06); }}
    .nav-item.hidden {{ display: none; }}
    .nav-header {{ font-weight: 900; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .nav-text {{ color: #334155; line-height: 1.55; margin-bottom: 6px; }}
    .nav-item small {{ display: block; color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .template-badge {{ background: var(--warn); color: white; font-size: 10px; padding: 2px 6px; border-radius: 6px; }}
    .locate-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 6px; }}
    .locate-badge.ok {{ background: var(--ok); color: #fff; }}
    .locate-badge.partial {{ background: var(--accent); color: #fff; }}
    .locate-badge.miss {{ background: #94a3b8; color: #fff; }}
    .compare-content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; align-items: stretch; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line-2); border-radius: var(--radius); display: flex; flex-direction: column; min-height: 0; height: var(--compare-panel-height); overflow: hidden; box-shadow: var(--shadow); }}
    .panel-header {{ padding: 12px 16px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); font-weight: 900; font-size: 16px; display: flex; justify-content: space-between; gap: 8px; background: var(--panel-2); }}
    .panel-header span:last-child {{ font-size: 14px; color: var(--muted); word-break: break-all; text-align: right; }}
    .panel-body {{ padding: 20px 18px 32px; overflow: auto; scroll-behavior: smooth; flex: 1; min-height: 0; background: #fff; }}
    .docx-content {{ line-height: 1.9; font-size: 16px; color: #111827; }}
    .docx-content p, .docx-content li, .docx-content td, .docx-content th, .docx-content div, .docx-content span {{ font-size: 16px; line-height: 1.9; overflow-wrap: anywhere; word-break: break-word; }}
    .docx-content h1, .docx-content h2, .docx-content h3, .docx-content h4, .docx-content h5, .docx-content h6 {{ line-height: 1.6; overflow-wrap: anywhere; word-break: break-word; }}
    .docx-content h1 {{ font-size: 1.5em; }}
    .docx-content h2 {{ font-size: 1.3em; }}
    .docx-content h3 {{ font-size: 1.15em; }}
    .docx-content table {{ display: block; width: 100%; overflow-x: auto; border-collapse: collapse; margin: 1em 0; }}
    .docx-content table td, .docx-content table th {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    .docx-content table th {{ background: #f5f5f5; font-weight: bold; }}
    .docx-content ul, .docx-content ol {{ margin: 0.5em 0; padding-left: 2em; }}
    .docx-content li {{ margin: 0.25em 0; }}
    .docx-content img {{ max-width: 100%; height: auto; }}
    .source-doc-section.hidden {{ display: none; }}
    .hit {{ background: rgba(239, 68, 68, 0.18) !important; color: #991b1b !important; border-radius: 6px; padding: 0 2px; cursor: pointer; transition: all 160ms ease; }}
    .hit.template {{ background: rgba(245, 158, 11, 0.18) !important; color: #92400e !important; }}
    .hit.paraphrase {{ background: rgba(37, 99, 235, 0.18) !important; color: #1e3a8a !important; }}
    .hit.active {{ box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18); background: rgba(239, 68, 68, 0.28) !important; }}
    .empty {{ color: #94a3b8; font-size: 13px; padding: 20px; text-align: center; }}
    .failed {{ background: #fff; border: 1px solid #fecaca; border-radius: 12px; padding: 16px; }}
    .failed h2 {{ margin-top: 0; color: #991b1b; }}
    .failed li {{ margin-bottom: 10px; }}
    @media (max-width: 1200px) {{
      .detail-main {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 960px) {{
      .page {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; max-height: none; }}
      .main {{ min-height: auto; }}
      .compare-content {{ grid-template-columns: 1fr; }}
      .detail-stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      :root {{ --compare-panel-height: 420px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <aside class="sidebar">
      <h3>项目列表</h3>
      {''.join(project_buttons) or '<div class="empty">无成功项目</div>'}
    </aside>
    <main class="main">
      <section class="hero">
        <h1>批量查重报告</h1>
        <div>当前页面直接展示每个项目的左右对比内容，不再嵌套 iframe，项目详情按需加载。</div>
        <div class="stats">
          <span class="pill">成功项目 {len(project_metas)}</span>
          <span class="pill">失败项目 {len(failed_projects)}</span>
          <span class="pill">重复段 {total_groups}</span>
          <span class="pill">有效重复字符 {total_effective_chars}</span>
        </div>
      </section>
      <section class="detail">
        <div class="detail-header">
          <div>
            <div class="detail-title" id="detail-title">未选择项目</div>
            <div class="detail-sub" id="detail-sub">请选择左侧项目查看左右对比内容。</div>
            <div class="detail-status" id="detail-status">等待加载</div>
            <div class="detail-stats">
              <div class="stat-card"><div class="stat-label">重复段数</div><div class="stat-value" id="stat-groups">0</div></div>
              <div class="stat-card"><div class="stat-label">有效重复字数</div><div class="stat-value" id="stat-effective-chars">0</div></div>
              <div class="stat-card"><div class="stat-label">有效重复率</div><div class="stat-value" id="stat-effective-rate">0.00%</div></div>
              <div class="stat-card"><div class="stat-label">检测总字数</div><div class="stat-value" id="stat-total-chars">0</div></div>
            </div>
          </div>
          <div class="detail-actions">
            <button class="btn" id="btn-prev" type="button">上一处</button>
            <button class="btn" id="btn-next" type="button">下一处</button>
            <button class="btn" id="btn-top" type="button">回到顶部</button>
            <a class="detail-link" id="detail-link" href="#" target="_blank" rel="noopener noreferrer">打开原始单项目页</a>
          </div>
        </div>
        <div class="detail-main">
          <aside class="match-sidebar">
            <div class="match-top">
              <div class="match-title">
                <span>重复片段导航</span>
                <span class="match-counter" id="nav-counter">0/0</span>
              </div>
              <input id="nav-search" class="match-search" placeholder="搜索片段关键词（支持模糊匹配）" />
              <div class="filters" id="nav-filters">
                <button class="chip active" type="button" data-filter="all">全部</button>
                <button class="chip" type="button" data-filter="effective">有效</button>
                <button class="chip" type="button" data-filter="template">模板</button>
                <button class="chip" type="button" data-filter="paraphrase">改写</button>
              </div>
            </div>
            <div class="nav-list" id="detail-nav-list">
              <p class="empty">无重复片段</p>
            </div>
          </aside>
          <section class="compare-content" id="detail-compare">
            <div class="panel">
              <div class="panel-header"><span>主文档</span><span id="primary-name">-</span></div>
              <div id="primary-panel" class="panel-body"><div class="docx-content"><p class="empty">无内容</p></div></div>
            </div>
            <div class="panel">
              <div class="panel-header"><span>来源文档</span><span id="source-name">-</span></div>
              <div id="source-panel" class="panel-body"><div class="docx-content"><p class="empty">无内容</p></div></div>
            </div>
          </section>
        </div>
      </section>
      {failed_html}
    </main>
  </div>
  <script id="project-meta" type="application/json">{project_json}</script>
  <script>
    (function() {{
      const projectMetas = JSON.parse(document.getElementById('project-meta').textContent || '[]');
      const projectButtons = Array.from(document.querySelectorAll('.project-item[data-idx]'));
      const detailTitle = document.getElementById('detail-title');
      const detailSub = document.getElementById('detail-sub');
      const detailStatus = document.getElementById('detail-status');
      const detailLink = document.getElementById('detail-link');
      const statGroups = document.getElementById('stat-groups');
      const statEffectiveChars = document.getElementById('stat-effective-chars');
      const statEffectiveRate = document.getElementById('stat-effective-rate');
      const statTotalChars = document.getElementById('stat-total-chars');
      const primaryName = document.getElementById('primary-name');
      const sourceName = document.getElementById('source-name');
      const primaryPanel = document.getElementById('primary-panel');
      const sourcePanel = document.getElementById('source-panel');
      const navList = document.getElementById('detail-nav-list');
      const navSearch = document.getElementById('nav-search');
      const navCounter = document.getElementById('nav-counter');
      const btnPrev = document.getElementById('btn-prev');
      const btnNext = document.getElementById('btn-next');
      const btnTop = document.getElementById('btn-top');
      const formatter = new Intl.NumberFormat('zh-CN');
      let currentMatchId = null;
      let highlightMap = new Map();
      let renderToken = 0;
      window.__BATCH_REPORT_CACHE = window.__BATCH_REPORT_CACHE || {{}};

      function formatPercent(value) {{
        return `${{Number(value || 0).toFixed(2)}}%`;
      }}

      function setPlaceholder(message) {{
        navList.innerHTML = '<p class="empty">' + message + '</p>';
        primaryPanel.innerHTML = '<div class="docx-content"><p class="empty">' + message + '</p></div>';
        sourcePanel.innerHTML = '<div class="docx-content"><p class="empty">' + message + '</p></div>';
        primaryName.textContent = '-';
        sourceName.textContent = '-';
      }}

      function loadProjectData(meta) {{
        return new Promise((resolve, reject) => {{
          const cache = window.__BATCH_REPORT_CACHE || {{}};
          if (cache[meta.data_key]) {{
            resolve(cache[meta.data_key]);
            return;
          }}

          const existing = document.querySelector(`script[data-batch-key="${{meta.data_key}}"]`);
          if (existing) {{
            existing.addEventListener('load', () => {{
              const loaded = (window.__BATCH_REPORT_CACHE || {{}})[meta.data_key];
              loaded ? resolve(loaded) : reject(new Error('项目数据加载后未命中缓存'));
            }}, {{ once: true }});
            existing.addEventListener('error', () => reject(new Error('项目数据脚本加载失败')), {{ once: true }});
            return;
          }}

          const script = document.createElement('script');
          script.src = meta.data_js_path;
          script.async = true;
          script.dataset.batchKey = meta.data_key;
          script.onload = () => {{
            const loaded = (window.__BATCH_REPORT_CACHE || {{}})[meta.data_key];
            script.remove();
            loaded ? resolve(loaded) : reject(new Error('项目数据加载后未命中缓存'));
          }};
          script.onerror = () => {{
            script.remove();
            reject(new Error('项目数据脚本加载失败'));
          }};
          document.body.appendChild(script);
        }});
      }}

      function findNavItem(matchId) {{
        return Array.from(document.querySelectorAll('#detail-nav-list .nav-item[data-match-id]'))
          .find(el => el.dataset.matchId === matchId) || null;
      }}

      function getMatchIds(el) {{
        return String(el.dataset.matchIds || el.dataset.matchId || '')
          .split(',')
          .map(item => item.trim())
          .filter(Boolean);
      }}

      function switchSourceDoc(sourceDoc) {{
        const sections = Array.from(sourcePanel.querySelectorAll('.source-doc-section[data-source-doc]'));
        if (!sections.length) {{
          return null;
        }}
        const target = sections.find(el => el.dataset.sourceDoc === sourceDoc) || sections[0];
        sections.forEach(el => el.classList.toggle('hidden', el !== target));
        sourceName.textContent = target.dataset.sourceName || target.dataset.sourceDoc || sourceName.textContent || '-';
        return target;
      }}

      function getVisibleNavItems() {{
        return Array.from(document.querySelectorAll('#detail-nav-list .nav-item[data-match-id]'))
          .filter(el => !el.classList.contains('hidden'));
      }}

      function refreshCounter() {{
        const items = getVisibleNavItems();
        const total = items.length;
        let idx = -1;
        if (currentMatchId) {{
          idx = items.findIndex(el => el.dataset.matchId === currentMatchId);
        }}
        navCounter.textContent = total > 0 ? `${{idx >= 0 ? idx + 1 : 0}}/${{total}}` : '0/0';
        btnPrev.disabled = total === 0;
        btnNext.disabled = total === 0;
      }}

      function activateMatch(matchId) {{
        document.querySelectorAll('#detail-compare .hit.active').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('#detail-nav-list .nav-item.active').forEach(el => el.classList.remove('active'));

        const hits = highlightMap.get(matchId) || [];
        hits.forEach(el => el.classList.add('active'));

        const navItem = findNavItem(matchId);
        if (navItem) navItem.classList.add('active');
        currentMatchId = matchId;

        const sourceDoc = navItem ? navItem.dataset.sourceDoc || '' : '';
        if (sourceDoc) {{
          switchSourceDoc(sourceDoc);
        }}
        const primaryHit = hits.find(el => el.dataset.side === 'primary') || hits[0];
        const sourceHit = hits.find(el => el.dataset.side === 'source' && (!sourceDoc || el.dataset.sourceDoc === sourceDoc));
        if (primaryHit) primaryHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        if (sourceHit) sourceHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        refreshCounter();
      }}

      function applyNavFilter() {{
        const q = (navSearch.value || '').trim().toLowerCase();
        const activeChip = document.querySelector('#nav-filters .chip.active');
        const mode = activeChip ? activeChip.dataset.filter : 'all';

        document.querySelectorAll('#detail-nav-list .nav-item').forEach(el => {{
          const text = (el.innerText || '').toLowerCase();
          const isTemplate = el.dataset.template === '1';
          const isParaphrase = el.dataset.type === 'paraphrase';
          const matchesText = !q || text.includes(q);
          const matchesMode = mode === 'all'
            || (mode === 'template' && isTemplate)
            || (mode === 'effective' && !isTemplate)
            || (mode === 'paraphrase' && isParaphrase);
          el.classList.toggle('hidden', !(matchesText && matchesMode));
        }});

        const visibleItems = getVisibleNavItems();
        if (!visibleItems.some(el => el.dataset.matchId === currentMatchId)) {{
          currentMatchId = null;
          document.querySelectorAll('#detail-compare .hit.active').forEach(el => el.classList.remove('active'));
          document.querySelectorAll('#detail-nav-list .nav-item.active').forEach(el => el.classList.remove('active'));
        }}
        refreshCounter();
      }}

      function bindDetailEvents() {{
        highlightMap = new Map();
        document.querySelectorAll('#detail-compare .hit[data-match-id]').forEach(el => {{
          const matchIds = getMatchIds(el);
          matchIds.forEach(matchId => {{
            if (!highlightMap.has(matchId)) highlightMap.set(matchId, []);
            highlightMap.get(matchId).push(el);
          }});
          const defaultMatchId = matchIds[0] || el.dataset.matchId;
          if (defaultMatchId) {{
            el.addEventListener('click', () => activateMatch(defaultMatchId));
          }}
        }});

        document.querySelectorAll('#detail-nav-list .nav-item[data-match-id]').forEach(el => {{
          el.addEventListener('click', () => activateMatch(el.dataset.matchId));
        }});
      }}

      async function renderProject(index) {{
        const meta = projectMetas[index];
        if (!meta) return;

        const token = ++renderToken;
        currentMatchId = null;
        projectButtons.forEach(btn => btn.classList.toggle('active', Number(btn.dataset.idx) === index));
        detailTitle.textContent = meta.xmmc || meta.project_id || '未命名项目';
        detailSub.textContent = `${{meta.project_id || '-'}} · ${{meta.doc_type_name || '未分类'}}`;
        detailLink.setAttribute('href', meta.report_rel_path || '#');
        statGroups.textContent = formatter.format(meta.match_group_count || 0);
        statEffectiveChars.textContent = formatter.format(meta.effective_duplicate_chars || 0);
        statEffectiveRate.textContent = formatPercent(meta.effective_duplicate_rate || 0);
        statTotalChars.textContent = formatter.format(meta.total_chars || 0);
        detailStatus.textContent = '正在加载项目内容...';
        setPlaceholder('正在加载项目内容...');
        btnPrev.disabled = true;
        btnNext.disabled = true;

        try {{
          const report = await loadProjectData(meta);
          if (token !== renderToken) return;

          primaryName.textContent = report.primary_name || '-';
          sourceName.textContent = report.source_name || '-';
          primaryPanel.innerHTML = report.primary_body || '<div class="docx-content"><p class="empty">无内容</p></div>';
          sourcePanel.innerHTML = report.source_body || '<div class="docx-content"><p class="empty">无内容</p></div>';
          navList.innerHTML = report.nav_list_html || '<p class="empty">无重复片段</p>';
          navSearch.value = '';
          document.querySelectorAll('#nav-filters .chip').forEach((chip, chipIndex) => {{
            chip.classList.toggle('active', chipIndex === 0);
          }});

          bindDetailEvents();
          applyNavFilter();
          const firstVisible = getVisibleNavItems()[0];
          if (firstVisible) {{
            activateMatch(firstVisible.dataset.matchId);
          }} else {{
            refreshCounter();
          }}
          detailStatus.textContent = '已加载完成，可直接查看左右对比内容。';
        }} catch (error) {{
          if (token !== renderToken) return;
          detailStatus.textContent = `加载失败：${{error && error.message ? error.message : '未知错误'}}`;
          setPlaceholder('项目内容加载失败');
        }}
      }}

      navSearch.addEventListener('input', applyNavFilter);
      document.querySelectorAll('#nav-filters .chip').forEach(chip => {{
        chip.addEventListener('click', () => {{
          document.querySelectorAll('#nav-filters .chip').forEach(x => x.classList.remove('active'));
          chip.classList.add('active');
          applyNavFilter();
        }});
      }});

      btnPrev.addEventListener('click', () => {{
        const items = getVisibleNavItems();
        if (!items.length) return;
        let idx = items.findIndex(el => el.dataset.matchId === currentMatchId);
        idx = idx <= 0 ? items.length - 1 : idx - 1;
        activateMatch(items[idx].dataset.matchId);
      }});

      btnNext.addEventListener('click', () => {{
        const items = getVisibleNavItems();
        if (!items.length) return;
        let idx = items.findIndex(el => el.dataset.matchId === currentMatchId);
        idx = idx < 0 || idx >= items.length - 1 ? 0 : idx + 1;
        activateMatch(items[idx].dataset.matchId);
      }});

      btnTop.addEventListener('click', () => {{
        primaryPanel.scrollTo({{ top: 0, behavior: 'smooth' }});
        sourcePanel.scrollTo({{ top: 0, behavior: 'smooth' }});
      }});

      projectButtons.forEach(btn => {{
        btn.addEventListener('click', () => renderProject(Number(btn.dataset.idx)));
      }});

      if (projectMetas.length && projectButtons.length) {{
        renderProject(0);
      }} else {{
        btnPrev.disabled = true;
        btnNext.disabled = true;
        detailStatus.textContent = '没有可显示的项目。';
      }}
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

        assets_dir = output_html_path.parent / f"{output_html_path.stem}_assets"
        if assets_dir.exists():
            shutil.rmtree(assets_dir)
        assets_dir.mkdir(parents=True, exist_ok=True)

        project_metas, total_groups, total_effective_chars = self._build_project_assets(
            results,
            output_html_path.parent,
            assets_dir,
        )
        output_html_path.write_text(
            self._render(project_metas, failed_projects, total_groups, total_effective_chars),
            encoding="utf-8",
        )
        return output_html_path
