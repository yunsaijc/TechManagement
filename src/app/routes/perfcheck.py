"""绩效核验 API 路由"""
import asyncio
from datetime import datetime
import hashlib
import json
import logging
import os
import re
import uuid
from typing import Dict, Optional, Tuple
from pathlib import Path

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
_cache_index: Dict[str, Dict[str, object]] = {}
_task_to_cache_key: Dict[str, str] = {}

_CACHE_TTL_SECONDS = int(os.getenv("PERFCHECK_CACHE_TTL_SECONDS", str(7 * 24 * 60 * 60)))
_CACHE_MAX_ENTRIES = int(os.getenv("PERFCHECK_CACHE_MAX_ENTRIES", "500"))

_DEFAULT_DECLARATION_PDF = "/home/tdkx/ljh/Tech/tests/申报书/5e8836fc476344b382794452deef9061.pdf"
_DEFAULT_TASK_PDF = "/home/tdkx/ljh/Tech/tests/任务书/5e8836fc476344b382794452deef9061.pdf"
_DEFAULT_PROJECT_ID = "default_project"
_FIXED_BATCH_DIR = Path("/home/tdkx/ljh/Tech/debug_perfcheck/debug/batch_perfcheck_20260403_100019")


class PerfCheckDefaultRequest(BaseModel):
    project_id: str = "perfcheck_default_pdf"
    budget_shift_threshold: float = 0.10
    strict_mode: bool = True
    enable_llm_enhancement: bool = False
    enable_table_vision_extraction: bool = True
    enable_llm_entailment: bool = True


class FixedPerfCheckResultInfo(BaseModel):
    project_id: str
    task_id: str = ""
    summary: str = ""
    result_path: str = ""
    report_path: str = ""
    updated_at: float = 0.0



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


def _normalize_project_id(project_id: Optional[str]) -> str:
    text = str(project_id or "").strip()
    return text or _DEFAULT_PROJECT_ID


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
        old_id = result.task_id
        result.task_id = task_id
        _results[task_id] = result
        if old_id and old_id != task_id:
            _results[old_id] = result
        try:
            _save_debug_result(result, debug_task_id=task_id)
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
        cache_key = _task_to_cache_key.pop(task_id, None)
        if cache_key:
            _cache_index.pop(cache_key, None)


async def _run_compare_files_task(
    task_id: str,
    *,
    project_id: str,
    dec_bytes: bytes,
    dec_type: str,
    dec_filename: str = "",
    task_bytes: bytes,
    task_type: str,
    task_filename: str = "",
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
        old_id = result.task_id
        result.task_id = task_id
        _results[task_id] = result
        if old_id and old_id != task_id:
            _results[old_id] = result
        try:
            _save_debug_result(
                result,
                debug_task_id=task_id,
                declaration_filename=dec_filename,
                task_filename=task_filename,
            )
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
        cache_key = _task_to_cache_key.pop(task_id, None)
        if cache_key:
            _cache_index.pop(cache_key, None)


def _safe_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fa5]+", "_", stem).strip("_")
    return stem or "unknown"


