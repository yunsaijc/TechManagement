"""离线 corpus 维护命令。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.plagiarism.config import (
    PLAGIARISM_DEFAULT_CHECKPOINT_PATH,
    PLAGIARISM_DEFAULT_MANIFEST_PATH,
    PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR,
    build_reward_upload_windows_file_path,
)
from src.services.plagiarism.corpus import CorpusManager
from src.services.plagiarism.reward_corpus_manager import RewardCorpusManager
from src.services.plagiarism.smb_file_reader import SMBReviewFileReader
from src.common.database.connection import reward_execute


def _checkpoint_path() -> Path:
    """返回 checkpoint 路径，优先使用离线 ingest 的独立工作目录。"""
    env_path = os.getenv("PLAGIARISM_CORPUS_CHECKPOINT_PATH")
    if env_path:
        return Path(env_path)
    return Path(PLAGIARISM_DEFAULT_CHECKPOINT_PATH)


def _manifest_path() -> Path:
    """返回 manifest 路径，允许脚本切到独立工作目录。"""
    env_path = os.getenv("PLAGIARISM_CORPUS_MANIFEST_PATH")
    if env_path:
        return Path(env_path)
    return Path(PLAGIARISM_DEFAULT_MANIFEST_PATH)


def _print_json(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _on_progress(progress: dict) -> None:
    stage = progress.get("stage") or "unknown"
    processed = progress.get("processed") or 0
    total = progress.get("total") or 0
    elapsed = progress.get("elapsed_seconds") or 0
    stats = progress.get("stats") or {}
    print(
        f"[CorpusCLI] stage={stage}, processed={processed}, total={total}, "
        f"elapsed={elapsed}s, stats={json.dumps(stats, ensure_ascii=False)}"
    )


def _read_checkpoint() -> Dict[str, Any]:
    checkpoint_path = _checkpoint_path()
    if not checkpoint_path.exists():
        return {"next_cursor": None, "has_more": False, "updated_at": None, "last_task_id": None}
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception:
        return {"next_cursor": None, "has_more": False, "updated_at": None, "last_task_id": None}
    return data if isinstance(data, dict) else {"next_cursor": None, "has_more": False}


def _write_checkpoint(next_cursor: Optional[str], has_more: bool, last_task_id: str) -> None:
    checkpoint_path = _checkpoint_path()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "next_cursor": next_cursor if has_more else None,
        "has_more": bool(has_more),
        "updated_at": time.time(),
        "last_task_id": last_task_id,
    }
    checkpoint_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _pending_manifest_count() -> int:
    manifest_path = _manifest_path()
    if not manifest_path.exists():
        return 0
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    return sum(
        1 for item in data.values()
        if isinstance(item, dict) and item.get("action") in {"new", "update", "fix_path"}
    )


async def _run_scan_manifest(args: argparse.Namespace) -> int:
    manager = CorpusManager(scan_only=True)
    checkpoint = _read_checkpoint()
    cursor_doc_id = args.cursor_doc_id if args.cursor_doc_id is not None else checkpoint.get("next_cursor")
    result = manager.scan_manifest(
        cursor_doc_id=cursor_doc_id,
        max_scan=args.max_scan,
        progress_callback=_on_progress if args.verbose else None,
    )
    _write_checkpoint(
        next_cursor=result.get("next_cursor"),
        has_more=bool(result.get("has_more")),
        last_task_id=f"scan-manifest@{int(time.time())}",
    )
    result["checkpoint"] = _read_checkpoint()
    _print_json(result)
    return 0


async def _run_build_batch(args: argparse.Namespace) -> int:
    manager = CorpusManager()
    result = await manager.build_batch_from_manifest(
        limit=args.limit,
        max_concurrency=args.max_concurrency,
        progress_callback=_on_progress if args.verbose else None,
    )
    result["checkpoint"] = _read_checkpoint()
    _print_json(result)
    return 0


async def _run_rebuild_coarse(args: argparse.Namespace) -> int:
    manager = CorpusManager()
    result = manager.rebuild_coarse_index(
        batch_size=args.batch_size,
        progress_callback=_on_progress if args.verbose else None,
    )
    _print_json(result)
    return 0


async def _run_ingest_docs(args: argparse.Namespace) -> int:
    manager = CorpusManager()
    round_index = 1

    while True:
        checkpoint = _read_checkpoint()
        pending = _pending_manifest_count()
        should_scan = bool(checkpoint.get("has_more")) or pending == 0

        if should_scan:
            cursor_doc_id = checkpoint.get("next_cursor")
            scan_result = manager.scan_manifest(
                cursor_doc_id=cursor_doc_id,
                max_scan=args.max_scan,
                progress_callback=_on_progress if args.verbose else None,
            )
            _write_checkpoint(
                next_cursor=scan_result.get("next_cursor"),
                has_more=bool(scan_result.get("has_more")),
                last_task_id=f"scan-manifest@{int(time.time())}",
            )
            if args.verbose:
                _print_json(
                    {
                        "round": round_index,
                        "phase": "scan",
                        **scan_result,
                        "checkpoint": _read_checkpoint(),
                    }
                )

        build_result = await manager.build_batch_from_manifest(
            limit=args.limit,
            max_concurrency=args.max_concurrency,
            progress_callback=_on_progress if args.verbose else None,
        )
        build_result["checkpoint"] = _read_checkpoint()
        if args.verbose:
            _print_json({"round": round_index, "phase": "build", **build_result})

        pending = int(build_result.get("remaining") or 0)
        checkpoint = _read_checkpoint()
        if pending == 0 and not checkpoint.get("has_more"):
            _print_json(
                {
                    "completed": True,
                    "rounds": round_index,
                    "pending": pending,
                    "checkpoint": checkpoint,
                }
            )
            return 0

        round_index += 1


async def _run_ingest(args: argparse.Namespace) -> int:
    docs_exit = await _run_ingest_docs(args)
    if docs_exit != 0:
        return docs_exit

    coarse_args = argparse.Namespace(
        batch_size=args.coarse_batch_size,
        verbose=args.verbose,
    )
    rebuild_exit = await _run_rebuild_coarse(coarse_args)
    if rebuild_exit != 0:
        return rebuild_exit

    _print_json(
        {
            "completed": True,
            "phase": "all_done",
            "checkpoint": _read_checkpoint(),
        }
    )
    return 0


def _file_corpus_root() -> Path:
    return Path(PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR)


def _extract_reward_upload_year(xmtjbh: str, fallback_year: str | None = None) -> str:
    tj = str(xmtjbh or "").strip()
    match = re.match(r"^(\d{4})-", tj)
    if match:
        return match.group(1)
    year = str(fallback_year or "").strip()
    if re.fullmatch(r"\d{4}", year):
        return year
    raise ValueError(f"无法确定提名号 {tj} 对应的材料年度")


def _build_k_upload_path(xmtjbh: str, fallback_year: str | None = None) -> str:
    year = _extract_reward_upload_year(xmtjbh, fallback_year=fallback_year)
    ext = _reward_upload_extension(year)
    return build_reward_upload_windows_file_path(year=year, xmtjbh=xmtjbh, file_name=f"{xmtjbh}{ext}")


def _file_corpus_dest_path(xmtjbh: str, fallback_year: str | None = None) -> Path:
    tj = str(xmtjbh).strip()
    year = _extract_reward_upload_year(tj, fallback_year=fallback_year)
    return _file_corpus_root() / f"zmcl{year}" / tj / f"{tj}{_reward_upload_extension(year)}"


def _reward_upload_extension(year: str) -> str:
    if year.isdigit() and int(year) < 2024:
        return ".doc"
    return ".docx"


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _write_bytes_if_changed(dest: Path, content: bytes) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            if dest.stat().st_size == len(content):
                existing = dest.read_bytes()
                if _md5_bytes(existing) == _md5_bytes(content):
                    return False
        except OSError:
            pass
    tmp_path = dest.with_name(f"{dest.name}.tmp")
    with open(tmp_path, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, dest)
    return True


def _create_file_corpus_manager(corpus_root: Path) -> CorpusManager:
    env_keys = [
        "PLAGIARISM_CORPUS_PATH",
        "PLAGIARISM_CORPUS_INDEX_PATH",
        "PLAGIARISM_CORPUS_SQLITE_PATH",
        "PLAGIARISM_CORPUS_MANIFEST_PATH",
    ]
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ["PLAGIARISM_CORPUS_PATH"] = str(corpus_root)
    os.environ["PLAGIARISM_CORPUS_INDEX_PATH"] = str(corpus_root / "corpus_index.json")
    os.environ["PLAGIARISM_CORPUS_SQLITE_PATH"] = str(corpus_root / "corpus_index.db")
    os.environ["PLAGIARISM_CORPUS_MANIFEST_PATH"] = str(corpus_root / "corpus_manifest.json")
    try:
        return CorpusManager(corpus_path=str(corpus_root), index_save_path=str(corpus_root / "corpus_index.json"))
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _get_xmbh_to_xmtjbh(db_name: str, xmbh_ids: list[str]) -> dict[str, dict[str, str | None]]:
    cleaned = [str(x).strip() for x in xmbh_ids if str(x).strip()]
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


async def _run_sync_file_corpus(args: argparse.Namespace) -> int:
    db_name = str(args.db_name or "xmsbnew")
    scope = str(args.scope).strip().lower()
    if scope not in {"dn", "lshj"}:
        raise SystemExit("scope 只能是 dn 或 lshj")

    manager = RewardCorpusManager(db_name=db_name)
    current_nd = manager.get_current_nomination_year()
    scope_xmbh_ids = manager.get_scope_project_ids(scope, current_nd=current_nd)
    if args.limit:
        scope_xmbh_ids = scope_xmbh_ids[: int(args.limit)]

    xmbh_to_xmtjbh = _get_xmbh_to_xmtjbh(db_name, scope_xmbh_ids)
    xmtjbh_list = [xmbh_to_xmtjbh.get(xmbh) for xmbh in scope_xmbh_ids]
    xmtjbh_list = [x for x in xmtjbh_list if x and x.get("xmtjbh")]

    reader = SMBReviewFileReader()
    download_semaphore = asyncio.Semaphore(max(1, int(args.download_concurrency)))
    stats = {"projects": len(scope_xmbh_ids), "with_xmtjbh": len(xmtjbh_list), "downloaded": 0, "skipped": 0, "failed": 0}
    failed: list[dict] = []

    async def download_one(doc_info: dict[str, str | None]) -> None:
        nonlocal stats
        async with download_semaphore:
            xmtjbh = str(doc_info.get("xmtjbh") or "").strip()
            year = str(doc_info.get("year") or "").strip() or None
            k_path = _build_k_upload_path(xmtjbh, fallback_year=year)
            dest_path = _file_corpus_dest_path(xmtjbh, fallback_year=year)
            try:
                content = await asyncio.to_thread(reader.read_bytes, k_path)
                changed = _write_bytes_if_changed(dest_path, content)
                if changed:
                    stats["downloaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                stats["failed"] += 1
                failed.append({"xmtjbh": xmtjbh, "year": year, "path": k_path, "error": str(exc)})

    tasks = [asyncio.create_task(download_one(doc_info)) for doc_info in xmtjbh_list]
    for completed in asyncio.as_completed(tasks):
        await completed

    file_root = _file_corpus_root()
    corpus = _create_file_corpus_manager(file_root)

    cursor = None
    while True:
        scan_result = corpus.scan_manifest(
            cursor_doc_id=cursor,
            max_scan=args.max_scan,
            progress_callback=_on_progress if args.verbose else None,
        )
        cursor = scan_result.get("next_cursor") if scan_result.get("has_more") else None

        while True:
            build_result = await corpus.build_batch_from_manifest(
                limit=args.build_limit,
                max_concurrency=args.index_concurrency,
                progress_callback=_on_progress if args.verbose else None,
            )
            if not build_result.get("has_more"):
                break

        if not scan_result.get("has_more"):
            break

    coarse_result = corpus.rebuild_coarse_index(
        batch_size=args.coarse_batch_size,
        progress_callback=_on_progress if args.verbose else None,
    )

    _print_json(
        {
            "scope": scope,
            "current_nomination_year": current_nd,
            "sync": stats,
            "failed": failed,
            "corpus": {
                "root": str(file_root),
                "index_path": str(file_root / "corpus_index.json"),
                "sqlite_path": str(file_root / "corpus_index.db"),
                "manifest_path": str(file_root / "corpus_manifest.json"),
                "document_count": len(corpus.index.documents),
                "last_updated": corpus.index.last_updated,
            },
            "coarse": coarse_result,
        }
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan-manifest")
    scan_parser.add_argument("--cursor-doc-id", default=None)
    scan_parser.add_argument("--max-scan", type=int, default=2000)
    scan_parser.add_argument("--verbose", action="store_true")

    build_parser = subparsers.add_parser("build-batch")
    build_parser.add_argument("--limit", type=int, default=5)
    build_parser.add_argument("--max-concurrency", type=int, default=4)
    build_parser.add_argument("--verbose", action="store_true")

    rebuild_parser = subparsers.add_parser("rebuild-coarse")
    rebuild_parser.add_argument("--batch-size", type=int, default=50)
    rebuild_parser.add_argument("--verbose", action="store_true")

    ingest_docs_parser = subparsers.add_parser("ingest-docs")
    ingest_docs_parser.add_argument("--max-scan", type=int, default=2000)
    ingest_docs_parser.add_argument("--limit", type=int, default=5)
    ingest_docs_parser.add_argument("--max-concurrency", type=int, default=4)
    ingest_docs_parser.add_argument("--verbose", action="store_true")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--max-scan", type=int, default=2000)
    ingest_parser.add_argument("--limit", type=int, default=5)
    ingest_parser.add_argument("--max-concurrency", type=int, default=4)
    ingest_parser.add_argument("--coarse-batch-size", type=int, default=50)
    ingest_parser.add_argument("--verbose", action="store_true")

    sync_file_parser = subparsers.add_parser("sync-file-corpus")
    sync_file_parser.add_argument("--scope", required=True, choices=["dn", "lshj"])
    sync_file_parser.add_argument("--db-name", default="xmsbnew")
    sync_file_parser.add_argument("--limit", type=int, default=None)
    sync_file_parser.add_argument("--download-concurrency", type=int, default=2)
    sync_file_parser.add_argument("--max-scan", type=int, default=None)
    sync_file_parser.add_argument("--build-limit", type=int, default=50)
    sync_file_parser.add_argument("--index-concurrency", type=int, default=2)
    sync_file_parser.add_argument("--coarse-batch-size", type=int, default=50)
    sync_file_parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "scan-manifest":
        return asyncio.run(_run_scan_manifest(args))
    if args.command == "build-batch":
        return asyncio.run(_run_build_batch(args))
    if args.command == "rebuild-coarse":
        return asyncio.run(_run_rebuild_coarse(args))
    if args.command == "ingest-docs":
        return asyncio.run(_run_ingest_docs(args))
    if args.command == "ingest":
        return asyncio.run(_run_ingest(args))
    if args.command == "sync-file-corpus":
        return asyncio.run(_run_sync_file_corpus(args))
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
