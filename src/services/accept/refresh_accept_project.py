#!/usr/bin/env python3
"""刷新单个项目的验收核查结果（不依赖 PyMuPDF / viewer）。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.accept.debug_workflow import (
    build_acceptance_project_payload,
    load_existing_results,
    persist_acceptance_project_payload,
)


async def main_async(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir)
    year = args.year
    project_no = args.project_no
    results_path = input_dir / "acceptance_results.json"
    existing_results = load_existing_results(results_path)
    existing_project = next(
        (item for item in existing_results if str(item.get("project_no") or "") == project_no),
        None,
    )

    refreshed = await build_acceptance_project_payload(
        input_dir=input_dir,
        year=year,
        project_no=project_no,
        taskbook_path=Path(args.taskbook_path),
        yssq_path=Path(args.yssq_path),
        attachment_dir=Path(args.attachment_dir),
        project_name=args.project_name or (str(existing_project.get("project_name") or "") if existing_project else ""),
    )
    await persist_acceptance_project_payload(
        input_dir=input_dir,
        payload=refreshed,
        existing_results=existing_results,
        existing_project=existing_project,
    )

    print(
        f"[refresh-accept] project_no={project_no} "
        f"fulfillment_rate={refreshed['fulfillment_rate']} "
        f"fulfilled={refreshed['fulfilled_commitments']}/{refreshed['total_commitments']} "
        f"partial={refreshed['partial_commitments']} missing={refreshed['missing_commitments']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh acceptance check result for one project.")
    parser.add_argument("--input-dir", default=str(ROOT / "debug_accept"))
    parser.add_argument("--year", default="2019")
    parser.add_argument("--project-no", required=True)
    parser.add_argument("--project-name", default="")
    parser.add_argument("--taskbook-path", required=True)
    parser.add_argument("--yssq-path", required=True)
    parser.add_argument("--attachment-dir", required=True)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
