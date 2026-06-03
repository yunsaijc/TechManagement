"""项目级形式审查 API 路由"""
from typing import List

from fastapi import APIRouter, HTTPException

from src.common.models import ApiResponse, BatchReviewRequest, BatchReviewResult, ProjectTypeInfo
from src.services.review.batch_agent import BatchReviewAgent
from src.services.review.project_config import PROJECT_CONFIG, get_project_config, get_project_label

router = APIRouter()

_batch_review_results: dict[str, BatchReviewResult] = {}


@router.post("/batches")
async def submit_batch_review(request: BatchReviewRequest) -> ApiResponse[BatchReviewResult]:
    """提交批次级形式审查"""
    agent = BatchReviewAgent()

    try:
        result = await agent.process(request)
        _batch_review_results[result.id] = result
        return ApiResponse(
            status="success",
            data=result,
            message="批次形式审查完成",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/batches/{batch_review_id}")
async def get_batch_review(batch_review_id: str) -> ApiResponse[BatchReviewResult]:
    """查询批次级形式审查结果"""
    result = _batch_review_results.get(batch_review_id)
    if not result:
        raise HTTPException(status_code=404, detail="批次审查结果不存在")

    return ApiResponse(
        status="success",
        data=result,
    )


@router.get("/project-types")
async def get_project_types() -> ApiResponse[List[ProjectTypeInfo]]:
    """获取支持的项目类型列表"""
    data = [
        ProjectTypeInfo(
            value=project_type,
            label=get_project_label(project_type),
            required_doc_types=(get_project_config(project_type) or {}).get("required_doc_types", []),
        )
        for project_type, config in PROJECT_CONFIG.items()
    ]

    return ApiResponse(
        status="success",
        data=data,
    )
