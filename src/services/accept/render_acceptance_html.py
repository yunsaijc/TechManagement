from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


ROOT = Path("/home/tdkx/ljh/Tech")
INPUT_PATH = ROOT / "debug_accept" / "acceptance_results.json"
OUTPUT_PATH = ROOT / "debug_accept" / "index.html"
ACCEPTANCE_RESULTS_FILENAME = "acceptance_results.json"
ACCEPTANCE_CATALOG_FILENAME = "acceptance_catalog.json"
ACCEPTANCE_CATALOG_LOADER_FILENAME = "acceptance_catalog.js"
ACCEPTANCE_PROJECTS_DIRNAME = "acceptance_projects"
ACCEPTANCE_BLOCKS_FILENAME = "acceptance_blocks.json"
ACCEPTANCE_BLOCKS_LOADER_FILENAME = "acceptance_blocks.js"
ACCEPTANCE_CATALOG_GLOBAL = "__ACCEPTANCE_CATALOG__"
ACCEPTANCE_PROJECTS_GLOBAL = "__ACCEPTANCE_PROJECTS__"
ACCEPTANCE_BLOCKS_GLOBAL = "__ACCEPTANCE_BLOCKS__"
CATALOG_FIELDS = (
    "project_no",
    "project_name",
    "attachment_count",
    "total_commitments",
    "fulfilled_commitments",
    "partial_commitments",
    "missing_commitments",
    "fulfillment_rate",
)


def _is_fully_accepted_project(project: dict[str, object]) -> bool:
    return (
        float(project.get("fulfillment_rate") or 0) >= 1
        and int(project.get("partial_commitments") or 0) == 0
        and int(project.get("missing_commitments") or 0) == 0
        and int(project.get("total_commitments") or 0) > 0
    )


def _strip_document_blocks(
    documents: list[dict[str, object]] | None,
    *,
    blocks: dict[str, object],
    project_no: str,
) -> list[dict[str, object]]:
    slim_docs: list[dict[str, object]] = []
    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        doc_copy = dict(doc)
        role = str(doc_copy.get("role") or "")
        doc_blocks = doc_copy.pop("blocks", None)
        if role == "hts" and doc_blocks:
            blocks[project_no] = doc_blocks
        slim_docs.append(doc_copy)
    return slim_docs


