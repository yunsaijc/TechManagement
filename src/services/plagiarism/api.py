"""查重服务 API 路由"""
import asyncio
import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.common.database.connection import reward_execute
from src.common.models import ApiResponse
from src.services.plagiarism.batch_report_builder import BatchPlagiarismReportBuilder
from src.services.plagiarism.by_file_ingest_aggregator import ByFileIngestResultAggregator
from src.services.plagiarism.config import (
    PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT,
    PLAGIARISM_DEFAULT_REMOTE_CORPUS_ROOT,
    PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR,
    PLAGIARISM_REWARD_DICT_CONFIG,
    PLAGIARISM_REWARD_SCOPE_CONFIG,
    build_reward_upload_windows_file_path,
    get_all_doc_types,
    get_section_config,
)
from src.services.plagiarism.kjjh_api import router as kjjh_router
from src.services.plagiarism.reward_corpus import RewardCorpusPlagiarismService
from src.services.plagiarism.reward_corpus_manager import RewardCorpusManager
from src.services.plagiarism.section_extractor import SectionExtractor
from src.services.plagiarism.smb_file_reader import SMBReviewFileReader

router = APIRouter()
router.include_router(kjjh_router, prefix="/kjjh")
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
    local_root = PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT
    candidates: list[Path | None] = []
    for ext in (".docx", ".doc"):
        filename = f"{project_id}{ext}"
        candidates.extend(
            [
                local_root / "sbs_5000" / filename,
                local_root / "sbs_10000" / filename,
                local_root / year / "sbs" / filename if year else None,
                local_root / filename,
            ]
        )
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


def _resolve_remote_project_doc(project_id: str, year: str) -> Optional[Path]:
    if not year:
        return None
    for ext in (".docx", ".doc"):
        candidate = PLAGIARISM_DEFAULT_REMOTE_CORPUS_ROOT / year / "sbs" / f"{project_id}{ext}"
        if candidate.is_file():
            return candidate
    return PLAGIARISM_DEFAULT_REMOTE_CORPUS_ROOT / year / "sbs" / f"{project_id}.docx"


def _resolve_project_doc(
    project_id: str,
    year: str,
    read_remote_if_missing: bool,
) -> dict:
    local_doc_path, expected_local_paths = _find_local_project_doc(project_id, year)
    remote_doc_path = _resolve_remote_project_doc(project_id, year)
    remote_exists = bool(remote_doc_path and remote_doc_path.is_file())

    resolved_path: Optional[Path] = local_doc_path
    storage = "local" if local_doc_path is not None else None
    if resolved_path is None and read_remote_if_missing and remote_exists and remote_doc_path is not None:
        resolved_path = remote_doc_path
        storage = "remote"

    return {
        "resolved_path": resolved_path,
        "storage": storage,
        "expected_local_paths": expected_local_paths,
        "remote_path": str(remote_doc_path) if remote_doc_path is not None else "",
        "remote_exists": remote_exists,
    }


def _extract_reward_upload_year(xmtjbh: str, fallback_year: str | None = None) -> str:
    tj = str(xmtjbh or "").strip()
    match = re.match(r"^(\d{4})-", tj)
    if match:
        return match.group(1)
    year = str(fallback_year or "").strip()
    if re.fullmatch(r"\d{4}", year):
        return year
    raise ValueError(f"无法确定提名号 {tj} 对应的材料年度")


def _get_xmtjbh_and_year_by_xmbh(db_name: str, xmbh: str) -> tuple[str, str | None]:
    rows = reward_execute(
        db_name,
        """
        SELECT c.xmtjbh AS xmtjbh, p.nd AS nd
        FROM t_xm_cl c
        LEFT JOIN ps_xmpsxx p ON p.xmbh = c.xmbh
        WHERE c.xmbh = %s
          AND c.xmtjbh IS NOT NULL
          AND TRIM(c.xmtjbh) <> ''
        LIMIT 1
        """,
        (xmbh,),
    )
    if not rows:
        raise ValueError(f"未找到项目 {xmbh} 对应提名号 xmtjbh")
    row = rows[0]
    return str(row.get("xmtjbh") or "").strip(), str(row.get("nd") or "").strip() or None


def _build_reward_upload_word_path(xmtjbh: str, fallback_year: str | None = None) -> str:
    year = _extract_reward_upload_year(xmtjbh, fallback_year=fallback_year)
    ext = ".docx"
    if year.isdigit() and int(year) < 2024:
        ext = ".doc"
    return build_reward_upload_windows_file_path(year=year, xmtjbh=xmtjbh, file_name=f"{xmtjbh}{ext}")