def _save_debug_result(
    result: PerfCheckResult,
    *,
    debug_task_id: Optional[str] = None,
    declaration_filename: str = "",
    task_filename: str = "",
) -> None:
    """保存调试结果到本地目录。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dec_stem = _safe_stem(declaration_filename)
    task_stem = _safe_stem(task_filename)
    if dec_stem == task_stem:
        base_name = f"{dec_stem}_{timestamp}"
    else:
        base_name = f"{dec_stem}_vs_{task_stem}_{timestamp}"

    json_path = os.path.join(DEBUG_DIR, f"{base_name}.json")
    md_path = os.path.join(DEBUG_DIR, f"{base_name}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    markdown = PerfCheckReporter().build_markdown(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    if debug_task_id:
        stable_json_path = os.path.join(DEBUG_DIR, f"task_{debug_task_id}.json")
        stable_md_path = os.path.join(DEBUG_DIR, f"task_{debug_task_id}.md")
        with open(stable_json_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        with open(stable_md_path, "w", encoding="utf-8") as f:
            f.write(markdown)


def _load_debug_result(task_id: str) -> Optional[PerfCheckResult]:
    path = os.path.join(DEBUG_DIR, f"task_{task_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PerfCheckResult(**data)
    except Exception:
        return None


def _load_fixed_batch_latest_result() -> Optional[PerfCheckResult]:
    if not _FIXED_BATCH_DIR.exists() or not _FIXED_BATCH_DIR.is_dir():
        return None

    candidates = []
    for entry in _FIXED_BATCH_DIR.iterdir():
        if not entry.is_dir():
            continue
        result_file = entry / "result.json"
        if result_file.exists() and result_file.is_file():
            candidates.append((result_file.stat().st_mtime, result_file))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, result_file in candidates:
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return PerfCheckResult(**payload)
        except Exception:
            continue
    return None


def _load_fixed_batch_result_infos() -> list[FixedPerfCheckResultInfo]:
    if not _FIXED_BATCH_DIR.exists() or not _FIXED_BATCH_DIR.is_dir():
        return []

    items: list[tuple[float, FixedPerfCheckResultInfo]] = []
    for entry in _FIXED_BATCH_DIR.iterdir():
        if not entry.is_dir():
            continue
        result_file = entry / "result.json"
        if not result_file.exists() or not result_file.is_file():
            continue
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            info = FixedPerfCheckResultInfo(
                project_id=str(payload.get("project_id") or entry.name),
                task_id=str(payload.get("task_id") or ""),
                summary=str(payload.get("summary") or ""),
                result_path=str(result_file),
                report_path=str(entry / "report.md"),
                updated_at=result_file.stat().st_mtime,
            )
            items.append((info.updated_at, info))
        except Exception:
            continue

    items.sort(key=lambda item: item[0], reverse=True)
    return [info for _, info in items]

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_cache_key_files(
    *,
    project_id: str,
    declaration_bytes: bytes,
    declaration_type: str,
    task_bytes: bytes,
    task_type: str,
    budget_shift_threshold: float,
    strict_mode: bool,
    enable_llm_enhancement: bool,
    enable_table_vision_extraction: bool,
    enable_llm_entailment: bool,
) -> str:
    payload = {
        "cache_version": 3,
        "kind": "compare_files",
        "project_id": project_id or "",
        "declaration_sha256": _sha256_bytes(declaration_bytes),
        "declaration_type": declaration_type or "",
        "task_sha256": _sha256_bytes(task_bytes),
        "task_type": task_type or "",
        "budget_shift_threshold": float(budget_shift_threshold),
        "strict_mode": bool(strict_mode),
        "enable_llm_enhancement": bool(enable_llm_enhancement),
        "enable_table_vision_extraction": bool(enable_table_vision_extraction),
        "enable_llm_entailment": bool(enable_llm_entailment),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _make_cache_key_text(
    *,
    project_id: str,
    declaration_text: str,
    task_text: str,
    budget_shift_threshold: float,
    strict_mode: bool,
    enable_llm_enhancement: bool,
    enable_llm_entailment: bool,
) -> str:
    payload = {
        "cache_version": 3,
        "kind": "compare_text",
        "project_id": project_id or "",
        "declaration_sha256": hashlib.sha256((declaration_text or "").encode("utf-8")).hexdigest(),
        "task_sha256": hashlib.sha256((task_text or "").encode("utf-8")).hexdigest(),
        "budget_shift_threshold": float(budget_shift_threshold),
        "strict_mode": bool(strict_mode),
        "enable_llm_enhancement": bool(enable_llm_enhancement),
        "enable_llm_entailment": bool(enable_llm_entailment),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _purge_cache() -> None:
    now = datetime.now().timestamp()
    expired = []
    for k, v in _cache_index.items():
        saved_at = float(v.get("saved_at", 0.0) or 0.0)
        if saved_at <= 0 or (now - saved_at) > float(_CACHE_TTL_SECONDS):
            expired.append(k)
    for k in expired:
        _cache_index.pop(k, None)
    if len(_cache_index) <= _CACHE_MAX_ENTRIES:
        return
    items = sorted(_cache_index.items(), key=lambda kv: float(kv[1].get("saved_at", 0.0) or 0.0))
    for k, _ in items[: max(0, len(items) - _CACHE_MAX_ENTRIES)]:
        _cache_index.pop(k, None)


def _get_task_or_result(task_id: str) -> Optional[PerfCheckTask]:
    task = _tasks.get(task_id)
    if task is not None:
        return task
    result = _results.get(task_id)
    if result is None:
        return None
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
    return task


@router.post("/compare", response_model=ApiResponse[PerfCheckResult])
async def compare_files(
    declaration_file: UploadFile = File(...),
    task_file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
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
        normalized_project_id = _normalize_project_id(project_id)

        service = get_perfcheck_service()
        result = await service.compare_files(
            project_id=normalized_project_id,
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
            _save_debug_result(
                result,
                declaration_filename=declaration_file.filename or "declaration",
                task_filename=task_file.filename or "task",
            )
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
    project_id: Optional[str] = Form(None),
    budget_shift_threshold: float = Form(0.10),
    strict_mode: bool = Form(True),
    enable_llm_enhancement: bool = Form(False),
    enable_table_vision_extraction: bool = Form(True),
    enable_llm_entailment: bool = Form(True),
) -> ApiResponse[PerfCheckTask]:
    try:
        _purge_cache()
        dec_bytes = await declaration_file.read()
        task_bytes = await task_file.read()
        if not dec_bytes or not task_bytes:
            raise HTTPException(status_code=400, detail="文件内容不能为空")

        dec_type = declaration_file.filename.rsplit(".", 1)[-1].lower()
        task_type = task_file.filename.rsplit(".", 1)[-1].lower()
        normalized_project_id = _normalize_project_id(project_id)

        cache_key = _make_cache_key_files(
            project_id=normalized_project_id,
            declaration_bytes=dec_bytes,
            declaration_type=dec_type,
            task_bytes=task_bytes,
            task_type=task_type,
            budget_shift_threshold=budget_shift_threshold,
            strict_mode=strict_mode,
            enable_llm_enhancement=enable_llm_enhancement,
            enable_table_vision_extraction=enable_table_vision_extraction,
            enable_llm_entailment=enable_llm_entailment,
        )
        cached = _cache_index.get(cache_key)
        if cached and isinstance(cached.get("task_id"), str):
            cached_task_id = str(cached["task_id"])
            task = _get_task_or_result(cached_task_id)
            if task is not None and getattr(task, "state", "") != "failed":
                return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200, message="命中缓存任务")
            _cache_index.pop(cache_key, None)

        task_id = uuid.uuid4().hex[:12]
        task = _make_task(task_id=task_id, project_id=normalized_project_id)
        _tasks[task_id] = task
        _task_to_cache_key[task_id] = cache_key
        _cache_index[cache_key] = {"task_id": task_id, "saved_at": datetime.now().timestamp()}

        asyncio.create_task(
            _run_compare_files_task(
                task_id,
            project_id=normalized_project_id,
                dec_bytes=dec_bytes,
                dec_type=dec_type,
                dec_filename=declaration_file.filename or "declaration",
                task_bytes=task_bytes,
                task_type=task_type,
                task_filename=task_file.filename or "task",
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
                dec_filename=os.path.basename(_DEFAULT_DECLARATION_PDF),
                task_bytes=task_bytes,
                task_type="pdf",
                task_filename=os.path.basename(_DEFAULT_TASK_PDF),
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
        _purge_cache()
        cache_key = _make_cache_key_text(
            project_id=_normalize_project_id(request.project_id),
            declaration_text=request.declaration_text or "",
            task_text=request.task_text or "",
            budget_shift_threshold=request.budget_shift_threshold,
            strict_mode=request.strict_mode,
            enable_llm_enhancement=request.enable_llm_enhancement,
            enable_llm_entailment=request.enable_llm_entailment,
        )
        cached = _cache_index.get(cache_key)
        if cached and isinstance(cached.get("task_id"), str):
            cached_task_id = str(cached["task_id"])
            task = _get_task_or_result(cached_task_id)
            if task is not None and getattr(task, "state", "") != "failed":
                return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200, message="命中缓存任务")
            _cache_index.pop(cache_key, None)

        task_id = uuid.uuid4().hex[:12]
        task = _make_task(task_id=task_id, project_id=request.project_id)
        _tasks[task_id] = task
        _task_to_cache_key[task_id] = cache_key
        _cache_index[cache_key] = {"task_id": task_id, "saved_at": datetime.now().timestamp()}
        asyncio.create_task(_run_compare_text_task(task_id, request))
        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200, message="任务已提交")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务提交失败: {str(e)}")


@router.get("/debug-fixed-result", response_model=ApiResponse[PerfCheckResult])
async def get_debug_fixed_result() -> ApiResponse[PerfCheckResult]:
    """读取固定批次目录中的最新核验结果（用于前端直接展示）。"""
    result = _load_fixed_batch_latest_result()
    if result is None:
        raise HTTPException(status_code=404, detail=f"固定批次结果不存在或解析失败: {_FIXED_BATCH_DIR}")
    return ApiResponse(status=ResponseStatus.SUCCESS, data=result, code=200, message="已加载固定批次核验结果")


@router.get("/debug-fixed-results", response_model=ApiResponse[list[FixedPerfCheckResultInfo]])
async def get_debug_fixed_results() -> ApiResponse[list[FixedPerfCheckResultInfo]]:
    """读取固定批次目录下的所有核验结果清单。"""
    results = _load_fixed_batch_result_infos()
    if not results:
        raise HTTPException(status_code=404, detail=f"固定批次结果不存在或解析失败: {_FIXED_BATCH_DIR}")
    return ApiResponse(status=ResponseStatus.SUCCESS, data=results, code=200, message="已加载固定批次结果清单")


@router.get("/debug-fixed-result/by-project", response_model=ApiResponse[PerfCheckResult])
async def get_debug_fixed_result_by_project(project_id: str) -> ApiResponse[PerfCheckResult]:
    """按 project_id 读取固定批次中的核验结果。"""
    normalized = str(project_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="project_id 不能为空")

    result_file = _FIXED_BATCH_DIR / normalized / "result.json"
    if not result_file.exists() or not result_file.is_file():
        raise HTTPException(status_code=404, detail=f"固定批次结果不存在: {normalized}")

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        result = PerfCheckResult(**payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"结果解析失败: {str(e)}")
    return ApiResponse(status=ResponseStatus.SUCCESS, data=result, code=200, message="已加载固定批次核验结果")


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

    loaded = _load_debug_result(task_id)
    if loaded is not None:
        task = PerfCheckTask(
            task_id=loaded.task_id,
            project_id=loaded.project_id,
            state="finished",
            progress=1.0,
            stage="done",
            message="核验完成",
            summary=loaded.summary,
            result=loaded,
        )
        _results[task_id] = loaded
        _tasks[task_id] = task
        return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200)

    raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")


@router.get("/{task_id}/report", response_model=ApiResponse[str])
async def get_report(task_id: str, format: str = "markdown") -> ApiResponse[str]:
    """获取核验报告。"""
    result = _results.get(task_id)
    if result is None:
        loaded = _load_debug_result(task_id)
        if loaded is None:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        result = loaded
        _results[task_id] = result

    if format not in {"markdown", "json"}:
        raise HTTPException(status_code=400, detail="仅支持 format=markdown 或 format=json")

    if format == "json":
        report = result.model_dump_json(ensure_ascii=False, indent=2)
    else:
        report = PerfCheckReporter().build_markdown(result)

    return ApiResponse(status=ResponseStatus.SUCCESS, data=report, code=200)
