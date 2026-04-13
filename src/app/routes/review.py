"""形式审查 API 路由"""
import asyncio
import json
import logging
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from docx import Document
from pydantic import BaseModel

from src.common.models import ApiResponse, CheckResult, CheckStatus, ReviewResult
from src.services.review.agent import ReviewAgent
from src.services.review.rules.config import DOCUMENT_CONFIG

router = APIRouter()
logger = logging.getLogger(__name__)

# 存储审查结果（生产环境应使用数据库）
_review_results: dict[str, ReviewResult] = {}


class ReviewRequest(BaseModel):
    """审查请求"""
    document_type: str
    check_items: Optional[List[str]] = None
    enable_llm_analysis: bool = False  # 是否启用 LLM 深度分析


class DocumentTypeInfo(BaseModel):
    """文档类型信息"""
    value: str
    label: str
    check_items: List[str]


class CheckItemInfo(BaseModel):
    """检查项信息"""
    value: str
    label: str
    description: str


def _read_docx_paragraphs(docx_path: Path, max_paragraphs: int = 1200) -> List[str]:
    """按 docx 底层 XML 段落提取文本，覆盖文本框/表格等常规 API 易漏内容。"""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: List[str] = []

    def _clean_text(text: str) -> str:
        return str(text or "").replace("\xa0", " ").replace("\u3000", " ").strip()

    def _extract_from_xml(xml_bytes: bytes) -> None:
        root = ET.fromstring(xml_bytes)
        for p in root.findall(".//w:p", ns):
            parts = []
            for t in p.findall(".//w:t", ns):
                if t.text:
                    parts.append(t.text)
            line = _clean_text("".join(parts))
            if not line:
                continue
            paragraphs.append(line)
            if len(paragraphs) >= max_paragraphs:
                return

    with zipfile.ZipFile(docx_path, "r") as zf:
        names = zf.namelist()
        target_names = ["word/document.xml"]
        target_names.extend([n for n in names if n.startswith("word/header") and n.endswith(".xml")])
        target_names.extend([n for n in names if n.startswith("word/footer") and n.endswith(".xml")])
        for name in target_names:
            if name not in names:
                continue
            try:
                _extract_from_xml(zf.read(name))
            except Exception:
                continue
            if len(paragraphs) >= max_paragraphs:
                break

    return paragraphs


def _extract_docx_tables(docx_path: Path) -> List[dict]:
    """提取文档内所有表格，输出结构化标题与要点行。"""
    doc = Document(str(docx_path))
    out: List[dict] = []

    def _norm(text: str) -> str:
        return str(text or "").replace("\n", " ").replace("\xa0", " ").replace("\u3000", " ").strip()

    for ti, table in enumerate(doc.tables, start=1):
        raw_rows: List[List[str]] = []
        for row in table.rows:
            vals = [_norm(cell.text) for cell in row.cells]
            vals = [v for v in vals if v]
            if not vals:
                continue
            dedup_vals: List[str] = []
            for v in vals:
                if not dedup_vals or dedup_vals[-1] != v:
                    dedup_vals.append(v)
            raw_rows.append(dedup_vals)

        if not raw_rows:
            continue

        title = raw_rows[0][0]
        points: List[dict] = []

        for row in raw_rows[1:]:
            line = " ".join(row)
            if "序号" in line and "形式审查要点" in line:
                continue

            seq = ""
            content = ""
            for v in row:
                vv = v.strip()
                if vv.isdigit() and not seq:
                    seq = vv
                    continue
                if "序号" in vv:
                    continue
                if "形式审查要点" in vv:
                    continue
                content = vv

            if not content:
                continue
            points.append({"seq": seq, "content": content})

        out.append(
            {
                "table_index": ti,
                "title": title,
                "rows": points,
            }
        )

    return out


def _safe_read_json(file_path: Path) -> dict:
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _doc_kind_label(doc_kind: str) -> str:
    labels = {
        "commitment_letter": "承诺书",
        "ethics_approval": "伦理审查意见",
        "biosafety_commitment": "生物安全承诺书",
        "cooperation_agreement": "合作协议",
        "recommendation_letter": "推荐函",
        "industry_permit": "行业许可材料",
    }
    return labels.get(doc_kind, doc_kind or "未知材料")


