"""项目级形式审查 API 路由"""
from typing import List

from fastapi import APIRouter, HTTPException

from src.common.models import ApiResponse, ProjectReviewRequest, ProjectReviewResult, ProjectTypeInfo
from src.services.review.project_agent import ProjectReviewAgent
from src.services.review.project_config import PROJECT_CONFIG, get_project_label

router = APIRouter()

_project_review_results: dict[str, ProjectReviewResult] = {}


@router.post("/projects")
async def submit_project_review(request: ProjectReviewRequest) -> ApiResponse[ProjectReviewResult]:
    """提交项目级形式审查"""
    agent = ProjectReviewAgent()

    try:
        result = await agent.process(request)
        _project_review_results[result.id] = result
        return ApiResponse(
            status="success",
            data=result,
            message="项目形式审查完成",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/projects/{project_review_id}")
async def get_project_review(project_review_id: str) -> ApiResponse[ProjectReviewResult]:
    """查询项目级形式审查结果"""
    result = _project_review_results.get(project_review_id)
    if not result:
        raise HTTPException(status_code=404, detail="项目审查结果不存在")

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
            required_doc_kinds=config.get("required_doc_kinds", []),
        )
        for project_type, config in PROJECT_CONFIG.items()
    ]

    return ApiResponse(
        status="success",
        data=data,
    )
