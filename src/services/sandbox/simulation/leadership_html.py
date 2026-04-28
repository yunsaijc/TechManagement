"""Standalone sandbox dashboard renderer."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def render_leadership_html(payload: Any, *, title: str = "Sandbox Simulation Report") -> str:
    """Render a single-file dashboard HTML document."""
    return LeadershipHtmlRenderer(title=title).build_html(payload)


class LeadershipHtmlRenderer:
    """Render sandbox simulation payloads into a dashboard-style HTML report."""

    def __init__(self, *, title: str = "Sandbox Simulation Report") -> None:
        self.title = title

    def build_html(self, payload: Any) -> str:
        data = _to_plain_data(payload)
        baseline = _as_dict(data.get("baseline"))
        baseline_portfolio = _as_dict(baseline.get("portfolio"))
        scenario_contract = _as_dict(data.get("scenario_contract"))
        leadership_page = (
            _as_dict(_as_dict(_as_dict(data.get("derived_views")).get("leadership_summary")).get("page"))
            or _as_dict(data.get("leadership_page"))
        )
        visual_scene = (
            _as_dict(data.get("visual_scene"))
            or _as_dict(_as_dict(_as_dict(data.get("derived_views")).get("leadership_summary")).get("visual_scene"))
        )
        basis_docs = [_as_dict(item) for item in scenario_contract.get("basis_documents", []) if _as_dict(item)]
        stages = [_as_dict(item) for item in data.get("stage_impacts", []) if _as_dict(item)]

        overview_cards = _build_overview_cards(
            baseline_portfolio=baseline_portfolio,
            summary_cards=[_as_dict(item) for item in leadership_page.get("summary_cards", []) if _as_dict(item)],
        )
        selection_groups = _build_selection_groups(leadership_page)
        adjustment_panel = _build_adjustment_panel(scenario_contract, leadership_page)
        frontend_payload = _build_frontend_payload(visual_scene, stages, basis_docs)
        payload_json = _json_for_script(frontend_payload)
        report_title = _build_report_title(leadership_page, self.title)

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(report_title)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --paper: #ffffff;
      --paper-soft: #fafbfd;
      --ink: #1f2a37;
      --muted: #7a8699;
      --line: #e8edf5;
      --line-strong: #d6dfea;
      --blue: #3f7cff;
      --blue-soft: rgba(63, 124, 255, 0.10);
      --green: #12b76a;
      --green-soft: rgba(18, 183, 106, 0.12);
      --red: #f04438;
      --red-soft: rgba(240, 68, 56, 0.10);
      --amber: #f79009;
      --amber-soft: rgba(247, 144, 9, 0.12);
      --shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
      --radius-xl: 22px;
      --radius-lg: 16px;
      --radius-md: 12px;
      --sans: "Source Han Sans SC", "PingFang SC", "Noto Sans SC", sans-serif;
      --mono: "JetBrains Mono", "SFMono-Regular", monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: var(--sans);
      background:
        radial-gradient(circle at top left, rgba(63,124,255,0.10), transparent 20%),
        linear-gradient(180deg, #f8faff 0%, #f3f6fb 100%);
    }}
    .page {{
      width: min(1560px, calc(100vw - 24px));
      margin: 0 auto;
      padding: 12px 0 24px;
      display: grid;
      gap: 12px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 14px 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      background: rgba(255,255,255,0.92);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }}
    .brand-mark {{
      width: 40px;
      height: 40px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      color: var(--paper);
      font-weight: 700;
      background: linear-gradient(135deg, #4f7fff, #275bf0);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.22);
    }}
    .brand-copy {{
      min-width: 0;
    }}
    .brand-copy h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.15;
      letter-spacing: -0.03em;
    }}
    .brand-copy p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .top-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .ghost-link,
    .action-btn {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: var(--paper);
      color: var(--ink);
      padding: 10px 12px;
      font: inherit;
      font-size: 13px;
      text-decoration: none;
      cursor: pointer;
    }}
    .action-btn.primary {{
      color: var(--blue);
      border-color: rgba(63,124,255,0.20);
      background: var(--blue-soft);
      font-weight: 600;
    }}
    .dashboard {{
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }}
    .sidebar,
    .main-panel,
    .card {{
      min-width: 0;
    }}
    .sidebar {{
      display: grid;
      gap: 12px;
      position: sticky;
      top: 16px;
      align-self: start;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      background: var(--paper);
      box-shadow: var(--shadow);
    }}
    .sidebar-card {{
      padding: 16px;
      display: grid;
      gap: 14px;
    }}
    .step-head {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
      font-weight: 700;
    }}
    .step-index {{
      width: 22px;
      height: 22px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: var(--blue);
      color: var(--paper);
      font-size: 12px;
      font-family: var(--mono);
    }}
    .toggle-row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .toggle-btn {{
      appearance: none;
      border: 1px solid var(--line);
      background: var(--paper-soft);
      color: var(--muted);
      font: inherit;
      border-radius: 10px;
      padding: 10px 12px;
      text-align: center;
      font-size: 13px;
      cursor: pointer;
    }}
    .toggle-btn.active {{
      color: var(--blue);
      border-color: rgba(63,124,255,0.20);
      background: var(--blue-soft);
      font-weight: 600;
    }}
    .field {{
      display: grid;
      gap: 8px;
    }}
    .field label {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      font-weight: 600;
    }}
    .input,
    .select,
    .textarea {{
      width: 100%;
      border: 1px solid var(--line-strong);
      border-radius: 10px;
      background: var(--paper);
      color: var(--ink);
      font: inherit;
      padding: 10px 12px;
      font-size: 13px;
    }}
    .textarea {{
      min-height: 88px;
      resize: vertical;
    }}
    .selection-panel {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--paper-soft);
      max-height: 280px;
      overflow: auto;
      padding: 10px;
      display: grid;
      gap: 10px;
    }}
    .selection-group {{
      display: grid;
      gap: 8px;
    }}
    .selection-group > strong {{
      font-size: 13px;
      line-height: 1.5;
    }}
    .selection-item {{
      display: flex;
      align-items: start;
      gap: 10px;
      font-size: 13px;
      line-height: 1.5;
      padding: 4px 0;
    }}
    .selection-item input {{
      margin-top: 3px;
      accent-color: var(--blue);
    }}
    .selection-item > div {{
      min-width: 0;
    }}
    .selection-item span {{
      display: block;
      word-break: break-word;
    }}
    .selection-item small {{
      display: block;
      color: var(--muted);
      line-height: 1.5;
      margin-top: 3px;
      word-break: break-word;
    }}
    .range-shell {{
      display: grid;
      gap: 10px;
    }}
    .range-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 52px;
      gap: 10px;
      align-items: center;
    }}
    .range-input {{
      width: 100%;
      accent-color: var(--blue);
    }}
    .range-value {{
      border: 1px solid var(--line-strong);
      border-radius: 10px;
      background: var(--paper-soft);
      padding: 8px 0;
      text-align: center;
      font-size: 13px;
      font-family: var(--mono);
    }}
    .range-scale {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 11px;
      font-family: var(--mono);
    }}
    .run-btn {{
      appearance: none;
      border: 0;
      border-radius: 12px;
      background: linear-gradient(135deg, #4f7fff, #275bf0);
      color: var(--paper);
      font: inherit;
      font-size: 15px;
      font-weight: 700;
      padding: 14px 16px;
      cursor: pointer;
      box-shadow: 0 10px 20px rgba(39,91,240,0.20);
    }}
    .hint-box {{
      padding: 12px;
      border-radius: 12px;
      background: #f7f9fc;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.7;
    }}
    .eta {{
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}
    .main-panel {{
      display: grid;
      gap: 12px;
    }}
    .section-card {{
      padding: 16px;
      display: grid;
      gap: 14px;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: end;
      flex-wrap: wrap;
    }}
    .section-head h2 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
    }}
    .section-head p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .trend-hint {{
      display: inline-flex;
      gap: 16px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .trend-hint span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .year-tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 2px;
    }}
    .year-tab {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--paper-soft);
      color: var(--muted);
      font: inherit;
      font-size: 12px;
      font-weight: 700;
      padding: 7px 11px;
      cursor: pointer;
      transition: border-color .18s ease, background .18s ease, color .18s ease;
    }}
    .year-tab.active {{
      color: var(--blue);
      border-color: rgba(63,124,255,0.26);
      background: var(--blue-soft);
    }}
    .arrow-up {{ color: var(--green); }}
    .arrow-down {{ color: var(--red); }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px 14px 12px;
      background: var(--paper);
      display: grid;
      gap: 8px;
      min-height: 118px;
    }}
    .metric-card span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .metric-card strong {{
      font-size: clamp(28px, 2.1vw, 36px);
      line-height: 1.0;
      letter-spacing: -0.04em;
      font-variant-numeric: tabular-nums;
      word-break: break-word;
    }}
    .metric-delta {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      font-weight: 600;
    }}
    .metric-delta.up {{ color: var(--green); }}
    .metric-delta.down {{ color: var(--red); }}
    .metric-delta.warn {{ color: var(--amber); }}
    .metric-delta.neutral {{ color: var(--blue); }}
    .charts-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .chart-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: var(--paper);
      display: grid;
      gap: 10px;
      min-height: 296px;
      overflow: hidden;
    }}
    .chart-card.wide {{
      grid-column: 1 / -1;
    }}
    .chart-card h3 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.3;
    }}
    .legend {{
      display: flex;
      gap: 14px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }}
    .legend span {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
    }}
    .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 4px;
      display: inline-block;
    }}
    .swatch.base {{ background: #d9e2f1; }}
    .swatch.scenario {{ background: var(--blue); }}
    .swatch.direct {{ background: var(--blue); }}
    .swatch.spill {{ background: var(--green); }}
    .swatch.ghost {{ background: #b8c4d8; }}
    .chart-frame {{
      width: 100%;
      height: 240px;
      display: block;
    }}
    .graph-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-template-areas:
        "graph graph"
        "table side";
      gap: 16px;
      align-items: stretch;
    }}
    .graph-card,
    .table-card,
    .side-card,
    .summary-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: var(--paper);
      display: grid;
      gap: 12px;
      min-width: 0;
    }}
    .graph-card {{ grid-area: graph; }}
    .table-card {{
      grid-area: table;
      align-content: start;
      overflow: hidden;
      min-height: 420px;
    }}
    .side-card {{
      grid-area: side;
      align-content: start;
      overflow: hidden;
      min-height: 420px;
    }}
    .table-scroll {{
      overflow: auto;
      max-height: 352px;
      margin-right: -4px;
      padding-right: 4px;
    }}
    .side-scroll {{
      display: grid;
      gap: 12px;
      overflow: auto;
      max-height: 352px;
      margin-right: -4px;
      padding-right: 4px;
      align-content: start;
    }}
    .graph-toolbar {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .graph-workbench-head {{
      align-items: flex-start;
    }}
    .graph-heading {{
      display: grid;
      gap: 4px;
    }}
    .graph-heading h2 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.3;
    }}
    .graph-heading p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .graph-controls {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
      align-items: center;
    }}
    .view-chip {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--paper-soft);
      color: var(--muted);
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      padding: 8px 12px;
      cursor: pointer;
    }}
    .view-chip.active {{
      color: var(--blue);
      border-color: rgba(63,124,255,0.2);
      background: var(--blue-soft);
    }}
    .mini-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .mini-btn {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper);
      color: var(--ink);
      font: inherit;
      font-size: 12px;
      padding: 8px 10px;
      cursor: pointer;
    }}
    .mini-btn.primary {{
      color: var(--blue);
      border-color: rgba(63,124,255,0.20);
      background: var(--blue-soft);
    }}
    .graph-legend-bar {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .graph-status {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .propagation-shell {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      align-items: start;
    }}
    .propagation-svg {{
      width: 100%;
      height: 520px;
      display: block;
      border-radius: 8px;
      background:
        linear-gradient(#eef3f9 1px, transparent 1px),
        linear-gradient(90deg, #eef3f9 1px, transparent 1px),
        radial-gradient(circle at 50% 48%, rgba(63,124,255,0.14), transparent 34%),
        linear-gradient(180deg, #fbfcfe, #f7f9fc);
      background-size: 32px 32px, 32px 32px, 100% 100%, 100% 100%;
      border: 1px solid var(--line);
    }}
    .path-info {{
      display: grid;
      gap: 10px;
      align-content: start;
    }}
    .focus-box {{
      padding: 12px;
      border-radius: 12px;
      background: var(--paper-soft);
      border: 1px solid var(--line);
      display: grid;
      gap: 8px;
    }}
    .focus-hero {{
      background: linear-gradient(180deg, #fafcff, #f5f8fe);
      border-color: #dbe6f4;
    }}
    .focus-hero h4 {{
      font-size: 16px;
    }}
    .focus-box h4 {{
      margin: 0;
      font-size: 14px;
      line-height: 1.4;
    }}
    .focus-box p,
    .focus-box small {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.65;
    }}
    .focus-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .focus-kpi {{
      padding: 10px;
      border-radius: 8px;
      background: var(--paper);
      border: 1px solid var(--line);
      display: grid;
      gap: 4px;
    }}
    .focus-kpi span {{
      color: var(--muted);
      font-size: 11px;
    }}
    .focus-kpi strong {{
      font-size: 13px;
      line-height: 1.4;
    }}
    .baseline-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
    }}
    .baseline-card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: linear-gradient(180deg, #ffffff, #f7f9fd);
      padding: 12px;
      display: grid;
      gap: 5px;
      min-height: 82px;
    }}
    .baseline-card span {{
      color: var(--muted);
      font-size: 11px;
      line-height: 1.4;
    }}
    .baseline-card strong {{
      font-size: 22px;
      line-height: 1.1;
      letter-spacing: -0.03em;
      font-variant-numeric: tabular-nums;
    }}
    .detail-list {{
      display: grid;
      gap: 8px;
    }}
    .detail-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper-soft);
      font-size: 12px;
      line-height: 1.5;
    }}
    .detail-row strong {{
      min-width: 0;
      font-size: 12px;
      line-height: 1.5;
      word-break: break-word;
    }}
    .detail-row span {{
      color: var(--muted);
      font-family: var(--mono);
      white-space: nowrap;
    }}
    .keyword-cloud {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .keyword-chip {{
      padding: 5px 8px;
      border-radius: 999px;
      background: var(--blue-soft);
      color: var(--blue);
      font-size: 11px;
      font-weight: 600;
    }}
    .history-bars {{
      display: grid;
      gap: 7px;
    }}
    .history-row {{
      display: grid;
      grid-template-columns: 42px minmax(0, 1fr) 42px;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: 11px;
      font-family: var(--mono);
    }}
    .history-track {{
      height: 8px;
      border-radius: 999px;
      background: #edf2f8;
      overflow: hidden;
    }}
    .history-fill {{
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, #7aa5ff, #275bf0);
    }}
    .project-card {{
      display: grid;
      gap: 7px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper-soft);
    }}
    .project-card strong {{
      font-size: 12px;
      line-height: 1.5;
      word-break: break-word;
    }}
    .project-card small {{
      color: var(--muted);
      line-height: 1.55;
    }}
    .table-card h3,
    .side-card h3,
    .graph-card h3,
    .summary-card h3 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.3;
    }}
    .impact-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      table-layout: fixed;
    }}
    .impact-table th,
    .impact-table td {{
      text-align: left;
      padding: 8px 6px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      line-height: 1.45;
      word-break: break-word;
    }}
    .impact-table th {{
      color: var(--muted);
      font-size: 11px;
      font-family: var(--mono);
      letter-spacing: 0.04em;
      text-transform: uppercase;
      position: sticky;
      top: 0;
      background: var(--paper);
      z-index: 1;
    }}
    .impact-table tr:last-child td {{
      border-bottom: 0;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .pill.direct {{
      color: var(--blue);
      background: var(--blue-soft);
    }}
    .pill.spill {{
      color: var(--green);
      background: var(--green-soft);
    }}
    .pill.warn {{
      color: var(--amber);
      background: var(--amber-soft);
    }}
    .pill.info {{
      color: var(--muted);
      background: #f0f4fa;
    }}
    .note-list,
    .summary-list {{
      display: grid;
      gap: 10px;
    }}
    .note-item,
    .summary-item {{
      padding: 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--paper-soft);
    }}
    .note-item p,
    .summary-item p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.65;
      word-break: break-word;
    }}
    .summary-card {{
      padding: 14px 16px;
    }}
    .summary-card .summary-list {{
      grid-template-columns: 1fr;
    }}
    .footer-note {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.7;
      text-align: center;
      padding-top: 4px;
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .node-label {{
      font-size: 12px;
      fill: #4a5568;
      text-anchor: middle;
      pointer-events: none;
    }}
    .node-sub {{
      font-size: 11px;
      fill: #8b97a8;
      text-anchor: middle;
      pointer-events: none;
    }}
    .edge-line {{
      fill: none;
      stroke-width: 2.4;
      stroke-linecap: round;
    }}
    .edge-line.direct {{
      stroke: rgba(63,124,255,0.75);
    }}
    .edge-line.spill {{
      stroke: rgba(18,183,106,0.75);
      stroke-dasharray: 7 7;
    }}
    .edge-line.ghost {{
      stroke: rgba(156,163,175,0.55);
      stroke-dasharray: 4 6;
    }}
    .edge-line.future {{
      opacity: 0.18;
    }}
    .impact-ring {{
      fill: none;
      stroke: rgba(63,124,255,0.14);
      stroke-width: 1.4;
      stroke-dasharray: 5 8;
    }}
    .impact-ring.outer {{
      stroke: rgba(18,183,106,0.14);
    }}
    .edge-flow {{
      fill: none;
      stroke: rgba(63,124,255,0.92);
      stroke-width: 2.4;
      stroke-linecap: round;
      stroke-dasharray: 8 14;
      animation: dash 1.8s linear infinite;
    }}
    .graph-node {{
      cursor: pointer;
    }}
    .graph-node .halo {{
      fill: rgba(63,124,255,0.10);
      opacity: 0;
    }}
    .graph-node.selected .halo,
    .graph-node.current .halo {{
      opacity: 1;
      animation: pulse 1.7s ease-in-out infinite;
    }}
    .graph-node.dim {{
      opacity: 0.24;
    }}
    .graph-node.future {{
      opacity: 0.30;
    }}
    .graph-node .core {{
      stroke-width: 2;
      filter: drop-shadow(0 5px 10px rgba(30, 64, 175, 0.12));
    }}
    .graph-node.direct .core {{
      fill: #dbe8ff;
      stroke: #7aa5ff;
    }}
    .graph-node.spill .core {{
      fill: #dff5ea;
      stroke: #65c18c;
    }}
    .graph-node.negative .core {{
      fill: #fde4e2;
      stroke: #f17c73;
    }}
    .graph-node.center .core {{
      fill: #9cbcff;
      stroke: var(--blue);
    }}
    .graph-node-value {{
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      fill: #1f2a37;
      text-anchor: middle;
      dominant-baseline: middle;
      pointer-events: none;
    }}
    @keyframes dash {{
      from {{ stroke-dashoffset: 0; }}
      to {{ stroke-dashoffset: -44; }}
    }}
    @keyframes pulse {{
      0%, 100% {{ transform: scale(1); opacity: 0.25; }}
      50% {{ transform: scale(1.06); opacity: 0.55; }}
    }}
    @media (max-width: 1280px) {{
      .dashboard,
      .charts-grid,
      .baseline-grid,
      .metric-grid {{
        grid-template-columns: 1fr;
      }}
      .graph-grid {{
        grid-template-columns: 1fr;
        grid-template-areas:
          "graph"
          "table"
          "side";
      }}
      .sidebar {{
        position: static;
      }}
    }}
    @media (max-width: 820px) {{
      .page {{
        width: min(100vw - 16px, 1440px);
        padding-top: 8px;
      }}
      .topbar {{
        align-items: start;
        flex-direction: column;
      }}
      .toggle-row,
      .focus-kpi-grid {{
        grid-template-columns: 1fr;
      }}
      .brand-copy p {{
        white-space: normal;
      }}
      .graph-controls {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    {_render_topbar(report_title)}
    <div class="dashboard">
      {_render_sidebar(selection_groups, adjustment_panel)}
      <main class="main-panel">
        {_render_overview_section(overview_cards, leadership_page)}
        {_render_bottom_section(leadership_page, stages)}
        {_render_summary_section(leadership_page)}
      </main>
    </div>
    <div class="footer-note">
      本页采用沙盘驾驶舱布局：左边设置方案，右边看指标、图表、传导路径和关键结果。
    </div>
  </div>
  <script type="application/json" id="report-data">{payload_json}</script>
  <script>
    (function() {{
      const raw = document.getElementById('report-data');
      if (!raw) return;
      const data = JSON.parse(raw.textContent || '{{}}');
      const scene = data.scene || {{}};
      const yearRuns = scene.yearRuns || {{}};
      const runOrder = (scene.runOrder || Object.keys(yearRuns)).filter((year) => yearRuns[year]);
      let activeYear = String(scene.activeYear || runOrder[0] || '');
      let currentRun = {{}};
      let topics = [];
      let edges = [];
      let topicById = new Map();
      let positions = new Map();

      const searchInput = document.getElementById('selection-search');
      const selectionItems = Array.from(document.querySelectorAll('[data-selection-text]'));
      const methodSelect = document.getElementById('adjustment-method');
      const rangeInput = document.getElementById('adjustment-intensity');
      const rangeValue = document.getElementById('adjustment-intensity-value');
      const runButton = document.getElementById('run-simulation');
      const filterAllButton = document.getElementById('graph-filter-all');
      const filterDirectButton = document.getElementById('graph-filter-direct');
      const toggleSpillButton = document.getElementById('graph-toggle-spill');
      const graphResetButton = document.getElementById('graph-reset');
      const yearTabs = document.getElementById('year-run-tabs');
      const metricGrid = document.getElementById('metric-grid');
      const baselineContextRoot = document.getElementById('baseline-context-root');
      const applicationChart = document.getElementById('application-chart');
      const fundedChart = document.getElementById('funded-chart');
      const fundingChart = document.getElementById('funding-chart');
      const applicationChartTitle = document.getElementById('application-chart-title');
      const fundedChartTitle = document.getElementById('funded-chart-title');
      const fundingChartTitle = document.getElementById('funding-chart-title');
      const impactTableRoot = document.getElementById('impact-table-root');
      const graphStatus = document.getElementById('graph-status');
      const graphSvg = document.getElementById('propagation-graph');
      const edgeLayer = document.getElementById('graph-edge-layer');
      const flowLayer = document.getElementById('graph-flow-layer');
      const nodeLayer = document.getElementById('graph-node-layer');
      const stageFocusTitle = document.getElementById('stage-focus-title');
      const stageFocusCopy = document.getElementById('stage-focus-copy');
      const stageFocusKpis = document.getElementById('stage-focus-kpis');
      const topicHistory = document.getElementById('topic-history');
      const topicGuides = document.getElementById('topic-guides');
      const topicInstitutions = document.getElementById('topic-institutions');
      const topicProjects = document.getElementById('topic-projects');

      let selectedTopicId = '';
      let filterMode = 'all';
      let showSpill = true;

      function setCurrentRun(year) {{
        activeYear = String(year || activeYear || runOrder[0] || '');
        currentRun = yearRuns[activeYear] || {{
          label: activeYear || '当前推演',
          focusTopicId: scene.focusTopicId,
          topics: scene.topics || [],
          edges: scene.edges || [],
          validation: {{}},
        }};
        topics = (currentRun.topics || []).filter(Boolean);
        edges = (currentRun.edges || []).filter(Boolean);
        topicById = new Map(topics.map((item) => [item.id, item]));
        positions = layoutTopics();
      }}

      function escapeHtml(value) {{
        return String(value || '')
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;')
          .replaceAll('"', '&quot;')
          .replaceAll("'", '&#39;');
      }}

      function topicKey(item) {{
        return String(item.graph_node_id || (item.topic_id ? `topic:${{item.topic_id}}` : item.topic_id || ''));
      }}

      function compactValue(metric, value) {{
        const numeric = Number(value || 0);
        if (!Number.isFinite(numeric)) return '-';
        const key = String(metric || '');
        if (key.includes('funding')) return `${{numeric >= 0 ? '+' : ''}}${{numeric.toFixed(1)}}`;
        if (key.includes('density') || key.includes('risk') || key.includes('score') || key.includes('centrality') || key.includes('migration')) {{
          return `${{numeric >= 0 ? '+' : ''}}${{numeric.toFixed(3)}}`;
        }}
        return `${{numeric >= 0 ? '+' : ''}}${{Math.round(numeric)}}`;
      }}

      function plainNumber(value, digits) {{
        const numeric = Number(value || 0);
        if (!Number.isFinite(numeric)) return '-';
        return numeric.toLocaleString('zh-CN', {{
          maximumFractionDigits: digits,
          minimumFractionDigits: digits,
        }});
      }}

      function signedNumber(value, digits) {{
        const numeric = Number(value || 0);
        if (!Number.isFinite(numeric)) return '-';
        const sign = numeric >= 0 ? '+' : '';
        return `${{sign}}${{plainNumber(numeric, digits)}}`;
      }}

      function runRoleLabel(run) {{
        const role = String((run || {{}}).role || '');
        if (role === 'current') return '当前推演';
        if (role === 'backtest') return '历史回测';
        if (role === 'future') return '未来延伸';
        return '对照批次';
      }}

      function currentBaselineContext() {{
        return currentRun.baselineContext || scene.baselineContext || {{}};
      }}

      function isBacktestRun() {{
        return String((currentRun || {{}}).role || '') === 'backtest';
      }}

      function metricValue(topic, key) {{
        return Number(((topic || {{}}).metrics || {{}})[key] || 0);
      }}

      function runRows() {{
        return topics.map((topic) => {{
          const backtest = topic.backtest || null;
          if (backtest) {{
            const predicted = backtest.predicted || {{}};
            const actual = backtest.actual || {{}};
            const error = backtest.error || {{}};
            const majorDelta = Math.max(
              Math.abs(Number(error.application || 0)),
              Math.abs(Number(error.funded || 0)) * 4,
              Math.abs(Number(error.funding || 0)) / 20,
            );
            return {{
              id: topic.id,
              label: topic.shortLabel || topic.label || '未标注主题',
              fullLabel: topic.label || topic.shortLabel || '未标注主题',
              baselineApplication: Number(actual.application || 0),
              baselineFunded: Number(actual.funded || 0),
              baselineFunding: Number(actual.funding || 0),
              deltaApplication: Number(error.application || 0),
              deltaFunded: Number(error.funded || 0),
              deltaFunding: Number(error.funding || 0),
              predictedApplication: Number(predicted.application || 0),
              predictedFunded: Number(predicted.funded || 0),
              predictedFunding: Number(predicted.funding || 0),
              actualApplication: Number(actual.application || 0),
              actualFunded: Number(actual.funded || 0),
              actualFunding: Number(actual.funding || 0),
              errorApplication: Number(error.application || 0),
              errorFunded: Number(error.funded || 0),
              errorFunding: Number(error.funding || 0),
              errorApplicationPct: Number(error.applicationPct || 0),
              errorFundedPct: Number(error.fundedPct || 0),
              errorFundingPct: Number(error.fundingPct || 0),
              majorDelta,
              direct: Boolean(topic.direct),
              backtest: true,
            }};
          }}
          const deltaApplication = metricValue(topic, 'deltaApplication');
          const deltaFunded = metricValue(topic, 'deltaFunded');
          const deltaFunding = metricValue(topic, 'deltaFunding');
          const majorDelta = Math.max(Math.abs(deltaFunding), Math.abs(deltaFunded), Math.abs(deltaApplication));
          return {{
            id: topic.id,
            label: topic.shortLabel || topic.label || '未标注主题',
            fullLabel: topic.label || topic.shortLabel || '未标注主题',
            baselineApplication: Number(topic.baselineApplication || 0),
            baselineFunded: Number(topic.baselineFunded || 0),
            baselineFunding: Number(topic.baselineFunding || 0),
            deltaApplication,
            deltaFunded,
            deltaFunding,
            majorDelta,
            direct: Boolean(topic.direct),
          }};
        }});
      }}

      function chartAxisLabel(value, maxChars) {{
        const text = String(value || '');
        return text.length > maxChars ? `${{text.slice(0, Math.max(1, maxChars - 1))}}…` : text;
      }}

      function svgEmpty(message) {{
        return `<svg class="chart-frame" viewBox="0 0 360 220"><text x="20" y="28" fill="#98a2b3" font-size="12">${{escapeHtml(message)}}</text></svg>`;
      }}

      function barChartSvg(rows, metricKey, baselineKey) {{
        const chartRows = rows
          .filter((row) => Math.abs(Number(row[metricKey] || 0)) > 1e-9)
          .sort((a, b) => Math.abs(Number(b[metricKey] || 0)) - Math.abs(Number(a[metricKey] || 0)))
          .slice(0, 10);
        if (!chartRows.length) return svgEmpty('当前筛选下没有变化项。');
        const values = [];
        chartRows.forEach((row) => {{
          const baseline = Math.max(Number(row[baselineKey] || 0), 0);
          const scenario = Math.max(baseline + Number(row[metricKey] || 0), 0);
          values.push(baseline, scenario);
        }});
        const maxValue = Math.max(...values, 1);
        const chartWidth = 360;
        const left = 42;
        const bottom = 178;
        const usableHeight = 128;
        const groupWidth = (chartWidth - left - 16) / chartRows.length;
        const barWidth = Math.max(8, (groupWidth - 8) / 2);
        const grid = [];
        const labels = [];
        const bars = [];
        for (let step = 0; step < 5; step += 1) {{
          const y = bottom - usableHeight * step / 4;
          const value = maxValue * step / 4;
          grid.push(`<line x1="${{left}}" y1="${{y.toFixed(1)}}" x2="${{chartWidth - 10}}" y2="${{y.toFixed(1)}}" stroke="#edf2f8" stroke-width="1"/>`);
          labels.push(`<text x="${{left - 8}}" y="${{(y + 4).toFixed(1)}}" text-anchor="end" fill="#98a2b3" font-size="11">${{Math.round(value)}}</text>`);
        }}
        chartRows.forEach((row, index) => {{
          const baseline = Math.max(Number(row[baselineKey] || 0), 0);
          const scenario = Math.max(baseline + Number(row[metricKey] || 0), 0);
          const groupX = left + index * groupWidth + 4;
          const baselineH = usableHeight * baseline / maxValue;
          const scenarioH = usableHeight * scenario / maxValue;
          bars.push(`<rect x="${{groupX.toFixed(1)}}" y="${{(bottom - baselineH).toFixed(1)}}" width="${{barWidth.toFixed(1)}}" height="${{baselineH.toFixed(1)}}" rx="4" fill="#d9e2f1"/>`);
          bars.push(`<rect x="${{(groupX + barWidth + 4).toFixed(1)}}" y="${{(bottom - scenarioH).toFixed(1)}}" width="${{barWidth.toFixed(1)}}" height="${{scenarioH.toFixed(1)}}" rx="4" fill="#3f7cff"/>`);
          const labelX = groupX + barWidth;
          labels.push(`<text x="${{labelX.toFixed(1)}}" y="${{(bottom + 16).toFixed(1)}}" text-anchor="end" transform="rotate(-38 ${{labelX.toFixed(1)}} ${{(bottom + 16).toFixed(1)}})" fill="#7a8699" font-size="11">${{escapeHtml(chartAxisLabel(row.label, 12))}}</text>`);
        }});
        return `<svg class="chart-frame" viewBox="0 0 360 220" role="img" aria-label="批次对比柱状图">${{grid.join('')}}${{bars.join('')}}${{labels.join('')}}</svg>`;
      }}

      function bubbleChartSvg(rows) {{
        const chartRows = rows
          .filter((row) => Math.abs(Number(row.deltaFunding || 0)) > 1e-9)
          .sort((a, b) => Math.abs(Number(b.deltaFunding || 0)) - Math.abs(Number(a.deltaFunding || 0)))
          .slice(0, 8);
        if (!chartRows.length) return svgEmpty('当前批次没有经费变化。');
        const maxX = Math.max(...chartRows.map((row) => Number(row.baselineFunding || 0)), 1);
        const maxY = Math.max(...chartRows.map((row) => Number(row.baselineFunding || 0) + Number(row.deltaFunding || 0)), 1);
        const maxR = Math.max(...chartRows.map((row) => Math.abs(Number(row.deltaFunding || 0))), 1);
        const palette = ['#7aa5ff', '#69d2a6', '#ffb454', '#b18cff', '#ff8d7a', '#91d5ff', '#9be29b', '#ffd166'];
        const grid = [];
        const points = [];
        const legends = [];
        for (let step = 0; step < 5; step += 1) {{
          const x = 48 + 224 * step / 4;
          const y = 180 - 136 * step / 4;
          grid.push(`<line x1="${{x.toFixed(1)}}" y1="28" x2="${{x.toFixed(1)}}" y2="180" stroke="#edf2f8"/>`);
          grid.push(`<line x1="48" y1="${{y.toFixed(1)}}" x2="272" y2="${{y.toFixed(1)}}" stroke="#edf2f8"/>`);
        }}
        chartRows.forEach((row, index) => {{
          const color = palette[index % palette.length];
          const x = 48 + 224 * (Number(row.baselineFunding || 0) / maxX);
          const y = 180 - 136 * ((Number(row.baselineFunding || 0) + Number(row.deltaFunding || 0)) / maxY);
          const r = 8 + 18 * (Math.abs(Number(row.deltaFunding || 0)) / maxR);
          points.push(`<circle cx="${{x.toFixed(1)}}" cy="${{y.toFixed(1)}}" r="${{r.toFixed(1)}}" fill="${{color}}" fill-opacity="0.68" stroke="${{color}}" stroke-opacity="0.9"/>`);
          legends.push(`<text x="286" y="${{28 + index * 18}}" fill="#667085" font-size="11">${{escapeHtml(chartAxisLabel(row.label, 18))}}</text><circle cx="274" cy="${{24 + index * 18}}" r="5" fill="${{color}}" fill-opacity="0.85"/>`);
        }});
        return `<svg class="chart-frame" viewBox="0 0 360 220" role="img" aria-label="批次经费气泡图"><text x="20" y="20" fill="#98a2b3" font-size="11">调整后经费</text><text x="190" y="208" fill="#98a2b3" font-size="11">基准经费</text>${{grid.join('')}}${{points.join('')}}${{legends.join('')}}</svg>`;
      }}

      function backtestBarChartSvg(rows, predictedKey, actualKey) {{
        const chartRows = rows
          .filter((row) => Number(row[predictedKey] || 0) > 0 || Number(row[actualKey] || 0) > 0)
          .sort((a, b) => Math.max(Number(b[predictedKey] || 0), Number(b[actualKey] || 0)) - Math.max(Number(a[predictedKey] || 0), Number(a[actualKey] || 0)))
          .slice(0, 10);
        if (!chartRows.length) return svgEmpty('当前回测批次没有可展示的预测值。');
        const maxValue = Math.max(...chartRows.flatMap((row) => [Number(row[predictedKey] || 0), Number(row[actualKey] || 0)]), 1);
        const chartWidth = 360;
        const left = 42;
        const bottom = 178;
        const usableHeight = 128;
        const groupWidth = (chartWidth - left - 16) / chartRows.length;
        const barWidth = Math.max(8, (groupWidth - 8) / 2);
        const grid = [];
        const labels = [];
        const bars = [];
        for (let step = 0; step < 5; step += 1) {{
          const y = bottom - usableHeight * step / 4;
          const value = maxValue * step / 4;
          grid.push(`<line x1="${{left}}" y1="${{y.toFixed(1)}}" x2="${{chartWidth - 10}}" y2="${{y.toFixed(1)}}" stroke="#edf2f8" stroke-width="1"/>`);
          labels.push(`<text x="${{left - 8}}" y="${{(y + 4).toFixed(1)}}" text-anchor="end" fill="#98a2b3" font-size="11">${{Math.round(value)}}</text>`);
        }}
        chartRows.forEach((row, index) => {{
          const predicted = Math.max(Number(row[predictedKey] || 0), 0);
          const actual = Math.max(Number(row[actualKey] || 0), 0);
          const groupX = left + index * groupWidth + 4;
          const predictedH = usableHeight * predicted / maxValue;
          const actualH = usableHeight * actual / maxValue;
          bars.push(`<rect x="${{groupX.toFixed(1)}}" y="${{(bottom - predictedH).toFixed(1)}}" width="${{barWidth.toFixed(1)}}" height="${{predictedH.toFixed(1)}}" rx="4" fill="#3f7cff"/>`);
          bars.push(`<rect x="${{(groupX + barWidth + 4).toFixed(1)}}" y="${{(bottom - actualH).toFixed(1)}}" width="${{barWidth.toFixed(1)}}" height="${{actualH.toFixed(1)}}" rx="4" fill="#d9e2f1"/>`);
          const labelX = groupX + barWidth;
          labels.push(`<text x="${{labelX.toFixed(1)}}" y="${{(bottom + 16).toFixed(1)}}" text-anchor="end" transform="rotate(-38 ${{labelX.toFixed(1)}} ${{(bottom + 16).toFixed(1)}})" fill="#7a8699" font-size="11">${{escapeHtml(chartAxisLabel(row.label, 12))}}</text>`);
        }});
        return `<svg class="chart-frame" viewBox="0 0 360 220" role="img" aria-label="回测对比柱状图">${{grid.join('')}}${{bars.join('')}}${{labels.join('')}}</svg>`;
      }}

      function errorClass(value, actual) {{
        const numeric = Number(value || 0);
        const denominator = Math.max(Math.abs(Number(actual || 0)), 1);
        const ratio = Math.abs(numeric) / denominator;
        if (ratio <= 0.08) return 'up';
        if (ratio <= 0.20) return 'warn';
        return numeric >= 0 ? 'down' : 'neutral';
      }}

      function backtestDeltaText(actual, error, digits, unit) {{
        const suffix = unit ? ` ${{unit}}` : '';
        return `与真实值偏差 ${{signedNumber(error, digits)}}${{suffix}}`;
      }}

      function renderRunMetrics(rows) {{
        if (!metricGrid) return;
        const sum = (key) => rows.reduce((total, row) => total + Number(row[key] || 0), 0);
        if (isBacktestRun()) {{
          const predictedApplication = sum('predictedApplication');
          const actualApplication = sum('actualApplication');
          const errorApplication = sum('errorApplication');
          const predictedFunded = sum('predictedFunded');
          const actualFunded = sum('actualFunded');
          const errorFunded = sum('errorFunded');
          const predictedFunding = sum('predictedFunding');
          const actualFunding = sum('actualFunding');
          const errorFunding = sum('errorFunding');
          const cards = [
            {{ label: '当前批次', value: currentRun.year || activeYear || '-', delta: '回测', cls: 'neutral' }},
            {{ label: '验证方向', value: String(rows.length), delta: '研究方向', cls: 'neutral' }},
            {{ label: '申报项目数', value: plainNumber(predictedApplication, 0), delta: backtestDeltaText(actualApplication, errorApplication, 0, '项'), cls: errorClass(errorApplication, actualApplication) }},
            {{ label: '立项项目数', value: plainNumber(predictedFunded, 0), delta: backtestDeltaText(actualFunded, errorFunded, 0, '项'), cls: errorClass(errorFunded, actualFunded) }},
            {{ label: '经费', value: plainNumber(predictedFunding, 1), delta: backtestDeltaText(actualFunding, errorFunding, 1, '万元'), cls: errorClass(errorFunding, actualFunding) }},
          ];
          metricGrid.innerHTML = cards.map((card) => `
            <article class="metric-card">
              <span>${{escapeHtml(card.label)}}</span>
              <strong>${{escapeHtml(card.value)}}</strong>
              <div class="metric-delta ${{card.cls || 'up'}}">${{escapeHtml(card.delta)}}</div>
            </article>
          `).join('');
          return;
        }}
        const cards = [
          {{ label: '当前批次', value: currentRun.year || activeYear || '-', delta: runRoleLabel(currentRun), down: false }},
          {{ label: '研究方向', value: String(rows.filter((row) => row.majorDelta > 1e-9).length), delta: '有变化对象', down: false }},
          {{ label: '申报变化', value: signedNumber(sum('deltaApplication'), 0), delta: '项目数', down: sum('deltaApplication') < 0 }},
          {{ label: '立项变化', value: signedNumber(sum('deltaFunded'), 0), delta: '项目数', down: sum('deltaFunded') < 0 }},
          {{ label: '经费变化', value: signedNumber(sum('deltaFunding'), 1), delta: '万元', down: sum('deltaFunding') < 0 }},
        ];
        metricGrid.innerHTML = cards.map((card) => `
          <article class="metric-card">
            <span>${{escapeHtml(card.label)}}</span>
            <strong>${{escapeHtml(card.value)}}</strong>
            <div class="metric-delta ${{card.down ? 'down' : 'up'}}">${{escapeHtml(card.delta)}}</div>
          </article>
        `).join('');
      }}

      function renderBaselineContext(rows) {{
        if (!baselineContextRoot) return;
        const ctx = currentBaselineContext();
        const changedCount = rows.filter((row) => row.majorDelta > 1e-9).length;
        const cards = [
          {{ label: `${{ctx.year || activeYear || ''}} 年公开项目`, value: plainNumber(ctx.projectCount || 0, 0) }},
          {{ label: '基线研究方向', value: plainNumber(ctx.topicCount || 0, 0) }},
          {{ label: '指南项', value: plainNumber(ctx.guideCount || 0, 0) }},
          {{ label: '专项', value: plainNumber(ctx.programCount || 0, 0) }},
          {{ label: '承担单位', value: plainNumber(ctx.institutionCount || 0, 0) }},
          {{ label: isBacktestRun() ? '参与验证方向' : '本次有变化方向', value: `${{plainNumber(isBacktestRun() ? rows.length : changedCount, 0)}} / ${{plainNumber(ctx.topicCount || rows.length || 0, 0)}}` }},
        ];
        baselineContextRoot.innerHTML = cards.map((card) => `
          <article class="baseline-card">
            <span>${{escapeHtml(card.label)}}</span>
            <strong>${{escapeHtml(card.value)}}</strong>
          </article>
        `).join('');
      }}

      function renderRunCharts(rows) {{
        if (isBacktestRun()) {{
          if (applicationChartTitle) applicationChartTitle.textContent = '申报项目数回测 TOP10';
          if (fundedChartTitle) fundedChartTitle.textContent = '立项项目数回测 TOP10';
          if (fundingChartTitle) fundingChartTitle.textContent = '经费回测 TOP10';
          if (applicationChart) applicationChart.innerHTML = backtestBarChartSvg(rows, 'predictedApplication', 'actualApplication');
          if (fundedChart) fundedChart.innerHTML = backtestBarChartSvg(rows, 'predictedFunded', 'actualFunded');
          if (fundingChart) fundingChart.innerHTML = backtestBarChartSvg(rows, 'predictedFunding', 'actualFunding');
          return;
        }}
        if (applicationChartTitle) applicationChartTitle.textContent = '申报项目数变化 TOP10（个）';
        if (fundedChartTitle) fundedChartTitle.textContent = '立项项目数变化 TOP10（个）';
        if (fundingChartTitle) fundingChartTitle.textContent = '经费变化 TOP10（万元）';
        if (applicationChart) applicationChart.innerHTML = barChartSvg(rows, 'deltaApplication', 'baselineApplication');
        if (fundedChart) fundedChart.innerHTML = barChartSvg(rows, 'deltaFunded', 'baselineFunded');
        if (fundingChart) fundingChart.innerHTML = bubbleChartSvg(rows);
      }}

      function renderRunImpactTable(rows) {{
        if (!impactTableRoot) return;
        if (isBacktestRun()) {{
          const tableRows = rows
            .filter((row) => row.predictedApplication > 0 || row.actualApplication > 0)
            .sort((a, b) => Number(b.majorDelta || 0) - Number(a.majorDelta || 0))
            .slice(0, 8);
          if (!tableRows.length) {{
            impactTableRoot.innerHTML = '<div class="note-item"><p>当前回测批次没有可展示的预测对比。</p></div>';
            return;
          }}
          const body = tableRows.map((row) => `
            <tr>
              <td><span class="pill info">回测</span></td>
              <td>${{escapeHtml(row.fullLabel)}}</td>
              <td>${{escapeHtml(`申报 ${{plainNumber(row.predictedApplication, 0)}}｜立项 ${{plainNumber(row.predictedFunded, 0)}}｜经费 ${{plainNumber(row.predictedFunding, 1)}}`)}}</td>
              <td>${{escapeHtml(`申报 ${{plainNumber(row.actualApplication, 0)}}｜立项 ${{plainNumber(row.actualFunded, 0)}}｜经费 ${{plainNumber(row.actualFunding, 1)}}`)}}</td>
              <td>${{escapeHtml(`申报 ${{signedNumber(row.errorApplication, 0)}}｜立项 ${{signedNumber(row.errorFunded, 0)}}｜经费 ${{signedNumber(row.errorFunding, 1)}}`)}}</td>
            </tr>
          `).join('');
          impactTableRoot.innerHTML = `<table class="impact-table">
            <thead>
              <tr>
                <th>类型</th>
                <th>研究方向</th>
                <th>预测值</th>
                <th>真实值</th>
                <th>偏差</th>
              </tr>
            </thead>
            <tbody>${{body}}</tbody>
          </table>`;
          return;
        }}
        const tableRows = rows
          .filter((row) => row.majorDelta > 1e-9)
          .sort((a, b) => Number(b.majorDelta || 0) - Number(a.majorDelta || 0))
          .slice(0, 8);
        if (!tableRows.length) {{
          impactTableRoot.innerHTML = '<div class="note-item"><p>当前批次没有明显变化。</p></div>';
          return;
        }}
        const body = tableRows.map((row) => {{
          const impactClass = row.direct ? 'direct' : 'spill';
          const impactType = row.direct ? '直接影响' : '外溢影响';
          const deltaParts = [];
          if (Math.abs(row.deltaFunding) > 1e-9) deltaParts.push(`经费 ${{signedNumber(row.deltaFunding, 1)}}`);
          if (Math.abs(row.deltaFunded) > 1e-9) deltaParts.push(`立项 ${{signedNumber(row.deltaFunded, 0)}}`);
          if (Math.abs(row.deltaApplication) > 1e-9) deltaParts.push(`申报 ${{signedNumber(row.deltaApplication, 0)}}`);
          const baseline = `申报 ${{plainNumber(row.baselineApplication, 0)}}｜立项 ${{plainNumber(row.baselineFunded, 0)}}｜经费 ${{plainNumber(row.baselineFunding, 1)}}`;
          return `<tr>
            <td><span class="pill ${{impactClass}}">${{impactType}}</span></td>
            <td>${{escapeHtml(row.fullLabel)}}</td>
            <td>${{escapeHtml(deltaParts.join('，') || '无明显变化')}}</td>
            <td>${{escapeHtml(baseline)}}</td>
          </tr>`;
        }}).join('');
        impactTableRoot.innerHTML = `<table class="impact-table">
          <thead>
            <tr>
              <th>影响类型</th>
              <th>研究方向</th>
              <th>本批次变化</th>
              <th>当前规模</th>
            </tr>
          </thead>
          <tbody>${{body}}</tbody>
        </table>`;
      }}

      function renderRunOverview() {{
        const rows = runRows();
        renderBaselineContext(rows);
        renderRunMetrics(rows);
        renderRunCharts(rows);
        renderRunImpactTable(rows);
      }}

      function splitLabel(text, maxChars) {{
        const value = String(text || '').trim();
        if (value.length <= maxChars) return [value];
        const lines = [];
        for (let index = 0; index < value.length && lines.length < 2; index += maxChars) {{
          lines.push(value.slice(index, index + maxChars));
        }}
        if (value.length > maxChars * 2) {{
          lines[1] = `${{lines[1].slice(0, Math.max(1, maxChars - 1))}}…`;
        }}
        return lines;
      }}

      function curvePath(from, to, bend) {{
        const controlX = (from.x + to.x) / 2;
        const controlY = (from.y + to.y) / 2 + bend;
        return `M ${{from.x}} ${{from.y}} Q ${{controlX}} ${{controlY}} ${{to.x}} ${{to.y}}`;
      }}

      function createSvgEl(name, attrs) {{
        const node = document.createElementNS('http://www.w3.org/2000/svg', name);
        Object.entries(attrs || {{}}).forEach(([key, value]) => {{
          if (value !== undefined && value !== null) {{
            node.setAttribute(key, String(value));
          }}
        }});
        return node;
      }}
      function visibleTopics() {{
        return topics.filter((topic) => {{
          if (filterMode === 'direct' && !topic.direct) return false;
          if (!showSpill && !topic.direct) return false;
          return true;
        }});
      }}

      function visibleEdges() {{
        return edges.filter((edge) => {{
          if (filterMode === 'direct' && edge.kind !== 'direct') return false;
          if (!showSpill && edge.kind === 'spill') return false;
          return true;
        }});
      }}

      function topicEntry(topic) {{
        return (topic && topic.primaryEntry) || {{ item: {{}} }};
      }}

      function upstream(topicId) {{
        return Array.from(new Set(visibleEdges().filter((edge) => edge.targetId === topicId).map((edge) => edge.sourceId)));
      }}

      function downstream(topicId) {{
        return Array.from(new Set(visibleEdges().filter((edge) => edge.sourceId === topicId).map((edge) => edge.targetId)));
      }}

      function defaultTopicId() {{
        const visible = visibleTopics();
        return (visible.find((item) => item.id === currentRun.focusTopicId) || visible[0] || {{}}).id || '';
      }}

      function ringPoint(index, count, radiusX, radiusY, centerX, centerY, startAngle) {{
        if (!count) return {{ x: centerX, y: centerY }};
        const angle = startAngle + (Math.PI * 2 * index) / count;
        return {{
          x: centerX + Math.cos(angle) * radiusX,
          y: centerY + Math.sin(angle) * radiusY,
        }};
      }}

      function layoutTopics() {{
        const positions = new Map();
        const centerX = 360;
        const centerY = 260;
        const maxMagnitude = Math.max(...topics.map((item) => item.maxAbs), 1);
        const focus = topicById.get(currentRun.focusTopicId) || topics[0];
        if (focus) {{
          positions.set(focus.id, {{
            x: centerX,
            y: centerY,
            r: 30 + (focus.maxAbs / maxMagnitude) * 12,
          }});
        }}
        const directNodes = topics.filter((item) => item.direct && item.id !== (focus || {{}}).id);
        const spillNodes = topics.filter((item) => !item.direct);
        directNodes.forEach((topic, index) => {{
          const point = ringPoint(index, directNodes.length, 220, 135, centerX, centerY, -Math.PI / 2);
          positions.set(topic.id, {{
            x: point.x,
            y: point.y,
            r: 20 + (topic.maxAbs / maxMagnitude) * 10,
          }});
        }});
        spillNodes.forEach((topic, index) => {{
          const point = ringPoint(index, spillNodes.length, 310, 205, centerX, centerY, -Math.PI / 3);
          positions.set(topic.id, {{
            x: point.x,
            y: point.y,
            r: 17 + (topic.maxAbs / maxMagnitude) * 8,
          }});
        }});
        return positions;
      }}

      function renderSimpleList(root, items, emptyText) {{
        if (!root) return;
        if (!items.length) {{
          root.innerHTML = `<div class="focus-box"><small>${{escapeHtml(emptyText)}}</small></div>`;
          return;
        }}
        root.innerHTML = items.map((item) => `
          <div class="focus-box">
            <h4>${{escapeHtml(item.title)}}</h4>
            <small>${{escapeHtml(item.meta || '')}}</small>
          </div>
        `).join('');
      }}

      function renderBucketRows(root, items, emptyText) {{
        if (!root) return;
        const rows = (items || []).filter(Boolean).slice(0, 8);
        if (!rows.length) {{
          root.innerHTML = `<div class="focus-box"><small>${{escapeHtml(emptyText)}}</small></div>`;
          return;
        }}
        root.innerHTML = `<div class="detail-list">${{rows.map((item) => `
          <div class="detail-row">
            <strong>${{escapeHtml(item.label || '-')}}</strong>
            <span>${{plainNumber(item.count || 0, 0)}} 项</span>
          </div>
        `).join('')}}</div>`;
      }}

      function renderHistory(root, history) {{
        if (!root) return;
        const rows = (history || []).filter(Boolean);
        if (!rows.length) {{
          root.innerHTML = '<div class="focus-box"><small>这个方向没有可展示的年度历史。</small></div>';
          return;
        }}
        const maxProjects = Math.max(...rows.map((item) => Number(item.projects || 0)), 1);
        root.innerHTML = `<div class="history-bars">${{rows.map((item) => `
          <div class="history-row">
            <span>${{escapeHtml(item.year)}}</span>
            <div class="history-track"><div class="history-fill" style="width:${{Math.max(4, Number(item.projects || 0) / maxProjects * 100).toFixed(1)}}%"></div></div>
            <span>${{plainNumber(item.projects || 0, 0)}}</span>
          </div>
        `).join('')}}</div>`;
      }}

      function renderProjectCards(root, profile) {{
        if (!root) return;
        const projects = (profile.sampleProjects || []).filter(Boolean).slice(0, 6);
        const keywords = (profile.keywords || []).filter(Boolean).slice(0, 10);
        if (!projects.length && !keywords.length) {{
          root.innerHTML = '<div class="focus-box"><small>这个方向没有可展示的项目样本。</small></div>';
          return;
        }}
        const keywordHtml = keywords.length ? `<div class="keyword-cloud">${{keywords.map((item) => `<span class="keyword-chip">${{escapeHtml(item.label || '')}}</span>`).join('')}}</div>` : '';
        const projectHtml = projects.map((item) => `
          <div class="project-card">
            <strong>${{escapeHtml(item.projectName || '未命名项目')}}</strong>
            <small>${{escapeHtml([item.institution, item.program, item.guide].filter(Boolean).join('｜'))}}</small>
            <small>${{item.funded ? '已立项' : '未立项'}}${{Number(item.funding || 0) > 0 ? `｜经费 ${{plainNumber(item.funding, 1)}} 万元` : ''}}</small>
          </div>
        `).join('');
        root.innerHTML = `${{keywordHtml}}<div class="detail-list">${{projectHtml}}</div>`;
      }}

      function renderYearTabs() {{
        if (!yearTabs) return;
        const years = runOrder.length ? runOrder : (activeYear ? [activeYear] : []);
        yearTabs.innerHTML = years.map((year) => {{
          const run = yearRuns[year] || {{}};
          const active = String(year) === String(activeYear);
          return `<button class="year-tab${{active ? ' active' : ''}}" type="button" data-year="${{escapeHtml(year)}}">${{escapeHtml(run.label || year)}}</button>`;
        }}).join('');
        Array.from(yearTabs.querySelectorAll('[data-year]')).forEach((button) => {{
          button.addEventListener('click', () => {{
            const nextYear = button.getAttribute('data-year') || '';
            if (!nextYear || nextYear === activeYear) return;
            selectedTopicId = '';
            setCurrentRun(nextYear);
            renderYearTabs();
            renderScene();
          }});
        }});
      }}

      function updateFocus() {{
        const topic = topicById.get(selectedTopicId) || topicById.get(defaultTopicId());
        if (!topic) return;
        const entry = topicEntry(topic);
        const item = entry.item || {{}};
        const profile = topic.detailProfile || {{}};
        const backtest = topic.backtest || null;
        stageFocusTitle.textContent = String(topic.shortLabel || topic.label || '未标注主题');
        stageFocusCopy.textContent = String(topic.label || item.displayContext || '暂无补充说明。');
        const focusCards = backtest ? [
          {{ label: '申报项目数', value: `${{plainNumber((backtest.predicted || {{}}).application, 0)}} 项` }},
          {{ label: '与真实值偏差', value: `${{signedNumber((backtest.error || {{}}).application, 0)}} 项` }},
          {{ label: '立项项目数', value: `${{plainNumber((backtest.predicted || {{}}).funded, 0)}} 项` }},
          {{ label: '经费偏差', value: `${{signedNumber((backtest.error || {{}}).funding, 1)}} 万元` }},
        ] : [
          {{ label: '本次变化', value: item.deltaSentence || compactValue(item.metric, entry.delta) }},
          {{ label: '本年项目', value: plainNumber(profile.projectCount ?? topic.baselineApplication ?? 0, 0) }},
          {{ label: '本年立项', value: plainNumber(profile.fundedCount ?? topic.baselineFunded ?? 0, 0) }},
          {{ label: '本年经费', value: `${{plainNumber(profile.fundingAmount ?? topic.baselineFunding ?? 0, 1)}} 万元` }},
        ];
        stageFocusKpis.innerHTML = focusCards.map((card) => `
          <div class="focus-kpi">
            <span>${{escapeHtml(card.label)}}</span>
            <strong>${{escapeHtml(String(card.value))}}</strong>
          </div>
        `).join('');
        renderHistory(topicHistory, profile.history || []);
        renderBucketRows(topicGuides, [...(profile.guides || []), ...(profile.industries || [])].slice(0, 10), '这个方向没有可展示的指南或行业拆分。');
        renderBucketRows(topicInstitutions, profile.institutions || [], '这个方向没有可展示的承担单位。');
        renderProjectCards(topicProjects, profile);
        if (graphStatus) {{
          graphStatus.textContent = `当前焦点：${{String(topic.shortLabel || topic.label || '未标注主题')}}`;
        }}
      }}

      function drawGraph() {{
        edgeLayer.innerHTML = '';
        flowLayer.innerHTML = '';
        nodeLayer.innerHTML = '';
        edgeLayer.appendChild(createSvgEl('circle', {{ cx: 360, cy: 260, r: 142, class: 'impact-ring' }}));
        edgeLayer.appendChild(createSvgEl('circle', {{ cx: 360, cy: 260, r: 238, class: 'impact-ring outer' }}));
        const activeSet = new Set([selectedTopicId, ...upstream(selectedTopicId), ...downstream(selectedTopicId)].filter(Boolean));
        visibleEdges().forEach((edge) => {{
          const from = positions.get(edge.sourceId);
          const to = positions.get(edge.targetId);
          if (!from || !to) return;
          const classes = ['edge-line', edge.kind];
          if (selectedTopicId && !activeSet.has(edge.sourceId) && !activeSet.has(edge.targetId)) classes.push('future');
          const bend = edge.kind === 'spill' ? 28 : (edge.kind === 'ghost' ? -16 : -22);
          const path = curvePath(from, to, bend);
          edgeLayer.appendChild(createSvgEl('path', {{ d: path, class: classes.join(' ') }}));
          if (selectedTopicId && (edge.sourceId === selectedTopicId || edge.targetId === selectedTopicId) && edge.kind !== 'ghost') {{
            flowLayer.appendChild(createSvgEl('path', {{ d: path, class: 'edge-flow' }}));
          }}
        }});

        visibleTopics().forEach((topic) => {{
          const pos = positions.get(topic.id);
          if (!pos) return;
          const entry = topicEntry(topic);
          const item = entry.item || {{}};
          const classes = ['graph-node', topic.direct ? 'direct' : 'spill'];
          if (topic.id === selectedTopicId) classes.push('selected');
          if (topic.id === currentRun.focusTopicId) classes.push('center');
          if (selectedTopicId && !activeSet.has(topic.id) && topic.id !== selectedTopicId) classes.push('dim');
          if (Number(entry.delta || 0) < 0) classes.push('negative');

          const group = createSvgEl('g', {{ class: classes.join(' '), tabindex: 0 }});
          group.appendChild(createSvgEl('circle', {{ cx: pos.x, cy: pos.y, r: pos.r + 8, class: 'halo' }}));
          group.appendChild(createSvgEl('circle', {{ cx: pos.x, cy: pos.y, r: pos.r, class: 'core' }}));
          const valueNode = createSvgEl('text', {{ x: pos.x, y: pos.y, class: 'graph-node-value' }});
          valueNode.textContent = topic.backtest
            ? plainNumber((topic.backtest.predicted || {{}}).application, 0)
            : compactValue(item.metric, entry.delta);
          group.appendChild(valueNode);
          const labelLines = splitLabel(topic.shortLabel || topic.label, 10);
          labelLines.forEach((line, index) => {{
            const label = createSvgEl('text', {{
              x: pos.x,
              y: pos.y + pos.r + 18 + index * 14,
              class: 'node-label',
            }});
            label.textContent = line;
            group.appendChild(label);
          }});
          if (topic.backtest) {{
            const error = (topic.backtest.error || {{}}).application;
            const sub = createSvgEl('text', {{
              x: pos.x,
              y: pos.y + pos.r + 18 + labelLines.length * 14,
              class: 'node-sub',
            }});
            sub.textContent = `偏差 ${{signedNumber(error, 0)}}`;
            group.appendChild(sub);
          }} else if (item.metricLabel) {{
            const sub = createSvgEl('text', {{
              x: pos.x,
              y: pos.y + pos.r + 18 + labelLines.length * 14,
              class: 'node-sub',
            }});
            sub.textContent = String(item.metricLabel).slice(0, 10);
            group.appendChild(sub);
          }}
          group.addEventListener('click', () => {{
            selectedTopicId = topic.id;
            renderScene();
          }});
          group.addEventListener('keydown', (event) => {{
            if (event.key === 'Enter' || event.key === ' ') {{
              event.preventDefault();
              selectedTopicId = topic.id;
              renderScene();
            }}
          }});
          nodeLayer.appendChild(group);
        }});
      }}

      function syncGraphControls() {{
        if (filterAllButton) filterAllButton.classList.toggle('active', filterMode === 'all');
        if (filterDirectButton) filterDirectButton.classList.toggle('active', filterMode === 'direct');
        if (toggleSpillButton) toggleSpillButton.classList.toggle('active', showSpill);
      }}

      function renderScene() {{
        if (!selectedTopicId || !topicById.has(selectedTopicId) || !visibleTopics().some((topic) => topic.id === selectedTopicId)) {{
          selectedTopicId = defaultTopicId();
        }}
        syncGraphControls();
        renderRunOverview();
        drawGraph();
        updateFocus();
      }}

      if (searchInput) {{
        searchInput.addEventListener('input', () => {{
          const keyword = String(searchInput.value || '').trim().toLowerCase();
          selectionItems.forEach((item) => {{
            const text = String(item.getAttribute('data-selection-text') || '').toLowerCase();
            item.style.display = !keyword || text.includes(keyword) ? '' : 'none';
          }});
        }});
      }}

      if (rangeInput && rangeValue) {{
        const syncRange = () => {{
          rangeValue.textContent = String(rangeInput.value || '0');
        }};
        rangeInput.addEventListener('input', syncRange);
        syncRange();
      }}

      if (methodSelect && runButton) {{
        methodSelect.addEventListener('change', () => {{
          runButton.dataset.method = methodSelect.value;
        }});
      }}

      if (runButton) {{
        runButton.addEventListener('click', () => {{
          selectedTopicId = currentRun.focusTopicId || defaultTopicId();
          filterMode = 'all';
          showSpill = true;
          renderScene();
        }});
      }}
      if (filterAllButton) {{
        filterAllButton.addEventListener('click', () => {{
          filterMode = 'all';
          renderScene();
        }});
      }}
      if (filterDirectButton) {{
        filterDirectButton.addEventListener('click', () => {{
          filterMode = 'direct';
          renderScene();
        }});
      }}
      if (toggleSpillButton) {{
        toggleSpillButton.addEventListener('click', () => {{
          showSpill = !showSpill;
          renderScene();
        }});
      }}
      if (graphResetButton) {{
        graphResetButton.addEventListener('click', () => {{
          selectedTopicId = currentRun.focusTopicId || defaultTopicId();
          filterMode = 'all';
          showSpill = true;
          renderScene();
        }});
      }}

      setCurrentRun(activeYear);
      renderYearTabs();
      if (!topics.length) return;
      renderScene();
    }})();
  </script>
</body>
</html>"""


