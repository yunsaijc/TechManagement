import asyncio
from datetime import datetime
import json
import logging
import os
import re
import uuid
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.common.models import ApiResponse, ResponseStatus
from src.common.models.logicon import LogicOnResult, LogicOnTask
from src.services.logicon import get_logicon_service
from src.services.logicon.reporter import LogicOnReporter


router = APIRouter()
logger = logging.getLogger(__name__)

_results: Dict[str, LogicOnResult] = {}
_tasks: Dict[str, LogicOnTask] = {}

DEBUG_DIR = "/home/tdkx/ljh/Tech/debug_logicon"
os.makedirs(DEBUG_DIR, exist_ok=True)


class LogicOnTextRequest(BaseModel):
    doc_kind: str = "auto"
    text: str
    enable_llm: bool = False
    return_graph: bool = False
    amount_tolerance_wan: float = 0.01
    date_tolerance_days: int = 30
    metric_tolerance_ratio: float = 0.01


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
) -> tuple[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source = _safe_stem(source_filename)
    base_name = f"{source}_{result.doc_id}_{timestamp}" if source else f"{result.doc_id}_{timestamp}"
    json_path = os.path.join(DEBUG_DIR, f"{base_name}.json")
    md_path = os.path.join(DEBUG_DIR, f"{base_name}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    markdown = LogicOnReporter().build_markdown(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return json_path, md_path


async def _run_check_file_task(
    task_id: str,
    *,
    doc_id: str,
    file_data: bytes,
    file_type: str,
    doc_kind: str,
    enable_llm: bool,
    return_graph: bool,
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
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
            doc_id=doc_id,
        )
        try:
            json_path, md_path = _save_debug_result(result)
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
    enable_llm: bool = Form(False),
    return_graph: bool = Form(False),
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
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
        )
        try:
            json_path, md_path = _save_debug_result(result, source_filename=file.filename or "")
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
            amount_tolerance_wan=request.amount_tolerance_wan,
            date_tolerance_days=request.date_tolerance_days,
            metric_tolerance_ratio=request.metric_tolerance_ratio,
        )
        try:
            json_path, md_path = _save_debug_result(result, source_filename="check_text")
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
    enable_llm: bool = Form(False),
    return_graph: bool = Form(False),
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
            enable_llm=enable_llm,
            return_graph=return_graph,
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
