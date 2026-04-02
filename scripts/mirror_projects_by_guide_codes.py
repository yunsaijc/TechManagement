#!/usr/bin/env python3
"""按指南代码把真实项目 docx 镜像到本地。"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from src.services.grouping.storage.project_repo import ProjectRepository
from src.services.plagiarism.config import (
    PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT,
    PLAGIARISM_DEFAULT_REMOTE_CORPUS_ROOT,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror project DOCX files by guide codes")
    parser.add_argument("guide_codes", nargs="+", help="指南代码列表")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个项目")
    parser.add_argument(
        "--target-root",
        default=str(PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT),
        help="本地镜像根目录",
    )
    parser.add_argument(
        "--remote-root",
        default=str(PLAGIARISM_DEFAULT_REMOTE_CORPUS_ROOT),
        help="远端语料根目录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    projects = ProjectRepository.get_submitted_projects_by_guide_codes(
        args.guide_codes,
        limit=args.limit,
    )
    if not projects:
        print("[mirror-zndm] no submitted projects found")
        return 0

    target_root = Path(args.target_root)
    remote_root = Path(args.remote_root)
    copied = 0
    skipped = 0
    missing = 0

    print(f"[mirror-zndm] target_root={target_root}")
    print(f"[mirror-zndm] remote_root={remote_root}")
    print(f"[mirror-zndm] selected_projects={len(projects)}")

    for index, project in enumerate(projects, start=1):
        project_id = project["id"]
        year = project["year"]
        if not year:
            print(f"[mirror-zndm] skip {project_id}: missing year")
            skipped += 1
            continue

        remote_path = remote_root / year / "sbs" / f"{project_id}.docx"
        target_path = target_root / year / "sbs" / f"{project_id}.docx"
        if target_path.exists():
            skipped += 1
            if index == 1 or index % 50 == 0:
                print(f"[mirror-zndm] progress {index}/{len(projects)} copied={copied} skipped={skipped} missing={missing}")
            continue
        if not remote_path.is_file():
            print(f"[mirror-zndm] missing remote: {remote_path}")
            missing += 1
            if index == 1 or index % 50 == 0:
                print(f"[mirror-zndm] progress {index}/{len(projects)} copied={copied} skipped={skipped} missing={missing}")
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(remote_path, target_path)
        copied += 1

        if index == 1 or index % 50 == 0 or index == len(projects):
            print(f"[mirror-zndm] progress {index}/{len(projects)} copied={copied} skipped={skipped} missing={missing}")

    print(f"[mirror-zndm] done copied={copied} skipped={skipped} missing={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