def _render_topbar(report_title: str) -> str:
    return f"""
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">政</div>
        <div class="brand-copy">
          <h1>政策沙盘推演</h1>
          <p>{_escape(report_title)}</p>
        </div>
      </div>
      <div class="top-actions">
        <a class="ghost-link" href="#instructions">操作指南</a>
        <a class="ghost-link" href="#examples">使用案例</a>
        <button class="action-btn primary" type="button">导出报告</button>
      </div>
    </header>"""


def _render_sidebar(selection_groups: Sequence[Mapping[str, Any]], adjustment_panel: Mapping[str, Any]) -> str:
    return f"""
    <aside class="sidebar">
      <section class="card sidebar-card">
        <div class="step-head"><span class="step-index">1</span><span>选择调整对象</span></div>
        <div class="toggle-row">
          <button class="toggle-btn active" type="button">按研究方向选择</button>
          <button class="toggle-btn" type="button">按方向选择</button>
        </div>
        <div class="field">
          <label for="selection-search">搜索研究方向</label>
          <input class="input" id="selection-search" type="search" placeholder="搜索研究方向">
        </div>
        <div class="selection-panel">{_render_selection_groups(selection_groups)}</div>
      </section>
      <section class="card sidebar-card">
        <div class="step-head"><span class="step-index">2</span><span>设置调整方案</span></div>
        <div class="hint-box">本次怎么调：先选方式，再拖动幅度，最后确定生效时间。</div>
        <div class="field">
          <label for="adjustment-method">调整方式</label>
          <select class="select" id="adjustment-method">{_render_select_options(adjustment_panel.get('method_options'), adjustment_panel.get('method'))}</select>
        </div>
        <div class="field">
          <label for="adjustment-intensity">调整幅度</label>
          <div class="range-shell">
            <div class="range-row">
              <input class="range-input" id="adjustment-intensity" type="range" min="-50" max="100" step="1" value="{_escape(adjustment_panel.get('intensity_display'))}">
              <div class="range-value" id="adjustment-intensity-value">{_escape(adjustment_panel.get('intensity_display'))}</div>
            </div>
            <div class="range-scale"><span>-50%</span><span>0%</span><span>+50%</span><span>+100%</span></div>
          </div>
        </div>
        <div class="field">
          <label for="effective-year">生效时间</label>
          <select class="select" id="effective-year">{_render_select_options(adjustment_panel.get('year_options'), adjustment_panel.get('year'))}</select>
        </div>
        <div class="field">
          <label for="scenario-note">方案备注（选填）</label>
          <textarea class="textarea" id="scenario-note" placeholder="请输入方案备注...">{_escape(adjustment_panel.get('note'))}</textarea>
        </div>
      </section>
      <section class="card sidebar-card">
        <div class="step-head"><span class="step-index">3</span><span>运行推演</span></div>
        <button class="run-btn" id="run-simulation" type="button">运行推演</button>
        <div class="eta">预计耗时：约 30 秒</div>
        <div class="hint-box">提示：结果基于已有数据和模型测算，适合快速比较不同调法的方向性影响。</div>
      </section>
    </aside>"""


