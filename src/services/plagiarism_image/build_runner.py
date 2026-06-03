"""Low-priority image corpus build runner."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from .config import IMAGE_BUILD_NICE_LEVEL
from .corpus import ImageCorpusManager


def _apply_low_priority() -> None:
    try:
        os.nice(IMAGE_BUILD_NICE_LEVEL)
    except OSError:
        pass

    ionice_bin = shutil.which("ionice")
    if not ionice_bin:
        return
    try:
        subprocess.run(
            [ionice_bin, "-c3", "-p", str(os.getpid())],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    _apply_low_priority()

    manager = ImageCorpusManager()
    shadow_path = manager.shadow_db_path(args.job_id)
    shadow_manager = ImageCorpusManager(
        feature_db_path=shadow_path,
        index_path=manager.index_path,
        manifest_path=manager.manifest_path,
        checkpoint_path=manager.checkpoint_path,
        build_lock_path=manager.build_lock_path,
    )
    try:
        manager.attach_build_job_pid(args.job_id, os.getpid())
        job = manager.start_build_job(args.job_id)
        if not job or str(job.get("status")) != "running":
            return 0
        if not bool(job.get("reset_cursor")):
            manager.clone_active_db_to_shadow(shadow_path)
        result = shadow_manager.build_batch(
            corpus_path=job["corpus_path"],
            limit=int(job["limit"]),
            reset_cursor=bool(job["reset_cursor"]),
        )
        shadow_manager.close()
        manager.promote_shadow_db(shadow_path)
        manager.finish_build_job(args.job_id, status="completed", result=result, error=None)
        return 0
    except Exception as exc:
        manager.finish_build_job(args.job_id, status="failed", result=None, error=str(exc))
        return 1
    finally:
        shadow_manager.close()
        manager.cleanup_shadow_db(shadow_path)
        manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
