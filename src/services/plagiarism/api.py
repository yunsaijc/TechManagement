"""查重服务 API 路由"""
import json
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.common.models import ApiResponse
from src.services.plagiarism.agent import PlagiarismAgent
from src.services.plagiarism.config import get_section_config, get_all_doc_types
from src.services.plagiarism.section_extractor import SectionExtractor

router = APIRouter()


class PlagiarismRequest(BaseModel):
    """查重请求"""
    threshold: float = 0.8
    threshold_high: float = 0.9
    threshold_medium: float = 0.7


@router.post("")
async def check_plagiarism(
    files: List[UploadFile] = File(...),
    use_corpus: bool = Form(True),
    corpus_id: Optional[str] = Form(None),
    threshold: float = Form(0.5),
    threshold_high: float = Form(0.8),
    threshold_medium: float = Form(0.5),
    doc_type: str = Form("default"),
    section_config: Optional[str] = Form(None),
    debug: bool = Form(False),
) -> ApiResponse[dict]:
    """查重接口
    
    Args:
        files: 上传的文件列表（支持 pdf, docx）
        use_corpus: 是否查比对库，默认 True
        corpus_id: 预留参数，当前版本暂不支持多库切换
        threshold: 相似度阈值，默认 0.5
        threshold_high: 高相似度阈值，默认 0.8
        threshold_medium: 中相似度阈值，默认 0.5
        doc_type: 文档类型，用于加载对应的 section 配置，默认 "default"
        section_config: 自定义 section 配置（JSON 字符串），优先级高于 doc_type
        debug: 是否保存 debug 结果，默认 False
        
    Returns:
        查重结果
    """
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个文件")

    if corpus_id:
        raise HTTPException(status_code=400, detail="当前版本暂不支持 corpus_id 多库切换")
    
    # 读取文件数据并保存临时文件
    import tempfile
    file_data_list = []
    file_paths = {}
    temp_files = []
    
    for f in files:
        content = await f.read()
        if not content:
            continue
        # 使用文件名作为 doc_id
        doc_id = f.filename
        file_data_list.append((doc_id, content))
        
        # 保存临时文件用于 mammoth 转换
        suffix = ""
        if f.filename and "." in f.filename:
            suffix = "." + f.filename.rsplit(".", 1)[-1].lower()
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix or ".tmp", delete=False)
        temp_file.write(content)
        temp_file.close()
        file_paths[doc_id] = temp_file.name
        temp_files.append(temp_file.name)
    
    if not file_data_list:
        # 清理临时文件
        import os
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except:
                pass
        raise HTTPException(status_code=400, detail="请上传至少 1 个文件进行比对")
    
    # 逻辑检查：如果只上传 1 个文件，必须启用库查重
    if len(file_data_list) < 2 and not use_corpus:
        # 清理临时文件
        import os
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except:
                pass
        raise HTTPException(status_code=400, detail="仅上传 1 个文件时，必须启用 use_corpus=True")

    # 解析 section 配置
    config = None
    if section_config:
        try:
            config = json.loads(section_config)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="section_config 必须是有效的 JSON 字符串")
    else:
        # 使用 doc_type 加载默认配置
        config = get_section_config(doc_type)

    if not SectionExtractor.validate_config(config):
        raise HTTPException(
            status_code=400,
            detail="section_config 无效：primary 必须配置 start_pattern（可选 end_pattern）",
        )
    
    # 执行查重
    agent = PlagiarismAgent(
        threshold=threshold,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        section_config=config,
        debug=debug,
    )
    
    result = await agent.check(file_data_list, file_paths=file_paths, use_corpus=use_corpus)
    
    # 清理临时文件
    import os
    for temp_file in temp_files:
        try:
            os.unlink(temp_file)
        except:
            pass
    
    return ApiResponse(
        status="success",
        data={
            "id": result.id,
            "total_pairs": result.total_pairs,
            "effective_duplicate_rate": result.effective_duplicate_rate,
            "effective_duplicate_chars": result.effective_duplicate_chars,
            "primary_scope_chars": result.primary_scope_chars,
            "source_rankings": result.source_rankings,
            "match_groups": result.match_groups,
            "processing_time": round(result.processing_time, 2),
        },
    )


@router.get("/corpus/status")
async def get_corpus_status() -> ApiResponse[dict]:
    """获取库索引状态"""
    from src.services.plagiarism.corpus import CorpusManager
    manager = CorpusManager()
    total_chars = sum(doc.char_count for doc in manager.index.documents.values())
    return ApiResponse(
        status="success",
        data={
            "document_count": len(manager.index.documents),
            "total_chars": total_chars,
            "last_updated": manager.index.last_updated,
        },
    )


@router.post("/corpus/refresh")
async def refresh_corpus() -> ApiResponse[dict]:
    """刷新库索引（触发远程挂载目录扫描）"""
    from src.services.plagiarism.corpus import CorpusManager
    manager = CorpusManager()
    stats = await manager.scan_and_update()
    return ApiResponse(
        status="success",
        data=stats,
    )


@router.get("/types")
async def get_supported_types() -> ApiResponse[List[str]]:
    """获取支持的文档类型"""
    return ApiResponse(
        status="success",
        data=["pdf", "docx"],
    )


@router.get("/section-configs")
async def get_section_configs() -> ApiResponse[dict]:
    """获取支持的 section 配置"""
    configs = {}
    for doc_type in get_all_doc_types():
        configs[doc_type] = get_section_config(doc_type)
    return ApiResponse(
        status="success",
        data=configs,
    )
