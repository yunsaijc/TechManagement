"""离线 corpus 维护命令。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.plagiarism.corpus import CorpusManager


def _checkpoint_path() -> Path:
    """返回 checkpoint 路径，优先使用离线 ingest 的独立工作目录。"""
    env_path = os.getenv("PLAGIARISM_CORPUS_CHECKPOINT_PATH")
    if env_path:
        return Path(env_path)
    return Path("data/plagiarism/corpus_refresh_checkpoint.json")


def _manifest_path() -> Path:
    """返回 manifest 路径，允许脚本切到独立工作目录。"""
    env_path = os.getenv("PLAGIARISM_CORPUS_MANIFEST_PATH")
    if env_path:
        return Path(env_path)
    return Path("data/plagiarism/corpus_manifest.json")


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


async def _run_ingest(args: argparse.Namespace) -> int:
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

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--max-scan", type=int, default=2000)
    ingest_parser.add_argument("--limit", type=int, default=5)
    ingest_parser.add_argument("--max-concurrency", type=int, default=4)
    ingest_parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "scan-manifest":
        return asyncio.run(_run_scan_manifest(args))
    if args.command == "build-batch":
        return asyncio.run(_run_build_batch(args))
    if args.command == "ingest":
        return asyncio.run(_run_ingest(args))
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