def _rule_label(code: str) -> str:
    labels = {
        "registered_date_limit": "注册时间",
        "funding_ratio_check": "财政/自筹比例",
        "external_status_check": "科研/社会失信",
        "ethics_approval_required": "伦理审查意见",
        "industry_permit_required": "行业准入许可",
        "biosafety_commitment_required": "生物安全承诺",
        "commitment_letter_required": "承诺书",
        "cooperation_agreement_required": "合作协议",
        "cooperation_region_check": "合作地区",
        "recommendation_letter_required": "管理部门推荐函",
        "execution_period_limit": "执行期限",
        "duplicate_submission_check": "重复/多头申报",
        "other_policy_compliance": "其他政策条款",
    }
    return labels.get(code, code or "未知要点")


def _normalize_match_text(text: str) -> str:
    return re.sub(r"[\s，。、“”‘’：；（）()【】\-]", "", str(text or "")).strip().lower()


def _match_rule_code_by_requirement(row_text: str, review_points: List[dict]) -> str:
    """将 docx 表格中的要点文本匹配到规则 code。"""
    left = _normalize_match_text(row_text)
    if not left:
        return ""
    best_code = ""
    best_len = -1
    for point in review_points:
        code = str(point.get("code") or "").strip()
        req = _normalize_match_text(point.get("requirement") or "")
        if not code or not req:
            continue
        if req in left or left in req:
            if len(req) > best_len:
                best_len = len(req)
                best_code = code
    return best_code


