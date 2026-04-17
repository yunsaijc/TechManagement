import asyncio
from datetime import datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.common.models import ApiResponse, ResponseStatus
from src.common.models.logicon import LogicOnResult, LogicOnTask
from src.services.logicon import get_logicon_service
from src.services.logicon.parser import LogicOnParser, PerfCheckParser
from src.services.logicon.project_display import sanitize_logicon_display_name
from src.services.logicon.reporter import LogicOnReporter


router = APIRouter()
logger = logging.getLogger(__name__)

_results: Dict[str, LogicOnResult] = {}
_tasks: Dict[str, LogicOnTask] = {}

DEBUG_DIR = "/home/tdkx/ljh/Tech/debug_logicon"
REPORTS_DIR = os.path.join(DEBUG_DIR, "reports")
os.makedirs(DEBUG_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


class LogicOnTextRequest(BaseModel):
    doc_kind: str = "auto"
    text: str
    enable_llm: bool = True
    return_graph: bool = False
    enable_agent: bool = True
    agent_max_turns: int = 8
    enable_equivalence_probe: bool = True
    amount_tolerance_wan: float = 0.01
    date_tolerance_days: int = 30
    metric_tolerance_ratio: float = 0.01


class LogicOnDebugPairedDocs(BaseModel):
    """同一文档 stem 下申报书 / 任务书的批量报告（来自 debug_logicon/reports/batch_*）。"""

    stem: str
    display_name: str = ""
    declaration: Optional[LogicOnResult] = None
    task: Optional[LogicOnResult] = None


class LogicOnDebugBatchView(BaseModel):
    batch_id: str
    report_abs_path: str
    items: List[LogicOnDebugPairedDocs]


def _latest_batch_subdir() -> Tuple[str, str]:
    """返回 (batch_id, 绝对路径)；若无 batch_* 子目录则 ("", "")。"""
    if not os.path.isdir(REPORTS_DIR):
        return "", ""
    names = [
        n
        for n in os.listdir(REPORTS_DIR)
        if n.startswith("batch_") and os.path.isdir(os.path.join(REPORTS_DIR, n))
    ]
    if not names:
        return "", ""
    names.sort(reverse=True)
    bid = names[0]
    return bid, os.path.join(REPORTS_DIR, bid)


def _load_batch_by_stem(batch_path: str) -> Dict[str, Dict[str, LogicOnResult]]:
    """读取目录内 *_declaration.json / *_task.json，按 stem 聚合为 { stem: {declaration|task: LogicOnResult } }。"""
    decl_pat = re.compile(r"^(.+)_declaration\.json$", re.I)
    task_pat = re.compile(r"^(.+)_task\.json$", re.I)
    by_stem: Dict[str, Dict[str, LogicOnResult]] = {}
    try:
        names = sorted(os.listdir(batch_path))
    except OSError:
        return {}
    for name in names:
        if not name.lower().endswith(".json"):
            continue
        full = os.path.join(batch_path, name)
        if not os.path.isfile(full):
            continue
        m_d = decl_pat.match(name)
        m_t = task_pat.match(name)
        stem = (m_d or m_t)
        if not stem:
            continue
        s = stem.group(1)
        kind = "declaration" if m_d else "task"
        try:
            with open(full, encoding="utf-8") as f:
                raw = json.load(f)
            result = LogicOnResult.model_validate(raw)
        except Exception as e:
            logger.warning("skip invalid logicon batch json %s: %s", full, e)
            continue
        slot = by_stem.setdefault(s, {})
        slot[kind] = result
    return by_stem


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


# stem 与批量脚本输入文件名一致时，在此目录下查找原始 docx/pdf 以解析「项目名称」。
_DOC_SEARCH_SUBDIRS = (
    "data/samples_2025_docx/sbs",
    "data/samples_2025_docx/hts",
    "data/perfcheck_samples_2025_docx/sbs",
    "data/perfcheck_samples_2025_docx/hts",
)

async def _load_batch_paired_results_async(batch_path: str) -> List[LogicOnDebugPairedDocs]:
    by_stem = _load_batch_by_stem(batch_path)
    stems = sorted(by_stem.keys())
    if not stems:
        return []
    sem = asyncio.Semaphore(4)
    parser = LogicOnParser()
    perf = PerfCheckParser()
    root = _project_root()

    async def _resolve_one(stem: str) -> str:
        """从样例目录中读取与 stem 同名的文档，抽取封面/页眉中的项目名称。"""
        if not stem:
            return ""
        async with sem:
            for sub in _DOC_SEARCH_SUBDIRS:
                for ext in ("docx", "pdf"):
                    path = root / sub / f"{stem}.{ext}"
                    if not path.is_file():
                        continue
                    try:
                        data = path.read_bytes()
                        parsed = await parser.parse_file(data, ext)
                        raw = getattr(parsed, "raw_text", "") or ""
                        name = perf._extract_project_name(raw[:24000])
                        if name:
                            cleaned = sanitize_logicon_display_name(name)
                            if cleaned:
                                return cleaned
                            # 清洗后过短则不再用原始长串，避免列表标题再次出现整表拼接
                            return ""
                    except Exception as e:
                        logger.debug("display_name parse skip %s: %s", path, e)
        return ""

    labels = await asyncio.gather(*(_resolve_one(s) for s in stems), return_exceptions=True)
    items: List[LogicOnDebugPairedDocs] = []
    for stem, label in zip(stems, labels):
        disk_label = ""
        if isinstance(label, Exception):
            logger.warning("display_name failed stem=%s: %s", stem, label)
        else:
            disk_label = str(label or "").strip()
        slot = by_stem[stem]
        decl = slot.get("declaration")
        task = slot.get("task")
        from_json = ""
        if decl is not None:
            from_json = str(getattr(decl, "project_name", "") or "").strip()
        if not from_json and task is not None:
            from_json = str(getattr(task, "project_name", "") or "").strip()
        label_str = from_json or disk_label
        items.append(
            LogicOnDebugPairedDocs(
                stem=stem,
                display_name=label_str,
                declaration=decl,
                task=task,
            )
        )
    return items


@router.get("/debug-reports/latest", response_model=ApiResponse[LogicOnDebugBatchView])
async def get_latest_debug_batch_reports() -> ApiResponse[LogicOnDebugBatchView]:
    """供前端展示：debug_logicon/reports 下按名称倒序最新的 batch_* 目录内容。"""
    batch_id, batch_path = _latest_batch_subdir()
    if not batch_id:
        payload = LogicOnDebugBatchView(batch_id="", report_abs_path=REPORTS_DIR, items=[])
        return ApiResponse(status=ResponseStatus.SUCCESS, data=payload)
    items = await _load_batch_paired_results_async(batch_path)
    payload = LogicOnDebugBatchView(batch_id=batch_id, report_abs_path=batch_path, items=items)
    return ApiResponse(status=ResponseStatus.SUCCESS, data=payload)


def _make_task(*, task_id: str, doc_id: str) -> LogicOnTask:
    return LogicOnTask(
        task_id=task_id,
        doc_id=doc_id,
        state="running",
        progress=0.01,
        stage="received",
        message="已接收请求",
        summary="",
        result=None,
    )


def _update_task(
    task_id: str,
    *,
    state: Optional[str] = None,
    progress: Optional[float] = None,
    stage: Optional[str] = None,
    error_code: Optional[str] = None,
    message: Optional[str] = None,
    summary: Optional[str] = None,
    result: Optional[LogicOnResult] = None,
) -> None:
    task = _tasks.get(task_id)
    if task is None:
        return
    data = task.model_dump()
    if state is not None:
        data["state"] = state
    if progress is not None:
        data["progress"] = max(0.0, min(1.0, float(progress)))
    if stage is not None:
        data["stage"] = stage
    if error_code is not None:
        data["error_code"] = error_code
    if message is not None:
        data["message"] = message
    if summary is not None:
        data["summary"] = summary
    if result is not None:
        data["result"] = result
    _tasks[task_id] = LogicOnTask(**data)


def _normalize_task_error(e: Exception) -> Tuple[str, str]:
    msg = str(e).strip()
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "TIMEOUT", (msg or "处理超时")
    low = msg.lower()
    if "timeout" in low or "timed out" in low:
        return "TIMEOUT", (msg or "处理超时")
    if isinstance(e, ValueError):
        return "INVALID_INPUT", msg or "输入非法"
    return "UNKNOWN_ERROR", (msg or f"{type(e).__name__}: 未提供详细错误信息")


def _safe_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fa5]+", "_", stem).strip("_")
    return stem or "unknown"