def _candidate_reward_upload_word_paths(xmtjbh: str, fallback_year: str | None = None) -> list[str]:
    """按优先级返回提名材料候选路径（先历史默认后缀，再尝试另一后缀）。"""
    year = _extract_reward_upload_year(xmtjbh, fallback_year=fallback_year)
    preferred_ext = ".docx"
    if year.isdigit() and int(year) < 2024:
        preferred_ext = ".doc"
    alternate_ext = ".doc" if preferred_ext == ".docx" else ".docx"
    return [
        build_reward_upload_windows_file_path(year=year, xmtjbh=xmtjbh, file_name=f"{xmtjbh}{preferred_ext}"),
        build_reward_upload_windows_file_path(year=year, xmtjbh=xmtjbh, file_name=f"{xmtjbh}{alternate_ext}"),
    ]


def _resolve_upload_file_bytes(file_path: str) -> tuple[bytes, str, str | None]:
    raw = str(file_path or "").strip()
    if not raw:
        raise ValueError("word_path 不能为空")

    local_path = Path(raw)
    if local_path.is_file():
        return local_path.read_bytes(), str(local_path), None

    reader = SMBReviewFileReader()
    content = reader.read_bytes(raw)
    suffix = Path(raw).suffix.lower() if Path(raw).suffix else ".docx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(content)
    tmp.close()
    return content, raw, tmp.name


def _is_reward_upload_windows_path(file_path: str) -> bool:
    raw = str(file_path or "").strip()
    if not raw:
        return False
    normalized = raw.replace("/", "\\").lower()
    return bool(
        re.match(
            r"^[a-z]:\\fjcl\\static\\rpw\\zmcl\d{4}\\[^\\]+\\[^\\]+\.(doc|docx)$",
            normalized,
        )
    )


def _get_xmbh_to_xmtjbh_map(db_name: str, xmbh_list: list[str]) -> dict[str, dict[str, str | None]]:
    cleaned = [str(x).strip() for x in xmbh_list if str(x).strip()]
    if not cleaned:
        return {}
    result: dict[str, dict[str, str | None]] = {}
    chunk_size = 500
    for i in range(0, len(cleaned), chunk_size):
        chunk = cleaned[i : i + chunk_size]
        placeholders = ",".join(["%s"] * len(chunk))
        rows = reward_execute(
            db_name,
            f"""
            SELECT c.xmbh AS xmbh, c.xmtjbh AS xmtjbh, p.nd AS nd
            FROM t_xm_cl c
            LEFT JOIN ps_xmpsxx p ON p.xmbh = c.xmbh
            WHERE c.xmbh IN ({placeholders})
              AND c.xmtjbh IS NOT NULL
              AND TRIM(c.xmtjbh) <> ''
            """,
            tuple(chunk),
        )
        for row in rows:
            xmbh = str(row.get("xmbh") or "").strip()
            xmtjbh = str(row.get("xmtjbh") or "").strip()
            if xmbh and xmtjbh:
                result[xmbh] = {
                    "xmtjbh": xmtjbh,
                    "year": str(row.get("nd") or "").strip() or None,
                }
    return result


def _candidate_file_corpus_doc_ids_from_xmtjbh(xmtjbh: str, fallback_year: str | None = None) -> list[str]:
    tj = str(xmtjbh).strip()
    if not tj:
        return []
    year = _extract_reward_upload_year(tj, fallback_year=fallback_year)
    candidates = [
        f"zmcl{year}/{tj}/{tj}.docx",
        f"zmcl{year}/{tj}/{tj}.doc",
    ]
    return candidates


def _build_primary_doc_id(*, xmbh: str, resolved_word_path: str, temp_primary_path: str | None) -> str:
    effective_path = str(temp_primary_path or resolved_word_path)
    suffix = Path(effective_path).suffix.lower() or ".docx"
    if suffix not in {".docx", ".doc", ".pdf"}:
        suffix = ".docx"
    return f"{xmbh}{suffix}"


def _resolve_file_local_ingest_corpus_paths(corpus_root: Path) -> tuple[Path, Path, Path, Path]:
    """奖励上传材料（K 盘 zmcl 镜像）分支：若存在 docx 独立建库产物则优先使用，否则 corpus_*。"""
    upload_json = corpus_root / "file_upload_docx_index.json"
    upload_db = corpus_root / "file_upload_docx_index.db"
    if upload_json.is_file() and upload_db.is_file():
        return (
            upload_json,
            upload_db,
            corpus_root / "file_upload_docx_manifest.json",
            corpus_root / "file_upload_docx_checkpoint.json",
        )
    return (
        corpus_root / "corpus_index.json",
        corpus_root / "corpus_index.db",
        corpus_root / "corpus_manifest.json",
        corpus_root / "corpus_refresh_checkpoint.json",
    )