def _render_overview_section(cards: Sequence[Mapping[str, Any]], leadership_page: Mapping[str, Any]) -> str:
    window_copy = _build_window_copy(leadership_page)
    return f"""
    <section class="card section-card">
      <div class="section-head">
        <div>
          <h2>整体变化</h2>
          <p>{_escape(window_copy)}，先看总量变化，再看申报、立项和经费结果。</p>
        </div>
        <div class="trend-hint">
          <span class="arrow-up">↑ 上升</span>
          <span class="arrow-down">↓ 下降</span>
        </div>
      </div>
      <div class="year-tabs" id="year-run-tabs" aria-label="切换推演年份"></div>
      <div class="baseline-grid" id="baseline-context-root"></div>
      <div class="metric-grid" id="metric-grid">{_render_metric_cards(cards)}</div>
      <div class="charts-grid">
        <article class="chart-card">
          <h3 id="application-chart-title">申报项目数变化 TOP10（个）</h3>
          <div class="legend"><span><i class="swatch base"></i>基准方案</span><span><i class="swatch scenario"></i>调整后方案</span></div>
          <div id="application-chart">{_render_bar_chart(leadership_page.get('application_top10'), value_type='application')}</div>
        </article>
        <article class="chart-card">
          <h3 id="funded-chart-title">立项项目数变化 TOP10（个）</h3>
          <div class="legend"><span><i class="swatch base"></i>基准方案</span><span><i class="swatch scenario"></i>调整后方案</span></div>
          <div id="funded-chart">{_render_bar_chart(leadership_page.get('funded_top10'), value_type='funded')}</div>
        </article>
        <article class="chart-card wide">
          <h3 id="funding-chart-title">经费变化 TOP10（万元）</h3>
          <div class="legend"><span><i class="swatch direct"></i>直接影响</span><span><i class="swatch spill"></i>带动影响</span></div>
          <div id="funding-chart">{_render_bubble_chart(_as_dict(leadership_page.get('funding_distribution')).get('items'))}</div>
        </article>
      </div>
    </section>"""


