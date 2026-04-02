"""
评审 HTML 报告生成器

负责将 EvaluationResult 渲染为正式报告与调试报告。
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List


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
        output_html.write_text(self.build_html(data, debug_mode=debug_mode), encoding="utf-8")
        return output_html

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
        expert_qna = data.get("expert_qna") or []
        evidence_map = self._build_evidence_map(evidence)
        evaluation_id = str(result.get("evaluation_id") or "")

        score = result.get("overall_score", 0)
        grade = result.get("grade", "-")
        title = result.get("project_name") or result.get("project_id") or "评审报告"
        score_class = self._score_class(score)
        report_title = "项目智能评审报告" if not debug_mode else "项目评审调试报告"
        report_eyebrow = "Expert Evaluation Report" if not debug_mode else "Evaluation Debug Report"
        report_summary_title = "评审结论" if not debug_mode else "综合意见"
        left_tail = ""
        right_tail = ""

        if debug_mode:
            left_tail = f"""
        <section class="panel">
          <h2>解析章节预览</h2>
          <div class="section-preview">
            {self._render_sections(sections)}
          </div>
        </section>
            """
            right_tail = f"""
        <section class="panel">
          <h2>错误与调试信息</h2>
          {self._render_errors(errors, data.get("meta") or {})}
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
      --bg: #f3efe7;
      --panel: #fffdf8;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #e7dccb;
      --brand: #8f3d2e;
      --brand-soft: #f7e4db;
      --shadow: 0 18px 40px rgba(75, 50, 27, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(143, 61, 46, 0.10), transparent 30%),
        linear-gradient(180deg, #f8f4ed 0%, var(--bg) 100%);
    }}
    .page {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 28px;
    }}
    .hero {{
      background: linear-gradient(135deg, #fff8ef 0%, #f6ece0 52%, #efe4d6 100%);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      flex-wrap: wrap;
    }}
    .eyebrow {{
      color: var(--brand);
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 10px;
      font-weight: 700;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 32px;
      line-height: 1.2;
    }}
    .meta {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }}
    .score-chip {{
      min-width: 180px;
      padding: 18px 20px;
      border-radius: 20px;
      background: white;
      border: 1px solid var(--line);
      text-align: center;
    }}
    .score-good {{ border-color: rgba(31, 122, 77, 0.35); }}
    .score-mid {{ border-color: rgba(161, 98, 7, 0.35); }}
    .score-bad {{ border-color: rgba(180, 35, 24, 0.35); }}
    .score-value {{
      font-size: 40px;
      font-weight: 800;
      line-height: 1;
      margin-bottom: 8px;
    }}
    .score-label {{
      color: var(--muted);
      font-size: 13px;
    }}
    .flags {{
      margin-top: 18px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .flag {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 12px;
      border-radius: 999px;
      background: white;
      border: 1px solid var(--line);
      font-size: 13px;
    }}
    .section-nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .nav-link {{
      display: inline-flex;
      align-items: center;
      padding: 8px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 13px;
      text-decoration: none;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.85fr);
      gap: 20px;
      margin-top: 20px;
      align-items: start;
    }}
    .stack {{
      display: grid;
      gap: 20px;
    }}
    .stack.side {{
      position: sticky;
      top: 24px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 22px;
      box-shadow: var(--shadow);
    }}
    .panel-primary {{
      background: linear-gradient(180deg, #fffdf8 0%, #fff9f1 100%);
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 20px;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }}
    .panel-note {{
      color: var(--muted);
      font-size: 13px;
    }}
    .summary {{
      font-size: 15px;
      line-height: 1.8;
      margin: 0;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 18px;
      align-items: start;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .mini-card {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
    }}
    .mini-card .label {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .mini-card .value {{
      font-size: 18px;
      font-weight: 700;
    }}
    .list {{
      margin: 0;
      padding-left: 20px;
      line-height: 1.8;
    }}
    .list li + li {{
      margin-top: 6px;
    }}
    .score-list {{
      display: grid;
      gap: 14px;
    }}
    .score-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
      padding: 18px;
    }}
    .score-card-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .score-card-title {{
      font-size: 17px;
      font-weight: 700;
    }}
    .score-card-meta {{
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    .tag-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .tag {{
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: var(--brand-soft);
      color: var(--brand);
    }}
    .subtle {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }}
    .kv-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .kv-table th,
    .kv-table td {{
      border-top: 1px solid var(--line);
      padding: 12px 10px;
      text-align: left;
      vertical-align: top;
      line-height: 1.7;
    }}
    .kv-table th {{
      width: 110px;
      color: var(--muted);
      font-weight: 600;
    }}
    .section-preview {{
      display: grid;
      gap: 12px;
    }}
    details {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
      padding: 12px 14px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
    }}
    pre {{
      margin: 12px 0 0;
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
    }}
    .report-block {{
      display: grid;
      gap: 12px;
    }}
    .support-list {{
      display: grid;
      gap: 10px;
    }}
    .support-item {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
      padding: 14px 15px;
    }}
    .support-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .qa-list {{
      display: grid;
      gap: 14px;
    }}
    .qa-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
      padding: 16px;
    }}
    .qa-question {{
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .qa-answer {{
      font-size: 14px;
      line-height: 1.8;
      margin-bottom: 12px;
    }}
    .citation-list {{
      display: grid;
      gap: 8px;
    }}
    .citation {{
      padding: 10px 12px;
      border-radius: 14px;
      background: #fff8ef;
      border: 1px solid var(--line);
      font-size: 13px;
      line-height: 1.7;
    }}
    .fold {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
      padding: 0;
      overflow: hidden;
    }}
    .fold > summary {{
      list-style: none;
      padding: 14px 16px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      background: #fcf7ef;
    }}
    .fold > summary::-webkit-details-marker {{
      display: none;
    }}
    .fold-body {{
      padding: 14px 16px 16px;
      display: grid;
      gap: 10px;
    }}
    .chat-shell {{
      display: grid;
      gap: 14px;
    }}
    .chat-toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
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
    .chat-input {{
      max-width: 320px;
    }}
    .chat-thread {{
      display: grid;
      gap: 12px;
      max-height: 760px;
      overflow: auto;
      padding-right: 4px;
    }}
    .chat-msg {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: #fff;
    }}
    .chat-msg-user {{
      background: #f7efe7;
      border-color: #e9d8c8;
    }}
    .chat-msg-assistant {{
      background: #fff;
    }}
    .chat-role {{
      color: var(--brand);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 8px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
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
      border-radius: 14px;
      background: #fff8ef;
      border: 1px solid var(--line);
      font-size: 13px;
      line-height: 1.7;
    }}
    .chat-form {{
      display: grid;
      gap: 10px;
    }}
    .chat-textarea {{
      min-height: 92px;
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
      border-radius: 999px;
      background: #fff;
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
    @media (max-width: 980px) {{
      .layout,
      .summary-grid,
      .grid-3 {{
        grid-template-columns: 1fr;
      }}
      .stack.side {{
        position: static;
      }}
      .page {{
        padding: 16px;
      }}
      .hero {{
        padding: 20px;
      }}
      h1 {{
        font-size: 26px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow">{report_eyebrow}</div>
          <h1>{report_title} | {html.escape(str(title))}</h1>
          <div class="meta">
            <div>项目ID：{html.escape(str(result.get("project_id") or "-"))}</div>
            <div>评审ID：{html.escape(str(result.get("evaluation_id") or "-"))}</div>
            <div>源文件：{html.escape(str(data.get("source_name") or data.get("meta", {}).get("file_name") or "-"))}</div>
            <div>生成时间：{html.escape(str(result.get("created_at") or "-"))}</div>
          </div>
        </div>
        <div class="score-chip {score_class}">
          <div class="score-value">{html.escape(str(score))}</div>
          <div style="font-size: 20px; font-weight: 800; margin-bottom: 6px;">{html.escape(str(grade))}</div>
          <div class="score-label">综合评分 / 等级</div>
        </div>
      </div>
      <div class="flags">
        <span class="flag">综合等级：{html.escape(str(grade))}</span>
        <span class="flag">结构化摘要：{"已生成" if highlights else "未生成"}</span>
        <span class="flag">专家问答：{"已生成" if expert_qna else "未生成"}</span>
        <span class="flag">聊天索引：{"已构建" if result.get("chat_ready") else "未构建"}</span>
        <span class="flag">章节数：{len(sections)} / 证据数：{len(evidence)}</span>
        {f'<span class="flag">降级结果：{"是" if result.get("partial") else "否"}</span>' if debug_mode else ''}
      </div>
      <div class="section-nav">
        <a class="nav-link" href="#report-overview">评审结论</a>
        <a class="nav-link" href="#report-dimensions">维度评分</a>
        <a class="nav-link" href="#report-chat">专家聊天</a>
        <a class="nav-link" href="#report-fit">指南贴合</a>
        <a class="nav-link" href="#report-benchmark">技术摸底</a>
      </div>
    </section>

    <div class="layout">
      <div class="stack">
        <section class="panel panel-primary" id="report-overview">
          <div class="panel-head">
            <h2>{report_summary_title}</h2>
            <div class="panel-note">先看这一屏，能快速判断项目值不值得继续深读。</div>
          </div>
          <div class="summary-grid">
            <div class="report-block">
              <p class="summary">{html.escape(str(result.get("summary") or "暂无"))}</p>
              <div class="support-list">
                <div class="support-item">
                  <div class="support-label">研究目标</div>
                  {self._render_highlight_list(highlights.get("research_goals") or [], "goal", evidence_map, "暂无提取结果")}
                </div>
                <div class="support-item">
                  <div class="support-label">创新点</div>
                  {self._render_highlight_list(highlights.get("innovations") or [], "innovation", evidence_map, "暂无提取结果")}
                </div>
                <div class="support-item">
                  <div class="support-label">技术路线</div>
                  {self._render_highlight_list(highlights.get("technical_route") or [], "route", evidence_map, "暂无提取结果")}
                </div>
              </div>
            </div>
            <div class="grid-3">
              <div class="mini-card">
                <div class="label">建议条数</div>
                <div class="value">{len(recommendations)}</div>
              </div>
              <div class="mini-card">
                <div class="label">问答条数</div>
                <div class="value">{len(expert_qna)}</div>
              </div>
              <div class="mini-card">
                <div class="label">模型版本</div>
                <div class="value" style="font-size: 14px;">{html.escape(str(result.get("model_version") or "-"))}</div>
              </div>
              <div class="mini-card">
                <div class="label">结构化摘要</div>
                <div class="value" style="font-size: 14px;">{"已生成" if highlights else "未生成"}</div>
              </div>
              <div class="mini-card">
                <div class="label">聊天索引</div>
                <div class="value" style="font-size: 14px;">{"已构建" if result.get("chat_ready") else "未构建"}</div>
              </div>
              <div class="mini-card">
                <div class="label">证据总数</div>
                <div class="value">{len(evidence)}</div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel" id="report-dimensions">
          <div class="panel-head">
            <h2>维度评分</h2>
            <div class="panel-note">逐项查看评分、亮点和主要问题。</div>
          </div>
          <div class="score-list">
            {self._render_dimension_scores(dimension_scores)}
          </div>
        </section>

        {left_tail}
      </div>

      <div class="stack side">

        {self._render_chat_panel(
            evaluation_id=evaluation_id,
            chat_ready=bool(result.get("chat_ready")),
            expert_qna=expert_qna,
            debug_mode=debug_mode,
        )}

        <section class="panel">
          <div class="panel-head">
            <h2>专家关注问答</h2>
            <div class="panel-note">保留典型问题，证据默认折叠。</div>
          </div>
          {self._render_expert_qna(expert_qna)}
        </section>

        <section class="panel">
          <h2>修改建议</h2>
          {self._render_list(recommendations, "暂无建议")}
        </section>

        <section class="panel" id="report-fit">
          <h2>指南贴合</h2>
          {self._render_industry_fit(industry_fit)}
        </section>

        <section class="panel" id="report-benchmark">
          <h2>技术摸底</h2>
          {self._render_benchmark(benchmark)}
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>证据链</h2>
            <div class="panel-note">需要核对原文时再展开。</div>
          </div>
          {self._render_evidence(evidence)}
        </section>

        {right_tail}
      </div>
    </div>
  </div>
</body>
</html>"""

    def build_index_html(self, records: List[Dict[str, Any]]) -> str:
        """构建 debug 目录索引页"""
        rows = []
        for record in records:
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(record.get('created_at') or '-'))}</td>"
                f"<td>{html.escape(str(record.get('project_id') or '-'))}</td>"
                f"<td>{html.escape(str(record.get('project_name') or '-'))}</td>"
                f"<td>{html.escape(str(record.get('source_name') or '-'))}</td>"
                f"<td>{html.escape(str(record.get('overall_score') or '-'))}</td>"
                f"<td>{html.escape(str(record.get('grade') or '-'))}</td>"
                f"<td>{'是' if record.get('partial') else '否'}</td>"
                f"<td><a href=\"{html.escape(str(record.get('html_file') or '#'))}\">正式报告</a> / "
                f"<a href=\"{html.escape(str(record.get('debug_html_file') or '#'))}\">调试报告</a> / "
                f"<a href=\"{html.escape(str(record.get('json_file') or '#'))}\">JSON</a></td>"
                "</tr>"
            )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>debug_eval 索引</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
      background: #f7f4ee;
      color: #1f2937;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
      background: #fffdf8;
      border: 1px solid #eadfce;
      border-radius: 20px;
      padding: 24px;
    }}
    h1 {{ margin: 0 0 10px; }}
    .sub {{ color: #6b7280; margin-bottom: 18px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
    }}
    th, td {{
      border-top: 1px solid #eadfce;
      padding: 12px 10px;
      text-align: left;
      font-size: 14px;
      line-height: 1.6;
      vertical-align: top;
    }}
    th {{
      color: #6b7280;
      font-weight: 600;
      white-space: nowrap;
    }}
    a {{ color: #8f3d2e; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>debug_eval</h1>
    <div class="sub">正文评审调试产物索引。最新记录在最上方。</div>
    <table>
      <thead>
        <tr>
          <th>创建时间</th>
          <th>项目ID</th>
          <th>项目名称</th>
          <th>源文件</th>
          <th>总分</th>
          <th>等级</th>
          <th>降级</th>
          <th>文件</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) or '<tr><td colspan="8">暂无调试报告</td></tr>'}
      </tbody>
    </table>
  </div>
</body>
</html>"""

    def _render_dimension_scores(self, dimension_scores: List[Dict[str, Any]]) -> str:
        cards: List[str] = []
        for score in dimension_scores:
            issues = score.get("issues") or []
            highlights = score.get("highlights") or []
            cards.append(
                f"""
                <div class="score-card">
                  <div class="score-card-head">
                    <div class="score-card-title">{html.escape(str(score.get("dimension_name") or score.get("dimension") or "-"))}</div>
                    <div class="score-card-meta">得分 {html.escape(str(score.get("score", "-")))} / 权重 {html.escape(str(score.get("weight", "-")))}</div>
                  </div>
                  <div class="subtle">{html.escape(str(score.get("opinion") or "暂无意见"))}</div>
                  <div class="tag-row">
                    {''.join(f'<span class="tag">亮点：{html.escape(str(item))}</span>' for item in highlights[:3])}
                    {''.join(f'<span class="tag">问题：{html.escape(str(item))}</span>' for item in issues[:3])}
                  </div>
                </div>
                """
            )
        return "".join(cards) or '<div class="empty">暂无维度评分</div>'

    def _render_evidence(self, evidence: List[Dict[str, Any]]) -> str:
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

    def _render_expert_qna(self, expert_qna: List[Dict[str, Any]]) -> str:
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

        suggestions = [str(item.get("question") or "").strip() for item in expert_qna if str(item.get("question") or "").strip()]
        suggestion_html = "".join(
            f'<button type="button" class="chat-suggestion" data-question="{html.escape(question)}">{html.escape(question)}</button>'
            for question in suggestions[:6]
        )

        ready_text = "聊天索引已构建，可直接向申报书提问。回答会返回页码证据。" if chat_ready else "当前评审未构建聊天索引，无法发起实时问答。请重新评审并启用 enable_chat_index。"
        status_text = "等待提问" if chat_ready else "未构建聊天索引"
        submit_disabled = "" if chat_ready and evaluation_id else "disabled"
        textarea_disabled = "" if chat_ready and evaluation_id else "disabled"
        toolbar_note = "默认直连本机 8000 端口；如果服务不在当前地址，可直接改这里。"
        escaped_eval_id = html.escape(evaluation_id)
        suggestions_block = suggestion_html or '<div class="chat-status">暂无可复用的典型问题。</div>'

        return f"""
        <section class="panel">
          <h2>专家即时问答</h2>
          <div
            class="chat-shell"
            id="report-chat"
            data-evaluation-id="{escaped_eval_id}"
            data-chat-ready="{str(chat_ready).lower()}"
          >
            <div class="chat-toolbar">
              <label for="chat-api-base">API 地址</label>
              <input id="chat-api-base" class="chat-input" type="text" value="" placeholder="http://127.0.0.1:8000" />
              <div class="chat-status">{html.escape(toolbar_note)}</div>
            </div>
            <div class="chat-status">{html.escape(ready_text)}</div>
            <div class="chat-suggestions" id="chat-suggestions">
              {suggestions_block}
            </div>
            <div class="chat-thread" id="chat-thread">
              <div class="chat-msg chat-msg-assistant">
                <div class="chat-role">assistant</div>
                <div class="chat-body">你可以直接问：验证数据有吗？这项技术能落地吗？进展到什么程度？我会按当前评审记录返回页码证据。</div>
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
        </section>
        <script>
          (() => {{
            const shell = document.getElementById("report-chat");
            if (!shell) return;

            const evaluationId = shell.dataset.evaluationId || "";
            const chatReady = shell.dataset.chatReady === "true";
            const apiBaseInput = document.getElementById("chat-api-base");
            const thread = document.getElementById("chat-thread");
            const form = document.getElementById("chat-form");
            const questionInput = document.getElementById("chat-question");
            const submitButton = document.getElementById("chat-submit");
            const statusNode = document.getElementById("chat-status");
            const suggestionButtons = Array.from(shell.querySelectorAll(".chat-suggestion"));

            const detectDefaultBase = () => {{
              if (window.location.protocol === "http:" || window.location.protocol === "https:") {{
                return window.location.origin;
              }}
              return "http://127.0.0.1:8000";
            }};

            apiBaseInput.value = detectDefaultBase();

            const escapeHtml = (value) => String(value || "")
              .replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#39;");

            const setBusy = (busy, text) => {{
              if (submitButton) submitButton.disabled = busy || !chatReady || !evaluationId;
              if (questionInput) questionInput.disabled = busy || !chatReady || !evaluationId;
              suggestionButtons.forEach((button) => {{
                button.disabled = busy || !chatReady || !evaluationId;
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

            const normalizeBase = (value) => String(value || "").trim().replace(/\/+$/, "");

            const askQuestion = async (question) => {{
              const text = String(question || "").trim();
              if (!text) {{
                setBusy(false, "请输入问题");
                return;
              }}
              if (!chatReady || !evaluationId) {{
                setBusy(false, "当前评审未构建聊天索引");
                return;
              }}

              appendMessage("user", text);
              questionInput.value = "";
              setBusy(true, "正在生成回答...");

              try {{
                const response = await fetch(`${{normalizeBase(apiBaseInput.value)}}/api/v1/evaluation/chat/ask`, {{
                  method: "POST",
                  headers: {{
                    "Content-Type": "application/json",
                  }},
                  body: JSON.stringify({{
                    evaluation_id: evaluationId,
                    question: text,
                  }}),
                }});

                const payload = await response.json().catch(() => ({{ detail: "服务返回了不可解析响应" }}));
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

            setBusy(false, chatReady ? "等待提问" : "未构建聊天索引");
          }})();
        </script>
        """

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
                    f'<div class="subtle">证据页：第 {html.escape(str(page))} 页</div>'
                    f'<div class="subtle">证据：{html.escape(str(snippet))}</div>'
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