def _create_file_corpus_manager(corpus_root: Path):
    from src.services.plagiarism.corpus import CorpusManager

    index_json, index_sqlite, manifest_path, checkpoint_path = _resolve_file_local_ingest_corpus_paths(
        corpus_root
    )

    env_keys = [
        "PLAGIARISM_CORPUS_PATH",
        "PLAGIARISM_CORPUS_INDEX_PATH",
        "PLAGIARISM_CORPUS_SQLITE_PATH",
        "PLAGIARISM_CORPUS_MANIFEST_PATH",
        "PLAGIARISM_CORPUS_CHECKPOINT_PATH",
    ]
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ["PLAGIARISM_CORPUS_PATH"] = str(corpus_root)
    os.environ["PLAGIARISM_CORPUS_INDEX_PATH"] = str(index_json)
    os.environ["PLAGIARISM_CORPUS_SQLITE_PATH"] = str(index_sqlite)
    os.environ["PLAGIARISM_CORPUS_MANIFEST_PATH"] = str(manifest_path)
    os.environ["PLAGIARISM_CORPUS_CHECKPOINT_PATH"] = str(checkpoint_path)
    try:
        return CorpusManager(corpus_path=str(corpus_root), index_save_path=str(index_json))
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _FilteredCorpusManager:
    def __init__(self, base_manager, allowed_doc_ids: list[str]):
        self._base = base_manager
        seen: set[str] = set()
        ordered: list[str] = []
        for doc_id in allowed_doc_ids:
            cleaned = str(doc_id).strip()
            if not cleaned or cleaned in seen:
                continue
            if cleaned not in self._base.index.documents:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        self._allowed = ordered
        self._allowed_set = set(ordered)
        self.index = type(
            "CorpusIndexView",
            (),
            {"documents": {doc_id: self._base.index.documents[doc_id] for doc_id in ordered}},
        )()

    def has_inverted_index(self):
        return self._base.has_inverted_index()

    def retrieve_candidate_doc_ids(self, primary_text: str, primary_excluded_ranges: list, top_k: int = 50):
        candidates = self._base.retrieve_candidate_doc_ids(
            primary_text=primary_text,
            primary_excluded_ranges=primary_excluded_ranges,
            top_k=top_k,
        )
        return [doc_id for doc_id in candidates if doc_id in self._allowed_set]

    def get_retrieval_documents(self, doc_ids=None):
        if doc_ids is None:
            return self._base.get_retrieval_documents(self._allowed)
        filtered = [doc_id for doc_id in doc_ids if doc_id in self._allowed_set]
        return self._base.get_retrieval_documents(filtered)

    async def get_document_text(self, doc_id: str):
        if doc_id not in self._allowed_set:
            return ""
        return await self._base.get_document_text(doc_id)


