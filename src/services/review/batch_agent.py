"""批次级形式审查 Agent"""
import asyncio
import re
import time
from html import escape
from typing import Any, Dict, List

from src.common.review_runtime import ReviewRuntime
from src.common.models import BatchReviewRequest, BatchReviewResult, ProjectReviewResult
from src.services.review.debug_writer import ReviewDebugWriter
from src.services.review.project_agent import ProjectReviewAgent
from src.services.review.project_context_builder import ProjectContextBuilder
from src.services.review.project_index_repo import ProjectIndexRepository


class BatchReviewAgent:
    """批次级形式审查 Agent"""
    DOC_KIND_LABELS = {
        "commitment_letter": "承诺书",
        "recommendation_letter": "合作方科技管理部门推荐函",
        "cooperation_agreement": "合作协议（合同）",
        "ethics_approval": "伦理审查意见",
        "biosafety_commitment": "生物安全承诺书",
        "industry_permit": "行业准入资格/许可材料",
        "business_license": "营业执照（统一社会信用代码证）",
        "financial_statement": "财务报表",
        "acceptance_report": "验收报告",
        "patent_certificate": "专利证书",
        "award_certificate": "获奖证书",
        "retrieval_report": "检索报告",
        "technical_route_diagram": "技术路线图",
        "other_supporting_material": "其他支撑材料",
        "unknown_attachment": "未识别附件",
    }

    def __init__(
        self,
        project_repo: ProjectIndexRepository | None = None,
        context_builder: ProjectContextBuilder | None = None,
        project_review_agent: ProjectReviewAgent | None = None,
    ):
        self.project_repo = project_repo or ProjectIndexRepository()
        self.context_builder = context_builder or ProjectContextBuilder()
        self.project_review_agent = project_review_agent or ProjectReviewAgent()
        self.project_concurrency = max(1, int(ReviewRuntime.BATCH_PROJECT_CONCURRENCY))

    async def process(self, request: BatchReviewRequest) -> BatchReviewResult:
        """执行批次级形式审查"""
        start_time = time.time()
        normalized_zxmc = re.sub(r"[^0-9A-Za-z_-]", "_", request.zxmc.strip()) or "unknown"
        batch_id = f"batch_review_{normalized_zxmc}"
        debug_writer = ReviewDebugWriter(batch_id)
        debug_writer.write_json("request.json", request.model_dump())
        project_rows = self.project_repo.get_projects_by_zxmc(
            request.zxmc,
            limit=request.limit,
            project_ids=request.project_ids,
        )
        debug_writer.write_json(
            "project_index.json",
            [row.model_dump() for row in project_rows],
        )
        semaphore = asyncio.Semaphore(self.project_concurrency)

        async def _process_project(row) -> tuple[ProjectReviewResult, Dict[str, Any]]:
            async with semaphore:
                context = await self.context_builder.build(row)
                debug_writer.write_json(
                    f"projects/{row.project_id}.scan.json",
                    context.scan_info,
                )
                debug_writer.write_json(
                    f"projects/{row.project_id}.context.json",
                    context.model_dump(mode="json"),
                )
                project_result = await self.project_review_agent.process_context(context)
                debug_writer.write_json(
                    f"projects/{row.project_id}.result.json",
                    project_result.model_dump(mode="json"),
                )
                return project_result, context.model_dump(mode="json")

        project_items = list(
            await asyncio.gather(*[_process_project(row) for row in project_rows])
        )
        project_results: List[ProjectReviewResult] = [item[0] for item in project_items]
        project_context_map: Dict[str, Dict[str, Any]] = {
            result.project_id: context_payload for result, context_payload in project_items
        }

        summary = self._generate_summary(project_results)
        suggestions = self._generate_suggestions(project_results)

        debug_writer.write_json(
            "batch_summary.json",
            {
                "zxmc": request.zxmc,
                "project_count": len(project_results),
                "concurrency": {
                    "batch_project_concurrency": self.project_concurrency,
                    "attachment_classify_concurrency": self.context_builder.classification_concurrency,
                },
                "summary": summary,
                "suggestions": suggestions,
            },
        )
        debug_writer.write_text(
            "index.html",
            self._build_batch_debug_html(
                batch_id=batch_id,
                request=request,
                project_results=project_results,
                project_context_map=project_context_map,
                summary=summary,
                suggestions=suggestions,
            ),
        )

        return BatchReviewResult(
            id=batch_id,
            zxmc=request.zxmc,
            project_count=len(project_results),
            project_results=project_results,
            debug_dir=debug_writer.output_dir,
            summary=summary,
            suggestions=suggestions,
            processing_time=time.time() - start_time,
        )

    def _generate_summary(self, project_results: List[ProjectReviewResult]) -> str:
        """生成批次摘要"""
        if not project_results:
            return "批次形式审查完成：未查询到项目"
        failed_projects = sum(
            1
            for result in project_results
            if any(item.status in {"failed", "warning"} for item in result.results) or result.manual_review_items
        )
        return f"批次形式审查完成：共 {len(project_results)} 个项目，需关注 {failed_projects} 个"

    def _generate_suggestions(self, project_results: List[ProjectReviewResult]) -> List[str]:
        """生成批次建议"""
        if any(result.manual_review_items for result in project_results):
            return ["存在附件类型识别不确定的项目，建议优先人工复核材料类型"]
        return []

    def _build_batch_debug_html(
        self,
        batch_id: str,
        request: BatchReviewRequest,
        project_results: List[ProjectReviewResult],
        project_context_map: Dict[str, Dict[str, Any]],
        summary: str,
        suggestions: List[str],
    ) -> str:
        """生成批次调试 HTML 页面"""
        project_sections = "\n".join(
            self._render_project_section(index + 1, result, project_context_map.get(result.project_id, {}))
            for index, result in enumerate(project_results)
        )
        suggestion_items = "".join(
            f"<li>{escape(item)}</li>"
            for item in suggestions
        ) or "<li>无</li>"
        project_count = len(project_results)
        failed_count = sum(
            1
            for result in project_results
            if any(item.status in {"failed", "warning"} for item in result.results) or result.manual_review_items
        )
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(batch_id)} 调试结果</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --card: #ffffff;
      --line: #d8dfeb;
      --text: #1f2937;
      --muted: #667085;
      --passed: #067647;
      --failed: #b42318;
      --warning: #b54708;
      --manual: #6941c6;
      --requires: #175cd3;
      --na: #344054;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #eef4ff 0%, var(--bg) 140px);
      color: var(--text);
    }}
    .page {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero, .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }}
    .hero {{
      padding: 24px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .hero p {{
      margin: 6px 0;
      color: var(--muted);
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fbfcfe;
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
      margin-top: 6px;
    }}
    .links {{
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    a {{
      color: #175cd3;
      text-decoration: none;
    }}
    .project {{
      margin-bottom: 18px;
      overflow: hidden;
    }}
    .project summary {{
      list-style: none;
      cursor: pointer;
      padding: 18px 20px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
    }}
    .project summary::-webkit-details-marker {{ display: none; }}
    .project h2 {{
      margin: 0 0 6px;
      font-size: 20px;
    }}
    .project-meta {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .project-body {{
      border-top: 1px solid var(--line);
      padding: 18px 20px 22px;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .badge {{
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid currentColor;
      background: #fff;
      white-space: nowrap;
    }}
    .status-passed {{ color: var(--passed); }}
    .status-failed {{ color: var(--failed); }}
    .status-warning {{ color: var(--warning); }}
    .status-manual {{ color: var(--manual); }}
    .status-requires_data {{ color: var(--requires); }}
    .status-not_applicable {{ color: var(--na); }}
    .status-skipped {{ color: var(--na); }}
    .section-grid {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 16px;
      margin-top: 16px;
    }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px 16px;
      background: #fcfdff;
    }}
    .panel h3 {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 8px 12px;
      font-size: 14px;
    }}
    .kv div:nth-child(odd) {{
      color: var(--muted);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-top: 10px;
    }}
    th, td {{
      border-top: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
      background: #f8fafc;
    }}
    ul {{
      margin: 8px 0 0;
      padding-left: 18px;
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      word-break: break-all;
    }}
    .empty {{
      color: var(--muted);
      font-size: 14px;
    }}
    @media (max-width: 960px) {{
      .section-grid {{ grid-template-columns: 1fr; }}
      .project summary {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>批次调试视图</h1>
      <p>批次 ID：<span class="mono">{escape(batch_id)}</span></p>
      <p>zxmc：<span class="mono">{escape(request.zxmc)}</span></p>
      <p>摘要：{escape(summary)}</p>
      <div class="metrics">
        <div class="metric"><div>项目数</div><strong>{project_count}</strong></div>
        <div class="metric"><div>需关注项目</div><strong>{failed_count}</strong></div>
        <div class="metric"><div>limit</div><strong>{escape(str(request.limit or "未限制"))}</strong></div>
      </div>
      <div class="links">
        <a href="request.json">request.json</a>
        <a href="project_index.json">project_index.json</a>
        <a href="batch_summary.json">batch_summary.json</a>
      </div>
      <ul>{suggestion_items}</ul>
    </section>
    {project_sections or '<div class="card" style="padding:20px;">无项目结果</div>'}
  </div>
</body>
</html>"""

    def _render_project_section(self, order: int, result: ProjectReviewResult, context_payload: Dict[str, Any]) -> str:
        """渲染单项目调试区块"""
        result_path = f"projects/{result.project_id}.result.json"
        context_path = f"projects/{result.project_id}.context.json"
        scan_path = f"projects/{result.project_id}.scan.json"
        rule_evidence_table = self._render_rule_evidence_table(result, context_payload)
        summary_badges = self._render_status_badges([
            ("失败", str(sum(1 for item in result.results if item.status == "failed")), "failed"),
            ("警告", str(sum(1 for item in result.results if item.status == "warning")), "warning"),
            ("人工", str(len(result.manual_review_items)), "manual"),
        ])
        project_rules_table = self._render_project_results_table(result)
        policy_rules_table = self._render_policy_rule_checks_table(result)
        missing_items = self._render_simple_list(
            [f"{self._doc_kind_with_code(item.doc_kind)}: {item.reason}" for item in result.missing_attachments]
        )
        manual_items = self._render_simple_list(
            [f"{item.item}: {item.message}" for item in result.manual_review_items]
        )
        suggestions = self._render_simple_list(result.suggestions)
        return f"""
<details class="card project" open>
  <summary>
    <div>
      <h2>{order}. {escape(result.project_id)} / {escape(result.project_type)}</h2>
      <div class="project-meta">{escape(result.summary)}</div>
      <div class="links">
        <a href="{escape(context_path)}">context.json</a>
        <a href="{escape(result_path)}">result.json</a>
        <a href="{escape(scan_path)}">scan.json</a>
      </div>
    </div>
    <div class="badges">{summary_badges}</div>
  </summary>
  <div class="project-body">
    <div class="section-grid">
      <section class="panel">
        <h3>项目级规则结果</h3>
        {project_rules_table}
      </section>
      <section class="panel">
        <h3>Docx 逐条对照</h3>
        {policy_rules_table}
      </section>
    </div>
    <div class="section-grid">
      <section class="panel">
        <h3>缺失附件</h3>
        {missing_items}
      </section>
      <section class="panel">
        <h3>人工复核项</h3>
        {manual_items}
      </section>
    </div>
    <div class="section-grid">
      <section class="panel" style="grid-column: 1 / -1;">
        <h3>错误来源定位（规则 -> 文件 -> 片段）</h3>
        {rule_evidence_table}
      </section>
    </div>
    <div class="section-grid">
      <section class="panel">
        <h3>建议</h3>
        {suggestions}
      </section>
      <section class="panel">
        <h3>处理信息</h3>
        <div class="kv">
          <div>project_id</div><div class="mono">{escape(result.project_id)}</div>
          <div>project_type</div><div>{escape(result.project_type)}</div>
          <div>processed_at</div><div>{escape(str(result.processed_at))}</div>
          <div>processing_time</div><div>{escape(f"{result.processing_time:.3f}s")}</div>
        </div>
      </section>
    </div>
  </div>
</details>"""

    def _render_project_results_table(self, result: ProjectReviewResult) -> str:
        """渲染项目级规则结果表"""
        rows = []
        for item in result.results:
            rows.append(
                "<tr>"
                f"<td>{escape(item.item)}</td>"
                f"<td>{self._render_status_badge(item.status)}</td>"
                f"<td>{escape(item.message)}</td>"
                f"<td><pre class='mono'>{escape(str(item.evidence))}</pre></td>"
                "</tr>"
            )
        if not rows:
            return "<div class='empty'>无项目级规则结果</div>"
        return (
            "<table><thead><tr><th>item</th><th>status</th><th>message</th><th>evidence</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    def _render_policy_rule_checks_table(self, result: ProjectReviewResult) -> str:
        """渲染 docx 逐条规则对照表"""
        rows = []
        for item in result.policy_rule_checks:
            rows.append(
                "<tr>"
                f"<td>{escape(item.code)}</td>"
                f"<td>{self._render_status_badge(item.status)}</td>"
                f"<td>{escape(item.requirement)}</td>"
                f"<td>{escape(item.source_rule or '-')}</td>"
                f"<td>{escape(item.reason)}</td>"
                "</tr>"
            )
        if not rows:
            return "<div class='empty'>无 docx 逐条规则结果</div>"
        return (
            "<table><thead><tr><th>code</th><th>status</th><th>requirement</th><th>source_rule</th><th>reason</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    def _render_rule_evidence_table(self, result: ProjectReviewResult, context_payload: Dict[str, Any]) -> str:
        """渲染异常规则的来源定位信息"""
        rows = []
        evidence_items = self._collect_rule_evidence_items(result, context_payload)
        if not evidence_items:
            return "<div class='empty'>无异常规则来源定位信息</div>"
        for item in evidence_items:
            rows.append(
                "<tr>"
                f"<td>{escape(item['rule'])}</td>"
                f"<td>{self._render_status_badge(item['status'])}</td>"
                f"<td class='mono'>{escape(item['source_file'])}</td>"
                f"<td><pre class='mono'>{escape(item['clip'])}</pre></td>"
                "</tr>"
            )
        return (
            "<table><thead><tr><th>rule</th><th>status</th><th>source_file</th><th>evidence_clip</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    def _collect_rule_evidence_items(self, result: ProjectReviewResult, context_payload: Dict[str, Any]) -> List[Dict[str, str]]:
        """收集异常规则定位项"""
        items: List[Dict[str, str]] = []
        scan_info = context_payload.get("scan_info", {}) if isinstance(context_payload, dict) else {}
        proposal_facts = scan_info.get("proposal_facts", {}) if isinstance(scan_info, dict) else {}
        proposal_file = (
            scan_info.get("proposal_main_file")
            or proposal_facts.get("proposal_main_file")
            or "-"
        )
        proposal_excerpt = proposal_facts.get("proposal_text_excerpt", "")
        attachments = context_payload.get("attachments", []) if isinstance(context_payload, dict) else []
        attachment_index = {
            str(att.get("doc_kind", "")): att
            for att in attachments
            if isinstance(att, dict)
        }

        for rule_item in result.results:
            if rule_item.status not in {"failed", "warning"}:
                continue
            if rule_item.item == "registered_date_limit":
                clip = self._extract_keyword_snippet(proposal_excerpt, "注册时间")
                items.append(
                    {
                        "rule": rule_item.item,
                        "status": rule_item.status,
                        "source_file": str(proposal_file),
                        "clip": clip or self._format_evidence_clip(rule_item.evidence, rule_item.message),
                    }
                )
                continue
            if rule_item.item in {"required_attachments", "conditional_attachments"}:
                missing_doc_kinds = self._extract_missing_doc_kinds(rule_item.evidence)
                if not missing_doc_kinds:
                    items.append(
                        {
                            "rule": rule_item.item,
                            "status": rule_item.status,
                            "source_file": "附件目录（未定位具体文件）",
                            "clip": self._format_evidence_clip(rule_item.evidence, rule_item.message),
                        }
                    )
                    continue
                for doc_kind in missing_doc_kinds:
                    matched = attachment_index.get(doc_kind)
                    if matched:
                        clip = self._build_attachment_clip(matched)
                        source_file = str(matched.get("file_ref") or matched.get("file_name") or "附件文件")
                    else:
                        source_file = "附件目录（未找到匹配类别）"
                        clip = self._build_attachment_overview_clip(attachments)
                    items.append(
                        {
                            "rule": f"{rule_item.item}:{self._doc_kind_with_code(doc_kind)}",
                            "status": rule_item.status,
                            "source_file": source_file,
                            "clip": clip,
                        }
                    )
                continue
            if rule_item.item == "external_status_check":
                items.append(
                    {
                        "rule": rule_item.item,
                        "status": rule_item.status,
                        "source_file": "外部校验数据源（当前未接入）",
                        "clip": self._format_evidence_clip(rule_item.evidence, rule_item.message),
                    }
                )
                continue
            items.append(
                {
                    "rule": rule_item.item,
                    "status": rule_item.status,
                    "source_file": str(proposal_file),
                    "clip": self._format_evidence_clip(rule_item.evidence, rule_item.message),
                }
            )
        return items

    def _format_evidence_clip(self, evidence: Any, fallback_message: str = "") -> str:
        """将规则 evidence 转为人可读的短文本"""
        if isinstance(evidence, dict):
            if not evidence:
                return fallback_message or "无附加证据字段"
            if isinstance(evidence.get("pending_review_points"), list):
                lines: List[str] = []
                pending_points = evidence["pending_review_points"]
                for index, point in enumerate(pending_points[:6], start=1):
                    if not isinstance(point, dict):
                        continue
                    code = str(point.get("code", "")).strip() or "-"
                    requirement = str(point.get("requirement", "")).strip() or "-"
                    reason = str(point.get("reason", "")).strip() or "-"
                    lines.append(f"{index}. [{code}] {requirement}")
                    lines.append(f"   原因: {reason}")
                if not lines:
                    return fallback_message or "待补核验点为空"
                return "待补核验点：\n" + "\n".join(lines)
            if isinstance(evidence.get("missing_doc_kinds"), list):
                kinds = [str(item) for item in evidence["missing_doc_kinds"] if item]
                if kinds:
                    return "缺失附件类别：" + "、".join(self._doc_kind_with_code(kind) for kind in kinds)
            if isinstance(evidence.get("missing_conditional_attachments"), list):
                lines = []
                for item in evidence["missing_conditional_attachments"][:6]:
                    if isinstance(item, dict):
                        kind = str(item.get("doc_kind", "-"))
                        lines.append(f"{self._doc_kind_with_code(kind)}: {item.get('reason', '-')}")
                if lines:
                    return "缺失条件性附件：\n" + "\n".join(lines)
            lines = []
            for key, value in evidence.items():
                if isinstance(value, (str, int, float, bool)):
                    lines.append(f"{key}: {value}")
            if lines:
                return "\n".join(lines[:8])
            return fallback_message or "证据字段较复杂，详见 result.json"
        if isinstance(evidence, list):
            if not evidence:
                return fallback_message or "无附加证据列表"
            return "\n".join(str(item) for item in evidence[:6])
        text = str(evidence).strip() if evidence is not None else ""
        return text or fallback_message or "无附加证据"

    def _extract_missing_doc_kinds(self, evidence: Dict[str, Any]) -> List[str]:
        """抽取缺失材料类别"""
        if not isinstance(evidence, dict):
            return []
        values: List[str] = []
        if isinstance(evidence.get("missing_doc_kinds"), list):
            values.extend(str(item) for item in evidence["missing_doc_kinds"] if item)
        if isinstance(evidence.get("missing_conditional_attachments"), list):
            for item in evidence["missing_conditional_attachments"]:
                if isinstance(item, dict) and item.get("doc_kind"):
                    values.append(str(item["doc_kind"]))
        seen = set()
        deduped: List[str] = []
        for item in values:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def _build_attachment_clip(self, attachment: Dict[str, Any]) -> str:
        """构造附件证据片段"""
        details = attachment.get("classification_details", {})
        llm_info = details.get("llm", {}) if isinstance(details, dict) else {}
        visible_clues = llm_info.get("visible_clues", []) if isinstance(llm_info, dict) else []
        clues = "；".join(str(item) for item in visible_clues[:4])
        if not clues:
            clues = str(attachment.get("classification_reason", ""))
        secondary_hits = self._format_secondary_refine_hits(details)
        return (
            f"file_name={attachment.get('file_name', '')}\n"
            f"doc_kind={self._doc_kind_with_code(str(attachment.get('doc_kind', '')))}\n"
            f"contains={self._format_contains_doc_kinds(attachment)}\n"
            f"classification_source={attachment.get('classification_source', '')}\n"
            f"clues={clues}\n"
            f"{secondary_hits}"
        )

    def _build_attachment_overview_clip(self, attachments: List[Any]) -> str:
        """构造附件总览片段"""
        if not attachments:
            return "未扫描到附件文件"
        lines: List[str] = []
        for index, item in enumerate(attachments[:5], start=1):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("doc_kind", ""))
            contains = self._format_contains_doc_kinds(item)
            details = item.get("classification_details", {})
            secondary_hits = self._format_secondary_refine_hits_inline(details)
            file_name = str(item.get("file_name", ""))
            lines.extend([
                f"[{index}] 文件: {file_name}",
                f"    主分类: {self._doc_kind_with_code(kind)}",
                f"    复合命中: {contains}",
                f"    {secondary_hits}",
            ])
        if not lines:
            return "附件列表为空"
        return "已识别附件（前5）：\n" + "\n".join(lines)

    def _extract_keyword_snippet(self, text: str, keyword: str, radius: int = 90) -> str:
        """提取关键词附近片段"""
        if not text:
            return ""
        index = text.find(keyword)
        if index < 0:
            return text[: min(220, len(text))]
        start = max(0, index - radius)
        end = min(len(text), index + len(keyword) + radius)
        return text[start:end]

    def _doc_kind_label(self, doc_kind: str) -> str:
        """附件类别中文标签"""
        return self.DOC_KIND_LABELS.get(doc_kind, doc_kind or "-")

    def _doc_kind_with_code(self, doc_kind: str) -> str:
        """附件类别中文 + code"""
        label = self._doc_kind_label(doc_kind)
        if not doc_kind:
            return label
        if label == doc_kind:
            return doc_kind
        return f"{label} ({doc_kind})"

    def _format_contains_doc_kinds(self, attachment: Dict[str, Any]) -> str:
        """格式化单文件包含的多类别"""
        details = attachment.get("classification_details", {})
        if not isinstance(details, dict):
            return "-"
        values = details.get("contains_doc_kinds", [])
        if not isinstance(values, list) or not values:
            return "-"
        return "、".join(self._doc_kind_with_code(str(item)) for item in values if str(item).strip())

    def _format_secondary_refine_hits(self, details: Any) -> str:
        """格式化二次复核页命中详情"""
        if not isinstance(details, dict):
            return "二次复核页命中=-"
        refine = details.get("llm_secondary_refine", {})
        if not isinstance(refine, dict):
            return "二次复核页命中=-"
        page_candidates = refine.get("page_candidates", [])
        if not isinstance(page_candidates, list) or not page_candidates:
            return "二次复核页命中=-"
        lines: List[str] = []
        for item in page_candidates[:6]:
            if not isinstance(item, dict):
                continue
            page = item.get("page", "-")
            doc_kind = self._doc_kind_with_code(str(item.get("doc_kind", "")))
            confidence = item.get("confidence", "-")
            reason = str(item.get("reason", "")).strip()
            lines.append(f"第{page}页 -> {doc_kind} @ {confidence} | {reason}")
        if not lines:
            return "二次复核页命中=-"
        return "二次复核页命中=\n" + "\n".join(lines)

    def _format_secondary_refine_hits_inline(self, details: Any) -> str:
        """格式化二次复核页命中详情（单行简版）"""
        if not isinstance(details, dict):
            return "二次复核页命中=-"
        refine = details.get("llm_secondary_refine", {})
        if not isinstance(refine, dict):
            return "二次复核页命中=-"
        page_candidates = refine.get("page_candidates", [])
        if not isinstance(page_candidates, list) or not page_candidates:
            return "二次复核页命中=-"
        tokens: List[str] = []
        for item in page_candidates[:3]:
            if not isinstance(item, dict):
                continue
            page = item.get("page", "-")
            doc_kind = self._doc_kind_with_code(str(item.get("doc_kind", "")))
            confidence = item.get("confidence", "-")
            tokens.append(f"第{page}页 -> {doc_kind} @ {confidence}")
        if not tokens:
            return "二次复核页命中=-"
        return "二次复核页命中: " + "；".join(tokens)

    def _render_simple_list(self, values: List[str]) -> str:
        """渲染简单列表"""
        if not values:
            return "<div class='empty'>无</div>"
        return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"

    def _render_status_badges(self, values: List[tuple[str, str, str]]) -> str:
        """渲染一组状态标签"""
        return "".join(
            f"<span class='badge status-{escape(status)}'>{escape(label)} {escape(value)}</span>"
            for label, value, status in values
        )

    def _render_status_badge(self, status: str) -> str:
        """渲染状态标签"""
        return f"<span class='badge status-{escape(status)}'>{escape(status)}</span>"