def split_acceptance_payload(
    data: list[dict[str, object]],
    input_dir: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """目录 + 单项目文件 + 任务书 blocks，供前端按需加载。"""
    catalog: list[dict[str, object]] = []
    blocks: dict[str, object] = {}
    projects_dir = input_dir / ACCEPTANCE_PROJECTS_DIRNAME
    projects_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in projects_dir.glob("*.json"):
        stale_path.unlink()
    for stale_path in projects_dir.glob("*.js"):
        stale_path.unlink()

    for project in data:
        project_no = str(project.get("project_no") or "")
        if not project_no:
            continue
        if _is_fully_accepted_project(project):
            catalog.append({field: project.get(field) for field in CATALOG_FIELDS})
        slim = deepcopy(project)
        slim["documents"] = _strip_document_blocks(
            slim.get("documents"),
            blocks=blocks,
            project_no=project_no,
        )
        json_path = projects_dir / f"{project_no}.json"
        json_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
        compact = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
        js_path = projects_dir / f"{project_no}.js"
        js_path.write_text(
            "globalThis."
            f"{ACCEPTANCE_PROJECTS_GLOBAL}=globalThis.{ACCEPTANCE_PROJECTS_GLOBAL}||{{}};"
            f"globalThis.{ACCEPTANCE_PROJECTS_GLOBAL}[{json.dumps(project_no, ensure_ascii=False)}]={compact};\n",
            encoding="utf-8",
        )
    return catalog, blocks


def _write_json_and_js(
    json_path: Path,
    js_path: Path,
    payload: object,
    *,
    global_name: str,
) -> None:
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    js_path.write_text(f"globalThis.{global_name}={compact};\n", encoding="utf-8")


def write_acceptance_results_files(input_dir: Path, data: list[dict[str, object]]) -> None:
    """完整结果供批处理合并；目录/单项目/blocks 供页面按需加载。"""
    (input_dir / ACCEPTANCE_RESULTS_FILENAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    catalog, blocks = split_acceptance_payload(data, input_dir)
    _write_json_and_js(
        input_dir / ACCEPTANCE_CATALOG_FILENAME,
        input_dir / ACCEPTANCE_CATALOG_LOADER_FILENAME,
        catalog,
        global_name=ACCEPTANCE_CATALOG_GLOBAL,
    )
    _write_json_and_js(
        input_dir / ACCEPTANCE_BLOCKS_FILENAME,
        input_dir / ACCEPTANCE_BLOCKS_LOADER_FILENAME,
        blocks,
        global_name=ACCEPTANCE_BLOCKS_GLOBAL,
    )


def build_html(*, catalog_url: str = ACCEPTANCE_CATALOG_FILENAME) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>验收核查工作台</title>
  <style>
    :root {{
      --bg: #eef2f7;
      --card: #ffffff;
      --line: #d4dbe7;
      --line-strong: #b6c2d4;
      --text: #162033;
      --muted: #61708a;
      --accent: #0f766e;
      --accent-soft: #dff6f1;
      --fulfilled: #067647;
      --partial: #b54708;
      --missing: #b42318;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.10), transparent 26%),
        linear-gradient(180deg, #f7fafc 0%, var(--bg) 180px);
      color: var(--text);
      height: 100vh;
      overflow: hidden;
    }}
    a {{
      color: #175cd3;
      text-decoration: none;
    }}
    button {{
      font: inherit;
    }}
    .page {{
      width: min(1960px, 100%);
      height: 100vh;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 14px;
      overflow: hidden;
    }}
    .hero {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 14px 18px;
      display: grid;
      grid-template-columns: minmax(260px, 1fr) minmax(360px, 1.35fr) auto;
      align-items: end;
      gap: 14px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 20px;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .hero-main {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .hero-stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
    }}
    .project-picker {{
      min-width: 0;
    }}
    .project-picker-label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .project-select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      color: var(--text);
      padding: 9px 12px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
    }}
    .project-select:focus {{
      outline: 2px solid rgba(15, 118, 110, 0.22);
      border-color: var(--accent);
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f8fafc;
      color: var(--muted);
      font-size: 12px;
    }}
    .workspace {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
      min-width: 0;
      min-height: 0;
      height: 100%;
      overflow: hidden;
    }}
    .center-panel, .viewer-panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    .sidebar {{
      padding: 18px 14px;
    }}
    .sidebar-head {{
      padding: 0 8px 12px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 12px;
    }}
    .sidebar-title {{
      margin: 0;
      font-size: 18px;
      font-weight: 800;
    }}
    .sidebar-subtitle {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .project-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      padding-right: 2px;
    }}
    .project-item {{
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fbfcfe;
      padding: 14px 12px;
      cursor: pointer;
      transition: 0.18s ease;
    }}
    .project-item:hover {{
      border-color: var(--line-strong);
      transform: translateY(-1px);
    }}
    .project-item.active {{
      border-color: var(--accent);
      background: linear-gradient(180deg, #ffffff 0%, #eefcf8 100%);
      box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.12);
    }}
    .project-item-title {{
      font-size: 14px;
      font-weight: 700;
      line-height: 1.55;
      margin-bottom: 6px;
    }}
    .project-item-meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .project-item-stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .center-panel, .viewer-panel {{
      padding: 18px 18px 16px;
    }}
    .center-panel {{
      padding-bottom: 12px;
    }}
    .panel-head {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
      margin-bottom: 10px;
    }}
    .panel-head h2, .panel-head h3 {{
      margin: 0;
    }}
    .panel-head p {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .doc-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
      margin-bottom: 0;
      flex: 0 0 auto;
    }}
    .doc-tab {{
      border: 1px solid var(--line);
      background: #f8fafc;
      color: var(--text);
      border-radius: 10px;
      padding: 7px 14px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .doc-tab.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #115e59;
    }}
    .doc-list {{
      margin-bottom: 8px;
      flex: 0 0 auto;
    }}
    .doc-list:empty {{
      display: none;
    }}
    .doc-select-label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .doc-select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
      cursor: pointer;
    }}
    .doc-select:focus {{
      outline: 2px solid rgba(15, 118, 110, 0.22);
      border-color: var(--accent);
    }}
    .viewer-layout {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-height: 0;
      height: 100%;
      flex: 1 1 auto;
      overflow: hidden;
    }}
    .viewer-meta {{
      display: grid;
      grid-template-columns: 72px minmax(0, 1fr);
      gap: 4px 10px;
      font-size: 12px;
      flex: 0 0 auto;
      overflow-wrap: anywhere;
      max-height: 58px;
      overflow-y: auto;
      padding-right: 2px;
    }}
    .viewer-meta-row {{
      display: contents;
    }}
    .viewer-meta-label {{
      color: var(--muted);
    }}
    .viewer-meta-value {{
      min-width: 0;
    }}
    .viewer-subdoc-select {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }}
    .viewer-subdoc-meta {{
      color: var(--muted);
      line-height: 1.5;
      overflow-wrap: anywhere;
    }}
    .viewer-preview {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #f8fafc;
      min-height: 0;
      flex: 1 1 auto;
      overflow: auto;
      display: flex;
      align-items: stretch;
      justify-content: center;
    }}
    .viewer-preview.compact {{
      flex: 0 0 auto;
      min-height: 240px;
      align-items: center;
    }}
    .viewer-preview.compact .viewer-fallback {{
      padding: 18px 24px;
    }}
    .viewer-preview iframe {{
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      background: #fff;
      flex: 1 1 auto;
    }}
    .viewer-image {{
      display: block;
      max-width: 100%;
      height: auto;
      align-self: flex-start;
      background: #fff;
    }}
    .viewer-fallback {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      text-align: center;
      line-height: 1.8;
      padding: 24px;
      width: 100%;
    }}
    .viewer-fallback a {{
      display: inline-flex;
      margin-top: 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 12px;
      background: #fff;
    }}
    .viewer-fallback-line {{
      display: block;
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .viewer-snippets {{
      width: min(860px, 100%);
      margin-top: 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      text-align: left;
    }}
    .viewer-snippet {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
      padding: 12px 14px;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
    }}
    .viewer-snippet-title {{
      font-size: 12px;
      font-weight: 800;
      line-height: 1.5;
      color: var(--accent);
      margin-bottom: 6px;
      overflow-wrap: anywhere;
    }}
    .viewer-snippet-text {{
      font-size: 13px;
      line-height: 1.7;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--text);
    }}
    .viewer-snippet-empty {{
      width: min(860px, 100%);
      margin-top: 18px;
      padding: 14px;
      border: 1px dashed var(--line-strong);
      border-radius: 12px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
      text-align: left;
    }}
    .result-summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }}
    .stat-card {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
      background: linear-gradient(180deg, #ffffff 0%, #fafcff 100%);
      min-height: 56px;
    }}
    .stat-label {{
      color: var(--muted);
      font-size: 11px;
      line-height: 1.2;
      margin-bottom: 3px;
    }}
    .stat-value {{
      font-size: 20px;
      font-weight: 800;
      line-height: 1.1;
    }}
    .result-scroll {{
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding-right: 2px;
    }}
    .status-section {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: linear-gradient(180deg, #ffffff 0%, #fafcff 100%);
      padding: 14px;
      margin-bottom: 14px;
    }}
    .status-section.status-fulfilled-section {{
      border-color: rgba(6, 118, 71, 0.28);
      background: linear-gradient(180deg, #f7fdf9 0%, #effaf3 100%);
    }}
    .status-section.status-partial-section {{
      border-color: rgba(181, 71, 8, 0.28);
      background: linear-gradient(180deg, #fffaf5 0%, #fff4e8 100%);
    }}
    .status-section.status-missing-section {{
      border-color: rgba(180, 35, 24, 0.24);
      background: linear-gradient(180deg, #fff9f9 0%, #fff1f2 100%);
    }}
    .status-section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .status-section-title {{
      font-size: 15px;
      font-weight: 800;
    }}
    .status-section.status-fulfilled-section .status-section-title {{
      color: var(--fulfilled);
    }}
    .status-section.status-partial-section .status-section-title {{
      color: var(--partial);
    }}
    .status-section.status-missing-section .status-section-title {{
      color: var(--missing);
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .status-fulfilled {{
      color: var(--fulfilled);
      background: #ecfdf3;
    }}
    .status-partial {{
      color: var(--partial);
      background: #fff7ed;
    }}
    .status-missing {{
      color: var(--missing);
      background: #fff1f2;
    }}
    .metric-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .metric-card {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #ffffff;
      padding: 14px;
      text-align: left;
      cursor: pointer;
    }}
    .metric-card.status-fulfilled-card {{
      border-color: rgba(6, 118, 71, 0.24);
      background: #fcfffd;
    }}
    .metric-card.status-partial-card {{
      border-color: rgba(181, 71, 8, 0.24);
      background: #fffdfa;
    }}
    .metric-card.status-missing-card {{
      border-color: rgba(180, 35, 24, 0.2);
      background: #fffdfd;
    }}
    .metric-card.active {{
      border-color: var(--accent);
      background: linear-gradient(180deg, #ffffff 0%, #f0fdfa 100%);
      box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.14);
    }}
    .metric-card-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 8px;
    }}
    .metric-title {{
      font-size: 15px;
      font-weight: 800;
      line-height: 1.5;
    }}
    .metric-card.status-fulfilled-card .metric-title {{
      color: var(--fulfilled);
    }}
    .metric-card.status-partial-card .metric-title {{
      color: var(--partial);
    }}
    .metric-card.status-missing-card .metric-title {{
      color: var(--missing);
    }}
    .metric-values {{
      font-size: 13px;
      line-height: 1.7;
      color: var(--text);
    }}
    .triad-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .triad-cell {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
      padding: 9px 10px;
      min-width: 0;
    }}
    .triad-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }}
    .triad-value {{
      font-size: 14px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .metric-card.status-fulfilled-card .triad-value {{ color: var(--fulfilled); }}
    .metric-card.status-partial-card .triad-value {{ color: var(--partial); }}
    .metric-card.status-missing-card .triad-value {{ color: var(--missing); }}
    .consistency-summary {{
      margin-top: 10px;
      border-radius: 12px;
      padding: 9px 10px;
      font-size: 13px;
      line-height: 1.7;
      background: #f8fafc;
      border: 1px solid var(--line);
      white-space: pre-wrap;
    }}
    .metric-status-line {{
      margin-top: 6px;
      font-size: 13px;
      font-weight: 700;
    }}
    .metric-status-line.status-fulfilled-text {{
      color: var(--fulfilled);
    }}
    .metric-status-line.status-partial-text {{
      color: var(--partial);
    }}
    .metric-status-line.status-missing-text {{
      color: var(--missing);
    }}
    .metric-reason {{
      margin-top: 8px;
      font-size: 13px;
      line-height: 1.7;
      color: var(--muted);
      white-space: pre-wrap;
    }}
    .metric-source {{
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: #f8fafc;
      border: 1px solid var(--line);
      font-size: 13px;
      line-height: 1.7;
      white-space: pre-wrap;
    }}
    .metric-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .link-btn {{
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: #175cd3;
      padding: 6px 10px;
      font-size: 12px;
      cursor: pointer;
    }}
    .evidence-list {{
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .evidence-item {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fbfcfe;
      padding: 12px;
    }}
    .evidence-item-top {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 6px;
    }}
    .evidence-title {{
      font-size: 13px;
      font-weight: 700;
      line-height: 1.6;
      overflow-wrap: anywhere;
    }}
    .evidence-meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
      margin-bottom: 6px;
    }}
    .evidence-excerpt {{
      font-size: 13px;
      line-height: 1.7;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .warning-list {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 14px;
    }}
    .warning {{
      color: #9a6700;
      background: #fff8e1;
      border: 1px solid #f2d27a;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
      line-height: 1.6;
    }}
    .warning.info-note {{
      color: #175cd3;
      background: #f0f9ff;
      border-color: #b9e6fe;
    }}
    .pass-banner {{
      border: 1px solid #abefc6;
      background: #ecfdf3;
      color: #067647;
      border-radius: 14px;
      padding: 12px 14px;
      font-size: 15px;
      font-weight: 600;
      margin-bottom: 12px;
    }}
    .empty {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
      padding: 8px 2px;
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="hero-main">
        <h1>验收核查工作台</h1>
        <p>顶部切项目，左侧看任务书 / 验收申请 / 验收申请附件原文，右侧看《验收指标自动核查表》与证据链。</p>
      </div>
      <div class="project-picker">
        <label class="project-picker-label" for="projectSelect">选择项目</label>
        <select class="project-select" id="projectSelect"></select>
      </div>
      <div class="hero-stats" id="heroStats"></div>
    </section>
    <section class="workspace">
      <section class="center-panel">
        <div class="panel-head">
          <h2 id="centerTitle">原文材料</h2>
          <p id="centerSubtitle"></p>
          <div class="doc-tabs" id="docRoleTabs"></div>
        </div>
        <div class="viewer-layout">
          <div class="doc-list" id="docList"></div>
          <div class="viewer-meta" id="viewerMeta"></div>
          <div class="viewer-preview" id="viewerPreview"></div>
        </div>
      </section>
      <section class="viewer-panel">
        <div class="panel-head">
          <h3 id="resultTitle">验收核查结果</h3>
          <p id="resultSubtitle"></p>
        </div>
        <div class="result-summary" id="resultSummary"></div>
        <div class="result-scroll">
          <div class="warning-list" id="warningList"></div>
          <div id="resultSections"></div>
        </div>
      </section>
    </section>
  </main>
  <script>
    const CATALOG_URL = {json.dumps(catalog_url, ensure_ascii=False)};
    const CATALOG_LOADER_URL = {json.dumps(ACCEPTANCE_CATALOG_LOADER_FILENAME, ensure_ascii=False)};
    const PROJECTS_BASE = {json.dumps(ACCEPTANCE_PROJECTS_DIRNAME, ensure_ascii=False)};
    const BLOCKS_URL = {json.dumps(ACCEPTANCE_BLOCKS_FILENAME, ensure_ascii=False)};
    const BLOCKS_LOADER_URL = {json.dumps(ACCEPTANCE_BLOCKS_LOADER_FILENAME, ensure_ascii=False)};
    const CATALOG_GLOBAL = {json.dumps(ACCEPTANCE_CATALOG_GLOBAL, ensure_ascii=False)};
    const PROJECTS_GLOBAL = {json.dumps(ACCEPTANCE_PROJECTS_GLOBAL, ensure_ascii=False)};
    const BLOCKS_GLOBAL = {json.dumps(ACCEPTANCE_BLOCKS_GLOBAL, ensure_ascii=False)};
    let CATALOG = [];
    let CURRENT_PROJECT = null;
    let projectCache = new Map();
    let projectLoadingPromise = null;
    let projectLoadingKey = "";
    let renderSeq = 0;
    let TASKBOOK_BLOCKS = {{}};
    let blocksLoaded = false;
    let blocksLoading = null;
    const STATUS_LABELS = {{
      fulfilled: "完成",
      partial: "部分完成",
      missing: "未完成"
    }};
    const STATUS_CLASSES = {{
      fulfilled: "status-fulfilled",
      partial: "status-partial",
      missing: "status-missing"
    }};
    const STATUS_ORDER = ["fulfilled", "partial", "missing"];
    const ROLE_LABELS = {{
      hts: "任务书",
      yssq: "验收申请",
      yssqfj: "验收申请附件"
    }};

    let currentProjectIndex = 0;
    let currentRole = "yssq";
    let currentDocIndex = 0;
    let currentSubdocIndex = 0;
    let activeCommitmentId = "";
    let currentViewerTarget = null;

    function esc(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function statusPill(status) {{
      const label = STATUS_LABELS[status] || "未知";
      const cls = STATUS_CLASSES[status] || "status-missing";
      return `<span class="status-pill ${{cls}}">${{esc(label)}}</span>`;
    }}

    function ratioText(value) {{
      if (typeof value !== "number" || Number.isNaN(value)) {{
        return "-";
      }}
      return `${{Math.round(value * 100)}}%`;
    }}

    function metricDisplayName(row) {{
      return row?.metric_variant || row?.metric_name || "";
    }}

    function metricLayerLabel(row) {{
      const layer = String(row?.metric_layer || "generic");
      const labels = {{
        deliverable: "成果件型",
        numeric: "数值型",
        technical: "技术参数型",
        financial: "财务型",
        talent: "人才型",
        generic: "通用型",
      }};
      return labels[layer] || "通用型";
    }}

    function evidenceNatureLabel(detail) {{
      const nature = String(detail?.evidence_nature || "");
      const labels = {{
        artifact: "成果本体",
        proof: "证明材料",
        summary: "摘要材料",
        catalog: "目录材料",
        reference: "引文材料",
      }};
      return labels[nature] || "未分类";
    }}

    function evidenceJudgeSourceLabel(detail) {{
      const source = String(detail?.evidence_judge_source || "");
      const labels = {{
        rule: "规则判定",
        llm: "LLM辅助判定",
        hybrid: "规则+LLM",
        unknown: "未标注",
      }};
      return labels[source] || "未标注";
    }}

    function statusText(status) {{
      return STATUS_LABELS[String(status || "").toLowerCase()] || "未识别";
    }}

    function dedupeMatchDetails(details) {{
      const list = Array.isArray(details) ? details : [];
      const seen = new Set();
      const deduped = [];
      list.forEach(function (detail) {{
        const key = [
          detail?.doc_kind || "",
          detail?.artifact_key || detail?.display_title || detail?.title || detail?.file_name || "",
          detail?.viewer_page || detail?.source_page || "",
          detail?.source_block_id || "",
        ].join("||");
        if (seen.has(key)) {{
          return;
        }}
        seen.add(key);
        deduped.push(detail);
      }});
      return deduped;
    }}

    function rowOrderKey(row) {{
      const page = Number(row?.source_page || 0);
      const block = String(row?.source_block_id || "");
      const line = String(row?.source_line || row?.reason || "");
      return [page > 0 ? page : 999999, block, line];
    }}

    function compareRows(a, b) {{
      const ka = rowOrderKey(a);
      const kb = rowOrderKey(b);
      if (ka[0] !== kb[0]) return ka[0] - kb[0];
      if (ka[1] !== kb[1]) return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0;
      if (ka[2] !== kb[2]) return ka[2] < kb[2] ? -1 : ka[2] > kb[2] ? 1 : 0;
      return String(a?.commitment_id || "").localeCompare(String(b?.commitment_id || ""));
    }}

    function getProjectSummary(index) {{
      return CATALOG[index] || null;
    }}

    function getProject() {{
      return CURRENT_PROJECT;
    }}

    function getDocumentsByRole(project, role) {{
      return (project.documents || []).filter(function (doc) {{
        return doc.role === role;
      }});
    }}

    function getSubdocs(doc) {{
      return Array.isArray(doc?.subdocs) ? doc.subdocs : [];
    }}

    function getCurrentSubdoc(doc) {{
      const subdocs = getSubdocs(doc);
      if (!subdocs.length) {{
        return null;
      }}
      if (currentSubdocIndex >= subdocs.length) {{
        currentSubdocIndex = 0;
      }}
      return subdocs[currentSubdocIndex] || subdocs[0] || null;
    }}

    function ensureSelection() {{
      const project = getProject();
      if (!project) {{
        return;
      }}
      const preferredRoles = ["yssq", "yssqfj", "hts"];
      const availableRoles = preferredRoles.filter(function (role) {{
        return getDocumentsByRole(project, role).length > 0;
      }});
      if (!availableRoles.includes(currentRole)) {{
        currentRole = availableRoles[0] || "hts";
      }}
      const docs = getDocumentsByRole(project, currentRole);
      if (currentDocIndex >= docs.length) {{
        currentDocIndex = 0;
      }}
    }}

    function renderHero() {{
      const totalProjects = CATALOG.length;
      const summary = getProjectSummary(currentProjectIndex);
      const project = getProject();
      const rows = project ? (project.rows || []) : [];
      const fulfilled = summary ? Number(summary.fulfilled_commitments || 0) : 0;
      const partial = summary ? Number(summary.partial_commitments || 0) : 0;
      const missing = summary ? Number(summary.missing_commitments || 0) : 0;
      const passed = summary && Number(summary.fulfillment_rate || 0) >= 1 && partial === 0 && missing === 0;
      document.getElementById("heroStats").innerHTML = [
        `<span class="chip">批次项目 ${{totalProjects}} 个</span>`,
        `<span class="chip">当前项目指标 ${{rows.length || (summary ? summary.total_commitments || 0 : 0)}} 条</span>`,
        `<span class="chip">完成 ${{fulfilled}} 条</span>`,
        `<span class="chip">部分完成 ${{partial}} 条</span>`,
        `<span class="chip">未完成 ${{missing}} 条</span>`,
        passed ? `<span class="chip" style="background:#ecfdf3;color:#067647;border-color:#abefc6;">验收通过</span>` : ""
      ].join("");
    }}

    function renderProjectPicker() {{
      const select = document.getElementById("projectSelect");
      select.innerHTML = CATALOG.map(function (summary, index) {{
        const selected = index === currentProjectIndex ? "selected" : "";
        const label = `${{summary.project_no}} ${{summary.project_name}} · 履约率 ${{ratioText(summary.fulfillment_rate)}} · 附件 ${{summary.attachment_count}} 份`;
        return `<option value="${{index}}" ${{selected}}>${{esc(label)}}</option>`;
      }}).join("");
      select.onchange = function () {{
        currentProjectIndex = Number(select.value || 0);
        currentRole = "yssq";
        currentDocIndex = 0;
        currentSubdocIndex = 0;
        activeCommitmentId = "";
        currentViewerTarget = null;
        render();
      }};
    }}

    function normalizeViewerPage(payload) {{
      const viewerPage = Number(payload?.viewer_page || 0);
      if (viewerPage > 0) {{
        return viewerPage;
      }}
      const sourcePage = Number(payload?.source_page || 0);
      return sourcePage >= 0 ? sourcePage + 1 : 1;
    }}

    function compactText(value) {{
      return String(value || "").replace(/\\s+/g, "");
    }}

    function metricAnchorAliases(metricName, metricVariant) {{
      const aliasMap = {{
        "科技论文": ["科技论文", "发表论文", "发表学术论文", "高质量论文", "论文"],
        "发明专利": ["发明专利", "申请专利", "申报国家发明专利", "专利"],
        "培养研究生": ["培养研究生", "联合培养研究生", "研究生"],
        "研究报告": ["研究报告", "总研究报告", "科技报告"],
        "科技报告": ["科技报告", "研究报告"],
        "决策咨询报告": ["决策咨询报告", "决策参考报告"],
      }};
      const values = [];
      [metricName, metricVariant].forEach(function (key) {{
        key = String(key || "").trim();
        if (!key) {{
          return;
        }}
        values.push(key);
        (aliasMap[key] || []).forEach((item) => values.push(item));
        if (key.includes("/")) {{
          key.split("/").forEach((part) => {{
            (aliasMap[part.trim()] || [part.trim()]).forEach((item) => values.push(item));
          }});
        }}
      }});
      const seen = new Set();
      return values.filter(function (item) {{
        const compact = compactText(item);
        if (!compact || seen.has(compact)) {{
          return false;
        }}
        seen.add(compact);
        return true;
      }});
    }}

    function metricAnchorSnippet(raw, metricName, metricVariant) {{
      const cleaned = String(raw || "").replace(/\\[表格[^\\]]*\\]/g, " ").replace(/\\s+/g, " ").trim();
      const aliases = metricAnchorAliases(metricName, metricVariant);
      const parts = cleaned.split(/[，,；;。|]/).map((item) => item.trim()).filter(Boolean);
      for (const part of parts) {{
        if (!aliases.some((alias) => compactText(part).includes(compactText(alias)))) {{
          continue;
        }}
        if (/\\d+\\s*(?:[-~至到]\\s*)?\\d*\\s*(?:篇|项|名|人|份)/.test(part)) {{
          return part.replace(/^.*?(具体目标|指标值|实施期目标)[:：]?/, "").slice(0, 160);
        }}
      }}
      for (const alias of aliases) {{
        const escaped = alias.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&");
        const match = cleaned.match(new RegExp(escaped));
        if (match && match.index >= 0) {{
          const start = Math.max(0, match.index - 36);
          const end = Math.min(cleaned.length, match.index + match[0].length + 72);
          return cleaned.slice(start, end).replace(/^[^。；;|]{{0,16}}[。；;|]\\s*/, "").replace(/\\s*[。；;|][^。；;|]{{0,40}}$/, "").slice(0, 160);
        }}
      }}
      return "";
    }}

    function pickTaskbookAnchorLine(row) {{
      const text = String(row?.source_line || row?.reason || "").trim();
      if (!text) {{
        return "";
      }}
      const lines = text.split("\\n").map((line) => line.trim()).filter(Boolean);
      if (lines.length <= 1) {{
        return text;
      }}
      const metricVariant = String(row?.metric_variant || "").trim();
      const metricName = String(row?.metric_name || "").trim();
      const keywordGroups = [];
      if (metricVariant === "科技报告/研究报告") {{
        keywordGroups.push(["撰写科技报告", "科技报告、研究报告", "科技报告,研究报告"]);
      }}
      const aliases = metricAnchorAliases(metricName, metricVariant);
      if (aliases.length) {{
        keywordGroups.push(aliases);
      }}
      for (const keywords of keywordGroups) {{
        const scored = [];
        lines.forEach(function (line, index) {{
          const compact = compactText(line);
          if (keywords.some((keyword) => compact.includes(compactText(keyword)))) {{
            const overallBonus = /(具体目标|总体目标|实施期目标|指标值)/.test(compact) ? -60 : 0;
            const annualPenalty = /(第一年度|第二年度|第三年度|本年度目标)/.test(compact) ? 40 : 0;
            const unitBonus = /\\d+\\s*(?:[-~至到]\\s*)?\\d*\\s*(?:篇|项|名|人|份)/.test(line) ? -20 : 0;
            scored.push([overallBonus + annualPenalty + unitBonus, index, line]);
          }}
        }});
        if (scored.length) {{
          scored.sort((left, right) => left[0] - right[0] || left[1] - right[1]);
          return scored[0][2];
        }}
      }}
      const tableLines = lines.filter((line) => /\\[表格行\\d+\\]/.test(line));
      for (let index = tableLines.length - 1; index >= 0; index -= 1) {{
        const line = tableLines[index];
        if (/(绩效|实施期目标|指标名称|指标值)/.test(line)) {{
          return line;
        }}
      }}
      if (tableLines.length) {{
        return tableLines[tableLines.length - 1];
      }}
      return lines[lines.length - 1];
    }}

    function anchorCoreTokens(anchorLine) {{
      const tokens = [];
      const compact = compactText(String(anchorLine || "").replace(/\\[表格行\\d+\\]/g, ""));
      if (!compact) {{
        return tokens;
      }}
      const metricFragments = String(anchorLine || "").match(/(?:指标名称|实施期目标)[:：]([^;；|]{{4,48}})/g) || [];
      metricFragments.forEach(function (fragment) {{
        const piece = compactText(fragment.replace(/^[^:：]+[:：]/, ""));
        if (piece.length >= 4) {{
          tokens.push(piece);
        }}
      }});
      if (compact.includes("撰写科技报告") || compact.includes("科技报告、研究报告")) {{
        tokens.push("撰写科技报告", "科技报告、研究报告", "科技报告,研究报告");
      }}
      if (compact.includes("绩效")) {{
        tokens.push("绩效指标", "实施期目标");
      }}
      if (compact.includes("研究报告") && !compact.includes("科技报告、研究报告")) {{
        tokens.push("研究报告");
      }}
      if (compact.includes("科技报告")) {{
        tokens.push("科技报告");
      }}
      return Array.from(new Set(tokens.filter(function (token) {{
        return compactText(token).length >= 4;
      }})));
    }}

    function blockMatchesAnchor(blockText, anchorLine, rowTag, rowNumber) {{
      const text = String(blockText || "");
      const compactBlock = compactText(text);
      const compactAnchor = compactText(anchorLine);
      const coreTokens = anchorCoreTokens(anchorLine);
      let matched = false;
      if (rowTag && text.includes(rowTag)) {{
        matched = true;
      }} else if (rowNumber && compactBlock.includes(`表格行${{rowNumber}}`)) {{
        matched = true;
      }} else if (compactAnchor.length >= 12 && compactBlock.includes(compactAnchor)) {{
        matched = true;
      }}
      if (!matched) {{
        return false;
      }}
      if (!coreTokens.length) {{
        return true;
      }}
      return coreTokens.some(function (token) {{
        return compactBlock.includes(compactText(token));
      }});
    }}

    function scoreTaskbookBlock(block, anchorLine) {{
      const compactAnchor = compactText(anchorLine);
      const compactBlock = compactText(block?.text || "");
      let core = compactAnchor;
      ["总体目标", "绩效指标", "实施期目标", "指标名称", "指标值", "第一年度目标", "当前年度"].forEach(function (token) {{
        core = core.replace(compactText(token), "");
      }});
      const missingCore = core && !compactBlock.includes(core) ? 1 : 0;
      const bbox = block?.bbox || {{}};
      const width = Number(bbox.width ?? bbox.w ?? 0);
      const height = Number(bbox.height ?? bbox.h ?? 0);
      const invalidBox = width <= 0 || height <= 0 ? 1 : 0;
      return [missingCore, invalidBox, String(block?.text || "").length];
    }}

    function findTaskbookBlock(project, row) {{
      const hts = (project.documents || []).find(function (doc) {{
        return doc.role === "hts";
      }});
      if (!hts || !hts.blocks) {{
        return null;
      }}
      const anchorLine = pickTaskbookAnchorLine(row);
      if (!anchorLine) {{
        return null;
      }}
      const rowTagMatch = anchorLine.match(/\\[表格行\\d+\\]/);
      const rowTag = rowTagMatch ? rowTagMatch[0] : "";
      const rowNumberMatch = rowTag.match(/\\[表格行(\\d+)\\]/);
      const rowNumber = rowNumberMatch ? rowNumberMatch[1] : "";
      const matched = [];
      Object.keys(hts.blocks).forEach(function (blockId) {{
        const block = hts.blocks[blockId];
        if (!blockMatchesAnchor(block?.text || "", anchorLine, rowTag, rowNumber)) {{
          return;
        }}
        matched.push(Object.assign({{ block_id: blockId }}, block));
      }});
      if (matched.length) {{
        matched.sort(function (left, right) {{
          const leftScore = scoreTaskbookBlock(left, anchorLine);
          const rightScore = scoreTaskbookBlock(right, anchorLine);
          for (let index = 0; index < leftScore.length; index += 1) {{
            if (leftScore[index] !== rightScore[index]) {{
              return leftScore[index] - rightScore[index];
            }}
          }}
          return 0;
        }});
        return matched[0];
      }}
      const storedId = String(row?.source_block_id || "");
      if (storedId && hts.blocks[storedId]) {{
        const stored = Object.assign({{ block_id: storedId }}, hts.blocks[storedId]);
        if (blockMatchesAnchor(stored.text || "", anchorLine, rowTag, rowNumber)) {{
          return stored;
        }}
      }}
      return null;
    }}

    function inferPageSizeFromBlocks(blocksDict, pageIndex) {{
      let maxX = 0;
      let maxY = 0;
      Object.values(blocksDict || {{}}).forEach(function (block) {{
        if (pageIndex !== undefined && pageIndex !== null && Number(block?.page ?? -1) !== Number(pageIndex)) {{
          return;
        }}
        const bbox = block?.bbox;
        if (!bbox) {{
          return;
        }}
        const x = Number(bbox.x || 0);
        const y = Number(bbox.y || 0);
        const width = Number(bbox.width ?? bbox.w ?? 0);
        const height = Number(bbox.height ?? bbox.h ?? 0);
        maxX = Math.max(maxX, x + width);
        maxY = Math.max(maxY, y + height);
      }});
      if (maxX > 2 && maxY > 2) {{
        return [maxX, maxY];
      }}
      if (maxX > 0 && maxY > 0 && maxX <= 1.5 && maxY <= 1.5) {{
        return [1, 1];
      }}
      return null;
    }}

    function resolvePageSize(blocksDict, pageIndex, pageSizes) {{
      const key = String(pageIndex ?? 0);
      const stored = pageSizes && pageSizes[key];
      if (Array.isArray(stored) && stored.length >= 2) {{
        const pageWidth = Number(stored[0] || 0);
        const pageHeight = Number(stored[1] || 0);
        if (pageWidth > 0 && pageHeight > 0) {{
          return [pageWidth, pageHeight];
        }}
      }}
      return inferPageSizeFromBlocks(blocksDict, pageIndex);
    }}

    function rectIsOversized(rects) {{
      if (!Array.isArray(rects) || !rects.length) {{
        return true;
      }}
      const rect = rects[0] || {{}};
      const w = Number(rect.w || 0);
      const h = Number(rect.h || 0);
      const area = w * h;
      return area > 0.15 || w > 0.92 || h > 0.38;
    }}

    function blockToViewerRects(block, blocksDict, pageSizes) {{
      const bbox = block?.bbox;
      if (!bbox) {{
        return [];
      }}
      const x = Number(bbox.x || 0);
      const y = Number(bbox.y || 0);
      const width = Number(bbox.width ?? bbox.w ?? 0);
      const height = Number(bbox.height ?? bbox.h ?? 0);
      if (width <= 0 || height <= 0) {{
        return [];
      }}
      const pageIndex = Number(block.page ?? 0);
      const pageSize = resolvePageSize(blocksDict, pageIndex, pageSizes);
      if (pageSize) {{
        const pageWidth = pageSize[0];
        const pageHeight = pageSize[1];
        let nx = Math.max(0, Math.min(x / pageWidth, 1));
        let ny = Math.max(0, Math.min(y / pageHeight, 1));
        let nw = Math.max(0, Math.min(width / pageWidth, 1 - nx));
        let nh = Math.max(0, Math.min(height / pageHeight, 1 - ny));
        if (nw <= 0 || nh <= 0) {{
          return [];
        }}
        const padX = 0.006;
        const padY = 0.01;
        nx = Math.max(0, nx - padX);
        ny = Math.max(0, ny - padY);
        nw = Math.min(1 - nx, nw + padX * 2);
        nh = Math.min(1 - ny, nh + padY * 2);
        return [{{ x: nx, y: ny, w: nw, h: nh }}];
      }}
      if (width <= 1 && height <= 1 && x <= 1 && y <= 1) {{
        return [{{ x: x, y: y, w: width, h: height }}];
      }}
      return [];
    }}

    function buildTaskbookViewerTarget(project, row, locationLabel) {{
      const anchorLine = pickTaskbookAnchorLine(row);
      const highlightText = pickHighlightText(row, anchorLine || row.source_line || row.reason || "");
      const presetRects = Array.isArray(row?.viewer_rects) ? row.viewer_rects : [];
      const presetPage = normalizeViewerPage(row);
      if (presetRects.length && presetPage > 0 && !rectIsOversized(presetRects)) {{
        return {{
          page: presetPage,
          source_page: Number(row?.source_page ?? presetPage - 1),
          rects: presetRects,
          location_label: locationLabel || "任务书指标位置",
          highlight_text: highlightText,
          title: String(row?.metric_variant || row?.metric_name || "").trim(),
          artifact_key: String(row?.source_block_id || ""),
          doc_kind: "任务书",
          metric_name: String(row?.metric_name || row?.metric_variant || ""),
        }};
      }}
      const hts = (project.documents || []).find(function (doc) {{
        return doc.role === "hts";
      }});
      const block = findTaskbookBlock(project, row);
      if (block && Number(block.page ?? -1) >= 0) {{
        const rects = blockToViewerRects(block, hts?.blocks || {{}}, hts?.page_sizes || {{}});
        if (rects.length && !rectIsOversized(rects)) {{
          return {{
            page: Number(block.page || 0) + 1,
            source_page: Number(block.page || 0),
            rects: rects,
            location_label: locationLabel || "任务书指标位置",
            highlight_text: highlightText,
            title: String(row?.metric_variant || row?.metric_name || "").trim(),
            artifact_key: String(block.block_id || ""),
            doc_kind: "任务书",
            metric_name: String(row?.metric_name || row?.metric_variant || ""),
          }};
        }}
      }}
      const fallback = buildViewerTarget(row, locationLabel, anchorLine || row.source_line || row.reason || "");
      if (fallback && highlightText) {{
        fallback.highlight_text = highlightText;
      }}
      if (fallback && (!fallback.rects || !fallback.rects.length || rectIsOversized(fallback.rects))) {{
        fallback.rects = [];
      }}
      return fallback;
    }}

    function pickHighlightText(payload, fallbackText) {{
      const docKind = String(payload?.doc_kind || "").trim();
      const itemTitle = String(payload?.title || "").trim();
      if (itemTitle && (docKind === "论文" || docKind === "专利证书" || docKind === "学位论文")) {{
        return itemTitle.length > 160 ? `${{itemTitle.slice(0, 160)}}…` : itemTitle;
      }}
      const preset = String(payload?.highlight_text || "").trim();
      if (preset) {{
        return preset.length > 160 ? `${{preset.slice(0, 160)}}…` : preset;
      }}
      const metricName = String(payload?.metric_name || payload?.metric_variant || "").trim();
      const raw = String(
        fallbackText
        || payload?.excerpt
        || payload?.source_line
        || payload?.reason
        || ""
      ).trim();
      if (!raw) {{
        return "";
      }}
      const metricVariant = String(payload?.metric_variant || "").trim();
      if (metricVariant === "科技报告/研究报告") {{
        const disjunctive = raw.match(/撰写科技报告\\s*[、,，]\\s*研\\s*究\\s*报告[^|；。]{{0,24}}/);
        if (disjunctive && disjunctive[0]) {{
          return disjunctive[0].trim().slice(0, 160);
        }}
      }}
      const metricSnippet = metricAnchorSnippet(raw, metricName, metricVariant);
      if (metricSnippet) {{
        return metricSnippet;
      }}
      const cleaned = raw.replace(/\\[表格[^\\]]*\\]/g, "").replace(/\\s+/g, " ").trim();
      const metricPatterns = {{
        "检测范围": [/检测范围为?\\s*[^|；。]{{6,48}}/i, /\\d+\\s*[-~至到]\\s*\\d+\\s*(?:cells|mg)/i],
        "检测频率": [/工作频率[^|；。]{{4,32}}/i, /检测频率[^|；。]{{4,32}}/i],
        "检测标准偏差": [/标准[偏误]差[^|；。]{{4,32}}/i],
        "最大测量误差": [/最大测量误差[^|；。]{{4,32}}/i],
        "科技报告": [/撰写科技报告\\s*[、,，]\\s*研\\s*究\\s*报告[^|；。]{{0,24}}/i, /科技报告\\s*[、,，]\\s*研\\s*究\\s*报告[^|；。]{{0,24}}/i],
      }};
      const patterns = metricPatterns[metricName] || [];
      for (const pattern of patterns) {{
        const match = cleaned.match(pattern);
        if (match && match[0]) {{
          return match[0].trim().slice(0, 160);
        }}
      }}
      const parts = cleaned.split(/[|；;。]/).map((item) => item.trim()).filter((item) => item.length >= 6);
      const actualPart = parts.find((item) => item.startsWith("其") || item.includes("实际"));
      if (actualPart) {{
        return actualPart.slice(0, 160);
      }}
      return cleaned.length > 160 ? `${{cleaned.slice(0, 160)}}…` : cleaned;
    }}

    function detailJumpKey(detail) {{
      return [
        detail?.evidence_id || "",
        detail?.file_name || "",
        detail?.source_block_id || "",
        detail?.source_page ?? "",
        detail?.contribution_value ?? "",
        String(detail?.excerpt || "").trim().slice(0, 120),
      ].join("||");
    }}

    function buildViewerTarget(payload, locationLabel, highlightText) {{
      if (!payload) {{
        return null;
      }}
      const rects = Array.isArray(payload.viewer_rects) ? payload.viewer_rects : [];
      const text = pickHighlightText(payload, highlightText);
      return {{
        page: normalizeViewerPage(payload),
        source_page: Number(payload?.source_page ?? -1),
        rects: rects,
        location_label: locationLabel || "命中定位",
        highlight_text: text,
        title: String(payload?.title || "").trim(),
        artifact_key: String(payload?.artifact_key || "").trim(),
        doc_kind: String(payload?.doc_kind || "").trim(),
        metric_name: String(payload?.metric_name || payload?.metric_variant || ""),
      }};
    }}

    function buildViewerSrc(viewerFile, target) {{
      if (!viewerFile) {{
        return "";
      }}
      if (!target || !(target.page > 0)) {{
        return viewerFile;
      }}
      const params = new URLSearchParams();
      params.set("page", String(target.page));
      if (target.rects && target.rects.length) {{
        params.set("rects", JSON.stringify(target.rects));
      }}
      if (target.location_label) {{
        params.set("label", target.location_label);
      }}
      if (target.highlight_text) {{
        params.set("text", target.highlight_text);
      }}
      return `${{viewerFile}}?${{params.toString()}}`;
    }}

    function buildPdfDocumentSrc(filePath, target) {{
      const base = browserPath(filePath);
      if (!base) {{
        return "";
      }}
      if (!target || !(target.page > 0)) {{
        return base;
      }}
      const page = Math.max(1, Number(target.page || 1));
      const fragment = `#page=${{page}}`;
      return base.includes("#") ? base : `${{base}}${{fragment}}`;
    }}

    function postViewerTarget(iframe, target) {{
      if (!iframe || !target) {{
        return;
      }}
      const payload = {{
        type: "gotoPacketTarget",
        page: normalizeViewerPage(target) || Number(target.page || 1),
        highlight_rects: target.rects || [],
        location_label: target.location_label || "命中定位",
        highlight_text: pickHighlightText(target, target.highlight_text),
      }};
      if (payload.page <= 0) {{
        payload.page = 1;
      }}
      const send = function () {{
        try {{
          iframe.contentWindow?.postMessage(payload, "*");
        }} catch (error) {{
          console.warn("postViewerTarget failed", error);
        }}
      }};
      iframe.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
      iframe.addEventListener("load", function () {{
        [0, 120, 320, 640].forEach(function (delay) {{
          window.setTimeout(send, delay);
        }});
      }}, {{ once: true }});
      [0, 120, 320, 640].forEach(function (delay) {{
        window.setTimeout(send, delay);
      }});
    }}

    function browserPath(filePath) {{
      const value = String(filePath || "").trim();
      if (!value) {{
        return "";
      }}
      if (/^(https?:|data:|blob:)/i.test(value)) {{
        return value;
      }}
      return value.replace(/^.*\\/debug_accept\\//, "").replace(/^debug_accept\\//, "");
    }}

    function isPdfLike(doc) {{
      const type = String(doc?.file_type || doc?.preview_type || "").toLowerCase();
      const browserFile = String(doc?.browser_file || doc?.preview_file || "").toLowerCase();
      const fileName = String(doc?.file_name || "").toLowerCase();
      return type === "pdf" || /\\.pdf($|\\?)/.test(browserFile) || /\\.pdf$/.test(fileName);
    }}

    function slugifyDocumentStem(value) {{
      return String(value || "")
        .replace(/\\.[^.\\/\\\\]+$/, "")
        .replace(/[^A-Za-z0-9_-]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .slice(0, 80) || "document";
    }}

    function guessOfficePreviewPdf(doc, project) {{
      const browserFile = String(doc?.browser_file || "").trim();
      if (!browserFile || !/\\.docx?$/i.test(browserFile)) {{
        return "";
      }}
      const sourceLayout = String(doc?.source_layout_file || "").trim();
      if (sourceLayout) {{
        return sourceLayout;
      }}
      const projectNo = String(project?.project_no || "").trim();
      const rolePrefix = doc?.role ? `${{doc.role}}_` : "";
      const stem = slugifyDocumentStem(doc?.file_name || browserFile);
      if (!projectNo || !stem) {{
        return "";
      }}
      return `viewers/original_docs/${{projectNo}}_${{rolePrefix}}${{stem}}/${{stem}}.source-layout.pdf`;
    }}

    function isImageDocument(doc) {{
      const type = String(doc?.file_type || "").toLowerCase();
      const name = String(doc?.file_name || "").toLowerCase();
      return ["png", "jpg", "jpeg", "bmp", "webp", "gif", "tif", "tiff"].includes(type) || /\\.(png|jpe?g|bmp|webp|gif|tiff?)$/.test(name);
    }}

    function displayTitle(payload) {{
      return payload?.display_title || payload?.title || payload?.file_name || "";
    }}

    function isDissertationBundle(doc) {{
      const title = String(doc?.display_title || "");
      const subdocs = Array.isArray(doc?.subdocs) ? doc.subdocs : [];
      return title.includes("硕士学位论文") || subdocs.some(function (item) {{
        return item?.metric_name === "培养研究生" || item?.doc_kind === "学位论文";
      }});
    }}

    function collectDocumentSnippets(project, doc) {{
      if (!project || !doc) {{
        return [];
      }}
      if (doc.role === "yssq") {{
        return [];
      }}
      if (isDissertationBundle(doc)) {{
        return [];
      }}
      const snippets = [];
      const ownExcerpt = String(doc.text_excerpt || "").trim();
      if (ownExcerpt) {{
        snippets.push({{
          metric_name: ROLE_LABELS[doc.role] || "原文摘录",
          title: displayTitle(doc) || doc.file_name || "",
          text: ownExcerpt,
          page: 0,
        }});
      }}
      (project.rows || []).forEach(function (row) {{
        (row.match_details || []).forEach(function (detail) {{
          if (!detail || detail.file_name !== doc.file_name) {{
            return;
          }}
          if (detail.metric_name === "科技论文" && isDissertationBundle(doc)) {{
            return;
          }}
          const text = String(detail.excerpt || detail.reason || "").trim();
          if (!text) {{
            return;
          }}
          const isApplication = detail.doc_kind === "验收申请" || doc.role === "yssq";
          snippets.push({{
            metric_name: isApplication ? "验收申请表完成情况" : (metricDisplayName(row) || detail.metric_name || "相关指标"),
            title: isApplication
              ? (metricDisplayName(row) || detail.metric_name || "相关指标")
              : (detail.display_title || detail.title || doc.display_title || doc.file_name),
            text: text,
            page: detail.viewer_page || detail.source_page || 0,
          }});
        }});
      }});
      return snippets;
    }}

    function renderDocSelectors(project) {{
      const roleTabs = document.getElementById("docRoleTabs");
      const docList = document.getElementById("docList");
      const roles = ["hts", "yssq", "yssqfj"].filter(function (role) {{
        return getDocumentsByRole(project, role).length > 0;
      }});
      roleTabs.innerHTML = roles.map(function (role) {{
        const active = role === currentRole ? "active" : "";
        const docs = getDocumentsByRole(project, role);
        return `<button class="doc-tab ${{active}}" data-role="${{role}}">${{ROLE_LABELS[role] || role}} · ${{docs.length}}</button>`;
      }}).join("");
      roleTabs.querySelectorAll(".doc-tab").forEach(function (button) {{
        button.addEventListener("click", function () {{
          currentRole = button.dataset.role || "hts";
          currentDocIndex = 0;
          currentViewerTarget = null;
          render();
        }});
      }});

      const docs = getDocumentsByRole(project, currentRole);
      docList.dataset.role = currentRole;
      if (currentDocIndex >= docs.length) {{
        currentDocIndex = 0;
      }}
      if (currentRole !== "yssqfj" || docs.length <= 1) {{
        docList.innerHTML = "";
        return;
      }}
      docList.innerHTML = `
        <label class="doc-select-label" for="docSelect">选择验收申请附件</label>
        <select class="doc-select" id="docSelect">
          ${{docs.map(function (doc, index) {{
            const selected = index === currentDocIndex ? "selected" : "";
            const subdocs = getSubdocs(doc);
            const suffix = subdocs.length >= 2 ? ` · 子项 ${{subdocs.length}}` : "";
            return `<option value="${{index}}" ${{selected}}>${{esc(displayTitle(doc) + suffix)}}</option>`;
          }}).join("")}}
        </select>
      `;
      const select = docList.querySelector("#docSelect");
      select?.addEventListener("change", function () {{
        currentDocIndex = Number(select.value || 0);
        currentSubdocIndex = 0;
        currentViewerTarget = null;
        renderViewer(project);
      }});
    }}

    function renderViewer(project) {{
      const docs = getDocumentsByRole(project, currentRole);
      const doc = docs[currentDocIndex] || null;
      const subdocs = getSubdocs(doc);
      const subdoc = getCurrentSubdoc(doc);
      const centerTitle = document.getElementById("centerTitle");
      const centerSubtitle = document.getElementById("centerSubtitle");
      const viewerMeta = document.getElementById("viewerMeta");
      const viewerPreview = document.getElementById("viewerPreview");

      if (!doc) {{
        centerTitle.textContent = "原文材料";
        centerSubtitle.textContent = "当前项目暂无可展示材料。";
        viewerMeta.innerHTML = "";
        viewerPreview.innerHTML = `<div class="viewer-fallback">当前项目暂无该类材料。</div>`;
        return;
      }}

      const guessedPreviewPdf = guessOfficePreviewPdf(doc, project);
      viewerPreview.classList.toggle("compact", doc.role === "yssq" && !doc.viewer_file && !doc.preview_file && !guessedPreviewPdf);
      centerTitle.textContent = ROLE_LABELS[doc.role] || "原文材料";
      centerSubtitle.textContent = `${{project.project_no}} ${{project.project_name}}`;
      const metaSections = [];
      if (subdocs.length >= 2 && currentRole === "yssqfj") {{
        metaSections.push(`
          <div class="viewer-meta-row">
            <div class="viewer-meta-label">子附件</div>
            <div class="viewer-meta-value viewer-subdoc-select">
              <label class="doc-select-label" for="subdocSelect">选择子附件</label>
              <select class="doc-select" id="subdocSelect">
                ${{subdocs.map(function (item, index) {{
                  const selected = index === currentSubdocIndex ? "selected" : "";
                  const label = item.title || item.metric_name || `子项 ${{index + 1}}`;
                  return `<option value="${{index}}" ${{selected}}>${{esc(label)}}</option>`;
                }}).join("")}}
              </select>
            </div>
          </div>
        `);
      }}
      viewerMeta.innerHTML = metaSections.join("");
      const subdocSelect = viewerMeta.querySelector("#subdocSelect");
      subdocSelect?.addEventListener("change", function () {{
        currentSubdocIndex = Number(subdocSelect.value || 0);
        const current = getCurrentSubdoc(doc);
        currentViewerTarget = current ? buildViewerTarget(current, current.title || "子附件定位", "") : null;
        renderViewer(project);
      }});
      if (doc.viewer_file) {{
        const subTarget = currentViewerTarget || (subdoc ? buildViewerTarget(subdoc, subdoc.title || "子附件定位", "") : null);
        const src = buildViewerSrc(doc.viewer_file, subTarget);
        viewerPreview.innerHTML = `<iframe src="${{esc(src)}}" title="${{esc(displayTitle(doc) || doc.file_name)}}"></iframe>`;
        const iframe = viewerPreview.querySelector("iframe");
        if (subTarget && subTarget.page > 0) {{
          postViewerTarget(iframe, subTarget);
        }}
      }} else if (doc.preview_file && String(doc.preview_type || "").toLowerCase() === "pdf") {{
        const src = buildPdfDocumentSrc(doc.preview_file, currentViewerTarget);
        viewerPreview.innerHTML = `<iframe src="${{esc(src)}}" title="${{esc(displayTitle(doc) || doc.file_name)}}"></iframe>`;
      }} else if (doc.preview_file && String(doc.preview_type || "").toLowerCase() === "html") {{
        const src = browserPath(doc.preview_file);
        viewerPreview.innerHTML = `<iframe src="${{esc(src)}}" title="${{esc(displayTitle(doc) || doc.file_name)}}"></iframe>`;
      }} else if (guessedPreviewPdf) {{
        const src = buildPdfDocumentSrc(guessedPreviewPdf, currentViewerTarget);
        viewerPreview.innerHTML = `<iframe src="${{esc(src)}}" title="${{esc(displayTitle(doc) || doc.file_name)}}"></iframe>`;
      }} else if (isPdfLike(doc)) {{
        const src = buildPdfDocumentSrc(doc.browser_file || doc.file_path, currentViewerTarget);
        viewerPreview.innerHTML = `<iframe src="${{esc(src)}}" title="${{esc(displayTitle(doc) || doc.file_name)}}"></iframe>`;
      }} else if (isImageDocument(doc)) {{
        const src = browserPath(doc.browser_file || doc.file_path);
        viewerPreview.innerHTML = `<img class="viewer-image" src="${{esc(src)}}" alt="${{esc(displayTitle(doc) || doc.file_name)}}">`;
      }} else {{
        const href = browserPath(doc.preview_file || doc.browser_file || doc.file_path);
        const snippets = collectDocumentSnippets(project, doc);
        const snippetHtml = snippets.length
          ? `<div class="viewer-snippets">${{snippets.slice(0, 4).map(function (item) {{
              return `
                <div class="viewer-snippet">
                  <div class="viewer-snippet-title">${{esc(item.metric_name)}} · ${{esc(item.title)}}${{item.page ? ` · 第${{item.page}}页` : ""}}</div>
                  <div class="viewer-snippet-text">${{esc(item.text)}}</div>
                </div>
              `;
            }}).join("")}}</div>`
          : "";
        viewerPreview.innerHTML = `
          <div class="viewer-fallback">
            <div class="viewer-fallback-line">当前材料暂不支持内嵌预览。</div>
            <div class="viewer-fallback-line">文件：${{esc(displayTitle(doc) || doc.file_name)}}</div>
            ${{href ? `<a href="${{esc(href)}}" target="_blank" rel="noreferrer">打开原文件</a>` : ""}}
            ${{snippetHtml}}
          </div>
        `;
      }}
    }}

    function resolveSubdocIndex(doc, viewerTarget) {{
      const subdocs = getSubdocs(doc);
      if (!subdocs.length || !viewerTarget) {{
        return 0;
      }}
      const page = normalizeViewerPage(viewerTarget);
      const rects = viewerTarget.rects || [];
      let bestIndex = 0;
      let bestScore = -1;
      subdocs.forEach(function (item, index) {{
        let score = 0;
        const itemPage = normalizeViewerPage(item);
        if (itemPage === page) {{
          score += 4;
        }}
        if (viewerTarget.artifact_key && item.artifact_key === viewerTarget.artifact_key) {{
          score += 8;
        }}
        const targetTitle = String(viewerTarget.title || viewerTarget.highlight_text || "").trim();
        if (targetTitle && String(item.title || "").includes(targetTitle.slice(0, 24))) {{
          score += 4;
        }}
        if (rects.length && Array.isArray(item.viewer_rects) && item.viewer_rects.length) {{
          score += 3;
        }}
        if (score > bestScore) {{
          bestScore = score;
          bestIndex = index;
        }}
      }});
      return bestIndex;
    }}

    function focusDocumentByEvidence(detail, fallbackRole, viewerTarget) {{
      const project = getProject();
      if (!project) {{
        return;
      }}
      let target = null;
      if (detail && detail.file_name) {{
        target = (project.documents || []).find(function (doc) {{
          return doc.file_name === detail.file_name;
        }});
      }}
      currentViewerTarget = viewerTarget || null;
      const previousRole = currentRole;
      const previousDocIndex = currentDocIndex;
      if (target) {{
        currentRole = target.role;
        const docs = getDocumentsByRole(project, currentRole);
        currentDocIndex = docs.findIndex(function (doc) {{
          return doc.file_name === target.file_name;
        }});
        if (currentDocIndex < 0) {{
          currentDocIndex = 0;
        }}
        const activeDoc = docs[currentDocIndex] || null;
        currentSubdocIndex = activeDoc ? resolveSubdocIndex(activeDoc, currentViewerTarget) : 0;
      }} else {{
        currentRole = fallbackRole || "hts";
        currentDocIndex = 0;
        currentSubdocIndex = 0;
      }}
      renderDocSelectors(project);
      if (previousRole === currentRole && previousDocIndex === currentDocIndex) {{
        renderViewer(project);
        const iframe = document.querySelector("#viewerPreview iframe");
        if (iframe && currentViewerTarget) {{
          postViewerTarget(iframe, currentViewerTarget);
        }}
        return;
      }}
      renderViewer(project);
    }}

    function renderProjectPending(message) {{
      const text = message || "正在加载项目结果…";
      document.getElementById("centerSubtitle").textContent = text;
      document.getElementById("docRoleTabs").innerHTML = "";
      document.getElementById("docList").innerHTML = "";
      document.getElementById("viewerMeta").innerHTML = "";
      document.getElementById("viewerPreview").innerHTML = `<div class="viewer-fallback">${{esc(text)}}</div>`;
      document.getElementById("resultSummary").innerHTML = "";
      document.getElementById("warningList").innerHTML = "";
      document.getElementById("resultSections").innerHTML = `<div class="empty">${{esc(text)}}</div>`;
    }}

    function scheduleRenderViewer(project) {{
      const viewerPreview = document.getElementById("viewerPreview");
      viewerPreview.innerHTML = `<div class="viewer-fallback">正在加载预览…</div>`;
      window.setTimeout(function () {{
        renderViewer(project);
      }}, 0);
    }}

    function renderResults(project) {{
      document.getElementById("resultTitle").textContent = "验收核查结果";
      const passed = Number(project.fulfillment_rate || 0) >= 1
        && Number(project.partial_commitments || 0) === 0
        && Number(project.missing_commitments || 0) === 0
        && Number(project.total_commitments || 0) > 0;
      document.getElementById("resultSubtitle").textContent = passed
        ? `${{project.project_no}} · 任务书 ${{project.total_commitments}} 项指标均已满足，验收核查通过`
        : `${{project.project_no}} · KPI履约率 ${{ratioText(project.fulfillment_rate)}} · 按任务书指标展示核查结果`;

      document.getElementById("resultSummary").innerHTML = `
        <div class="stat-card"><div class="stat-label">核查结论</div><div class="stat-value">${{passed ? "通过" : ratioText(project.fulfillment_rate)}}</div></div>
        <div class="stat-card"><div class="stat-label">任务书指标</div><div class="stat-value">${{esc(project.total_commitments || 0)}} 条</div></div>
        <div class="stat-card"><div class="stat-label">完成</div><div class="stat-value">${{esc(project.fulfilled_commitments || 0)}} 条</div></div>
        <div class="stat-card"><div class="stat-label">部分完成 / 未完成</div><div class="stat-value">${{esc(project.partial_commitments || 0)}} / ${{esc(project.missing_commitments || 0)}}</div></div>
      `;

      const warnings = project.warnings || [];
      const passBanner = passed
        ? `<div class="pass-banner">本项目验收核查结论：通过（附件证明材料满足任务书考核指标要求）</div>`
        : "";
      const warningHtml = warnings.map(function (text) {{
        const noteClass = passed ? " info-note" : "";
        return `<div class="warning${{noteClass}}">${{esc(text)}}</div>`;
      }}).join("");
      document.getElementById("warningList").innerHTML = passBanner + warningHtml;

      const sections = document.getElementById("resultSections");
      sections.innerHTML = STATUS_ORDER.map(function (status) {{
        const rows = (project.rows || [])
          .filter(function (row) {{
            return (row.status || "").toLowerCase() === status;
          }})
          .sort(compareRows);
        if (!rows.length) {{
          return "";
        }}
        return `
          <section class="status-section status-${{status}}-section">
            <div class="status-section-head">
              <div class="status-section-title">${{STATUS_LABELS[status]}}</div>
              <div class="chip">${{rows.length}} 条</div>
            </div>
            <div class="metric-list">
              ${{rows.length ? rows.map(function (row) {{
                const active = row.commitment_id === activeCommitmentId ? "active" : "";
                const dedupedDetails = dedupeMatchDetails(row.match_details || []);
                const firstDetail = dedupedDetails[0] || null;
                return `
                  <button class="metric-card status-${{status}}-card ${{active}}" data-commitment-id="${{esc(row.commitment_id)}}">
                    <div class="metric-card-top">
                      <div class="metric-title">${{esc(metricDisplayName(row))}}</div>
                      ${{statusPill(status)}}
                    </div>
                    <div class="metric-values">
                      <strong>指标类型：</strong>${{esc(metricLayerLabel(row))}} ·
                      <strong>申请表状态：</strong>${{esc(statusText(row.application_status))}} ·
                      <strong>附件状态：</strong>${{esc(statusText(row.attachment_status))}}
                    </div>
                    <div class="metric-values">
                      <strong>规则依据：</strong>${{esc(row.rule_basis || "-")}}
                    </div>
                    ${{(row.conflict_flags || []).length ? `<div class="warning info-note">三方冲突：${{esc((row.conflict_flags || []).join("；"))}}</div>` : ""}}
                    <div class="triad-grid">
                      <div class="triad-cell">
                        <div class="triad-label">任务书考核指标</div>
                        <div class="triad-value">${{esc(row.target_display || "-")}}</div>
                      </div>
                      <div class="triad-cell">
                        <div class="triad-label">验收申请表完成情况</div>
                        <div class="triad-value">${{esc(row.application_display || "未提取")}}</div>
                      </div>
                      <div class="triad-cell">
                        <div class="triad-label">附件证明核验值</div>
                        <div class="triad-value">${{esc(row.attachment_display || row.actual_display || "-")}}</div>
                      </div>
                    </div>
                    <div class="metric-status-line status-${{status}}-text">${{STATUS_LABELS[status]}}</div>
                    <div class="consistency-summary">${{esc(row.consistency_summary || "")}}</div>
                    <div class="metric-reason">${{esc(row.reason || "")}}</div>
                    <div class="metric-source">任务书原文：${{esc(row.source_line || "")}}</div>
                    <div class="metric-links">
                      <span class="link-btn" data-jump="taskbook" data-commitment-id="${{esc(row.commitment_id)}}">定位任务书指标</span>
                    </div>
                    <div class="evidence-list">
                      ${{dedupedDetails.map(function (detail, detailIndex) {{
                        return `
                          <div class="evidence-item">
                            <div class="evidence-item-top">
                              <div class="evidence-title">${{esc(detail.display_title || detail.title || detail.file_name || ("证据" + (detailIndex + 1)))}}</div>
                              <span class="chip">${{esc(detail.doc_kind === "验收申请" ? "验收申请表" : "附件证明")}}</span>
                            </div>
                            <div class="evidence-meta">类型：${{esc(detail.doc_kind === "验收申请" ? "验收申请表完成情况" : "附件证明材料")}} · 证据性质：${{esc(evidenceNatureLabel(detail))}} · 判定来源：${{esc(evidenceJudgeSourceLabel(detail))}} · 来源：${{esc(detail.display_title || detail.title || detail.file_name || "-")}} · 页码：${{esc(detail.viewer_page || detail.source_page || "-")}} · 贡献值：${{esc(detail.contribution_value || "-")}}</div>
                            ${{detail.evidence_judge_reason ? `<div class="evidence-excerpt">判定依据：${{esc(detail.evidence_judge_reason)}}</div>` : ""}}
                            <div class="evidence-excerpt">${{esc(detail.excerpt || detail.reason || "")}}</div>
                            <div class="metric-links">
                              <span class="link-btn" data-jump="detail" data-commitment-id="${{esc(row.commitment_id)}}" data-detail-key="${{esc(detailJumpKey(detail))}}">定位这条${{detail.doc_kind === "验收申请" ? "申请表声明" : "附件证据"}}</span>
                            </div>
                          </div>
                        `;
                      }}).join("") || `<div class="empty">当前指标暂未命中可定位证据。</div>`}}
                    </div>
                  </button>
                `;
              }}).join("") : `<div class="empty">当前项目暂无“${{STATUS_LABELS[status]}}”指标。</div>`}}
            </div>
          </section>
        `;
      }}).join("");

      sections.querySelectorAll(".metric-card").forEach(function (card) {{
        card.addEventListener("click", function (event) {{
          if (event.target && event.target.dataset && event.target.dataset.jump) {{
            return;
          }}
          activeCommitmentId = card.dataset.commitmentId || "";
          renderResults(project);
        }});
      }});

      sections.querySelectorAll("[data-jump]").forEach(function (node) {{
        node.addEventListener("click", async function (event) {{
          event.stopPropagation();
          const commitmentId = node.dataset.commitmentId || "";
          const row = (project.rows || []).find(function (item) {{
            return item.commitment_id === commitmentId;
          }});
          if (!row) {{
            return;
          }}
          activeCommitmentId = commitmentId;
          if (node.dataset.jump === "taskbook") {{
            await ensureTaskbookBlocksLoaded();
            focusDocumentByEvidence(
              null,
              "hts",
              buildTaskbookViewerTarget(project, row, "任务书指标位置")
            );
          }} else if (node.dataset.jump === "evidence") {{
            const detail = (row.match_details || [])[0] || null;
            focusDocumentByEvidence(
              detail,
              "yssq",
              buildViewerTarget(detail, "证据命中位置", "")
            );
          }} else if (node.dataset.jump === "detail") {{
            const detailKey = node.dataset.detailKey || "";
            const detail = (row.match_details || []).find(function (item) {{
              return detailJumpKey(item) === detailKey;
            }}) || null;
            focusDocumentByEvidence(
              detail,
              detail && detail.doc_kind === "验收申请" ? "yssq" : "yssqfj",
              buildViewerTarget(detail, "证据命中位置", "")
            );
          }}
          renderResults(project);
        }});
      }});
    }}

    function renderLoading(message) {{
      const text = message || "正在加载验收核查结果…";
      document.getElementById("heroStats").innerHTML = `<div class="empty">${{esc(text)}}</div>`;
      document.getElementById("projectSelect").innerHTML = "";
      document.getElementById("docRoleTabs").innerHTML = "";
      document.getElementById("docList").innerHTML = "";
      document.getElementById("viewerMeta").innerHTML = "";
      document.getElementById("viewerPreview").innerHTML = "";
      document.getElementById("resultSummary").innerHTML = "";
      document.getElementById("warningList").innerHTML = "";
      document.getElementById("resultSections").innerHTML = "";
    }}

    function applyTaskbookBlocks(project) {{
      if (!project || !TASKBOOK_BLOCKS || typeof TASKBOOK_BLOCKS !== "object") {{
        return;
      }}
      const projectNo = String(project.project_no || "");
      const blocks = TASKBOOK_BLOCKS[projectNo];
      if (!blocks) {{
        return;
      }}
      const hts = (project.documents || []).find(function (doc) {{
        return doc.role === "hts";
      }});
      if (hts) {{
        hts.blocks = blocks;
      }}
    }}

    function loadScriptAsset(url, globalName, validator) {{
      return new Promise(function (resolve, reject) {{
        const cached = globalThis[globalName];
        if (validator(cached)) {{
          resolve(cached);
          return;
        }}
        const script = document.createElement("script");
        script.src = url;
        script.async = true;
        script.onload = function () {{
          const payload = globalThis[globalName];
          if (!validator(payload)) {{
            reject(new Error(`${{url}} 未导出 ${{globalName}}`));
            return;
          }}
          resolve(payload);
        }};
        script.onerror = function () {{
          reject(new Error(`无法加载 ${{url}}`));
        }};
        document.head.appendChild(script);
      }});
    }}

    async function fetchJsonAsset(url, validator) {{
      const response = await fetch(url, {{ cache: "no-store" }});
      if (!response.ok) {{
        throw new Error(`${{url}} HTTP ${{response.status}}`);
      }}
      const payload = await response.json();
      if (!validator(payload)) {{
        throw new Error(`${{url}} 格式不正确`);
      }}
      return payload;
    }}

    function renderLoadError(error) {{
      const hint = window.location.protocol === "file:"
        ? "已尝试通过 acceptance_catalog.js 加载。请确认 acceptance_catalog.js 与 index.html 在同一目录；或使用 python -m http.server 8080 后访问 http://localhost:8080/index.html"
        : "请确认 acceptance_catalog.json / acceptance_projects 与 index.html 位于同一目录。";
      renderLoading(`加载失败：${{error?.message || error}}。${{hint}}`);
    }}

    async function loadCatalogFromScript() {{
      CATALOG = await loadScriptAsset(
        CATALOG_LOADER_URL,
        CATALOG_GLOBAL,
        function (value) {{ return Array.isArray(value); }}
      );
    }}

    async function loadCatalog() {{
      const useScriptFirst = window.location.protocol === "file:";
      if (useScriptFirst) {{
        await loadCatalogFromScript();
        return;
      }}
      try {{
        CATALOG = await fetchJsonAsset(CATALOG_URL, function (value) {{ return Array.isArray(value); }});
      }} catch (error) {{
        await loadCatalogFromScript();
      }}
    }}

    async function loadProjectFromScript(projectNo) {{
      const cache = globalThis[PROJECTS_GLOBAL];
      if (cache && cache[projectNo]) {{
        return cache[projectNo];
      }}
      const scriptUrl = `${{PROJECTS_BASE}}/${{encodeURIComponent(projectNo)}}.js`;
      await new Promise(function (resolve, reject) {{
        const script = document.createElement("script");
        script.src = scriptUrl;
        script.async = true;
        script.onload = function () {{
          const payload = (globalThis[PROJECTS_GLOBAL] || {{}})[projectNo];
          if (!payload || typeof payload !== "object") {{
            reject(new Error(`${{scriptUrl}} 未导出项目 ${{projectNo}}`));
            return;
          }}
          resolve(payload);
        }};
        script.onerror = function () {{
          reject(new Error(`无法加载 ${{scriptUrl}}`));
        }};
        document.head.appendChild(script);
      }});
      return (globalThis[PROJECTS_GLOBAL] || {{}})[projectNo];
    }}

    async function loadProjectDetail(projectNo) {{
      if (projectCache.has(projectNo)) {{
        CURRENT_PROJECT = projectCache.get(projectNo);
        return CURRENT_PROJECT;
      }}
      const jsonUrl = `${{PROJECTS_BASE}}/${{encodeURIComponent(projectNo)}}.json`;
      let payload = null;
      if (window.location.protocol !== "file:") {{
        try {{
          payload = await fetchJsonAsset(jsonUrl, function (value) {{
            return value && typeof value === "object" && !Array.isArray(value);
          }});
        }} catch (error) {{
          payload = null;
        }}
      }}
      if (!payload) {{
        payload = await loadProjectFromScript(projectNo);
      }}
      projectCache.set(projectNo, payload);
      CURRENT_PROJECT = payload;
      return payload;
    }}

    async function ensureCurrentProjectLoaded() {{
      const summary = getProjectSummary(currentProjectIndex);
      if (!summary) {{
        return null;
      }}
      const projectNo = String(summary.project_no || "");
      if (CURRENT_PROJECT && String(CURRENT_PROJECT.project_no || "") === projectNo) {{
        return CURRENT_PROJECT;
      }}
      if (projectCache.has(projectNo)) {{
        CURRENT_PROJECT = projectCache.get(projectNo);
        return CURRENT_PROJECT;
      }}
      if (projectLoadingPromise && projectLoadingKey === projectNo) {{
        await projectLoadingPromise;
        return CURRENT_PROJECT;
      }}
      projectLoadingKey = projectNo;
      projectLoadingPromise = loadProjectDetail(projectNo).finally(function () {{
        projectLoadingKey = "";
        projectLoadingPromise = null;
      }});
      await projectLoadingPromise;
      return CURRENT_PROJECT;
    }}

    async function loadBlocksPayload() {{
      const useScriptFirst = window.location.protocol === "file:";
      const validator = function (value) {{
        return value && typeof value === "object" && !Array.isArray(value);
      }};
      if (useScriptFirst) {{
        return loadScriptAsset(BLOCKS_LOADER_URL, BLOCKS_GLOBAL, validator);
      }}
      try {{
        return await fetchJsonAsset(BLOCKS_URL, validator);
      }} catch (error) {{
        return loadScriptAsset(BLOCKS_LOADER_URL, BLOCKS_GLOBAL, validator);
      }}
    }}

    async function ensureTaskbookBlocksLoaded() {{
      const project = getProject();
      if (!project) {{
        return;
      }}
      if (blocksLoaded) {{
        applyTaskbookBlocks(project);
        return;
      }}
      if (blocksLoading) {{
        await blocksLoading;
        applyTaskbookBlocks(project);
        return;
      }}
      blocksLoading = (async function () {{
        TASKBOOK_BLOCKS = await loadBlocksPayload();
        blocksLoaded = true;
        applyTaskbookBlocks(project);
      }})().finally(function () {{
        blocksLoading = null;
      }});
      await blocksLoading;
    }}

    async function renderAsync() {{
      const seq = ++renderSeq;
      const summary = getProjectSummary(currentProjectIndex);
      if (!summary) {{
        renderLoading("暂无项目数据。");
        return;
      }}
      renderHero();
      renderProjectPicker();
      renderProjectPending("正在加载项目结果…");
      const project = await ensureCurrentProjectLoaded();
      if (seq !== renderSeq || !project) {{
        return;
      }}
      ensureSelection();
      renderHero();
      renderResults(project);
      renderDocSelectors(project);
      scheduleRenderViewer(project);
    }}

    function render() {{
      renderAsync().catch(renderLoadError);
    }}

    async function boot() {{
      renderLoading("正在加载项目列表…");
      try {{
        await loadCatalog();
        if (!CATALOG.length) {{
          renderLoading("暂无项目数据。");
          return;
        }}
        await renderAsync();
      }} catch (error) {{
        renderLoadError(error);
      }}
    }}

    boot();
  </script>
</body>
</html>
"""


def write_acceptance_html_shell(output_path: Path | None = None, *, catalog_url: str = ACCEPTANCE_CATALOG_FILENAME) -> Path:
    target = output_path or OUTPUT_PATH
    target.write_text(build_html(catalog_url=catalog_url), encoding="utf-8")
    return target


def main() -> None:
    write_acceptance_html_shell(OUTPUT_PATH)
    if INPUT_PATH.exists():
        data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            write_acceptance_results_files(OUTPUT_PATH.parent, data)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
