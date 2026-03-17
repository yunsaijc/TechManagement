"""查重服务 API 路由"""
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.common.models import ApiResponse
from src.services.plagiarism.agent import PlagiarismAgent

router = APIRouter()


class PlagiarismRequest(BaseModel):
    """查重请求"""
    threshold: float = 0.8
    threshold_high: float = 0.9
    threshold_medium: float = 0.7


@router.post("")
async def check_plagiarism(
    files: List[UploadFile] = File(...),
    threshold: float = Form(0.8),
    threshold_high: float = Form(0.9),
    threshold_medium: float = Form(0.7),
) -> ApiResponse[dict]:
    """查重接口
    
    Args:
        files: 上传的文件列表（支持 pdf, docx）
        threshold: 相似度阈值，默认 0.8
        threshold_high: 高相似度阈值，默认 0.9
        threshold_medium: 中相似度阈值，默认 0.7
        
    Returns:
        查重结果
    """
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个文件")
    
    # 读取文件数据
    file_data_list = []
    for f in files:
        content = await f.read()
        if not content:
            continue
        # 使用文件名作为 doc_id
        file_data_list.append((f.filename, content))
    
    if len(file_data_list) < 2:
        raise HTTPException(status_code=400, detail="请上传至少 2 个文件进行比对")
    
    # 执行查重
    agent = PlagiarismAgent(
        threshold=threshold,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
    )
    
    result = await agent.check(file_data_list)
    
    return ApiResponse(
        status="success",
        data={
            "id": result.id,
            "total_pairs": result.total_pairs,
            "high_similarity": result.high_similarity,
            "medium_similarity": result.medium_similarity,
            "low_similarity": result.low_similarity,
            "processing_time": round(result.processing_time, 2),
        },
    )


@router.get("/types")
async def get_supported_types() -> ApiResponse[List[str]]:
    """获取支持的文档类型"""
    return ApiResponse(
        status="success",
        data=["pdf", "docx"],
    )
