"""智能分组与专家匹配 API 路由"""
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.common.models import ApiResponse, ResponseStatus
from src.common.models.grouping import (
    FullGroupingRequest,
    FullGroupingResult,
    GroupingRequest,
    GroupingResult,
    GroupingStatistics,
    GroupSummary,
    MatchingRequest,
    MatchingResult,
    MatchingStatistics,
    ProjectGroup,
)
from src.services.grouping import get_grouping_service
from src.common.database import get_subject_repo

router = APIRouter()

# 调试接口：查询学科
@router.get("/debug/subjects")
async def debug_subjects():
    """查询学科表"""
    try:
        repo = get_subject_repo()
        subjects = repo.list_all()
        return {"count": len(subjects), "samples": [{"code": s.code, "name": s.name} for s in subjects[:20]]}
    except Exception as e:
        return {"error": str(e)}

@router.get("/debug/subjects/all")
async def debug_subjects_all():
    """查询所有学科(按前缀分组)"""
    try:
        repo = get_subject_repo()
        subjects = repo.list_all()
        
        # 按前2位分组
        from collections import defaultdict
        groups = defaultdict(list)
        for s in subjects:
            if s.code:
                prefix = s.code[:2]
                groups[prefix].append({"code": s.code, "name": s.name})
        
        return {"count": len(subjects), "prefixes": dict(groups)}
    except Exception as e:
        return {"error": str(e)}

# 存储分组和匹配结果（生产环境应使用数据库）
_grouping_results: Dict[str, GroupingResult] = {}
_matching_results: Dict[str, MatchingResult] = {}


@router.post("/projects", response_model=ApiResponse[GroupingResult])
async def group_projects(request: GroupingRequest) -> ApiResponse[GroupingResult]:
    """项目分组
    
    对申报项目进行智能分组，实现组内数量与质量双均衡。
    
    Args:
        request: 分组请求参数
    
    Returns:
        分组结果
    """
    try:
        service = get_grouping_service()
        result = await service.group_projects(request)
        
        # 存储结果
        _grouping_results[result.id] = result
        
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="分组完成",
            code=200
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分组失败: {str(e)}")


@router.post("/match", response_model=ApiResponse[MatchingResult])
async def match_experts(
    group_id: int,
    request: MatchingRequest
) -> ApiResponse[MatchingResult]:
    """专家匹配
    
    为指定分组匹配评审专家。
    
    Args:
        group_id: 分组ID
        request: 匹配请求参数
    
    Returns:
        匹配结果
    """
    try:
        # 获取分组结果
        grouping_result = None
        for gr in _grouping_results.values():
            for g in gr.groups:
                if g.group_id == group_id:
                    grouping_result = gr
                    break
            if grouping_result:
                break
        
        if not grouping_result:
            raise HTTPException(status_code=404, detail=f"分组 {group_id} 不存在")
        
        # 执行匹配
        service = get_grouping_service()
        result = await service.match_experts(
            group=grouping_result,
            group_id=group_id,
            request=request
        )
        
        # 存储结果
        _matching_results[result.id] = result
        
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="匹配完成",
            code=200
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"匹配失败: {str(e)}")


@router.post("/full", response_model=ApiResponse[FullGroupingResult])
async def full_grouping(request: FullGroupingRequest) -> ApiResponse[FullGroupingResult]:
    """完整分组与匹配
    
    一次性完成项目分组和专家匹配。
    
    Args:
        request: 完整请求参数
    
    Returns:
        完整结果（分组 + 匹配）
    """
    try:
        service = get_grouping_service()
        result = await service.full_grouping(request)
        
        # 存储结果
        _grouping_results[result.id] = GroupingResult(
            id=result.id,
            year=result.year,
            groups=result.groups,
            statistics=GroupingStatistics(
                total_projects=result.statistics.total_projects,
                group_count=result.statistics.total_groups,
                balance_score=result.statistics.balance_score,
                avg_projects_per_group=result.statistics.total_projects / max(1, result.statistics.total_groups),
                avg_quality_per_group=result.statistics.avg_match_score
            )
        )
        
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="完整流程完成",
            code=200
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/grouping/{grouping_id}", response_model=ApiResponse[GroupingResult])
async def get_grouping_result(grouping_id: str) -> ApiResponse[GroupingResult]:
    """查询分组结果
    
    Args:
        grouping_id: 分组结果ID
    
    Returns:
        分组结果
    """
    if grouping_id not in _grouping_results:
        raise HTTPException(status_code=404, detail=f"分组结果 {grouping_id} 不存在")
    
    return ApiResponse(
        status=ResponseStatus.SUCCESS,
        data=_grouping_results[grouping_id],
        code=200
    )


@router.get("/match/{matching_id}", response_model=ApiResponse[MatchingResult])
async def get_matching_result(matching_id: str) -> ApiResponse[MatchingResult]:
    """查询匹配结果
    
    Args:
        matching_id: 匹配结果ID
    
    Returns:
        匹配结果
    """
    if matching_id not in _matching_results:
        raise HTTPException(status_code=404, detail=f"匹配结果 {matching_id} 不存在")
    
    return ApiResponse(
        status=ResponseStatus.SUCCESS,
        data=_matching_results[matching_id],
        code=200
    )
