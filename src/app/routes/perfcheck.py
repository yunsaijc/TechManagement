"""绩效核验 API 路由"""
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
from src.common.models.perfcheck import PerfCheckRequest, PerfCheckResult, PerfCheckTask
from src.services.perfcheck import get_perfcheck_service
from src.services.perfcheck.reporter import PerfCheckReporter

router = APIRouter()
logger = logging.getLogger(__name__)

DEBUG_DIR = "/home/tdkx/ljh/Tech/debug_pefcheck"
os.makedirs(DEBUG_DIR, exist_ok=True)

# 生产环境应使用持久化存储
_results: Dict[str, PerfCheckResult] = {}
_tasks: Dict[str, PerfCheckTask] = {}

_DEFAULT_DECLARATION_PDF = "/home/tdkx/ljh/Tech/tests/申报书/5e8836fc476344b382794452deef9061.pdf"
_DEFAULT_TASK_PDF = "/home/tdkx/ljh/Tech/tests/任务书/5e8836fc476344b382794452deef9061.pdf"


class PerfCheckDefaultRequest(BaseModel):
    project_id: str = "perfcheck_default_pdf"
    budget_shift_threshold: float = 0.10
    strict_mode: bool = True
    enable_llm_enhancement: bool = False
    enable_table_vision_extraction: bool = True
    enable_llm_entailment: bool = True



