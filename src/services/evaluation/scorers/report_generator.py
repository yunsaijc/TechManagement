"""
评审 HTML 报告生成器

负责将 EvaluationResult 渲染为正式报告与调试报告。
"""
from __future__ import annotations

import asyncio
import html
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import fitz

from src.services.evaluation.parsers import DocumentParser
from src.services.evaluation.highlight.extractor import HighlightExtractor
from src.services.evaluation.packet_builder import EvaluationPacketBuilder
from src.services.evaluation.storage.project_repo import EvaluationProjectRepository


class ReportGenerator:
    """评审报告生成器"""

    HASH_SOURCE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:pdf|docx)$", re.IGNORECASE)

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
    DIMENSION_SECTORS = (
        {
            "id": "value",
            "label": "项目价值",
            "color": "#c8defd",
            "accent": "#2563a6",
            "dimensions": {"innovation", "创新性", "outcome", "预期成果", "social_benefit", "社会效益", "economic_benefit", "经济效益"},
        },
        {
            "id": "execution",
            "label": "实施基础",
            "color": "#cfe8d9",
            "accent": "#2d7a4f",
            "dimensions": {"feasibility", "技术可行性", "team", "团队能力", "schedule", "进度合理性"},
        },
        {
            "id": "risk",
            "label": "风险规范",
            "color": "#ffd8bb",
            "accent": "#b8631b",
            "dimensions": {"risk", "风险控制", "compliance", "合规性"},
        },
        {
            "id": "other",
            "label": "其他维度",
            "color": "#d9e3ef",
            "accent": "#54657b",
            "dimensions": set(),
        },
    )
    DIMENSION_ORDER = {
        "innovation": 0,
        "创新性": 0,
        "outcome": 1,
        "预期成果": 1,
        "social_benefit": 2,
        "社会效益": 2,
        "economic_benefit": 3,
        "经济效益": 3,
        "feasibility": 4,
        "技术可行性": 4,
        "team": 5,
        "团队能力": 5,
        "schedule": 6,
        "进度合理性": 6,
        "risk": 7,
        "风险控制": 7,
        "compliance": 8,
        "合规性": 8,
    }
    BENCHMARK_NOVELTY_LABELS = {
        "high": "高",
        "medium_high": "较高",
        "medium": "中等",
        "medium_low": "偏保守",
        "low": "较低",
        "unknown": "待核验",
    }
    BENCHMARK_SOURCE_LABELS = {
        "literature": "论文",
        "openalex": "论文",
        "patent": "专利",
    }

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
        updated = self._ensure_page_chunks(data)
        updated = self._ensure_highlight_payload(data) or updated
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

    def _ensure_highlight_payload(self, data: Dict[str, Any]) -> bool:
        """兼容旧 debug JSON，缺少结构化摘要时按当前提取器回填"""
        result = data.get("result")
        if not isinstance(result, dict):
            return False

        existing_highlights = result.get("highlights") or {}
        if not isinstance(existing_highlights, dict):
            existing_highlights = {}
        has_goal = bool(existing_highlights.get("research_goals"))
        has_innovation = bool(existing_highlights.get("innovations"))
        has_route = bool(existing_highlights.get("technical_route"))
        if has_goal and has_innovation and has_route:
            return False

        sections = data.get("sections") or {}
        page_chunks = data.get("page_chunks") or []
        if not isinstance(sections, dict) or not sections or not isinstance(page_chunks, list) or not page_chunks:
            return False

        extractor = HighlightExtractor()
        highlights, evidence = asyncio.run(
            extractor.extract(
                sections=sections,
                page_chunks=page_chunks,
                file_name=str(data.get("source_name") or data.get("meta", {}).get("file_name") or ""),
            )
        )
        extracted = highlights.model_dump(mode="json")

        changed = False
        merged_highlights = {
            "research_goals": list(existing_highlights.get("research_goals") or []),
            "innovations": list(existing_highlights.get("innovations") or []),
            "technical_route": list(existing_highlights.get("technical_route") or []),
        }
        for key in ("research_goals", "innovations", "technical_route"):
            if not merged_highlights[key] and extracted.get(key):
                merged_highlights[key] = list(extracted.get(key) or [])
                changed = True

        if changed:
            result["highlights"] = merged_highlights

        if evidence:
            existing_evidence = result.get("evidence") or []
            if not isinstance(existing_evidence, list):
                existing_evidence = []
            existing_keys = {
                (
                    str(item.get("category") or ""),
                    str(item.get("target") or ""),
                    str(item.get("file") or ""),
                    int(item.get("page") or 0),
                )
                for item in existing_evidence
                if isinstance(item, dict)
            }
            for item in evidence:
                payload = item.model_dump(mode="json")
                key = (
                    str(payload.get("category") or ""),
                    str(payload.get("target") or ""),
                    str(payload.get("file") or ""),
                    int(payload.get("page") or 0),
                )
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                existing_evidence.append(payload)
                changed = True
            if changed:
                result["evidence"] = existing_evidence

        data["result"] = result
        return changed

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
        result_tabs = [
            ("report-overview", "评审结论"),
            ("report-dimensions", "维度评分"),
            ("report-chat", "专家聊天"),
            ("report-benchmark", "技术摸底"),
        ]
        if industry_fit:
            result_tabs.append(("report-fit", "指南贴合"))
        result_tabs_html = ""
        if not debug_mode:
            result_tabs_html = (
                '<div class="result-tabs" id="result-tabs">'
                + "".join(
                    (
                        f'<button type="button" class="result-tab{" is-active" if index == 0 else ""}" '
                        f'data-tab-target="{tab_id}">{label}</button>'
                    )
                    for index, (tab_id, label) in enumerate(result_tabs)
                )
                + "</div>"
            )
        optional_panels = ""
        optional_panels += f"""
              <section class="result-panel" id="report-benchmark">
                {self._render_benchmark(benchmark)}
              </section>
"""
        if industry_fit:
            optional_panels += f"""
              <section class="result-panel" id="report-fit">
                {self._render_industry_fit(industry_fit)}
              </section>
"""
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
      height: 100dvh;
      overflow: hidden;
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
      overflow: hidden;
    }}
    .debug-layout {{
      grid-template-columns: minmax(0, 1fr) 360px;
      overflow: hidden;
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
    .doc-toast {{
      position: absolute;
      top: 18px;
      left: 50%;
      transform: translate(-50%, -10px);
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(24, 34, 48, 0.88);
      color: #fff;
      font-size: 12px;
      line-height: 1.4;
      box-shadow: 0 16px 36px rgba(15, 23, 42, 0.2);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 3;
      white-space: nowrap;
      max-width: calc(100% - 32px);
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .doc-toast.show {{
      opacity: 1;
      transform: translate(-50%, 0);
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
    .summary-block {{
      padding: 14px 16px;
      border: 1px solid #d9e4ef;
      border-radius: 16px;
      background: linear-gradient(180deg, #fbfcfe 0%, #f5f8fb 100%);
    }}
    .highlight-grid {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}
    .highlight-card {{
      padding: 14px 0 0;
      border-top: 1px solid var(--line);
    }}
    .highlight-grid .highlight-card:first-child {{
      padding-top: 0;
      border-top: 0;
    }}
    .highlight-label {{
      margin-bottom: 10px;
      color: var(--brand);
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .highlight-list {{
      display: grid;
      gap: 10px;
    }}
    .highlight-item {{
      display: grid;
      gap: 8px;
      padding: 12px 14px;
      border: 1px solid #dfe8f1;
      border-radius: 14px;
      background: #fbfcfe;
    }}
    .highlight-item-text {{
      font-size: 14px;
      line-height: 1.85;
      word-break: break-word;
    }}
    .highlight-item-evidence {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.75;
      word-break: break-word;
      padding-top: 6px;
      border-top: 1px dashed #d7e0ea;
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
      gap: 16px;
    }}
    .dimension-dashboard {{
      display: grid;
      gap: 16px;
    }}
    .dimension-radar-card {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
    }}
    .dimension-radar-wrap {{
      display: grid;
      gap: 14px;
    }}
    .dimension-radar-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .dimension-radar-sector {{
      opacity: 0.96;
    }}
    .dimension-radar-ring {{
      fill: none;
      stroke: #aebfd2;
      stroke-width: 1.2;
    }}
    .dimension-radar-axis {{
      stroke: #b4c4d5;
      stroke-width: 1.2;
    }}
    .dimension-radar-area {{
      fill: rgba(29, 60, 97, 0.14);
      stroke: #1d3c61;
      stroke-width: 2;
    }}
    .dimension-radar-point {{
      stroke: #fff;
      stroke-width: 2;
      cursor: pointer;
      transition: transform 0.16s ease;
    }}
    .dimension-radar-point.is-active {{
      stroke: #111827;
      stroke-width: 3;
    }}
    .dimension-radar-label {{
      fill: var(--ink);
      font-size: 12px;
      cursor: pointer;
    }}
    .dimension-radar-label.is-active {{
      font-weight: 700;
      fill: var(--brand);
    }}
    .dimension-sector-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .dimension-sector-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--sector-accent) 12%, #ffffff);
      color: #334155;
      font-size: 12px;
      font-weight: 700;
    }}
    .dimension-sector-chip::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--sector-accent);
      flex-shrink: 0;
    }}
    .dimension-body {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 0;
      min-height: 0;
    }}
    .dimension-detail-stage {{
      min-height: 0;
      margin-top: 16px;
    }}
    .dimension-detail-item {{
      display: none;
      gap: 0;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
      padding: 18px;
    }}
    .dimension-detail-item.is-active {{
      display: grid;
      border-color: var(--sector-accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--sector-accent) 16%, transparent);
    }}
    .dimension-detail-kicker {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      margin-bottom: 10px;
    }}
    .dimension-detail-meter {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      margin: 12px 0 14px;
    }}
    .dimension-detail-meter-track {{
      height: 10px;
      border-radius: 999px;
      background: #e8eef5;
      overflow: hidden;
    }}
    .dimension-detail-meter-fill {{
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, color-mix(in srgb, var(--sector-accent) 46%, #ffffff) 0%, var(--sector-accent) 100%);
    }}
    .dimension-detail-meter-value {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .dimension-empty {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.75;
    }}
    .dimension-detail-blocks {{
      display: grid;
      gap: 14px;
      margin-top: 14px;
    }}
    .dimension-detail-block {{
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .dimension-detail-block:first-child {{
      padding-top: 0;
      border-top: 0;
    }}
    .dimension-detail-label {{
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }}
    .dimension-detail-summary {{
      font-size: 15px;
      line-height: 1.8;
      color: var(--ink);
    }}
    .dimension-detail-list {{
      display: grid;
      gap: 6px;
    }}
    .dimension-detail-list-item {{
      font-size: 14px;
      line-height: 1.8;
      color: var(--ink);
      word-break: break-word;
    }}
    .dimension-detail-list-item::before {{
      content: "• ";
      color: var(--sector-accent);
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
      display: grid;
      gap: 6px;
    }}
    .tag {{
      font-size: 13px;
      line-height: 1.75;
      color: var(--ink);
    }}
    .tag-strong {{
      color: var(--brand);
      font-weight: 700;
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
    .flat-stack {{
      display: grid;
      gap: 14px;
    }}
    .flat-section {{
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .flat-stack .flat-section:first-child {{
      padding-top: 0;
      border-top: 0;
    }}
    .flat-label {{
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }}
    .flat-value {{
      font-size: 14px;
      line-height: 1.85;
      word-break: break-word;
    }}
    .flat-list {{
      display: grid;
      gap: 6px;
    }}
    .flat-item {{
      font-size: 14px;
      line-height: 1.8;
      word-break: break-word;
    }}
    .flat-item::before {{
      content: "• ";
      color: var(--brand);
    }}
    .benchmark-reference-list {{
      display: grid;
      gap: 10px;
    }}
    .benchmark-reference-item {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #f8fbff;
    }}
    .benchmark-reference-title {{
      font-size: 14px;
      font-weight: 600;
      line-height: 1.7;
      color: var(--text);
      word-break: break-word;
    }}
    .benchmark-reference-meta {{
      margin-top: 4px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
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
    .chat-progress {{
      padding: 0 0 12px;
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 10px;
    }}
    .chat-progress-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .chat-progress-title {{
      color: var(--ink);
      font-size: 13px;
      font-weight: 700;
    }}
    .chat-progress-status {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }}
    .chat-progress-steps {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .chat-progress-step {{
      position: relative;
      display: grid;
      gap: 4px;
      padding: 8px 8px 8px 12px;
      border-radius: 10px;
      background: #f8fbfe;
      color: var(--muted);
      transition: all 160ms ease;
    }}
    .chat-progress-step::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 3px;
      border-radius: 12px 0 0 12px;
      background: transparent;
    }}
    .chat-progress-step.is-active {{
      color: var(--ink);
      box-shadow: inset 0 0 0 1px #c8d7e6;
    }}
    .chat-progress-step.is-active::before {{
      background: var(--brand);
    }}
    .chat-progress-step.is-done {{
      color: var(--ink);
      background: #fbfcfe;
    }}
    .chat-progress-step.is-done::before {{
      background: #4c7f58;
    }}
    .chat-progress-step-label {{
      font-size: 12px;
      font-weight: 700;
    }}
    .chat-progress-step-detail {{
      font-size: 11px;
      line-height: 1.5;
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
      gap: 10px;
      max-height: 420px;
      overflow: auto;
      padding-right: 4px;
    }}
    .chat-empty {{
      padding: 14px 0;
      border-top: 1px dashed var(--line);
      border-bottom: 1px dashed var(--line);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.8;
    }}
    .chat-msg {{
      padding: 0;
      background: transparent;
    }}
    .chat-msg + .chat-msg {{
      padding-top: 14px;
      border-top: 1px solid var(--line);
    }}
    .chat-msg-user {{
      padding: 14px;
      border: 1px solid #c9d9ea;
      border-radius: 14px;
      background: var(--brand-soft);
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
    .chat-answer {{
      display: grid;
      gap: 10px;
    }}
    .chat-answer-meta {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 2px;
    }}
    .chat-answer-tag {{
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 999px;
      background: #e8eff7;
      color: var(--brand);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }}
    .chat-answer-summary {{
      color: var(--muted);
      font-size: 12px;
    }}
    .chat-answer-block {{
      padding-left: 12px;
      border-left: 2px solid #d7e1eb;
    }}
    .chat-answer-block-primary {{
      border-left-color: #9eb6cf;
    }}
    .chat-answer-head {{
      margin-bottom: 6px;
      color: var(--brand);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .chat-answer-text {{
      font-size: 14px;
      line-height: 1.85;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .chat-answer-block-primary .chat-answer-text {{
      font-size: 15px;
      font-weight: 600;
      line-height: 1.9;
    }}
    .chat-answer-list {{
      margin: 0;
      padding: 12px 16px 12px 30px;
      display: grid;
      gap: 8px;
      font-size: 14px;
      line-height: 1.85;
    }}
    .chat-followups {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    .chat-citations {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .chat-citation {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      background: #f8fbfe;
      border: 1px solid #dde7f0;
      font-size: 12px;
      line-height: 1;
    }}
    .chat-citation-head {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }}
    .chat-citation-page {{
      flex-shrink: 0;
      padding: 3px 8px;
      border-radius: 999px;
      background: #e8eef5;
      color: var(--brand);
      font-size: 11px;
      font-weight: 700;
    }}
    .chat-citation-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .chat-citation-actions {{
      display: inline-flex;
      align-items: center;
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
    .chat-followup,
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
    .chat-suggestion[disabled],
    .chat-followup[disabled] {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    .chat-status {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    .chat-live {{
      display: grid;
      gap: 10px;
    }}
    .chat-live-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .chat-live-title {{
      font-size: 12px;
      font-weight: 700;
      color: var(--brand);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .chat-live-phase {{
      color: var(--muted);
      font-size: 12px;
    }}
    .chat-live-text {{
      min-height: 48px;
      font-size: 14px;
      line-height: 1.85;
      color: var(--ink);
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .chat-live-skeleton {{
      display: grid;
      gap: 8px;
    }}
    .chat-live-line {{
      height: 10px;
      border-radius: 999px;
      background: linear-gradient(90deg, #edf3f9 0%, #dfe9f3 45%, #edf3f9 100%);
      background-size: 200% 100%;
      animation: chat-shimmer 1.4s linear infinite;
    }}
    .chat-live-line.is-short {{
      width: 56%;
    }}
    .chat-live-line.is-mid {{
      width: 78%;
    }}
    @keyframes chat-shimmer {{
      0% {{
        background-position: 200% 0;
      }}
      100% {{
        background-position: -200% 0;
      }}
    }}
    .result-shell {{
      height: 100%;
      min-height: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      padding: 18px 18px 16px;
      gap: 14px;
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
      height: 100%;
      overflow: auto;
      padding-right: 4px;
    }}
    .result-panel {{
      display: none;
      padding-right: 2px;
    }}
    .result-panel.is-active {{
      display: grid;
      gap: 16px;
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
      .chat-progress-steps {{
        grid-template-columns: 1fr 1fr;
      }}
      .report-title {{
        font-size: 18px;
      }}
      .score-trigger,
      .score-card-head {{
        display: grid;
      }}
      .dimension-radar-card,
      .dimension-detail-item {{
        padding: 14px;
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
            <div class="workspace-head">
              <h2>{report_title}</h2>
              {result_tabs_html}
            </div>
            <div class="result-panels">
              <section class="result-panel is-active" id="report-overview">
                <div class="summary-block">
                  <p class="summary">{html.escape(str(result.get("summary") or "暂无"))}</p>
                </div>
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
              </section>

              <section class="result-panel" id="report-dimensions">
                <div class="score-list">
                  {self._render_dimension_scores(dimension_scores)}
                </div>
              </section>

              {self._render_chat_panel(
                  evaluation_id=evaluation_id,
                  chat_ready=bool(result.get("chat_ready")),
                  expert_qna=expert_qna,
                  debug_mode=debug_mode,
              )}

              {optional_panels}

              {right_tail}
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
            preferred_name = self._extract_project_name_from_payload(payload)
            project_name = preferred_name or str(record.get("project_name") or record.get("project_id") or "未命名项目")
            grade = str(record.get("grade") or "-")
            score = str(record.get("overall_score") or "-")
            html_file = str(record.get("html_file") or "#")
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
      height: 100dvh;
      overflow: hidden;
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
      margin: 0;
      font-size: 20px;
      line-height: 1.4;
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
      gap: 0;
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
    .workspace-main {{
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background: #eef2f6;
      overflow: hidden;
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
      min-height: 0;
      display: block;
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
              html, body {{
                height: 100% !important;
                overflow: hidden !important;
              }}
              .workspace-layout {{
                grid-template-columns: minmax(0, 1.55fr) minmax(430px, 1.08fr) !important;
                overflow: hidden !important;
              }}
              .project-stack {{
                display: none !important;
              }}
              .hero {{
                display: none !important;
              }}
              .page {{
                padding-top: 0 !important;
                height: 100% !important;
                min-height: 0 !important;
                overflow: hidden !important;
              }}
              .page-stack {{
                grid-template-rows: minmax(0, 1fr) !important;
                height: 100% !important;
                min-height: 0 !important;
              }}
              .main-stack,
              .side-stack,
              .doc-panel,
              .result-shell,
              .result-panels {{
                min-height: 0 !important;
              }}
              .main-stack,
              .side-stack,
              .doc-panel,
              .result-shell {{
                overflow: hidden !important;
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

        items = self._build_dimension_dashboard_items(dimension_scores)
        default_index = self._pick_default_dimension_index(items)
        sector_html = "".join(
            f'<div class="dimension-sector-chip" style="--sector-accent:{html.escape(str(sector["accent"]))}">{html.escape(str(sector["label"]))}</div>'
            for sector in self.DIMENSION_SECTORS
            if any(item.get("sector_id") == sector["id"] for item in items)
        )
        detail_html = self._render_dimension_detail(items, default_index)
        radar_html = self._render_dimension_radar(items, default_index)
        script = """
        <script>
          (() => {
            const root = document.getElementById("dimension-accordion");
            if (!root) return;
            const points = Array.from(root.querySelectorAll("[data-dimension-index]"));
            const detailItems = Array.from(root.querySelectorAll(".dimension-detail-item"));
            const activate = (index) => {
              points.forEach((node) => {
                node.classList.toggle("is-active", node.dataset.dimensionIndex === index);
              });
              detailItems.forEach((node) => {
                node.classList.toggle("is-active", node.dataset.dimensionIndex === index);
                if (node.dataset.dimensionIndex === index) {
                  node.scrollIntoView({ block: "nearest", behavior: "smooth" });
                }
              });
            };
            points.forEach((node) => {
              node.addEventListener("click", () => {
                activate(node.dataset.dimensionIndex);
              });
            });
            activate(root.dataset.defaultIndex || "0");
          })();
        </script>
        """
        return (
            f'<div class="dimension-dashboard" id="dimension-accordion" data-default-index="{default_index}">'
            f'<section class="dimension-radar-card"><div class="dimension-radar-wrap">{radar_html}<div class="dimension-sector-row">{sector_html}</div></div></section>'
            f'<div class="dimension-body">{detail_html}</div>'
            f'</div>{script}'
        )

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

    def _build_dimension_dashboard_items(self, dimension_scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """构建维度评分面板所需的视图数据"""
        items: List[Dict[str, Any]] = []
        for index, score in enumerate(dimension_scores):
            name = str(score.get("dimension_name") or score.get("dimension") or f"维度{index + 1}")
            dimension = str(score.get("dimension") or "").strip()
            raw_score = score.get("score", "-")
            try:
                score_value = float(raw_score)
            except (TypeError, ValueError):
                score_value = 0.0
            sector = self._get_dimension_sector_meta(dimension=dimension, dimension_name=name)
            items.append(
                {
                    "name": name,
                    "dimension": dimension,
                    "score": raw_score,
                    "score_value": score_value,
                    "weight": score.get("weight", "-"),
                    "opinion": str(score.get("opinion") or "暂无意见"),
                    "issues": score.get("issues") or [],
                    "highlights": score.get("highlights") or [],
                    "sector_id": sector["id"],
                    "sector_label": sector["label"],
                    "sector_color": sector["color"],
                    "sector_accent": sector["accent"],
                    "original_index": index,
                }
            )
        items.sort(key=self._dimension_dashboard_sort_key)
        for index, item in enumerate(items):
            item["dashboard_index"] = index
            item["meter_percent"] = max(0.0, min(float(item["score_value"]) / 10.0, 1.0)) * 100.0
        return items

    def _dimension_dashboard_sort_key(self, item: Dict[str, Any]) -> tuple[int, int, int]:
        sector_order = next(
            (index for index, sector in enumerate(self.DIMENSION_SECTORS) if sector["id"] == item.get("sector_id")),
            len(self.DIMENSION_SECTORS),
        )
        dimension_order = self.DIMENSION_ORDER.get(str(item.get("dimension") or ""), self.DIMENSION_ORDER.get(str(item.get("name") or ""), 999))
        return sector_order, dimension_order, int(item.get("original_index") or 0)

    def _get_dimension_sector_meta(self, dimension: str, dimension_name: str) -> Dict[str, Any]:
        """根据维度归属子扇区"""
        for sector in self.DIMENSION_SECTORS:
            dimensions = sector.get("dimensions") or set()
            if dimension in dimensions or dimension_name in dimensions:
                return sector
        return self.DIMENSION_SECTORS[-1]

    def _render_dimension_detail(self, items: List[Dict[str, Any]], default_index: int) -> str:
        details: List[str] = []
        for item in items:
            active_class = " is-active" if item["dashboard_index"] == default_index else ""
            summary, basis = self._split_dimension_opinion(str(item["opinion"]))
            highlights = self._normalize_dimension_highlight_items(item.get("highlights") or [])
            issues = self._filter_dimension_issue_items(item.get("issues") or [])
            actions = self._build_dimension_action_items(issues)
            details.append(
                f"""
                <section
                  class="dimension-detail-item{active_class}"
                  data-dimension-index="{item['dashboard_index']}"
                  style="--sector-accent:{html.escape(str(item['sector_accent']))};"
                >
                  <div class="dimension-detail-kicker">{html.escape(str(item["sector_label"]))}</div>
                  <div class="score-card-head">
                    <div class="score-card-title">{html.escape(str(item["name"]))}</div>
                    <div class="score-card-meta">得分 {html.escape(str(item["score"]))} / 权重 {html.escape(str(item["weight"]))}</div>
                  </div>
                  <div class="dimension-detail-meter">
                    <div class="dimension-detail-meter-track">
                      <div class="dimension-detail-meter-fill" style="width:{item['meter_percent']:.1f}%"></div>
                    </div>
                    <div class="dimension-detail-meter-value">{html.escape(str(item["score"]))} / 10</div>
                  </div>
                  <div class="dimension-detail-blocks">
                    {self._render_dimension_text_block("一句话判断", [summary], "暂无判断")}
                    {self._render_dimension_text_block("主要依据", basis, "暂无明确依据")}
                    {self._render_dimension_text_block("优势", highlights[:4], "暂无明显优势")}
                    {self._render_dimension_text_block("短板 / 待补充", issues[:4], "暂无明显短板")}
                    {self._render_dimension_text_block("建议动作", actions[:3], "暂无明确建议动作")}
                  </div>
                </section>
                """
            )
        return f'<section class="dimension-detail-stage">{"".join(details)}</section>'

    def _split_dimension_opinion(self, opinion: str) -> tuple[str, List[str]]:
        """将维度长评语拆成一句话判断和依据列表"""
        text = re.sub(r"\s+", " ", str(opinion or "")).strip()
        if not text:
            return "暂无判断", []

        parts = [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]
        if not parts:
            return text, []

        summary = parts[0]
        basis = [part for part in parts[1:4] if self._normalize_text_for_compare(part) != self._normalize_text_for_compare(summary)]
        if not basis and len(summary) > 80:
            basis = []
        return summary, basis

    def _filter_dimension_issue_items(self, issues: List[Any]) -> List[str]:
        """过滤不应作为短板展示的中性说明"""
        filtered: List[str] = []
        for issue in issues:
            text = str(issue).strip()
            if not text:
                continue
            if self._is_neutral_dimension_note(text):
                continue
            if self._normalize_text_for_compare(text) in {self._normalize_text_for_compare(item) for item in filtered}:
                continue
            filtered.append(text)
        return filtered

    def _normalize_dimension_highlight_items(self, highlights: List[Any]) -> List[str]:
        """优化亮点表述，避免出现调试味的章节识别文案"""
        chapter_names: List[str] = []
        normalized: List[str] = []
        for raw in highlights:
            text = str(raw).strip()
            if not text:
                continue
            if text.startswith("已识别章节："):
                chapter_name = text.split("：", 1)[-1].strip()
                if chapter_name:
                    chapter_names.append(chapter_name)
                continue
            if self._normalize_text_for_compare(text) not in {self._normalize_text_for_compare(item) for item in normalized}:
                normalized.append(text)
        if chapter_names:
            normalized.insert(0, f"已覆盖{chr(12289).join(chapter_names[:4])}等实施内容")
        return normalized

    def _is_neutral_dimension_note(self, text: str) -> bool:
        """识别“已按替代材料评估”等中性说明，避免误判为短板"""
        value = re.sub(r"\s+", "", str(text or ""))
        neutral_patterns = [
            "不再强制要求",
            "已按",
            "已基于",
            "已识别",
            "替代内容评估",
            "替代材料进行",
            "更偏平台建设",
            "科普实施类",
        ]
        problem_keywords = ["缺少", "缺乏", "不足", "未提供", "未说明", "不清晰", "偏弱", "风险", "无法"]
        if any(keyword in value for keyword in neutral_patterns) and not any(keyword in value for keyword in problem_keywords):
            return True
        if "未设置独立技术路线章节" in value and ("已按" in value or "替代" in value):
            return True
        return False

    def _build_dimension_action_items(self, issues: List[str]) -> List[str]:
        """根据短板生成可执行的补充动作"""
        actions: List[str] = []
        for issue in issues:
            text = str(issue).strip()
            if not text:
                continue
            if self._is_neutral_dimension_note(text):
                continue
            normalized = re.sub(r"^(问题[:：]?|缺少|缺乏|不足|未提及|不够|偏弱|需|需要|建议)", "", text).strip(" ，。；;")
            if not normalized:
                normalized = text
            normalized = re.sub(r"已按.+$", "", normalized).strip(" ，。；;")
            normalized = re.sub(r"已基于.+$", "", normalized).strip(" ，。；;")
            if not normalized:
                continue
            if any(keyword in text for keyword in ["缺少", "缺乏", "未提及", "不足"]):
                action = f"补充{normalized}"
            elif any(keyword in text for keyword in ["不够", "不清晰", "偏弱"]):
                action = f"完善{normalized}"
            else:
                action = f"明确{normalized}"
            if self._normalize_text_for_compare(action) not in {self._normalize_text_for_compare(item) for item in actions}:
                actions.append(action)
        return actions

    def _normalize_text_for_compare(self, value: str) -> str:
        """规范化文本用于去重比较"""
        return re.sub(r"\W+", "", str(value or "")).lower()

    def _render_dimension_text_block(self, label: str, items: List[str], empty_text: str) -> str:
        """渲染维度详情中的结构化文本块"""
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if not cleaned:
            body = f'<div class="dimension-empty">{html.escape(empty_text)}</div>'
        elif len(cleaned) == 1:
            body = f'<div class="dimension-detail-summary">{html.escape(cleaned[0])}</div>'
        else:
            body = (
                '<div class="dimension-detail-list">'
                + "".join(f'<div class="dimension-detail-list-item">{html.escape(item)}</div>' for item in cleaned)
                + "</div>"
            )
        return (
            '<section class="dimension-detail-block">'
            f'<div class="dimension-detail-label">{html.escape(label)}</div>'
            f'{body}'
            '</section>'
        )

    def _render_dimension_radar(self, items: List[Dict[str, Any]], default_index: int) -> str:
        center_x = 240.0
        center_y = 190.0
        radius = 118.0
        label_radius = 158.0
        rings = [0.2, 0.4, 0.6, 0.8, 1.0]
        count = max(len(items), 1)
        step = 360.0 / count

        sector_paths: List[str] = []
        for sector in self.DIMENSION_SECTORS:
            sector_items = [item for item in items if item.get("sector_id") == sector["id"]]
            if not sector_items:
                continue
            start_index = int(sector_items[0]["dashboard_index"])
            end_index = int(sector_items[-1]["dashboard_index"])
            start_angle = -90.0 + start_index * step - step / 2.0
            end_angle = -90.0 + end_index * step + step / 2.0
            sector_paths.append(
                f'<path class="dimension-radar-sector" d="{self._describe_radar_wedge(center_x, center_y, radius, start_angle, end_angle)}" fill="{html.escape(str(sector["color"]))}"></path>'
            )

        ring_html = []
        for ratio in rings:
            ring_radius = radius * ratio
            ring_html.append(f'<circle class="dimension-radar-ring" cx="{center_x:.1f}" cy="{center_y:.1f}" r="{ring_radius:.1f}"></circle>')

        axis_html: List[str] = []
        point_values: List[str] = []
        point_html: List[str] = []
        label_html: List[str] = []
        for item in items:
            index = int(item["dashboard_index"])
            angle = -90.0 + index * step
            outer_x, outer_y = self._polar_to_cartesian(center_x, center_y, radius, angle)
            point_x, point_y = self._polar_to_cartesian(center_x, center_y, radius * float(item["meter_percent"]) / 100.0, angle)
            label_x, label_y = self._polar_to_cartesian(center_x, center_y, label_radius, angle)
            text_anchor = "middle"
            if label_x > center_x + 18:
                text_anchor = "start"
            elif label_x < center_x - 18:
                text_anchor = "end"
            active_class = " is-active" if index == default_index else ""
            axis_html.append(f'<line class="dimension-radar-axis" x1="{center_x:.1f}" y1="{center_y:.1f}" x2="{outer_x:.1f}" y2="{outer_y:.1f}"></line>')
            point_values.append(f"{point_x:.1f},{point_y:.1f}")
            point_html.append(
                f'<circle class="dimension-radar-point{active_class}" data-dimension-index="{index}" cx="{point_x:.1f}" cy="{point_y:.1f}" r="5.8" fill="{html.escape(str(item["sector_accent"]))}"></circle>'
            )
            label_html.append(
                f'<text class="dimension-radar-label{active_class}" data-dimension-index="{index}" x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="{text_anchor}" dominant-baseline="middle">{html.escape(str(item["name"]))}</text>'
            )

        area_html = f'<polygon class="dimension-radar-area" points="{" ".join(point_values)}"></polygon>'
        return (
            '<svg class="dimension-radar-svg" id="dimension-radar-svg" viewBox="0 0 480 380" role="img" aria-label="维度评分雷达图">'
            + "".join(sector_paths)
            + "".join(ring_html)
            + "".join(axis_html)
            + area_html
            + "".join(point_html)
            + "".join(label_html)
            + "</svg>"
        )

    def _polar_to_cartesian(self, center_x: float, center_y: float, radius: float, angle_deg: float) -> tuple[float, float]:
        """极坐标转平面坐标，雷达图专用"""
        angle_rad = math.radians(angle_deg)
        return center_x + radius * math.cos(angle_rad), center_y + radius * math.sin(angle_rad)

    def _describe_radar_wedge(self, center_x: float, center_y: float, radius: float, start_angle: float, end_angle: float) -> str:
        """生成雷达图扇区背景路径"""
        normalized_end = end_angle
        while normalized_end <= start_angle:
            normalized_end += 360.0
        start_x, start_y = self._polar_to_cartesian(center_x, center_y, radius, start_angle)
        end_x, end_y = self._polar_to_cartesian(center_x, center_y, radius, normalized_end)
        large_arc = 1 if normalized_end - start_angle > 180.0 else 0
        return (
            f"M {center_x:.1f} {center_y:.1f} "
            f"L {start_x:.1f} {start_y:.1f} "
            f"A {radius:.1f} {radius:.1f} 0 {large_arc} 1 {end_x:.1f} {end_y:.1f} Z"
        )

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
                <div class="doc-toast" id="doc-toast"></div>
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
            <div class="doc-toast" id="doc-toast"></div>
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
            const toast = document.getElementById("doc-toast");
            const pageMap = __PACKET_PAGE_MAP__;
            if (!viewer && !packetFrame) return;

            const normalize = (value) => String(value || "")
              .replace(/\\s+/g, "")
              .replace(/[，。；：、“”‘’（）()【】《》,.!?\\-]/g, "")
              .trim();

            let activeTimer = null;
            let toastTimer = null;

            const showDocumentToast = (message) => {
              if (!toast) return;
              if (toastTimer) window.clearTimeout(toastTimer);
              toast.textContent = String(message || "");
              toast.classList.add("show");
              toastTimer = window.setTimeout(() => {
                toast.classList.remove("show");
                toast.textContent = "";
              }, 1800);
            };

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
              if (!Array.isArray(rects) || !rects.length) {
                showDocumentToast("未定位到精确片段，已跳转到对应页。");
              }
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
              if (!viewer) return false;
              const pageNode = viewer.querySelector(`.doc-page[data-page="${page}"]`);
              if (!pageNode) {
                showDocumentToast("未找到对应正文页。");
                return false;
              }

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
              if (!matchedChunk) {
                showDocumentToast("未定位到精确片段，已跳转到对应页。");
              }

              if (activeTimer) window.clearTimeout(activeTimer);
              activeTimer = window.setTimeout(() => {
                pageNode.classList.remove("is-active");
                if (matchedChunk) matchedChunk.classList.remove("is-match");
              }, 3600);
              return Boolean(matchedChunk);
            };

            const handleJumpTrigger = (trigger) => {
              if (!trigger) return;
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
            };

            window.__evaluationJumpToTrigger = handleJumpTrigger;

            document.addEventListener("click", (event) => {
              const trigger = event.target.closest("[data-doc-jump]");
              if (!trigger) return;
              event.preventDefault();
              handleJumpTrigger(trigger);
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
        configured_api_base = str(os.getenv("EVALUATION_REPORT_API_BASE", "")).strip().rstrip("/")
        default_api_base = configured_api_base or f"http://127.0.0.1:{default_port}"
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
          <div
            class="chat-shell"
            id="chat-shell"
            data-evaluation-id="{escaped_eval_id}"
            data-chat-ready="{str(chat_ready).lower()}"
            data-default-api-base="{escaped_default_api_base}"
            data-default-port="{escaped_default_port}"
          >
              <div class="chat-progress" id="chat-progress">
                <div class="chat-progress-head">
                  <div class="chat-progress-title">问答生成过程</div>
                  <div class="chat-progress-status" id="chat-progress-status">等待提问</div>
                </div>
                <div class="chat-progress-steps" id="chat-progress-steps">
                  <div class="chat-progress-step" data-step="context">
                    <div class="chat-progress-step-label">上下文</div>
                    <div class="chat-progress-step-detail">读取评审记录与索引</div>
                  </div>
                  <div class="chat-progress-step" data-step="retrieve">
                    <div class="chat-progress-step-label">检索</div>
                    <div class="chat-progress-step-detail">定位正文证据</div>
                  </div>
                  <div class="chat-progress-step" data-step="evidence">
                    <div class="chat-progress-step-label">整理</div>
                    <div class="chat-progress-step-detail">收敛依据与不足</div>
                  </div>
                  <div class="chat-progress-step" data-step="answer">
                    <div class="chat-progress-step-label">回答</div>
                    <div class="chat-progress-step-detail">生成专家结论</div>
                  </div>
                </div>
              </div>
              <div class="chat-suggestions" id="chat-suggestions">
                {suggestions_block}
              </div>
              <div class="chat-thread" id="chat-thread">
                <div class="chat-empty" id="chat-empty">围绕研究目标、创新点、验证数据、进展与量产可行性直接提问。回答会附证据并支持联动原文。</div>
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
            const progressStatusNode = document.getElementById("chat-progress-status");
            const progressSteps = Array.from(shell.querySelectorAll(".chat-progress-step"));
            const getSuggestionButtons = () => Array.from(shell.querySelectorAll(".chat-suggestion, .chat-followup"));

            const configuredBase = shell.dataset.defaultApiBase || "";
            const configuredPort = shell.dataset.defaultPort || "";

            const detectDefaultBase = () => {{
              if (window.location.protocol === "http:" || window.location.protocol === "https:") {{
                return window.location.origin;
              }}
              return configuredBase || `http://127.0.0.1:${{configuredPort || "8888"}}`;
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
              getSuggestionButtons().forEach((button) => {{
                button.disabled = busy || !evaluationId;
              }});
              if (statusNode) {{
                statusNode.textContent = text || (busy ? "正在生成回答..." : "等待提问");
              }}
              if (progressStatusNode) {{
                progressStatusNode.textContent = text || (busy ? "正在生成回答..." : "等待提问");
              }}
            }};

            const getProgressStepKey = (message) => {{
              const text = String(message || "");
              if (text.includes("评审记录") || text.includes("聊天索引")) return "context";
              if (text.includes("识别问题类型") || text.includes("检索")) return "retrieve";
              if (text.includes("整理证据") || text.includes("规则化回答")) return "evidence";
              if (text.includes("模型") || text.includes("回答")) return "answer";
              return "";
            }};

            const setProgressState = (activeKey = "", message = "") => {{
              const stepOrder = ["context", "retrieve", "evidence", "answer"];
              const activeIndex = stepOrder.indexOf(activeKey);
              progressSteps.forEach((node, index) => {{
                const done = activeIndex > index;
                const active = activeIndex === index;
                node.classList.toggle("is-done", done);
                node.classList.toggle("is-active", active);
              }});
              if (!activeKey) {{
                progressSteps.forEach((node) => {{
                  node.classList.remove("is-done", "is-active");
                }});
              }}
              if (progressStatusNode) {{
                progressStatusNode.textContent = message || (activeKey ? "处理中" : "等待提问");
              }}
            }};

            const removeEmptyState = () => {{
              document.getElementById("chat-empty")?.remove();
            }};

            const escapeRegExp = (value) => String(value || "").replace(/[][.*+?^${{}}()|\\\\]/g, "\\\\$&");

            const detectQuestionTag = (question) => {{
              const text = String(question || "");
              if (text.includes("研究目标") || text.includes("项目目标") || text.includes("总体目标")) return "研究目标";
              if (text.includes("创新点") || text.includes("创新")) return "创新点";
              if (text.includes("验证") || text.includes("数据") || text.includes("测试")) return "验证数据";
              if (text.includes("量产") || text.includes("产业化") || text.includes("转化")) return "量产判断";
              if (text.includes("进展") || text.includes("阶段") || text.includes("进度")) return "进展程度";
              if (text.includes("成果") || text.includes("效益")) return "成果效益";
              return "综合判断";
            }};

            const getQuestionKeywords = (question) => {{
              const text = String(question || "");
              const keywords = [];
              const add = (values) => values.forEach((value) => {{
                if (value && !keywords.includes(value)) keywords.push(value);
              }});
              if (text.includes("研究目标") || text.includes("项目目标") || text.includes("总体目标")) add(["目标", "建设", "研究"]);
              if (text.includes("创新点") || text.includes("创新")) add(["创新", "技术", "模式"]);
              if (text.includes("验证") || text.includes("数据") || text.includes("测试")) add(["验证", "数据", "试验", "测试", "样本", "指标"]);
              if (text.includes("量产") || text.includes("产业化") || text.includes("转化")) add(["量产", "产业化", "转化", "中试", "产线"]);
              if (text.includes("进展") || text.includes("阶段") || text.includes("进度")) add(["进展", "阶段", "完成", "计划"]);
              if (text.includes("成果") || text.includes("效益")) add(["成果", "效益", "指标", "产出"]);
              return keywords.slice(0, 6);
            }};

            const highlightText = (text, question) => {{
              let result = escapeHtml(text || "-");
              const keywords = getQuestionKeywords(question);
              keywords.forEach((keyword) => {{
                if (!keyword) return;
                const pattern = new RegExp(`(${{escapeRegExp(keyword)}})`, "g");
                result = result.replace(pattern, "<mark>$1</mark>");
              }});
              return result;
            }};

            const parseStructuredAnswer = (text) => {{
              const normalized = String(text || "").replace(/\\r/g, "").trim();
              if (!normalized) return null;
              const conclusionMatch = normalized.match(/结论：([\\s\\S]*?)(?=\\n依据：|\\n不足：|$)/);
              const basisMatch = normalized.match(/依据：([\\s\\S]*?)(?=\\n不足：|$)/);
              const gapMatch = normalized.match(/不足：([\\s\\S]*)$/);
              if (!conclusionMatch && !basisMatch && !gapMatch) return null;
              const basisItems = (basisMatch?.[1] || "")
                .split(/\\n(?=\\d+[.、]|[-•])/)
                .map((item) => item.replace(/^\\s*(\\d+[.、]|[-•])\\s*/, "").trim())
                .filter(Boolean);
              return {{
                conclusion: (conclusionMatch?.[1] || "").trim(),
                basisItems,
                gap: (gapMatch?.[1] || "").trim(),
              }};
            }};

            const buildFollowUps = (question) => {{
              const text = String(question || "");
              if (text.includes("研究目标") || text.includes("项目目标") || text.includes("总体目标")) {{
                return ["这些目标有验证数据支撑吗？", "当前进展到什么程度了？", "目标里哪些是量化指标？"];
              }}
              if (text.includes("创新点") || text.includes("创新")) {{
                return ["这些创新点有验证数据吗？", "这些创新目前做到什么程度了？", "哪些创新更接近实际转化？"];
              }}
              if (text.includes("验证") || text.includes("数据") || text.includes("测试")) {{
                return ["这些验证是已完成还是计划开展？", "验证数据对应哪一页最关键？", "这些结果足以支持量产判断吗？"];
              }}
              if (text.includes("量产") || text.includes("产业化") || text.includes("转化")) {{
                return ["缺少哪些证据才能判断可以量产？", "当前更像示范应用还是产业化？", "文档里有中试或产线信息吗？"];
              }}
              return ["这项工作目前进展到什么程度了？", "申报书里有验证数据吗？", "这项技术有可能量产吗？"];
            }};

            const buildCitationHtml = (citations = [], question = "") => {{
              if (!citations.length) return "";
              return `<div class="chat-citations">${{citations.map((citation, index) => `
                <div class="chat-citation">
                  <div class="chat-citation-head">
                    <div class="chat-citation-label">证据 ${{index + 1}}</div>
                    <div class="chat-citation-page">第 ${{escapeHtml(citation.page || "-")}} 页</div>
                  </div>
                  <div class="chat-citation-actions">
                    <a
                      class="jump-link"
                      href="#doc-page-${{escapeHtml(citation.page || "-")}}"
                      data-doc-jump="true"
                      data-chat-citation="true"
                      data-evaluation-id="${{escapeHtml(evaluationId)}}"
                      data-page="${{escapeHtml(citation.page || "")}}"
                      data-file="${{escapeHtml(citation.file || "")}}"
                      data-snippet="${{escapeHtml(String(citation.snippet || '').replace(/\\s+/g, '').slice(0, 120))}}"
                      data-highlight-text="${{escapeHtml(citation.snippet || "")}}"
                      data-packet-page="${{escapeHtml(citation.packet_page || "")}}"
                      data-highlight-rects='${{escapeHtml(JSON.stringify(citation.highlight_rects || []))}}'
                    >查看原文</a>
                  </div>
                </div>
              `).join("")}}</div>`;
            }};

            const buildMessageHtml = (role, text, citations = [], followUps = [], question = "") => {{
              const parsed = role === "assistant" ? parseStructuredAnswer(text) : null;
              const citationHtml = buildCitationHtml(citations, question);
              const followUpHtml = followUps.length
                ? `<div class="chat-followups">${{followUps.map((item) => `<button type="button" class="chat-followup" data-question="${{escapeHtml(item)}}">${{escapeHtml(item)}}</button>`).join("")}}</div>`
                : "";

              if (parsed) {{
                const tag = detectQuestionTag(question);
                const basisHtml = parsed.basisItems.length
                  ? `<ol class="chat-answer-list">${{parsed.basisItems.map((item) => `<li>${{escapeHtml(item)}}</li>`).join("")}}</ol>`
                  : `<div class="chat-answer-text">${{escapeHtml(text)}}</div>`;
                const gapHtml = parsed.gap
                  ? `<section class="chat-answer-block"><div class="chat-answer-head">不足</div><div class="chat-answer-text">${{escapeHtml(parsed.gap)}}</div></section>`
                  : "";
                return `
                  <div class="chat-role">${{escapeHtml(role)}}</div>
                  <div class="chat-answer">
                    <div class="chat-answer-meta">
                      <div class="chat-answer-tag">${{escapeHtml(tag)}}</div>
                      <div class="chat-answer-summary">依据 ${{parsed.basisItems.length || 1}} 条 · 证据 ${{citations.length}}</div>
                    </div>
                    <section class="chat-answer-block chat-answer-block-primary">
                      <div class="chat-answer-head">结论</div>
                      <div class="chat-answer-text">${{escapeHtml(parsed.conclusion || text)}}</div>
                    </section>
                    <section class="chat-answer-block">
                      <div class="chat-answer-head">依据</div>
                      ${{basisHtml}}
                    </section>
                    ${{gapHtml}}
                  </div>
                  ${{citationHtml}}
                  ${{followUpHtml}}
                `;
              }}
              return `
                <div class="chat-role">${{escapeHtml(role)}}</div>
                <div class="chat-body">${{escapeHtml(text)}}</div>
                ${{citationHtml}}
                ${{followUpHtml}}
              `;
            }};

            const appendMessage = (role, text, citations = [], followUps = [], question = "") => {{
              removeEmptyState();
              const wrapper = document.createElement("div");
              wrapper.className = `chat-msg ${{role === "user" ? "chat-msg-user" : "chat-msg-assistant"}}`;
              wrapper.innerHTML = buildMessageHtml(role, text, citations, followUps, question);
              thread.appendChild(wrapper);
              thread.scrollTop = thread.scrollHeight;
              return wrapper;
            }};

            const createStreamingAssistantMessage = () => {{
              removeEmptyState();
              const wrapper = document.createElement("div");
              wrapper.className = "chat-msg chat-msg-assistant";
              wrapper.innerHTML = `
                <div class="chat-role">assistant</div>
                <div class="chat-live">
                  <div class="chat-live-head">
                    <div class="chat-live-title">回答生成中</div>
                    <div class="chat-live-phase">正在生成回答...</div>
                  </div>
                  <div class="chat-live-text"></div>
                  <div class="chat-live-skeleton">
                    <div class="chat-live-line"></div>
                    <div class="chat-live-line is-mid"></div>
                    <div class="chat-live-line is-short"></div>
                  </div>
                </div>
              `;
              thread.appendChild(wrapper);
              thread.scrollTop = thread.scrollHeight;
              const bodyNode = wrapper.querySelector(".chat-live-text");
              const phaseNode = wrapper.querySelector(".chat-live-phase");
              const skeletonNode = wrapper.querySelector(".chat-live-skeleton");
              let currentText = "";
              let phaseText = "正在生成回答...";
              return {{
                setPhase(text) {{
                  phaseText = String(text || "").trim() || phaseText;
                  if (phaseNode) phaseNode.textContent = phaseText;
                  if (bodyNode && !currentText) bodyNode.textContent = phaseText;
                  thread.scrollTop = thread.scrollHeight;
                }},
                update(delta) {{
                  currentText += String(delta || "");
                  if (bodyNode) {{
                    bodyNode.textContent = currentText || phaseText;
                  }}
                  if (skeletonNode && currentText.trim()) skeletonNode.style.display = "none";
                  thread.scrollTop = thread.scrollHeight;
                }},
                finalize(text, citations = [], followUps = [], question = "") {{
                  currentText = String(text || "");
                  wrapper.innerHTML = buildMessageHtml("assistant", currentText || "未返回回答", citations, followUps, question);
                  thread.scrollTop = thread.scrollHeight;
                }},
                hasContent() {{
                  return Boolean(currentText.trim());
                }},
                getText() {{
                  return currentText;
                }},
                getPhase() {{
                  return phaseText;
                }},
              }};
            }};

            const normalizeBase = (value) => String(value || "").trim().replace(/\\/+$/, "");

            const fetchCitationHighlight = async (trigger) => {{
              const payload = {{
                evaluation_id: trigger.dataset.evaluationId || evaluationId,
                file: trigger.dataset.file || "",
                page: Number(trigger.dataset.page || 0),
                snippet: trigger.dataset.highlightText || "",
              }};
              const response = await fetch(`${{normalizeBase(apiBase)}}/api/v1/evaluation/chat/citation-highlight`, {{
                method: "POST",
                headers: {{
                  "Content-Type": "application/json",
                }},
                body: JSON.stringify(payload),
              }});
              const data = await response.json().catch(() => ({{ detail: "高亮补全响应不可解析" }}));
              if (!response.ok) {{
                throw new Error(data.detail || `请求失败：${{response.status}}`);
              }}
              if (data.packet_page) {{
                trigger.dataset.packetPage = String(data.packet_page);
              }}
              if (Array.isArray(data.highlight_rects)) {{
                trigger.dataset.highlightRects = JSON.stringify(data.highlight_rects);
              }}
            }};

            const requestChatAnswer = async (text) => {{
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
              return payload;
            }};

            const parseSseFrame = (frame) => {{
              const lines = String(frame || "").split(/\\r?\\n/);
              let eventName = "message";
              const dataLines = [];
              lines.forEach((line) => {{
                if (!line) return;
                if (line.startsWith("event:")) {{
                  eventName = line.slice(6).trim() || "message";
                  return;
                }}
                if (line.startsWith("data:")) {{
                  dataLines.push(line.slice(5).trim());
                }}
              }});
              const rawData = dataLines.join("\\n");
              let payload = {{}};
              if (rawData) {{
                payload = JSON.parse(rawData);
              }}
              return {{ eventName, payload }};
            }};

            const requestChatAnswerStream = async (text, streamMessage) => {{
              const response = await fetch(`${{normalizeBase(apiBase)}}/api/v1/evaluation/chat/ask-stream`, {{
                method: "POST",
                headers: {{
                  "Content-Type": "application/json",
                }},
                body: JSON.stringify({{
                  evaluation_id: evaluationId,
                  question: text,
                }}),
              }});

              if (!response.ok) {{
                const payload = await response.json().catch(() => ({{ detail: "流式接口返回了不可解析响应" }}));
                throw new Error(payload.detail || `请求失败：${{response.status}}`);
              }}
              if (!response.body || typeof response.body.getReader !== "function") {{
                throw new Error("当前环境不支持流式响应");
              }}

              const reader = response.body.getReader();
              const decoder = new TextDecoder("utf-8");
              let buffer = "";
              let answer = "";
              let citations = [];
              let completed = false;

              while (true) {{
                const {{ value, done }} = await reader.read();
                buffer += decoder.decode(value || new Uint8Array(), {{ stream: !done }});
                const frames = buffer.split("\\n\\n");
                buffer = frames.pop() || "";

                for (const frame of frames) {{
                  if (!frame.trim()) continue;
                  const {{ eventName, payload }} = parseSseFrame(frame);
                  if (eventName === "status") {{
                    const message = String(payload.message || "正在处理中");
                    setBusy(true, message);
                    streamMessage.setPhase(message);
                    setProgressState(getProgressStepKey(message), message);
                    continue;
                  }}
                  if (eventName === "delta") {{
                    const delta = String(payload.text || "");
                    answer += delta;
                    streamMessage.update(delta);
                    continue;
                  }}
                  if (eventName === "done") {{
                    answer = String(payload.answer || answer || "");
                    citations = Array.isArray(payload.citations) ? payload.citations : [];
                    completed = true;
                    continue;
                  }}
                  if (eventName === "error") {{
                    throw new Error(payload.message || "流式问答失败");
                  }}
                }}

                if (done) {{
                  break;
                }}
              }}

              if (!completed) {{
                throw new Error("流式响应提前结束");
              }}
              return {{ answer, citations }};
            }};

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
              setProgressState("context", "正在定位本次问答上下文");
              const streamMessage = createStreamingAssistantMessage();

              try {{
                let payload;
                try {{
                  payload = await requestChatAnswerStream(text, streamMessage);
                }} catch (streamError) {{
                  if (streamMessage.hasContent()) {{
                    throw streamError;
                  }}
                  payload = await requestChatAnswer(text);
                }}

                streamMessage.finalize(
                  payload.answer || "未返回回答",
                  Array.isArray(payload.citations) ? payload.citations : [],
                  buildFollowUps(text),
                  text,
                );
                setProgressState("", "本次回答已生成");
                setBusy(false, "回答已生成");
              }} catch (error) {{
                const partial = streamMessage.getText();
                if (partial) {{
                  streamMessage.finalize(`${{partial}}\\n\\n流式中断，请重试。`, [], [], text);
                }} else {{
                  streamMessage.finalize(`调用失败：${{error.message || streamMessage.getPhase() || "未知错误"}}`, [], [], text);
                }}
                setProgressState("", "调用失败");
                setBusy(false, "调用失败");
              }}
            }};

            form.addEventListener("submit", async (event) => {{
              event.preventDefault();
              await askQuestion(questionInput.value);
            }});

            shell.addEventListener("click", async (event) => {{
              const button = event.target.closest(".chat-suggestion, .chat-followup");
              if (button) {{
                await askQuestion(button.dataset.question || button.textContent || "");
                return;
              }}

              const trigger = event.target.closest("[data-chat-citation]");
              if (!trigger) return;
              event.preventDefault();
              event.stopPropagation();
              let rects = [];
              try {{
                rects = JSON.parse(trigger.dataset.highlightRects || "[]");
              }} catch (error) {{
                rects = [];
              }}
              if (!rects.length && trigger.dataset.evaluationId) {{
                try {{
                  await fetchCitationHighlight(trigger);
                }} catch (error) {{
                  console.warn("citation highlight fetch failed", error);
                }}
              }}
              window.__evaluationJumpToTrigger?.(trigger);
            }});

            setProgressState("", chatReady ? "等待提问" : "可直接提问（首次会自动建索引）");
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
        highlight_payload = self._resolve_packet_highlight_payload(
            packet_assets,
            packet_page,
            snippet,
            source_file=source_file,
        )
        return {
            "packet_page": highlight_payload.get("page") or packet_page,
            "highlight_rects": highlight_payload.get("rects") or [],
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

        exact_match = None
        proposal_match = None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_file") or "")
            if self._packet_source_matches(source_file, item):
                exact_match = item
                break
            if self._is_same_proposal_family(source_file, item_source) and str(item.get("source_kind") or "") == "proposal":
                proposal_match = proposal_match or item
        matched = exact_match or proposal_match
        if matched is None:
            matched = next((item for item in page_map if str(item.get("source_kind") or "") == "proposal"), None)
        if not isinstance(matched, dict):
            return page
        start_page = int(matched.get("start_page", 0) or 0)
        end_page = int(matched.get("end_page", start_page) or start_page)
        if start_page <= 0:
            return page
        return min(start_page + max(page, 1) - 1, end_page if end_page >= start_page else start_page)

    def _resolve_packet_highlight_payload(
        self,
        packet_assets: Dict[str, Any],
        packet_page: int,
        snippet: str,
        source_file: str = "",
    ) -> Dict[str, Any]:
        """在 packet 中搜索最可能的片段位置并生成高亮框"""
        if not isinstance(packet_assets, dict):
            return {"page": packet_page, "rects": []}
        packet_abs_path = str(packet_assets.get("packet_abs_path") or "").strip()
        if not packet_abs_path or not os.path.exists(packet_abs_path) or packet_page <= 0:
            return {"page": packet_page, "rects": []}
        text = self._condense_highlight_text(snippet)
        if not text:
            return {"page": packet_page, "rects": []}
        candidates = self._build_packet_highlight_candidates(text)
        if not candidates:
            return {"page": packet_page, "rects": []}

        with fitz.open(packet_abs_path) as packet_doc:
            if packet_page > packet_doc.page_count:
                return {"page": packet_page, "rects": []}
            primary_pages, fallback_pages = self._build_packet_search_pages(
                packet_assets,
                source_file,
                packet_page,
                packet_doc.page_count,
            )
            matched_page, _, rects = self._search_packet_pages_highlights(
                packet_doc,
                primary_pages,
                candidates,
                packet_page,
            )
            if not rects and fallback_pages:
                matched_page, _, rects = self._search_packet_pages_highlights(
                    packet_doc,
                    fallback_pages,
                    candidates,
                    packet_page,
                )
            if rects:
                return {"page": matched_page or packet_page, "rects": rects}

            line_page, line_rects = self._search_packet_pages_line_rects(
                packet_doc,
                primary_pages,
                candidates,
            )
            if not line_rects and fallback_pages:
                line_page, line_rects = self._search_packet_pages_line_rects(
                    packet_doc,
                    fallback_pages,
                    candidates,
                )
            if line_rects:
                return {"page": line_page or packet_page, "rects": line_rects}
        return {"page": packet_page, "rects": []}

    def _build_packet_highlight_candidates(self, text: str) -> List[str]:
        """为 packet 检索生成逐级降级候选文本"""
        normalized = str(text or "").strip()
        if not normalized:
            return []

        candidates: List[str] = []
        for line in re.split(r"[\n\r]+", normalized):
            stripped = line.strip(" -:：;；,.，。|")
            if stripped:
                candidates.append(stripped)
            for part in re.split(r"[|｜]", stripped):
                part = part.strip(" -:：;；,.，。")
                if part:
                    candidates.append(part)

        for token in re.split(r"[\s,，。;；:：/\\()（）_-]+", normalized):
            token = token.strip(" -|")
            compact = re.sub(r"\s+", "", token)
            if re.search(r"[\u4e00-\u9fff]", compact):
                if len(compact) >= 4:
                    candidates.append(compact)
                    candidates.extend(self._build_chinese_fragment_candidates(compact))
            elif len(compact) >= 6:
                candidates.append(compact)

        deduped: List[str] = []
        seen = set()
        for candidate in sorted(candidates, key=len, reverse=True):
            compact = re.sub(r"\s+", "", candidate)
            if len(compact) < 4:
                continue
            key = compact[:120]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate[:120])
            if len(deduped) >= 12:
                break
        return deduped

    def _build_chinese_fragment_candidates(self, text: str) -> List[str]:
        """为长中文串补充可搜索片段，适配 PDF 断行场景"""
        compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(text or ""))
        if len(compact) < 8:
            return []
        fragments: List[str] = []
        for window in (12, 10, 8, 6):
            if len(compact) < window:
                continue
            fragments.append(compact[:window])
            fragments.append(compact[-window:])
            for start in range(0, len(compact) - window + 1, max(1, window // 2)):
                fragments.append(compact[start:start + window])
        return fragments[:24]

    def _build_packet_search_pages(
        self,
        packet_assets: Dict[str, Any],
        source_file: str,
        packet_page: int,
        packet_page_count: int,
    ) -> tuple[List[int], List[int]]:
        """构造 packet 搜索页范围：先搜附近页，再扩到源文件对应页段"""
        primary_pages: List[int] = []
        fallback_pages: List[int] = []
        primary_seen = set()
        fallback_seen = set()

        def append_primary(page_number: int) -> None:
            if 1 <= page_number <= packet_page_count and page_number not in primary_seen:
                primary_seen.add(page_number)
                primary_pages.append(page_number)

        def append_fallback(page_number: int) -> None:
            if 1 <= page_number <= packet_page_count and page_number not in primary_seen and page_number not in fallback_seen:
                fallback_seen.add(page_number)
                fallback_pages.append(page_number)

        append_primary(packet_page)
        for offset in range(1, 3):
            append_primary(packet_page - offset)
            append_primary(packet_page + offset)

        page_range = self._resolve_source_packet_range(packet_assets, source_file)
        if page_range:
            start_page, end_page = page_range
            if start_page > end_page:
                start_page, end_page = end_page, start_page
            for page_number in range(start_page, min(end_page, packet_page_count) + 1):
                append_fallback(page_number)
        return primary_pages, fallback_pages

    def _resolve_source_packet_range(self, packet_assets: Dict[str, Any], source_file: str) -> tuple[int, int] | None:
        """读取 source_file 在 packet 中对应的页范围"""
        if not isinstance(packet_assets, dict):
            return None
        page_map = packet_assets.get("page_map", [])
        if not isinstance(page_map, list):
            return None
        exact_match = None
        proposal_match = None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_file") or "")
            if self._packet_source_matches(source_file, item):
                exact_match = item
                break
            if self._is_same_proposal_family(source_file, item_source) and str(item.get("source_kind") or "") == "proposal":
                proposal_match = proposal_match or item
        matched = exact_match or proposal_match
        if not isinstance(matched, dict):
            return None
        start_page = matched.get("start_page")
        end_page = matched.get("end_page")
        if isinstance(start_page, int) and isinstance(end_page, int) and start_page > 0 and end_page > 0:
            return start_page, end_page
        if isinstance(start_page, int) and start_page > 0:
            return start_page, start_page
        return None

    def _search_packet_pages_highlights(
        self,
        packet_doc: fitz.Document,
        page_numbers: List[int],
        candidates: List[str],
        preferred_page: int,
    ) -> tuple[int | None, str, List[Dict[str, float]]]:
        """在多个 packet 页中查找最优文本高亮页"""
        best_page: int | None = None
        best_text = ""
        best_rects: List[Dict[str, float]] = []
        best_score = -10**9
        best_order = 10**9

        normalized_candidates = [candidate for candidate in candidates if str(candidate).strip()]
        for page_number in page_numbers:
            if page_number <= 0 or page_number > packet_doc.page_count:
                continue
            page = packet_doc.load_page(page_number - 1)
            page_rect = page.rect
            if page_rect.width <= 0 or page_rect.height <= 0:
                continue
            matched_candidate = ""
            matched_rects: List[Dict[str, float]] = []
            matched_score = -10**9
            for candidate in normalized_candidates:
                search_hits = page.search_for(candidate)
                if search_hits:
                    rect_payload = self._merge_highlight_rects(search_hits[:6], page_rect)
                    if not rect_payload:
                        continue
                    area_penalty = sum(float(item.get("w", 0)) * float(item.get("h", 0)) for item in rect_payload)
                    candidate_score = (
                        len(re.sub(r"\s+", "", candidate)) * 100
                        - len(rect_payload) * 20
                        - int(area_penalty * 10000)
                    )
                    if candidate_score > matched_score:
                        matched_score = candidate_score
                        matched_candidate = candidate
                        matched_rects = rect_payload
            if not matched_rects:
                continue

            score = matched_score - abs(page_number - preferred_page) * 450
            page_order = page_numbers.index(page_number)
            if score > best_score or (score == best_score and page_order < best_order):
                best_score = score
                best_order = page_order
                best_page = page_number
                best_text = matched_candidate
                best_rects = matched_rects
        return best_page, best_text, best_rects

    def _condense_highlight_text(self, snippet: str, max_len: int = 180) -> str:
        """压缩片段文本，避免长段导致高亮漂移"""
        text = re.sub(r"\s+", " ", str(snippet or "")).strip()
        if len(text) <= max_len:
            return text
        return text[:max_len].rstrip() + "..."

    def _search_packet_pages_line_rects(
        self,
        packet_doc: fitz.Document,
        page_numbers: List[int],
        candidates: List[str],
    ) -> tuple[int | None, List[Dict[str, float]]]:
        """当 search_for 失败时，退化为行级近似匹配"""
        best_page: int | None = None
        best_rects: List[Dict[str, float]] = []
        best_score = 0
        for page_number in page_numbers:
            if page_number <= 0 or page_number > packet_doc.page_count:
                continue
            page = packet_doc.load_page(page_number - 1)
            page_rect = page.rect
            if page_rect.width <= 0 or page_rect.height <= 0:
                continue
            line_rect, score = self._find_line_rect_by_candidates(page, candidates)
            if line_rect is None or score <= best_score:
                continue
            best_page = page_number
            best_score = score
            best_rects = self._merge_highlight_rects([line_rect], page_rect)
        return best_page, best_rects

    def _find_line_rect_by_candidates(self, page: fitz.Page, candidates: List[str]) -> tuple[fitz.Rect | None, int]:
        """按行文本近似匹配候选片段"""
        line_items = self._extract_page_line_items(page)
        if not line_items:
            return None, 0
        best_rect = None
        best_score = 0
        for candidate in candidates:
            normalized_candidate = self._normalize_packet_text(candidate)
            if len(normalized_candidate) < 4:
                continue
            for item in line_items:
                normalized_line = item["normalized_text"]
                if not normalized_line:
                    continue
                if normalized_candidate in normalized_line or normalized_line in normalized_candidate:
                    score = min(len(normalized_candidate), len(normalized_line)) * 100
                else:
                    score = self._shared_substring_score(normalized_candidate, normalized_line) * 100
                if score > best_score:
                    best_score = score
                    best_rect = fitz.Rect(item["rect"])
        if best_score < 600:
            return None, 0
        return best_rect, best_score

    def _extract_page_line_items(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """按行聚合页面文本"""
        words = page.get_text("words")
        grouped: Dict[tuple[int, int], List[Any]] = {}
        for word in words:
            if len(word) < 8:
                continue
            key = (int(word[5]), int(word[6]))
            grouped.setdefault(key, []).append(word)
        items: List[Dict[str, Any]] = []
        for entries in grouped.values():
            ordered = sorted(entries, key=lambda item: (item[1], item[0]))
            text = "".join(str(item[4]) for item in ordered).strip()
            if not text:
                continue
            rects = [fitz.Rect(item[:4]) for item in ordered]
            merged = self._union_rects(rects)
            if not merged:
                continue
            items.append(
                {
                    "text": text,
                    "normalized_text": self._normalize_packet_text(text),
                    "rect": merged,
                }
            )
        return sorted(items, key=lambda item: (item["rect"].y0, item["rect"].x0))

    def _normalize_packet_text(self, value: Any) -> str:
        """归一化 packet 文本，便于页级/行级匹配"""
        text = str(value or "")
        return re.sub(r"\s+", "", text)

    def _union_rects(self, rects: List[fitz.Rect]) -> fitz.Rect | None:
        """合并多个 rect"""
        valid = [fitz.Rect(rect) for rect in rects if rect is not None]
        if not valid:
            return None
        merged = fitz.Rect(valid[0])
        for rect in valid[1:]:
            merged |= rect
        return merged

    def _shared_substring_score(self, left: str, right: str) -> int:
        """粗略评估两个文本的最大公共子串长度"""
        best = 0
        max_window = min(24, len(left), len(right))
        min_window = 6
        for window in range(max_window, min_window - 1, -1):
            for start in range(0, len(left) - window + 1):
                snippet = left[start:start + window]
                if snippet and snippet in right:
                    return window
        return best

    def _is_same_proposal_family(self, left: str, right: str) -> bool:
        """判断两个路径是否指向同一项目的申报书不同格式"""
        left_path = Path(str(left or ""))
        right_path = Path(str(right or ""))
        if not left_path.name or not right_path.name:
            return False
        if left_path.parent != right_path.parent:
            return False
        return left_path.stem == right_path.stem

    def _packet_source_matches(self, source_file: str, item: Dict[str, Any]) -> bool:
        """判断引用文件是否命中 packet 映射项，兼容仅传文件名的情况"""
        source_value = str(source_file or "").strip()
        if not source_value:
            return False
        item_source = str(item.get("source_file") or "").strip()
        item_name = str(item.get("source_name") or "").strip()
        source_name = Path(source_value).name
        if item_source == source_value:
            return True
        if item_name and item_name == source_name:
            return True
        if item_source and Path(item_source).name == source_name:
            return True
        return False

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
            last = merged[-1]
            same_band = (
                abs(current.y0 - last.y0) <= vertical_gap
                or abs(current.y1 - last.y1) <= vertical_gap
                or current.intersects(last)
            )
            close_horizontally = current.x0 <= last.x1 + horizontal_gap
            close_vertically = current.y0 <= last.y1 + vertical_gap
            if same_band and close_horizontally and close_vertically:
                merged[-1] = fitz.Rect(
                    min(last.x0, current.x0),
                    min(last.y0, current.y0),
                    max(last.x1, current.x1),
                    max(last.y1, current.y1),
                )
            else:
                merged.append(current)

        result: List[Dict[str, float]] = []
        pad_x = page_rect.width * 0.012
        pad_y = page_rect.height * 0.008
        for rect in merged[:4]:
            expanded = fitz.Rect(
                max(page_rect.x0, rect.x0 - pad_x),
                max(page_rect.y0, rect.y0 - pad_y),
                min(page_rect.x1, rect.x1 + pad_x),
                min(page_rect.y1, rect.y1 + pad_y),
            )
            result.append(
                {
                    "x": round(max(0.0, min(1.0, expanded.x0 / page_rect.width)), 6),
                    "y": round(max(0.0, min(1.0, expanded.y0 / page_rect.height)), 6),
                    "w": round(max(0.0, min(1.0, expanded.width / page_rect.width)), 6),
                    "h": round(max(0.0, min(1.0, expanded.height / page_rect.height)), 6),
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
            if value and not self.HASH_SOURCE_NAME_RE.match(value):
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
                    f'<div class="highlight-item-evidence">证据：{html.escape(str(snippet))}</div>'
                    f'<div class="jump-link-row">{self._render_jump_link(page, snippet, str(evidence.get("file") or ""), packet_assets)}</div>'
                )
            rows.append(
                f"""
                <div class="highlight-item">
                  <div class="highlight-item-text">{html.escape(text)}</div>
                  {meta_html}
                </div>
                """
            )
        return '<div class="highlight-list">' + "".join(rows) + "</div>"

    def _render_flat_list(self, items: List[Any], empty_text: str) -> str:
        """渲染扁平条目列表"""
        if not items:
            return f'<div class="empty">{html.escape(empty_text)}</div>'

        rows = [f'<div class="flat-item">{html.escape(str(item))}</div>' for item in items if str(item).strip()]
        if not rows:
            return f'<div class="empty">{html.escape(empty_text)}</div>'
        return '<div class="flat-list">' + "".join(rows) + "</div>"

    def _render_industry_fit(self, industry_fit: Dict[str, Any] | None) -> str:
        if not industry_fit:
            return '<div class="empty">未启用或暂无结果</div>'
        return (
            '<div class="flat-stack">'
            f'<section class="flat-section"><div class="flat-label">贴合度</div><div class="flat-value">{html.escape(str(industry_fit.get("fit_score", "-")))}</div></section>'
            f'<section class="flat-section"><div class="flat-label">匹配项</div>{self._render_flat_list(industry_fit.get("matched") or [], "暂无")}</section>'
            f'<section class="flat-section"><div class="flat-label">差距项</div>{self._render_flat_list(industry_fit.get("gaps") or [], "暂无")}</section>'
            f'<section class="flat-section"><div class="flat-label">建议</div>{self._render_flat_list(industry_fit.get("suggestions") or [], "暂无")}</section>'
            '</div>'
        )

    def _render_benchmark(self, benchmark: Dict[str, Any] | None) -> str:
        if not benchmark:
            return '<div class="empty">未执行技术摸底</div>'
        novelty_level = str(benchmark.get("novelty_level") or "").strip().lower()
        novelty_label = self.BENCHMARK_NOVELTY_LABELS.get(novelty_level, novelty_level or "-")
        return (
            '<div class="flat-stack">'
            f'<section class="flat-section"><div class="flat-label">新颖性</div><div class="flat-value">{html.escape(novelty_label)}</div></section>'
            f'<section class="flat-section"><div class="flat-label">文献定位</div><div class="flat-value">{html.escape(str(benchmark.get("literature_position") or "-"))}</div></section>'
            f'<section class="flat-section"><div class="flat-label">专利重叠</div><div class="flat-value">{html.escape(str(benchmark.get("patent_overlap") or "-"))}</div></section>'
            f'<section class="flat-section"><div class="flat-label">综合结论</div><div class="flat-value">{html.escape(str(benchmark.get("conclusion") or "-"))}</div></section>'
            f'<section class="flat-section"><div class="flat-label">对比参考</div>{self._render_benchmark_references(benchmark.get("references") or [])}</section>'
            '</div>'
        )

    def _render_benchmark_references(self, references: List[Dict[str, Any]]) -> str:
        rows: List[str] = []
        for index, item in enumerate(references[:4], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            source = str(item.get("source") or "").strip().lower()
            source_label = self.BENCHMARK_SOURCE_LABELS.get(source, "参考")
            year = str(item.get("year") or "").strip()
            meta_parts = [source_label]
            if year:
                meta_parts.append(year)
            rows.append(
                '<div class="benchmark-reference-item">'
                f'<div class="benchmark-reference-title">{index}. {html.escape(title)}</div>'
                f'<div class="benchmark-reference-meta">{" · ".join(html.escape(part) for part in meta_parts)}</div>'
                '</div>'
            )
        if not rows:
            return '<div class="empty">暂无参考条目</div>'
        return '<div class="benchmark-reference-list">' + "".join(rows) + "</div>"

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