def _render_bottom_section(leadership_page: Mapping[str, Any], stages: Sequence[Mapping[str, Any]]) -> str:
    return f"""
    <section class="card section-card">
      <div class="graph-grid">
        <article class="graph-card">
          <div class="graph-toolbar graph-workbench-head">
            <div class="graph-heading">
              <h2>影响传导路径</h2>
              <p>单场景关系图</p>
            </div>
            <div class="graph-controls">
              <button class="view-chip active" id="graph-filter-all" type="button">全部连接</button>
              <button class="view-chip" id="graph-filter-direct" type="button">只看直接影响</button>
              <button class="view-chip active" id="graph-toggle-spill" type="button">外溢影响</button>
              <button class="mini-btn" id="graph-reset" type="button">重置视图</button>
            </div>
          </div>
          <div class="graph-legend-bar">
            <div class="legend">
              <span><i class="swatch direct"></i>直接影响</span>
              <span><i class="swatch spill"></i>带动影响</span>
              <span><i class="swatch ghost"></i>背景联系</span>
            </div>
            <div class="graph-status" id="graph-status">当前焦点：载入中</div>
          </div>
          <div class="propagation-shell">
            {_render_propagation_graph()}
          </div>
        </article>
        <article class="table-card">
          <h3>关键影响结果</h3>
          <div class="table-scroll" id="impact-table-root">{_render_impact_table(leadership_page.get('impact_table'))}</div>
        </article>
        <aside class="side-card">
          <h3>主题详情</h3>
          <div class="side-scroll">
            <div class="focus-box focus-hero">
              <h4 id="stage-focus-title">{_escape(_focus_seed_title(stages))}</h4>
              <p id="stage-focus-copy">{_escape(_focus_seed_copy(stages))}</p>
              <div class="focus-kpi-grid" id="stage-focus-kpis">{_render_focus_seed_kpis(stages)}</div>
            </div>
            <h3>年度走势</h3>
            <div id="topic-history" class="note-list"><div class="note-item"><p>选择一个主题后显示 2020 年以来的项目走势。</p></div></div>
            <h3>指南与行业拆分</h3>
            <div id="topic-guides" class="note-list"><div class="note-item"><p>选择一个主题后显示它落在哪些指南和行业。</p></div></div>
            <h3>主要承担单位</h3>
            <div id="topic-institutions" class="note-list"><div class="note-item"><p>选择一个主题后显示主要承担单位。</p></div></div>
            <h3>项目样本</h3>
            <div id="topic-projects" class="note-list"><div class="note-item"><p>选择一个主题后显示真实项目样本。</p></div></div>
            <h3 id="instructions">结果边界</h3>
            <div class="note-list">{_render_note_items(leadership_page.get('confidence'), note_type='confidence')}</div>
          </div>
        </aside>
      </div>
    </section>"""


