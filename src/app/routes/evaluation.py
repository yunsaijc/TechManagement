"""
正文评审服务 API 路由

提供正文评审相关的 REST 接口。
"""
import asyncio
import json
import os
import statistics
import tempfile
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from src.common.models.evaluation import (
    BatchEvaluationRequest,
    BatchEvaluationResult,
    DimensionCheckItem,
    DimensionInfo,
    DimensionsResponse,
    EvaluationChatAskRequest,
    EvaluationChatAskResponse,
    EvaluationRequest,
    EvaluationResult,
    WeightValidateRequest,
    WeightValidateResponse,
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
)
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.config import evaluation_config


router = APIRouter(tags=["正文评审"])

_agent: Optional[EvaluationAgent] = None


def get_agent() -> EvaluationAgent:
    """获取 Agent 单例"""
    global _agent
    if _agent is None:
        _agent = EvaluationAgent()
    return _agent


@router.post("", response_model=EvaluationResult)
@router.post("/evaluate", response_model=EvaluationResult)
async def evaluate_project(request: EvaluationRequest):
    """单项目评审（按 project_id）"""
    agent = get_agent()
    try:
        return await agent.evaluate_by_project(request)
    except ValueError as e:
        detail = str(e)
        if detail.startswith("项目不存在"):
            raise HTTPException(status_code=404, detail=detail)
        if detail.startswith("未找到项目申报文档"):
            raise HTTPException(status_code=422, detail=detail)
        if detail.startswith("PARSE_ERROR"):
            raise HTTPException(status_code=422, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/evaluate/file", response_model=EvaluationResult)
async def evaluate_file(
    file: UploadFile = File(..., description="项目申报书文档（Word/PDF）"),
    project_id: str = Form(..., description="项目ID"),
    dimensions: Optional[str] = Form(None, description="评审维度，逗号分隔"),
    weights: Optional[str] = Form(None, description="权重配置，JSON格式"),
    include_sections: Optional[str] = Form(None, description="评审章节，逗号分隔"),
    enable_highlight: bool = Form(False, description="是否启用划重点"),
    enable_industry_fit: bool = Form(False, description="是否启用产业指南贴合"),
    enable_benchmark: bool = Form(False, description="是否启用技术摸底"),
    enable_chat_index: bool = Form(False, description="是否启用聊天索引"),
):
    """通过上传文件执行评审"""
    agent = get_agent()

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        dim_list = [d.strip() for d in dimensions.split(",")] if dimensions else None
        weight_dict = json.loads(weights) if weights else None
        section_list = [s.strip() for s in include_sections.split(",")] if include_sections else []

        request = EvaluationRequest(
            project_id=project_id,
            dimensions=dim_list,
            weights=weight_dict,
            include_sections=section_list,
            enable_highlight=enable_highlight,
            enable_industry_fit=enable_industry_fit,
            enable_benchmark=enable_benchmark,
            enable_chat_index=enable_chat_index,
        )
        return await agent.evaluate(request, file_path=tmp_path, source_name=file.filename or "")
    except ValueError as e:
        detail = str(e)
        if detail.startswith("PARSE_ERROR"):
            raise HTTPException(status_code=422, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    finally:
        os.unlink(tmp_path)


@router.post("/chat/ask", response_model=EvaluationChatAskResponse)
async def ask_question(request: EvaluationChatAskRequest):
    """基于评审结果执行问答"""
    agent = get_agent()
    try:
        return await agent.ask(
            evaluation_id=request.evaluation_id,
            question=request.question,
        )
    except ValueError as e:
        detail = str(e)
        if detail.startswith("评审记录不存在"):
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)


@router.post("/batch", response_model=BatchEvaluationResult)
async def batch_evaluate(request: BatchEvaluationRequest):
    """批量评审"""
    agent = get_agent()
    semaphore = asyncio.Semaphore(request.concurrency)

    results: List[EvaluationResult] = []
    errors: List[Dict[str, str]] = []

    async def evaluate_one(project_id: str):
        async with semaphore:
            one_request = EvaluationRequest(
                project_id=project_id,
                weights=request.weights,
            )
            return await agent.evaluate_by_project(one_request)

    tasks = [evaluate_one(project_id) for project_id in request.project_ids]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for project_id, item in zip(request.project_ids, raw_results):
        if isinstance(item, Exception):
            errors.append({"project_id": project_id, "error": str(item)})
        else:
            results.append(item)

    summary = _build_batch_summary(results)

    return BatchEvaluationResult(
        total=len(request.project_ids),
        success=len(results),
        failed=len(errors),
        results=results,
        summary=summary,
        errors=errors,
    )


@router.get("/dimensions", response_model=DimensionsResponse)
async def list_dimensions():
    """列出所有评审维度"""
    agent = get_agent()
    dimensions = await agent.list_dimensions()

    dim_infos = []
    for dim in dimensions:
        check_items = [
            DimensionCheckItem(
                name=item.get("name", ""),
                weight=float(item.get("weight", 0)) if item.get("weight") else 0,
                description=item.get("description", ""),
            )
            for item in dim.get("check_items", [])
        ]

        dim_infos.append(
            DimensionInfo(
                code=dim["code"],
                name=dim["name"],
                category=dim["category"],
                description=dim.get("description", ""),
                default_weight=dim["default_weight"],
                check_items=check_items,
                required_sections=dim.get("required_sections", []),
            )
        )

    return DimensionsResponse(dimensions=dim_infos)


@router.get("/dimensions/{dimension}", response_model=DimensionInfo)
async def get_dimension(dimension: str):
    """获取指定维度详情"""
    agent = get_agent()
    dim = await agent.get_dimension_info(dimension)
    if not dim:
        raise HTTPException(status_code=404, detail=f"维度不存在: {dimension}")

    check_items = [
        DimensionCheckItem(
            name=item.get("name", ""),
            weight=float(item.get("weight", 0)) if item.get("weight") else 0,
            description=item.get("description", ""),
        )
        for item in dim.get("check_items", [])
    ]

    return DimensionInfo(
        code=dim["code"],
        name=dim["name"],
        category=dim["category"],
        description=dim.get("description", ""),
        default_weight=dim["default_weight"],
        check_items=check_items,
        required_sections=dim.get("required_sections", []),
    )


@router.post("/weights/validate", response_model=WeightValidateResponse)
async def validate_weights(request: WeightValidateRequest):
    """验证权重配置"""
    valid, message, normalized = evaluation_config.validate_weights(request.weights)
    return WeightValidateResponse(
        valid=valid,
        message=message,
        normalized_weights=normalized if valid else None,
        errors=None if valid else [{"message": message}],
    )


@router.get("/weights/default")
@router.get("/weights/templates")
async def get_default_weights():
    """获取默认权重配置"""
    return {
        "weights": {
            dim: {
                "name": DIMENSION_NAMES.get(dim, dim),
                "weight": weight,
            }
            for dim, weight in DEFAULT_WEIGHTS.items()
        }
    }


@router.get("/history/{project_id}", response_model=List[EvaluationResult])
async def get_evaluation_history(project_id: str):
    """获取项目评审历史"""
    agent = get_agent()
    return await agent.get_evaluation_history(project_id)


@router.get("/statistics")
async def get_statistics():
    """获取评审统计信息"""
    agent = get_agent()
    return await agent.storage.get_statistics()


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "evaluation"}


