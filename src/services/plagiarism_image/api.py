"""API routes for isolated image plagiarism checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from src.common.database.connection import reward_execute
from src.common.models import ApiResponse
from src.services.grouping.storage.project_repo import ProjectRepository
from src.services.plagiarism.config import (
    PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR,
    PLAGIARISM_REWARD_SCOPE_CONFIG,
    build_reward_upload_windows_file_path,
)
from src.services.plagiarism.smb_file_reader import SMBReviewFileReader

from .agent import ImagePlagiarismAgent
from .config import (
    DEFAULT_HASH_HAMMING_MAX,
    DEFAULT_HIGH_SCORE,
    DEFAULT_MEDIUM_SCORE,
    DEFAULT_MIN_INLIERS,
    IMAGE_BUILD_CPU_QUOTA,
    IMAGE_BUILD_IO_WEIGHT,
    IMAGE_BUILD_MEMORY_MAX,
    IMAGE_PLAGIARISM_DEBUG_ROOT,
    IMAGE_EMBEDDING_MIN_SCORE,
    IMAGE_EMBEDDING_TOP_K,
    IMAGE_EMBEDDING_VERIFY_TOP_K,
)
from .corpus import ImageCorpusManager, resolve_project_doc

router = APIRouter()


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
                    raise HTTPException(status_code=400, detail=f"guide_codes JSON 解析失败: {exc}")
                if not isinstance(parsed, list):
                    raise HTTPException(status_code=400, detail="guide_codes JSON 必须是字符串数组")
                for item in parsed:
                    if isinstance(item, str) and item.strip():
                        codes.append(item.strip())
            else:
                for part in raw.split(","):
                    part = part.strip()
                    if part:
                        codes.append(part)

    if guide_codes_list:
        for item in guide_codes_list:
            if item and item.strip():
                codes.append(item.strip())

    dedup: List[str] = []
    seen = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        dedup.append(code)
    return dedup


def _spawn_build_job(job_id: str) -> None:
    base_cmd = [sys.executable, "-m", "src.services.plagiarism_image.build_runner", "--job-id", str(job_id)]
    systemd_run = shutil.which("systemd-run")
    if systemd_run:
        unit_name = f"plagiarism-image-build-{job_id}"
        systemd_cmd = [
            systemd_run,
            "--user",
            "--no-ask-password",
            "--collect",
            "--same-dir",
            "--unit",
            unit_name,
            "--property",
            f"CPUQuota={IMAGE_BUILD_CPU_QUOTA}",
            "--property",
            f"MemoryMax={IMAGE_BUILD_MEMORY_MAX}",
            "--property",
            f"IOWeight={IMAGE_BUILD_IO_WEIGHT}",
            "--property",
            "Nice=19",
            "--property",
            "IOSchedulingClass=idle",
            "--property",
            "IOSchedulingPriority=7",
            "--quiet",
            "--service-type=exec",
        ] + base_cmd
        try:
            proc = subprocess.run(
                systemd_cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.returncode == 0:
                return
        except Exception:
            pass

    subprocess.Popen(
        base_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


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


def _candidate_reward_upload_word_paths(xmtjbh: str, fallback_year: str | None = None) -> list[str]:
    year = _extract_reward_upload_year(xmtjbh, fallback_year=fallback_year)
    preferred_ext = ".docx"
    if year.isdigit() and int(year) < 2024:
        preferred_ext = ".doc"
    alternate_ext = ".doc" if preferred_ext == ".docx" else ".docx"
    return [
        build_reward_upload_windows_file_path(year=year, xmtjbh=xmtjbh, file_name=f"{xmtjbh}{preferred_ext}"),
        build_reward_upload_windows_file_path(year=year, xmtjbh=xmtjbh, file_name=f"{xmtjbh}{alternate_ext}"),
    ]


def _candidate_reward_upload_local_mirror_paths(xmtjbh: str, fallback_year: str | None = None) -> list[str]:
    tj = str(xmtjbh or "").strip()
    if not tj:
        return []
    year = _extract_reward_upload_year(tj, fallback_year=fallback_year)
    base_dir = Path(PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR) / f"zmcl{year}" / tj
    return [
        str(base_dir / f"{tj}.docx"),
        str(base_dir / f"{tj}.doc"),
    ]


def _merge_unique_paths(*path_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in path_groups:
        for raw in group:
            cleaned = str(raw or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
    return merged


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


def _build_primary_doc_id(*, xmbh: str, resolved_word_path: str, temp_primary_path: str | None) -> str:
    effective_path = str(temp_primary_path or resolved_word_path)
    suffix = Path(effective_path).suffix.lower() or ".docx"
    if suffix not in {".docx", ".doc", ".pdf"}:
        suffix = ".docx"
    return f"{xmbh}{suffix}"


def _encode_abs_path(path: Path) -> str:
    abs_path = path.expanduser().resolve().as_posix().lstrip("/")
    return abs_path.replace("/", "__")


def _candidate_doc_paths_for_self_exclusion(resolved_word_path: str, corpus_path: str | None) -> set[str]:
    candidates: set[str] = set()
    raw = str(resolved_word_path or "").strip()
    if raw:
        candidates.add(str(Path(raw)))
    corpus_root = Path(str(corpus_path or "").strip()) if corpus_path else None
    if corpus_root is not None and corpus_root.name == "_stage_absdocx" and raw:
        src_path = Path(raw)
        suffix = src_path.suffix.lower() or ".docx"
        if suffix not in {".docx", ".doc"}:
            suffix = ".docx"
        candidates.add(str(corpus_root / f"{_encode_abs_path(src_path)}{suffix}"))
    return candidates


def _candidate_doc_tokens_for_self_exclusion(xmbh: str, xmtjbh: str | None) -> set[str]:
    tokens: set[str] = set()
    normalized_xmbh = str(xmbh or "").strip()
    normalized_xmtjbh = str(xmtjbh or "").strip()
    if normalized_xmbh:
        tokens.add(normalized_xmbh)
    if normalized_xmtjbh:
        tokens.add(normalized_xmtjbh)
    return tokens


def _is_excluded_image_entry(entry: Dict, excluded_doc_paths: set[str], excluded_doc_tokens: set[str]) -> bool:
    if not excluded_doc_paths and not excluded_doc_tokens:
        return False
    doc_path = str(entry.get("doc_path", "")).strip()
    doc_id = str(entry.get("doc_id", "")).strip()
    if doc_path and doc_path in excluded_doc_paths:
        return True
    if doc_id and doc_id in excluded_doc_paths:
        return True
    if excluded_doc_tokens:
        combined = f"{doc_path} {doc_id}".lower()
        return any(token.lower() in combined for token in excluded_doc_tokens if token)
    return False


class _FilteredImageCorpusManager:
    def __init__(self, base_manager: ImageCorpusManager, excluded_doc_paths: set[str], excluded_doc_tokens: set[str]) -> None:
        self._base = base_manager
        self._excluded_doc_paths = {str(p).strip() for p in excluded_doc_paths if str(p).strip()}
        self._excluded_doc_tokens = {str(t).strip() for t in excluded_doc_tokens if str(t).strip()}
        self.index = base_manager.index

    def __getattr__(self, name: str):
        return getattr(self._base, name)

    def _is_excluded_source_match(self, image_id: str) -> bool:
        entry = self._base._entry_by_image_id.get(image_id)  # noqa: SLF001
        if not isinstance(entry, dict):
            return False
        return _is_excluded_image_entry(entry, self._excluded_doc_paths, self._excluded_doc_tokens)

    def retrieve_coarse_candidates_for_query_image(
        self,
        query_asset,
        query_fp,
        hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX,
        top_k_coarse: int = 80,
        top_k_final: int = 8,
        exclude_doc_id: Optional[str] = None,
    ) -> Dict[str, object]:
        result = self._base.retrieve_coarse_candidates_for_query_image(
            query_asset=query_asset,
            query_fp=query_fp,
            hash_hamming_max=hash_hamming_max,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            exclude_doc_id=exclude_doc_id,
        )
        exact_matches = [m for m in result.get("exact_matches", []) if not self._is_excluded_source_match(str(m.source_image_id))]
        if exact_matches:
            return {
                "exact_matches": exact_matches,
                "shortlisted": [],
                "coarse_candidates": result.get("coarse_candidates", 0),
            }
        shortlisted = [
            item
            for item in result.get("shortlisted", [])
            if isinstance(item, tuple) and len(item) == 2 and not _is_excluded_image_entry(item[1], self._excluded_doc_paths, self._excluded_doc_tokens)
        ]
        return {
            "exact_matches": [],
            "shortlisted": shortlisted,
            "coarse_candidates": len(shortlisted),
        }

    def retrieve_candidates_for_query_image(
        self,
        query_asset,
        query_fp,
        hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX,
        top_k_coarse: int = 80,
        top_k_final: int = 8,
        exclude_doc_id: Optional[str] = None,
        query_embedding=None,
        source_embeddings=None,
    ) -> Dict[str, object]:
        coarse = self.retrieve_coarse_candidates_for_query_image(
            query_asset=query_asset,
            query_fp=query_fp,
            hash_hamming_max=hash_hamming_max,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            exclude_doc_id=exclude_doc_id,
        )
        exact_matches = coarse.get("exact_matches", [])
        if exact_matches:
            return {
                "exact_matches": exact_matches,
                "verify_candidates": [],
                "coarse_candidates": int(coarse.get("coarse_candidates", 0) or 0),
                "embedding_enabled": bool(self._base._get_embedding_client().enabled),  # noqa: SLF001
                "embedding_candidates": 0,
                "embedding_hits": 0,
            }

        shortlisted = list(coarse.get("shortlisted", []))
        shortlisted_entries = [entry for _, entry in shortlisted]
        embedding_enabled = bool(self._base._get_embedding_client().enabled)  # noqa: SLF001
        embedding_candidates = 0
        embedding_hits = 0
        reranked_entries: List[Dict] = list(shortlisted_entries)
        if embedding_enabled and shortlisted_entries:
            reranked_entries = []
            if query_embedding is None and query_asset.image_bytes:
                query_embedding = self._base._embed_query_asset(query_asset)  # noqa: SLF001
            if query_embedding is not None:
                embedding_candidates = min(len(shortlisted_entries), max(1, int(IMAGE_EMBEDDING_TOP_K)))
                rerank_pool = shortlisted_entries[:embedding_candidates]
                if source_embeddings is None:
                    source_embeddings = self._base._get_or_create_embeddings_for_entries(rerank_pool)  # noqa: SLF001
                scored_entries: List[tuple[float, int, Dict]] = []
                for ham, entry in shortlisted[:embedding_candidates]:
                    image_id = str(entry.get("image_id", ""))
                    source_embedding = source_embeddings.get(image_id) if source_embeddings is not None else None
                    if source_embedding is None:
                        continue
                    embedding_hits += 1
                    score = float(np.dot(query_embedding, source_embedding))
                    if score < IMAGE_EMBEDDING_MIN_SCORE:
                        continue
                    scored_entries.append((score, ham, entry))

                scored_entries.sort(key=lambda x: (-x[0], x[1], str(x[2].get("image_id", ""))))
                verify_limit = max(1, min(int(top_k_final), int(IMAGE_EMBEDDING_VERIFY_TOP_K)))
                for score, _, entry in scored_entries[:verify_limit]:
                    entry_copy = dict(entry)
                    entry_copy["_embedding_score"] = round(score, 4)
                    reranked_entries.append(entry_copy)

        loaded_map = self._base._load_runtime_fps_for_entries(reranked_entries)  # noqa: SLF001
        verify_candidates: List[tuple] = []
        for entry in reranked_entries:
            image_id = str(entry.get("image_id", ""))
            loaded = loaded_map.get(image_id)
            if loaded is None:
                continue
            verify_candidates.append((loaded[0], loaded[1], self._base._as_optional_float(entry.get("_embedding_score"))))  # noqa: SLF001

        return {
            "exact_matches": [],
            "verify_candidates": verify_candidates,
            "coarse_candidates": int(coarse.get("coarse_candidates", 0) or 0),
            "embedding_enabled": embedding_enabled,
            "embedding_candidates": embedding_candidates,
            "embedding_hits": embedding_hits,
        }


async def _run_image_plagiarism_by_file(
    *,
    xmbh: str,
    scope: str,
    word_path: Optional[str] = None,
    threshold_high: float = DEFAULT_HIGH_SCORE,
    threshold_medium: float = DEFAULT_MEDIUM_SCORE,
    hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX,
    min_inliers_high: int = DEFAULT_MIN_INLIERS,
    include_low: bool = False,
    debug: bool = False,
    doc_type: str = "default",
    section_config: Optional[str] = None,
    include_report: bool = True,
    read_remote_if_missing: bool = True,
    top_k_coarse: int = 80,
    top_k_final: int = 8,
    max_pair_checks: int = 120000,
    verify_workers: int = 0,
    verify_backend: str = "auto",
) -> dict:
    normalized_xmbh = str(xmbh).strip()
    normalized_scope = str(scope).strip().lower()
    normalized_word_path = str(word_path).strip() if word_path is not None else ""
    normalized_doc_type = str(doc_type or "default").strip() or "default"

    if not normalized_xmbh:
        raise ValueError("xmbh 不能为空")
    if not normalized_scope:
        raise ValueError("scope 不能为空")
    if normalized_scope not in PLAGIARISM_REWARD_SCOPE_CONFIG:
        raise ValueError(f"scope 不支持: {scope}，可选: {', '.join(PLAGIARISM_REWARD_SCOPE_CONFIG.keys())}")
    if threshold_high <= 0 or threshold_high > 1 or threshold_medium <= 0 or threshold_medium > 1:
        raise ValueError("threshold_high/threshold_medium 必须在 (0,1] 区间")
    if threshold_medium > threshold_high:
        raise ValueError("threshold_medium 不能大于 threshold_high")

    temp_primary_path: str | None = None
    content: bytes | None = None
    resolved_word_path = normalized_word_path
    xmtjbh: str | None = None
    xmtj_year: str | None = None
    corpus_manager: ImageCorpusManager | None = None
    try:
        if not normalized_word_path:
            xmtjbh, xmtj_year = _get_xmtjbh_and_year_by_xmbh("xmsbnew", normalized_xmbh)
            candidates = _merge_unique_paths(
                _candidate_reward_upload_word_paths(xmtjbh, fallback_year=xmtj_year),
                _candidate_reward_upload_local_mirror_paths(xmtjbh, fallback_year=xmtj_year),
            )
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

        corpus_manager = ImageCorpusManager()
        corpus_status = corpus_manager.status()
        if int(corpus_status.get("indexed_images", 0) or 0) <= 0:
            raise HTTPException(
                status_code=400,
                detail="图片库为空：请先调用 /api/v1/plagiarism/image/corpus/build-batch 构建图片索引",
            )

        excluded_doc_paths = _candidate_doc_paths_for_self_exclusion(
            resolved_word_path=normalized_word_path,
            corpus_path=str(corpus_status.get("corpus_path") or ""),
        )
        excluded_doc_tokens = _candidate_doc_tokens_for_self_exclusion(normalized_xmbh, xmtjbh)
        filtered_corpus_manager = _FilteredImageCorpusManager(corpus_manager, excluded_doc_paths, excluded_doc_tokens)

        agent = ImagePlagiarismAgent(
            high_score=threshold_high,
            medium_score=threshold_medium,
            hash_hamming_max=hash_hamming_max,
            min_inliers_high=min_inliers_high,
            include_low=include_low,
        )
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        debug_dir = IMAGE_PLAGIARISM_DEBUG_ROOT / "by_file" / normalized_scope / f"{normalized_xmbh}_{timestamp}"
        debug_dir.mkdir(parents=True, exist_ok=True)

        primary_doc_id = _build_primary_doc_id(
            xmbh=normalized_xmbh,
            resolved_word_path=normalized_word_path,
            temp_primary_path=temp_primary_path,
        )

        if include_report and not debug:
            debug_dir.mkdir(parents=True, exist_ok=True)

        results = agent.check_documents_against_corpus(
            [(primary_doc_id, Path(normalized_word_path).name, content)],
            corpus_manager=filtered_corpus_manager,
            debug=debug,
            include_report=include_report,
            debug_output_dir=debug_dir,
            debug_output_html=debug_dir / "plagiarism_image_by_file_report.html",
            hash_hamming_max=hash_hamming_max,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
            document_labels={primary_doc_id: normalized_xmbh},
        )

        return {
            "xmbh": normalized_xmbh,
            "scope": normalized_scope,
            "scope_label": PLAGIARISM_REWARD_SCOPE_CONFIG.get(normalized_scope),
            "doc_type": normalized_doc_type,
            "word_path": normalized_word_path,
            "xmtjbh": xmtjbh,
            "current_nomination_year": xmtj_year,
            "primary_doc_id": primary_doc_id,
            "debug_output_dir": str(debug_dir),
            "debug_report_path": str(debug_dir / "plagiarism_image_by_file_report.html") if (debug or include_report) else None,
            "debug_report_upload_path": None,
            "result": results,
        }
    finally:
        if corpus_manager is not None:
            corpus_manager.close()
        if temp_primary_path:
            try:
                Path(temp_primary_path).unlink(missing_ok=True)
            except Exception:
                pass


async def _run_image_plagiarism_by_project_scope(
    *,
    xmbh: str,
    scope: str,
    threshold_high: float = DEFAULT_HIGH_SCORE,
    threshold_medium: float = DEFAULT_MEDIUM_SCORE,
    hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX,
    min_inliers_high: int = DEFAULT_MIN_INLIERS,
    include_low: bool = False,
    debug: bool = False,
    include_report: bool = True,
    read_remote_if_missing: bool = True,
    top_k_coarse: int = 80,
    top_k_final: int = 8,
    max_pair_checks: int = 120000,
    verify_workers: int = 0,
    verify_backend: str = "auto",
) -> dict:
    return await _run_image_plagiarism_by_file(
        xmbh=xmbh,
        scope=scope,
        word_path=None,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        hash_hamming_max=hash_hamming_max,
        min_inliers_high=min_inliers_high,
        include_low=include_low,
        debug=debug,
        doc_type="default",
        section_config=None,
        include_report=include_report,
        read_remote_if_missing=read_remote_if_missing,
        top_k_coarse=top_k_coarse,
        top_k_final=top_k_final,
        max_pair_checks=max_pair_checks,
        verify_workers=verify_workers,
        verify_backend=verify_backend,
    )


@router.get("/by-file")
async def check_image_plagiarism_by_file_get(
    xmbh: str = Query(...),
    scope: str = Query(...),
    word_path: Optional[str] = Query(None),
    threshold_high: float = Query(DEFAULT_HIGH_SCORE),
    threshold_medium: float = Query(DEFAULT_MEDIUM_SCORE),
    hash_hamming_max: int = Query(DEFAULT_HASH_HAMMING_MAX),
    min_inliers_high: int = Query(DEFAULT_MIN_INLIERS),
    include_low: bool = Query(False),
    debug: bool = Query(False),
    doc_type: str = Query("default"),
    section_config: Optional[str] = Query(None),
    include_report: bool = Query(True),
    read_remote_if_missing: bool = Query(True),
    top_k_coarse: int = Query(80),
    top_k_final: int = Query(8),
    max_pair_checks: int = Query(120000),
    verify_workers: int = Query(0),
    verify_backend: str = Query("auto"),
) -> ApiResponse[dict]:
    try:
        data = await _run_image_plagiarism_by_file(
            xmbh=xmbh,
            scope=scope,
            word_path=word_path,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            hash_hamming_max=hash_hamming_max,
            min_inliers_high=min_inliers_high,
            include_low=include_low,
            debug=debug,
            doc_type=doc_type,
            section_config=section_config,
            include_report=include_report,
            read_remote_if_missing=read_remote_if_missing,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}") from exc

    return ApiResponse(status="success", data=data)


@router.get("/by-project-scope")
async def check_image_plagiarism_by_project_scope_get(
    xmbh: Optional[str] = Query(None),
    project_number: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    threshold_high: float = Query(DEFAULT_HIGH_SCORE),
    threshold_medium: float = Query(DEFAULT_MEDIUM_SCORE),
    hash_hamming_max: int = Query(DEFAULT_HASH_HAMMING_MAX),
    min_inliers_high: int = Query(DEFAULT_MIN_INLIERS),
    include_low: bool = Query(False),
    debug: bool = Query(False),
    include_report: bool = Query(True),
    read_remote_if_missing: bool = Query(True),
    top_k_coarse: int = Query(80),
    top_k_final: int = Query(8),
    max_pair_checks: int = Query(120000),
    verify_workers: int = Query(0),
    verify_backend: str = Query("auto"),
) -> ApiResponse[dict]:
    resolved_xmbh = str((xmbh or project_number or "")).strip()
    resolved_scope = str(scope or "").strip()

    try:
        data = await _run_image_plagiarism_by_project_scope(
            xmbh=resolved_xmbh,
            scope=resolved_scope,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            hash_hamming_max=hash_hamming_max,
            min_inliers_high=min_inliers_high,
            include_low=include_low,
            debug=debug,
            include_report=include_report,
            read_remote_if_missing=read_remote_if_missing,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}") from exc

    data["query_mode"] = "project_scope"
    data["project_number"] = resolved_xmbh
    return ApiResponse(status="success", data=data)


@router.post("/by-project-scope")
async def check_image_plagiarism_by_project_scope(
    request: Request,
    xmbh: Optional[str] = Form(None),
    project_number: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
    threshold_high: float = Form(DEFAULT_HIGH_SCORE),
    threshold_medium: float = Form(DEFAULT_MEDIUM_SCORE),
    hash_hamming_max: int = Form(DEFAULT_HASH_HAMMING_MAX),
    min_inliers_high: int = Form(DEFAULT_MIN_INLIERS),
    include_low: bool = Form(False),
    debug: bool = Form(False),
    include_report: bool = Form(True),
    read_remote_if_missing: bool = Form(True),
    top_k_coarse: int = Form(80),
    top_k_final: int = Form(8),
    max_pair_checks: int = Form(120000),
    verify_workers: int = Form(0),
    verify_backend: str = Form("auto"),
) -> ApiResponse[dict]:
    query_params = request.query_params
    resolved_xmbh = xmbh if xmbh not in (None, "") else project_number
    if resolved_xmbh in (None, ""):
        resolved_xmbh = query_params.get("xmbh") or query_params.get("project_number")
    resolved_scope = scope if scope not in (None, "") else query_params.get("scope")

    try:
        data = await _run_image_plagiarism_by_project_scope(
            xmbh=str(resolved_xmbh or ""),
            scope=str(resolved_scope or ""),
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            hash_hamming_max=hash_hamming_max,
            min_inliers_high=min_inliers_high,
            include_low=include_low,
            debug=debug,
            include_report=include_report,
            read_remote_if_missing=read_remote_if_missing,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}") from exc

    data["query_mode"] = "project_scope"
    data["project_number"] = str(resolved_xmbh or "")
    return ApiResponse(status="success", data=data)


@router.post("/by-file")
async def check_image_plagiarism_by_file(
    request: Request,
    xmbh: Optional[str] = Form(None),
    word_path: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
    threshold_high: float = Form(DEFAULT_HIGH_SCORE),
    threshold_medium: float = Form(DEFAULT_MEDIUM_SCORE),
    hash_hamming_max: int = Form(DEFAULT_HASH_HAMMING_MAX),
    min_inliers_high: int = Form(DEFAULT_MIN_INLIERS),
    include_low: bool = Form(False),
    debug: bool = Form(False),
    doc_type: Optional[str] = Form(None),
    section_config: Optional[str] = Form(None),
    include_report: bool = Form(True),
    read_remote_if_missing: bool = Form(True),
    top_k_coarse: int = Form(80),
    top_k_final: int = Form(8),
    max_pair_checks: int = Form(120000),
    verify_workers: int = Form(0),
    verify_backend: str = Form("auto"),
) -> ApiResponse[dict]:
    query_params = request.query_params
    resolved_xmbh = xmbh if xmbh not in (None, "") else query_params.get("xmbh")
    resolved_scope = scope if scope not in (None, "") else query_params.get("scope")
    resolved_word_path = word_path if word_path not in (None, "") else query_params.get("word_path")
    resolved_doc_type = doc_type if doc_type not in (None, "") else query_params.get("doc_type", "default")
    resolved_section_config = (
        section_config if section_config not in (None, "") else query_params.get("section_config")
    )

    try:
        data = await _run_image_plagiarism_by_file(
            xmbh=str(resolved_xmbh or ""),
            scope=str(resolved_scope or ""),
            word_path=resolved_word_path,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            hash_hamming_max=hash_hamming_max,
            min_inliers_high=min_inliers_high,
            include_low=include_low,
            debug=debug,
            doc_type=str(resolved_doc_type or "default"),
            section_config=resolved_section_config,
            include_report=include_report,
            read_remote_if_missing=read_remote_if_missing,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}") from exc

    return ApiResponse(status="success", data=data)


@router.post("")
async def check_image_plagiarism(
    files: Optional[List[UploadFile]] = File(None),
    threshold_high: float = Form(DEFAULT_HIGH_SCORE),
    threshold_medium: float = Form(DEFAULT_MEDIUM_SCORE),
    hash_hamming_max: int = Form(DEFAULT_HASH_HAMMING_MAX),
    min_inliers_high: int = Form(DEFAULT_MIN_INLIERS),
    include_low: bool = Form(False),
    debug: bool = Form(False),
    max_pair_checks: int = Form(120000),
) -> ApiResponse[dict]:
    raise HTTPException(
        status_code=400,
        detail="当前仅支持批量文档图片查重，请使用 /api/v1/plagiarism/image/by-guide-codes",
    )


@router.post("/by-guide-codes")
async def check_image_plagiarism_by_guide_codes(
    guide_codes_raw: Optional[str] = Form(None, alias="guide_codes"),
    guide_codes_list: Optional[List[str]] = Form(None, alias="guide_codes_list"),
    threshold_high: float = Form(DEFAULT_HIGH_SCORE),
    threshold_medium: float = Form(DEFAULT_MEDIUM_SCORE),
    hash_hamming_max: int = Form(DEFAULT_HASH_HAMMING_MAX),
    min_inliers_high: int = Form(DEFAULT_MIN_INLIERS),
    include_low: bool = Form(False),
    debug: bool = Form(False),
    limit: Optional[int] = Form(20),
    read_remote_if_missing: bool = Form(True),
    top_k_coarse: int = Form(80),
    top_k_final: int = Form(8),
    max_pair_checks: int = Form(120000),
    verify_workers: int = Form(0),
    verify_backend: str = Form("auto"),
) -> ApiResponse[dict]:
    codes = _normalize_guide_codes(guide_codes_raw, guide_codes_list)
    if not codes:
        raise HTTPException(status_code=400, detail="guide_codes 不能为空")

    projects = ProjectRepository.get_submitted_projects_by_guide_codes(codes, limit=limit)
    if not projects:
        return ApiResponse(
            status="success",
            data={
                "guide_codes": codes,
                "selected_projects": 0,
                "resolved_projects": 0,
                "missing_docs": [],
                "failed_projects": [],
                "results": {"matches": []},
            },
        )

    payload: List[tuple[str, str, bytes]] = []
    missing_docs: List[Dict] = []
    failed_projects: List[Dict] = []
    project_meta: Dict[str, Dict] = {}

    for project in projects:
        resolved = resolve_project_doc(
            project_id=project["id"],
            year=project.get("year", ""),
            read_remote_if_missing=read_remote_if_missing,
        )
        meta = {
            "id": project["id"],
            "xmmc": project.get("xmmc", ""),
            "year": project.get("year", ""),
            "zndm": project.get("zndm", ""),
            "guide_name": project.get("guide_name"),
        }
        resolved_path = resolved.get("resolved_path")
        if resolved_path is None:
            missing_docs.append({
                **meta,
                "expected_local_paths": resolved.get("expected_local_paths", []),
                "remote_path": resolved.get("remote_path"),
                "remote_exists": resolved.get("remote_exists", False),
            })
            continue

        path = Path(str(resolved_path))
        try:
            file_data = path.read_bytes()
        except Exception as exc:
            failed_projects.append({
                **meta,
                "file_path": str(path),
                "error": f"读取文件失败: {exc}",
            })
            continue

        doc_id = project["id"]
        payload.append((doc_id, path.name, file_data))
        project_meta[doc_id] = {
            **meta,
            "file_path": str(path),
            "storage": resolved.get("storage"),
        }

    results: Dict = {
        "documents": 0,
        "images": 0,
        "fingerprinted_images": 0,
        "pair_checks": 0,
        "matches": [],
        "level_count": {},
        "warnings": [],
        "debug_report_path": None,
    }
    if payload:
        corpus_manager = ImageCorpusManager()
        corpus_status = corpus_manager.status()
        if int(corpus_status.get("indexed_images", 0) or 0) <= 0:
            raise HTTPException(
                status_code=400,
                detail="图片库为空：请先调用 /api/v1/plagiarism/image/corpus/build-batch 构建图片索引",
            )
        agent = ImagePlagiarismAgent(
            high_score=threshold_high,
            medium_score=threshold_medium,
            hash_hamming_max=hash_hamming_max,
            min_inliers_high=min_inliers_high,
            include_low=include_low,
        )
        debug_dir = IMAGE_PLAGIARISM_DEBUG_ROOT / "by_guide_codes"
        results = agent.check_documents_against_corpus(
            payload,
            corpus_manager=corpus_manager,
            debug=debug,
            include_report=include_report,
            debug_output_dir=debug_dir,
            debug_output_html=debug_dir / "plagiarism_image_batch_report.html",
            hash_hamming_max=hash_hamming_max,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
            document_labels={doc_id: (meta.get("xmmc") or doc_id) for doc_id, meta in project_meta.items()},
        )

    enriched = []
    for item in results.get("matches", []):
        query_doc = str(item.get("query_doc", ""))
        source_doc = str(item.get("source_doc", ""))
        enriched.append(
            {
                **item,
                "query_project": project_meta.get(query_doc),
                "source_project": project_meta.get(source_doc),
            }
        )
    results["matches"] = enriched
    grouped: Dict[str, List[Dict]] = {}
    for item in enriched:
        qid = str(item.get("query_doc", ""))
        grouped.setdefault(qid, []).append(item)
    per_project_results = []
    for qid, items in grouped.items():
        qmeta = project_meta.get(qid)
        level_count = {"high": 0, "medium": 0, "low": 0}
        for it in items:
            lvl = str(it.get("level", "low"))
            level_count[lvl] = int(level_count.get(lvl, 0)) + 1
        per_project_results.append(
            {
                "project": qmeta,
                "match_count": len(items),
                "level_count": level_count,
                "matches": sorted(items, key=lambda x: (-float(x.get("score", 0.0)), str(x.get("source_doc", "")))),
            }
        )
    per_project_results.sort(key=lambda x: str((x.get("project") or {}).get("id", "")))

    return ApiResponse(
        status="success",
        data={
            "guide_codes": codes,
            "selected_projects": len(projects),
            "resolved_projects": len(payload),
            "missing_docs": missing_docs,
            "failed_projects": failed_projects,
            "per_project_results": per_project_results,
            "results": results,
        },
    )


@router.get("/corpus/status")
async def get_image_corpus_status() -> ApiResponse[dict]:
    manager = ImageCorpusManager()
    try:
        return ApiResponse(status="success", data=manager.status())
    finally:
        manager.close()


@router.post("/corpus/build-batch")
async def build_image_corpus_batch(
    corpus_path: Optional[str] = Form(None),
    limit: int = Form(20),
    reset_cursor: bool = Form(False),
) -> ApiResponse[dict]:
    manager = ImageCorpusManager()
    try:
        result = manager.build_batch(
            corpus_path=Path(corpus_path) if corpus_path else None,
            limit=limit,
            reset_cursor=reset_cursor,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        manager.close()
    return ApiResponse(status="success", data=result)


@router.post("/corpus/build-jobs")
async def submit_image_corpus_build_job(
    corpus_path: Optional[str] = Form(None),
    limit: int = Form(20),
    reset_cursor: bool = Form(False),
) -> ApiResponse[dict]:
    manager = ImageCorpusManager()
    try:
        job = manager.create_build_job(
            corpus_path=Path(corpus_path) if corpus_path else None,
            limit=limit,
            reset_cursor=reset_cursor,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        manager.close()
    _spawn_build_job(str(job["job_id"]))
    return ApiResponse(status="success", data=job)


@router.get("/corpus/build-jobs/{job_id}")
async def get_image_corpus_build_job(job_id: str) -> ApiResponse[dict]:
    manager = ImageCorpusManager()
    try:
        job = manager.get_build_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="build job 不存在")
        return ApiResponse(status="success", data=job)
    finally:
        manager.close()


@router.post("/corpus/reset")
async def reset_image_corpus() -> ApiResponse[dict]:
    manager = ImageCorpusManager()
    try:
        return ApiResponse(status="success", data=manager.reset())
    finally:
        manager.close()