def _render_summary_section(leadership_page: Mapping[str, Any]) -> str:
    bullets = _build_summary_bullets(leadership_page)
    return f"""
    <section class="card summary-card">
      <h3>关键结果与边界</h3>
      <div class="legend" style="margin-bottom:12px;"><span><i class="swatch scenario"></i>方案解读</span></div>
      <div class="summary-list">{''.join(f'<div class="summary-item"><p>{_escape(item)}</p></div>' for item in bullets)}</div>
    </section>"""


def _render_selection_groups(groups: Sequence[Mapping[str, Any]]) -> str:
    if not groups:
        return '<div class="selection-item"><input type="checkbox" checked><div><span>当前没有可展示对象</span></div></div>'
    output = []
    for group in groups:
        items = [_as_dict(item) for item in group.get("items", []) if _as_dict(item)]
        output.append(f'<div class="selection-group"><strong>{_escape(group.get("label") or "未分组")}</strong>')
        for item in items:
            output.append(
                f"""<label class="selection-item" data-selection-text="{_escape(item.get('search_text') or '')}">
                  <input type="checkbox" {'checked' if item.get('selected') else ''}>
                  <div>
                    <span>{_escape(item.get('label') or '未标注对象')}</span>
                    <small>{_escape(item.get('meta') or '')}</small>
                  </div>
                </label>"""
            )
        output.append("</div>")
    return "".join(output)