def _make_task(*, task_id: str, project_id: str) -> PerfCheckTask:
    return PerfCheckTask(
        task_id=task_id,
        project_id=project_id,
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
    result: Optional[PerfCheckResult] = None,
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
    _tasks[task_id] = PerfCheckTask(**data)


def _normalize_task_error(e: Exception) -> Tuple[str, str]:
    """将异常映射为稳定的错误码与可读信息。"""
    msg = str(e).strip()

    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "LLM_TIMEOUT", (msg or "LLM 调用超时，请稍后重试")

    if isinstance(e, asyncio.CancelledError):
        return "TASK_CANCELLED", (msg or "任务执行被取消或中断")

    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return "LLM_TIMEOUT", (msg or "LLM 调用超时，请稍后重试")

    return "UNKNOWN_ERROR", (msg or f"{type(e).__name__}: 未提供详细错误信息")


async def _run_compare_text_task(task_id: str, request: PerfCheckRequest) -> None:
    service = get_perfcheck_service()

    def on_progress(p: float, stage: str, msg: str = "") -> None:
        _update_task(task_id, progress=p, stage=stage, message=msg)

    try:
        result = await service.compare_text(
            project_id=request.project_id,
            declaration_text=request.declaration_text,
            task_text=request.task_text,
            budget_shift_threshold=request.budget_shift_threshold,
            strict_mode=request.strict_mode,
            enable_llm_enhancement=request.enable_llm_enhancement,
            enable_llm_entailment=request.enable_llm_entailment,
            on_progress=on_progress,
        )
        _results[result.task_id] = result
        try:
            _save_debug_result(result)
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")
        _update_task(
            task_id,
            state="finished",
            progress=1.0,
            stage="done",
            message="核验完成",
            summary=result.summary,
            result=result,
        )
    except Exception as e:
        code, msg = _normalize_task_error(e)
        logger.exception("Perfcheck compare_text async task failed: task_id=%s", task_id)
        current = _tasks.get(task_id)
        p = float(getattr(current, "progress", 0.0) or 0.0)
        _update_task(task_id, state="failed", progress=min(p, 0.99), stage="error", error_code=code, message=msg)


async def _run_compare_files_task(
    task_id: str,
    *,
    project_id: str,
    dec_bytes: bytes,
    dec_type: str,
    task_bytes: bytes,
    task_type: str,
    budget_shift_threshold: float,
    strict_mode: bool,
    enable_llm_enhancement: bool,
    enable_table_vision_extraction: bool,
    enable_llm_entailment: bool,
) -> None:
    service = get_perfcheck_service()

    def on_progress(p: float, stage: str, msg: str = "") -> None:
        _update_task(task_id, progress=p, stage=stage, message=msg)

    try:
        result = await service.compare_files(
            project_id=project_id,
            declaration_file=dec_bytes,
            declaration_file_type=dec_type,
            task_file=task_bytes,
            task_file_type=task_type,
            budget_shift_threshold=budget_shift_threshold,
            strict_mode=strict_mode,
            enable_llm_enhancement=enable_llm_enhancement,
            enable_table_vision_extraction=enable_table_vision_extraction,
            enable_llm_entailment=enable_llm_entailment,
            on_progress=on_progress,
        )
        _results[result.task_id] = result
        try:
            _save_debug_result(result)
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")
        _update_task(
            task_id,
            state="finished",
            progress=1.0,
            stage="done",
            message="核验完成",
            summary=result.summary,
            result=result,
        )
    except Exception as e:
        code, msg = _normalize_task_error(e)
        logger.exception("Perfcheck compare_files async task failed: task_id=%s", task_id)
        current = _tasks.get(task_id)
        p = float(getattr(current, "progress", 0.0) or 0.0)
        _update_task(task_id, state="failed", progress=min(p, 0.99), stage="error", error_code=code, message=msg)


def _save_debug_result(result: PerfCheckResult) -> None:
    """保存调试结果到本地目录。"""
    safe_project_id = re.sub(r"[^0-9A-Za-z._-]+", "_", result.project_id).strip("_")
    if not safe_project_id:
        safe_project_id = "unknown_project"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{safe_project_id}_{timestamp}_{result.task_id}"

    json_path = os.path.join(DEBUG_DIR, f"{base_name}.json")
    md_path = os.path.join(DEBUG_DIR, f"{base_name}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    markdown = PerfCheckReporter().build_markdown(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)


@router.post("/compare", response_model=ApiResponse[PerfCheckResult])
async def compare_files(
    declaration_file: UploadFile = File(...),
    task_file: UploadFile = File(...),
    project_id: str = Form(...),
    budget_shift_threshold: float = Form(0.10),
    strict_mode: bool = Form(True),
    enable_llm_enhancement: bool = Form(False),
    enable_table_vision_extraction: bool = Form(True),
    enable_llm_entailment: bool = Form(True),
) -> ApiResponse[PerfCheckResult]:
    """上传申报书与任务书文件，执行绩效核验。"""
    try:
        dec_bytes = await declaration_file.read()
        task_bytes = await task_file.read()
        if not dec_bytes or not task_bytes:
            raise HTTPException(status_code=400, detail="文件内容不能为空")

        dec_type = declaration_file.filename.rsplit(".", 1)[-1].lower()
        task_type = task_file.filename.rsplit(".", 1)[-1].lower()

        service = get_perfcheck_service()
        result = await service.compare_files(
            project_id=project_id,
            declaration_file=dec_bytes,
            declaration_file_type=dec_type,
            task_file=task_bytes,
            task_file_type=task_type,
            budget_shift_threshold=budget_shift_threshold,
            strict_mode=strict_mode,
            enable_llm_enhancement=enable_llm_enhancement,
            enable_table_vision_extraction=enable_table_vision_extraction,
            enable_llm_entailment=enable_llm_entailment,
        )
        _results[result.task_id] = result
        try:
            _save_debug_result(result)
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")

        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="核验完成",
            code=200,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"核验失败: {str(e)}")


@router.post("/compare-async", response_model=ApiResponse[PerfCheckTask])
async def compare_files_async(
    declaration_file: UploadFile = File(...),
    task_file: UploadFile = File(...),
    project_id: str = Form(...),
    budget_shift_threshold: float = Form(0.10),
    strict_mode: bool = Form(True),
    enable_llm_enhancement: bool = Form(False),
    enable_table_vision_extraction: bool = Form(True),
    enable_llm_entailment: bool = Form(True),
) -> ApiResponse[PerfCheckTask]:
    try:
        dec_bytes = await declaration_file.read()
        task_bytes = await task_file.read()
        if not dec_bytes or not task_bytes:
            raise HTTPException(status_code=400, detail="文件内容不能为空")

        dec_type = declaration_file.filename.rsplit(".", 1)[-1].lower()
        task_type = task_file.filename.rsplit(".", 1)[-1].lower()

        task_id = uuid.uuid4().hex[:12]
        task = _make_task(task_id=task_id, project_id=project_id)
        _tasks[task_id] = task

        asyncio.create_task(
            _run_compare_files_task(
                task_id,
                project_id=project_id,
                dec_bytes=dec_bytes,
                dec_type=dec_type,
                task_bytes=task_bytes,
                task_type=task_type,
                budget_shift_threshold=budget_shift_threshold,
                strict_mode=strict_mode,
                enable_llm_enhancement=enable_llm_enhancement,
                enable_table_vision_extraction=enable_table_vision_extraction,
                enable_llm_entailment=enable_llm_entailment,
            )
        )

        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200, message="任务已提交")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务提交失败: {str(e)}")


