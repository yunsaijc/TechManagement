"""独立进程执行 corpus refresh，并将状态写入磁盘。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.plagiarism.corpus import CorpusManager


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


def _load_status(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _run(args: argparse.Namespace) -> None:
    status_path = Path(args.status_path)
    manager = CorpusManager()
    started_at = time.time()
    last_status_write_at = 0.0
    last_status_processed = 0
    status: Dict[str, Any] = {
        "running": True,
        "task_id": args.task_id,
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": None,
        "error": None,
        "params": {
            "limit": args.limit,
            "batch_size": args.batch_size,
            "max_concurrency": args.max_concurrency,
            "save_every_batches": args.save_every_batches,
        },
        "progress": None,
        "result": None,
    }
    _write_json_atomic(status_path, status)

    def on_progress(progress: dict) -> None:
        nonlocal last_status_write_at, last_status_processed
        status["progress"] = progress
        now = time.time()
        processed = int(progress.get("processed") or 0)
        stage = progress.get("stage")
        should_write = (
            processed <= 1
            or processed - last_status_processed >= 10
            or now - last_status_write_at >= 2.0
            or bool(stage)
            or processed >= int(progress.get("total") or 0)
        )
        if not should_write:
            return
        last_status_processed = processed
        last_status_write_at = now
        _write_json_atomic(status_path, status)

    try:
        stats = await manager.scan_and_update_with_options(
            limit=args.limit,
            batch_size=args.batch_size,
            max_concurrency=args.max_concurrency,
            save_every_batches=args.save_every_batches,
            progress_callback=on_progress,
        )
        status["result"] = stats
    except Exception as exc:
        status["error"] = str(exc)
        raise
    finally:
        status["running"] = False
        status["finished_at"] = time.time()
        _write_json_atomic(status_path, status)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-path", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--save-every-batches", type=int, default=10)
    args = parser.parse_args(argv)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