@router.get("/debug-batch-view")
async def get_debug_batch_view(limit: int = 300) -> ApiResponse[dict]:
    """读取固定调试批次结果，供前端直接展示双栏页面。"""
    root = Path("/home/tdkx/ljh/Tech/debug_review")
    docx_path = root / "2026年度中央引导地方形式审查要点.docx"
    projects_dir = root / "batch_review_1775034762632" / "projects"

    if not docx_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到要点文档: {docx_path}")
    if not projects_dir.exists() or not projects_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"未找到项目结果目录: {projects_dir}")

    result_files = sorted(projects_dir.glob("*.result.json"))
    if limit > 0:
        result_files = result_files[:limit]

    projects: List[dict] = []
    review_points_index: dict[str, dict] = {}
    point_status_stats: dict[str, dict] = {}

    for result_file in result_files:
        try:
            result_payload = _safe_read_json(result_file)
        except Exception as e:
            logger.warning("读取结果文件失败 %s: %s", result_file, e)
            continue

        project_id = str(result_payload.get("project_id") or "").strip() or result_file.stem.replace(".result", "")
        context_path = projects_dir / f"{project_id}.context.json"
        project_name = ""
        project_info = {}
        guide_name = ""
        applicant_unit = ""
        project_leader = ""
        year = ""
        try:
            if context_path.exists():
                context_payload = _safe_read_json(context_path)
                project_info = context_payload.get("project_info") or {}
                row = context_payload.get("project_index_row") or {}
                project_name = str(
                    project_info.get("project_name")
                    or row.get("project_name")
                    or ""
                ).strip()
                guide_name = str(project_info.get("guide_name") or row.get("guide_name") or "").strip()
                applicant_unit = str(project_info.get("applicant_unit") or row.get("unit_name") or "").strip()
                project_leader = str(row.get("project_leader") or "").strip()
                year = str(project_info.get("year") or row.get("year") or "").strip()
        except Exception as e:
            logger.warning("读取上下文文件失败 %s: %s", context_path, e)

        status_counts = {"passed": 0, "warning": 0, "failed": 0, "skipped": 0}
        for item in result_payload.get("results", []):
            status = str(item.get("status") or "").strip().lower()
            if status in status_counts:
                status_counts[status] += 1

        policy_rule_checks = []
        for check in result_payload.get("policy_rule_checks", []):
            code = str(check.get("code") or "").strip()
            requirement = str(check.get("requirement") or "").strip()
            status = str(check.get("status") or "").strip().lower()
            reason = str(check.get("reason") or "").strip()
            row = {
                "code": code,
                "label": _rule_label(code),
                "requirement": requirement,
                "status": status,
                "reason": reason,
            }
            policy_rule_checks.append(row)

            if code and code not in review_points_index:
                review_points_index[code] = {
                    "code": code,
                    "label": _rule_label(code),
                    "requirement": requirement or code,
                }

            if code:
                if code not in point_status_stats:
                    point_status_stats[code] = {
                        "passed": 0,
                        "failed": 0,
                        "warning": 0,
                        "requires_data": 0,
                        "manual": 0,
                        "not_applicable": 0,
                        "other": 0,
                        "total": 0,
                    }
                if status in point_status_stats[code]:
                    point_status_stats[code][status] += 1
                else:
                    point_status_stats[code]["other"] += 1
                point_status_stats[code]["total"] += 1

        missing_attachments = []
        for item in result_payload.get("missing_attachments", []):
            kind = str(item.get("doc_kind") or "").strip()
            missing_attachments.append(
                {
                    "doc_kind": kind,
                    "doc_label": _doc_kind_label(kind),
                    "reason": str(item.get("reason") or "").strip(),
                }
            )

        manual_items = []
        for item in result_payload.get("manual_review_items", []):
            code = str(item.get("item") or "").strip()
            evidence = item.get("evidence") or {}
            manual_items.append(
                {
                    "code": code,
                    "label": _rule_label(code),
                    "message": str(item.get("message") or "").strip(),
                    "reason": str(evidence.get("reason") or "").strip(),
                    "automation": str(evidence.get("automation") or "").strip(),
                }
            )

        risk_checks = [
            x for x in policy_rule_checks
            if x.get("status") in {"failed", "warning", "requires_data", "manual"}
        ]

        projects.append(
            {
                "project_id": project_id,
                "project_name": project_name,
                "project_type": result_payload.get("project_type") or "",
                "project_meta": {
                    "year": year,
                    "guide_name": guide_name,
                    "applicant_unit": applicant_unit,
                    "project_leader": project_leader,
                    "execution_period_years": project_info.get("execution_period_years"),
                },
                "summary": str(result_payload.get("summary") or "").strip(),
                "results": result_payload.get("results") or [],
                "suggestions": result_payload.get("suggestions") or [],
                "status_counts": status_counts,
                "missing_attachments": missing_attachments,
                "manual_review_items": manual_items,
                "risk_checks": risk_checks[:8],
                "policy_rule_checks": policy_rule_checks,
            }
        )

    review_points = list(review_points_index.values())
    for point in review_points:
        code = point.get("code")
        point["stats"] = point_status_stats.get(
            code,
            {
                "passed": 0,
                "failed": 0,
                "warning": 0,
                "requires_data": 0,
                "manual": 0,
                "not_applicable": 0,
                "other": 0,
                "total": 0,
            },
        )

    points_by_code = {str(x.get("code") or "").strip(): x for x in review_points}

    paragraphs = _read_docx_paragraphs(docx_path)
    guideline_text = "\n".join(paragraphs)
    tables = _extract_docx_tables(docx_path)
    for table in tables:
        for row in table.get("rows", []):
            content = str(row.get("content") or "").strip()
            code = _match_rule_code_by_requirement(content, review_points)
            point = points_by_code.get(code, {}) if code else {}
            row["matched_code"] = code
            row["matched_label"] = point.get("label") if point else ""
            row["matched_requirement"] = point.get("requirement") if point else ""
            row["stats"] = point.get("stats") if point else {
                "passed": 0,
                "failed": 0,
                "warning": 0,
                "requires_data": 0,
                "manual": 0,
                "not_applicable": 0,
                "other": 0,
                "total": 0,
            }

    return ApiResponse(
        status="success",
        data={
            "guideline": {
                "file_name": docx_path.name,
                "paragraphs": paragraphs,
                "full_text": guideline_text,
                "tables": tables,
            },
            "review_points": review_points,
            "projects": projects,
            "stats": {
                "total_projects": len(projects),
                "total_review_points": len(review_points),
            },
        },
    )