async def run_reward_plagiarism_by_file(
    *,
    xmbh: str,
    scope: str,
    word_path: Optional[str] = None,
    threshold: float = 0.5,
    threshold_high: float = 0.8,
    threshold_medium: float = 0.5,
    doc_type: str = "default",
    section_config_json: Optional[str] = None,
    debug: bool = False,
    include_report: bool = True,
    debug_output_root: Path | str | None = None,
) -> dict:
    """执行奖励库上传 `/by-file` 查重，仅供该分支复用。"""
    normalized_xmbh = str(xmbh).strip()
    normalized_scope = str(scope).strip().lower()
    normalized_word_path = str(word_path).strip() if word_path is not None else ""
    if not normalized_xmbh:
        raise ValueError("xmbh 不能为空")
    if normalized_scope not in PLAGIARISM_REWARD_SCOPE_CONFIG:
        raise ValueError(
            f"scope 不支持: {scope}，可选: {', '.join(PLAGIARISM_REWARD_SCOPE_CONFIG.keys())}"
        )
    if threshold_high <= 0 or threshold_high > 1 or threshold_medium <= 0 or threshold_medium > 1:
        raise ValueError("threshold_high/threshold_medium 必须在 (0,1] 区间")
    if threshold_medium > threshold_high:
        raise ValueError("threshold_medium 不能大于 threshold_high")

    temp_primary_path: str | None = None
    content: bytes | None = None
    resolved_word_path = normalized_word_path
    xmtjbh: str | None = None
    xmtj_year: str | None = None
    try:
        if not normalized_word_path:
            xmtjbh, xmtj_year = _get_xmtjbh_and_year_by_xmbh("xmsbnew", normalized_xmbh)
            candidates = _candidate_reward_upload_word_paths(xmtjbh, fallback_year=xmtj_year)
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    content, resolved_word_path, temp_primary_path = _resolve_upload_file_bytes(candidate)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
            if content is None:
                raise ValueError(f"读取上传文件失败: {last_error}" if last_error else "读取上传文件失败")
            normalized_word_path = resolved_word_path
        else:
            content, resolved_word_path, temp_primary_path = _resolve_upload_file_bytes(normalized_word_path)
            normalized_word_path = resolved_word_path

        if section_config_json:
            try:
                config = json.loads(section_config_json)
            except json.JSONDecodeError as exc:
                raise ValueError("section_config 必须是有效的 JSON 字符串") from exc
        else:
            config = get_section_config(doc_type)

        if not SectionExtractor.validate_config(config):
            raise ValueError("section_config 无效：primary 必须配置 start_pattern（可选 end_pattern）")

        manager = RewardCorpusManager(db_name="xmsbnew")
        current_nd = manager.get_current_nomination_year()
        scope_ids = manager.get_scope_project_ids(normalized_scope, current_nd=current_nd)
        scope_ids = [doc_id for doc_id in scope_ids if doc_id != normalized_xmbh]

        from src.services.plagiarism.agent import PlagiarismAgent

        file_corpus_root = PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR
        file_corpus_manager = _create_file_corpus_manager(file_corpus_root)
        file_doc_ids_set = set(file_corpus_manager.index.documents.keys())
        if not file_doc_ids_set:
            raise ValueError("file_local_ingest 对比库为空，请先执行批量建库/增量刷新")

        xmbh_to_xmtjbh = _get_xmbh_to_xmtjbh_map("xmsbnew", scope_ids)
        allowed_doc_ids: list[str] = []
        allowed_seen: set[str] = set()
        for scope_xmbh in scope_ids:
            doc_info = xmbh_to_xmtjbh.get(str(scope_xmbh).strip())
            if not doc_info:
                continue
            tj = str(doc_info.get("xmtjbh") or "").strip()
            if not tj:
                continue
            year = str(doc_info.get("year") or "").strip() or None
            for cand in _candidate_file_corpus_doc_ids_from_xmtjbh(tj, fallback_year=year):
                if cand in file_doc_ids_set and cand not in allowed_seen:
                    allowed_seen.add(cand)
                    allowed_doc_ids.append(cand)

        if not allowed_doc_ids:
            raise ValueError("在指定 scope 范围内没有已建库的可比对文档（请先刷新库）")

        primary_doc_id = _build_primary_doc_id(
            xmbh=normalized_xmbh,
            resolved_word_path=normalized_word_path,
            temp_primary_path=temp_primary_path,
        )

        agent = PlagiarismAgent(
            threshold=threshold,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            section_config=config,
            debug=debug,
            capture_debug_output=include_report,
            highlight_template_segments=False,
        )
        agent.result_aggregator = ByFileIngestResultAggregator(
            section_extractor=agent.section_extractor,
            template_filter=agent.template_filter,
        )
        agent.corpus_manager = _FilteredCorpusManager(file_corpus_manager, allowed_doc_ids)

        debug_root = Path(debug_output_root) if debug_output_root else Path("/home/tdkx/ljh/Tech/debug_plagiarism/file")
        debug_output_dir = debug_root / f"{normalized_xmbh}_{time.strftime('%Y%m%d_%H%M%S')}"
        debug_output_dir.mkdir(parents=True, exist_ok=True)

        result = await agent.check(
            [(primary_doc_id, content)],
            file_paths={primary_doc_id: str(temp_primary_path or normalized_word_path)},
            use_corpus=True,
            debug_output_dir=debug_output_dir,
        )

        return {
            "xmbh": normalized_xmbh,
            "primary_doc_id": primary_doc_id,
            "word_path": normalized_word_path,
            "xmtjbh": xmtjbh,
            "scope": normalized_scope,
            "scope_label": PLAGIARISM_REWARD_SCOPE_CONFIG[normalized_scope],
            "current_nomination_year": current_nd,
            "scope_total_projects": len(scope_ids),
            "available_corpus_docs": len(allowed_doc_ids),
            "debug_output_dir": str(debug_output_dir),
            "debug_report_path": str(debug_output_dir / "plagiarism_report_mammoth.html"),
            "debug_report_upload_path": (
                str(debug_output_dir / "plagiarism_report_upload_plain.html")
                if _is_reward_upload_windows_path(normalized_word_path)
                else None
            ),
            "result": _serialize_plagiarism_result(result),
        }
    finally:
        if temp_primary_path:
            try:
                os.unlink(temp_primary_path)
            except OSError:
                pass


