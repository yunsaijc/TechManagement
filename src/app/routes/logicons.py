"""逻辑自洽校验 API 路由"""
from datetime import datetime
import json
import os
import re
from typing import Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.common.models import ApiResponse, ResponseStatus
from src.common.models.logicons import (
    ConflictCategory,
    LogiConsResult,
    LogiConsTask,
    LogiConsTextRequest,
    RuleConfigSnapshot,
    RuleInfo,
)
from src.services.logicons import get_logicons_service

router = APIRouter()

_results: Dict[str, LogiConsResult] = {}

DEBUG_DIR = "/home/tdkx/ljh/Tech/debug_logicons"
os.makedirs(DEBUG_DIR, exist_ok=True)


def _save_debug_result(result: LogiConsResult) -> None:
    """保存调试结果到本地目录（文件名带时间戳）。"""
    safe_project_id = re.sub(r"[^0-9A-Za-z._-]+", "_", result.project_id).strip("_")
    if not safe_project_id:
        safe_project_id = "unknown_project"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{safe_project_id}_{timestamp}_{result.check_id}.json"
    file_path = os.path.join(DEBUG_DIR, file_name)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)


@router.post("/check", response_model=ApiResponse[LogiConsResult])
async def check_file(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    budget_tolerance: float = Form(0.01),
    timeline_grace_years: int = Form(0),
    enable_llm_enhancement: bool = Form(False),
) -> ApiResponse[LogiConsResult]:
    """上传文件并执行逻辑一致性校验。"""
    try:
        file_data = await file.read()
        if not file_data:
            raise HTTPException(status_code=400, detail="文件内容不能为空")

        if not file.filename or "." not in file.filename:
            raise HTTPException(status_code=400, detail="文件名缺少后缀")

        file_type = file.filename.rsplit(".", 1)[-1].lower()
        if file_type not in {"docx", "pdf"}:
            raise HTTPException(status_code=415, detail=f"不支持的文件格式: {file_type}")

        service = get_logicons_service()
        result = await service.check_file(
            project_id=project_id,
            file_data=file_data,
            file_type=file_type,
            budget_tolerance=budget_tolerance,
            timeline_grace_years=timeline_grace_years,
            enable_llm_enhancement=enable_llm_enhancement,
        )
        _results[result.check_id] = result
        try:
            _save_debug_result(result)
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")

        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="校验完成",
            code=200,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"校验失败: {str(e)}")


@router.post("/check-text", response_model=ApiResponse[LogiConsResult])
async def check_text(request: LogiConsTextRequest) -> ApiResponse[LogiConsResult]:
    """直接提交文本执行逻辑一致性校验。"""
    try:
        service = get_logicons_service()
        result = await service.check_text(
            project_id=request.project_id,
            text=request.text,
            budget_tolerance=request.budget_tolerance,
            timeline_grace_years=request.timeline_grace_years,
            enable_llm_enhancement=request.enable_llm_enhancement,
        )
        _results[result.check_id] = result
        try:
            _save_debug_result(result)
        except Exception as e:
            result.warnings.append(f"调试结果保存失败: {str(e)}")

        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="校验完成",
            code=200,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"校验失败: {str(e)}")


@router.get("/rules", response_model=ApiResponse[RuleConfigSnapshot])
async def get_rules() -> ApiResponse[RuleConfigSnapshot]:
    """获取规则配置。"""
    snapshot = RuleConfigSnapshot(
        rules=[
            RuleInfo(code="T001", name="执行期与里程碑年份一致", category=ConflictCategory.TIMELINE),
            RuleInfo(code="T002", name="执行期年数与任务跨度一致", category=ConflictCategory.TIMELINE),
            RuleInfo(code="B001", name="资金总额与分项合计一致", category=ConflictCategory.BUDGET),
            RuleInfo(code="I001", name="同类指标跨章节一致", category=ConflictCategory.INDICATOR),
        ],
        defaults={
            "budget_tolerance": 0.01,
            "timeline_grace_years": 0,
            "enable_llm_enhancement": False,
        },
    )
    return ApiResponse(status=ResponseStatus.SUCCESS, data=snapshot, code=200)


@router.get("/{check_id}", response_model=ApiResponse[LogiConsTask])
async def get_task(check_id: str) -> ApiResponse[LogiConsTask]:
    """查询任务状态。"""
    result = _results.get(check_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {check_id} 不存在")

    task = LogiConsTask(
        check_id=result.check_id,
        project_id=result.project_id,
        state="finished",
        summary=result.summary,
    )
    return ApiResponse(status=ResponseStatus.SUCCESS, data=task, code=200)


@router.get("/{check_id}/result", response_model=ApiResponse[LogiConsResult])
async def get_result(check_id: str) -> ApiResponse[LogiConsResult]:
    """查询完整结果。"""
    result = _results.get(check_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {check_id} 不存在")

    return ApiResponse(status=ResponseStatus.SUCCESS, data=result, code=200)
