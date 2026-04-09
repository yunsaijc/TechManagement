"""API routes for isolated image plagiarism checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.common.models import ApiResponse
from src.services.grouping.storage.project_repo import ProjectRepository

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
            debug_output_dir=debug_dir,
            debug_output_html=debug_dir / "plagiarism_image_batch_report.html",
            hash_hamming_max=hash_hamming_max,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            max_pair_checks=max_pair_checks,
            verify_workers=verify_workers,
            verify_backend=verify_backend,
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
