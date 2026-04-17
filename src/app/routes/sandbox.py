"""Sandbox 研发链路 API 路由。"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.services.sandbox.briefing_orchestrator_step4 import main as step4_main
from src.services.sandbox.graph_rag_step5 import main as step5_main
from src.services.sandbox.hotspot_migration_step2 import main as step2_main
from src.services.sandbox.leadership_sandbox_orchestrator import (
    load_latest_leadership_report,
    run_leadership_sandbox,
)
from src.services.sandbox.macro_insight_step3 import main as step3_main
from src.services.sandbox.neo4j_gds_preflight import main as step1_main

router = APIRouter()
_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sandbox-job")
_JOB_LOCK = Lock()
_LEADERSHIP_JOBS: dict[str, dict[str, object]] = {}


class LeadershipForecastRequest(BaseModel):
    question: str | None = None
    runPreflight: bool = False
    mode: str = "quick"
    forceRefresh: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_job(job_id: str, **kwargs: object) -> None:
    with _JOB_LOCK:
        item = _LEADERSHIP_JOBS.get(job_id)
        if not item:
            return
        item.update(kwargs)


def _run_leadership_job(job_id: str, payload: LeadershipForecastRequest) -> None:
    def _progress_cb(event: dict[str, object]) -> None:
        output = event.get("output") if isinstance(event.get("output"), dict) else None
        _set_job(
            job_id,
            state="running",
            progress=int(event.get("progress", 0) or 0),
            step=str(event.get("step", "")),
            message=str(event.get("message", "")),
            partialOutput=output,
            updatedAt=_now_iso(),
        )

    try:
        _set_job(job_id, state="running", progress=3, step="queue", message="任务已启动", updatedAt=_now_iso())
        report = run_leadership_sandbox(
            payload.question,
            payload.runPreflight,
            payload.mode,
            payload.forceRefresh,
            _progress_cb,
        )
        _set_job(
            job_id,
            state="completed",
            progress=100,
            step="done",
            message="推演完成",
            updatedAt=_now_iso(),
            finishedAt=_now_iso(),
            report=report,
        )
    except Exception as exc:  # noqa: BLE001
        _set_job(
            job_id,
            state="failed",
            progress=100,
            step="error",
            message=f"推演失败: {exc}",
            error=str(exc),
            updatedAt=_now_iso(),
            finishedAt=_now_iso(),
        )


def _run_step(step_name: str, fn) -> dict[str, object]:
    code = int(fn())
    if code != 0:
        raise HTTPException(status_code=500, detail=f"{step_name} 执行失败，退出码={code}")
    return {"step": step_name, "code": code, "status": "ok"}


@router.get("/health")
async def sandbox_health() -> dict[str, str]:
    """Sandbox 路由健康检查。"""
    return {"status": "healthy", "service": "sandbox"}


@router.post("/step1/preflight")
async def run_step1_preflight() -> dict[str, object]:
    """执行 Step1：Neo4j + GDS 预检。"""
    return await run_in_threadpool(_run_step, "step1_preflight", step1_main)


@router.post("/step2/hotspot")
async def run_step2_hotspot() -> dict[str, object]:
    """执行 Step2：热点迁移分析。"""
    return await run_in_threadpool(_run_step, "step2_hotspot", step2_main)


@router.post("/step3/insight")
async def run_step3_insight() -> dict[str, object]:
    """执行 Step3：宏观研判规则引擎。"""
    return await run_in_threadpool(_run_step, "step3_insight", step3_main)


@router.post("/step4/briefing")
async def run_step4_briefing() -> dict[str, object]:
    """执行 Step4：领导简报编排。"""
    return await run_in_threadpool(_run_step, "step4_briefing", step4_main)


@router.post("/step5/graphrag")
async def run_step5_graphrag() -> dict[str, object]:
    """执行 Step5：GraphRAG。"""
    return await run_in_threadpool(_run_step, "step5_graphrag", step5_main)


@router.post("/pipeline/step3-5")
async def run_pipeline_step3_5() -> dict[str, object]:
    """串行执行 Step3 -> Step4 -> Step5。"""
    result_step3 = await run_in_threadpool(_run_step, "step3_insight", step3_main)
    result_step4 = await run_in_threadpool(_run_step, "step4_briefing", step4_main)
    result_step5 = await run_in_threadpool(_run_step, "step5_graphrag", step5_main)
    return {
        "status": "ok",
        "pipeline": "step3_5",
        "results": [result_step3, result_step4, result_step5],
    }


@router.post("/pipeline/leadership-forecast")
async def run_pipeline_leadership_forecast(payload: LeadershipForecastRequest) -> dict[str, object]:
    """执行 Step2 -> Step5 协同推演，输出领导视角趋势预判。"""
    try:
        report = await run_in_threadpool(
            run_leadership_sandbox,
            payload.question,
            payload.runPreflight,
            payload.mode,
            payload.forceRefresh,
            None,
        )
        return report
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/pipeline/leadership-forecast/start")
async def start_pipeline_leadership_forecast(payload: LeadershipForecastRequest) -> dict[str, object]:
    """异步启动 Step2 -> Step5 推演任务，立即返回任务ID。"""
    job_id = uuid4().hex
    now = _now_iso()
    with _JOB_LOCK:
        _LEADERSHIP_JOBS[job_id] = {
            "jobId": job_id,
            "state": "queued",
            "progress": 0,
            "step": "queued",
            "message": "任务排队中",
            "error": "",
            "createdAt": now,
            "updatedAt": now,
            "finishedAt": "",
            "partialOutput": None,
            "report": None,
        }

    _JOB_EXECUTOR.submit(_run_leadership_job, job_id, payload)
    return {
        "status": "accepted",
        "jobId": job_id,
        "state": "queued",
        "progress": 0,
        "message": "任务已提交",
    }


@router.get("/pipeline/leadership-forecast/jobs/{job_id}")
async def get_pipeline_leadership_forecast_job(job_id: str) -> dict[str, object]:
    """查询异步推演任务进度和结果。"""
    with _JOB_LOCK:
        item = _LEADERSHIP_JOBS.get(job_id)
        if not item:
            raise HTTPException(status_code=404, detail="任务不存在")

        state = str(item.get("state", "queued"))
        result: dict[str, object] = {
            "status": "ok",
            "jobId": job_id,
            "state": state,
            "progress": int(item.get("progress", 0) or 0),
            "step": str(item.get("step", "")),
            "message": str(item.get("message", "")),
            "error": str(item.get("error", "")),
            "createdAt": str(item.get("createdAt", "")),
            "updatedAt": str(item.get("updatedAt", "")),
            "finishedAt": str(item.get("finishedAt", "")),
        }
        if isinstance(item.get("partialOutput"), dict):
            result["partialOutput"] = item.get("partialOutput")
        if state == "completed" and item.get("report"):
            result["report"] = item.get("report")
        return result


@router.get("/pipeline/leadership-forecast/latest")
async def get_latest_leadership_forecast() -> dict[str, object]:
    """读取最新一次领导视角推演结果。"""
    report = await run_in_threadpool(load_latest_leadership_report)
    if not report:
        raise HTTPException(status_code=404, detail="尚未生成领导推演结果")
    return {
        "status": "ok",
        "source": "latest_report",
        "report": report,
    }
