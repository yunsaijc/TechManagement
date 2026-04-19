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
from src.services.review.doc_types import doc_type_to_legacy_doc_kind, get_doc_type_label, normalize_doc_type
from src.services.review.notice_rules import build_notice_context
from src.services.review.project_agent import ProjectReviewAgent
from src.services.review.project_context_builder import ProjectContextBuilder
from src.services.review.project_index_repo import ProjectIndexRepository


class BatchReviewAgent:
    """批次级形式审查 Agent"""
    PROJECT_TYPE_LABELS = {
        "regional_innovation": "区域创新体系建设项目",
        "innovation_base": "科技创新基地项目",
        "achievement_transformation": "科技成果转移转化项目",
        "basic_research": "基础研究项目",
        "unknown": "未识别项目类型",
    }
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
            report_url=f"/debug-review/{batch_id}/index.html",
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
        failed_count = sum(
            1
            for result in project_results
            if any(item.status in {"failed", "warning"} for item in result.results) or result.manual_review_items
        )
        project_count = len(project_results)
        suggestion_items = "".join(
            f"<span class='batch-note'>{escape(item)}</span>" for item in suggestions
        ) or "<span class='batch-note'>无额外提示</span>"
        batch_badges = self._render_status_badges(
            [
                ("需关注", str(failed_count), "failed"),
                ("项目数", str(project_count), "passed"),
            ]
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
      height: 100vh;
      overflow: hidden;
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
    .hero, .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
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
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .hero-stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    .batch-notes {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .batch-note {{
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
    a {{
      color: #175cd3;
      text-decoration: none;
    }}
    .workspace {{
      display: grid;
      grid-template-columns: 260px minmax(0, 1.9fr) minmax(320px, 0.95fr);
      gap: 18px;
      align-items: stretch;
      min-width: 0;
      min-height: 0;
      height: 100%;
      overflow: hidden;
    }}
    .sidebar, .center-panel, .viewer-panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      min-width: 0;
      max-width: 100%;
      box-sizing: border-box;
      height: 100%;
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
      box-sizing: border-box;
      min-width: 0;
      max-width: 100%;
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
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .rule-card-requirement {{
      color: var(--text);
      font-size: 13px;
      line-height: 1.7;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .rule-card-meta {{
      display: grid;
      grid-template-columns: 72px 1fr;
      gap: 6px 10px;
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
      min-width: 0;
    }}
    .rule-card-meta-label {{
      color: var(--muted);
    }}
    .rule-card-meta > div {{
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .center-panel {{
      padding: 18px 18px 16px;
      overflow: hidden;
    }}
    .viewer-panel {{
      padding: 18px 18px 20px;
    }}
    #pdfPanel {{
      flex: 1 1 auto;
      min-height: 0;
      height: 100%;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    #rulesPanel {{
      min-width: 0;
      max-width: 100%;
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      padding-right: 2px;
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
      margin-bottom: 10px;
    }}
    .viewer-meta-label {{
      color: var(--muted);
    }}
    .viewer-preview {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #f8fafc;
      min-height: 0;
      height: 100%;
      flex: 1 1 auto;
      overflow: hidden;
      display: flex;
      align-items: stretch;
      justify-content: center;
    }}
    .viewer-preview iframe {{
      width: 100%;
      height: 100%;
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
      padding: 12px 14px;
    }}
    .viewer-layout {{
      display: flex;
      flex-direction: column;
      gap: 0;
      height: 100%;
      min-height: 0;
    }}
    .pdf-only {{
      display: flex;
      flex-direction: column;
      position: relative;
      flex: 1 1 auto;
      min-height: 0;
    }}
    .viewer-preview.hidden,
    .viewer-fallback.hidden,
    .clip-panel.hidden,
    .evidence-tabs.hidden,
    .viewer-meta.hidden {{
      display: none;
    }}
    .viewer-aux {{
      margin-top: 12px;
    }}
    .packet-frame {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #fff;
    }}
    .pdf-toast {{
      position: absolute;
      top: 14px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 4;
      max-width: min(520px, calc(100% - 48px));
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(15, 118, 110, 0.28);
      background: rgba(240, 253, 250, 0.96);
      color: #115e59;
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.14);
      font-size: 13px;
      line-height: 1.4;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
    }}
    .pdf-toast.show {{
      opacity: 1;
      transform: translateX(-50%) translateY(4px);
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
        grid-template-columns: 240px minmax(0, 1.45fr) minmax(320px, 0.9fr);
      }}
    }}
    @media (max-width: 1080px) {{
      body {{
        height: auto;
        overflow: auto;
      }}
      .page {{
        height: auto;
        overflow: visible;
      }}
      .workspace {{
        grid-template-columns: 1fr;
        height: auto;
        overflow: visible;
      }}
      .sidebar, .center-panel, .viewer-panel {{
        height: auto;
        min-height: auto;
        overflow: visible;
      }}
      .project-list {{
        flex: initial;
        min-height: auto;
        max-height: none;
        overflow: visible;
      }}
      #rulesPanel {{
        overflow: visible;
        min-height: auto;
      }}
      #pdfPanel {{
        height: auto;
        min-height: 480px;
        overflow: visible;
      }}
      .viewer-layout, .pdf-only, .viewer-preview {{
        height: auto;
        min-height: 480px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-main">
        <h1>批次审查工作台</h1>
        <div class="hero-meta">
          <p>批次：<span class="mono">{escape(batch_id)}</span></p>
          <p>zxmc：<span class="mono">{escape(request.zxmc)}</span></p>
        </div>
      </div>
      <div class="hero-stats">{batch_badges}</div>
      <div class="batch-notes">{suggestion_items}</div>
    </section>
    <section class="workspace">
      <aside class="sidebar">
        <div class="sidebar-head">
          <h2 class="sidebar-title">项目列表</h2>
        </div>
        <div class="project-list" id="projectList"></div>
      </aside>
      <main class="center-panel">
        <div id="pdfPanel"></div>
      </main>
      <aside class="viewer-panel">
        <div id="rulesPanel"></div>
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
          <div class="project-item-meta">${{escapeHtml(project.project_id)}} · ${{escapeHtml(project.project_type_label || project.project_type)}}</div>
          <div class="project-item-stats">
            ${{statusBadge("failed", `失败 ${{project.counts.failed}}`)}}
            ${{statusBadge("manual", `需人工 ${{project.counts.manual}}`)}}
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
      state.ruleId = findPreferredRuleId(project) || project.default_rule_id || findFirstRuleId(project) || "";
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

    function hasNavigableEvidence(item) {{
      const targets = item?.evidence_targets || [];
      return targets.some((target) => Number(target?.packet_page || 0) > 0);
    }}

    function findPreferredRuleId(project) {{
      const sections = [...project.policy_sections, ...project.extra_sections];
      for (const preferredStatus of ["failed", "manual", "passed"]) {{
        for (const section of sections) {{
          for (const group of section.groups) {{
            for (const item of (group.items || [])) {{
              if (String(item.status || "") === preferredStatus && hasNavigableEvidence(item)) {{
                return item.id;
              }}
            }}
          }}
        }}
      }}
      for (const section of sections) {{
        for (const group of section.groups) {{
          for (const item of (group.items || [])) {{
            if (hasNavigableEvidence(item)) {{
              return item.id;
            }}
          }}
        }}
      }}
      return "";
    }}

    function selectRule(ruleId) {{
      state.ruleId = ruleId;
      state.evidenceIndex = 0;
      renderRulesPanel();
      renderPdfPanel();
    }}

    function selectEvidence(index) {{
      state.evidenceIndex = index;
      renderPdfPanel();
    }}

    function renderRulesPanel() {{
      const project = REPORT_DATA.projects[state.projectIndex];
      const panel = document.getElementById("rulesPanel");
      if (!project) {{
        panel.innerHTML = '<div class="empty">无项目</div>';
        return;
      }}
      panel.innerHTML = `
        <div class="panel-head">
          <h2>${{escapeHtml(project.project_name || project.project_id)}}</h2>
          <div class="project-summary">${{escapeHtml(project.project_type_label || project.project_type)}} · ${{statusBadge("failed", `失败 ${{project.counts.failed}}`)}} ${{statusBadge("manual", `需人工 ${{project.counts.manual}}`)}}</div>
        </div>
        <div class="result-sections">
          ${{renderSections(project.policy_sections, "审查要点对照")}}
          ${{renderSections(project.extra_sections, "额外检查项")}}
        </div>
      `;
      panel.querySelectorAll(".rule-card").forEach((node) => {{
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

    function ensurePdfShell() {{
      const viewer = document.getElementById("pdfPanel");
      if (!viewer) {{
        return null;
      }}
      if (!viewer.dataset.initialized) {{
        viewer.innerHTML = `
          <div class="pdf-only">
            <div class="pdf-toast" id="pdfToast"></div>
            <div class="viewer-preview hidden" id="viewerPreview">
              <iframe class="packet-frame" id="packetFrame" title="review packet viewer"></iframe>
            </div>
            <div class="viewer-fallback" id="viewerFallback">选择一条规则后，在这里查看对应材料。</div>
          </div>
        `;
        viewer.dataset.initialized = "1";
      }}
      return viewer;
    }}

    function showPdfToast(message) {{
      const toast = document.getElementById("pdfToast");
      if (!toast) {{
        return;
      }}
      if (toast.dataset.timerId) {{
        clearTimeout(Number(toast.dataset.timerId));
      }}
      toast.textContent = String(message || "");
      toast.classList.add("show");
      const timerId = window.setTimeout(() => {{
        toast.classList.remove("show");
        toast.textContent = "";
        toast.dataset.timerId = "";
      }}, 1800);
      toast.dataset.timerId = String(timerId);
    }}

    function buildViewerPayload(target, packetPage) {{
      return {{
        type: "gotoPacketTarget",
        page: Number(packetPage || 0),
        location_label: String(target.location_label || ""),
        highlight_mode: String(target.highlight_mode || "none"),
        highlight_text: String(target.highlight_text || target.clip || ""),
        highlight_rects: Array.isArray(target.highlight_rects) ? target.highlight_rects : [],
      }};
    }}

    function postViewerPayload(frame, payload) {{
      const pageNumber = Number(payload?.page || 0);
      if (!frame || !pageNumber) {{
        return;
      }}
      const send = () => {{
        try {{
          frame.contentWindow?.postMessage(payload, "*");
        }} catch (error) {{
          console.warn("viewer postMessage failed", error);
        }}
      }};
      window.setTimeout(send, 0);
      window.setTimeout(send, 120);
      window.setTimeout(send, 320);
    }}

    function setViewerPacket(viewerUri, payload) {{
      const frame = document.getElementById("packetFrame");
      if (!frame) {{
        return;
      }}
      const nextUri = String(viewerUri || "");
      const pageNumber = Number(payload?.page || 0);
      if (!nextUri) {{
        frame.removeAttribute("src");
        frame.dataset.viewerUri = "";
        frame.dataset.pendingPayload = "";
        return;
      }}
      if (frame.dataset.viewerUri !== nextUri) {{
        frame.dataset.viewerUri = nextUri;
        frame.dataset.pendingPayload = JSON.stringify(payload || {{}});
        frame.onload = () => {{
          const pendingPayload = frame.dataset.pendingPayload ? JSON.parse(frame.dataset.pendingPayload) : null;
          if (pendingPayload && Number(pendingPayload.page || 0) > 0) {{
            postViewerPayload(frame, pendingPayload);
          }}
        }};
        frame.src = nextUri;
        return;
      }}
      if (pageNumber > 0) {{
        frame.dataset.pendingPayload = JSON.stringify(payload || {{}});
        postViewerPayload(frame, payload);
      }}
    }}

    function renderPdfPanel() {{
      const project = REPORT_DATA.projects[state.projectIndex];
      const viewer = ensurePdfShell();
      if (!project) {{
        if (viewer) {{
          viewer.innerHTML = '<div class="viewer-empty">无项目。</div>';
          delete viewer.dataset.initialized;
        }}
        return;
      }}
      const previewNode = document.getElementById("viewerPreview");
      const fallbackNode = document.getElementById("viewerFallback");
      const rule = getActiveRule(project);
      const packet = project.packet || {{}};
      if (!rule) {{
        if (previewNode) previewNode.classList.add("hidden");
        if (fallbackNode) {{
          fallbackNode.textContent = "选择一条规则后，在这里查看对应材料。";
          fallbackNode.classList.remove("hidden");
        }}
        const viewerUri = packet.viewer_file ? String(packet.viewer_file) : "";
        const defaultPage = Number(packet.default_page || 1);
        if (viewerUri && defaultPage > 0) {{
          if (previewNode) previewNode.classList.remove("hidden");
          if (fallbackNode) fallbackNode.classList.add("hidden");
          setViewerPacket(viewerUri, {{
            type: "gotoPacketTarget",
            page: defaultPage,
            location_label: "项目材料",
            highlight_mode: "none",
            highlight_text: "",
            highlight_rects: [],
          }});
          return;
        }}
        setViewerPacket("", null);
        return;
      }}
      const targets = rule.evidence_targets || [];
      const activeIndex = Math.max(0, Math.min(state.evidenceIndex, targets.length - 1));
      const target = targets[activeIndex] || null;
      if (!target) {{
        const viewerUri = packet.viewer_file ? String(packet.viewer_file) : "";
        const defaultPage = Number(packet.default_page || 1);
        if (viewerUri && defaultPage > 0) {{
          if (previewNode) previewNode.classList.remove("hidden");
          if (fallbackNode) fallbackNode.classList.add("hidden");
          setViewerPacket(viewerUri, {{
            type: "gotoPacketTarget",
            page: defaultPage,
            location_label: "项目材料",
            highlight_mode: "none",
            highlight_text: "",
            highlight_rects: [],
          }});
          showPdfToast("当前规则暂无可定位材料，已切到该项目材料首页。");
        }} else {{
          if (previewNode) previewNode.classList.add("hidden");
          if (fallbackNode) {{
            fallbackNode.textContent = "当前规则暂无可定位材料。";
            fallbackNode.classList.remove("hidden");
          }}
          setViewerPacket("", null);
        }}
      }} else {{
        renderEvidenceTarget(target, project);
      }}
    }}

    function renderEvidenceTarget(target, project) {{
      const packet = project.packet || {{}};
      const packetPage = target.packet_page ? Number(target.packet_page) : 0;
      const viewerUri = packet.viewer_file
        ? String(packet.viewer_file)
        : "";
      const previewNode = document.getElementById("viewerPreview");
      const fallbackNode = document.getElementById("viewerFallback");
      renderPreview(target, viewerUri, buildViewerPayload(target, packetPage), previewNode, fallbackNode);
    }}

    function renderPreview(target, viewerUri, viewerPayload, previewNode, fallbackNode) {{
      if (viewerUri && Number(viewerPayload?.page || 0) > 0) {{
        if (previewNode) previewNode.classList.remove("hidden");
        if (fallbackNode) fallbackNode.classList.add("hidden");
        setViewerPacket(viewerUri, viewerPayload);
        return;
      }}
      if (!fallbackNode) return;
      if (target.viewer_mode === "explanation") {{
        const hasOpenPacket = !!document.getElementById("packetFrame")?.dataset.viewerUri;
        if (hasOpenPacket) {{
          if (previewNode) previewNode.classList.remove("hidden");
          if (fallbackNode) fallbackNode.classList.add("hidden");
          showPdfToast("这条规则没有对应的可定位原文页面。");
          return;
        }}
        if (previewNode) previewNode.classList.add("hidden");
        setViewerPacket("", null);
        fallbackNode.textContent = "这条规则没有对应的可定位原文页面。";
        fallbackNode.classList.remove("hidden");
        return;
      }}
      if (target.open_uri) {{
        if (previewNode) previewNode.classList.add("hidden");
        setViewerPacket("", null);
        fallbackNode.textContent = "当前材料暂不可在右侧预览。";
        fallbackNode.classList.remove("hidden");
        return;
      }}
      if (previewNode && document.getElementById("packetFrame")?.dataset.viewerUri) {{
        previewNode.classList.remove("hidden");
        fallbackNode.classList.add("hidden");
        return;
      }}
      if (previewNode) previewNode.classList.add("hidden");
      setViewerPacket("", null);
      fallbackNode.textContent = "当前证据没有可用预览资产。";
      fallbackNode.classList.remove("hidden");
    }}

    function renderAll() {{
      renderProjectList();
      renderRulesPanel();
      renderPdfPanel();
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
            "block_count": len(paragraphs),
            "blocks": self._build_preview_blocks(paragraphs),
        }

    def _build_preview_blocks(self, paragraphs: List[str]) -> List[Dict[str, Any]]:
        """为 docx 预览块补充累计字符位置，供页码估算使用"""
        blocks: List[Dict[str, Any]] = []
        char_end = 0
        for index, paragraph in enumerate(paragraphs, start=1):
            paragraph_text = str(paragraph or "")
            char_end += len(paragraph_text)
            blocks.append(
                {
                    "anchor_id": f"p-{index}",
                    "text": paragraph_text,
                    "char_count": len(paragraph_text),
                    "char_end": char_end,
                }
            )
        return blocks

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
                    "doc_type": normalize_doc_type(str(item.get("doc_type") or item.get("doc_kind") or "")),
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
                    "doc_type": normalize_doc_type(str(item.get("doc_type") or item.get("doc_kind") or "")),
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
        viewer_assets = self._write_packet_viewer_assets(
            debug_writer=debug_writer,
            project_id=project_id,
            packet_bytes=packet_bytes,
        )
        return {
            "packet_file": packet_file,
            "packet_abs_path": str((Path(debug_writer.output_dir) / packet_file).resolve()),
            "page_map_file": page_map_file,
            "page_map": page_map,
            "source_items": source_items,
            "default_page": 1,
            "viewer_file": viewer_assets.get("viewer_file", ""),
            "page_images": viewer_assets.get("page_images", []),
        }

    def _write_packet_viewer_assets(
        self,
        debug_writer: ReviewDebugWriter,
        project_id: str,
        packet_bytes: bytes,
    ) -> Dict[str, Any]:
        """为 packet 生成可滚动页面 viewer 资产"""
        if not packet_bytes:
            return {}
        try:
            packet_doc = fitz.open(stream=packet_bytes, filetype="pdf")
        except Exception:
            return {}

        page_images: List[Dict[str, Any]] = []
        try:
            for page_index in range(packet_doc.page_count):
                page = packet_doc.load_page(page_index)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                image_rel_path = f"projects/{project_id}/packet_pages/page-{page_index + 1:04d}.png"
                debug_writer.write_bytes(image_rel_path, pix.tobytes("png"))
                page_images.append(
                    {
                        "page": page_index + 1,
                        "image_file": image_rel_path,
                        "width": pix.width,
                        "height": pix.height,
                    }
                )
        finally:
            packet_doc.close()

        viewer_file = f"projects/{project_id}/packet_viewer.html"
        viewer_html = self._build_packet_viewer_html(
            title=f"{project_id} 审查材料",
            page_images=page_images,
        )
        debug_writer.write_text(viewer_file, viewer_html)
        return {
            "viewer_file": viewer_file,
            "page_images": page_images,
        }

    def _build_packet_viewer_html(self, title: str, page_images: List[Dict[str, Any]]) -> str:
        """构造 packet 页面 viewer HTML"""
        pages_html = []
        for item in page_images:
            if not isinstance(item, dict):
                continue
            page = int(item.get("page", 0) or 0)
            image_file = str(item.get("image_file", "")).strip()
            if not page or not image_file:
                continue
            image_src = f"packet_pages/{Path(image_file).name}"
            pages_html.append(
                "<section class='packet-page' "
                f"id='packet-page-{page}' data-page='{page}'>"
                f"<div class='page-index'>第 {page} 页</div>"
                f"<img loading='lazy' src='{escape(image_src)}' alt='packet page {page}'>"
                "</section>"
            )
        pages_content = "".join(pages_html) or "<div class='empty'>当前材料暂无可预览页面。</div>"
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #dfe5ec;
      --panel: #f3f6fa;
      --page-bg: #ffffff;
      --line: #c8d2de;
      --text: #182230;
      --muted: #5f6b7a;
      --accent: #0f766e;
    }}
    * {{
      box-sizing: border-box;
    }}
    html, body {{
      margin: 0;
      height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    body {{
      overflow-y: auto;
    }}
    .viewer-root {{
      min-height: 100%;
      padding: 18px 0 28px;
    }}
    .viewer-head {{
      display: flex;
      justify-content: center;
      padding: 0 12px 12px;
    }}
    .head-stack {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      max-width: min(900px, calc(100vw - 48px));
    }}
    .page-pill {{
      min-width: 110px;
      text-align: center;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(15, 118, 110, 0.18);
      background: rgba(255, 255, 255, 0.92);
      color: #115e59;
      font-size: 12px;
      font-weight: 700;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
      backdrop-filter: blur(10px);
    }}
    .focus-card {{
      display: none;
      width: min(900px, calc(100vw - 48px));
      padding: 10px 14px;
      border-radius: 16px;
      border: 1px solid rgba(15, 118, 110, 0.2);
      background: rgba(255, 255, 255, 0.94);
      color: var(--text);
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
    }}
    .focus-card.show {{
      display: block;
    }}
    .focus-label {{
      font-size: 12px;
      font-weight: 800;
      color: #0f766e;
      margin-bottom: 4px;
    }}
    .focus-text {{
      font-size: 12px;
      line-height: 1.55;
      color: var(--muted);
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    .pages {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 18px;
      padding: 0 18px;
    }}
    .packet-page {{
      position: relative;
      width: min(1120px, calc(100vw - 72px));
      background: var(--page-bg);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12);
      transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
    }}
    .packet-page.active {{
      border-color: rgba(15, 118, 110, 0.36);
      box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12), 0 18px 48px rgba(15, 23, 42, 0.12);
    }}
    .page-index {{
      padding: 9px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .packet-page img {{
      width: 100%;
      height: auto;
      display: block;
      background: #fff;
    }}
    .highlight-layer {{
      position: absolute;
      inset: 33px 0 0 0;
      pointer-events: none;
    }}
    .highlight-rect {{
      position: absolute;
      border-radius: 10px;
      background: rgba(251, 191, 36, 0.22);
      border: 3px solid rgba(245, 158, 11, 0.92);
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.75), 0 10px 24px rgba(245, 158, 11, 0.22);
    }}
    .empty {{
      padding: 32px;
      color: var(--muted);
      text-align: center;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="viewer-root">
    <div class="viewer-head">
      <div class="head-stack">
        <div class="page-pill" id="pagePill">第 1 页</div>
        <div class="focus-card" id="focusCard">
          <div class="focus-label" id="focusLabel">命中定位</div>
          <div class="focus-text" id="focusText"></div>
        </div>
      </div>
    </div>
    <div class="pages" id="pages">{pages_content}</div>
  </div>
  <script>
    const pagePill = document.getElementById("pagePill");
    const focusCard = document.getElementById("focusCard");
    const focusLabel = document.getElementById("focusLabel");
    const focusText = document.getElementById("focusText");
    let activePage = 1;

    function setActivePage(page) {{
      const pageNumber = Number(page || 1);
      activePage = pageNumber;
      document.querySelectorAll(".packet-page.active").forEach((node) => node.classList.remove("active"));
      const target = document.getElementById(`packet-page-${{pageNumber}}`);
      if (target) {{
        target.classList.add("active");
      }}
      if (pagePill) {{
        pagePill.textContent = `第 ${{pageNumber}} 页`;
      }}
    }}

    function gotoPage(page, smooth) {{
      const pageNumber = Number(page || 1);
      const target = document.getElementById(`packet-page-${{pageNumber}}`);
      if (!target) return;
      setActivePage(pageNumber);
      target.scrollIntoView({{ behavior: smooth ? "smooth" : "auto", block: "start" }});
    }}

    function clearHighlights() {{
      document.querySelectorAll(".highlight-layer").forEach((node) => node.remove());
    }}

    function applyHighlights(page, rects) {{
      clearHighlights();
      const pageNumber = Number(page || 0);
      const target = document.getElementById(`packet-page-${{pageNumber}}`);
      if (!target || !Array.isArray(rects) || !rects.length) {{
        return;
      }}
      const layer = document.createElement("div");
      layer.className = "highlight-layer";
      rects.forEach((item) => {{
        if (!item) return;
        const x = Number(item.x || 0);
        const y = Number(item.y || 0);
        const w = Number(item.w || 0);
        const h = Number(item.h || 0);
        if (!(w > 0) || !(h > 0)) return;
        const rect = document.createElement("div");
        rect.className = "highlight-rect";
        rect.style.left = `${{x * 100}}%`;
        rect.style.top = `${{y * 100}}%`;
        rect.style.width = `${{w * 100}}%`;
        rect.style.height = `${{h * 100}}%`;
        layer.appendChild(rect);
      }});
      if (layer.childElementCount) {{
        target.appendChild(layer);
      }}
    }}

    function updateFocusCard(payload) {{
      const label = String(payload.location_label || payload.label || "命中定位");
      const text = String(payload.highlight_text || payload.text || "").trim();
      if (!text) {{
        focusCard?.classList.remove("show");
        if (focusText) focusText.textContent = "";
        return;
      }}
      if (focusLabel) focusLabel.textContent = label;
      if (focusText) focusText.textContent = text;
      focusCard?.classList.add("show");
    }}

    window.addEventListener("message", (event) => {{
      const payload = event.data || {{}};
      if (payload.type !== "gotoPacketTarget") return;
      gotoPage(payload.page, true);
      applyHighlights(payload.page, payload.highlight_rects || []);
      updateFocusCard(payload);
    }});

    const observer = new IntersectionObserver((entries) => {{
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      const page = Number(visible.target.dataset.page || activePage || 1);
      setActivePage(page);
    }}, {{
      root: null,
      threshold: [0.35, 0.6, 0.85],
    }});

    document.querySelectorAll(".packet-page").forEach((node) => observer.observe(node));
    gotoPage(1, false);
  </script>
</body>
</html>"""

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
                    "doc_type": "",
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
                    "doc_type": self._attachment_doc_type(item),
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
                and any(
                    (isinstance(target.get("packet_page"), int) and target.get("packet_page", 0) > 0)
                    or str(target.get("source_file") or "").strip() not in {"", "-"}
                    for target in item.get("evidence_targets", [])
                )
            ),
            next(
                (
                    item["id"]
                    for item in all_items
                    if item["status"] in {"failed", "manual"}
                ),
                all_items[0]["id"] if all_items else "",
            ),
        )
        return {
            "project_id": result.project_id,
            "project_name": project_name,
            "project_type": result.project_type,
            "project_type_label": self._project_type_label(result.project_type),
            "summary": result.summary,
            "counts": status_counts,
            "policy_sections": policy_sections,
            "extra_sections": extra_sections,
            "default_rule_id": default_rule_id,
            "packet": {
                "packet_file": str(packet_assets.get("packet_file", "")),
                "viewer_file": str(packet_assets.get("viewer_file", "")),
                "default_page": int(packet_assets.get("default_page", 1) or 1),
            },
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

    def _project_type_label(self, project_type: str) -> str:
        """项目类型中文标签"""
        key = str(project_type or "").strip()
        return self.PROJECT_TYPE_LABELS.get(key, key or "未识别项目类型")

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
        project_info_updates = proposal_facts.get("project_info_updates", {}) if isinstance(proposal_facts, dict) else {}
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
            if expected_doc_kind and status == "passed":
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

        if source_result.item == "leader_achievement_attachment_check":
            matched_doc_kinds = []
            if isinstance(getattr(source_result, "evidence", {}), dict):
                matched_doc_kinds = [
                    str(item).strip()
                    for item in source_result.evidence.get("matched_doc_kinds", [])
                    if str(item).strip()
                ]
            for index, attachment in enumerate(
                self._find_matching_attachments(attachments, matched_doc_kinds, limit=3),
                start=1,
            ):
                targets.append(
                    self._build_attachment_target(
                        target_id=f"{source_result.item}:{index}",
                        attachment=attachment,
                        clip=self._build_attachment_clip(attachment),
                        preview_assets=preview_assets,
                        packet_assets=packet_assets,
                    )
                )
            if targets:
                return targets

        clip = self._build_proposal_rule_clip(
            rule_item=str(source_result.item or ""),
            evidence=getattr(source_result, "evidence", {}),
            proposal_excerpt=proposal_excerpt,
            project_info_updates=project_info_updates,
            fallback_message=getattr(source_result, "message", ""),
        )
        rule_highlight = self._build_rule_highlight_spec(
            rule_item=str(source_result.item or ""),
            evidence=getattr(source_result, "evidence", {}),
            project_info_updates=project_info_updates,
        )
        if source_result.item == "proposal_file_presence":
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
                    rule_highlight=rule_highlight,
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

    def _attachment_doc_type(self, attachment: Dict[str, Any]) -> str:
        """从附件对象中提取统一 doc_type。"""
        if not isinstance(attachment, dict):
            return "unknown"
        raw = str(attachment.get("doc_type") or attachment.get("doc_kind") or "").strip()
        return normalize_doc_type(raw)

    def _attachment_doc_kind(self, attachment: Dict[str, Any]) -> str:
        """从附件对象中提取旧 doc_kind。"""
        if not isinstance(attachment, dict):
            return ""
        value = str(attachment.get("doc_kind") or "").strip()
        if value:
            return value
        return doc_type_to_legacy_doc_kind(self._attachment_doc_type(attachment))

    def _attachment_contains_doc_types(self, attachment: Dict[str, Any]) -> set[str]:
        """提取复合命中的 doc_type 集合。"""
        if not isinstance(attachment, dict):
            return set()
        details = attachment.get("classification_details", {})
        if not isinstance(details, dict):
            return set()
        raw_values = details.get("contains_doc_types", [])
        if not isinstance(raw_values, list):
            raw_values = details.get("contains_doc_kinds", [])
        if not isinstance(raw_values, list):
            return set()
        return {
            normalize_doc_type(str(value).strip())
            for value in raw_values
            if str(value).strip()
        }

    def _attachment_contains_doc_kinds(self, attachment: Dict[str, Any]) -> set[str]:
        """提取复合命中的旧 doc_kind 集合。"""
        doc_types = self._attachment_contains_doc_types(attachment)
        values = {
            doc_type_to_legacy_doc_kind(doc_type)
            for doc_type in doc_types
            if doc_type
        }
        details = attachment.get("classification_details", {}) if isinstance(attachment, dict) else {}
        raw_values = details.get("contains_doc_kinds", []) if isinstance(details, dict) else []
        if isinstance(raw_values, list):
            for value in raw_values:
                text = str(value).strip()
                if text:
                    values.add(text)
        return {item for item in values if item}

    def _find_matching_attachment(self, attachments: List[Any], doc_kind: str) -> Dict[str, Any] | None:
        """在附件列表中查找匹配类别"""
        expected_doc_type = normalize_doc_type(doc_kind, default="")
        for item in attachments:
            if not isinstance(item, dict):
                continue
            if self._attachment_doc_kind(item) == doc_kind:
                return item
            if expected_doc_type and self._attachment_doc_type(item) == expected_doc_type:
                return item
            contains_doc_kinds = self._attachment_contains_doc_kinds(item)
            contains_doc_types = self._attachment_contains_doc_types(item)
            if doc_kind in contains_doc_kinds:
                return item
            if expected_doc_type and expected_doc_type in contains_doc_types:
                return item
        return None

    def _find_matching_attachments(
        self,
        attachments: List[Any],
        doc_kinds: List[str],
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """按类别顺序查找多个匹配附件"""
        if not doc_kinds:
            return []
        normalized_doc_kinds = [str(item).strip() for item in doc_kinds if str(item).strip()]
        normalized_doc_types = {
            normalize_doc_type(item, default="")
            for item in normalized_doc_kinds
            if str(item).strip()
        }
        normalized_doc_types.discard("")
        if not normalized_doc_kinds:
            return []
        matched: List[Dict[str, Any]] = []
        seen_files: set[str] = set()
        target_doc_kinds = set(normalized_doc_kinds)
        for doc_kind in normalized_doc_kinds:
            for item in attachments:
                if not isinstance(item, dict):
                    continue
                source_file = str(item.get("file_ref", "") or "")
                if source_file and source_file in seen_files:
                    continue
                item_doc_kind = self._attachment_doc_kind(item)
                item_doc_type = self._attachment_doc_type(item)
                contains_doc_kinds = self._attachment_contains_doc_kinds(item)
                contains_doc_types = self._attachment_contains_doc_types(item)
                expected_doc_type = normalize_doc_type(doc_kind, default="")
                if (
                    item_doc_kind == doc_kind
                    or doc_kind in contains_doc_kinds
                    or (expected_doc_type and item_doc_type == expected_doc_type)
                    or (expected_doc_type and expected_doc_type in contains_doc_types)
                ):
                    matched.append(item)
                    if source_file:
                        seen_files.add(source_file)
                    if len(matched) >= max(1, limit):
                        return matched
            if len(matched) >= max(1, limit):
                return matched

        if matched:
            return matched

        for item in attachments:
            if not isinstance(item, dict):
                continue
            source_file = str(item.get("file_ref", "") or "")
            if source_file and source_file in seen_files:
                continue
            item_doc_kind = self._attachment_doc_kind(item)
            item_doc_type = self._attachment_doc_type(item)
            contains_doc_kinds = self._attachment_contains_doc_kinds(item)
            contains_doc_types = self._attachment_contains_doc_types(item)
            if (
                item_doc_kind in target_doc_kinds
                or contains_doc_kinds & target_doc_kinds
                or item_doc_type in normalized_doc_types
                or contains_doc_types & normalized_doc_types
            ):
                matched.append(item)
                if source_file:
                    seen_files.add(source_file)
                if len(matched) >= max(1, limit):
                    break
        return matched

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
        attachment_kind = self._attachment_doc_kind(attachment)
        tab_label = str(attachment.get("file_name") or self._doc_kind_label(attachment_kind))
        location_label = f"{self._doc_kind_label(attachment_kind)}"
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
        rule_highlight: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """构造文件类证据目标"""
        path = Path(source_file) if source_file else None
        suffix = path.suffix.lower() if path and path.exists() else ""
        preview_asset = preview_assets.get(source_file, {}) if isinstance(preview_assets, dict) else {}
        open_uri = self._build_file_uri(path, page=page, for_embed=False) if path else ""
        preview_uri = ""
        preview_mode = "none"
        anchor_id = self._resolve_preview_anchor(preview_asset, clip)
        if page is None:
            page = self._estimate_page_from_anchor(preview_asset, anchor_id, packet_assets, source_file)
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
        highlight_payload = self._resolve_packet_highlight(
            packet_assets,
            packet_page,
            clip,
            source_file,
            rule_highlight=rule_highlight,
        )
        matched_packet_page = highlight_payload.get("page")
        if isinstance(matched_packet_page, int) and matched_packet_page > 0:
            packet_page = matched_packet_page
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
            "highlight_mode": highlight_payload.get("mode", "none"),
            "highlight_text": highlight_payload.get("text", ""),
            "highlight_rects": highlight_payload.get("rects", []),
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
        exact_match: Dict[str, Any] | None = None
        proposal_match: Dict[str, Any] | None = None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_file") or "")
            if item_source == str(source_file or ""):
                exact_match = item
                break
            if self._is_same_proposal_family(source_file, item_source) and str(item.get("source_kind") or "") == "proposal":
                proposal_match = proposal_match or item
        matched = exact_match or proposal_match
        if not isinstance(matched, dict):
            return None
        start_page = matched.get("start_page")
        end_page = matched.get("end_page")
        if not isinstance(start_page, int) or start_page <= 0:
            return None
        if isinstance(page, int) and page > 0:
            max_page = end_page if isinstance(end_page, int) and end_page >= start_page else start_page
            return min(start_page + page - 1, max_page)
        return start_page

    def _resolve_packet_highlight(
        self,
        packet_assets: Dict[str, Any],
        packet_page: int | None,
        clip: str,
        source_file: str,
        rule_highlight: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """根据定位摘要在 packet 页中搜索并生成高亮框"""
        text = self._condense_highlight_text(clip)
        if not isinstance(packet_assets, dict) or not isinstance(packet_page, int) or packet_page <= 0:
            return {"mode": "none", "text": text, "rects": [], "page": packet_page}
        packet_abs_path = str(packet_assets.get("packet_abs_path", "")).strip()
        if not packet_abs_path:
            return {"mode": "none", "text": text, "rects": [], "page": packet_page}

        candidates = self._build_highlight_candidates(text)
        if not candidates:
            return {"mode": "none", "text": text, "rects": [], "page": packet_page}

        try:
            with fitz.open(packet_abs_path) as packet_doc:
                if packet_page > packet_doc.page_count:
                    return {"mode": "none", "text": text, "rects": [], "page": packet_page}
                special_payload = self._resolve_special_packet_highlight(
                    packet_doc=packet_doc,
                    packet_assets=packet_assets,
                    packet_page=packet_page,
                    clip=text,
                    source_file=source_file,
                    rule_highlight=rule_highlight,
                )
                if special_payload.get("rects"):
                    return special_payload
                special_page = special_payload.get("page")
                if isinstance(special_page, int) and special_page > 0:
                    packet_page = special_page
                primary_pages, fallback_pages = self._build_packet_search_pages(
                    packet_assets,
                    source_file,
                    packet_page,
                    packet_doc.page_count,
                )
                matched_page, matched_text, rects = self._search_packet_pages_highlights(
                    packet_doc,
                    primary_pages,
                    candidates,
                    packet_page,
                )
                if not rects and fallback_pages:
                    matched_page, matched_text, rects = self._search_packet_pages_highlights(
                        packet_doc,
                        fallback_pages,
                        candidates,
                        packet_page,
                    )
        except Exception:
            return {"mode": "none", "text": text, "rects": [], "page": packet_page}

        if rects:
            return {
                "mode": "rect",
                "text": matched_text or text,
                "rects": rects,
                "page": matched_page,
            }
        return {"mode": "none", "text": text, "rects": [], "page": packet_page}

    def _resolve_special_packet_highlight(
        self,
        packet_doc: fitz.Document,
        packet_assets: Dict[str, Any],
        packet_page: int,
        clip: str,
        source_file: str,
        rule_highlight: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        """针对结构化规则使用更稳定的 packet 定位逻辑"""
        if not isinstance(rule_highlight, dict):
            return {"mode": "none", "text": clip, "rects": [], "page": packet_page}
        rule_item = str(rule_highlight.get("rule_item") or "").strip()
        evidence = rule_highlight.get("evidence", {})
        project_info_updates = rule_highlight.get("project_info_updates", {})
        if not isinstance(evidence, dict):
            evidence = {}
        if not isinstance(project_info_updates, dict):
            project_info_updates = {}

        if rule_item == "funding_ratio_check":
            return self._resolve_funding_ratio_packet_highlight(
                packet_doc=packet_doc,
                packet_assets=packet_assets,
                packet_page=packet_page,
                source_file=source_file,
                clip=clip,
                evidence=evidence,
                project_info_updates=project_info_updates,
            )
        if rule_item == "budget_forbidden_expense_check":
            return self._resolve_budget_forbidden_packet_highlight(
                packet_doc=packet_doc,
                packet_assets=packet_assets,
                packet_page=packet_page,
                source_file=source_file,
                clip=clip,
                evidence=evidence,
                project_info_updates=project_info_updates,
            )
        if rule_item == "performance_metric_count_check":
            return self._resolve_performance_metric_packet_highlight(
                packet_doc=packet_doc,
                packet_assets=packet_assets,
                packet_page=packet_page,
                source_file=source_file,
                clip=clip,
                evidence=evidence,
            )
        return {"mode": "none", "text": clip, "rects": [], "page": packet_page}

    def _resolve_funding_ratio_packet_highlight(
        self,
        packet_doc: fitz.Document,
        packet_assets: Dict[str, Any],
        packet_page: int,
        source_file: str,
        clip: str,
        evidence: Dict[str, Any],
        project_info_updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """财政/自筹资金比例：优先定位“经费来源”整行"""
        ratio_line = self._find_budget_line_for_ratio(evidence, project_info_updates)
        page_numbers = self._build_priority_packet_pages(
            packet_assets,
            source_file,
            packet_page,
            packet_doc.page_count,
        )
        best_page = self._select_best_packet_page_by_text(
            packet_doc,
            page_numbers,
            [ratio_line, "经费来源", "专项经费", "自筹经费", "财政资金"],
            packet_page,
        )
        page = packet_doc.load_page(best_page - 1)
        row_rect = self._find_row_band_rect(
            page,
            [ratio_line, "经费来源", "专项经费", "自筹经费", "财政资金"],
        )
        if not row_rect:
            return {"mode": "none", "text": ratio_line or clip, "rects": [], "page": best_page}
        return {
            "mode": "rect",
            "text": ratio_line or "经费来源",
            "rects": self._rects_to_payload([row_rect], page.rect, pad_x_ratio=0.016, pad_y_ratio=0.012),
            "page": best_page,
        }

    def _resolve_budget_forbidden_packet_highlight(
        self,
        packet_doc: fitz.Document,
        packet_assets: Dict[str, Any],
        packet_page: int,
        source_file: str,
        clip: str,
        evidence: Dict[str, Any],
        project_info_updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """经费禁列项：命中禁列项时框整行，否则退到预算说明区"""
        forbidden_line = self._find_first_forbidden_budget_line(evidence)
        forbidden_terms = []
        for item in evidence.get("forbidden_hits", []) if isinstance(evidence.get("forbidden_hits"), list) else []:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "")).strip()
            if term:
                forbidden_terms.append(term)
        budget_anchor = self._find_budget_section_anchor(project_info_updates)
        page_numbers = self._build_priority_packet_pages(
            packet_assets,
            source_file,
            packet_page,
            packet_doc.page_count,
        )
        budget_page = self._select_best_packet_page_by_text(
            packet_doc,
            page_numbers,
            [budget_anchor, "项目预算基本测算说明", "经费来源"],
            packet_page,
        )
        exact_terms = [forbidden_line, *forbidden_terms[:3], "间接经费", "绩效支出", "罚款", "捐款", "赞助", "投资", "偿还债务"]
        exact_terms = [term for term in exact_terms if str(term or "").strip()]
        if exact_terms:
            page = packet_doc.load_page(budget_page - 1)
            anchor_rect = self._find_precise_term_rect(page, exact_terms)
            row_rect = self._expand_rect_to_row_band(page, anchor_rect) if anchor_rect else None
            if row_rect:
                return {
                    "mode": "rect",
                    "text": forbidden_line or forbidden_terms[0] or "预算禁列项",
                    "rects": self._rects_to_payload([row_rect], page.rect, pad_x_ratio=0.014, pad_y_ratio=0.01),
                    "page": budget_page,
                }

        best_page = budget_page
        page = packet_doc.load_page(best_page - 1)
        row_rect = self._find_row_band_rect(page, [budget_anchor, "项目预算基本测算说明"])
        if not row_rect:
            return {"mode": "none", "text": forbidden_line or budget_anchor or clip, "rects": [], "page": best_page}
        return {
            "mode": "rect",
            "text": forbidden_line or budget_anchor or "预算说明",
            "rects": self._rects_to_payload([row_rect], page.rect, pad_x_ratio=0.016, pad_y_ratio=0.012),
            "page": best_page,
        }

    def _resolve_performance_metric_packet_highlight(
        self,
        packet_doc: fitz.Document,
        packet_assets: Dict[str, Any],
        packet_page: int,
        source_file: str,
        clip: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        """绩效指标：按指标表整块定位，不再只框局部词"""
        metric_names = self._extract_performance_metric_names(evidence)
        page_numbers = self._build_priority_packet_pages(
            packet_assets,
            source_file,
            packet_page,
            packet_doc.page_count,
        )
        best_page = self._select_best_packet_page_by_text(
            packet_doc,
            page_numbers,
            ["预期绩效目标", "绩效指标", "一级指标", "三级指标", "指标值", *metric_names[:4]],
            packet_page,
        )
        page = packet_doc.load_page(best_page - 1)
        section_rects: List[fitz.Rect] = []
        heading_rect = self._find_row_band_rect(page, ["绩效指标", "一级指标", "三级指标", "指标值"])
        if heading_rect:
            section_rects.append(heading_rect)
        for metric_name in metric_names[:8]:
            row_rect = self._find_row_band_rect(page, [metric_name])
            if row_rect:
                section_rects.append(row_rect)
        if not section_rects:
            return {"mode": "none", "text": metric_names[0] if metric_names else clip, "rects": [], "page": best_page}
        merged_rect = self._union_rects(section_rects)
        if not merged_rect:
            return {"mode": "none", "text": metric_names[0] if metric_names else clip, "rects": [], "page": best_page}
        return {
            "mode": "rect",
            "text": "绩效指标表",
            "rects": self._rects_to_payload([merged_rect], page.rect, pad_x_ratio=0.018, pad_y_ratio=0.016),
            "page": best_page,
        }

    def _build_priority_packet_pages(
        self,
        packet_assets: Dict[str, Any],
        source_file: str,
        preferred_page: int,
        packet_page_count: int,
    ) -> List[int]:
        """生成带优先级的 packet 页序列"""
        page_range = self._resolve_source_packet_range(packet_assets, source_file)
        if page_range:
            start_page, end_page = page_range
            pages = list(range(max(1, start_page), min(packet_page_count, end_page) + 1))
        else:
            start_page = max(1, preferred_page - 4)
            end_page = min(packet_page_count, preferred_page + 4)
            pages = list(range(start_page, end_page + 1))
        return sorted(set(pages), key=lambda value: (0 if value == preferred_page else 1, abs(value - preferred_page), value))

    def _select_best_packet_page_by_text(
        self,
        packet_doc: fitz.Document,
        page_numbers: List[int],
        terms: List[str],
        preferred_page: int,
    ) -> int:
        """按文本命中度选择最可能的 packet 页"""
        usable_terms = [term for term in terms if str(term or "").strip()]
        if not usable_terms:
            return preferred_page
        best_page = preferred_page
        best_score = -10**9
        for page_number in page_numbers:
            if page_number <= 0 or page_number > packet_doc.page_count:
                continue
            page = packet_doc.load_page(page_number - 1)
            page_text = self._normalize_packet_text(page.get_text("text"))
            if not page_text:
                continue
            score = -abs(page_number - preferred_page) * 12
            for term in usable_terms:
                local_best = 0
                for variant in self._build_anchor_terms(term):
                    normalized_variant = self._normalize_packet_text(variant)
                    if len(normalized_variant) < 2:
                        continue
                    if normalized_variant in page_text:
                        local_best = max(local_best, len(normalized_variant) * 10)
                score += local_best
            if score > best_score:
                best_score = score
                best_page = page_number
        return best_page

    def _find_row_band_rect(self, page: fitz.Page, anchor_terms: List[str]) -> fitz.Rect | None:
        """在页面内按锚点词找到整行/整带区域"""
        anchor_rect = self._find_best_anchor_rect(page, anchor_terms)
        if not anchor_rect:
            return None
        return self._expand_rect_to_row_band(page, anchor_rect)

    def _find_precise_term_rect(self, page: fitz.Page, terms: List[str]) -> fitz.Rect | None:
        """优先使用直接词命中，避免长文本片段误匹配到错误行"""
        usable_terms = [str(term or "").strip() for term in terms if str(term or "").strip()]
        if not usable_terms:
            return None
        for term in usable_terms:
            hits = page.search_for(term)
            if hits:
                merged = self._union_rects(hits[:8])
                if merged:
                    return merged

        line_items = self._extract_page_line_items(page)
        for term in usable_terms:
            normalized_term = self._normalize_packet_text(term)
            if len(normalized_term) < 2:
                continue
            for item in line_items:
                if normalized_term in item["normalized_text"]:
                    return fitz.Rect(item["rect"])
        return None

    def _find_best_anchor_rect(self, page: fitz.Page, anchor_terms: List[str]) -> fitz.Rect | None:
        """优先用行文本，再回退到 search_for，找到最稳定的锚点框"""
        best_rect: fitz.Rect | None = None
        best_score = 0
        line_items = self._extract_page_line_items(page)
        for term in anchor_terms:
            for variant in self._build_anchor_terms(term):
                normalized_variant = self._normalize_packet_text(variant)
                if len(normalized_variant) < 2:
                    continue
                for item in line_items:
                    normalized_line = item["normalized_text"]
                    if not normalized_line:
                        continue
                    if normalized_variant in normalized_line or normalized_line in normalized_variant:
                        score = min(len(normalized_variant), len(normalized_line)) * 100
                    else:
                        score = self._shared_substring_score(normalized_variant, normalized_line) * 100
                    if score > best_score:
                        best_score = score
                        best_rect = fitz.Rect(item["rect"])
                if best_score >= max(600, len(normalized_variant) * 100):
                    continue
                hits = page.search_for(variant)
                if hits:
                    merged = self._union_rects(hits[:8])
                    score = len(normalized_variant) * 100
                    if merged and score > best_score:
                        best_score = score
                        best_rect = merged
        return best_rect if best_score >= 400 else None

    def _expand_rect_to_row_band(self, page: fitz.Page, anchor_rect: fitz.Rect) -> fitz.Rect:
        """根据锚点框把高亮扩成整行/整带"""
        page_rect = page.rect
        words = page.get_text("words")
        if not words:
            return fitz.Rect(anchor_rect)
        band_pad = max(anchor_rect.height * 1.4, page_rect.height * 0.012)
        band_top = anchor_rect.y0 - band_pad
        band_bottom = anchor_rect.y1 + band_pad
        row_words: List[fitz.Rect] = []
        for word in words:
            if len(word) < 5:
                continue
            rect = fitz.Rect(word[:4])
            center_y = (rect.y0 + rect.y1) / 2
            if band_top <= center_y <= band_bottom:
                row_words.append(rect)
        merged = self._union_rects(row_words)
        return merged or fitz.Rect(anchor_rect)

    def _extract_page_line_items(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """按 block/line 聚合页面文本行"""
        words = page.get_text("words")
        grouped: Dict[tuple[int, int], List[Any]] = {}
        for word in words:
            if len(word) < 8:
                continue
            key = (int(word[5]), int(word[6]))
            grouped.setdefault(key, []).append(word)
        items: List[Dict[str, Any]] = []
        for _, entries in grouped.items():
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

    def _build_anchor_terms(self, text: str) -> List[str]:
        """构造更适合 packet 行匹配的锚点词"""
        value = str(text or "").strip()
        if not value:
            return []
        candidates = [value]
        split_parts = re.split(r"[|｜]", value)
        for part in split_parts:
            cleaned = part.strip()
            if len(cleaned) >= 4:
                candidates.append(cleaned)
        no_brackets = re.sub(r"[（(].*?[）)]", "", value).strip()
        if len(no_brackets) >= 4:
            candidates.append(no_brackets)
        compact = re.sub(r"\s+", "", value)
        if len(compact) >= 6:
            candidates.extend(self._build_chinese_fragment_candidates(compact)[:8])
        deduped: List[str] = []
        seen = set()
        for item in candidates:
            key = self._normalize_packet_text(item)
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:10]

    def _extract_performance_metric_names(self, evidence: Dict[str, Any]) -> List[str]:
        """提取绩效指标名称列表"""
        rows = evidence.get("performance_metric_rows", [])
        if not isinstance(rows, list):
            return []
        names: List[str] = []
        seen = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            metric_name = str(item.get("metric_name", "")).strip()
            if metric_name and metric_name not in seen:
                seen.add(metric_name)
                names.append(metric_name)
        return names

    def _build_rule_highlight_spec(
        self,
        rule_item: str,
        evidence: Any,
        project_info_updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造结构化规则的专用定位信息"""
        if rule_item not in {"funding_ratio_check", "budget_forbidden_expense_check", "performance_metric_count_check"}:
            return {}
        if not isinstance(evidence, dict):
            return {}
        return {
            "rule_item": rule_item,
            "evidence": evidence,
            "project_info_updates": project_info_updates if isinstance(project_info_updates, dict) else {},
        }

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

    def _rects_to_payload(
        self,
        rects: List[fitz.Rect],
        page_rect: fitz.Rect,
        pad_x_ratio: float = 0.012,
        pad_y_ratio: float = 0.008,
    ) -> List[Dict[str, float]]:
        """把 rect 转成前端 viewer 需要的归一化 payload"""
        if not rects or page_rect.width <= 0 or page_rect.height <= 0:
            return []
        payload: List[Dict[str, float]] = []
        pad_x = page_rect.width * pad_x_ratio
        pad_y = page_rect.height * pad_y_ratio
        for rect in rects[:4]:
            expanded = fitz.Rect(
                max(page_rect.x0, rect.x0 - pad_x),
                max(page_rect.y0, rect.y0 - pad_y),
                min(page_rect.x1, rect.x1 + pad_x),
                min(page_rect.y1, rect.y1 + pad_y),
            )
            payload.append(
                {
                    "x": round(expanded.x0 / page_rect.width, 6),
                    "y": round(expanded.y0 / page_rect.height, 6),
                    "w": round((expanded.x1 - expanded.x0) / page_rect.width, 6),
                    "h": round((expanded.y1 - expanded.y0) / page_rect.height, 6),
                }
            )
        return payload

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
            matched_candidates: List[str] = []
            matched_rects: List[fitz.Rect] = []
            for candidate in normalized_candidates:
                search_hits = page.search_for(candidate)
                if search_hits:
                    matched_candidates.append(candidate)
                    matched_rects.extend(search_hits[:6])
            if not matched_rects:
                continue

            merged_rects = self._merge_highlight_rects(matched_rects, page_rect)
            score = (
                len(matched_candidates) * 1000
                + sum(len(re.sub(r"\s+", "", candidate)) for candidate in matched_candidates[:6])
                + len(merged_rects) * 10
                - abs(page_number - preferred_page) * 450
            )
            page_order = page_numbers.index(page_number)
            if score > best_score or (score == best_score and page_order < best_order):
                best_score = score
                best_order = page_order
                best_page = page_number
                best_text = " / ".join(matched_candidates[:3])
                best_rects = merged_rects
        return best_page, best_text, best_rects

    def _merge_highlight_rects(
        self,
        rects: List[fitz.Rect],
        page_rect: fitz.Rect,
    ) -> List[Dict[str, float]]:
        """把多个小命中框合并成更稳定、更易读的高亮区域"""
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

        padded: List[Dict[str, float]] = []
        pad_x = page_rect.width * 0.012
        pad_y = page_rect.height * 0.008
        for rect in merged[:4]:
            expanded = fitz.Rect(
                max(page_rect.x0, rect.x0 - pad_x),
                max(page_rect.y0, rect.y0 - pad_y),
                min(page_rect.x1, rect.x1 + pad_x),
                min(page_rect.y1, rect.y1 + pad_y),
            )
            padded.append(
                {
                    "x": round(expanded.x0 / page_rect.width, 6),
                    "y": round(expanded.y0 / page_rect.height, 6),
                    "w": round((expanded.x1 - expanded.x0) / page_rect.width, 6),
                    "h": round((expanded.y1 - expanded.y0) / page_rect.height, 6),
                }
            )
        return padded

    def _build_packet_search_pages(
        self,
        packet_assets: Dict[str, Any],
        source_file: str,
        packet_page: int,
        packet_page_count: int,
    ) -> tuple[List[int], List[int]]:
        """构造 packet 搜索页范围：先搜附近页，必要时再扩到整份材料"""
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
        exact_match: Dict[str, Any] | None = None
        proposal_match: Dict[str, Any] | None = None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_file") or "")
            if item_source == str(source_file or ""):
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

    def _condense_highlight_text(self, clip: str, max_len: int = 160) -> str:
        """压缩 evidence 摘要，供 viewer 展示"""
        text = re.sub(r"\s+", " ", str(clip or "")).strip()
        if len(text) <= max_len:
            return text
        return text[:max_len].rstrip() + "..."

    def _build_highlight_candidates(self, text: str) -> List[str]:
        """从 evidence 摘要中构造可搜索的高亮候选词"""
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
    
    def _is_same_proposal_family(self, left: str, right: str) -> bool:
        """判断两个路径是否指向同一项目的申报书不同格式"""
        left_path = Path(str(left or ""))
        right_path = Path(str(right or ""))
        if not left_path.name or not right_path.name:
            return False
        if left_path.parent != right_path.parent:
            return False
        return left_path.stem == right_path.stem

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

    def _build_proposal_rule_clip(
        self,
        rule_item: str,
        evidence: Any,
        proposal_excerpt: str,
        project_info_updates: Dict[str, Any],
        fallback_message: str,
    ) -> str:
        """为申报书类规则挑选更接近原文的定位片段"""
        formatted = self._format_evidence_clip(evidence, fallback_message)
        if not isinstance(evidence, dict):
            return formatted

        if rule_item == "registered_date_limit":
            registered_date = str(evidence.get("registered_date", "")).strip()
            if registered_date:
                return f"注册时间 | {registered_date}"
            return self._extract_keyword_snippet(proposal_excerpt, "注册时间") or formatted

        if rule_item == "project_leader_age_check":
            birth_date = str(evidence.get("project_leader_birth_date", "")).strip()
            if birth_date:
                return self._compact_date_token(birth_date) or birth_date
            return self._extract_keyword_snippet(proposal_excerpt, "出生") or self._extract_keyword_snippet(proposal_excerpt, "负责人") or formatted

        if rule_item == "execution_period_limit":
            return (
                self._extract_line_by_keyword(proposal_excerpt, "起 止 年 月")
                or self._extract_line_by_keyword(proposal_excerpt, "起止年月")
                or self._extract_keyword_snippet(proposal_excerpt, "起止年月")
                or self._extract_keyword_snippet(proposal_excerpt, "执行期")
                or formatted
            )

        if rule_item == "funding_ratio_check":
            matched_line = self._find_budget_line_for_ratio(evidence, project_info_updates)
            if matched_line:
                return matched_line
            return formatted

        if rule_item == "performance_metric_count_check":
            metric_line = self._find_first_performance_metric_line(evidence)
            if metric_line:
                return metric_line
            return self._extract_keyword_snippet(proposal_excerpt, "绩效指标") or formatted

        if rule_item == "budget_forbidden_expense_check":
            forbidden_line = self._find_first_forbidden_budget_line(evidence)
            if forbidden_line:
                return forbidden_line
            budget_anchor = self._find_budget_section_anchor(project_info_updates)
            if budget_anchor:
                return budget_anchor
            return self._extract_keyword_snippet(proposal_excerpt, "预算") or formatted

        if rule_item == "cooperation_region_check":
            region_line = self._find_cooperation_region_line(evidence)
            if region_line:
                return region_line
            return self._extract_keyword_snippet(proposal_excerpt, "合作单位") or formatted

        if rule_item == "applicant_qualification_check":
            unit = str(evidence.get("applicant_unit", "")).strip()
            region = str(evidence.get("applicant_region", "")).strip()
            if unit and region:
                return f"{unit} {region}"
            return formatted

        return formatted

    def _find_budget_line_for_ratio(self, evidence: Dict[str, Any], project_info_updates: Dict[str, Any]) -> str:
        """在预算文本中定位财政/自筹资金比例对应原文"""
        budget_lines = project_info_updates.get("budget_line_items", [])
        if not isinstance(budget_lines, list):
            return ""
        fiscal_funding = evidence.get("fiscal_funding")
        self_funding = evidence.get("self_funding")
        fiscal_tokens = self._build_number_tokens(fiscal_funding)
        self_tokens = self._build_number_tokens(self_funding)
        for raw_line in budget_lines:
            line = str(raw_line or "").strip()
            if not line:
                continue
            if any(token in line for token in ["专项经费", "财政资金"]) and any(token in line for token in ["自筹经费", "自筹资金"]):
                if (not fiscal_tokens or any(token in line for token in fiscal_tokens)) and (not self_tokens or any(token in line for token in self_tokens)):
                    return line
        return ""

    def _find_first_performance_metric_line(self, evidence: Dict[str, Any]) -> str:
        """定位绩效指标原文行"""
        rows = evidence.get("performance_metric_rows", [])
        if not isinstance(rows, list):
            return ""
        for item in rows:
            if not isinstance(item, dict):
                continue
            raw_row = item.get("raw_row")
            if isinstance(raw_row, list):
                text = " | ".join(str(value).strip() for value in raw_row if str(value).strip())
                if text:
                    return text
            metric_name = str(item.get("metric_name", "")).strip()
            if metric_name:
                return metric_name
        return ""

    def _find_first_forbidden_budget_line(self, evidence: Dict[str, Any]) -> str:
        """定位预算禁列项命中的原文行"""
        forbidden_hits = evidence.get("forbidden_hits", [])
        if not isinstance(forbidden_hits, list):
            return ""
        for item in forbidden_hits:
            if not isinstance(item, dict):
                continue
            line = str(item.get("line", "")).strip()
            if line:
                return line
        return ""

    def _find_budget_section_anchor(self, project_info_updates: Dict[str, Any]) -> str:
        """在预算区选择一个稳定可命中的锚点"""
        budget_lines = project_info_updates.get("budget_line_items", [])
        if not isinstance(budget_lines, list):
            return ""
        preferred_keywords = ["项目预算基本测算说明", "第五部分 项目预算表", "经费来源：", "序号 | 预算科目名称 | 金额"]
        for keyword in preferred_keywords:
            for raw_line in budget_lines:
                line = str(raw_line or "").strip()
                if line and keyword in line:
                    return line
        return ""

    def _find_cooperation_region_line(self, evidence: Dict[str, Any]) -> str:
        """定位合作单位地区原文行"""
        unmatched = evidence.get("unmatched_units", [])
        if isinstance(unmatched, list):
            for item in unmatched:
                if not isinstance(item, dict):
                    continue
                unit = str(item.get("unit", "")).strip()
                region = str(item.get("region_text", "")).strip()
                if unit and region:
                    return f"{unit} | {region}"
                if unit:
                    return unit
        details = evidence.get("cooperation_region_details", [])
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                unit = str(item.get("unit", "")).strip()
                region = str(item.get("region", "")).strip()
                if unit and region:
                    return f"{unit} | {region}"
        return ""

    def _build_number_tokens(self, value: Any) -> List[str]:
        """把数值转换成常见文本写法，便于回查原文"""
        if not isinstance(value, (int, float)):
            return []
        normalized = float(value)
        tokens = {
            str(int(normalized)) if normalized.is_integer() else "",
            f"{normalized:.0f}" if normalized.is_integer() else "",
            f"{normalized:.1f}",
            f"{normalized:.2f}",
        }
        return [token for token in tokens if token]

    def _compact_date_token(self, value: str) -> str:
        """把日期压缩成 19820516 形式，便于命中身份证号"""
        digits = re.sub(r"\D+", "", str(value or ""))
        if len(digits) >= 8:
            return digits[:8]
        return digits

    def _estimate_page_from_anchor(
        self,
        preview_asset: Any,
        anchor_id: str,
        packet_assets: Dict[str, Any],
        source_file: str,
    ) -> int | None:
        """把 docx/html 预览锚点近似换算成原文件页码"""
        if not isinstance(preview_asset, dict) or not anchor_id:
            return None
        blocks = preview_asset.get("blocks", [])
        if not isinstance(blocks, list) or not blocks:
            return None

        matched_block: Dict[str, Any] | None = None
        total_chars = 0
        for item in blocks:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            total_chars += max(1, len(text))
            if str(item.get("anchor_id") or "") == anchor_id:
                matched_block = item
        if not matched_block or total_chars <= 0:
            return None

        proposal_page_count = self._resolve_source_page_count(packet_assets, source_file)
        if not proposal_page_count or proposal_page_count <= 1:
            return 1 if proposal_page_count == 1 else None

        char_end = matched_block.get("char_end")
        if not isinstance(char_end, int) or char_end <= 0:
            index = self._extract_anchor_index(anchor_id)
            block_count = preview_asset.get("block_count")
            if not isinstance(block_count, int) or block_count <= 0 or index <= 0:
                return None
            ratio = min(1.0, max(0.0, index / block_count))
        else:
            ratio = min(1.0, max(0.0, char_end / total_chars))

        estimated_page = int(ratio * proposal_page_count)
        if ratio > 0 and estimated_page < proposal_page_count:
            estimated_page += 1
        return min(max(estimated_page, 1), proposal_page_count)

    def _resolve_source_page_count(self, packet_assets: Dict[str, Any], source_file: str) -> int | None:
        """读取 source_file 在 packet 中的页数"""
        if not isinstance(packet_assets, dict):
            return None
        page_map = packet_assets.get("page_map", [])
        if not isinstance(page_map, list):
            return None
        exact_match: Dict[str, Any] | None = None
        proposal_match: Dict[str, Any] | None = None
        for item in page_map:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_file") or "")
            if item_source == str(source_file or ""):
                exact_match = item
                break
            if self._is_same_proposal_family(source_file, item_source) and str(item.get("source_kind") or "") == "proposal":
                proposal_match = proposal_match or item
        matched = exact_match or proposal_match
        if not isinstance(matched, dict):
            return None
        page_count = matched.get("page_count")
        return page_count if isinstance(page_count, int) and page_count > 0 else None

    def _extract_anchor_index(self, anchor_id: str) -> int:
        """提取形如 p-17 的锚点序号"""
        match = re.search(r"(\d+)$", str(anchor_id or "").strip())
        if not match:
            return 0
        try:
            return int(match.group(1))
        except ValueError:
            return 0

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
            self._attachment_doc_kind(att): att
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
            if isinstance(evidence.get("missing_doc_types"), list):
                kinds = [str(item) for item in evidence["missing_doc_types"] if item]
                if kinds:
                    return "缺失附件类别：" + "、".join(self._doc_kind_with_code(kind) for kind in kinds)
            if isinstance(evidence.get("missing_conditional_attachments"), list):
                lines = []
                for item in evidence["missing_conditional_attachments"][:6]:
                    if isinstance(item, dict):
                        kind = str(item.get("doc_type") or item.get("doc_kind") or "-")
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
            return fallback_message or "证据字段较复杂，需查看原始审查结果"
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
        if isinstance(evidence.get("missing_doc_types"), list):
            values.extend(
                doc_type_to_legacy_doc_kind(normalize_doc_type(str(item), default=""))
                for item in evidence["missing_doc_types"]
                if item
            )
        if isinstance(evidence.get("missing_doc_kinds"), list):
            values.extend(str(item) for item in evidence["missing_doc_kinds"] if item)
        if isinstance(evidence.get("missing_conditional_attachments"), list):
            for item in evidence["missing_conditional_attachments"]:
                if not isinstance(item, dict):
                    continue
                if item.get("doc_kind"):
                    values.append(str(item["doc_kind"]))
                elif item.get("doc_type"):
                    values.append(doc_type_to_legacy_doc_kind(normalize_doc_type(str(item["doc_type"]), default="")))
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
        doc_kind = self._attachment_doc_kind(attachment)
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
            kind = self._attachment_doc_kind(item)
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

    def _extract_line_by_keyword(self, text: str, keyword: str) -> str:
        """提取包含关键词的整行"""
        if not text or not keyword:
            return ""
        for raw_line in str(text).splitlines():
            line = str(raw_line or "").strip()
            if line and keyword in line:
                return line
        return ""

    def _doc_kind_label(self, doc_kind: str) -> str:
        """附件类别中文标签"""
        normalized_doc_type = normalize_doc_type(doc_kind, default="")
        if normalized_doc_type:
            label = get_doc_type_label(normalized_doc_type)
            if label and label != "未知":
                return label
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
        values = details.get("contains_doc_types", [])
        if not isinstance(values, list) or not values:
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
            doc_kind = self._doc_kind_with_code(str(item.get("doc_type") or item.get("doc_kind") or ""))
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
            doc_kind = self._doc_kind_label(str(item.get("doc_type") or item.get("doc_kind") or ""))
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