def _render_select_options(options: Sequence[Mapping[str, Any]] | None, selected_value: Any) -> str:
    rows = [_as_dict(item) for item in options or [] if _as_dict(item)]
    if not rows:
        rows = [{"value": selected_value or "", "label": selected_value or "未设置"}]
    return "".join(
        f'<option value="{_escape(item.get("value") or "")}" {"selected" if str(item.get("value") or "") == str(selected_value or "") else ""}>{_escape(item.get("label") or item.get("value") or "未设置")}</option>'
        for item in rows
    )


def _render_metric_cards(cards: Sequence[Mapping[str, Any]]) -> str:
    if not cards:
        return '<article class="metric-card"><span>暂无指标</span><strong>-</strong><div class="metric-delta up">-</div></article>'
    return "".join(
        f"""<article class="metric-card">
          <span>{_escape(item.get('label') or '指标')}</span>
          <strong>{_escape(item.get('display_value') or '-')}</strong>
          <div class="metric-delta {'down' if item.get('delta_negative') else 'up'}">{_escape(item.get('delta_text') or '-')}</div>
        </article>"""
        for item in cards
    )


def _render_bar_chart(items: Any, *, value_type: str) -> str:
    rows = [_as_dict(item) for item in items or [] if _as_dict(item)][:10]
    if not rows:
        return '<svg class="chart-frame" viewBox="0 0 360 220"><text x="20" y="28" fill="#98a2b3" font-size="12">当前没有可展示的数据。</text></svg>'

    if value_type == "application":
        baseline_key = "baseline_application_count"
    elif value_type == "funded":
        baseline_key = "baseline_funded_count"
    else:
        baseline_key = "baseline_funding_amount"

    values = []
    for row in rows:
        baseline = max(_as_number(row.get(baseline_key)), 0.0)
        scenario = max(baseline + _as_number(row.get("delta")), 0.0)
        values.extend([baseline, scenario])
    max_value = max(values) or 1.0

    chart_width = 360
    chart_height = 220
    left = 42
    bottom = 178
    usable_height = 128
    group_gap = 8
    group_width = (chart_width - left - 16) / len(rows)
    bar_width = max(8.0, (group_width - group_gap) / 2)
    labels = []
    bars = []
    grid = []
    for step in range(5):
        y = bottom - usable_height * step / 4
        value = max_value * step / 4
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{chart_width - 10}" y2="{y:.1f}" stroke="#edf2f8" stroke-width="1"/>')
        labels.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" fill="#98a2b3" font-size="11">{_short_axis_number(value)}</text>')

    for index, row in enumerate(rows):
        baseline = max(_as_number(row.get(baseline_key)), 0.0)
        scenario = max(baseline + _as_number(row.get("delta")), 0.0)
        group_x = left + index * group_width + 4
        baseline_h = usable_height * baseline / max_value
        scenario_h = usable_height * scenario / max_value
        bars.append(
            f'<rect x="{group_x:.1f}" y="{bottom - baseline_h:.1f}" width="{bar_width:.1f}" height="{baseline_h:.1f}" rx="4" fill="#d9e2f1"/>'
        )
        bars.append(
            f'<rect x="{group_x + bar_width + 4:.1f}" y="{bottom - scenario_h:.1f}" width="{bar_width:.1f}" height="{scenario_h:.1f}" rx="4" fill="#3f7cff"/>'
        )
        label = _chart_axis_label(str(row.get("label") or ""), 12)
        labels.append(
            f'<text x="{group_x + bar_width:.1f}" y="{bottom + 16:.1f}" text-anchor="end" transform="rotate(-38 {group_x + bar_width:.1f} {bottom + 16:.1f})" fill="#7a8699" font-size="11">{_escape(label)}</text>'
        )

    return f"""<svg class="chart-frame" viewBox="0 0 {chart_width} {chart_height}" role="img" aria-label="对比柱状图">
      {''.join(grid)}
      {''.join(bars)}
      {''.join(labels)}
    </svg>"""