@router.post("")
async def check_plagiarism(
    request: Request,
    files: List[UploadFile] = File(...),
    use_corpus: bool = Form(True),
    corpus_id: Optional[str] = Form(None),
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
        files: 上传的文件列表（支持 pdf, docx, doc）
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
    from src.services.plagiarism.agent import PlagiarismAgent

    agent = PlagiarismAgent(
        threshold=threshold,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        section_config=config,
        debug=debug,
        capture_debug_output=include_report,
        enable_plain_text_report=False,
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


@router.post("/by-file")
async def check_plagiarism_by_file(
    request: Request,
    xmbh: str = Form(...),
    word_path: Optional[str] = Form(None),
    scope: str = Form(...),
    threshold: float = Form(0.5),
    threshold_high: float = Form(0.8),
    threshold_medium: float = Form(0.5),
    doc_type: str = Form("default"),
    section_config: Optional[str] = Form(None),
    debug: bool = Form(False),
    include_report: bool = Form(True),
) -> ApiResponse[dict]:
    normalized_xmbh = str(xmbh).strip()
    normalized_scope = str(scope).strip().lower()
    normalized_word_path = str(word_path).strip() if word_path is not None else ""
    if not normalized_xmbh:
        raise HTTPException(status_code=400, detail="xmbh 不能为空")
    if normalized_scope not in PLAGIARISM_REWARD_SCOPE_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"scope 不支持: {scope}，可选: {', '.join(PLAGIARISM_REWARD_SCOPE_CONFIG.keys())}",
        )
    if threshold_high <= 0 or threshold_high > 1 or threshold_medium <= 0 or threshold_medium > 1:
        raise HTTPException(status_code=400, detail="threshold_high/threshold_medium 必须在 (0,1] 区间")
    if threshold_medium > threshold_high:
        raise HTTPException(status_code=400, detail="threshold_medium 不能大于 threshold_high")

    temp_primary_path: str | None = None
    content: bytes | None = None
    resolved_word_path = normalized_word_path
    xmtjbh: str | None = None
    xmtj_year: str | None = None
    try:
        if not normalized_word_path:
            xmtjbh, xmtj_year = _get_xmtjbh_and_year_by_xmbh("xmsbnew", normalized_xmbh)
            candidates = _candidate_reward_upload_word_paths(xmtjbh, fallback_year=xmtj_year)
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    content, resolved_word_path, temp_primary_path = _resolve_upload_file_bytes(candidate)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
            if content is None:
                raise ValueError(f"读取上传文件失败: {last_error}" if last_error else "读取上传文件失败")
            normalized_word_path = resolved_word_path
        else:
            content, resolved_word_path, temp_primary_path = _resolve_upload_file_bytes(normalized_word_path)
            normalized_word_path = resolved_word_path
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}") from exc

    config = None
    if section_config:
        try:
            config = json.loads(section_config)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="section_config 必须是有效的 JSON 字符串") from exc
    else:
        config = get_section_config(doc_type)

    if not SectionExtractor.validate_config(config):
        raise HTTPException(
            status_code=400,
            detail="section_config 无效：primary 必须配置 start_pattern（可选 end_pattern）",
        )

    manager = RewardCorpusManager(db_name="xmsbnew")
    current_nd = manager.get_current_nomination_year()
    scope_ids = manager.get_scope_project_ids(normalized_scope, current_nd=current_nd)
    scope_ids = [doc_id for doc_id in scope_ids if doc_id != normalized_xmbh]

    from src.services.plagiarism.agent import PlagiarismAgent

    file_corpus_root = PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR
    file_corpus_manager = _create_file_corpus_manager(file_corpus_root)
    file_doc_ids_set = set(file_corpus_manager.index.documents.keys())
    if not file_doc_ids_set:
        raise HTTPException(
            status_code=400,
            detail="file_local_ingest 对比库为空，请先执行批量建库/增量刷新",
        )

    xmbh_to_xmtjbh = _get_xmbh_to_xmtjbh_map("xmsbnew", scope_ids)
    allowed_doc_ids: list[str] = []
    allowed_seen: set[str] = set()
    for scope_xmbh in scope_ids:
        doc_info = xmbh_to_xmtjbh.get(str(scope_xmbh).strip())
        if not doc_info:
            continue
        tj = str(doc_info.get("xmtjbh") or "").strip()
        if not tj:
            continue
        year = str(doc_info.get("year") or "").strip() or None
        for cand in _candidate_file_corpus_doc_ids_from_xmtjbh(tj, fallback_year=year):
            if cand in file_doc_ids_set and cand not in allowed_seen:
                allowed_seen.add(cand)
                allowed_doc_ids.append(cand)

    if not allowed_doc_ids:
        raise HTTPException(status_code=400, detail="在指定 scope 范围内没有已建库的可比对文档（请先刷新库）")

    primary_doc_id = _build_primary_doc_id(
        xmbh=normalized_xmbh,
        resolved_word_path=normalized_word_path,
        temp_primary_path=temp_primary_path,
    )

    agent = PlagiarismAgent(
        threshold=threshold,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        section_config=config,
        debug=debug,
        capture_debug_output=include_report,
        highlight_template_segments=False,
    )
    agent.result_aggregator = ByFileIngestResultAggregator(
        section_extractor=agent.section_extractor,
        template_filter=agent.template_filter,
    )
    agent.corpus_manager = _FilteredCorpusManager(file_corpus_manager, allowed_doc_ids)
    debug_output_dir = Path("/home/tdkx/ljh/Tech/debug_plagiarism/file") / (
        f"{normalized_xmbh}_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    debug_output_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = await agent.check(
            [(primary_doc_id, content)],
            file_paths={primary_doc_id: str(temp_primary_path or normalized_word_path)},
            use_corpus=True,
            debug_output_dir=debug_output_dir,
        )
    finally:
        if temp_primary_path:
            try:
                os.unlink(temp_primary_path)
            except OSError:
                pass

    return ApiResponse(
        status="success",
        data={
            "xmbh": normalized_xmbh,
            "primary_doc_id": primary_doc_id,
            "word_path": normalized_word_path,
            "xmtjbh": xmtjbh,
            "scope": normalized_scope,
            "scope_label": PLAGIARISM_REWARD_SCOPE_CONFIG[normalized_scope],
            "current_nomination_year": current_nd,
            "scope_total_projects": len(scope_ids),
            "available_corpus_docs": len(allowed_doc_ids),
            "debug_report_path": str(debug_output_dir / "plagiarism_report_mammoth.html"),
            "debug_report_upload_path": (
                str(debug_output_dir / "plagiarism_report_upload_plain.html")
                if _is_reward_upload_windows_path(normalized_word_path)
                else None
            ),
            "result": _serialize_plagiarism_result(result),
        },
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
    read_remote_if_missing: bool = Form(True),
    max_concurrency: int = Form(2),
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

    from src.services.grouping.storage.project_repo import ProjectRepository

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
    failed_projects = []
    for project in projects:
        resolved_doc = _resolve_project_doc(
            project_id=project["id"],
            year=project["year"],
            read_remote_if_missing=read_remote_if_missing,
        )
        project_info = {
            "id": project["id"],
            "xmmc": project["xmmc"],
            "year": project["year"],
            "zndm": project["zndm"],
            "guide_name": project["guide_name"],
        }
        resolved_path = resolved_doc["resolved_path"]
        if resolved_path is None:
            missing_docs.append(
                {
                    **project_info,
                    "expected_local_paths": resolved_doc["expected_local_paths"],
                    "remote_path": resolved_doc["remote_path"],
                    "remote_exists": resolved_doc["remote_exists"],
                }
            )
            continue
        available_projects.append(
            {
                **project_info,
                "file_path": str(resolved_path),
                "storage": resolved_doc["storage"],
                "remote_path": resolved_doc["remote_path"],
                "remote_exists": resolved_doc["remote_exists"],
            }
        )

    results = []
    batch_debug_projects = []
    from src.services.plagiarism.agent import PlagiarismAgent

    agent = PlagiarismAgent(
        threshold=threshold,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        section_config=config,
        debug=debug,
    )
    worker_count = max(1, min(int(max_concurrency), 4))
    semaphore = asyncio.Semaphore(worker_count)

    async def _run_project(project: dict) -> tuple[str, dict]:
        async with semaphore:
            file_path = Path(project["file_path"])
            try:
                file_data = file_path.read_bytes()
            except Exception as exc:
                return (
                    "missing",
                    {
                        "id": project["id"],
                        "xmmc": project["xmmc"],
                        "year": project["year"],
                        "zndm": project["zndm"],
                        "guide_name": project["guide_name"],
                        "expected_local_paths": [project["file_path"]],
                        "remote_path": project["remote_path"],
                        "remote_exists": project["remote_exists"],
                        "error": f"读取文件失败: {exc}",
                    },
                )

            project_debug_dir = None
            if debug:
                project_debug_dir = Path("debug_plagiarism") / "by_guide_codes" / project["id"]

            try:
                file_ext = file_path.suffix.lower()
                upload_name = f"{project['id']}{file_ext if file_ext in {'.doc', '.docx', '.pdf'} else '.docx'}"
                result = await agent.check(
                    [(upload_name, file_data)],
                    file_paths={upload_name: str(file_path)},
                    use_corpus=True,
                    debug_output_dir=project_debug_dir,
                )
            except Exception as exc:
                return (
                    "failed",
                    {
                        "id": project["id"],
                        "xmmc": project["xmmc"],
                        "year": project["year"],
                        "zndm": project["zndm"],
                        "guide_name": project["guide_name"],
                        "file_path": project["file_path"],
                        "storage": project["storage"],
                        "remote_path": project["remote_path"],
                        "remote_exists": project["remote_exists"],
                        "error": str(exc),
                    },
                )

            result_item = {
                "project": {
                    "id": project["id"],
                    "xmmc": project["xmmc"],
                    "year": project["year"],
                    "zndm": project["zndm"],
                    "guide_name": project["guide_name"],
                    "file_path": project["file_path"],
                    "storage": project["storage"],
                    "remote_exists": project["remote_exists"],
                },
                "result": _serialize_plagiarism_result(result),
            }
            debug_item = None
            if debug:
                debug_item = {
                    "project": {
                        "id": project["id"],
                        "xmmc": project["xmmc"],
                        "year": project["year"],
                        "zndm": project["zndm"],
                        "guide_name": project["guide_name"],
                        "file_path": project["file_path"],
                        "storage": project["storage"],
                    },
                    "result": _serialize_plagiarism_result(result),
                    "debug": {
                        "report_html_path": str(project_debug_dir / "plagiarism_report_mammoth.html") if project_debug_dir else None,
                    },
                }
            return (
                "ok",
                {
                    "result_item": result_item,
                    "debug_item": debug_item,
                },
            )

    job_results = await asyncio.gather(*[_run_project(project) for project in available_projects])
    for status, payload in job_results:
        if status == "missing":
            missing_docs.append(payload)
        elif status == "failed":
            failed_projects.append(payload)
        elif status == "ok":
            results.append(payload["result_item"])
            if debug and payload.get("debug_item"):
                batch_debug_projects.append(payload["debug_item"])

    batch_report_path = None
    if debug and (results or failed_projects):
        batch_debug_dir = Path("debug_plagiarism") / "by_guide_codes"
        batch_debug_dir.mkdir(parents=True, exist_ok=True)
        batch_report_path = str(
            BatchPlagiarismReportBuilder().build(
                results=batch_debug_projects,
                failed_projects=failed_projects,
                output_html_path=batch_debug_dir / "plagiarism_batch_report.html",
            )
        )

    return ApiResponse(
        status="success",
        data={
            "guide_codes": cleaned_codes,
            "selected_projects": len(projects),
            "resolved_projects": len(available_projects),
            "available_docs": len(results),
            "read_remote_if_missing": read_remote_if_missing,
            "missing_docs": missing_docs,
            "failed_projects": failed_projects,
            "debug_report_path": batch_report_path,
            "results": results,
        },
    )


def _run_plagiarism_by_xmbh(
    *,
    xmbh: str | None,
    dict_type: str,
    scope: str,
    record_id: str | None = None,
    threshold_high: float = 0.8,
    threshold_medium: float = 0.5,
    max_sources: int | None,
) -> ApiResponse[dict]:
    """按项目编号 + 字典类型 + 查询范围执行文本查重（GET/POST 共用实现）。"""
    normalized_xmbh = str(xmbh or "").strip()
    normalized_dict_type = dict_type.strip().lower()
    normalized_scope = scope.strip().lower()
    normalized_record_id = str(record_id or "").strip() or None
    if normalized_dict_type not in PLAGIARISM_REWARD_DICT_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"dict_type 不支持: {dict_type}，可选: {', '.join(PLAGIARISM_REWARD_DICT_CONFIG.keys())}",
        )
    if normalized_record_id and normalized_dict_type != "cxd":
        raise HTTPException(status_code=400, detail="record_id 仅支持 dict_type=cxd 的创新点逐条查重")
    if not normalized_xmbh and not (normalized_dict_type == "cxd" and normalized_record_id):
        raise HTTPException(status_code=400, detail="xmbh 不能为空；若 dict_type=cxd，可改传 record_id")
    if normalized_scope not in PLAGIARISM_REWARD_SCOPE_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"scope 不支持: {scope}，可选: {', '.join(PLAGIARISM_REWARD_SCOPE_CONFIG.keys())}",
        )
    if threshold_high <= 0 or threshold_high > 1 or threshold_medium <= 0 or threshold_medium > 1:
        raise HTTPException(status_code=400, detail="threshold_high/threshold_medium 必须在 (0,1] 区间")
    if threshold_medium > threshold_high:
        raise HTTPException(status_code=400, detail="threshold_medium 不能大于 threshold_high")
    if max_sources is not None and max_sources <= 0:
        raise HTTPException(status_code=400, detail="max_sources 必须为正整数，或不传")

    service = RewardCorpusPlagiarismService(db_name="xmsbnew")
    started = time.time()
    try:
        if normalized_dict_type == "cxd" and normalized_record_id:
            payload = service.check_innovation_item_by_scope(
                record_id=normalized_record_id,
                scope=normalized_scope,
                threshold_high=threshold_high,
                threshold_medium=threshold_medium,
                max_sources=max_sources,
            )
        else:
            payload = service.check_by_scope(
                xmbh=normalized_xmbh,
                dict_type=normalized_dict_type,
                scope=normalized_scope,
                threshold_high=threshold_high,
                threshold_medium=threshold_medium,
                max_sources=max_sources,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        mode_label = "按创新点记录逐条查重" if normalized_dict_type == "cxd" and normalized_record_id else "按项目编号查重"
        raise HTTPException(status_code=500, detail=f"{mode_label}失败: {exc}") from exc

    result = payload["result"]
    result.processing_time = time.time() - started
    primary_record = payload.get("primary_record") if isinstance(payload.get("primary_record"), dict) else None
    resolved_xmbh = str((primary_record or {}).get("xmbh") or normalized_xmbh or "").strip()
    return ApiResponse(
        status="success",
        data={
            "xmbh": resolved_xmbh,
            "dict_type": normalized_dict_type,
            "dict_label": PLAGIARISM_REWARD_DICT_CONFIG[normalized_dict_type]["label"],
            "record_id": normalized_record_id,
            "primary_record": primary_record,
            "scope": normalized_scope,
            "scope_label": PLAGIARISM_REWARD_SCOPE_CONFIG[normalized_scope],
            "current_nomination_year": payload.get("current_nomination_year"),
            "scope_total_projects": payload.get("scope_total_projects", 0),
            "loaded_text_projects": payload.get("loaded_text_projects", 0),
            "loaded_text_items": payload.get("loaded_text_items"),
            "selected_source_docs": payload.get("selected_source_docs", []),
            "selected_source_items": payload.get("selected_source_items", []),
            "corpus_saved_path": payload.get("corpus_saved_path"),
            "html_report_path": payload.get("html_report_path"),
            "result": _serialize_plagiarism_result(result),
        },
    )


@router.get("/by-xmbh")
async def check_plagiarism_by_xmbh_debug(
    xmbh: str | None = Query(None),
    dict_type: str | None = Query(None),
    scope: str | None = Query(None),
    record_id: str | None = Query(None),
    threshold_high: float = Query(0.8),
    threshold_medium: float = Query(0.5),
    max_sources: int | None = Query(None),
) -> ApiResponse[dict]:
    """浏览器调试入口：直接打开 URL 不报 405，带 query 参数可直接执行查重。"""
    if not dict_type or not scope or (not xmbh and not record_id):
        example_url = (
            "/api/v1/plagiarism/by-xmbh?"
            "record_id=1829495626704044034&dict_type=cxd&scope=lshj&threshold_high=0.8&threshold_medium=0.5"
        )
        return ApiResponse(
            status="success",
            data={
                "usage": "请通过 query 传入 dict_type/scope，以及 xmbh 或 record_id 后再访问该 URL。",
                "required_query": ["dict_type", "scope"],
                "either_query": ["xmbh", "record_id"],
                "optional_query": ["threshold_high", "threshold_medium", "max_sources"],
                "example_url": example_url,
                "note": "当 dict_type=cxd 且传 record_id 时，会按单条创新点逐条查重；不传 max_sources 时默认不限制来源数量。",
            },
        )
    return _run_plagiarism_by_xmbh(
        xmbh=xmbh,
        dict_type=dict_type,
        scope=scope,
        record_id=record_id,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        max_sources=max_sources,
    )


@router.post("/by-xmbh")
async def check_plagiarism_by_xmbh(
    request: Request,
    xmbh: str | None = Form(None),
    record_id: str | None = Form(None),
    dict_type: str | None = Form(None),
    scope: str | None = Form(None),
    threshold_high: float | None = Form(None),
    threshold_medium: float | None = Form(None),
    max_sources: int | None = Form(None),
) -> ApiResponse[dict]:
    """按项目编号 + 字典类型 + 查询范围执行文本查重。"""
    query = request.query_params

    def _pick_value(value, key: str) -> str | None:
        if value is not None:
            if isinstance(value, str):
                cleaned = value.strip()
                return cleaned if cleaned else None
            return str(value)
        raw = query.get(key)
        if raw is None:
            return None
        cleaned = raw.strip()
        return cleaned if cleaned else None

    xmbh_value = _pick_value(xmbh, "xmbh")
    record_id_value = _pick_value(record_id, "record_id")
    dict_type_value = _pick_value(dict_type, "dict_type")
    scope_value = _pick_value(scope, "scope")

    threshold_high_raw = _pick_value(threshold_high, "threshold_high")
    threshold_medium_raw = _pick_value(threshold_medium, "threshold_medium")
    max_sources_raw = _pick_value(max_sources, "max_sources")

    if threshold_high_raw is None:
        threshold_high_value = 0.8
    else:
        try:
            threshold_high_value = float(threshold_high_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="threshold_high 必须是数字") from exc

    if threshold_medium_raw is None:
        threshold_medium_value = 0.5
    else:
        try:
            threshold_medium_value = float(threshold_medium_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="threshold_medium 必须是数字") from exc

    if max_sources_raw is None:
        max_sources_value = None
    else:
        try:
            max_sources_value = int(max_sources_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="max_sources 必须是整数") from exc

    if not dict_type_value or not scope_value or (not xmbh_value and not record_id_value):
        raise HTTPException(
            status_code=400,
            detail="dict_type/scope 必填，且 xmbh 与 record_id 至少传一个（支持 query 或 x-www-form-urlencoded 传参）",
        )

    return _run_plagiarism_by_xmbh(
        xmbh=xmbh_value,
        record_id=record_id_value,
        dict_type=dict_type_value,
        scope=scope_value,
        threshold_high=threshold_high_value,
        threshold_medium=threshold_medium_value,
        max_sources=max_sources_value,
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
        data=["pdf", "docx", "doc"],
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

# from src.services.plagiarism.batch_api import check_plagiarism_by_dir
# router.add_api_route("/batch/dir", check_plagiarism_by_dir, methods=["POST"])
