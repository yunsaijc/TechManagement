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
from src.services.plagiarism.agent import PlagiarismAgent
from src.services.plagiarism.config import get_section_config, get_all_doc_types
from src.services.plagiarism.section_extractor import SectionExtractor

router = APIRouter()
_CORPUS_REFRESH_STATUS_PATH = Path("data/plagiarism/corpus_refresh_status.json")
_CORPUS_REFRESH_LOG_PATH = Path("data/plagiarism/corpus_refresh.log")


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


@router.get("/corpus/refresh/status")
async def get_corpus_refresh_status() -> ApiResponse[dict]:
    return ApiResponse(
        status="success",
        data=_read_corpus_refresh_status(),
    )


@router.post("/corpus/refresh")
async def refresh_corpus(
    limit: Optional[int] = Form(None),
    batch_size: int = Form(100),
    max_concurrency: int = Form(2),
    save_every_batches: int = Form(5),
    wait: bool = Form(False),
) -> ApiResponse[dict]:
    """刷新库索引（触发远程挂载目录扫描）"""
    from src.services.plagiarism.corpus import CorpusManager

    current_status = _read_corpus_refresh_status()
    if current_status.get("running"):
        return ApiResponse(
            status="success",
            data={
                "accepted": False,
                "message": "refresh 任务已在运行",
                "task": current_status,
            },
        )

    params = {
        "limit": limit,
        "batch_size": batch_size,
        "max_concurrency": max_concurrency,
        "save_every_batches": save_every_batches,
        "wait": wait,
    }

    task_id = uuid.uuid4().hex

    if wait:
        manager = CorpusManager()
        stats = await manager.scan_and_update_with_options(
            limit=limit,
            batch_size=batch_size,
            max_concurrency=max_concurrency,
            save_every_batches=save_every_batches,
        )
        return ApiResponse(
            status="success",
            data={
                "accepted": True,
                "task": {
                    "running": False,
                    "task_id": task_id,
                    "params": params,
                },
                "result": stats,
            },
        )

    initial_status = {
        "running": True,
        "task_id": task_id,
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
        "params": params,
        "progress": {
            "stage": "spawn_pending",
            "processed": 0,
            "total": 0,
            "elapsed_seconds": 0,
            "eta_seconds": 0,
            "stats": {},
        },
        "result": None,
        "pid": None,
        "log_path": str(_CORPUS_REFRESH_LOG_PATH),
    }
    _write_corpus_refresh_status(initial_status)

    cmd = []
    if shutil.which("ionice"):
        cmd.extend(["ionice", "-c3"])
    if shutil.which("nice"):
        cmd.extend(["nice", "-n", "19"])
    cmd.extend(
        [
            sys.executable,
            "-m",
            "src.services.plagiarism.corpus_refresh_runner",
            "--status-path",
            str(_CORPUS_REFRESH_STATUS_PATH),
            "--task-id",
            task_id,
            "--batch-size",
            str(batch_size),
            "--max-concurrency",
            str(max_concurrency),
            "--save-every-batches",
            str(save_every_batches),
        ]
    )
    if limit is not None:
        cmd.extend(["--limit", str(limit)])

    _CORPUS_REFRESH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(_CORPUS_REFRESH_LOG_PATH, "ab")
    process = subprocess.Popen(
        cmd,
        cwd=str(Path.cwd()),
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    log_file.close()

    initial_status["pid"] = process.pid
    initial_status["progress"] = {
        "stage": "spawned",
        "processed": 0,
        "total": 0,
        "elapsed_seconds": 0,
        "eta_seconds": 0,
        "stats": {},
    }
    _write_corpus_refresh_status(initial_status)

    time.sleep(0.2)
    return_code = process.poll()
    if return_code is not None:
        failed_status = _read_corpus_refresh_status()
        failed_status.update(
            {
                "running": False,
                "finished_at": time.time(),
                "error": f"refresh 子进程启动失败，exit_code={return_code}",
                "pid": process.pid,
            }
        )
        progress = failed_status.get("progress") or {}
        progress["stage"] = "spawn_failed"
        failed_status["progress"] = progress
        _write_corpus_refresh_status(failed_status)

    return ApiResponse(
        status="success",
        data={
            "accepted": True,
            "message": "refresh 已在后台启动",
            "task": {
                "task_id": task_id,
                "running": True,
                "params": params,
            },
        },
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
