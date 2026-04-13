"""
评审 HTML 报告生成器

负责将 EvaluationResult 渲染为正式报告与调试报告。
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import fitz

from src.services.evaluation.parsers import DocumentParser
from src.services.evaluation.packet_builder import EvaluationPacketBuilder
from src.services.evaluation.storage.project_repo import EvaluationProjectRepository


class ReportGenerator:
    """评审报告生成器"""

    SECTION_PREVIEW_SKIP_PATTERNS = [
        r"附件",
        r"预算",
        r"费用",
        r"财政资金",
        r"自筹资金",
        r"直接费用",
        r"间接费用",
        r"项目组主要成员",
        r"项目团队",
        r"项目基本信息",
        r"基地负责人",
    ]
    SECTION_PREVIEW_DROP_LINE_PATTERNS = [
        r"^\[表格(?:行|表头)\d+\]",
        r"^（?包括.+限\d+.*[）)]$",
        r"^围绕.+限\d+.*$",
        r"^具体内容应包括.+$",
        r"^每项创新点的描述限\d+.*$",
        r"^主要指标：?$",
        r"^核心建设内容：?$",
    ]
    SECTION_PREVIEW_INLINE_HEADINGS = [
        "背景与意义",
        "建设目标",
        "实施内容",
        "创新亮点",
        "预期效益",
        "项目效益",
        "实施地点",
        "目的",
        "意义",
    ]
    PROJECT_NAME_PATTERNS = [
        r"项\s*目\s*名\s*称\s*[：:]\s*(.+?)(?:申\s*报\s*单\s*位|承\s*担\s*单\s*位|合\s*作\s*单\s*位|项目负责人|$)",
        r"项目名称\s*\|\s*(.+?)\s*\|\s*所属专项",
        r"项目名称\s+(.+?)\s+所属专项",
    ]

    def build_from_debug_file(
        self,
        debug_json_path: Path | str,
        output_html_path: Path | str,
        debug_mode: bool = False,
    ) -> Path:
        """根据 debug JSON 生成 HTML 报告"""
        debug_json = Path(debug_json_path)
        output_html = Path(output_html_path)
        data = json.loads(debug_json.read_text(encoding="utf-8"))
        if not debug_mode:
            data["_workspace_projects"] = self._collect_workspace_projects(
                debug_dir=debug_json.parent,
                current_stem=debug_json.stem,
            )
        updated = self._ensure_page_chunks(data)
        updated = self._ensure_packet_assets(data, debug_json.parent) or updated
        if updated:
            debug_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        output_html.write_text(self.build_html(data, debug_mode=debug_mode), encoding="utf-8")
        return output_html

    def _collect_workspace_projects(self, debug_dir: Path, current_stem: str) -> List[Dict[str, Any]]:
        """收集同目录下可切换的项目列表，供单项目工作台左侧项目栏使用"""
        projects: List[Dict[str, Any]] = []
        for path in sorted(debug_dir.glob("EVAL_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            result = payload.get("result") or {}
            if not isinstance(result, dict):
                continue
            project_id = str(result.get("project_id") or payload.get("project_id") or path.stem)
            project_name = self._extract_project_name_from_payload(payload) or str(
                result.get("project_name")
                or payload.get("project_name")
                or payload.get("source_name")
                or project_id
            )
            projects.append(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "score": result.get("overall_score"),
                    "grade": result.get("grade"),
                    "html_file": f"{path.stem}.html",
                    "active": path.stem == current_stem,
                }
            )
        return projects

    def _ensure_page_chunks(self, data: Dict[str, Any]) -> bool:
        """兼容旧 debug JSON，缺少 page_chunks 时尝试回源补齐"""
        page_chunks = data.get("page_chunks")
        if isinstance(page_chunks, list) and page_chunks:
            return False

        meta = data.get("meta") or {}
        if not isinstance(meta, dict):
            return False

        file_path = str(meta.get("file_path") or "").strip()
        if not file_path or not os.path.exists(file_path):
            return False

        source_name = str(data.get("source_name") or meta.get("file_name") or os.path.basename(file_path))
        parser = DocumentParser()
        parsed = asyncio.run(parser.parse(file_path, source_name=source_name))
        recovered_chunks = parsed.get("page_chunks") or []
        if not recovered_chunks:
            return False

        data["page_chunks"] = recovered_chunks
        recovered_meta = parsed.get("meta") or {}
        if isinstance(recovered_meta, dict):
            merged_meta = dict(meta)
            merged_meta.update(recovered_meta)
            data["meta"] = merged_meta
        return True

    def _ensure_packet_assets(self, data: Dict[str, Any], debug_dir: Path) -> bool:
        """兼容旧 debug JSON，缺少 packet 资产时尝试回源补齐"""
        packet_assets = data.get("packet_assets")
        if isinstance(packet_assets, dict):
            viewer_file = str(packet_assets.get("viewer_file") or "").strip()
            packet_file = str(packet_assets.get("packet_file") or "").strip()
            if viewer_file and packet_file and (debug_dir / viewer_file).exists() and (debug_dir / packet_file).exists():
                return False

        meta = data.get("meta") or {}
        if not isinstance(meta, dict):
            return False
        source_file = str(meta.get("file_path") or "").strip()
        if not source_file or not os.path.exists(source_file):
            return False

        attachments = data.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        result = data.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        project_id = str(data.get("project_id") or result.get("project_id") or "").strip()
        if not attachments:
            attachment_files = meta.get("attachment_files") or []
            if isinstance(attachment_files, list) and attachment_files:
                attachments = [
                    {
                        "file_ref": str(path),
                        "file_name": Path(str(path)).name,
                        "doc_kind": "",
                    }
                    for path in attachment_files
                    if str(path).strip()
                ]
            elif project_id:
                try:
                    repo = EvaluationProjectRepository()
                    attachment_files = repo.get_attachment_file_paths(project_id)
                except Exception:
                    attachment_files = []
                attachments = [
                    {
                        "file_ref": str(path),
                        "file_name": Path(str(path)).name,
                        "doc_kind": "",
                    }
                    for path in attachment_files
                    if str(path).strip()
                ]
            if attachments:
                data["attachments"] = attachments

        packet_builder = EvaluationPacketBuilder()
        packet_assets = packet_builder.build(
            output_dir=debug_dir,
            project_id=project_id or "manual",
            source_file=source_file,
            source_name=str(data.get("source_name") or meta.get("file_name") or Path(source_file).name),
            attachments=attachments,
        )
        if not packet_assets:
            return False
        data["packet_assets"] = packet_assets
        return True

    def build_html(self, data: Dict[str, Any], debug_mode: bool = False) -> str:
        """构建 HTML 页面"""
        result = data.get("result", {})
        highlights = result.get("highlights") or {}
        dimension_scores = result.get("dimension_scores") or []
        recommendations = result.get("recommendations") or []
        evidence = result.get("evidence") or []
        errors = result.get("errors") or []
        industry_fit = result.get("industry_fit")
        benchmark = result.get("benchmark")
        sections = data.get("sections") or {}
        page_chunks = data.get("page_chunks") or []
        packet_assets = data.get("packet_assets") or {}
        expert_qna = data.get("expert_qna") or []
        workspace_projects = data.get("_workspace_projects") or []
        evidence_map = self._build_evidence_map(evidence)
        evaluation_id = str(result.get("evaluation_id") or "")

        score = result.get("overall_score", 0)
        grade = result.get("grade", "-")
        title = self._extract_project_name_from_payload(data) or result.get("project_name") or result.get("project_id") or "评审报告"
        score_class = self._score_class(score)
        report_title = "项目智能评审报告" if not debug_mode else "项目评审调试报告"
        left_tail = ""
        right_tail = ""
        source_name = data.get("source_name") or data.get("meta", {}).get("file_name") or "-"
        project_nav = self._render_project_nav(workspace_projects, debug_mode)
        document_panel = self._render_document_panel(page_chunks, data.get("meta") or {}, packet_assets, debug_mode)
        layout_class = "content-grid debug-layout" if debug_mode else "content-grid workspace-layout"

        if debug_mode:
            left_tail = f"""
        <section class="panel">
          <div class="panel-inner">
            <h2>解析章节预览</h2>
            <div class="section-preview">
              {self._render_sections(sections)}
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-inner">
            <h2>调试元信息</h2>
            <table class="kv-table">
              <tr><th>项目ID</th><td>{html.escape(str(result.get("project_id") or "-"))}</td></tr>
              <tr><th>评审ID</th><td>{html.escape(str(result.get("evaluation_id") or "-"))}</td></tr>
              <tr><th>源文件</th><td>{html.escape(str(source_name))}</td></tr>
              <tr><th>生成时间</th><td>{html.escape(str(result.get("created_at") or "-"))}</td></tr>
            </table>
          </div>
        </section>
            """
            right_tail = f"""
        <section class="panel" id="report-debug">
          <div class="panel-inner">
            <h2>错误与调试信息</h2>
            {self._render_errors(errors, data.get("meta") or {})}
          </div>
        </section>
            """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>正文评审报告 - {html.escape(str(title))}</title>
  <style>
    :root {{
      --bg: #f3f5f7;
      --panel: #ffffff;
      --panel-soft: #f7f9fb;
      --panel-deep: #eef3f8;
      --ink: #1b2430;
      --muted: #66758a;
      --line: #d7dfe8;
      --brand: #1d3c61;
      --brand-soft: #e8eff6;
      --ok: #1f7a4d;
      --warn: #a56a1f;
      --risk: #b42318;
      --shadow: 0 8px 24px rgba(18, 31, 53, 0.05);
    }}
    * {{
      box-sizing: border-box;
      min-width: 0;
    }}
    html {{
      scroll-behavior: smooth;
      height: 100%;
    }}
    body {{
      margin: 0;
      height: 100%;
      overflow: hidden;
      font-family: "Source Han Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    a {{
      color: inherit;
    }}
    .page {{
      max-width: 1760px;
      width: 100%;
      margin: 0 auto;
      padding: 20px;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    .page-stack {{
      display: grid;
      gap: 20px;
      height: 100%;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 14px 18px;
      background: linear-gradient(180deg, #fbfcfd 0%, #f4f7fa 100%);
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      flex-wrap: nowrap;
    }}
    .report-title {{
      margin: 0;
      font-size: 18px;
      line-height: 1.3;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .report-subtitle {{
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.4;
    }}
    .score-card {{
      min-width: 132px;
      padding: 8px 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      flex-shrink: 0;
    }}
    .score-good {{
      border-color: rgba(31, 122, 77, 0.28);
    }}
    .score-mid {{
      border-color: rgba(165, 106, 31, 0.28);
    }}
    .score-bad {{
      border-color: rgba(180, 35, 24, 0.28);
    }}
    .score-label {{
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 4px;
    }}
    .score-main {{
      display: flex;
      align-items: baseline;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .score-value {{
      font-size: 28px;
      line-height: 1;
      font-weight: 800;
    }}
    .score-grade {{
      font-size: 16px;
      font-weight: 700;
      color: var(--brand);
    }}
    .nav-link {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 11px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel);
      font-size: 12px;
      font-weight: 600;
      text-decoration: none;
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .nav-link:hover {{
      border-color: #bfd0e3;
      background: var(--brand-soft);
      color: var(--brand);
    }}
    .content-grid {{
      display: grid;
      gap: 20px;
      align-items: stretch;
      min-height: 0;
      height: 100%;
    }}
    .workspace-layout {{
      grid-template-columns: 150px minmax(0, 1.55fr) minmax(430px, 1.08fr);
    }}
    .debug-layout {{
      grid-template-columns: minmax(0, 1fr) 360px;
    }}
    .project-stack,
    .nav-stack,
    .main-stack,
    .side-stack {{
      display: grid;
      gap: 18px;
      min-height: 0;
      height: 100%;
      overflow: hidden;
      padding-right: 6px;
      max-height: 100%;
    }}
    .side-stack {{
      padding-right: 2px;
    }}
    .project-stack {{
      padding-right: 0;
    }}
    .nav-stack {{
      padding-right: 0;
    }}
    .project-panel {{
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    .project-panel-inner {{
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 14px;
    }}
    .project-panel-title {{
      font-size: 15px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .project-list {{
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
      display: grid;
      gap: 8px;
      align-content: start;
    }}
    .project-link {{
      display: grid;
      gap: 6px;
      padding: 10px 11px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
      color: inherit;
      text-decoration: none;
    }}
    .project-link:hover,
    .project-link.is-active {{
      border-color: #9eb6cf;
      background: #edf3f8;
      color: var(--brand);
    }}
    .project-link-title {{
      font-size: 13px;
      font-weight: 700;
      line-height: 1.55;
      word-break: break-word;
    }}
    .project-link-meta {{
      color: var(--muted);
      font-size: 11px;
      line-height: 1.6;
      word-break: break-all;
    }}
    .project-link-score {{
      color: var(--muted);
      font-size: 11px;
      line-height: 1.6;
    }}
    .rail-panel {{
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    .rail-inner {{
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      gap: 14px;
    }}
    .rail-title {{
      font-size: 15px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .rail-meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.7;
    }}
    .rail-group {{
      display: grid;
      gap: 8px;
      align-content: start;
    }}
    .rail-group-title {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .rail-scroll {{
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
      display: grid;
      gap: 14px;
      align-content: start;
    }}
    .rail-links {{
      display: grid;
      gap: 8px;
    }}
    .rail-link {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
      color: inherit;
      text-decoration: none;
      font-size: 13px;
      line-height: 1.6;
    }}
    .rail-link:hover,
    .rail-link.is-active {{
      border-color: #9eb6cf;
      background: #edf3f8;
      color: var(--brand);
    }}
    .rail-link-label {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .rail-link-meta {{
      color: var(--muted);
      font-size: 12px;
      flex-shrink: 0;
    }}
    .doc-panel {{
      height: 100%;
      min-height: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: minmax(0, 1fr);
    }}
    .doc-panel-inner {{
      height: 100%;
      min-height: 0;
      display: grid;
      grid-template-rows: minmax(0, 1fr);
    }}
    .doc-viewer {{
      min-height: 0;
      overflow: auto;
      padding-right: 2px;
      display: grid;
      gap: 14px;
      align-content: start;
    }}
    .packet-frame {{
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      border-radius: 14px;
      background: #dfe5ec;
    }}
    .doc-page {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: linear-gradient(180deg, #fff 0%, #fbfcfe 100%);
      padding: 18px;
      box-shadow: var(--shadow);
      scroll-margin-top: 18px;
    }}
    .doc-page.is-active {{
      border-color: #88a4c3;
      box-shadow: 0 0 0 3px rgba(29, 60, 97, 0.12);
    }}
    .doc-page-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }}
    .doc-page-title {{
      font-size: 17px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .doc-page-sub {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }}
    .doc-chunk-list {{
      display: grid;
      gap: 10px;
    }}
    .doc-chunk {{
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid #e3e9f0;
      background: #fdfefe;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.85;
      font-size: 14px;
    }}
    .doc-chunk.is-match {{
      border-color: #e2b562;
      background: #fff8e7;
      box-shadow: inset 0 0 0 1px rgba(229, 164, 43, 0.28);
    }}
    .jump-link {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid #c8d6e5;
      background: #f5f8fb;
      color: var(--brand);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }}
    .jump-link:hover {{
      background: #eaf1f7;
      border-color: #9eb6cf;
    }}
    .jump-link-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }}
    .panel-inner {{
      padding: 22px;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }}
    .panel h2 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.4;
    }}
    .panel-note {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    .workspace-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .summary {{
      margin: 0;
      font-size: 15px;
      line-height: 1.9;
    }}
    .highlight-grid {{
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }}
    .highlight-card {{
      padding: 16px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 14px;
    }}
    .highlight-label {{
      margin-bottom: 8px;
      color: var(--brand);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .list {{
      margin: 0;
      padding-left: 20px;
      line-height: 1.9;
    }}
    .list li + li {{
      margin-top: 8px;
    }}
    .score-list {{
      display: grid;
      gap: 14px;
    }}
    .score-accordion {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      overflow: hidden;
    }}
    .score-item + .score-item {{
      border-top: 1px solid var(--line);
    }}
    .score-trigger {{
      width: 100%;
      border: 0;
      background: transparent;
      color: inherit;
      padding: 16px 18px;
      text-align: left;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
    }}
    .score-trigger:hover {{
      background: var(--panel-soft);
    }}
    .score-trigger-main {{
      display: grid;
      gap: 6px;
      min-width: 0;
    }}
    .score-trigger-sub {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    .score-trigger-meta {{
      display: grid;
      justify-items: end;
      gap: 8px;
      flex-shrink: 0;
    }}
    .score-pill {{
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--brand-soft);
      color: var(--brand);
      font-size: 12px;
      font-weight: 700;
    }}
    .score-chevron {{
      color: var(--muted);
      font-size: 12px;
      transition: transform 0.2s ease;
    }}
    .score-item.is-open .score-chevron {{
      transform: rotate(180deg);
    }}
    .score-body {{
      display: none;
      padding: 0 18px 18px;
    }}
    .score-item.is-open .score-body {{
      display: block;
    }}
    .score-detail-card {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel-soft);
    }}
    .score-card-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}
    .score-card-title {{
      font-size: 17px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .score-card-meta {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .tag-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .tag {{
      padding: 5px 10px;
      border-radius: 999px;
      background: var(--brand-soft);
      color: var(--brand);
      font-size: 12px;
      line-height: 1.6;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }}
    .qa-list,
    .support-list,
    .report-block,
    .section-preview,
    .citation-list {{
      display: grid;
      gap: 12px;
    }}
    .qa-card,
    .support-item,
    .support-box {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel-soft);
    }}
    .qa-question {{
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 10px;
      line-height: 1.6;
    }}
    .qa-answer {{
      font-size: 14px;
      line-height: 1.8;
      margin-bottom: 12px;
    }}
    .support-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .citation {{
      padding: 10px 12px;
      border-radius: 12px;
      background: #f5f8fb;
      border: 1px solid var(--line);
      font-size: 13px;
      line-height: 1.7;
    }}
    .kv-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .kv-table th,
    .kv-table td {{
      padding: 12px 10px;
      border-top: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      line-height: 1.8;
    }}
    .kv-table th {{
      width: 110px;
      color: var(--muted);
      font-weight: 600;
    }}
    details {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel);
      overflow: hidden;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      padding: 14px 16px;
      list-style: none;
      background: var(--panel-soft);
    }}
    summary::-webkit-details-marker {{
      display: none;
    }}
    .fold-body {{
      padding: 14px 16px 16px;
      display: grid;
      gap: 10px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      line-height: 1.7;
      color: #374151;
    }}
    .empty {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }}
    .facts-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .mini-card {{
      padding: 14px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 14px;
    }}
    .mini-card .label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .mini-card .value {{
      font-size: 18px;
      font-weight: 700;
      line-height: 1.5;
      word-break: break-word;
    }}
    .chat-shell {{
      display: grid;
      gap: 14px;
    }}
    .chat-toolbar {{
      display: grid;
      gap: 8px;
    }}
    .chat-toolbar label {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }}
    .chat-input,
    .chat-textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      color: var(--ink);
      padding: 12px 14px;
      font-size: 14px;
      outline: none;
    }}
    .chat-thread {{
      display: grid;
      gap: 12px;
      max-height: 420px;
      overflow: auto;
      padding-right: 4px;
    }}
    .chat-msg {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: var(--panel);
    }}
    .chat-msg-user {{
      background: var(--brand-soft);
      border-color: #c9d9ea;
    }}
    .chat-role {{
      color: var(--brand);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .chat-body {{
      font-size: 14px;
      line-height: 1.8;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .chat-citations {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}
    .chat-citation {{
      padding: 10px 12px;
      border-radius: 12px;
      background: #f5f8fb;
      border: 1px solid var(--line);
      font-size: 13px;
      line-height: 1.7;
    }}
    .chat-form {{
      display: grid;
      gap: 10px;
    }}
    .chat-textarea {{
      min-height: 96px;
      resize: vertical;
    }}
    .chat-actions {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .chat-suggestions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .chat-suggestion,
    .chat-submit {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      color: var(--ink);
      padding: 9px 14px;
      font-size: 13px;
      cursor: pointer;
    }}
    .chat-submit {{
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
      font-weight: 700;
    }}
    .chat-submit[disabled],
    .chat-suggestion[disabled] {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    .chat-status {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    .result-shell {{
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    .result-shell > .panel-inner {{
      height: 100%;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }}
    .result-tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }}
    .result-tab {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-soft);
      color: var(--muted);
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .result-tab.is-active {{
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
    }}
    .result-panels {{
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
    }}
    .result-panel {{
      display: none;
    }}
    .result-panel.is-active {{
      display: block;
    }}
    .result-panel > .panel {{
      box-shadow: none;
    }}
    @media (max-width: 1320px) {{
      body {{
        overflow: auto;
      }}
      .content-grid {{
        grid-template-columns: 1fr;
        height: auto;
      }}
      .page {{
        height: auto;
        min-height: 100vh;
      }}
      .page-stack {{
        height: auto;
        grid-template-rows: auto auto;
      }}
      .project-stack,
      .nav-stack,
      .main-stack,
      .side-stack {{
        overflow: visible;
        padding-right: 0;
      }}
    }}
    @media (max-width: 1120px) {{
      .facts-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
    @media (max-width: 760px) {{
      .page {{
        padding: 12px;
        height: auto;
      }}
      .hero,
      .panel-inner {{
        padding: 18px;
      }}
      .hero-top {{
        flex-wrap: wrap;
      }}
      .result-tabs {{
        overflow-x: auto;
        flex-wrap: nowrap;
        padding-bottom: 4px;
      }}
      .facts-grid {{
        grid-template-columns: 1fr;
      }}
      .report-title {{
        font-size: 18px;
      }}
      .score-trigger,
      .score-card-head {{
        display: grid;
      }}
      .score-trigger-meta {{
        justify-items: start;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="page-stack">
      <header class="panel hero">
        <div class="hero-top">
          <h1 class="report-title">{html.escape(str(title))}</h1>
          <div class="score-card {score_class}">
            <div class="score-label">综合评分 / 等级</div>
            <div class="score-main">
              <div class="score-value">{html.escape(str(score))}</div>
              <div class="score-grade">{html.escape(str(grade))}</div>
            </div>
          </div>
        </div>
      </header>

      <div class="{layout_class}">
        {project_nav}
        <main class="main-stack">
          {document_panel}
          {left_tail}
        </main>

        <aside class="side-stack">
          <section class="panel result-shell" id="result-shell">
            <div class="panel-inner">
              <div class="workspace-head">
                <h2>{report_title}</h2>
                {"" if debug_mode else """
                <div class="result-tabs" id="result-tabs">
                  <button type="button" class="result-tab is-active" data-tab-target="report-overview">评审结论</button>
                  <button type="button" class="result-tab" data-tab-target="report-dimensions">维度评分</button>
                  <button type="button" class="result-tab" data-tab-target="report-chat">专家聊天</button>
                  <button type="button" class="result-tab" data-tab-target="report-qna">典型问答</button>
                  <button type="button" class="result-tab" data-tab-target="report-fit">指南贴合</button>
                  <button type="button" class="result-tab" data-tab-target="report-benchmark">技术摸底</button>
                </div>
                """}
              </div>
              <div class="result-panels">
                <section class="result-panel is-active" id="report-overview">
                  <section class="panel">
                    <div class="panel-inner">
                      <p class="summary">{html.escape(str(result.get("summary") or "暂无"))}</p>
                      <div class="highlight-grid">
                        <div class="highlight-card">
                          <div class="highlight-label">研究目标</div>
                          {self._render_highlight_list(highlights.get("research_goals") or [], "goal", evidence_map, packet_assets, "暂无提取结果")}
                        </div>
                        <div class="highlight-card">
                          <div class="highlight-label">创新点</div>
                          {self._render_highlight_list(highlights.get("innovations") or [], "innovation", evidence_map, packet_assets, "暂无提取结果")}
                        </div>
                        <div class="highlight-card">
                          <div class="highlight-label">技术路线</div>
                          {self._render_highlight_list(highlights.get("technical_route") or [], "route", evidence_map, packet_assets, "暂无提取结果")}
                        </div>
                      </div>
                    </div>
                  </section>
                </section>

                <section class="result-panel" id="report-dimensions">
                  <section class="panel">
                    <div class="panel-inner">
                      <div class="score-list">
                        {self._render_dimension_scores(dimension_scores)}
                      </div>
                    </div>
                  </section>
                </section>

                {self._render_chat_panel(
                    evaluation_id=evaluation_id,
                    chat_ready=bool(result.get("chat_ready")),
                    expert_qna=expert_qna,
                    debug_mode=debug_mode,
                )}

                <section class="result-panel" id="report-qna">
                  <section class="panel">
                    <div class="panel-inner">
                      {self._render_expert_qna(expert_qna, packet_assets)}
                    </div>
                  </section>
                </section>

                <section class="result-panel" id="report-fit">
                  <section class="panel">
                    <div class="panel-inner">
                      {self._render_industry_fit(industry_fit)}
                    </div>
                  </section>
                </section>

                <section class="result-panel" id="report-benchmark">
                  <section class="panel">
                    <div class="panel-inner">
                      {self._render_benchmark(benchmark)}
                    </div>
                  </section>
                </section>

                {right_tail}
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </div>
  {self._render_result_tabs_script(debug_mode)}
</body>
</html>"""

    def build_index_html(self, records: List[Dict[str, Any]]) -> str:
        """构建多项目总工作台"""
        project_items: List[str] = []
        default_html = ""
        default_title = "项目评审工作台"
        default_score = ""
        for index, record in enumerate(records):
            payload = record.get("payload") or {}
            sections = payload.get("sections") if isinstance(payload, dict) else {}
            result = payload.get("result") if isinstance(payload, dict) else {}
            preferred_name = self._extract_project_name_from_payload(payload)
            project_name = preferred_name or str(record.get("project_name") or record.get("project_id") or "未命名项目")
            project_id = str(record.get("project_id") or "-")
            grade = str(record.get("grade") or "-")
            score = str(record.get("overall_score") or "-")
            html_file = str(record.get("html_file") or "#")
            debug_html_file = str(record.get("debug_html_file") or "#")
            json_file = str(record.get("json_file") or "#")
            summary = ""
            if isinstance(result, dict):
                summary = str(result.get("summary") or "").strip()
            summary = summary[:48] + ("..." if len(summary) > 48 else "")
            score_text = f"{score} / {grade}"
            active_class = " is-active" if index == 0 else ""
            if index == 0:
                default_html = html_file
                default_title = project_name
                default_score = score_text
            project_items.append(
                f"""
                <button
                  type="button"
                  class="project-item{active_class}"
                  data-project-html="{html.escape(html_file)}"
                  data-project-title="{html.escape(project_name)}"
                  data-project-score="{html.escape(score_text)}"
                >
                  <div class="project-item-top">
                    <div class="project-item-title">{html.escape(project_name)}</div>
                    <div class="project-item-score">{html.escape(score)} / {html.escape(grade)}</div>
                  </div>
                  <div class="project-item-meta">{html.escape(project_id)}</div>
                  <div class="project-item-summary">{html.escape(summary or '暂无摘要')}</div>
                  <div class="project-item-links">
                    <a href="{html.escape(html_file)}" target="evaluation-workspace-frame">正式</a>
                    <a href="{html.escape(debug_html_file)}" target="_blank" rel="noopener noreferrer">调试</a>
                    <a href="{html.escape(json_file)}" target="_blank" rel="noopener noreferrer">JSON</a>
                  </div>
                </button>
                """
            )

        empty_state = '<div class="empty-state">暂无评审结果</div>'
        workspace_html = (
            f"""
            <div class="workspace-shell">
              <aside class="project-rail">
                <div class="project-rail-head">
                  <h1>项目评审工作台</h1>
                  <div class="project-rail-sub">左侧切项目，右侧查看该项目完整评审报告。</div>
                </div>
                <div class="project-list">
                  {''.join(project_items)}
                </div>
              </aside>
              <section class="workspace-main">
                <div class="workspace-head">
                  <div class="workspace-title" id="workspace-title">{html.escape(default_title)}</div>
                  <div class="workspace-score" id="workspace-score">{html.escape(default_score)}</div>
                </div>
                <iframe
                  id="evaluation-workspace-frame"
                  class="workspace-frame"
                  name="evaluation-workspace-frame"
                  src="{html.escape(default_html)}"
                  title="项目评审工作台"
                ></iframe>
              </section>
            </div>
            """
            if records
            else empty_state
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>项目评审工作台</title>
  <style>
    * {{
      box-sizing: border-box;
      min-width: 0;
    }}
    html, body {{
      height: 100%;
    }}
    body {{
      margin: 0;
      font-family: "Source Han Sans SC", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
      background: #f3f5f7;
      color: #1b2430;
      overflow: hidden;
    }}
    .workspace-shell {{
      height: 100vh;
      display: grid;
      grid-template-columns: 252px minmax(0, 1fr);
      gap: 0;
    }}
    .project-rail {{
      border-right: 1px solid #d7dfe8;
      background: #fbfcfd;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
    }}
    .project-rail-head {{
      padding: 20px 18px 14px;
      border-bottom: 1px solid #e6edf4;
    }}
    .project-rail-head h1 {{
      margin: 0 0 6px;
      font-size: 20px;
      line-height: 1.4;
    }}
    .project-rail-sub {{
      color: #66758a;
      font-size: 13px;
      line-height: 1.7;
    }}
    .project-list {{
      min-height: 0;
      overflow: auto;
      padding: 10px;
      display: grid;
      gap: 8px;
      align-content: start;
    }}
    .project-item {{
      width: 100%;
      border: 1px solid #d7dfe8;
      border-radius: 12px;
      background: #ffffff;
      text-align: left;
      padding: 10px 11px;
      cursor: pointer;
      display: grid;
      gap: 4px;
      box-shadow: 0 4px 12px rgba(18, 31, 53, 0.035);
    }}
    .project-item:hover,
    .project-item.is-active {{
      border-color: #9eb6cf;
      background: #eef4f9;
    }}
    .project-item-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
    }}
    .project-item-title {{
      font-size: 13px;
      font-weight: 700;
      line-height: 1.45;
    }}
    .project-item-score {{
      flex-shrink: 0;
      color: #1d3c61;
      font-size: 11px;
      font-weight: 700;
      border: 1px solid #c8d6e5;
      border-radius: 999px;
      padding: 2px 7px;
      background: #f5f8fb;
    }}
    .project-item-meta {{
      color: #66758a;
      font-size: 11px;
      line-height: 1.45;
      word-break: break-all;
    }}
    .project-item-summary {{
      color: #334155;
      font-size: 12px;
      line-height: 1.5;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      overflow: hidden;
    }}
    .project-item-links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .project-item-links a {{
      color: #1d3c61;
      font-size: 11px;
      font-weight: 700;
      text-decoration: none;
      position: relative;
      z-index: 1;
    }}
    .workspace-main {{
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background: #eef2f6;
    }}
    .workspace-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      padding: 16px 20px;
      background: #ffffff;
      border-bottom: 1px solid #d7dfe8;
    }}
    .workspace-title {{
      font-size: 18px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .workspace-score {{
      flex-shrink: 0;
      color: #1d3c61;
      font-size: 13px;
      font-weight: 700;
      border: 1px solid #c8d6e5;
      border-radius: 999px;
      padding: 6px 10px;
      background: #f5f8fb;
    }}
    .workspace-frame {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #eef2f6;
    }}
    .empty-state {{
      display: grid;
      place-items: center;
      height: 100vh;
      color: #66758a;
      font-size: 16px;
    }}
    @media (max-width: 1024px) {{
      body {{
        overflow: auto;
      }}
      .workspace-shell {{
        height: auto;
        min-height: 100vh;
        grid-template-columns: 1fr;
        grid-template-rows: auto 70vh;
      }}
      .project-rail {{
        border-right: 0;
        border-bottom: 1px solid #d7dfe8;
      }}
      .workspace-head {{
        align-items: flex-start;
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  {workspace_html}
  <script>
    (() => {{
      const items = Array.from(document.querySelectorAll(".project-item"));
      const frame = document.getElementById("evaluation-workspace-frame");
      const title = document.getElementById("workspace-title");
      const score = document.getElementById("workspace-score");
      if (!items.length || !frame) return;

      const syncEmbeddedLayout = () => {{
        try {{
          const doc = frame.contentDocument;
          if (!doc) return;
          const rail = doc.getElementById("project-rail");
          if (rail) {{
            const stack = rail.closest(".project-stack");
            if (stack) stack.style.display = "none";
          }}
          const styleId = "embedded-workspace-override";
          let style = doc.getElementById(styleId);
          if (!style) {{
            style = doc.createElement("style");
            style.id = styleId;
            style.textContent = `
              .workspace-layout {{
                grid-template-columns: minmax(0, 1.55fr) minmax(430px, 1.08fr) !important;
              }}
              .project-stack {{
                display: none !important;
              }}
              .hero {{
                display: none !important;
              }}
              .page {{
                padding-top: 0 !important;
              }}
              .page-stack {{
                grid-template-rows: minmax(0, 1fr) !important;
              }}
            `;
            doc.head.appendChild(style);
          }}
        }} catch (error) {{
          console.warn("failed to sync embedded evaluation layout", error);
        }}
      }};

      const activate = (item) => {{
        items.forEach((node) => node.classList.toggle("is-active", node === item));
        frame.src = item.dataset.projectHtml || "";
        if (title) {{
          title.textContent = item.dataset.projectTitle || "";
        }}
        if (score) {{
          score.textContent = item.dataset.projectScore || "";
        }}
      }};

      frame.addEventListener("load", syncEmbeddedLayout);
      items.forEach((item) => {{
        item.addEventListener("click", (event) => {{
          const link = event.target.closest("a");
          if (link) return;
          activate(item);
        }});
      }});

      syncEmbeddedLayout();
    }})();
  </script>
</body>
</html>"""

    def _render_dimension_scores(self, dimension_scores: List[Dict[str, Any]]) -> str:
        if not dimension_scores:
            return '<div class="empty">暂无维度评分</div>'

        default_open_index = self._pick_default_dimension_index(dimension_scores)
        cards: List[str] = []
        for index, score in enumerate(dimension_scores):
            issues = score.get("issues") or []
            highlights = score.get("highlights") or []
            is_open = index == default_open_index
            open_class = " is-open" if is_open else ""
            summary = str(score.get("opinion") or "暂无意见")
            cards.append(
                f"""
                <div class="score-item{open_class}">
                  <button class="score-trigger" type="button">
                    <div class="score-trigger-main">
                      <div class="score-card-title">{html.escape(str(score.get("dimension_name") or score.get("dimension") or "-"))}</div>
                      <div class="score-trigger-sub">{html.escape(summary[:72] + ("..." if len(summary) > 72 else ""))}</div>
                    </div>
                    <div class="score-trigger-meta">
                      <div class="score-pill">得分 {html.escape(str(score.get("score", "-")))}</div>
                      <div class="score-chevron">展开详情</div>
                    </div>
                  </button>
                  <div class="score-body">
                    <div class="score-detail-card">
                      <div class="score-card-head">
                        <div class="score-card-title">{html.escape(str(score.get("dimension_name") or score.get("dimension") or "-"))}</div>
                        <div class="score-card-meta">得分 {html.escape(str(score.get("score", "-")))} / 权重 {html.escape(str(score.get("weight", "-")))}</div>
                      </div>
                      <div class="subtle">{html.escape(summary)}</div>
                      <div class="tag-row">
                        {''.join(f'<span class="tag">亮点：{html.escape(str(item))}</span>' for item in highlights[:3])}
                        {''.join(f'<span class="tag">问题：{html.escape(str(item))}</span>' for item in issues[:3])}
                      </div>
                    </div>
                  </div>
                </div>
                """
            )
        script = """
        <script>
          (() => {
            const root = document.getElementById("dimension-accordion");
            if (!root) return;
            const items = Array.from(root.querySelectorAll(".score-item"));
            items.forEach((item) => {
              const trigger = item.querySelector(".score-trigger");
              if (!trigger) return;
              trigger.addEventListener("click", () => {
                items.forEach((current) => {
                  current.classList.toggle("is-open", current === item ? !current.classList.contains("is-open") : false);
                });
              });
            });
          })();
        </script>
        """
        return f'<div class="score-accordion" id="dimension-accordion">{"".join(cards)}</div>{script}'

    def _pick_default_dimension_index(self, dimension_scores: List[Dict[str, Any]]) -> int:
        """默认展开最低分维度；同分时优先有问题项的维度"""
        best_index = 0
        best_key = None
        for index, score in enumerate(dimension_scores):
            raw_score = score.get("score", 0)
            try:
                score_value = float(raw_score)
            except (TypeError, ValueError):
                score_value = 0.0
            issues = score.get("issues") or []
            key = (score_value, -len(issues), index)
            if best_key is None or key < best_key:
                best_key = key
                best_index = index
        return best_index

    def _render_document_panel(
        self,
        page_chunks: List[Dict[str, Any]],
        meta: Dict[str, Any],
        packet_assets: Dict[str, Any],
        debug_mode: bool,
    ) -> str:
        """渲染左侧正文阅读区"""
        if debug_mode:
            return ""

        viewer_file = str(packet_assets.get("viewer_file") or "").strip() if isinstance(packet_assets, dict) else ""
        if viewer_file:
            return f"""
            <section class="panel doc-panel" id="report-document">
              <div class="panel-inner doc-panel-inner">
                <iframe
                  class="packet-frame"
                  id="packet-viewer-frame"
                  src="{html.escape(viewer_file)}"
                  title="统一材料阅读区"
                ></iframe>
              </div>
            </section>
            {self._render_document_jump_script(packet_assets)}
            """

        pages: Dict[int, List[Dict[str, Any]]] = {}
        for chunk in page_chunks:
            if not isinstance(chunk, dict):
                continue
            page = int(chunk.get("page", 0) or 0)
            if page <= 0:
                continue
            pages.setdefault(page, []).append(chunk)

        page_count = len(pages) or int(meta.get("page_count", 0) or 0)
        if not pages:
            body_html = '<div class="empty">当前没有可渲染的正文页切片，暂时无法提供联动阅读。</div>'
        else:
            page_cards: List[str] = []
            for page_no in sorted(pages):
                chunks_html: List[str] = []
                for index, chunk in enumerate(pages[page_no], start=1):
                    section = str(chunk.get("section") or "").strip()
                    text = str(chunk.get("text") or "").strip()
                    if not text:
                        continue
                    section_html = (
                        f'<div class="doc-page-sub">{html.escape(section)}</div>'
                        if section
                        else ""
                    )
                    chunks_html.append(
                        f"""
                        <article
                          class="doc-chunk"
                          data-page="{page_no}"
                          data-snippet="{html.escape(self._normalize_search_text(text[:220]))}"
                        >
                          {section_html}
                          <div>{html.escape(text)}</div>
                        </article>
                        """
                    )
                page_cards.append(
                    f"""
                    <section class="doc-page" data-page="{page_no}" id="doc-page-{page_no}">
                      <div class="doc-page-head">
                        <div class="doc-page-title">第 {page_no} 页</div>
                      </div>
                      <div class="doc-chunk-list">
                        {''.join(chunks_html) or '<div class="empty">本页暂无可展示正文</div>'}
                      </div>
                    </section>
                    """
                )
            body_html = "".join(page_cards)

        return f"""
        <section class="panel doc-panel" id="report-document">
          <div class="panel-inner doc-panel-inner">
            <div class="doc-viewer" id="doc-viewer">
              {body_html}
            </div>
          </div>
        </section>
        {self._render_document_jump_script(packet_assets)}
        """

    def _render_document_nav(
        self,
        page_chunks: List[Dict[str, Any]],
        sections: Dict[str, str],
        debug_mode: bool,
    ) -> str:
        """渲染左侧阅读导航栏"""
        if debug_mode:
            return ""

        pages: Dict[int, str] = {}
        section_pages: Dict[str, int] = {}
        for chunk in page_chunks:
            if not isinstance(chunk, dict):
                continue
            try:
                page = int(chunk.get("page", 0) or 0)
            except (TypeError, ValueError):
                page = 0
            if page <= 0:
                continue
            pages.setdefault(page, str(chunk.get("text") or "").strip())
            section = str(chunk.get("section") or "").strip()
            if section and section not in section_pages:
                section_pages[section] = page

        section_links = []
        for name, page in list(section_pages.items())[:10]:
            section_links.append(
                f'<a class="rail-link" href="#doc-page-{page}" data-doc-jump="true" data-page="{page}" data-snippet="">'
                f'<span class="rail-link-label">{html.escape(name)}</span>'
                f'<span class="rail-link-meta">P{page}</span>'
                "</a>"
            )

        page_links = []
        for page, preview in sorted(pages.items()):
            page_links.append(
                f'<a class="rail-link" href="#doc-page-{page}" data-doc-jump="true" data-page="{page}" '
                f'data-snippet="{html.escape(self._normalize_search_text(preview[:120]))}">'
                f'<span class="rail-link-label">第 {page} 页</span>'
                f'<span class="rail-link-meta">跳转</span>'
                "</a>"
            )

        section_block = (
            f"""
            <div class="rail-group">
              <div class="rail-group-title">章节</div>
              <div class="rail-links">{"".join(section_links)}</div>
            </div>
            """
            if section_links
            else ""
        )
        page_block = (
            f"""
            <div class="rail-group">
              <div class="rail-group-title">正文页</div>
              <div class="rail-links">{"".join(page_links) or '<div class="empty">暂无页码</div>'}</div>
            </div>
            """
        )

        return f"""
        <aside class="nav-stack">
          <section class="panel rail-panel" id="document-rail">
            <div class="panel-inner rail-inner">
              <div>
                <div class="rail-title">正文导航</div>
                <div class="rail-meta">按章节或页码快速定位原文。</div>
              </div>
              <div class="rail-group">
                <div class="rail-group-title">项目</div>
                <div class="rail-links">
                  <a class="rail-link is-active" href="#report-document">
                    <span class="rail-link-label">当前项目</span>
                    <span class="rail-link-meta">{len(pages)} 页</span>
                  </a>
                </div>
              </div>
              <div class="rail-scroll">
                {section_block}
                {page_block}
              </div>
            </div>
          </section>
        </aside>
        """

    def _render_project_nav(
        self,
        workspace_projects: List[Dict[str, Any]],
        debug_mode: bool,
    ) -> str:
        """渲染最左侧项目切换栏，仅扩展左侧，不干扰现有正文与结果布局"""
        if debug_mode or not workspace_projects:
            return ""

        links: List[str] = []
        for item in workspace_projects:
            active_class = " is-active" if item.get("active") else ""
            title = str(item.get("project_name") or item.get("project_id") or "未命名项目")
            project_id = str(item.get("project_id") or "-")
            score = item.get("score")
            grade = str(item.get("grade") or "-")
            score_text = f"{score} / {grade}" if score is not None else grade
            href = str(item.get("html_file") or "#")
            links.append(
                f"""
                <a class="project-link{active_class}" href="{html.escape(href)}">
                  <div class="project-link-title">{html.escape(title)}</div>
                  <div class="project-link-meta">{html.escape(project_id)}</div>
                  <div class="project-link-score">{html.escape(score_text)}</div>
                </a>
                """
            )

        return f"""
        <aside class="project-stack">
          <section class="panel project-panel" id="project-rail">
            <div class="panel-inner project-panel-inner">
              <div class="project-panel-title">项目</div>
              <div class="project-list">
                {''.join(links)}
              </div>
            </div>
          </section>
        </aside>
        """

    def _render_jump_link(
        self,
        page: Any,
        snippet: Any,
        source_file: str = "",
        packet_assets: Dict[str, Any] | None = None,
        label: str = "查看原文",
    ) -> str:
        """渲染统一的正文跳转入口"""
        try:
            page_no = int(page)
        except (TypeError, ValueError):
            page_no = 0
        if page_no <= 0:
            return ""
        jump_payload = self._resolve_packet_jump_payload(
            packet_assets or {},
            source_file=source_file,
            page=page_no,
            snippet=str(snippet or ""),
        )
        packet_page = jump_payload.get("packet_page")
        rects_json = html.escape(json.dumps(jump_payload.get("highlight_rects") or [], ensure_ascii=False))
        return (
            f'<a class="jump-link" href="#doc-page-{page_no}" '
            f'data-doc-jump="true" data-page="{page_no}" '
            f'data-file="{html.escape(str(source_file or ""))}" '
            f'data-snippet="{html.escape(self._normalize_search_text(str(snippet or "")))}" '
            f'data-highlight-text="{html.escape(str(snippet or ""))}" '
            f'data-packet-page="{html.escape(str(packet_page or ""))}" '
            f"data-highlight-rects='{rects_json}'>"
            f'{html.escape(label)} · 第 {page_no} 页</a>'
        )

    def _render_document_jump_script(self, packet_assets: Dict[str, Any]) -> str:
        """正文跳转与片段高亮脚本"""
        packet_page_map_json = json.dumps(packet_assets.get("page_map") or [], ensure_ascii=False).replace("</", "<\\/")
        template = """
        <script>
          (() => {
            const viewer = document.getElementById("doc-viewer");
            const packetFrame = document.getElementById("packet-viewer-frame");
            const pageMap = __PACKET_PAGE_MAP__;
            if (!viewer && !packetFrame) return;

            const normalize = (value) => String(value || "")
              .replace(/\\s+/g, "")
              .replace(/[，。；：、“”‘’（）()【】《》,.!?\\-]/g, "")
              .trim();

            let activeTimer = null;

            const clearActiveState = () => {
              if (!viewer) return;
              viewer.querySelectorAll(".doc-page.is-active").forEach((node) => node.classList.remove("is-active"));
              viewer.querySelectorAll(".doc-chunk.is-match").forEach((node) => node.classList.remove("is-match"));
            };

            const resolvePacketPage = (fileName, page) => {
              const targetPage = Number(page || 0);
              if (!targetPage) return 0;
              const normalizedFile = String(fileName || "").trim();
              let matched = null;
              if (normalizedFile) {
                matched = pageMap.find((item) => {
                  const sourceName = String(item.source_name || "");
                  const sourceFile = String(item.source_file || "");
                  return sourceName === normalizedFile || sourceFile.endsWith(`/${normalizedFile}`) || sourceFile.endsWith(`\\\\${normalizedFile}`);
                });
              }
              if (!matched) {
                matched = pageMap.find((item) => String(item.source_kind || "") === "proposal") || pageMap[0];
              }
              if (!matched) return targetPage;
              const startPage = Number(matched.start_page || 0);
              const endPage = Number(matched.end_page || startPage || 0);
              if (!startPage) return targetPage;
              if (!targetPage) return startPage;
              return Math.min(startPage + targetPage - 1, endPage || startPage + targetPage - 1);
            };

            const postPacketJump = (page, highlightText, rects, fileName) => {
              if (!packetFrame || !page) return;
              const payload = {
                type: "gotoPacketTarget",
                page: Number(page || 0),
                location_label: String(fileName || "统一材料"),
                highlight_text: String(highlightText || ""),
                highlight_rects: Array.isArray(rects) ? rects : [],
              };
              const send = () => {
                try {
                  packetFrame.contentWindow?.postMessage(payload, "*");
                } catch (error) {
                  console.warn("packet viewer postMessage failed", error);
                }
              };
              window.setTimeout(send, 0);
              window.setTimeout(send, 120);
              window.setTimeout(send, 320);
            };

            const jumpToEvidence = (page, snippet) => {
              if (!viewer) return;
              const pageNode = viewer.querySelector(`.doc-page[data-page="${page}"]`);
              if (!pageNode) return;

              clearActiveState();
              pageNode.classList.add("is-active");

              const normalizedSnippet = normalize(snippet).slice(0, 120);
              let matchedChunk = null;
              if (normalizedSnippet) {
                matchedChunk = Array.from(pageNode.querySelectorAll(".doc-chunk")).find((node) => {
                  const text = node.dataset.snippet || normalize(node.textContent).slice(0, 300);
                  return text.includes(normalizedSnippet) || normalizedSnippet.includes(text.slice(0, 48));
                });
              }

              const target = matchedChunk || pageNode;
              if (matchedChunk) matchedChunk.classList.add("is-match");
              target.scrollIntoView({ behavior: "smooth", block: "center" });

              if (activeTimer) window.clearTimeout(activeTimer);
              activeTimer = window.setTimeout(() => {
                pageNode.classList.remove("is-active");
                if (matchedChunk) matchedChunk.classList.remove("is-match");
              }, 3600);
            };

            document.addEventListener("click", (event) => {
              const trigger = event.target.closest("[data-doc-jump]");
              if (!trigger) return;
              event.preventDefault();
              const page = Number(trigger.dataset.page || 0);
              if (!page) return;
              if (packetFrame) {
                let rects = [];
                try {
                  rects = JSON.parse(trigger.dataset.highlightRects || "[]");
                } catch (error) {
                  rects = [];
                }
                const packetPage = Number(trigger.dataset.packetPage || 0) || resolvePacketPage(trigger.dataset.file || "", page);
                postPacketJump(
                  packetPage,
                  trigger.dataset.highlightText || "",
                  rects,
                  trigger.dataset.file || "",
                );
                return;
              }
              jumpToEvidence(page, trigger.dataset.snippet || "");
            });
          })();
        </script>
        """
        return template.replace("__PACKET_PAGE_MAP__", packet_page_map_json)

    def _render_evidence(self, evidence: List[Dict[str, Any]], packet_assets: Dict[str, Any]) -> str:
        if not evidence:
            return '<div class="empty">暂无证据</div>'

        rows = []
        for item in evidence:
            rows.append(
                "<details class=\"fold\">"
                f"<summary>{html.escape(str(item.get('source') or '证据'))} · 第 {html.escape(str(item.get('page') or '-'))} 页</summary>"
                "<div class=\"fold-body\">"
                f"<div><strong>文件：</strong>{html.escape(str(item.get('file') or '-'))}</div>"
                f"<div><strong>片段：</strong>{html.escape(str(item.get('snippet') or '-'))}</div>"
                f"<div class=\"jump-link-row\">{self._render_jump_link(item.get('page'), item.get('snippet'), str(item.get('file') or ''), packet_assets)}</div>"
                "</div>"
                "</details>"
            )
        return f'<div class="report-block">{"".join(rows)}</div>'

    def _render_sections(self, sections: Dict[str, str]) -> str:
        if not sections:
            return '<div class="empty">暂无章节</div>'

        blocks = []
        shown = 0
        for name, text in sections.items():
            if self._should_skip_section_preview(name, text):
                continue
            preview = self._build_section_preview(name, text)
            if not preview:
                continue
            blocks.append(
                f"<details><summary>{html.escape(str(name))}</summary><pre>{html.escape(str(preview))}</pre></details>"
            )
            shown += 1
            if shown >= 16:
                break
        if not blocks:
            return '<div class="empty">暂无可展示的评审相关章节</div>'
        return "".join(blocks)

    def _render_list(self, items: List[Any], empty_text: str) -> str:
        if not items:
            return f'<div class="empty">{html.escape(empty_text)}</div>'
        return "<ol class=\"list\">" + "".join(
            f"<li>{html.escape(str(item))}</li>" for item in items
        ) + "</ol>"

    def _render_expert_qna(self, expert_qna: List[Dict[str, Any]], packet_assets: Dict[str, Any]) -> str:
        """渲染专家典型问答"""
        if not expert_qna:
            return '<div class="empty">当前未生成专家典型问答</div>'

        cards: List[str] = []
        for item in expert_qna:
            citations = item.get("citations") or []
            citation_html = "".join(
                (
                    "<div class=\"citation\">"
                    f"<div>页码：第 {html.escape(str(citation.get('page') or '-'))} 页</div>"
                    f"<div>文件：{html.escape(str(citation.get('file') or '-'))}</div>"
                    f"<div>片段：{html.escape(str(citation.get('snippet') or '-'))}</div>"
                    f"<div class=\"jump-link-row\">{self._render_jump_link(citation.get('page'), citation.get('snippet'), str(citation.get('file') or ''), packet_assets)}</div>"
                    "</div>"
                )
                for citation in citations[:3]
            ) or '<div class="empty">暂无可展示证据</div>'

            cards.append(
                "<div class=\"qa-card\">"
                f"<div class=\"qa-question\">{html.escape(str(item.get('question') or '-'))}</div>"
                f"<div class=\"qa-answer\">{html.escape(str(item.get('answer') or '暂无回答'))}</div>"
                f"<details class=\"fold\"><summary>查看页码证据</summary><div class=\"fold-body\"><div class=\"citation-list\">{citation_html}</div></div></details>"
                "</div>"
            )
        return f"<div class=\"qa-list\">{''.join(cards)}</div>"

    def _render_chat_panel(
        self,
        evaluation_id: str,
        chat_ready: bool,
        expert_qna: List[Dict[str, Any]],
        debug_mode: bool,
    ) -> str:
        """渲染报告内嵌聊天面板"""
        if debug_mode:
            return ""

        default_port = os.getenv("APP_PORT", "8888")
        default_api_base = f"http://127.0.0.1:{default_port}"
        suggestions = [str(item.get("question") or "").strip() for item in expert_qna if str(item.get("question") or "").strip()]
        suggestion_html = "".join(
            f'<button type="button" class="chat-suggestion" data-question="{html.escape(question)}">{html.escape(question)}</button>'
            for question in suggestions[:6]
        )

        status_text = "等待提问" if evaluation_id else "缺少评审ID"
        submit_disabled = "" if evaluation_id else "disabled"
        textarea_disabled = "" if evaluation_id else "disabled"
        escaped_eval_id = html.escape(evaluation_id)
        suggestions_block = suggestion_html or '<div class="chat-status">暂无可复用的典型问题。</div>'
        escaped_default_api_base = html.escape(default_api_base)
        escaped_default_port = html.escape(default_port)

        return f"""
        <section class="result-panel" id="report-chat">
          <section class="panel">
            <div class="panel-inner">
            <div
              class="chat-shell"
              id="chat-shell"
              data-evaluation-id="{escaped_eval_id}"
              data-chat-ready="{str(chat_ready).lower()}"
              data-default-api-base="{escaped_default_api_base}"
              data-default-port="{escaped_default_port}"
            >
              <div class="chat-suggestions" id="chat-suggestions">
                {suggestions_block}
              </div>
              <div class="chat-thread" id="chat-thread">
                <div class="chat-msg chat-msg-assistant">
                  <div class="chat-role">assistant</div>
                  <div class="chat-body">直接问具体问题，例如：这个项目的研究目标是什么？这项工作目前进展到什么程度了？这项技术有可能落地或量产吗？我会返回页码证据。</div>
                </div>
              </div>
              <form class="chat-form" id="chat-form">
                <textarea
                  id="chat-question"
                  class="chat-textarea"
                  placeholder="输入专家问题，例如：这项技术有可能量产吗？"
                  {textarea_disabled}
                ></textarea>
                <div class="chat-actions">
                  <div class="chat-status" id="chat-status">{html.escape(status_text)}</div>
                  <button id="chat-submit" class="chat-submit" type="submit" {submit_disabled}>发送问题</button>
                </div>
              </form>
            </div>
            </div>
          </section>
        </section>
        <script>
          (() => {{
            const shell = document.getElementById("chat-shell");
            if (!shell) return;

            const evaluationId = shell.dataset.evaluationId || "";
            const chatReady = shell.dataset.chatReady === "true";
            const thread = document.getElementById("chat-thread");
            const form = document.getElementById("chat-form");
            const questionInput = document.getElementById("chat-question");
            const submitButton = document.getElementById("chat-submit");
            const statusNode = document.getElementById("chat-status");
            const suggestionButtons = Array.from(shell.querySelectorAll(".chat-suggestion"));

            const configuredBase = shell.dataset.defaultApiBase || "";
            const configuredPort = shell.dataset.defaultPort || "";

            const detectDefaultBase = () => {{
              if (window.location.protocol === "http:" || window.location.protocol === "https:") {{
                if (window.location.port === configuredPort) {{
                  return window.location.origin;
                }}
                return configuredBase;
              }}
              return configuredBase;
            }};

            const apiBase = detectDefaultBase();

            const escapeHtml = (value) => String(value || "")
              .replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#39;");

            const setBusy = (busy, text) => {{
              if (submitButton) submitButton.disabled = busy || !evaluationId;
              if (questionInput) questionInput.disabled = busy || !evaluationId;
              suggestionButtons.forEach((button) => {{
                button.disabled = busy || !evaluationId;
              }});
              if (statusNode) {{
                statusNode.textContent = text || (busy ? "正在生成回答..." : "等待提问");
              }}
            }};

            const appendMessage = (role, text, citations = []) => {{
              const wrapper = document.createElement("div");
              wrapper.className = `chat-msg ${{role === "user" ? "chat-msg-user" : "chat-msg-assistant"}}`;

              const citationHtml = citations.length
                ? `<div class="chat-citations">${{citations.map((citation) => `
                    <div class="chat-citation">
                      <div>页码：第 ${{escapeHtml(citation.page || "-")}} 页</div>
                      <div>文件：${{escapeHtml(citation.file || "-")}}</div>
                      <div>片段：${{escapeHtml(citation.snippet || "-")}}</div>
                      <div class="jump-link-row">
                        <a
                          class="jump-link"
                          href="#doc-page-${{escapeHtml(citation.page || "-")}}"
                          data-doc-jump="true"
                          data-page="${{escapeHtml(citation.page || "")}}"
                          data-file="${{escapeHtml(citation.file || "")}}"
                          data-snippet="${{escapeHtml(String(citation.snippet || '').replace(/\\s+/g, '').slice(0, 120))}}"
                          data-highlight-text="${{escapeHtml(citation.snippet || "")}}"
                        >查看原文 · 第 ${{escapeHtml(citation.page || "-")}} 页</a>
                      </div>
                    </div>
                  `).join("")}}</div>`
                : "";

              wrapper.innerHTML = `
                <div class="chat-role">${{escapeHtml(role)}}</div>
                <div class="chat-body">${{escapeHtml(text)}}</div>
                ${{citationHtml}}
              `;
              thread.appendChild(wrapper);
              thread.scrollTop = thread.scrollHeight;
            }};

            const normalizeBase = (value) => String(value || "").trim().replace(/\\/+$/, "");

            const askQuestion = async (question) => {{
              const text = String(question || "").trim();
              if (!text) {{
                setBusy(false, "请输入问题");
                return;
              }}
              if (!evaluationId) {{
                setBusy(false, "缺少评审ID，无法发起提问");
                return;
              }}

              appendMessage("user", text);
              questionInput.value = "";
              setBusy(true, "正在生成回答...");

              try {{
                const response = await fetch(`${{normalizeBase(apiBase)}}/api/v1/evaluation/chat/ask`, {{
                  method: "POST",
                  headers: {{
                    "Content-Type": "application/json",
                  }},
                  body: JSON.stringify({{
                    evaluation_id: evaluationId,
                    question: text,
                  }}),
                }});

                const payload = await response.json().catch(() => ({{ detail: "服务返回了不可解析响应，请检查 API 地址是否指向正文评审服务" }}));
                if (!response.ok) {{
                  throw new Error(payload.detail || `请求失败：${{response.status}}`);
                }}

                appendMessage("assistant", payload.answer || "未返回回答", Array.isArray(payload.citations) ? payload.citations : []);
                setBusy(false, "回答已生成");
              }} catch (error) {{
                appendMessage("assistant", `调用失败：${{error.message || "未知错误"}}`);
                setBusy(false, "调用失败");
              }}
            }};

            form.addEventListener("submit", async (event) => {{
              event.preventDefault();
              await askQuestion(questionInput.value);
            }});

            suggestionButtons.forEach((button) => {{
              button.addEventListener("click", async () => {{
                await askQuestion(button.dataset.question || "");
              }});
            }});

            setBusy(false, chatReady ? "等待提问" : "可直接提问（首次会自动建索引）");
          }})();
        </script>
        """

    def _render_result_tabs_script(self, debug_mode: bool) -> str:
        """右侧结果区 tab 切换脚本"""
        if debug_mode:
            return ""
        return """
        <script>
          (() => {
            const root = document.getElementById("result-shell");
            if (!root) return;
            const tabs = Array.from(root.querySelectorAll(".result-tab"));
            const panels = Array.from(root.querySelectorAll(".result-panel"));
            if (!tabs.length || !panels.length) return;

            const activate = (targetId) => {
              tabs.forEach((tab) => {
                tab.classList.toggle("is-active", tab.dataset.tabTarget === targetId);
              });
              panels.forEach((panel) => {
                panel.classList.toggle("is-active", panel.id === targetId);
              });
            };

            tabs.forEach((tab) => {
              tab.addEventListener("click", () => activate(tab.dataset.tabTarget || ""));
            });

            activate("report-overview");
          })();
        </script>
        """

    def _resolve_packet_jump_payload(
        self,
        packet_assets: Dict[str, Any],
        source_file: str,
        page: int,
        snippet: str,
    ) -> Dict[str, Any]:
        """把原文件页码与片段映射到统一 packet 页与高亮框"""
        packet_page = self._resolve_packet_page(packet_assets, source_file, page)
        highlight_rects = self._resolve_packet_highlight_rects(packet_assets, packet_page, snippet)
        return {
            "packet_page": packet_page,
            "highlight_rects": highlight_rects,
        }

    def _resolve_packet_page(
        self,
        packet_assets: Dict[str, Any],
        source_file: str,
        page: int,
    ) -> int:
        """把原文件页码映射为 packet 页码"""
        if not isinstance(packet_assets, dict):
            return page
        page_map = packet_assets.get("page_map") or []
        if not isinstance(page_map, list):
            return page

        normalized_name = Path(str(source_file or "")).name
        matched = None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            source_name = Path(str(item.get("source_name") or "")).name
            source_path_name = Path(str(item.get("source_file") or "")).name
            if normalized_name and normalized_name in {source_name, source_path_name}:
                matched = item
                break
        if matched is None:
            matched = next((item for item in page_map if str(item.get("source_kind") or "") == "proposal"), None)
        if not isinstance(matched, dict):
            return page
        start_page = int(matched.get("start_page", 0) or 0)
        end_page = int(matched.get("end_page", start_page) or start_page)
        if start_page <= 0:
            return page
        return min(start_page + max(page, 1) - 1, end_page if end_page >= start_page else start_page)

    def _resolve_packet_highlight_rects(
        self,
        packet_assets: Dict[str, Any],
        packet_page: int,
        snippet: str,
    ) -> List[Dict[str, float]]:
        """在 packet 页内搜索片段并生成高亮框"""
        if not isinstance(packet_assets, dict):
            return []
        packet_abs_path = str(packet_assets.get("packet_abs_path") or "").strip()
        if not packet_abs_path or not os.path.exists(packet_abs_path) or packet_page <= 0:
            return []
        text = str(snippet or "").strip()
        if not text:
            return []
        candidates = self._build_packet_highlight_candidates(text)
        if not candidates:
            return []

        with fitz.open(packet_abs_path) as packet_doc:
            if packet_page > packet_doc.page_count:
                return []
            page = packet_doc.load_page(packet_page - 1)
            page_rect = page.rect
            if page_rect.width <= 0 or page_rect.height <= 0:
                return []
            matched_rects = []
            for candidate in candidates:
                hits = page.search_for(candidate)
                if hits:
                    matched_rects.extend(hits[:6])
                    if matched_rects:
                        break
        return self._merge_highlight_rects(matched_rects, page_rect) if matched_rects else []

    def _build_packet_highlight_candidates(self, text: str) -> List[str]:
        """为 packet 检索生成逐级降级候选文本"""
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return []
        candidates = [normalized]
        compact = re.sub(r"\s+", "", normalized)
        if len(compact) > 40:
            candidates.append(compact[:80])
        if len(normalized) > 60:
            candidates.append(normalized[:60])
            candidates.append(normalized[-60:])
        return [item for index, item in enumerate(candidates) if item and item not in candidates[:index]]

    def _merge_highlight_rects(
        self,
        rects: List[fitz.Rect],
        page_rect: fitz.Rect,
    ) -> List[Dict[str, float]]:
        """把多个命中框合并成较稳定的高亮区域"""
        if not rects or page_rect.width <= 0 or page_rect.height <= 0:
            return []

        sorted_rects = sorted(rects, key=lambda rect: (rect.y0, rect.x0))
        merged: List[fitz.Rect] = []
        vertical_gap = page_rect.height * 0.02
        horizontal_gap = page_rect.width * 0.04

        for rect in sorted_rects:
            current = fitz.Rect(rect)
            if not merged:
                merged.append(current)
                continue
            previous = merged[-1]
            same_line = abs(previous.y0 - current.y0) <= vertical_gap and current.x0 - previous.x1 <= horizontal_gap
            overlap = current.intersects(previous)
            if same_line or overlap:
                previous.include_rect(current)
            else:
                merged.append(current)

        result: List[Dict[str, float]] = []
        for rect in merged[:6]:
            result.append(
                {
                    "x": max(0.0, min(1.0, rect.x0 / page_rect.width)),
                    "y": max(0.0, min(1.0, rect.y0 / page_rect.height)),
                    "w": max(0.0, min(1.0, rect.width / page_rect.width)),
                    "h": max(0.0, min(1.0, rect.height / page_rect.height)),
                }
            )
        return result

    def _extract_project_name_from_payload(self, payload: Dict[str, Any]) -> str:
        """尽量从现有调试载荷中提取真实项目名称，避免 index 回退成文件名"""
        if not isinstance(payload, dict):
            return ""
        sections = payload.get("sections") or {}
        candidates: List[str] = []
        if isinstance(sections, dict):
            direct_name = str(sections.get("项目名称") or "").strip()
            if direct_name:
                return direct_name
            for key in ("概述", "项目基本信息", "项目简介"):
                value = sections.get(key)
                if value:
                    candidates.append(str(value))

        root_name = str(payload.get("project_name") or "").strip()
        result_name = str((payload.get("result") or {}).get("project_name") or "").strip()
        for value in (root_name, result_name):
            if value and not value.lower().endswith(".pdf"):
                return value

        for text in candidates:
            normalized_text = re.sub(r"\s+", " ", text)
            for pattern in self.PROJECT_NAME_PATTERNS:
                match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
                if match:
                    name = re.sub(r"\s+", " ", match.group(1)).strip(" ：:|")
                    if (
                        name
                        and "要求简练" not in name
                        and "字数不宜过多" not in name
                        and "项目申报书分为" not in name
                    ):
                        return name
        return ""

    def _build_evidence_map(self, evidence: List[Dict[str, Any]]) -> Dict[tuple[str, str], Dict[str, Any]]:
        """按摘要分类和条目构建证据映射"""
        mapping: Dict[tuple[str, str], Dict[str, Any]] = {}
        for item in evidence:
            category = str(item.get("category") or "")
            target = str(item.get("target") or "")
            if not category or not target:
                continue
            mapping[(category, target)] = item
        return mapping

    def _render_highlight_list(
        self,
        items: List[Any],
        category: str,
        evidence_map: Dict[tuple[str, str], Dict[str, Any]],
        packet_assets: Dict[str, Any],
        empty_text: str,
    ) -> str:
        """渲染带页码证据的划重点列表"""
        if not items:
            return f'<div class="empty">{html.escape(empty_text)}</div>'

        rows: List[str] = []
        for item in items:
            text = str(item)
            evidence = evidence_map.get((category, text))
            meta_html = ""
            if evidence:
                page = evidence.get("page")
                snippet = evidence.get("snippet") or ""
                meta_html = (
                    f'<div class="subtle">证据：{html.escape(str(snippet))}</div>'
                    f'<div class="jump-link-row">{self._render_jump_link(page, snippet, str(evidence.get("file") or ""), packet_assets)}</div>'
                )
            rows.append(f"<li>{html.escape(text)}{meta_html}</li>")
        return "<ol class=\"list\">" + "".join(rows) + "</ol>"

    def _render_industry_fit(self, industry_fit: Dict[str, Any] | None) -> str:
        if not industry_fit:
            return '<div class="empty">未启用或暂无结果</div>'
        return (
            '<table class="kv-table">'
            f"<tr><th>贴合度</th><td>{html.escape(str(industry_fit.get('fit_score', '-')))}</td></tr>"
            f"<tr><th>匹配项</th><td>{self._render_list(industry_fit.get('matched') or [], '暂无')}</td></tr>"
            f"<tr><th>差距项</th><td>{self._render_list(industry_fit.get('gaps') or [], '暂无')}</td></tr>"
            f"<tr><th>建议</th><td>{self._render_list(industry_fit.get('suggestions') or [], '暂无')}</td></tr>"
            '</table>'
        )

    def _render_benchmark(self, benchmark: Dict[str, Any] | None) -> str:
        if not benchmark:
            return '<div class="empty">未启用或暂无结果</div>'
        refs = benchmark.get("references") or []
        ref_html = self._render_list(
            [
                " / ".join(
                    part for part in [
                        str(item.get("source") or ""),
                        str(item.get("title") or ""),
                        str(item.get("year") or ""),
                    ] if part
                )
                for item in refs
            ],
            "暂无参考条目",
        )
        return (
            '<table class="kv-table">'
            f"<tr><th>新颖性</th><td>{html.escape(str(benchmark.get('novelty_level') or '-'))}</td></tr>"
            f"<tr><th>文献定位</th><td>{html.escape(str(benchmark.get('literature_position') or '-'))}</td></tr>"
            f"<tr><th>专利重叠</th><td>{html.escape(str(benchmark.get('patent_overlap') or '-'))}</td></tr>"
            f"<tr><th>综合结论</th><td>{html.escape(str(benchmark.get('conclusion') or '-'))}</td></tr>"
            f"<tr><th>参考条目</th><td>{ref_html}</td></tr>"
            '</table>'
        )

    def _render_errors(self, errors: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
        error_html = self._render_list(
            [
                f"[{item.get('module') or '-'}] {item.get('code') or '-'}: {item.get('message') or '-'}"
                for item in errors
            ],
            "无错误",
        )
        return (
            '<table class="kv-table">'
            f"<tr><th>错误列表</th><td>{error_html}</td></tr>"
            f"<tr><th>文件名</th><td>{html.escape(str(meta.get('file_name') or '-'))}</td></tr>"
            f"<tr><th>页数</th><td>{html.escape(str(meta.get('page_count') or '-'))}</td></tr>"
            f"<tr><th>解析版本</th><td>{html.escape(str(meta.get('parser_version') or '-'))}</td></tr>"
            f"<tr><th>近似分页</th><td>{'是' if meta.get('page_estimated') else '否'}</td></tr>"
            '</table>'
        )

    def _normalize_search_text(self, value: str) -> str:
        """统一跳转匹配文本，减少断行与标点差异影响"""
        normalized = re.sub(r"\s+", "", str(value or ""))
        normalized = re.sub(r"[，。；：、“”‘’（）()【】《》,.!?\-]", "", normalized)
        return normalized.strip()

    def _score_class(self, score: Any) -> str:
        try:
            value = float(score)
        except (TypeError, ValueError):
            return "score-mid"
        if value >= 8:
            return "score-good"
        if value >= 6:
            return "score-mid"
        return "score-bad"

    def _should_skip_section_preview(self, name: str, text: str) -> bool:
        """过滤低价值章节预览，避免预算与附件污染页面"""
        if not text or len(text.strip()) < 20:
            return True
        if len(name.strip()) <= 1:
            return True
        if re.fullmatch(r"\d{4}\s*年.*", name.strip()):
            return True
        if any(pattern in name for pattern in ("概述",)):
            return False
        for pattern in self.SECTION_PREVIEW_SKIP_PATTERNS:
            if pattern in name:
                return True
        if text.strip() in {"主要指标：", "核心建设内容："}:
            return True
        if text.strip().startswith("（包括") and len(text.strip()) <= 80:
            return True
        if "限" in text and "字以内" in text and len(text.strip()) <= 120:
            return True
        return False

    def _build_section_preview(self, name: str, text: str) -> str:
        """构建适合 HTML 展示的章节预览"""
        cleaned_text = self._cleanup_preview_text(text)
        lines = [line.strip() for line in cleaned_text.splitlines()]
        preview_lines: List[str] = []
        current_paragraph = ""

        for raw_line in lines:
            line = self._normalize_preview_line(raw_line)
            if not line:
                continue
            if self._should_drop_preview_line(name, line):
                continue
            if name == "概述" and "填报说明" in line:
                break

            if self._is_structured_preview_line(line):
                if current_paragraph:
                    preview_lines.append(current_paragraph)
                    current_paragraph = ""
                preview_lines.append(line)
                continue

            if current_paragraph:
                separator = "" if self._should_compact_preview_join(current_paragraph, line) else " "
                current_paragraph = f"{current_paragraph}{separator}{line}".strip()
            else:
                current_paragraph = line

        if current_paragraph:
            preview_lines.append(current_paragraph)

        preview = "\n".join(preview_lines).strip()
        if not preview:
            return ""
        return preview if len(preview) <= 1200 else f"{preview[:1200].rstrip()}..."

    def _cleanup_preview_text(self, text: str) -> str:
        """清洗 PDF 断行和中文断空格，提升章节预览可读性"""
        cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        cleaned = cleaned.replace("河北省科学技术厅制填报说明", "河北省科学技术厅制\n填报说明")
        for heading in self.SECTION_PREVIEW_INLINE_HEADINGS:
            cleaned = re.sub(
                rf"(^|\n)({re.escape(heading)})(?=[^\n：:])",
                rf"\1\2\n",
                cleaned,
            )
        cleaned = re.sub(
            r"(方向[一二三四五六七八九十]+：[^。\n]{4,80}?)(?=(?:该研究方向|该方向|本研究方向))",
            r"\1\n",
            cleaned,
        )
        cleaned = re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", cleaned)
        cleaned = re.sub(r"(?<=[A-Za-z])[ \t]+(?=[A-Za-z])", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _normalize_preview_line(self, line: str) -> str:
        """规范化单行预览文本"""
        normalized = re.sub(r"\s+", " ", line).strip()
        normalized = re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", normalized)
        return normalized

    def _should_drop_preview_line(self, section_name: str, line: str) -> bool:
        """过滤表单提示语和表格噪声行"""
        if not line:
            return True
        if section_name == "概述" and line in {"河北省科学技术厅制"}:
            return False
        return any(re.match(pattern, line) for pattern in self.SECTION_PREVIEW_DROP_LINE_PATTERNS)

    def _is_structured_preview_line(self, line: str) -> bool:
        """判断是否应单独成行，保留条目结构"""
        if len(line) <= 18 and not re.search(r"[。；;，,]", line):
            return True
        if re.match(r"^(?:[-•]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫])", line):
            return True
        if re.match(r"^\d+[、\.．)]", line):
            return True
        if re.match(r"^方向[一二三四五六七八九十]+[：:]", line):
            return True
        if re.match(r"^第[一二三四五六七八九十\d]+[章节部分阶段年]", line):
            return True
        if re.match(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*[-—~至]+\s*\d{4}\s*年\s*\d{1,2}\s*月$", line):
            return True
        return line.endswith(("：", ":"))

    def _should_compact_preview_join(self, previous: str, current: str) -> bool:
        """判断跨行拼接时是否应直接相连，避免中文词被断开"""
        if not previous or not current:
            return False
        return bool(
            re.match(r"[\u4e00-\u9fff]", previous[-1])
            and re.match(r"[\u4e00-\u9fff]", current[0])
        )
