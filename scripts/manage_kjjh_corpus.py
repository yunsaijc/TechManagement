#!/usr/bin/env python3
"""KJJH 合同文档本地建库管理工具."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.append(os.getcwd())

from src.services.plagiarism.kjjh_corpus_manager import KJJHCorpusManager


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def _run_build(
    manager: KJJHCorpusManager,
    *,
    max_scan: int,
    build_limit: int,
    max_concurrency: int,
    coarse_batch_size: int,
) -> dict:
    corpus = manager.create_corpus_manager()
    scan_result = corpus.scan_manifest(max_scan=max_scan)

    build_rounds = []
    while True:
        build_result = await corpus.build_batch_from_manifest(
            limit=build_limit,
            max_concurrency=max_concurrency,
        )
        build_rounds.append(build_result)
        if not build_result.get("has_more"):
            break

    coarse_result = corpus.rebuild_coarse_index(batch_size=coarse_batch_size)
    return {
        "scan": scan_result,
        "build_rounds": build_rounds,
        "coarse": coarse_result,
        "document_count": len(corpus.index.documents),
        "index_path": str(manager.index_path),
        "sqlite_path": str(manager.sqlite_path),
        "manifest_path": str(manager.manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="KJJH 合同文档本地建库管理工具")
    parser.add_argument(
        "--action",
        required=True,
        choices=["status", "sync-files", "build", "run-all"],
    )
    parser.add_argument("--min-year", type=int, default=2022)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-scan", type=int, default=2000)
    parser.add_argument("--build-limit", type=int, default=50)
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--coarse-batch-size", type=int, default=50)

    args = parser.parse_args()
    manager = KJJHCorpusManager()

    if args.action == "status":
        _print_json(
            {
                "source_corpus_root": str(manager.source_corpus_root),
                "local_ingest_root": str(manager.local_ingest_root),
                "index_path": str(manager.index_path),
                "sqlite_path": str(manager.sqlite_path),
                "manifest_path": str(manager.manifest_path),
                "checkpoint_path": str(manager.checkpoint_path),
                "remote_corpus_root": str(manager.remote_corpus_root),
            }
        )
        return

    if args.action == "sync-files":
        _print_json(manager.sync_local_files(min_year=args.min_year, limit=args.limit))
        return

    if args.action == "build":
        payload = asyncio.run(
            _run_build(
                manager,
                max_scan=args.max_scan,
                build_limit=args.build_limit,
                max_concurrency=args.max_concurrency,
                coarse_batch_size=args.coarse_batch_size,
            )
        )
        _print_json(payload)
        return

    if args.action == "run-all":
        sync_payload = manager.sync_local_files(min_year=args.min_year, limit=args.limit)
        build_payload = asyncio.run(
            _run_build(
                manager,
                max_scan=args.max_scan,
                build_limit=args.build_limit,
                max_concurrency=args.max_concurrency,
                coarse_batch_size=args.coarse_batch_size,
            )
        )
        _print_json(
            {
                "sync": sync_payload,
                "build": build_payload,
            }
        )
        return


if __name__ == "__main__":
    main()
