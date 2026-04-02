"""查重服务 API 路由"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.common.models import ApiResponse
from src.services.grouping.storage.project_repo import ProjectRepository
from src.services.plagiarism.agent import PlagiarismAgent
from src.services.plagiarism.config import (
    PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT,
    get_all_doc_types,
    get_section_config,
)
from src.services.plagiarism.section_extractor import SectionExtractor

router = APIRouter()
_CORPUS_REFRESH_STATUS_PATH = Path("data/plagiarism/corpus_refresh_status.json")
_CORPUS_REFRESH_LOG_PATH = Path("data/plagiarism/corpus_refresh.log")
_CORPUS_REFRESH_CHECKPOINT_PATH = Path("data/plagiarism/corpus_refresh_checkpoint.json")


def _read_corpus_refresh_status() -> dict:
    if not _CORPUS_REFRESH_STATUS_PATH.exists():
        return {
            "running": False,
            "task_id": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "params": None,
            "progress": None,
            "result": None,
            "pid": None,
        }

    try:
        with open(_CORPUS_REFRESH_STATUS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"running": False}
    except Exception as exc:
        return {"running": False, "error": f"状态文件读取失败: {exc}"}

    pid = data.get("pid")
    if data.get("running") and pid:
        try:
            os.kill(int(pid), 0)
        except OSError:
            data["running"] = False
            data.setdefault("error", "refresh 进程已退出")
    return data


def _write_corpus_refresh_status(data: dict) -> None:
    _CORPUS_REFRESH_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _CORPUS_REFRESH_STATUS_PATH.with_name(f"{_CORPUS_REFRESH_STATUS_PATH.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, _CORPUS_REFRESH_STATUS_PATH)


def _read_corpus_refresh_checkpoint() -> dict:
    if not _CORPUS_REFRESH_CHECKPOINT_PATH.exists():
        return {
            "next_cursor": None,
            "has_more": False,
            "updated_at": None,
            "last_task_id": None,
        }
    try:
        with open(_CORPUS_REFRESH_CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {
            "next_cursor": None,
            "has_more": False,
            "updated_at": None,
            "last_task_id": None,
        }


def _write_corpus_refresh_checkpoint(data: dict) -> None:
    _CORPUS_REFRESH_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _CORPUS_REFRESH_CHECKPOINT_PATH.with_name(f"{_CORPUS_REFRESH_CHECKPOINT_PATH.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, _CORPUS_REFRESH_CHECKPOINT_PATH)


class PlagiarismRequest(BaseModel):
    """查重请求"""
    threshold: float = 0.8
    threshold_high: float = 0.9
    threshold_medium: float = 0.7


def _normalize_guide_codes(
    guide_codes_raw: Optional[str],
    guide_codes_list: Optional[List[str]],
) -> List[str]:
    codes: List[str] = []
    if guide_codes_raw:
        raw = guide_codes_raw.strip()
        if raw:
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise HTTPException(status_code=400, detail=f"guide_codes JSON 解析失败: {exc}") from exc
                if not isinstance(parsed, list):
                    raise HTTPException(status_code=400, detail="guide_codes 必须是字符串数组")
                codes.extend(str(item).strip() for item in parsed if str(item).strip())
            else:
                codes.extend(part.strip() for part in raw.split(",") if part.strip())
    if guide_codes_list:
        codes.extend(code.strip() for code in guide_codes_list if code and code.strip())

    deduped: List[str] = []
    seen = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        deduped.append(code)
    return deduped


def _serialize_plagiarism_result(result) -> dict:
    return {
        "id": result.id,
        "total_pairs": result.total_pairs,
        "effective_duplicate_rate": result.effective_duplicate_rate,
        "effective_duplicate_chars": result.effective_duplicate_chars,
        "primary_scope_chars": result.primary_scope_chars,
        "source_rankings": result.source_rankings,
        "match_groups": result.match_groups,
        "processing_time": round(result.processing_time, 2),
    }


def _resolve_local_project_doc_candidates(project_id: str, year: str) -> List[Path]:
    filename = f"{project_id}.docx"
    local_root = PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT
    candidates = [
        local_root / "sbs_5000" / filename,
        local_root / "sbs_10000" / filename,
        local_root / year / "sbs" / filename if year else None,
        local_root / filename,
    ]
    ordered: List[Path] = []
    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(candidate)
    return ordered


def _find_local_project_doc(project_id: str, year: str) -> tuple[Optional[Path], List[str]]:
    candidates = _resolve_local_project_doc_candidates(project_id, year)
    for candidate in candidates:
        if candidate.is_file():
            return candidate, [str(path) for path in candidates]
    return None, [str(path) for path in candidates]


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
        data=_serialize_plagiarism_result(result),
    )


@router.post("/by-guide-codes")
async def check_plagiarism_by_guide_codes(
    guide_codes_raw: Optional[str] = Form(None, alias="guide_codes"),
    guide_codes_list: Optional[List[str]] = Form(None, alias="guide_codes_list"),
    threshold: float = Form(0.5),
    threshold_high: float = Form(0.8),
    threshold_medium: float = Form(0.5),
    doc_type: str = Form("default"),
    section_config: Optional[str] = Form(None),
    debug: bool = Form(False),
    limit: Optional[int] = Form(None),
) -> ApiResponse[dict]:
    """按指南代码批量执行“单项目 vs 库”查重。"""
    cleaned_codes = _normalize_guide_codes(guide_codes_raw, guide_codes_list)
    if not cleaned_codes:
        raise HTTPException(status_code=400, detail="guide_codes 不能为空")

    config = None
    if section_config:
        try:
            config = json.loads(section_config)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="section_config 必须是有效的 JSON 字符串")
    else:
        config = get_section_config(doc_type)

    if not SectionExtractor.validate_config(config):
        raise HTTPException(
            status_code=400,
            detail="section_config 无效：primary 必须配置 start_pattern（可选 end_pattern）",
        )

    projects = ProjectRepository.get_submitted_projects_by_guide_codes(cleaned_codes, limit=limit)
    if not projects:
        return ApiResponse(
            status="success",
            data={
                "guide_codes": cleaned_codes,
                "selected_projects": 0,
                "available_docs": 0,
                "missing_docs": [],
                "results": [],
            },
        )

    available_projects = []
    missing_docs = []
    for project in projects:
        doc_path, expected_paths = _find_local_project_doc(project["id"], project["year"])
        remote_path = f"/mnt/remote_corpus/{project['year']}/sbs/{project['id']}.docx"
        project_info = {
            "id": project["id"],
            "xmmc": project["xmmc"],
            "year": project["year"],
            "zndm": project["zndm"],
            "guide_name": project["guide_name"],
        }
        if doc_path is None:
            missing_docs.append(
                {
                    **project_info,
                    "expected_local_paths": expected_paths,
                    "remote_path": remote_path,
                }
            )
            continue
        available_projects.append(
            {
                **project_info,
                "local_path": str(doc_path),
                "remote_path": remote_path,
            }
        )

    results = []
    agent = PlagiarismAgent(
        threshold=threshold,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        section_config=config,
        debug=debug,
    )
    for project in available_projects:
        file_path = Path(project["local_path"])
        try:
            file_data = file_path.read_bytes()
        except Exception as exc:
            missing_docs.append(
                {
                    "id": project["id"],
                    "xmmc": project["xmmc"],
                    "year": project["year"],
                    "zndm": project["zndm"],
                    "guide_name": project["guide_name"],
                    "expected_local_paths": [project["local_path"]],
                    "remote_path": project["remote_path"],
                    "error": f"读取本地文件失败: {exc}",
                }
            )
            continue

        result = await agent.check(
            [(f"{project['id']}.docx", file_data)],
            file_paths={f"{project['id']}.docx": str(file_path)},
            use_corpus=True,
        )
        results.append(
            {
                "project": {
                    "id": project["id"],
                    "xmmc": project["xmmc"],
                    "year": project["year"],
                    "zndm": project["zndm"],
                    "guide_name": project["guide_name"],
                    "local_path": project["local_path"],
                },
                "result": _serialize_plagiarism_result(result),
            }
        )

    return ApiResponse(
        status="success",
        data={
            "guide_codes": cleaned_codes,
            "selected_projects": len(projects),
            "available_docs": len(results),
            "missing_docs": missing_docs,
            "results": results,
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


@router.get("/corpus/refresh/status")
async def get_corpus_refresh_status() -> ApiResponse[dict]:
    data = _read_corpus_refresh_status()
    data["checkpoint"] = _read_corpus_refresh_checkpoint()
    return ApiResponse(
        status="success",
        data=data,
    )


@router.post("/corpus/refresh")
async def refresh_corpus(
    limit: Optional[int] = Form(None),
    batch_size: int = Form(100),
    max_concurrency: int = Form(2),
    save_every_batches: int = Form(5),
    cursor_doc_id: Optional[str] = Form(None),
    max_scan: Optional[int] = Form(None),
    reset_cursor: bool = Form(False),
    wait: bool = Form(False),
) -> ApiResponse[dict]:
    """危险 refresh API 已禁用，只保留状态查询。"""
    raise HTTPException(
        status_code=403,
        detail=(
            "危险 refresh API 已禁用。"
            "请改用离线命令执行 scan_manifest / build_batch。"
        ),
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
