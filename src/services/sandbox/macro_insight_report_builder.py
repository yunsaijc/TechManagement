"""Step3 宏观治理研判精简报告构造与 HTML 生成器。"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_TOP_FINDINGS = 12

EVIDENCE_FIELD_LABELS: Dict[str, str] = {
    "applicationsA": "窗口A申报量",
    "applicationsB": "窗口B申报量",
    "outputsA": "窗口A产出量",
    "outputsB": "窗口B产出量",
    "growthRate": "申报量增长率",
    "outputGrowth": "产出增长率",
    "conversionA": "窗口A转化率",
    "conversionB": "窗口B转化率",
    "conversionDrop": "转化率下降值",
    "avgConversionB": "窗口B平均转化率",
    "gapFactor": "相对平均转化率比例",
    "recoveryDelta": "转化恢复幅度",
    "people": "参与人员数",
    "backbone": "骨干人数",
    "backboneRatio": "骨干占比",
    "senior": "高级人才数",
    "seniorRatio": "高级人才占比",
    "collabEdges": "协作边数",
    "collabPerCapita": "人均协作边数",
}

EVIDENCE_FIELD_EXPLANATIONS: Dict[str, str] = {
    "applicationsA": "窗口A内按主题归并后的项目申报数量。",
    "applicationsB": "窗口B内按主题归并后的项目申报数量。",
    "outputsA": "窗口A内该主题关联的成果产出数量。",
    "outputsB": "窗口B内该主题关联的成果产出数量。",
    "growthRate": "申报量增长率，按 (B-A)/A 计算；A 为 0 且 B 大于 0 时按新增长记为 1.0。",
    "outputGrowth": "成果产出增长率，按 (B-A)/A 计算；A 为 0 且 B 大于 0 时按新增长记为 1.0。",
    "conversionA": "窗口A转化率，按 outputs/applications 计算。",
    "conversionB": "窗口B转化率，按 outputs/applications 计算。",
    "conversionDrop": "窗口A转化率减去窗口B转化率，越大说明本期转化下降越明显。",
    "avgConversionB": "窗口B中达到最小申报阈值主题的平均转化率。",
    "gapFactor": "当前主题转化率与窗口B平均转化率的比值，越低说明偏离越大。",
    "recoveryDelta": "窗口B转化率相对窗口A的提升幅度。",
    "people": "窗口B内参与该主题项目的去重人员数。",
    "backbone": "标题中包含“副”等中坚骨干特征的人员数。",
    "backboneRatio": "骨干人数占参与人员总数的比例。",
    "senior": "标题中包含“教授”“研究员”“高工”等高级职称特征的人员数。",
    "seniorRatio": "高级人才人数占参与人员总数的比例。",
    "collabEdges": "该主题下已存在协作关系的人际边数量。",
    "collabPerCapita": "协作边数除以参与人员数，用于衡量协作强度。",
}


def _severity_rank(value: str) -> int:
    return 0 if str(value).lower() == "high" else 1


def build_evidence_explanation(evidence: Dict[str, Any]) -> List[Dict[str, str]]:
    explanations: List[Dict[str, str]] = []
    for key, value in evidence.items():
        explanations.append(
            {
                "field": key,
                "label": EVIDENCE_FIELD_LABELS.get(key, key),
                "value": str(value),
                "explanation": EVIDENCE_FIELD_EXPLANATIONS.get(key, "该指标为当前规则命中时使用的原始证据字段。"),
            }
        )
    return explanations


def build_macro_insight_lite_payload(
    result: Dict[str, Any],
    output_path: str,
    max_findings: int = DEFAULT_TOP_FINDINGS,
) -> Dict[str, Any]:
    findings = result.get("findings", []) if isinstance(result.get("findings", []), list) else []
    briefing = result.get("briefing", {}) if isinstance(result.get("briefing", {}), dict) else {}
    summary = result.get("summary", {}) if isinstance(result.get("summary", {}), dict) else {}
    meta = result.get("meta", {}) if isinstance(result.get("meta", {}), dict) else {}
    group_counts = summary.get("groupCounts", {}) if isinstance(summary.get("groupCounts", {}), dict) else {}

    ranked_findings = sorted(
        findings,
        key=lambda item: (
            _severity_rank(str(item.get("severity", ""))),
            str(item.get("topic", "")),
            str(item.get("type", "")),
        ),
    )
    top_findings = []
    for item in ranked_findings[:max_findings]:
        top_findings.append(
            {
                "topic": item.get("topic", "<未知主题>"),
                "severity": item.get("severity", "unknown"),
                "type": item.get("type", "unknown"),
                "suggestion": item.get("suggestion", ""),
                "evidence": item.get("evidence", {}),
                "evidenceExplanation": build_evidence_explanation(
                    item.get("evidence", {}) if isinstance(item.get("evidence", {}), dict) else {}
                ),
            }
        )

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceOutputPath": output_path,
        "summary": {
            "cards": [
                {"label": "主题数(窗口A)", "value": int(summary.get("totalTopicsA", 0) or 0)},
                {"label": "主题数(窗口B)", "value": int(summary.get("totalTopicsB", 0) or 0)},
                {"label": "发现总数", "value": int(summary.get("totalFindings", 0) or 0)},
                {"label": "高风险", "value": int(summary.get("highRisk", 0) or 0)},
                {"label": "中风险", "value": int(summary.get("mediumRisk", 0) or 0)},
            ],
            "groupCounts": group_counts,
            "riskTypes": summary.get("riskTypes", []),
        },
        "overview": {
            "windowA": meta.get("windowA", {}),
            "windowB": meta.get("windowB", {}),
            "topicExpr": meta.get("topicExpr", ""),
            "analysisBoundary": meta.get("analysisBoundary", {}),
            "fastMode": meta.get("fastMode", {}),
        },
        "briefing": briefing,
        "topFindings": top_findings,
    }


class MacroInsightReportBuilder:
    """将 Step3 精简结果渲染为面向展示的 HTML 报告。"""

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
        briefing = payload.get("briefing", {}) or {}
        top_findings = payload.get("topFindings", []) or []
        cards = summary.get("cards", []) or []
        group_counts = summary.get("groupCounts", {}) or {}
        risk_types = summary.get("riskTypes", []) or []
        analysis_boundary = overview.get("analysisBoundary", {}) or {}
        actions = briefing.get("actions", []) or []

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>宏观治理研判简报</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f5f1ea; color: #1c1917; }}
    .page {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    .hero {{ background: linear-gradient(135deg, #fffdf8 0%, #f7efe3 100%); border: 1px solid #eadfce; border-radius: 20px; padding: 24px; box-shadow: 0 10px 28px rgba(56, 38, 17, 0.06); }}
    .title {{ font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }}
    .subtitle {{ margin-top: 8px; font-size: 13px; color: #57534e; }}
    .headline {{ margin-top: 12px; font-size: 18px; line-height: 1.7; color: #7c2d12; font-weight: 700; }}
    .stats {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .stat {{ background: rgba(255,255,255,0.92); border: 1px solid #eadfce; border-radius: 16px; padding: 14px 16px; }}
    .stat-label {{ font-size: 12px; color: #78716c; }}
    .stat-value {{ margin-top: 6px; font-size: 24px; font-weight: 800; color: #9a3412; }}
    .section {{ margin-top: 18px; background: #ffffff; border: 1px solid #e7e5e4; border-radius: 18px; padding: 18px 20px; box-shadow: 0 10px 24px rgba(56, 38, 17, 0.04); }}
    .section-title {{ font-size: 16px; font-weight: 800; margin-bottom: 12px; }}
    .overview-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .overview-item {{ background: #fafaf9; border: 1px solid #e7e5e4; border-radius: 12px; padding: 12px 14px; }}
    .overview-label {{ font-size: 11px; color: #78716c; }}
    .overview-value {{ margin-top: 6px; font-size: 14px; font-weight: 700; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }}
    .pill-wrap {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; background: #ffedd5; color: #9a3412; font-size: 12px; }}
    .insight-list, .action-list {{ display: grid; gap: 10px; }}
    .insight-item, .action-item {{ background: #fafaf9; border: 1px solid #e7e5e4; border-radius: 12px; padding: 12px 14px; line-height: 1.7; }}
    .two-col {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 16px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 12px 10px; border-top: 1px solid #e7e5e4; vertical-align: top; text-align: left; }}
    th {{ font-size: 12px; color: #78716c; }}
    td {{ font-size: 13px; line-height: 1.7; }}
    .severity-high {{ color: #b91c1c; font-weight: 800; }}
    .severity-medium {{ color: #b45309; font-weight: 800; }}
    .empty {{ color: #a8a29e; font-size: 13px; padding: 8px 0; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px; font-size: 12px; }}
    .evidence-box {{ display: grid; gap: 8px; }}
    .evidence-note {{ background: #fff7ed; border: 1px solid #fed7aa; border-radius: 10px; padding: 10px; }}
    .evidence-note-title {{ font-size: 12px; font-weight: 700; color: #9a3412; margin-bottom: 6px; }}
    .evidence-note-list {{ display: grid; gap: 6px; }}
    .evidence-note-item {{ font-size: 12px; line-height: 1.6; color: #7c2d12; }}
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
      <div class="title">宏观治理研判简报</div>
      <div class="subtitle">生成时间 {html.escape(str(payload.get("generatedAt", "")))} | 来源 {html.escape(str(payload.get("sourceOutputPath", "")))}</div>
      <div class="headline">{html.escape(str(briefing.get("headline", "暂无标题结论")))}</div>
      <div class="stats">
        {''.join(self._render_stat_card(card) for card in cards)}
      </div>
    </section>

    <section class="section">
      <div class="section-title">分析说明</div>
      <div class="overview-grid">
        {self._render_overview_item("窗口A", overview.get("windowA"))}
        {self._render_overview_item("窗口B", overview.get("windowB"))}
        {self._render_overview_item("主题口径", overview.get("topicExpr"))}
        {self._render_overview_item("边界定位", analysis_boundary.get("positioning"))}
        {self._render_overview_item("负责内容", analysis_boundary.get("owns"))}
        {self._render_overview_item("排除内容", analysis_boundary.get("excludes"))}
      </div>
    </section>

    <section class="section">
      <div class="section-title">风险分布</div>
      <div class="two-col">
        <div class="insight-list">
          {self._render_group_counts(group_counts)}
        </div>
        <div>
          <div class="section-title" style="margin-bottom: 10px;">风险类型</div>
          <div class="pill-wrap">
            {self._render_risk_types(risk_types)}
          </div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">治理动作</div>
      <div class="action-list">
        {self._render_actions(actions)}
      </div>
    </section>

    <section class="section">
      <div class="section-title">重点发现</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>主题</th>
              <th>级别</th>
              <th>类型</th>
              <th>证据</th>
              <th>建议</th>
            </tr>
          </thead>
          <tbody>
            {self._render_findings(top_findings)}
          </tbody>
        </table>
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

    def _render_group_counts(self, group_counts: Dict[str, Any]) -> str:
        if not group_counts:
            return '<div class="empty">暂无分组统计</div>'
        return "".join(
            '<div class="insight-item">'
            f'<strong>{html.escape(str(key))}</strong>：{html.escape(str(value))}'
            '</div>'
            for key, value in group_counts.items()
        )

    def _render_risk_types(self, risk_types: List[Any]) -> str:
        if not risk_types:
            return '<div class="empty">暂无风险类型</div>'
        return "".join(f'<span class="pill">{html.escape(str(item))}</span>' for item in risk_types)

    def _render_actions(self, actions: List[Any]) -> str:
        if not actions:
            return '<div class="empty">暂无治理动作</div>'
        return "".join(
            f'<div class="action-item">{html.escape(str(item))}</div>'
            for item in actions
        )

    def _render_findings(self, findings: List[Dict[str, Any]]) -> str:
        if not findings:
            return '<tr><td colspan="5" class="empty">暂无重点发现</td></tr>'

        rows = []
        for item in findings:
            severity = str(item.get("severity", "-"))
            severity_class = "severity-high" if severity.lower() == "high" else "severity-medium"
            evidence_json = json.dumps(item.get("evidence", {}), ensure_ascii=False, indent=2)
            evidence_explanation = item.get("evidenceExplanation", []) or []
            rows.append(
                "<tr>"
                f'<td>{html.escape(str(item.get("topic", "-")))}</td>'
                f'<td class="{severity_class}">{html.escape(severity)}</td>'
                f'<td>{html.escape(str(item.get("type", "-")))}</td>'
                f'<td><div class="evidence-box"><pre>{html.escape(evidence_json)}</pre>{self._render_evidence_explanation(evidence_explanation)}</div></td>'
                f'<td>{html.escape(str(item.get("suggestion", "")))}</td>'
                "</tr>"
            )
        return "".join(rows)

    def _render_evidence_explanation(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return '<div class="empty">暂无证据解释</div>'
        return (
            '<div class="evidence-note">'
            '<div class="evidence-note-title">证据解释</div>'
            '<div class="evidence-note-list">'
            + "".join(
                '<div class="evidence-note-item">'
                f'<strong>{html.escape(str(item.get("label", "-")))}</strong>：'
                f'{html.escape(str(item.get("explanation", "")))}'
                '</div>'
                for item in rows
            )
            + '</div></div>'
        )