@router.get("/{project_id}", response_model=EvaluationResult)
async def get_evaluation(
    project_id: str,
    refresh: bool = Query(default=False, description="是否强制重新评审"),
):
    """获取项目评审结果（支持 refresh）"""
    agent = get_agent()
    if refresh:
        request = EvaluationRequest(project_id=project_id)
        return await agent.evaluate_by_project(request)

    latest = await agent.storage.get_latest(project_id)
    if not latest:
        raise HTTPException(
            status_code=404,
            detail="未找到评审结果，请使用 refresh=true 重新评审",
        )
    return latest


def _build_batch_summary(results: List[EvaluationResult]) -> Dict[str, object]:
    """构建批量评审汇总信息"""
    if not results:
        return {
            "avg_score": 0,
            "median_score": 0,
            "grade_distribution": {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
            "dimension_avg_scores": {},
        }

    scores = [item.overall_score for item in results]
    grade_distribution = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for item in results:
        grade_distribution[item.grade] = grade_distribution.get(item.grade, 0) + 1

    dim_scores: Dict[str, List[float]] = {}
    for item in results:
        for dim in item.dimension_scores:
            dim_scores.setdefault(dim.dimension, []).append(dim.score)

    dimension_avg_scores = {
        dim: round(sum(values) / len(values), 2)
        for dim, values in dim_scores.items()
    }

    return {
        "avg_score": round(sum(scores) / len(scores), 2),
        "median_score": round(statistics.median(scores), 2),
        "grade_distribution": grade_distribution,
        "dimension_avg_scores": dimension_avg_scores,
    }