def _render_bubble_chart(items: Any) -> str:
    rows = [_as_dict(item) for item in items or [] if _as_dict(item)][:8]
    if not rows:
        return '<svg class="chart-frame" viewBox="0 0 360 220"><text x="20" y="28" fill="#98a2b3" font-size="12">当前没有可展示的数据。</text></svg>'

    max_x = max(_as_number(item.get("baseline_funding_amount")) for item in rows) or 1.0
    max_y = max(_as_number(item.get("baseline_funding_amount")) + _as_number(item.get("delta")) for item in rows) or 1.0
    max_r = max(abs(_as_number(item.get("delta"))) for item in rows) or 1.0
    palette = ["#7aa5ff", "#69d2a6", "#ffb454", "#b18cff", "#ff8d7a", "#91d5ff", "#9be29b", "#ffd166"]
    points = []
    legends = []
    for index, item in enumerate(rows):
        x = 48 + 224 * (_as_number(item.get("baseline_funding_amount")) / max_x)
        y = 180 - 136 * ((_as_number(item.get("baseline_funding_amount")) + _as_number(item.get("delta"))) / max_y)
        r = 8 + 18 * (abs(_as_number(item.get("delta"))) / max_r)
        color = palette[index % len(palette)]
        points.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}" fill-opacity="0.68" stroke="{color}" stroke-opacity="0.9"/>'
        )
        legends.append(
            f'<text x="286" y="{28 + index * 18}" fill="#667085" font-size="11">{_escape(_chart_axis_label(str(item.get("label") or ""), 18))}</text>'
            f'<circle cx="274" cy="{24 + index * 18}" r="5" fill="{color}" fill-opacity="0.85"/>'
        )
    grid = []
    for step in range(5):
        x = 48 + 224 * step / 4
        y = 180 - 136 * step / 4
        grid.append(f'<line x1="{x:.1f}" y1="28" x2="{x:.1f}" y2="180" stroke="#edf2f8"/>')
        grid.append(f'<line x1="48" y1="{y:.1f}" x2="272" y2="{y:.1f}" stroke="#edf2f8"/>')
    return f"""<svg class="chart-frame" viewBox="0 0 360 220" role="img" aria-label="经费分布气泡图">
      <text x="20" y="20" fill="#98a2b3" font-size="11">调整后方案经费</text>
      <text x="190" y="208" fill="#98a2b3" font-size="11">基准方案经费</text>
      {''.join(grid)}
      {''.join(points)}
      {''.join(legends)}
    </svg>"""


def _render_propagation_graph() -> str:
    return """<svg class="propagation-svg" id="propagation-graph" viewBox="0 0 720 520" role="img" aria-label="影响传导路径图">
      <g id="graph-edge-layer"></g>
      <g id="graph-flow-layer"></g>
      <g id="graph-node-layer"></g>
    </svg>"""


def _focus_seed_title(stages: Sequence[Mapping[str, Any]]) -> str:
    first_stage = _as_dict(stages[0]) if stages else {}
    first_topic = _as_dict((first_stage.get("top_topics") or [None])[0])
    return str(first_topic.get("display_label") or first_topic.get("topic_label") or first_topic.get("topic_id") or "当前焦点")


def _focus_seed_copy(stages: Sequence[Mapping[str, Any]]) -> str:
    first_stage = _as_dict(stages[0]) if stages else {}
    first_topic = _as_dict((first_stage.get("top_topics") or [None])[0])
    return _clean_public_text(first_topic.get("stage_story") or first_topic.get("display_context") or "暂无补充说明。")


def _render_focus_seed_kpis(stages: Sequence[Mapping[str, Any]]) -> str:
    first_stage = _as_dict(stages[0]) if stages else {}
    first_topic = _as_dict((first_stage.get("top_topics") or [None])[0])
    rows = [
        ("本次变化", _scene_delta_sentence(first_topic.get("delta_sentence")) or "-"),
        ("当前申报", _format_plain_number(first_topic.get("baseline_application_count"), "int")),
        ("当前立项", _format_plain_number(first_topic.get("baseline_funded_count"), "int")),
        ("当前经费", _format_plain_number(first_topic.get("baseline_funding_amount"), "currency")),
    ]
    return "".join(
        f'<div class="focus-kpi"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
        for label, value in rows
    )


def _render_impact_table(items: Any) -> str:
    rows = [_as_dict(item) for item in items or [] if _as_dict(item)][:5]
    if not rows:
        return '<div class="note-item"><p>当前没有关键影响结果。</p></div>'
    body = []
    for item in rows:
        impact_type = str(item.get("impact_type") or "")
        impact_class = "spill" if "外溢" in impact_type or "间接" in impact_type else "direct"
        body.append(
            f"""<tr>
              <td><span class="pill {impact_class}">{_escape(impact_type or '影响')}</span></td>
              <td>{_escape(item.get('object_label') or '-')}</td>
              <td>{_escape(item.get('metric_label') or '-')}</td>
              <td>{_escape(_format_plain_number(item.get('delta'), _metric_label_to_format(item.get('metric_label'))))}</td>
              <td>{_escape(_confidence_stars(item.get('support_level')))}</td>
            </tr>"""
        )
    return f"""<table class="impact-table">
      <thead>
        <tr>
          <th>影响类型</th>
          <th>影响对象</th>
          <th>影响方向</th>
          <th>变化幅度</th>
          <th>置信度</th>
        </tr>
      </thead>
      <tbody>{''.join(body)}</tbody>
    </table>"""


def _render_note_items(items: Any, *, note_type: str) -> str:
    if note_type == "confidence":
        rows = []
        for item in items or []:
            row = _as_dict(item)
            if not row:
                continue
            message = _clean_public_text(row.get("message"))
            if not message:
                continue
            row = {**row, "message": message}
            rows.append(row)
        if not rows:
            return '<div class="note-item"><p>暂无补充说明。</p></div>'
        return "".join(
            f"""<div class="note-item">
              <div class="pill {'warn' if item.get('severity') == 'warning' else 'info'}">{_escape(item.get('label') or item.get('severity') or '说明')}</div>
              <p>{_escape(item.get('message') or '')}</p>
            </div>"""
            for item in rows[:4]
        )
    rows = [_clean_public_text(item) for item in items or []]
    rows = [item for item in rows if item]
    if not rows:
        return '<div class="note-item"><p>暂无补充说明。</p></div>'
    return "".join(f'<div class="note-item"><p>{_escape(item)}</p></div>' for item in rows[:4])


def _build_summary_bullets(leadership_page: Mapping[str, Any]) -> list[str]:
    output: list[str] = []
    control_panel = _as_dict(leadership_page.get("control_panel"))
    window_copy = _build_window_copy(leadership_page)
    if window_copy:
        output.append(window_copy)
    summary = str(control_panel.get("summary") or "").strip()
    if summary:
        output.append(summary)
    app = _as_dict((leadership_page.get("application_top10") or [None])[0])
    funded = _as_dict((leadership_page.get("funded_top10") or [None])[0])
    funding = _as_dict((_as_dict(leadership_page.get("funding_distribution")).get("items") or [None])[0])
    if app:
        output.append(f"申报端变化最大的是 {app.get('label') or '未标注对象'}，变化 {_format_plain_number(app.get('delta'), 'int')}。")
    if funded:
        output.append(f"立项端变化最大的是 {funded.get('label') or '未标注对象'}，变化 {_format_plain_number(funded.get('delta'), 'int')}。")
    if funding:
        output.append(f"经费端变化最大的是 {funding.get('label') or '未标注对象'}，变化 {_format_plain_number(funding.get('delta'), 'currency')}。")
    narrative = [str(item).strip() for item in leadership_page.get("narrative", []) or [] if str(item).strip()]
    output.extend(narrative[:1])
    return output[:4] or ["当前还没有形成可展示的解读。"]


def _build_window_copy(leadership_page: Mapping[str, Any]) -> str:
    scenario_window = str(_as_dict(leadership_page.get("control_panel")).get("scenario_window") or "").strip()
    if scenario_window:
        return f"本页只看 {scenario_window} 这一个推演窗口"
    return "本页只看当前这一轮推演窗口"


def _build_report_title(leadership_page: Mapping[str, Any], fallback_title: str) -> str:
    control_panel = _as_dict(leadership_page.get("control_panel"))
    summary = str(control_panel.get("summary") or "").strip()
    return summary or fallback_title


