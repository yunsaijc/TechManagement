"""智能分组与专家匹配 API 路由"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

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
from src.services.grouping.storage.project_repo import ProjectRepository
from src.common.database import get_subject_repo
from src.common.database.connection import get_project_connection

router = APIRouter()

DEBUG_GROUPING_FILE = Path(__file__).resolve().parents[3] / "debug_grouping" / "grouping_fixed.json"
DEBUG_GROUPING_FILES = [
    {
        "key": "grouping_fixed",
        "title": "分组方案 A",
        "path": Path(__file__).resolve().parents[3] / "debug_grouping" / "grouping_fixed.json",
    },
    {
        "key": "grouping_fixed_7e9c46e6622d4ce6854499ae17a2b1d6",
        "title": "分组方案 B",
        "path": Path(__file__).resolve().parents[3] / "debug_grouping" / "grouping_fixed_7e9c46e6622d4ce6854499ae17a2b1d6.json",
    },
]

# 调试接口：查询项目
@router.get("/debug/project/{project_id}")
async def debug_project(project_id: str):
    """根据ID查询项目原始数据"""
    try:
        project = ProjectRepository.get_project_by_id(project_id)
        if not project:
            return {"error": "项目不存在"}
        return {
            "id": project.id,
            "xmmc": project.xmmc,
            "ssxk1": project.ssxk1,
            "ssxk2": project.ssxk2,
            "xmjj": project.xmjj[:200] if project.xmjj else None,
        }
    except Exception as e:
        return {"error": str(e)}

# 调试接口：查询学科
@router.get("/debug/xkfl")
async def debug_xkfl():
    """查询学科分类表 sys_xkfl"""
    try:
        conn = get_project_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT code, name FROM sys_xkfl WHERE code LIKE '46%' ORDER BY code")
                rows = cursor.fetchall()
                return {"codes": [(r[0], r[1]) for r in rows]}
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e)}
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


@router.get("/debug/fixed-result", response_model=ApiResponse[Dict[str, Any]])
async def debug_fixed_result() -> ApiResponse[Dict[str, Any]]:
    """读取本地调试分组结果，供前端直接展示。"""
    if not DEBUG_GROUPING_FILE.exists():
        raise HTTPException(status_code=404, detail=f"调试结果不存在: {DEBUG_GROUPING_FILE}")

    try:
        with DEBUG_GROUPING_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取调试结果失败: {str(e)}")

    return ApiResponse(
        status=ResponseStatus.SUCCESS,
        data=payload,
        message="调试分组结果",
        code=200,
    )


@router.get("/debug/fixed-results", response_model=ApiResponse[Dict[str, Any]])
async def debug_fixed_results() -> ApiResponse[Dict[str, Any]]:
    """读取两份本地调试分组结果，供前端并列展示。"""
    datasets = []
    for item in DEBUG_GROUPING_FILES:
        path = item["path"]
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取调试结果失败: {str(e)}")
        datasets.append(
            {
                "key": item["key"],
                "title": item["title"],
                "filename": path.name,
                "payload": payload,
            }
        )

    if not datasets:
        raise HTTPException(status_code=404, detail="未找到可展示的调试分组结果")

    return ApiResponse(
        status=ResponseStatus.SUCCESS,
        data={"datasets": datasets},
        message="调试分组结果集合",
        code=200,
    )

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