def _save_debug_result(
    result: LogicOnResult,
    *,
    source_filename: str = "",
    report_slug: str | None = None,
) -> tuple[str, str]:
    """写入 JSON + Markdown；若提供 report_slug 则固定写入 reports/ 下（一份核验一对文件）。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source = _safe_stem(source_filename)
    if report_slug:
        base_name = _safe_stem(report_slug) or result.doc_id
        json_path = os.path.join(REPORTS_DIR, f"{base_name}.json")
        md_path = os.path.join(REPORTS_DIR, f"{base_name}.md")
    else:
        base_name = f"{source}_{result.doc_id}_{timestamp}" if source else f"{result.doc_id}_{timestamp}"
        json_path = os.path.join(DEBUG_DIR, f"{base_name}.json")
        md_path = os.path.join(DEBUG_DIR, f"{base_name}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    markdown = LogicOnReporter().build_markdown(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return json_path, md_path


def _report_slug_for_upload(*, source_filename: str, doc_id: str) -> str:
    stem = _safe_stem(source_filename)
    if stem and stem != "unknown":
        return f"{stem}__{doc_id}"
    return doc_id


async def _run_check_file_task(
    task_id: str,
    *,
    doc_id: str,
    file_data: bytes,
    file_type: str,
    doc_kind: str,
    source_filename: str = "",
    enable_llm: bool,
    return_graph: bool,
    enable_agent: bool,
    agent_max_turns: int,
    enable_equivalence_probe: bool,
    amount_tolerance_wan: float,
    date_tolerance_days: int,
    metric_tolerance_ratio: float,
) -> None:
    service = get_logicon_service()

    try:
        _update_task(task_id, progress=0.10, stage="parse", message="解析文档")
        result = await service.check_file(
            file_data=file_data,
            file_type=file_type,
            doc_kind=doc_kind,
            enable_llm=enable_llm,
            return_graph=return_graph,
            enable_agent=enable_agent,
            agent_max_turns=agent_max_turns,
            enable_equivalence_probe=enable_equivalence_probe,
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
            doc_id=doc_id,
        )
        try:
            slug = _report_slug_for_upload(source_filename=source_filename, doc_id=result.doc_id)
            json_path, md_path = _save_debug_result(result, source_filename=source_filename, report_slug=slug)
            result.warnings.append(f"调试结果已保存: {json_path} ; {md_path}")
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")
        _results[task_id] = result
        _update_task(
            task_id,
            state="finished",
            progress=1.0,
            stage="done",
            message="核验完成",
            summary=f"冲突 {len(result.conflicts)} 条",
            result=result,
        )
    except Exception as e:
        code, msg = _normalize_task_error(e)
        logger.exception("logicon async task failed: task_id=%s", task_id)
        current = _tasks.get(task_id)
        p = float(getattr(current, "progress", 0.0) or 0.0) if current else 0.0
        _update_task(task_id, state="failed", progress=min(p, 0.99), stage="error", error_code=code, message=msg)


@router.post("/check")
async def check_file(
    file: UploadFile = File(...),
    doc_kind: str = Form("auto"),
    enable_llm: bool = Form(True),
    return_graph: bool = Form(False),
    enable_agent: bool = Form(True),
    agent_max_turns: int = Form(8),
    enable_equivalence_probe: bool = Form(True),
    amount_tolerance_wan: float = Form(0.01),
    date_tolerance_days: int = Form(30),
    metric_tolerance_ratio: float = Form(0.01),
) -> ApiResponse[LogicOnResult]:
    file_data = await file.read()
    file_type = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "pdf"
    service = get_logicon_service()
    try:
        result = await service.check_file(
            file_data=file_data,
            file_type=file_type,
            doc_kind=doc_kind,
            enable_llm=enable_llm,
            return_graph=return_graph,
            enable_agent=enable_agent,
            agent_max_turns=agent_max_turns,
            enable_equivalence_probe=enable_equivalence_probe,
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
        )
        try:
            slug = _report_slug_for_upload(source_filename=file.filename or "", doc_id=result.doc_id)
            json_path, md_path = _save_debug_result(
                result,
                source_filename=file.filename or "",
                report_slug=slug,
            )
            result.warnings.append(f"调试结果已保存: {json_path} ; {md_path}")
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")
        return ApiResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-text")
async def check_text(request: LogicOnTextRequest) -> ApiResponse[LogicOnResult]:
    service = get_logicon_service()
    try:
        result = await service.check_text(
            text=request.text,
            doc_kind=request.doc_kind,
            enable_llm=request.enable_llm,
            return_graph=request.return_graph,
            enable_agent=request.enable_agent,
            agent_max_turns=request.agent_max_turns,
            enable_equivalence_probe=request.enable_equivalence_probe,
            amount_tolerance_wan=request.amount_tolerance_wan,
            date_tolerance_days=request.date_tolerance_days,
            metric_tolerance_ratio=request.metric_tolerance_ratio,
        )
        try:
            slug = _report_slug_for_upload(source_filename="check_text", doc_id=result.doc_id)
            json_path, md_path = _save_debug_result(
                result,
                source_filename="check_text",
                report_slug=slug,
            )
            result.warnings.append(f"调试结果已保存: {json_path} ; {md_path}")
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")
        return ApiResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-async")
async def check_file_async(
    file: UploadFile = File(...),
    doc_kind: str = Form("auto"),
    enable_llm: bool = Form(True),
    return_graph: bool = Form(False),
    enable_agent: bool = Form(True),
    agent_max_turns: int = Form(8),
    enable_equivalence_probe: bool = Form(True),
    amount_tolerance_wan: float = Form(0.01),
    date_tolerance_days: int = Form(30),
    metric_tolerance_ratio: float = Form(0.01),
) -> ApiResponse[LogicOnTask]:
    file_data = await file.read()
    file_type = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "pdf"
    task_id = str(uuid.uuid4())[:8]
    doc_id = f"logicon_{task_id}"
    task = _make_task(task_id=task_id, doc_id=doc_id)
    _tasks[task_id] = task
    asyncio.create_task(
        _run_check_file_task(
            task_id,
            doc_id=doc_id,
            file_data=file_data,
            file_type=file_type,
            doc_kind=doc_kind,
            source_filename=file.filename or "",
            enable_llm=enable_llm,
            return_graph=return_graph,
            enable_agent=enable_agent,
            agent_max_turns=agent_max_turns,
            enable_equivalence_probe=enable_equivalence_probe,
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
        )
    )
    return ApiResponse(status=ResponseStatus.SUCCESS, data=task)


@router.get("/{task_id}")
async def get_task(task_id: str) -> ApiResponse[LogicOnTask]:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(status=ResponseStatus.SUCCESS, data=task)