@router.post("")
async def submit_review(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    check_items: Optional[str] = Form(None),
    enable_llm_analysis: bool = Form(False),
    metadata: Optional[str] = Form(None),
) -> ApiResponse[ReviewResult]:
    """提交文件进行形式审查

    Args:
        file: 上传的文件
        document_type: 文档类型（必填，由调用方指定）
        check_items: 检查项，逗号分隔（可选）
        enable_llm_analysis: 是否启用 LLM 深度分析（可选）
        metadata: 元数据 JSON 字符串（可选）

    Returns:
        审查结果
    """
    import json

    # 解析检查项
    items = None
    if check_items:
        items = [i.strip() for i in check_items.split(",")]

    # 解析元数据
    meta_dict = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="metadata 必须是有效的 JSON 字符串")

    # 读取文件内容
    file_data = await file.read()

    try:
        review_id = f"review_{int(time.time() * 1000)}"
        placeholder = ReviewResult(
            id=review_id,
            status="processing",
            document_type=document_type,
            document_type_raw="",
            results=[],
            ocr_text="",
            extracted_data={},
            llm_analysis=None,
            summary="处理中",
            suggestions=[],
            processing_time=0.0,
        )
        _review_results[review_id] = placeholder

        async def _run_review() -> None:
            start_time = time.time()
            agent = ReviewAgent()
            try:
                result = await agent.process(
                    file_data=file_data,
                    file_type=file.filename.split(".")[-1] if "." in file.filename else "pdf",
                    document_type=document_type,
                    check_items=items,
                    enable_llm_analysis=enable_llm_analysis,
                    metadata=meta_dict,
                    review_id=review_id,
                )
                _review_results[review_id] = result
            except Exception as e:
                logger.exception("Review job failed: %s", review_id)
                _review_results[review_id] = ReviewResult(
                    id=review_id,
                    status="failed",
                    document_type=document_type,
                    document_type_raw="",
                    results=[
                        CheckResult(
                            item="system",
                            status=CheckStatus.FAILED,
                            message=str(e),
                            evidence={},
                            confidence=1.0,
                        )
                    ],
                    ocr_text="",
                    extracted_data={},
                    llm_analysis=None,
                    summary=f"审查失败：{e}",
                    suggestions=[],
                    processing_time=time.time() - start_time,
                )

        asyncio.create_task(_run_review())

        return ApiResponse(
            status="success",
            data=placeholder,
            message="已提交审查任务，请稍后使用 review_id 查询结果",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{review_id}")
async def get_review(review_id: str) -> ApiResponse[ReviewResult]:
    """根据 ID 查询审查结果

    Args:
        review_id: 审查 ID

    Returns:
        审查结果
    """
    result = _review_results.get(review_id)
    if not result:
        raise HTTPException(status_code=404, detail="审查结果不存在")

    return ApiResponse(
        status="success",
        data=result,
    )


@router.get("/document-types")
async def get_document_types() -> ApiResponse[List[DocumentTypeInfo]]:
    """获取支持的文档类型列表

    Returns:
        文档类型列表
    """
    types: List[DocumentTypeInfo] = []
    for doc_type, config in DOCUMENT_CONFIG.items():
        labels = config.get("labels", [])
        rules = config.get("rules", [])
        llm_rules = config.get("llm_rules", [])
        # 展示优先中文首标签；无标签则回退到 code
        label = labels[0] if labels else doc_type
        # 对外统一返回该类型可用检查项（规则引擎 + llm规则）
        check_items = [*rules, *llm_rules]
        types.append(
            DocumentTypeInfo(
                value=doc_type,
                label=label,
                check_items=check_items,
            )
        )

    return ApiResponse(
        status="success",
        data=types,
    )


@router.get("/check-items")
async def get_check_items() -> ApiResponse[List[CheckItemInfo]]:
    """获取所有可用的检查项

    Returns:
        检查项列表
    """
    items = [
        CheckItemInfo(
            value="signature",
            label="签字检查",
            description="检查文档中是否存在签字",
        ),
        CheckItemInfo(
            value="stamp",
            label="盖章检查",
            description="检查文档中是否存在印章",
        ),
        CheckItemInfo(
            value="prerequisite",
            label="前置条件",
            description="检查前置条件文档是否上传",
        ),
        CheckItemInfo(
            value="consistency",
            label="一致性检查",
            description="检查填写信息与证书是否一致",
        ),
        CheckItemInfo(
            value="completeness",
            label="完整性检查",
            description="检查文档是否完整",
        ),
    ]

    return ApiResponse(
        status="success",
        data=items,
    )