def _build_frontend_payload(
    visual_scene: Mapping[str, Any],
    stages: Sequence[Mapping[str, Any]],
    basis_docs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    scene = _scene_from_visual_scene(visual_scene) if visual_scene else _build_scene_payload(stages)
    sanitized_docs = [
        {
            "document_id": item.get("document_id"),
            "document_type": item.get("document_type"),
            "title": item.get("title"),
            "publish_date": item.get("publish_date"),
        }
        for item in basis_docs
    ]
    return {
        "topicIndex": {
            "topic_nodes": [
                {
                    "node_id": item.get("id"),
                    "label": item.get("shortLabel") or item.get("label"),
                }
                for item in scene.get("topics", [])
            ],
        },
        "scene": scene,
        "basisDocs": sanitized_docs,
    }


def _scene_from_visual_scene(visual_scene: Mapping[str, Any]) -> dict[str, Any]:
    topics = [_scene_topic_from_visual(_as_dict(item)) for item in visual_scene.get("topics", []) or [] if _as_dict(item)]
    year_runs = {}
    for year, raw_run in _as_dict(visual_scene.get("yearRuns")).items():
        run = _as_dict(raw_run)
        year_runs[str(year)] = {
            "year": run.get("year") or year,
            "role": run.get("role"),
            "label": run.get("label") or year,
            "focusTopicId": run.get("focusTopicId"),
            "trainWindow": run.get("trainWindow"),
            "validationYear": run.get("validationYear"),
            "backtestSummary": _as_dict(run.get("backtestSummary")),
            "baselineContext": _as_dict(run.get("baselineContext")),
            "topics": [_scene_topic_from_visual(_as_dict(item)) for item in run.get("topics", []) or [] if _as_dict(item)],
            "edges": [_as_dict(item) for item in run.get("edges", []) or [] if _as_dict(item)],
            "validation": _as_dict(run.get("validation")),
        }
    return {
        "focusTopicId": visual_scene.get("focusTopicId"),
        "activeYear": visual_scene.get("activeYear"),
        "yearRuns": year_runs,
        "runOrder": [
            str(item)
            for item in visual_scene.get("runOrder", []) or list(year_runs.keys())
            if str(item) in year_runs
        ],
        "topics": topics,
        "edges": [_as_dict(item) for item in visual_scene.get("edges", []) or [] if _as_dict(item)],
        "scenario": _as_dict(visual_scene.get("scenario")),
        "baselineContext": _as_dict(visual_scene.get("baselineContext")),
    }


def _scene_topic_from_visual(topic: Mapping[str, Any]) -> dict[str, Any]:
    primary_metric = _as_dict(topic.get("primaryMetric"))
    metric_key = _visual_metric_to_legacy_metric(primary_metric.get("key"))
    delta = _as_number(primary_metric.get("value"))
    return {
        "id": topic.get("id"),
        "label": topic.get("label"),
        "shortLabel": _graph_topic_label_from_visual(topic),
        "scope": topic.get("scope"),
        "guideCode": topic.get("guideCode"),
        "guideLabel": topic.get("guideLabel"),
        "years": topic.get("years") or [],
        "children": [_scene_child_from_visual(_as_dict(item)) for item in topic.get("children", []) or [] if _as_dict(item)],
        "detailProfile": _as_dict(topic.get("detailProfile")),
        "backtest": _as_dict(topic.get("backtest")),
        "metrics": topic.get("metrics") or {},
        "maxAbs": topic.get("maxAbs"),
        "directHits": topic.get("directCount"),
        "spillHits": topic.get("spillCount"),
        "baselineApplication": _as_dict(topic.get("baseline")).get("application"),
        "baselineFunded": _as_dict(topic.get("baseline")).get("funded"),
        "baselineFunding": _as_dict(topic.get("baseline")).get("funding"),
        "primaryEntry": {
            "delta": delta,
            "item": {
                "displayLabel": topic.get("label"),
                "topicLabel": topic.get("guideLabel") or topic.get("label"),
                "metricLabel": primary_metric.get("label"),
                "metric": metric_key,
                "impactOrigin": "direct" if topic.get("direct") else "spillover",
                "deltaSentence": _visual_delta_sentence(primary_metric),
                "displayContext": _visual_topic_context(topic),
            },
        },
        "direct": bool(topic.get("direct")),
    }


def _scene_child_from_visual(child: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "displayLabel": child.get("displayLabel"),
        "year": child.get("year"),
        "scope": child.get("scope"),
        "guideLabel": child.get("guideLabel"),
        "guideCode": child.get("guideCode"),
        "baselineApplication": child.get("baselineApplication"),
        "baselineFunded": child.get("baselineFunded"),
        "baselineFunding": child.get("baselineFunding"),
        "metrics": [
            {
                "metricLabel": _as_dict(metric).get("metricLabel"),
                "delta": _as_dict(metric).get("delta"),
                "deltaSentence": _as_dict(metric).get("deltaSentence"),
                "impactOriginLabel": _as_dict(metric).get("impactOriginLabel"),
            }
            for metric in child.get("metrics", []) or []
            if _as_dict(metric)
        ],
    }


def _visual_metric_to_legacy_metric(value: Any) -> str:
    key = str(value or "").strip()
    return {
        "deltaFunding": "delta_funding_amount",
        "deltaFunded": "delta_funded_count",
        "deltaApplication": "delta_application_count",
        "deltaCentrality": "delta_topic_centrality",
    }.get(key, key)


def _visual_delta_sentence(metric: Mapping[str, Any]) -> str:
    label = str(metric.get("label") or "变化").strip()
    value = _as_number(metric.get("value"))
    fmt = str(metric.get("format") or "").strip()
    unit = str(metric.get("unit") or "").strip()
    if fmt == "currency":
        amount = f"{value:+,.1f}"
    elif fmt == "decimal":
        amount = f"{value:+,.3f}"
    else:
        amount = f"{int(round(value)):+d}"
    return f"{label} {amount}{unit}"


def _visual_topic_context(topic: Mapping[str, Any]) -> str:
    parts = []
    scope = str(topic.get("scope") or "").strip()
    guide = str(topic.get("guideLabel") or "").strip()
    years = [str(item) for item in topic.get("years", []) or [] if str(item).strip()]
    if scope:
        parts.append(scope)
    if guide:
        parts.append(guide)
    if years:
        parts.append("推演年份 " + "、".join(years))
    return "｜".join(parts)


def _graph_topic_label_from_visual(topic: Mapping[str, Any]) -> str:
    guide = str(topic.get("guideLabel") or topic.get("label") or "").strip()
    code = str(topic.get("guideCode") or "").strip()
    if code and code not in guide:
        guide = f"{code}-{guide}"
    return _truncate_label(guide or str(topic.get("label") or "未标注主题"), 18)


def _build_scene_payload(stages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    topic_map: dict[str, dict[str, Any]] = {}
    for raw_stage in stages:
        stage = _as_dict(raw_stage)
        for raw_item in stage.get("top_topics", []) or []:
            item = _as_dict(raw_item)
            topic_id = str(item.get("graph_node_id") or (f"topic:{item.get('topic_id')}" if item.get("topic_id") else "")).strip()
            if not topic_id:
                continue
            current = topic_map.get(topic_id)
            if current is None:
                current = {
                    "id": topic_id,
                    "label": str(item.get("display_label") or item.get("topic_label") or item.get("topic_id") or "未标注主题"),
                    "shortLabel": _graph_topic_label(item),
                    "entries": [],
                    "maxAbs": 0.0,
                    "directHits": 0,
                    "spillHits": 0,
                    "baselineApplication": item.get("baseline_application_count"),
                    "baselineFunded": item.get("baseline_funded_count"),
                    "baselineFunding": item.get("baseline_funding_amount"),
                }
                topic_map[topic_id] = current
            delta = abs(_as_number(item.get("delta")))
            current["entries"].append(
                {
                    "delta": _as_number(item.get("delta")),
                    "item": {
                        "graphNodeId": item.get("graph_node_id"),
                        "topicId": item.get("topic_id"),
                        "displayLabel": item.get("display_label"),
                        "topicLabel": item.get("topic_label"),
                        "metricLabel": item.get("metric_label"),
                        "metric": item.get("metric"),
                        "impactOrigin": item.get("impact_origin"),
                        "deltaSentence": _scene_delta_sentence(item.get("delta_sentence")),
                        "stageStory": item.get("stage_story"),
                        "displayContext": item.get("display_context"),
                        "baselineApplicationCount": item.get("baseline_application_count"),
                        "baselineFundedCount": item.get("baseline_funded_count"),
                        "baselineFundingAmount": item.get("baseline_funding_amount"),
                    },
                }
            )
            current["maxAbs"] = max(_as_number(current.get("maxAbs")), delta)
            if str(item.get("impact_origin") or "") == "spillover":
                current["spillHits"] = int(current.get("spillHits") or 0) + 1
            else:
                current["directHits"] = int(current.get("directHits") or 0) + 1

    topics: list[dict[str, Any]] = []
    for topic in topic_map.values():
        entries = list(topic.pop("entries", []))
        entries.sort(
            key=lambda row: (
                str(_as_dict(row.get("item")).get("impactOrigin") or "") == "spillover",
                -abs(_as_number(row.get("delta"))),
            )
        )
        primary = entries[0] if entries else {"item": {}}
        topic["primaryEntry"] = primary
        topic["direct"] = bool(topic.get("directHits"))
        topics.append(topic)

    topics.sort(key=lambda row: (not bool(row.get("direct")), -_as_number(row.get("maxAbs"))))
    direct_topics = [item for item in topics if item.get("direct")]
    spill_topics = [item for item in topics if not item.get("direct")]
    focus_topic_id = str((direct_topics[0] if direct_topics else (topics[0] if topics else {})).get("id") or "")

    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()

    def push_edge(source_id: str, target_id: str, kind: str) -> None:
        if not source_id or not target_id or source_id == target_id:
            return
        edge_id = f"{source_id}|{target_id}|{kind}"
        if edge_id in seen_edges:
            return
        seen_edges.add(edge_id)
        edges.append({"edgeId": edge_id, "sourceId": source_id, "targetId": target_id, "kind": kind})

    for index, topic in enumerate(direct_topics[1:]):
        push_edge(focus_topic_id, str(topic.get("id") or ""), "direct")
        if index > 0:
            previous = direct_topics[index]
            push_edge(str(previous.get("id") or ""), str(topic.get("id") or ""), "ghost")

    anchor_count = max(len(direct_topics), 1)
    for index, topic in enumerate(spill_topics):
        anchor = (direct_topics[index % anchor_count] if direct_topics else (topics[0] if topics else {}))
        push_edge(str(anchor.get("id") or ""), str(topic.get("id") or ""), "spill")

    return {
        "focusTopicId": focus_topic_id,
        "topics": topics,
        "edges": edges,
    }


def _build_selection_groups(leadership_page: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected = [_as_dict(item) for item in _as_dict(leadership_page.get("control_panel")).get("targets", []) if _as_dict(item)]
    candidate_lists = [
        [_as_dict(item) for item in leadership_page.get("application_top10", []) if _as_dict(item)],
        [_as_dict(item) for item in leadership_page.get("funded_top10", []) if _as_dict(item)],
        [_as_dict(item) for item in _as_dict(leadership_page.get("funding_distribution")).get("items", []) if _as_dict(item)],
    ]
    by_label: dict[str, dict[str, Any]] = {}
    selected_labels = {str(item.get("label") or "").strip() for item in selected}
    for bucket in candidate_lists + [selected]:
        for item in bucket:
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            current = by_label.get(label)
            if current is None:
                scope, guide = _split_scope_label(label)
                current = {
                    "label": label,
                    "scope": scope,
                    "selected": label in selected_labels,
                    "meta": guide or "当前进入推演的对象",
                    "search_text": label,
                }
                by_label[label] = current
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in by_label.values():
        groups.setdefault(item["scope"], []).append(item)
    output = []
    for scope, items in list(groups.items())[:5]:
        items.sort(key=lambda row: (not row["selected"], row["label"]))
        output.append({"label": scope or "未分类", "items": items[:6]})
    return output


def _build_adjustment_panel(scenario_contract: Mapping[str, Any], leadership_page: Mapping[str, Any]) -> dict[str, Any]:
    actions = [_as_dict(item) for item in scenario_contract.get("actions", []) if _as_dict(item)]
    intensity = 20
    if actions:
        numeric = _as_number(actions[0].get("intensity"))
        if numeric:
            intensity = int(round(numeric * 100))
    return {
        "method_options": [
            {"value": "increase_support", "label": "增加支持"},
            {"value": "quota_adjustment", "label": "调整配额"},
            {"value": "budget_raise", "label": "增加经费"},
        ],
        "method": "increase_support",
        "intensity_display": intensity,
        "year_options": _build_year_options(
            _as_dict(leadership_page.get("control_panel")).get("scenario_window")
        ),
        "year": _as_dict(leadership_page.get("control_panel")).get("scenario_window") or "",
        "note": _build_adjustment_note(leadership_page),
    }


def _build_year_options(current_value: Any) -> list[dict[str, Any]]:
    text = str(current_value or "").strip()
    if text.isdigit():
        year = int(text)
        return [{"value": str(item), "label": f"{item}年"} for item in range(year - 1, year + 2)]
    return [{"value": text or "", "label": f"{text}年" if text else "当前窗口"}]


def _build_adjustment_note(leadership_page: Mapping[str, Any]) -> str:
    control_panel = _as_dict(leadership_page.get("control_panel"))
    summary = str(control_panel.get("summary") or "").strip()
    return summary if len(summary) <= 80 else summary[:78] + "..."


def _build_overview_cards(*, baseline_portfolio: Mapping[str, Any], summary_cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    delta_index = {str(item.get("key") or ""): _as_dict(item) for item in summary_cards if _as_dict(item)}
    baseline_application = _as_number(baseline_portfolio.get("application_count"))
    baseline_funded = _as_number(baseline_portfolio.get("funded_count"))
    baseline_funding = _as_number(baseline_portfolio.get("funding_amount"))
    baseline_intensity = baseline_funding / baseline_funded if baseline_funded else 0.0

    app_delta = _as_number(_as_dict(delta_index.get("application_count")).get("value"))
    funded_delta = _as_number(_as_dict(delta_index.get("funded_count")).get("value"))
    funding_delta = _as_number(_as_dict(delta_index.get("funding_amount")).get("value"))
    affected_delta = _as_number(_as_dict(delta_index.get("affected_topics")).get("value"))
    scenario_application = baseline_application + app_delta
    scenario_funded = baseline_funded + funded_delta
    scenario_funding = baseline_funding + funding_delta
    scenario_intensity = scenario_funding / scenario_funded if scenario_funded else 0.0

    cards = [
        _metric_card("总申报项目数（个）", scenario_application, app_delta, baseline_application, "int"),
        _metric_card("总立项项目数（个）", scenario_funded, funded_delta, baseline_funded, "int"),
        _metric_card("总经费（万元）", scenario_funding, funding_delta, baseline_funding, "currency"),
        _metric_card("平均资助强度（万元/项）", scenario_intensity, scenario_intensity - baseline_intensity, baseline_intensity, "currency"),
        _metric_card("影响主题数（个）", affected_delta, affected_delta, max(affected_delta - affected_delta, 0.0), "int"),
    ]
    return cards


def _metric_card(label: str, value: float, delta: float, baseline: float, fmt: str) -> dict[str, Any]:
    percent = 0.0
    if baseline:
        percent = delta / baseline * 100
    delta_negative = delta < 0
    if fmt == "currency":
        display_value = _format_plain_number(value / 10000 if "总经费" in label else value, "currency")
        delta_text = f"{'↓' if delta_negative else '↑'} {_format_plain_number(delta / 10000 if '总经费' in label else delta, 'currency')} ({percent:+.1f}%)"
    else:
        display_value = _format_plain_number(value, fmt)
        delta_text = f"{'↓' if delta_negative else '↑'} {_format_plain_number(delta, fmt)} ({percent:+.1f}%)"
    return {
        "label": label,
        "display_value": display_value,
        "delta_text": delta_text,
        "delta_negative": delta_negative,
    }


def _split_scope_label(value: str) -> tuple[str, str]:
    if " / " not in value:
        return "", value
    scope, guide = value.split(" / ", 1)
    return scope.strip(), guide.strip()


def _graph_topic_label(topic: Mapping[str, Any]) -> str:
    display_label = str(topic.get("display_label") or "").strip()
    if display_label:
        segments = [segment.strip() for segment in display_label.split("｜") if segment.strip()]
        if segments:
            tail = segments[-1]
            if len(tail) <= 18:
                return tail
            return _truncate_label(tail, 18)
    fallback = str(topic.get("topic_label") or topic.get("topic_id") or "未标注主题").strip()
    return _truncate_label(fallback, 18)


def _chart_axis_label(value: str, max_length: int) -> str:
    text = value.strip()
    if not text:
        return ""
    if " / " in text:
        _, guide = _split_scope_label(text)
        text = guide or text
    if "｜" in text:
        text = [segment.strip() for segment in text.split("｜") if segment.strip()][-1]
    return _truncate_label(text, max_length)


def _scene_delta_sentence(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("本阶段", "本次")


def _clean_public_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    blocked_fragments = ("旧场景定义", "旧对象结构", "兼容回放", "legacy")
    if any(fragment in text for fragment in blocked_fragments):
        return ""
    return text.replace("本阶段", "本次")


def _format_plain_number(value: Any, fmt: str) -> str:
    numeric = _as_number(value)
    if fmt == "int":
        return f"{numeric:,.0f}"
    if fmt == "currency":
        return f"{numeric:,.1f}"
    if fmt == "decimal":
        return f"{numeric:,.3f}"
    return str(value)


def _metric_label_to_format(metric_label: Any) -> str:
    text = str(metric_label or "").strip()
    if "经费" in text or "强度" in text:
        return "currency"
    if "项目数" in text or "立项" in text or "主题数" in text:
        return "int"
    return "decimal"


def _confidence_stars(support_level: Any) -> str:
    text = str(support_level or "").strip()
    if text == "observed-grounded":
        return "★★★★★"
    if text in {"supported", "partial", "proxy-grounded"}:
        return "★★★★☆"
    if text in {"assumption-heavy", "legacy_compatible"}:
        return "★★★☆☆"
    return "★★☆☆☆"


def _short_axis_number(value: float) -> str:
    if value >= 10000:
        return f"{value / 10000:.1f}w"
    return f"{value:,.0f}"


def _truncate_label(value: str, max_length: int) -> str:
    text = value.strip()
    return text if len(text) <= max_length else text[: max_length - 1] + "…"


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _to_plain_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_data(item) for item in value]
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