@router.post("/compare-text", response_model=ApiResponse[PerfCheckResult])
async def compare_text(request: PerfCheckRequest) -> ApiResponse[PerfCheckResult]:
    """直接提交两份文本执行核验。"""
    try:
        service = get_perfcheck_service()
        result = await service.compare_text(
            project_id=request.project_id,
            declaration_text=request.declaration_text,
            task_text=request.task_text,
            budget_shift_threshold=request.budget_shift_threshold,
            strict_mode=request.strict_mode,
            enable_llm_enhancement=request.enable_llm_enhancement,
            enable_llm_entailment=request.enable_llm_entailment,
        )
        _results[result.task_id] = result
        try:
            _save_debug_result(result)
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")

        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="核验完成",
            code=200,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"核验失败: {str(e)}")


@router.post("/compare-default-async", response_model=ApiResponse[PerfCheckTask])
async def compare_default_async(request: PerfCheckDefaultRequest) -> ApiResponse[PerfCheckTask]:
    try:
        if not os.path.exists(_DEFAULT_DECLARATION_PDF):
            raise HTTPException(status_code=404, detail=f"默认申报书不存在: {_DEFAULT_DECLARATION_PDF}")
        if not os.path.exists(_DEFAULT_TASK_PDF):
            raise HTTPException(status_code=404, detail=f"默认任务书不存在: {_DEFAULT_TASK_PDF}")

        with open(_DEFAULT_DECLARATION_PDF, "rb") as f:
            dec_bytes = f.read()
        with open(_DEFAULT_TASK_PDF, "rb") as f:
            task_bytes = f.read()

        task_id = uuid.uuid4().hex[:12]
        task = _make_task(task_id=task_id, project_id=request.project_id)
        _tasks[task_id] = task

        asyncio.create_task(
            _run_compare_files_task(
                task_id,
                project_id=request.project_id,
                dec_bytes=dec_bytes,
                dec_type="pdf",
                task_bytes=task_bytes,
                task_type="pdf",
                budget_shift_threshold=request.budget_shift_threshold,
                strict_mode=request.strict_mode,
                enable_llm_enhancement=request.enable_llm_enhancement,
                enable_table_vision_extraction=request.enable_table_vision_extraction,
                enable_llm_entailment=request.enable_llm_entailment,
            )
        )
        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200, message="默认用例任务已提交")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务提交失败: {str(e)}")


@router.post("/compare-text-async", response_model=ApiResponse[PerfCheckTask])
async def compare_text_async(request: PerfCheckRequest) -> ApiResponse[PerfCheckTask]:
    try:
        task_id = uuid.uuid4().hex[:12]
        task = _make_task(task_id=task_id, project_id=request.project_id)
        _tasks[task_id] = task
        asyncio.create_task(_run_compare_text_task(task_id, request))
        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200, message="任务已提交")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务提交失败: {str(e)}")


@router.get("/{task_id}", response_model=ApiResponse[PerfCheckTask])
async def get_task(task_id: str) -> ApiResponse[PerfCheckTask]:
    """查询核验任务状态。"""
    task = _tasks.get(task_id)
    if task is not None:
        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200)

    result = _results.get(task_id)
    if result is not None:
        task = PerfCheckTask(
            task_id=result.task_id,
            project_id=result.project_id,
            state="finished",
            progress=1.0,
            stage="done",
            message="核验完成",
            summary=result.summary,
            result=result,
        )
        _tasks[task_id] = task
        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200)

    raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")


@router.get("/{task_id}/report", response_model=ApiResponse[str])
async def get_report(task_id: str, format: str = "markdown") -> ApiResponse[str]:
    """获取核验报告。"""
    result = _results.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    if format not in {"markdown", "json"}:
        raise HTTPException(status_code=400, detail="仅支持 format=markdown 或 format=json")

    if format == "json":
        report = result.model_dump_json(ensure_ascii=False, indent=2)
    else:
        report = PerfCheckReporter().build_markdown(result)

    return ApiResponse(status=ResponseStatus.SUCCESS, data=report, code=200)
