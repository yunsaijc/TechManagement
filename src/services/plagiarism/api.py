"""查重服务 API 路由"""
import json
import os
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.common.models import ApiResponse
from src.services.plagiarism.agent import PlagiarismAgent
from src.services.plagiarism.config import get_section_config, get_all_doc_types
from src.services.plagiarism.section_extractor import SectionExtractor
from src.services.plagiarism.mammoth_report_builder import MammothPlagiarismReportBuilder

router = APIRouter()
_REPORT_DIR = Path(os.getenv("PLAGIARISM_REPORT_DIR", "debug_plagiarism/reports"))
_REPORT_DIR.mkdir(parents=True, exist_ok=True)
_REPORT_INDEX: dict[str, Path] = {}


def _safe_report_id(report_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\\-]+", report_id or ""):
        raise HTTPException(status_code=400, detail="report_id 无效")
    return report_id


class PlagiarismRequest(BaseModel):
    """查重请求"""
    threshold: float = 0.8
    threshold_high: float = 0.9
    threshold_medium: float = 0.7


@router.post("")
async def check_plagiarism(
    request: Request,
    files: List[UploadFile] = File(...),
    threshold: float = Form(0.5),
    threshold_high: float = Form(0.8),
    threshold_medium: float = Form(0.5),
    doc_type: str = Form("default"),
    section_config: Optional[str] = Form(None),
    debug: bool = Form(False),
    include_report: bool = Form(True),
) -> ApiResponse[dict]:
    """查重接口
    
    Args:
        files: 上传的文件列表（支持 pdf, docx）
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
    
    if len(file_data_list) < 2:
        # 清理临时文件
        import os
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except:
                pass
        raise HTTPException(status_code=400, detail="请上传至少 2 个文件进行比对")
    
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
        capture_debug_output=include_report,
    )
    
    result = await agent.check(file_data_list, file_paths=file_paths)

    report_id = None
    report_url = None
    if include_report and agent.last_debug_output:
        report_id = result.id
        report_json = _REPORT_DIR / f"{report_id}.json"
        report_html = _REPORT_DIR / f"{report_id}.html"
        try:
            report_json.write_text(json.dumps(agent.last_debug_output, ensure_ascii=False, indent=2), encoding="utf-8")

            def _is_docx(doc_id: str) -> bool:
                return str(doc_id or "").lower().endswith(".docx")

            primary_doc = agent.last_primary_doc_id or (agent.last_debug_doc_ids[0] if agent.last_debug_doc_ids else "")
            primary_path = file_paths.get(primary_doc) if _is_docx(primary_doc) else None
            source_path = None
            for doc_id in agent.last_debug_doc_ids:
                if doc_id != primary_doc and _is_docx(doc_id) and doc_id in file_paths:
                    source_path = file_paths[doc_id]
                    break

            MammothPlagiarismReportBuilder().build_from_debug_file(
                report_json,
                report_html,
                primary_docx_path=primary_path,
                source_docx_path=source_path,
            )
            _REPORT_INDEX[report_id] = report_html
            report_url = f"{str(request.base_url).rstrip('/')}/api/v1/plagiarism/report/{report_id}"
        except Exception:
            report_id = None
            report_url = None
    
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
            "high_similarity": result.high_similarity,
            "medium_similarity": result.medium_similarity,
            "low_similarity": result.low_similarity,
            "processing_time": round(result.processing_time, 2),
            "report_id": report_id,
            "report_url": report_url,
        },
    )


@router.get("/report/{report_id}", response_class=HTMLResponse)
async def get_report(report_id: str) -> HTMLResponse:
    rid = _safe_report_id(report_id)
    path = _REPORT_INDEX.get(rid) or (_REPORT_DIR / f"{rid}.html")
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在或已被清理")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


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
