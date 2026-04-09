"""批次级形式审查 Agent"""
import asyncio
import ast
import io
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path
from typing import Any, Dict, List

import fitz
from PIL import Image

from src.common.review_runtime import ReviewRuntime
from src.common.models import BatchReviewRequest, BatchReviewResult, ProjectReviewResult
from src.services.review.debug_writer import ReviewDebugWriter
from src.services.review.notice_rules import build_notice_context
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
        "research_paper": "科研论文（发表论文）",
        "other_supporting_material": "其他支撑材料",
        "unknown_attachment": "未识别附件",
    }
    RULE_LABELS = {
        "required_project_fields": "必填字段完整性",
        "proposal_file_presence": "主申报书文件存在性",
        "registered_date_limit": "注册时间限制",
        "required_attachments": "必需附件",
        "conditional_attachments": "条件性附件",
        "execution_period_limit": "执行期限制",
        "external_status_check": "外部状态校验",
        "policy_review_points_check": "形式审查要点对照",
        "applicant_unit_type_check": "申报单位类型校验",
        "funding_ratio_check": "财政资金与自筹资金比例",
        "cooperation_region_check": "合作单位注册地区",
        "recommendation_letter_required": "推荐函要求",
        "ethics_approval_required": "伦理审查意见要求",
        "industry_permit_required": "行业准入材料要求",
        "biosafety_commitment_required": "生物安全承诺书要求",
        "commitment_letter_required": "承诺书要求",
        "cooperation_agreement_required": "合作协议要求",
        "duplicate_submission_check": "重复申报/多头申报",
        "other_policy_compliance": "其他政策符合性",
        "base_staff_proof_required": "基地固定人员证明要求",
        "platform_scope_check": "依托平台范围",
        "joint_application_check": "联合申报要求",
        "beijing_tianjin_partner_check": "京津合作单位要求",
        "cluster_region_check": "集群地区匹配",
        "unfinished_guidance_project_check": "基地未结题项目限制",
        "joint_updownstream_application_check": "产业链上下游联合申报",
        "shared_mechanism_check": "共投共研共享机制",
        "provincial_nsf_conflict_check": "省自然基金冲突限制",
        "unfinished_basic_project_check": "基础研究项目未验收限制",
        "applicant_qualification_check": "申报单位资格",
        "project_leader_age_check": "项目负责人年龄限制",
        "active_guidance_project_leader_check": "负责人在研项目限制",
        "integrity_and_credit_check": "科研诚信与信用记录",
        "project_count_limit_check": "负责人项目数量限制",
        "enterprise_batch_limit_check": "企业申报数量限制",
        "enterprise_active_guidance_project_check": "企业在研项目限制",
        "performance_metric_count_check": "绩效指标设置要求",
        "budget_forbidden_expense_check": "经费禁列项检查",
        "leader_achievement_attachment_check": "负责人及骨干成果证明材料",
    }
    FIELD_LABELS = {
        "project_id": "项目ID",
        "project_type": "项目类型",
        "project_name": "项目名称",
        "applicant_unit": "申报单位",
        "execution_period_years": "执行期（年）",
        "year": "年度",
        "budget_line_count": "预算明细行数",
        "project_leader_birth_date": "项目负责人出生日期",
        "limit_birth_date": "年龄限制日期",
        "performance_metric_count": "绩效指标数量",
        "performance_first_year_ratio": "第一年度目标占比",
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
        notice_context = build_notice_context(
            notice_url=request.notice_url,
            notice_html=request.notice_html,
        )
        debug_writer = ReviewDebugWriter(batch_id)
        debug_writer.write_json("request.json", request.model_dump())
        debug_writer.write_json("notice_context.json", notice_context)
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
                context.notice_context = notice_context
                context_payload = context.model_dump(mode="json")
                context.scan_info["preview_assets"] = self._write_project_preview_assets(
                    debug_writer=debug_writer,
                    project_id=row.project_id,
                    context=context_payload,
                )
                context_payload = context.model_dump(mode="json")
                context.scan_info["packet_assets"] = self._write_project_packet_assets(
                    debug_writer=debug_writer,
                    project_id=row.project_id,
                    context=context_payload,
                )
                context_payload = context.model_dump(mode="json")
                debug_writer.write_json(
                    f"projects/{row.project_id}.scan.json",
                    context.scan_info,
                )
                debug_writer.write_json(
                    f"projects/{row.project_id}.context.json",
                    context_payload,
                )
                project_result = await self.project_review_agent.process_context(context)
                debug_writer.write_json(
                    f"projects/{row.project_id}.result.json",
                    project_result.model_dump(mode="json"),
                )
                return project_result, context_payload

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
        payload = self._build_workspace_payload(project_results, project_context_map)
        payload_json = json.dumps(payload, ensure_ascii=False)
        suggestion_items = "".join(f"<li>{escape(item)}</li>" for item in suggestions) or "<li>无</li>"
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
  <title>{escape(batch_id)} 审查工作台</title>
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
      --passed: #067647;
      --failed: #b42318;
      --warning: #9a3412;
      --manual: #7c3aed;
      --na: #344054;
      --system: #2b6cb0;
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
    }}
    .page {{
      max-width: 1680px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero, .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
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
      background: linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
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
    .workspace {{
      display: grid;
      grid-template-columns: 280px minmax(480px, 1.3fr) minmax(360px, 0.95fr);
      gap: 18px;
      align-items: start;
    }}
    .sidebar, .center-panel, .viewer-panel {{
      min-height: 72vh;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }}
    .sidebar {{
      padding: 18px 14px;
      position: sticky;
      top: 16px;
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
      max-height: calc(72vh - 84px);
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
      padding: 18px 18px 20px;
    }}
    .panel-head {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 14px;
      margin-bottom: 16px;
    }}
    .panel-head h2, .panel-head h3 {{
      margin: 0;
    }}
    .project-summary {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .panel-links {{
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 13px;
    }}
    .badge {{
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 11px;
      font-weight: 600;
      border: 0;
      background: #f1f5f9;
      white-space: nowrap;
    }}
    .status-passed {{ color: var(--passed); background: #ecfdf3; }}
    .status-failed {{ color: var(--failed); background: #fff1f2; }}
    .status-warning {{ color: var(--manual); background: #f5f3ff; }}
    .status-manual {{ color: var(--manual); background: #f5f3ff; }}
    .status-requires_data {{ color: var(--manual); background: #f5f3ff; }}
    .status-not_applicable {{ color: var(--na); background: #f2f4f7; }}
    .status-system_managed {{ color: var(--system); background: #eff6ff; }}
    .status-skipped {{ color: var(--na); background: #f2f4f7; }}
    .summary-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .result-sections {{
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}
    .result-section {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: linear-gradient(180deg, #ffffff 0%, #fafcff 100%);
      padding: 14px;
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .section-head-title {{
      font-size: 15px;
      font-weight: 800;
    }}
    .section-subgroups {{
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .status-group {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .status-group-head {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .status-group-count {{
      opacity: 0.85;
    }}
    .rule-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .rule-card {{
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #ffffff;
      padding: 14px;
      cursor: pointer;
      transition: 0.18s ease;
    }}
    .rule-card:hover {{
      border-color: var(--line-strong);
    }}
    .rule-card.active {{
      border-color: var(--accent);
      background: linear-gradient(180deg, #ffffff 0%, #f0fdfa 100%);
      box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.14);
    }}
    .rule-card-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .rule-card-title {{
      font-size: 15px;
      font-weight: 800;
      line-height: 1.5;
    }}
    .rule-card-requirement {{
      color: var(--text);
      font-size: 13px;
      line-height: 1.7;
      white-space: pre-wrap;
    }}
    .rule-card-meta {{
      display: grid;
      grid-template-columns: 72px 1fr;
      gap: 6px 10px;
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
    }}
    .rule-card-meta-label {{
      color: var(--muted);
    }}
    .viewer-panel {{
      position: sticky;
      top: 16px;
    }}
    .viewer-empty {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
      padding: 24px 4px 8px;
    }}
    .evidence-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }}
    .evidence-tab {{
      border: 1px solid var(--line);
      background: #f8fafc;
      color: var(--text);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      cursor: pointer;
    }}
    .evidence-tab.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #115e59;
    }}
    .viewer-meta {{
      display: grid;
      grid-template-columns: 84px 1fr;
      gap: 8px 12px;
      font-size: 13px;
      margin-bottom: 14px;
    }}
    .viewer-meta-label {{
      color: var(--muted);
    }}
    .viewer-preview {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #f8fafc;
      min-height: 360px;
      overflow: hidden;
      display: flex;
      align-items: stretch;
      justify-content: center;
    }}
    .viewer-preview iframe {{
      width: 100%;
      min-height: 420px;
      border: 0;
      background: #fff;
    }}
    .viewer-preview img {{
      max-width: 100%;
      display: block;
    }}
    .viewer-fallback {{
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      color: var(--muted);
      text-align: center;
      line-height: 1.8;
    }}
    .clip-panel {{
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fbfcfe;
      padding: 14px;
    }}
    .clip-title {{
      margin: 0 0 10px;
      font-size: 14px;
      font-weight: 800;
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
    .policy-table th.group-left {{
      background: #eef4ff;
      color: #1d4ed8;
      border-right: 2px solid var(--line);
      text-align: center;
    }}
    .policy-table th.group-right {{
      background: #fff4e8;
      color: #b54708;
      text-align: center;
    }}
    .policy-table td.left-block {{
      width: 44%;
      border-right: 2px solid var(--line);
      background: #fbfdff;
    }}
    .policy-table td.right-block {{
      width: 56%;
      background: #fffdf9;
    }}
    .policy-point {{
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .policy-req {{
      color: var(--text);
      line-height: 1.6;
    }}
    .policy-result {{
      display: grid;
      grid-template-columns: 72px 1fr;
      gap: 8px 12px;
      align-items: start;
    }}
    .policy-result .label {{
      color: var(--muted);
      font-size: 12px;
    }}
    .extra-table th.group-left {{
      background: #eefaf3;
      color: #067647;
      border-right: 2px solid var(--line);
      text-align: center;
    }}
    .extra-table th.group-right {{
      background: #fff7ed;
      color: #c2410c;
      text-align: center;
    }}
    .extra-table td.left-block {{
      width: 38%;
      border-right: 2px solid var(--line);
      background: #fbfefc;
    }}
    .extra-table td.right-block {{
      width: 62%;
      background: #fffdfa;
    }}
    .extra-title {{
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .extra-message {{
      line-height: 1.6;
    }}
    .extra-result {{
      display: grid;
      grid-template-columns: 72px 1fr;
      gap: 8px 12px;
      align-items: start;
    }}
    .extra-result .label {{
      color: var(--muted);
      font-size: 12px;
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
    pre.mono {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .empty {{
      color: var(--muted);
      font-size: 14px;
    }}
    .folded-toggle {{
      margin-top: 6px;
      border: 1px dashed var(--line);
      border-radius: 14px;
      background: #fbfcff;
    }}
    .folded-toggle summary {{
      cursor: pointer;
      padding: 12px 14px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      list-style: none;
    }}
    .folded-toggle summary::-webkit-details-marker {{
      display: none;
    }}
    .folded-body {{
      padding: 0 12px 12px;
    }}
    @media (max-width: 1320px) {{
      .workspace {{
        grid-template-columns: 240px minmax(420px, 1fr) minmax(320px, 0.9fr);
      }}
    }}
    @media (max-width: 1080px) {{
      .workspace {{
        grid-template-columns: 1fr;
      }}
      .sidebar, .viewer-panel {{
        position: static;
      }}
      .project-list {{
        max-height: none;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>批次审查工作台</h1>
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
    <section class="workspace">
      <aside class="sidebar">
        <div class="sidebar-head">
          <h2 class="sidebar-title">项目列表</h2>
          <div class="sidebar-subtitle">左侧切项目，中间看规则，右侧固定查看当前项目的合并材料。</div>
        </div>
        <div class="project-list" id="projectList"></div>
      </aside>
      <main class="center-panel">
        <div id="centerPanel"></div>
      </main>
      <aside class="viewer-panel">
        <div id="viewerPanel"></div>
      </aside>
    </section>
  </div>
  <script>
    const REPORT_DATA = {payload_json};

    const state = {{
      projectIndex: 0,
      ruleId: "",
      evidenceIndex: 0,
    }};

    function statusBadge(status, label) {{
      const safeStatus = String(status || "not_applicable");
      const safeLabel = String(label || safeStatus);
      return `<span class="badge status-${{escapeHtml(safeStatus)}}">${{escapeHtml(safeLabel)}}</span>`;
    }}

    function escapeHtml(value) {{
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function renderProjectList() {{
      const container = document.getElementById("projectList");
      if (!REPORT_DATA.projects.length) {{
        container.innerHTML = '<div class="empty">无项目结果</div>';
        return;
      }}
      container.innerHTML = REPORT_DATA.projects.map((project, index) => `
        <button class="project-item ${{index === state.projectIndex ? "active" : ""}}" data-project-index="${{index}}">
          <div class="project-item-title">${{escapeHtml(project.project_name || project.project_id)}}</div>
          <div class="project-item-meta">${{escapeHtml(project.project_id)}} · ${{escapeHtml(project.project_type)}}</div>
          <div class="project-item-stats">
            ${{statusBadge("failed", `失败 ${{project.counts.failed}}`)}}
            ${{statusBadge("manual", `需人工 ${{project.counts.manual}}`)}}
            ${{statusBadge("passed", `通过 ${{project.counts.passed}}`)}}
          </div>
        </button>
      `).join("");
      container.querySelectorAll(".project-item").forEach((node) => {{
        node.addEventListener("click", () => {{
          const index = Number(node.dataset.projectIndex || 0);
          selectProject(index);
        }});
      }});
    }}

    function selectProject(index) {{
      state.projectIndex = index;
      const project = REPORT_DATA.projects[index];
      state.ruleId = project.default_rule_id || findFirstRuleId(project) || "";
      state.evidenceIndex = 0;
      renderAll();
    }}

    function findFirstRuleId(project) {{
      const sections = [...project.policy_sections, ...project.extra_sections];
      for (const section of sections) {{
        for (const group of section.groups) {{
          if (group.items && group.items.length) {{
            return group.items[0].id;
          }}
        }}
      }}
      return "";
    }}

    function selectRule(ruleId) {{
      state.ruleId = ruleId;
      state.evidenceIndex = 0;
      renderCenterPanel();
      renderViewerPanel();
    }}

    function selectEvidence(index) {{
      state.evidenceIndex = index;
      renderViewerPanel();
    }}

    function renderCenterPanel() {{
      const project = REPORT_DATA.projects[state.projectIndex];
      const center = document.getElementById("centerPanel");
      if (!project) {{
        center.innerHTML = '<div class="empty">无项目</div>';
        return;
      }}
      center.innerHTML = `
        <div class="panel-head">
          <h2>${{escapeHtml(project.project_name || project.project_id)}}</h2>
          <div class="project-summary">${{escapeHtml(project.summary)}}</div>
          <div class="summary-badges">
            ${{statusBadge("failed", `失败 ${{project.counts.failed}}`)}}
            ${{statusBadge("manual", `需人工处理 ${{project.counts.manual}}`)}}
            ${{statusBadge("passed", `通过 ${{project.counts.passed}}`)}}
            ${{statusBadge("system_managed", `系统已限制 ${{project.counts.system_managed}}`)}}
            ${{statusBadge("not_applicable", `不适用 ${{project.counts.not_applicable}}`)}}
          </div>
          <div class="panel-links">
            <a href="${{escapeHtml(project.links.context)}}" target="_blank" rel="noopener noreferrer">context.json</a>
            <a href="${{escapeHtml(project.links.result)}}" target="_blank" rel="noopener noreferrer">result.json</a>
            <a href="${{escapeHtml(project.links.scan)}}" target="_blank" rel="noopener noreferrer">scan.json</a>
            ${{project.links.packet ? `<a href="${{escapeHtml(project.links.packet)}}" target="_blank" rel="noopener noreferrer">review_packet.pdf</a>` : ""}}
            ${{project.links.packet_page_map ? `<a href="${{escapeHtml(project.links.packet_page_map)}}" target="_blank" rel="noopener noreferrer">packet.page_map.json</a>` : ""}}
          </div>
        </div>
        <div class="result-sections">
          ${{renderSections(project.policy_sections, "审查要点对照")}}
          ${{renderSections(project.extra_sections, "额外检查项")}}
        </div>
      `;
      center.querySelectorAll(".rule-card").forEach((node) => {{
        node.addEventListener("click", () => {{
          selectRule(String(node.dataset.ruleId || ""));
        }});
      }});
    }}

    function renderSections(sections, fallbackTitle) {{
      if (!sections || !sections.length) {{
        return `<section class="result-section"><div class="section-head"><div class="section-head-title">${{escapeHtml(fallbackTitle)}}</div></div><div class="empty">无</div></section>`;
      }}
      return sections.map((section) => `
        <section class="result-section">
          <div class="section-head">
            <div class="section-head-title">${{escapeHtml(section.title)}}</div>
            <div class="project-item-stats">${{section.badges.map((badge) => statusBadge(badge.status, `${{badge.label}} ${{badge.value}}`)).join("")}}</div>
          </div>
          <div class="section-subgroups">
            ${{renderGroups(section.groups.filter((group) => !group.folded))}}
            ${{renderFoldedGroups(section.groups.filter((group) => group.folded))}}
          </div>
        </section>
      `).join("");
    }}

    function renderGroups(groups) {{
      if (!groups.length) {{
        return '<div class="empty">无</div>';
      }}
      return groups.map((group) => `
        <section class="status-group">
          <div class="status-group-head">
            ${{statusBadge(group.status, group.label)}}
            <span class="status-group-count">${{group.items.length}} 项</span>
          </div>
          <div class="rule-list">
            ${{group.items.map((item) => renderRuleCard(item)).join("")}}
          </div>
        </section>
      `).join("");
    }}

    function renderFoldedGroups(groups) {{
      if (!groups.length) {{
        return "";
      }}
      const total = groups.reduce((sum, group) => sum + group.items.length, 0);
      return `
        <details class="folded-toggle">
          <summary>系统前置限制 / 不适用（${{total}} 项）</summary>
          <div class="folded-body">
            ${{renderGroups(groups)}}
          </div>
        </details>
      `;
    }}

    function renderRuleCard(item) {{
      return `
        <button class="rule-card ${{item.id === state.ruleId ? "active" : ""}}" data-rule-id="${{escapeHtml(item.id)}}">
          <div class="rule-card-top">
            <div class="rule-card-title">${{escapeHtml(item.title)}}</div>
            <div>${{statusBadge(item.status, item.status_label)}}</div>
          </div>
          <div class="rule-card-requirement">${{escapeHtml(item.requirement || item.summary)}}</div>
          <div class="rule-card-meta">
            <div class="rule-card-meta-label">核验来源</div><div>${{escapeHtml(item.source_rule_label || "-")}}</div>
            <div class="rule-card-meta-label">结果说明</div><div>${{escapeHtml(item.summary || "-")}}</div>
            <div class="rule-card-meta-label">证据定位</div><div>${{item.evidence_targets.length ? `${{item.evidence_targets.length}} 个命中` : "无可跳转证据"}}</div>
          </div>
        </button>
      `;
    }}

    function getActiveRule(project) {{
      const sections = [...project.policy_sections, ...project.extra_sections];
      for (const section of sections) {{
        for (const group of section.groups) {{
          const item = (group.items || []).find((entry) => entry.id === state.ruleId);
          if (item) {{
            return item;
          }}
        }}
      }}
      return null;
    }}

    function renderViewerPanel() {{
      const project = REPORT_DATA.projects[state.projectIndex];
      const viewer = document.getElementById("viewerPanel");
      if (!project) {{
        viewer.innerHTML = '<div class="viewer-empty">无项目。</div>';
        return;
      }}
      const rule = getActiveRule(project);
      if (!rule) {{
        viewer.innerHTML = '<div class="viewer-empty">选择中间的规则项后，在这里查看对应证据或规则说明。</div>';
        return;
      }}
      const targets = rule.evidence_targets || [];
      const activeIndex = Math.max(0, Math.min(state.evidenceIndex, targets.length - 1));
      const target = targets[activeIndex] || null;
      viewer.innerHTML = `
        <div class="panel-head">
          <h3>${{escapeHtml(rule.title)}}</h3>
          <div class="project-summary">${{escapeHtml(rule.summary || "点击不同规则可切换证据。")}}</div>
        </div>
        ${{targets.length ? `<div class="evidence-tabs">${{targets.map((item, index) => `
          <button class="evidence-tab ${{index === activeIndex ? "active" : ""}}" data-evidence-index="${{index}}">
            ${{escapeHtml(item.tab_label || `证据${{index + 1}}`)}}
          </button>
        `).join("")}}</div>` : ""}}
        ${{target ? renderEvidenceTarget(target, project) : '<div class="viewer-empty">当前规则暂无可跳转证据。可通过中栏说明和 JSON 进一步排查。</div>'}}
      `;
      viewer.querySelectorAll(".evidence-tab").forEach((node) => {{
        node.addEventListener("click", () => {{
          selectEvidence(Number(node.dataset.evidenceIndex || 0));
        }});
      }});
    }}

    function renderEvidenceTarget(target, project) {{
      const packet = project.packet || {{}};
      const packetPage = Number(target.packet_page || packet.default_page || 1);
      const packetUri = packet.packet_file ? `${{packet.packet_file}}#page=${{packetPage}}` : "";
      return `
        <div class="viewer-meta">
          <div class="viewer-meta-label">来源文件</div><div class="mono">${{escapeHtml(target.source_file || "-")}}</div>
          <div class="viewer-meta-label">定位</div><div>${{escapeHtml(target.location_label || "-")}}</div>
          <div class="viewer-meta-label">Packet页码</div><div>${{packetUri ? `第${{packetPage}}页` : "不可用"}}</div>
          <div class="viewer-meta-label">打开原件</div><div>${{target.open_uri ? `<a href="${{escapeHtml(target.open_uri)}}" target="_blank" rel="noopener noreferrer">打开原文件</a>` : "不可用"}}</div>
        </div>
        <div class="viewer-preview">${{renderPreview(target, packetUri)}}</div>
        <div class="clip-panel">
          <div class="clip-title">${{target.viewer_mode === "document" ? "证据摘要" : "规则说明"}}</div>
          <pre class="mono">${{escapeHtml(target.clip || "无证据摘要")}}</pre>
        </div>
      `;
    }}

    function renderPreview(target, packetUri) {{
      if (packetUri) {{
        return `<iframe src="${{escapeHtml(packetUri)}}" title="review packet"></iframe>`;
      }}
      if (target.preview_mode === "html" && target.preview_uri) {{
        return `<iframe src="${{escapeHtml(target.preview_uri)}}" title="evidence html"></iframe>`;
      }}
      if (target.preview_mode === "image" && target.preview_uri) {{
        return `<img src="${{escapeHtml(target.preview_uri)}}" alt="evidence image">`;
      }}
      if (target.preview_mode === "pdf" && target.preview_uri) {{
        return `<iframe src="${{escapeHtml(target.preview_uri)}}" title="evidence pdf"></iframe>`;
      }}
      if (target.viewer_mode === "explanation") {{
        return `<div class="viewer-fallback">这条证据属于规则计算结果或附件目录汇总，不对应单个可预览页面。</div>`;
      }}
      if (target.open_uri) {{
        return `<div class="viewer-fallback">当前文件暂不支持内嵌预览。<br><a href="${{escapeHtml(target.open_uri)}}" target="_blank" rel="noopener noreferrer">打开原文件</a></div>`;
      }}
      return `<div class="viewer-fallback">当前证据没有可用预览资产。</div>`;
    }}

    function renderAll() {{
      renderProjectList();
      renderCenterPanel();
      renderViewerPanel();
    }}

    if (REPORT_DATA.projects.length) {{
      state.projectIndex = 0;
      state.ruleId = REPORT_DATA.projects[0].default_rule_id || findFirstRuleId(REPORT_DATA.projects[0]) || "";
    }}
    renderAll();
  </script>
</body>
</html>"""

    def _write_project_preview_assets(
        self,
        debug_writer: ReviewDebugWriter,
        project_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """为项目内可预览文件生成调试预览资产"""
        manifest: Dict[str, Dict[str, Any]] = {}
        scan_info = context.get("scan_info", {}) if isinstance(context, dict) else {}
        proposal_file = str(scan_info.get("proposal_main_file") or "").strip()
        attachment_items = context.get("attachments", []) if isinstance(context, dict) else []

        if proposal_file:
            preview = self._write_file_preview_asset(
                debug_writer=debug_writer,
                project_id=project_id,
                source_file=proposal_file,
                asset_name="proposal_main",
                title="申报书主文件预览",
            )
            if preview:
                manifest[proposal_file] = preview

        for index, item in enumerate(attachment_items, start=1):
            if not isinstance(item, dict):
                continue
            source_file = str(item.get("file_ref") or "").strip()
            if not source_file or source_file in manifest:
                continue
            file_name = str(item.get("file_name") or f"attachment_{index}")
            safe_name = re.sub(r"[^0-9A-Za-z_.-]", "_", Path(file_name).stem)[:48] or f"attachment_{index}"
            preview = self._write_file_preview_asset(
                debug_writer=debug_writer,
                project_id=project_id,
                source_file=source_file,
                asset_name=f"attachment_{index}_{safe_name}",
                title=file_name,
            )
            if preview:
                manifest[source_file] = preview

        return manifest

    def _write_file_preview_asset(
        self,
        debug_writer: ReviewDebugWriter,
        project_id: str,
        source_file: str,
        asset_name: str,
        title: str,
    ) -> Dict[str, Any] | None:
        """按文件类型生成预览资产"""
        path = Path(source_file)
        if not path.exists() or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix != ".docx":
            return None

        paragraphs = self._extract_docx_preview_paragraphs(path)
        if not paragraphs:
            return None

        relative_path = f"projects/{project_id}/previews/{asset_name}.html"
        preview_html = self._build_docx_preview_html(title=title, source_file=source_file, paragraphs=paragraphs)
        debug_writer.write_text(relative_path, preview_html)
        return {
            "preview_file": relative_path,
            "preview_mode": "html",
            "blocks": [
                {
                    "anchor_id": f"p-{index}",
                    "text": paragraph,
                }
                for index, paragraph in enumerate(paragraphs, start=1)
            ],
        }

    def _extract_docx_preview_paragraphs(self, path: Path) -> List[str]:
        """轻量提取 docx 预览段落"""
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: List[str] = []
        try:
            with zipfile.ZipFile(path) as archive:
                xml_bytes = archive.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
        except Exception:
            return paragraphs

        body = root.find("w:body", ns)
        if body is None:
            return paragraphs

        for child in list(body):
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = "".join(node.text or "" for node in child.findall(".//w:t", ns)).strip()
                normalized = re.sub(r"\s+", " ", text)
                if normalized:
                    paragraphs.append(normalized[:600])
            elif tag == "tbl":
                for row in child.findall("w:tr", ns):
                    cells = []
                    for cell in row.findall("w:tc", ns):
                        cell_text = "".join(node.text or "" for node in cell.findall(".//w:t", ns)).strip()
                        normalized = re.sub(r"\s+", " ", cell_text)
                        if normalized:
                            cells.append(normalized[:200])
                    if cells:
                        paragraphs.append(" | ".join(cells))
            if len(paragraphs) >= 400:
                break
        return paragraphs

    def _build_docx_preview_html(self, title: str, source_file: str, paragraphs: List[str]) -> str:
        """构造 docx 预览 HTML"""
        blocks = []
        for index, paragraph in enumerate(paragraphs, start=1):
            block_class = "table-row" if " | " in paragraph else "paragraph"
            blocks.append(
                f"<div class='block {block_class}' id='p-{index}'><span class='line-no'>{index}</span><div class='text'>{escape(paragraph)}</div></div>"
            )
        content = "\n".join(blocks) or "<div class='empty'>文档无可预览文本</div>"
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f7fafc;
      --card: #ffffff;
      --line: #d8e1eb;
      --text: #182230;
      --muted: #667085;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .page {{
      max-width: 980px;
      margin: 0 auto;
      padding: 20px;
    }}
    .head {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      margin-bottom: 14px;
    }}
    .title {{
      margin: 0 0 8px;
      font-size: 20px;
      font-weight: 800;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
      word-break: break-all;
    }}
    .doc {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
    }}
    .block {{
      display: grid;
      grid-template-columns: 52px 1fr;
      gap: 12px;
      padding: 10px 0;
      border-top: 1px solid #edf2f7;
    }}
    .block:first-child {{
      border-top: 0;
    }}
    .line-no {{
      color: var(--muted);
      font-size: 12px;
      text-align: right;
      padding-top: 2px;
    }}
    .text {{
      font-size: 14px;
      line-height: 1.9;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .table-row .text {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: #f8fafc;
      border: 1px solid #e7edf5;
      border-radius: 10px;
      padding: 10px 12px;
      line-height: 1.7;
    }}
    .empty {{
      color: var(--muted);
      font-size: 14px;
      padding: 10px 0;
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="head">
      <h1 class="title">{escape(title)}</h1>
      <div class="meta">源文件：{escape(source_file)}</div>
      <div class="meta">说明：当前为 docx 文本预览，优先解决规则到正文的可视化跳转。</div>
    </section>
    <section class="doc">
      {content}
    </section>
  </div>
</body>
</html>"""

    def _write_project_packet_assets(
        self,
        debug_writer: ReviewDebugWriter,
        project_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成项目统一 packet PDF，按原始顺序合并材料"""
        ordered_sources = self._collect_packet_sources(context)
        if not ordered_sources:
            return {}

        packet_doc = fitz.open()
        page_map: List[Dict[str, Any]] = []
        source_items: List[Dict[str, Any]] = []

        for order, item in enumerate(ordered_sources, start=1):
            source_file = str(item.get("source_file") or "").strip()
            if not source_file:
                continue
            path = Path(source_file)
            if not path.exists() or not path.is_file():
                continue
            merged_doc, merge_mode = self._open_mergeable_document(path)
            if merged_doc is None or merged_doc.page_count <= 0:
                continue
            start_page = packet_doc.page_count + 1
            packet_doc.insert_pdf(merged_doc)
            end_page = packet_doc.page_count
            page_count = max(0, end_page - start_page + 1)
            page_map.append(
                {
                    "source_file": source_file,
                    "source_name": str(item.get("source_name") or path.name),
                    "source_kind": str(item.get("source_kind") or "attachment"),
                    "doc_kind": str(item.get("doc_kind") or ""),
                    "start_page": start_page,
                    "end_page": end_page,
                    "page_count": page_count,
                    "merge_mode": merge_mode,
                }
            )
            source_items.append(
                {
                    "order": order,
                    "source_file": source_file,
                    "source_name": str(item.get("source_name") or path.name),
                    "source_kind": str(item.get("source_kind") or "attachment"),
                    "doc_kind": str(item.get("doc_kind") or ""),
                    "merge_mode": merge_mode,
                }
            )
            merged_doc.close()

        if packet_doc.page_count <= 0:
            packet_doc.close()
            return {}

        packet_bytes = packet_doc.tobytes(garbage=3, deflate=True)
        packet_doc.close()

        packet_file = f"projects/{project_id}/review_packet.pdf"
        page_map_file = f"projects/{project_id}/review_packet.page_map.json"
        debug_writer.write_bytes(packet_file, packet_bytes)
        debug_writer.write_json(page_map_file, page_map)
        return {
            "packet_file": packet_file,
            "page_map_file": page_map_file,
            "page_map": page_map,
            "source_items": source_items,
            "default_page": 1,
        }

    def _collect_packet_sources(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """收集 packet 合并输入，保持原始顺序"""
        sources: List[Dict[str, Any]] = []
        scan_info = context.get("scan_info", {}) if isinstance(context, dict) else {}
        proposal_files = scan_info.get("proposal_files", []) if isinstance(scan_info, dict) else []
        proposal_file = self._resolve_packet_proposal_file(proposal_files, scan_info)
        if proposal_file:
            proposal_path = Path(proposal_file)
            sources.append(
                {
                    "source_file": proposal_file,
                    "source_name": proposal_path.name,
                    "source_kind": "proposal",
                    "doc_kind": "",
                }
            )

        attachments = context.get("attachments", []) if isinstance(context, dict) else []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            source_file = str(item.get("file_ref") or "").strip()
            if not source_file:
                continue
            path = Path(source_file)
            sources.append(
                {
                    "source_file": source_file,
                    "source_name": str(item.get("file_name") or path.name),
                    "source_kind": "attachment",
                    "doc_kind": str(item.get("doc_kind") or ""),
                }
            )
        return sources

    def _resolve_packet_proposal_file(self, proposal_files: Any, scan_info: Dict[str, Any]) -> str:
        """为 packet 选择申报书源文件，优先原始 PDF"""
        candidates = [str(item).strip() for item in proposal_files or [] if str(item).strip()]
        pdf_candidates = [item for item in candidates if Path(item).suffix.lower() == ".pdf"]
        if pdf_candidates:
            return pdf_candidates[0]
        main_file = str(scan_info.get("proposal_main_file") or "").strip()
        if main_file:
            return main_file
        return candidates[0] if candidates else ""

    def _open_mergeable_document(self, path: Path) -> tuple[fitz.Document | None, str]:
        """把不同材料转换为可合并 PDF 文档"""
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                return fitz.open(path), "pdf"
            if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}:
                return self._image_to_pdf_document(path), "image_to_pdf"
            if suffix == ".docx":
                return self._docx_to_fallback_pdf_document(path), "docx_fallback"
        except Exception:
            return None, "unsupported"
        return None, "unsupported"

    def _image_to_pdf_document(self, path: Path) -> fitz.Document:
        """图片转单页 PDF 文档"""
        with Image.open(path) as image:
            rgb_image = image.convert("RGB")
            buffer = io.BytesIO()
            rgb_image.save(buffer, format="PDF", resolution=150.0)
        return fitz.open(stream=buffer.getvalue(), filetype="pdf")

    def _docx_to_fallback_pdf_document(self, path: Path) -> fitz.Document:
        """docx 无原始 PDF 时的降级合并方案"""
        paragraphs = self._extract_docx_preview_paragraphs(path)
        if not paragraphs:
            paragraphs = [path.name]

        doc = fitz.open()
        page_width = 595
        page_height = 842
        margin_x = 44
        margin_y = 48
        font_size = 10
        line_height = 16
        usable_width = page_width - margin_x * 2
        usable_height = page_height - margin_y * 2
        max_lines = max(1, int(usable_height // line_height))
        lines: List[str] = []

        for paragraph in paragraphs:
            text = paragraph.strip()
            if not text:
                lines.append("")
                continue
            chunk_size = 36 if " | " in text else 42
            for start in range(0, len(text), chunk_size):
                lines.append(text[start:start + chunk_size])
            lines.append("")

        if not lines:
            lines = [path.name]

        for start in range(0, len(lines), max_lines):
            page = doc.new_page(width=page_width, height=page_height)
            text_block = "\n".join(lines[start:start + max_lines]).strip() or path.name
            page.insert_textbox(
                fitz.Rect(margin_x, margin_y, margin_x + usable_width, margin_y + usable_height),
                text_block,
                fontsize=font_size,
                lineheight=1.4,
                fontname="helv",
                color=(0, 0, 0),
            )
        return doc

    def _build_workspace_payload(
        self,
        project_results: List[ProjectReviewResult],
        project_context_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构造三栏报告工作台数据"""
        projects = [
            self._build_project_workspace_item(result, project_context_map.get(result.project_id, {}))
            for result in project_results
        ]
        return {
            "projects": projects,
        }

    def _build_project_workspace_item(self, result: ProjectReviewResult, context_payload: Dict[str, Any]) -> Dict[str, Any]:
        """构造单项目工作台数据"""
        project_info = context_payload.get("project_info", {}) if isinstance(context_payload, dict) else {}
        scan_info = context_payload.get("scan_info", {}) if isinstance(context_payload, dict) else {}
        packet_assets = scan_info.get("packet_assets", {}) if isinstance(scan_info, dict) else {}
        project_name = str(project_info.get("project_name") or result.project_id)
        policy_sections = [
            self._build_section_payload(
                "形式审查要点对照",
                [
                    self._build_policy_rule_workspace_item(item, result, context_payload)
                    for item in result.policy_rule_checks
                ],
            )
        ]
        extra_sections = [
            self._build_section_payload(
                "额外检查项",
                [
                    self._build_extra_rule_workspace_item(item, context_payload)
                    for item in result.results
                    if item.item not in {
                        policy_item.code for policy_item in result.policy_rule_checks if getattr(policy_item, "code", None)
                    }
                    and item.item not in {
                        policy_item.source_rule for policy_item in result.policy_rule_checks if getattr(policy_item, "source_rule", None)
                    }
                ],
            )
        ]
        all_items = []
        for section in [*policy_sections, *extra_sections]:
            for group in section["groups"]:
                all_items.extend(group["items"])
        status_counts = self._count_workspace_items(all_items)
        default_rule_id = next(
            (
                item["id"]
                for item in all_items
                if item["status"] in {"failed", "manual"}
            ),
            all_items[0]["id"] if all_items else "",
        )
        return {
            "project_id": result.project_id,
            "project_name": project_name,
            "project_type": result.project_type,
            "summary": result.summary,
            "counts": status_counts,
            "policy_sections": policy_sections,
            "extra_sections": extra_sections,
            "default_rule_id": default_rule_id,
            "links": {
                "context": f"projects/{result.project_id}.context.json",
                "result": f"projects/{result.project_id}.result.json",
                "scan": f"projects/{result.project_id}.scan.json",
                "packet": str(packet_assets.get("packet_file", "")),
                "packet_page_map": str(packet_assets.get("page_map_file", "")),
            },
            "packet": packet_assets,
        }

    def _count_workspace_items(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """统计工作台条目状态数量"""
        counts = {
            "failed": 0,
            "manual": 0,
            "passed": 0,
            "system_managed": 0,
            "not_applicable": 0,
        }
        for item in items:
            group_key = str(item.get("group", "passed"))
            counts[group_key] = counts.get(group_key, 0) + 1
        return counts

    def _build_section_payload(self, title: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """按状态分组构造展示 section"""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(item["group"], []).append(item)
        groups = []
        ordered_keys = ["failed", "manual", "passed", "system_managed", "not_applicable"]
        for key in ordered_keys:
            values = grouped.get(key, [])
            if not values:
                continue
            label, css_class = self._display_status_meta(key)
            groups.append(
                {
                    "status": css_class,
                    "label": label,
                    "items": values,
                    "folded": key in {"system_managed", "not_applicable"},
                }
            )
        badges = [
            {"label": "失败", "value": str(len(grouped.get("failed", []))), "status": "failed"},
            {"label": "需人工", "value": str(len(grouped.get("manual", []))), "status": "manual"},
            {"label": "通过", "value": str(len(grouped.get("passed", []))), "status": "passed"},
        ]
        return {
            "title": title,
            "groups": groups,
            "badges": [badge for badge in badges if badge["value"] != "0"],
        }

    def _build_policy_rule_workspace_item(self, item: Any, result: ProjectReviewResult, context_payload: Dict[str, Any]) -> Dict[str, Any]:
        """构造审查要点卡片"""
        source_result = next((entry for entry in result.results if entry.item == item.source_rule), None)
        evidence_targets = self._build_evidence_targets_for_rule(
            rule_code=item.code,
            status=item.status,
            source_result=source_result,
            context_payload=context_payload,
            expected_doc_kind=self._policy_rule_doc_kind(item.code),
        )
        status_label, status_class = self._display_status_meta(item.status)
        return {
            "id": f"policy:{item.code}",
            "title": self._rule_label(item.code),
            "requirement": item.requirement,
            "status": status_class,
            "status_label": status_label,
            "source_rule_label": self._rule_label(item.source_rule or "-"),
            "summary": self._render_reason_text(item.status, item.reason or ""),
            "group": self._workspace_group_key(item.status),
            "evidence_targets": evidence_targets,
        }

    def _build_extra_rule_workspace_item(self, item: Any, context_payload: Dict[str, Any]) -> Dict[str, Any]:
        """构造额外检查项卡片"""
        status_label, status_class = self._display_status_meta(item.status)
        evidence_targets = self._build_evidence_targets_for_rule(
            rule_code=item.item,
            status=item.status,
            source_result=item,
            context_payload=context_payload,
            expected_doc_kind="",
        )
        return {
            "id": f"extra:{item.item}",
            "title": self._rule_label(item.item),
            "requirement": item.message,
            "status": status_class,
            "status_label": status_label,
            "source_rule_label": self._rule_label(item.item),
            "summary": item.message,
            "group": self._workspace_group_key(item.status),
            "evidence_targets": evidence_targets,
        }

    def _workspace_group_key(self, status: str) -> str:
        """工作台展示分组"""
        if status in {"warning", "manual", "requires_data"}:
            return "manual"
        if status in {"system_managed", "not_applicable", "skipped"}:
            return "not_applicable" if status != "system_managed" else "system_managed"
        if status == "failed":
            return "failed"
        return "passed"

    def _build_evidence_targets_for_rule(
        self,
        rule_code: str,
        status: str,
        source_result: Any,
        context_payload: Dict[str, Any],
        expected_doc_kind: str = "",
    ) -> List[Dict[str, Any]]:
        """把规则映射成右栏可浏览的证据目标"""
        scan_info = context_payload.get("scan_info", {}) if isinstance(context_payload, dict) else {}
        proposal_facts = scan_info.get("proposal_facts", {}) if isinstance(scan_info, dict) else {}
        preview_assets = scan_info.get("preview_assets", {}) if isinstance(scan_info, dict) else {}
        packet_assets = scan_info.get("packet_assets", {}) if isinstance(scan_info, dict) else {}
        proposal_file = (
            scan_info.get("proposal_main_file")
            or proposal_facts.get("proposal_main_file")
            or ""
        )
        proposal_excerpt = proposal_facts.get("proposal_text_excerpt", "")
        attachments = context_payload.get("attachments", []) if isinstance(context_payload, dict) else []
        targets: List[Dict[str, Any]] = []

        if not source_result:
            return targets

        if source_result.item in {"required_attachments", "conditional_attachments"}:
            if status in {"not_applicable", "system_managed"}:
                return [
                    self._build_generic_target(
                        target_id=f"{source_result.item}:{rule_code}:explanation",
                        source_file="",
                        location_label="规则说明",
                        clip=getattr(source_result, "message", "") or "当前项目未触发该条规则",
                        tab_label="规则说明",
                    )
                ]
            missing_doc_kinds = self._extract_missing_doc_kinds(source_result.evidence)
            if missing_doc_kinds:
                target_doc_kinds = [expected_doc_kind] if expected_doc_kind and expected_doc_kind in missing_doc_kinds else missing_doc_kinds
                for index, doc_kind in enumerate(target_doc_kinds, start=1):
                    matched = self._find_matching_attachment(attachments, doc_kind)
                    if matched:
                        targets.append(
                        self._build_attachment_target(
                            target_id=f"{source_result.item}:{doc_kind}:{index}",
                            attachment=matched,
                            clip=self._build_attachment_clip(matched),
                            preview_assets=preview_assets,
                            packet_assets=packet_assets,
                        )
                    )
                    else:
                        targets.append(
                            self._build_generic_target(
                                target_id=f"{source_result.item}:{doc_kind}:{index}",
                                source_file="",
                                location_label="附件目录总览",
                                clip=self._build_attachment_overview_clip(attachments),
                                tab_label=self._doc_kind_label(doc_kind),
                            )
                        )
                return targets
            if expected_doc_kind:
                matched = self._find_matching_attachment(attachments, expected_doc_kind)
                if matched:
                    return [
                        self._build_attachment_target(
                            target_id=f"{source_result.item}:{expected_doc_kind}:matched",
                            attachment=matched,
                            clip=self._build_attachment_clip(matched),
                            preview_assets=preview_assets,
                            packet_assets=packet_assets,
                        )
                    ]
            overview_clip = self._build_attachment_overview_clip(attachments)
            return [
                self._build_generic_target(
                    target_id=f"{source_result.item}:overview",
                    source_file="",
                    location_label="附件目录总览",
                    clip=overview_clip,
                    tab_label="附件总览",
                )
            ]

        if source_result.item == "external_status_check":
            return [
                self._build_generic_target(
                    target_id=f"{rule_code}:external",
                    source_file="",
                    location_label="外部校验数据",
                    clip=self._format_evidence_clip(source_result.evidence, source_result.message),
                    tab_label="外部校验",
                )
            ]

        if source_result.item in {"policy_review_points_check", "required_project_fields"}:
            return [
                self._build_generic_target(
                    target_id=f"{rule_code}:explanation",
                    source_file="",
                    location_label="规则说明",
                    clip=self._format_evidence_clip(source_result.evidence, source_result.message),
                    tab_label="规则说明",
                )
            ]

        if source_result.item == "attachment_review":
            failures = source_result.evidence.get("failures", []) if isinstance(source_result.evidence, dict) else []
            for index, failure in enumerate(failures[:6], start=1):
                if not isinstance(failure, dict):
                    continue
                attachment_id = str(failure.get("attachment_id", ""))
                matched = next((item for item in attachments if str(item.get("attachment_id", "")) == attachment_id), None)
                if matched:
                    targets.append(
                        self._build_attachment_target(
                            target_id=f"attachment_review:{index}",
                            attachment=matched,
                            clip=self._build_attachment_clip(matched),
                            preview_assets=preview_assets,
                            packet_assets=packet_assets,
                        )
                    )
            if targets:
                return targets

        clip = self._format_evidence_clip(getattr(source_result, "evidence", {}), getattr(source_result, "message", ""))
        if source_result.item == "registered_date_limit":
            clip = self._extract_keyword_snippet(proposal_excerpt, "注册时间") or clip
        elif source_result.item == "project_leader_age_check":
            clip = self._extract_keyword_snippet(proposal_excerpt, "负责人") or clip
        elif source_result.item == "funding_ratio_check":
            clip = self._extract_keyword_snippet(proposal_excerpt, "财政资金") or clip
        elif source_result.item == "performance_metric_count_check":
            clip = self._extract_keyword_snippet(proposal_excerpt, "绩效") or clip
        elif source_result.item == "budget_forbidden_expense_check":
            clip = self._extract_keyword_snippet(proposal_excerpt, "预算") or clip
        elif source_result.item == "cooperation_region_check":
            clip = self._extract_keyword_snippet(proposal_excerpt, "合作单位") or clip
        elif source_result.item == "proposal_file_presence":
            clip = self._format_evidence_clip(getattr(source_result, "evidence", {}), getattr(source_result, "message", ""))

        if proposal_file:
            targets.append(
                self._build_file_target(
                    target_id=f"{rule_code}:proposal",
                    source_file=str(proposal_file),
                    location_label="申报书主文件",
                    clip=clip,
                    tab_label="申报书",
                    page=None,
                    preview_assets=preview_assets,
                    packet_assets=packet_assets,
                )
            )
        elif clip:
            targets.append(
                self._build_generic_target(
                    target_id=f"{rule_code}:text",
                    source_file="",
                    location_label="规则证据",
                    clip=clip,
                    tab_label="规则证据",
                )
            )
        return targets

    def _policy_rule_doc_kind(self, rule_code: str) -> str:
        """政策规则对应的附件类别"""
        mapping = {
            "commitment_letter_required": "commitment_letter",
            "recommendation_letter_required": "recommendation_letter",
            "cooperation_agreement_required": "cooperation_agreement",
            "ethics_approval_required": "ethics_approval",
            "industry_permit_required": "industry_permit",
            "biosafety_commitment_required": "biosafety_commitment",
            "base_staff_proof_required": "base_staff_proof",
        }
        return mapping.get(str(rule_code or "").strip(), "")

    def _find_matching_attachment(self, attachments: List[Any], doc_kind: str) -> Dict[str, Any] | None:
        """在附件列表中查找匹配类别"""
        for item in attachments:
            if not isinstance(item, dict):
                continue
            if str(item.get("doc_kind", "")) == doc_kind:
                return item
            details = item.get("classification_details", {})
            contains = details.get("contains_doc_kinds", []) if isinstance(details, dict) else []
            if isinstance(contains, list) and doc_kind in {str(value) for value in contains}:
                return item
        return None

    def _build_attachment_target(
        self,
        target_id: str,
        attachment: Dict[str, Any],
        clip: str,
        preview_assets: Dict[str, Any],
        packet_assets: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造附件类证据目标"""
        source_file = str(attachment.get("file_ref", "") or "")
        details = attachment.get("classification_details", {})
        page = self._extract_first_page_hint(details)
        tab_label = str(attachment.get("file_name") or self._doc_kind_label(str(attachment.get("doc_kind", ""))))
        location_label = f"{self._doc_kind_label(str(attachment.get('doc_kind', '')))}"
        if page:
            location_label += f" · 第{page}页"
        return self._build_file_target(
            target_id=target_id,
            source_file=source_file,
            location_label=location_label,
            clip=clip,
            tab_label=tab_label,
            page=page,
            preview_assets=preview_assets,
            packet_assets=packet_assets,
        )

    def _build_file_target(
        self,
        target_id: str,
        source_file: str,
        location_label: str,
        clip: str,
        tab_label: str,
        page: int | None,
        preview_assets: Dict[str, Any],
        packet_assets: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造文件类证据目标"""
        path = Path(source_file) if source_file else None
        suffix = path.suffix.lower() if path and path.exists() else ""
        preview_asset = preview_assets.get(source_file, {}) if isinstance(preview_assets, dict) else {}
        open_uri = self._build_file_uri(path, page=page, for_embed=False) if path else ""
        preview_uri = ""
        preview_mode = "none"
        anchor_id = self._resolve_preview_anchor(preview_asset, clip)
        if isinstance(preview_asset, dict) and preview_asset.get("preview_file"):
            preview_uri = str(preview_asset.get("preview_file", ""))
            preview_mode = str(preview_asset.get("preview_mode", "html"))
            if anchor_id and preview_mode == "html":
                preview_uri = f"{preview_uri}#{anchor_id}"
        elif suffix == ".pdf":
            preview_mode = "pdf"
            preview_uri = self._build_file_uri(path, page=page, for_embed=True) if path else ""
        elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}:
            preview_mode = "image"
            preview_uri = self._build_file_uri(path, page=page, for_embed=True) if path else ""
        packet_page = self._resolve_packet_page(packet_assets, source_file, page)
        packet_uri = str(packet_assets.get("packet_file", "")) if isinstance(packet_assets, dict) else ""
        viewer_mode = "document" if preview_uri or open_uri else "explanation"
        return {
            "target_id": target_id,
            "tab_label": tab_label[:32],
            "source_file": source_file or "-",
            "location_label": location_label,
            "clip": clip,
            "open_uri": open_uri,
            "preview_uri": preview_uri,
            "preview_mode": preview_mode,
            "viewer_mode": viewer_mode,
            "anchor_id": anchor_id,
            "packet_uri": packet_uri,
            "packet_page": packet_page,
        }

    def _build_generic_target(
        self,
        target_id: str,
        source_file: str,
        location_label: str,
        clip: str,
        tab_label: str,
    ) -> Dict[str, Any]:
        """构造无预览证据目标"""
        return {
            "target_id": target_id,
            "tab_label": tab_label[:32],
            "source_file": source_file or "-",
            "location_label": location_label,
            "clip": clip,
            "open_uri": "",
            "preview_uri": "",
            "preview_mode": "none",
            "viewer_mode": "explanation",
            "anchor_id": "",
        }

    def _resolve_packet_page(self, packet_assets: Dict[str, Any], source_file: str, page: int | None) -> int | None:
        """把原始文件页码映射到 packet 页码"""
        if not isinstance(packet_assets, dict):
            return None
        page_map = packet_assets.get("page_map", [])
        if not isinstance(page_map, list):
            return None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            if str(item.get("source_file") or "") != str(source_file or ""):
                continue
            start_page = item.get("start_page")
            end_page = item.get("end_page")
            if not isinstance(start_page, int) or start_page <= 0:
                continue
            if isinstance(page, int) and page > 0:
                max_page = end_page if isinstance(end_page, int) and end_page >= start_page else start_page
                return min(start_page + page - 1, max_page)
            return start_page
        return None

    def _resolve_preview_anchor(self, preview_asset: Any, clip: str) -> str:
        """根据证据摘要在 docx 预览块中寻找最接近的锚点"""
        if not isinstance(preview_asset, dict):
            return ""
        blocks = preview_asset.get("blocks", [])
        if not isinstance(blocks, list) or not blocks:
            return ""
        normalized_clip = self._normalize_preview_match_text(clip)
        if not normalized_clip:
            return ""

        best_anchor = ""
        best_score = 0
        for item in blocks:
            if not isinstance(item, dict):
                continue
            anchor_id = str(item.get("anchor_id", "")).strip()
            text = self._normalize_preview_match_text(item.get("text", ""))
            if not anchor_id or not text:
                continue
            if normalized_clip in text or text in normalized_clip:
                score = min(len(normalized_clip), len(text))
            else:
                score = self._shared_substring_score(normalized_clip, text)
            if score > best_score:
                best_score = score
                best_anchor = anchor_id
        return best_anchor if best_score >= 6 else ""

    def _normalize_preview_match_text(self, value: Any) -> str:
        """归一化预览匹配文本"""
        text = str(value or "")
        text = re.sub(r"\s+", "", text)
        return text[:800]

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

    def _build_file_uri(self, path: Path | None, page: int | None = None, for_embed: bool = False) -> str:
        """构造本地文件 URI"""
        if not path or not path.exists():
            return ""
        try:
            uri = path.resolve().as_uri()
        except Exception:
            return ""
        if path.suffix.lower() == ".pdf" and page:
            return f"{uri}#page={page}"
        return uri

    def _extract_first_page_hint(self, details: Any) -> int | None:
        """从分类详情中提取首个页码提示"""
        if not isinstance(details, dict):
            return None
        refine = details.get("llm_secondary_refine", {})
        if not isinstance(refine, dict):
            return None
        page_candidates = refine.get("page_candidates", [])
        if not isinstance(page_candidates, list) or not page_candidates:
            return None
        for item in page_candidates:
            if not isinstance(item, dict):
                continue
            page = item.get("page")
            if isinstance(page, int) and page > 0:
                return page
        return None

    def _render_project_section(self, order: int, result: ProjectReviewResult, context_payload: Dict[str, Any]) -> str:
        """渲染单项目调试区块"""
        result_path = f"projects/{result.project_id}.result.json"
        context_path = f"projects/{result.project_id}.context.json"
        scan_path = f"projects/{result.project_id}.scan.json"
        rule_evidence_table = self._render_rule_evidence_table(result, context_payload)
        summary_badges = self._render_status_badges([
            ("失败", str(sum(1 for item in result.results if item.status == "failed")), "failed"),
            (
                "需人工处理",
                str(
                    sum(1 for item in result.results if item.status in {"warning", "requires_data"})
                    + len(result.manual_review_items)
                ),
                "manual",
            ),
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
      <section class="panel" style="grid-column: 1 / -1;">
        <h3>形式审查要点对照结果</h3>
        {policy_rules_table}
      </section>
    </div>
    <div class="section-grid">
      <section class="panel" style="grid-column: 1 / -1;">
        <h3>额外检查项</h3>
        {project_rules_table}
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
        """渲染额外检查项结果表"""
        covered_rules = {
            item.code for item in result.policy_rule_checks if getattr(item, "code", None)
        } | {
            item.source_rule for item in result.policy_rule_checks if getattr(item, "source_rule", None)
        }
        rows = []
        for item in result.results:
            if item.item in covered_rules:
                continue
            rows.append(
                "<tr>"
                "<td class='left-block'>"
                f"<div class='extra-title'>{escape(self._rule_label(item.item))}</div>"
                f"<div class='extra-message'>{escape(item.message)}</div>"
                "</td>"
                "<td class='right-block'>"
                "<div class='extra-result'>"
                f"<div class='label'>状态</div><div>{self._render_status_badge(item.status)}</div>"
                f"<div class='label'>证据</div><div><pre class='mono'>{escape(self._format_evidence_for_table(item.evidence))}</pre></div>"
                "</div>"
                "</td>"
                "</tr>"
            )
        if not rows:
            return "<div class='empty'>无额外检查项</div>"
        return (
            "<table class='extra-table'><thead>"
            "<tr><th class='group-left'>额外检查项</th><th class='group-right'>检查结果</th></tr>"
            "</thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    def _format_evidence_for_table(self, evidence: Any) -> str:
        """项目级规则 evidence 可读化（多行）"""
        if evidence is None:
            return "-"
        if isinstance(evidence, (dict, list)):
            return self._format_evidence_clip(evidence)
        if isinstance(evidence, str):
            text = evidence.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    parsed = json.loads(text)
                    return self._format_evidence_clip(parsed)
                except Exception:
                    try:
                        parsed = ast.literal_eval(text)
                        if isinstance(parsed, (dict, list)):
                            return self._format_evidence_clip(parsed)
                    except Exception:
                        pass
            return text
        return str(evidence)

    def _render_policy_rule_checks_table(self, result: ProjectReviewResult) -> str:
        """渲染 docx 逐条规则对照表"""
        primary_groups: Dict[str, Dict[str, Any]] = {}
        folded_groups: Dict[str, Dict[str, Any]] = {}
        for item in result.policy_rule_checks:
            display_label, display_class = self._display_status_meta(item.status)
            row_html = (
                "<tr>"
                "<td class='left-block'>"
                f"<div class='policy-point'>{escape(self._rule_label(item.code))}</div>"
                f"<div class='policy-req'>{escape(item.requirement)}</div>"
                "</td>"
                "<td class='right-block'>"
                "<div class='policy-result'>"
                f"<div class='label'>状态</div><div>{self._render_status_badge(item.status)}</div>"
                f"<div class='label'>核验来源</div><div>{escape(self._rule_label(item.source_rule or '-'))}</div>"
                f"<div class='label'>说明</div><div>{escape(self._render_reason_text(item.status, item.reason))}</div>"
                "</div>"
                "</td>"
                "</tr>"
            )
            if item.status in {"system_managed", "not_applicable"}:
                if item.status not in folded_groups:
                    folded_groups[item.status] = {
                        "label": display_label,
                        "class": display_class,
                        "rows": [],
                    }
                folded_groups[item.status]["rows"].append(row_html)
            else:
                group_key = display_class
                if group_key not in primary_groups:
                    primary_groups[group_key] = {
                        "label": display_label,
                        "class": display_class,
                        "rows": [],
                    }
                primary_groups[group_key]["rows"].append(row_html)
        if not primary_groups and not folded_groups:
            return "<div class='empty'>无 docx 逐条规则结果</div>"

        def render_grouped_tables(groups: Dict[str, Dict[str, Any]], order: List[str]) -> str:
            rendered = []
            for key in order:
                group = groups.get(key)
                if not group:
                    continue
                rows = group["rows"]
                rendered.append(
                    "<section class='status-group'>"
                    "<div class='status-group-head'>"
                    f"{self._render_status_badge(key)}"
                    f"<span class='status-group-count'>{len(rows)} 项</span>"
                    "</div>"
                    "<table class='policy-table'><thead>"
                    "<tr><th class='group-left'>审查点与要求</th><th class='group-right'>审查结果</th></tr>"
                    "</thead><tbody>"
                    + "".join(rows)
                    + "</tbody></table>"
                    "</section>"
                )
            for key, group in groups.items():
                if key in order:
                    continue
                rows = group["rows"]
                rendered.append(
                    "<section class='status-group'>"
                    "<div class='status-group-head'>"
                    f"{self._render_status_badge(key)}"
                    f"<span class='status-group-count'>{len(rows)} 项</span>"
                    "</div>"
                    "<table class='policy-table'><thead>"
                    "<tr><th class='group-left'>审查点与要求</th><th class='group-right'>审查结果</th></tr>"
                    "</thead><tbody>"
                    + "".join(rows)
                    + "</tbody></table>"
                    "</section>"
                )
            return "".join(rendered)

        sections = []
        if primary_groups:
            sections.append(render_grouped_tables(primary_groups, ["failed", "manual", "passed", "skipped"]))
        else:
            sections.append("<div class='empty'>主要审查结果中无需要展示的项目</div>")
        if folded_groups:
            sections.append(
                "<details class='inline-toggle'>"
                f"<summary>系统前置限制 / 不适用（{sum(len(group['rows']) for group in folded_groups.values())} 项）</summary>"
                "<div class='inline-toggle-body'>"
                + render_grouped_tables(folded_groups, ["system_managed", "not_applicable"])
                + "</div></details>"
            )
        return "".join(sections)

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
                            "rule": f"{self._rule_label(rule_item.item)}:{self._doc_kind_with_code(doc_kind)}",
                            "status": rule_item.status,
                            "source_file": source_file,
                            "clip": clip,
                        }
                    )
                continue
            if rule_item.item == "external_status_check":
                items.append(
                    {
                        "rule": self._rule_label(rule_item.item),
                        "status": rule_item.status,
                        "source_file": "外部校验数据源（当前未接入）",
                        "clip": self._format_evidence_clip(rule_item.evidence, rule_item.message),
                    }
                )
                continue
            items.append(
                {
                    "rule": self._rule_label(rule_item.item),
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
                    code = self._rule_label(str(point.get("code", "")).strip() or "-")
                    requirement = str(point.get("requirement", "")).strip() or "-"
                    reason = str(point.get("reason", "")).strip() or "-"
                    lines.append(f"{index}. {code}")
                    lines.append(f"   要求: {requirement}")
                    lines.append(f"   原因: {reason}")
                if not lines:
                    return fallback_message or "待补核验点为空"
                return "待补核验点：\n" + "\n".join(lines)
            if isinstance(evidence.get("required_fields"), list):
                fields = [self.FIELD_LABELS.get(str(item), str(item)) for item in evidence["required_fields"] if item]
                if fields:
                    return "已核验字段：\n" + "\n".join(f"- {field}" for field in fields)
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
            if isinstance(evidence.get("forbidden_hits"), list):
                lines = []
                for item in evidence["forbidden_hits"][:8]:
                    if isinstance(item, dict):
                        term = str(item.get("term", "-")).strip()
                        line = str(item.get("line", "-")).strip()
                        lines.append(f"- 命中词: {term}")
                        lines.append(f"  预算行: {line}")
                if lines:
                    return "预算禁列项命中：\n" + "\n".join(lines)
            if isinstance(evidence.get("sample_budget_lines"), list):
                lines = [str(item).strip() for item in evidence["sample_budget_lines"][:6] if str(item).strip()]
                if lines:
                    return "已检查预算行示例：\n" + "\n".join(f"- {line}" for line in lines)
            if isinstance(evidence.get("performance_metric_rows"), list):
                metric_lines = []
                for item in evidence["performance_metric_rows"][:8]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("metric_name", "-")).strip()
                    total_value = item.get("total_value", "-")
                    first_year_value = item.get("first_year_value", "-")
                    metric_lines.append(f"- {name}: 总体={total_value}，第一年={first_year_value}")
                prefix = []
                if isinstance(evidence.get("performance_metric_count"), (int, float)):
                    prefix.append(f"绩效指标数量: {evidence['performance_metric_count']}")
                ratio = evidence.get("performance_first_year_ratio")
                if isinstance(ratio, (int, float)):
                    prefix.append(f"第一年度目标占比: {ratio:.2%}")
                if metric_lines:
                    return "\n".join(prefix + ["已识别绩效指标："] + metric_lines)
            if isinstance(evidence.get("required_ratio"), (int, float)):
                ratio_lines = [
                    f"财政资金: {evidence.get('fiscal_funding', '-')}",
                    f"自筹资金: {evidence.get('self_funding', '-')}",
                    f"要求比例: {float(evidence['required_ratio']):.2f}",
                ]
                if isinstance(evidence.get("actual_ratio"), (int, float)):
                    ratio_lines.append(f"实际比例: {float(evidence['actual_ratio']):.2f}")
                applicant_unit_type = evidence.get("applicant_unit_type")
                if applicant_unit_type:
                    ratio_lines.append(f"申报单位类型: {applicant_unit_type}")
                cooperation_types = evidence.get("cooperation_unit_types")
                if isinstance(cooperation_types, list) and cooperation_types:
                    ratio_lines.append("合作单位类型: " + "、".join(str(item) for item in cooperation_types))
                return "\n".join(ratio_lines)
            lines = []
            for key, value in evidence.items():
                if isinstance(value, (str, int, float, bool)):
                    label = self.FIELD_LABELS.get(key, self._rule_label(key))
                    lines.append(f"{label}: {value}")
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
        doc_kind = str(attachment.get("doc_kind", ""))
        secondary_hits = self._format_secondary_refine_hits(details) if doc_kind == "other_supporting_material" else ""
        return (
            f"file_name={attachment.get('file_name', '')}\n"
            f"doc_kind={self._doc_kind_with_code(doc_kind)}\n"
            f"classification_source={attachment.get('classification_source', '')}\n"
            f"clues={clues}"
            + (f"\n{secondary_hits}" if secondary_hits else "")
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
            details = item.get("classification_details", {})
            secondary_hits = (
                self._format_secondary_refine_hits_inline(details)
                if kind == "other_supporting_material"
                else ""
            )
            file_name = str(item.get("file_name", ""))
            chunk = [
                f"[{index}] 文件: {file_name}",
                f"    主分类: {self._doc_kind_with_code(kind)}",
            ]
            if secondary_hits:
                chunk.append(f"    {secondary_hits}")
            chunk.append("")
            lines.extend(chunk)
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
        """附件类别中文标签"""
        label = self._doc_kind_label(doc_kind)
        return label

    def _format_contains_doc_kinds(self, attachment: Dict[str, Any]) -> str:
        """格式化单文件包含的多类别"""
        details = attachment.get("classification_details", {})
        if not isinstance(details, dict):
            return "-"
        values = details.get("contains_doc_kinds", [])
        if not isinstance(values, list) or not values:
            return "-"
        return "、".join(self._doc_kind_with_code(str(item)) for item in values if str(item).strip())

    def _rule_label(self, rule_code: str) -> str:
        """规则编码转中文标签"""
        text = str(rule_code or "").strip()
        if not text or text == "-":
            return "-"
        return self.RULE_LABELS.get(text, text)

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
        """格式化二次复核页命中详情（多行简版）"""
        if not isinstance(details, dict):
            return "二次复核页命中: 无"
        refine = details.get("llm_secondary_refine", {})
        if not isinstance(refine, dict):
            return "二次复核页命中: 无"
        page_candidates = refine.get("page_candidates", [])
        if not isinstance(page_candidates, list) or not page_candidates:
            return "二次复核页命中: 无"
        lines: List[str] = []
        for item in page_candidates[:3]:
            if not isinstance(item, dict):
                continue
            page = item.get("page", "-")
            doc_kind = self._doc_kind_label(str(item.get("doc_kind", "")))
            confidence = item.get("confidence", "-")
            lines.append(f"      - 第{page}页 -> {doc_kind} @ {confidence}")
        if not lines:
            return "二次复核页命中: 无"
        return "二次复核页命中:\n" + "\n".join(lines)

    def _render_simple_list(self, values: List[str]) -> str:
        """渲染简单列表"""
        if not values:
            return "<div class='empty'>无</div>"
        return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"

    def _render_status_badges(self, values: List[tuple[str, str, str]]) -> str:
        """渲染一组状态标签"""
        badges = []
        for label, value, status in values:
            text = str(value).strip()
            if text in {"0", "0.0", ""}:
                continue
            _, css_class = self._display_status_meta(status)
            badges.append(f"<span class='badge status-{escape(css_class)}'>{escape(label)} {escape(text)}</span>")
        return "".join(badges)

    def _render_status_badge(self, status: str) -> str:
        """渲染状态标签"""
        label, css_class = self._display_status_meta(status)
        return f"<span class='badge status-{escape(css_class)}'>{escape(label)}</span>"

    def _display_status_meta(self, status: str) -> tuple[str, str]:
        """对外展示状态与样式类"""
        if status in {"warning", "manual", "requires_data"}:
            return "需人工处理", "manual"
        labels = {
            "passed": "通过",
            "failed": "不通过",
            "not_applicable": "不适用",
            "system_managed": "系统已限制",
            "skipped": "跳过",
        }
        return labels.get(status, status), status

    def _render_reason_text(self, status: str, reason: str) -> str:
        """统一说明文案前缀，避免同类状态出现多套口径"""
        text = (reason or "").strip()
        if status in {"warning", "manual", "requires_data"} and text:
            return f"需人工处理：{text}"
        return text
