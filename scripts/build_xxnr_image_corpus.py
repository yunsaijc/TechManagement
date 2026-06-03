#!/usr/bin/env python3
"""Build an image plagiarism corpus for file_local_ingest DOCX files.

This script scans DOCX/PDF files under the source directory, extracts embedded
images, fingerprints them, and stores the resulting corpus files under the
target output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np


def _ensure_cv2_phash() -> None:
    img_hash = getattr(cv2, "img_hash", None)
    if img_hash is None:
        return
    if hasattr(img_hash, "pHash"):
        return

    def _phash(bgr: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
        dct = cv2.dct(np.float32(resized))
        low_freq = dct[:8, :8].flatten()
        median = float(np.median(low_freq[1:])) if low_freq.size > 1 else float(low_freq[0])
        bits = np.array([1 if float(v) > median else 0 for v in low_freq], dtype=np.uint8)
        packed = np.packbits(bits, bitorder="big")
        return packed.reshape(1, -1)

    setattr(img_hash, "pHash", _phash)


_ensure_cv2_phash()

from src.services.plagiarism_image.corpus import ImageCorpusManager


DEFAULT_SOURCE_ROOT = Path("/home/tdkx/workspace/tech/data/plagiarism/file_local_ingest")
DEFAULT_OUTPUT_ROOT = Path("/home/tdkx/workspace/tech/data/plagiarism_image/xxnr")
SAFE_LARGE_CORPUS_LIMIT = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build image plagiarism corpus for xxnr")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--limit", type=int, default=200, help="Documents per build batch")
    parser.add_argument("--reset", action="store_true", help="Reset existing build cursor before rebuilding")
    return parser.parse_args()


def _make_manager(output_root: Path) -> ImageCorpusManager:
    index_dir = output_root / "index"
    return ImageCorpusManager(
        index_path=index_dir / "image_index.json",
        manifest_path=index_dir / "image_manifest.json",
        checkpoint_path=index_dir / "image_checkpoint.json",
        feature_db_path=index_dir / "image_features.sqlite3",
        build_lock_path=index_dir / "image_build.lock",
    )


def _encode_abs_path(path: Path) -> str:
    abs_path = path.expanduser().resolve().as_posix().lstrip("/")
    return abs_path.replace("/", "__")


def _prepare_staging_root(source_root: Path, output_root: Path) -> Path:
    stage_root = output_root / "_stage_absdocx"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)

    docs = sorted(source_root.rglob("*.docx"), key=lambda p: str(p))
    for src in docs:
        rel_name = _encode_abs_path(src)
        link_path = stage_root / f"{rel_name}.docx"
        link_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(src.resolve(), link_path)
        except FileExistsError:
            link_path.unlink()
            os.symlink(src.resolve(), link_path)
    return stage_root


def _build_all(manager: ImageCorpusManager, source_root: Path, limit: int, reset: bool) -> list[dict]:
    rounds: list[dict] = []
    first_round = True
    while True:
        result = manager.build_batch(
            corpus_path=source_root,
            limit=limit,
            reset_cursor=reset if first_round else False,
        )
        rounds.append(result)
        first_round = False
        if not result.get("has_more"):
            break
    return rounds


def _retry_limit_from_error(error_text: str) -> int:
    match = re.search(r"limit>=\s*(\d+)", error_text)
    if match:
        return max(SAFE_LARGE_CORPUS_LIMIT, int(match.group(1)))
    match = re.search(r"limit >= (\d+)", error_text)
    if match:
        return max(SAFE_LARGE_CORPUS_LIMIT, int(match.group(1)))
    return SAFE_LARGE_CORPUS_LIMIT


def main() -> int:
    args = parse_args()
    source_root = args.source_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()

    if not source_root.exists() or not source_root.is_dir():
        raise SystemExit(f"source-root 不存在或不是目录: {source_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    manager = _make_manager(output_root)
    staging_root = _prepare_staging_root(source_root, output_root)
    try:
        if args.reset:
            manager.reset()

        requested_limit = max(1, args.limit)
        try:
            build_rounds = _build_all(manager, source_root=staging_root, limit=requested_limit, reset=args.reset)
        except ValueError as exc:
            error_text = str(exc)
            if "IO 保护阈值" not in error_text and "limit" not in error_text:
                raise
            retry_limit = _retry_limit_from_error(error_text)
            print(
                f"检测到大语料保护阈值，自动将 limit 从 {requested_limit} 提升到 {retry_limit} 后重试。",
                file=sys.stderr,
            )
            if args.reset:
                manager.reset()
            build_rounds = _build_all(manager, source_root=staging_root, limit=retry_limit, reset=args.reset)

        status = manager.status()
        payload = {
            "source_root": str(source_root),
            "output_root": str(output_root),
            "index_path": status["index_path"],
            "manifest_path": status["manifest_path"],
            "checkpoint_path": status["checkpoint_path"],
            "feature_db_path": status["feature_db_path"],
            "build_rounds": build_rounds,
            "status": status,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        manager.close()
        shutil.rmtree(staging_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())