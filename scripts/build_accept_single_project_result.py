#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.accept.run_accept_local_batch import (
    build_office_preview_assets,
    detect_file_type,
    select_candidate_attachment_paths,
    to_browser_relative,
)
from src.services.accept.service import AcceptanceService


def excerpt_text(text: str, limit: int = 2400) -> str:
    compact = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "\n..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a single acceptance result JSON.")
    parser.add_argument("--year", required=True)
    parser.add_argument("--project-no", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--taskbook-path", required=True)
    parser.add_argument("--acceptance-application-path", required=True)
    parser.add_argument("--acceptance-attachment-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", default="")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    root = PROJECT_ROOT
    cache_dir = Path(args.cache_dir) if args.cache_dir else root / "debug_accept" / ".accept_parse_cache" / args.year
    service = AcceptanceService(cache_dir=cache_dir)

    taskbook_path = Path(args.taskbook_path)
    yssq_path = Path(args.acceptance_application_path)
    attachment_dir = Path(args.acceptance_attachment_dir)

    taskbook = await service.parser.parse_bytes(
        file_data=taskbook_path.read_bytes(),
        file_type=detect_file_type(taskbook_path.name),
        file_name=taskbook_path.name,
    )
    yssq_document = await service.parser.parse_bytes(
        file_data=yssq_path.read_bytes(),
        file_type=detect_file_type(yssq_path.name),
        file_name=yssq_path.name,
    )

    candidate_paths = select_candidate_attachment_paths(
        attachment_dir=attachment_dir,
        taskbook=taskbook,
        yssq=yssq_document,
        service=service,
    )

    attachment_inputs = [yssq_document]
    parsed_attachments = [yssq_document]
    attachment_docs_payload: list[dict[str, object]] = []
    for file_path in candidate_paths:
        if not file_path.is_file():
            continue
        doc = await service.parser.parse_bytes(
            file_data=file_path.read_bytes(),
            file_type=detect_file_type(file_path.name),
            file_name=file_path.name,
        )
        if service.evidence_extractor.should_skip_attachment(doc):
            continue
        attachment_inputs.append(doc)
        parsed_attachments.append(doc)
        attachment_docs_payload.append(
            {
                "role": "yssqfj",
                "file_name": doc.file_name,
                "display_title": service.evidence_extractor.document_display_title(doc),
                "file_path": str(file_path),
                "browser_file": to_browser_relative(input_dir := (root / "debug_accept"), file_path),
                "file_type": doc.file_type,
                "viewer_file": "",
                "packet_file": "",
                "preview_file": "",
                "preview_type": "",
                "text_excerpt": excerpt_text(doc.text),
            }
        )

    result = service.check_from_documents(
        project_id=args.project_no,
        taskbook=taskbook,
        attachments=parsed_attachments,
    )

    input_dir = root / "debug_accept"
    taskbook_preview = build_office_preview_assets(
        input_dir=input_dir,
        project_no=args.project_no,
        file_path=taskbook_path,
    )
    yssq_preview = build_office_preview_assets(
        input_dir=input_dir,
        project_no=args.project_no,
        file_path=yssq_path,
    )

    payload = {
        "year": args.year,
        "project_no": args.project_no,
        "project_name": args.project_name,
        "taskbook_path": str(taskbook_path),
        "acceptance_application_path": str(yssq_path),
        "acceptance_attachment_dir": str(attachment_dir),
        "candidate_attachment_count": len(candidate_paths),
        "attachment_count": len(parsed_attachments),
        "total_commitments": result.total_commitments,
        "fulfilled_commitments": result.fulfilled_commitments,
        "partial_commitments": result.partial_commitments,
        "missing_commitments": result.missing_commitments,
        "fulfillment_rate": result.fulfillment_rate,
        "warnings": result.warnings,
        "documents": [
            {
                "role": "hts",
                "file_name": taskbook.file_name,
                "display_title": "任务书",
                "file_path": str(taskbook_path),
                "browser_file": to_browser_relative(input_dir, taskbook_path),
                "file_type": taskbook.file_type,
                "viewer_file": "",
                "packet_file": "",
                "preview_file": taskbook_preview.get("preview_file", ""),
                "preview_type": taskbook_preview.get("preview_type", ""),
                "text_excerpt": excerpt_text(taskbook.text),
            },
            {
                "role": "yssq",
                "file_name": yssq_document.file_name,
                "display_title": "验收申请",
                "file_path": str(yssq_path),
                "browser_file": to_browser_relative(input_dir, yssq_path),
                "file_type": yssq_document.file_type,
                "viewer_file": "",
                "packet_file": "",
                "preview_file": yssq_preview.get("preview_file", ""),
                "preview_type": yssq_preview.get("preview_type", ""),
                "text_excerpt": excerpt_text(yssq_document.text),
            },
            *attachment_docs_payload,
        ],
        "rows": [row.model_dump(mode="json") for row in result.rows],
    }

    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    args = parse_args()
    payload = asyncio.run(run(args))
    print(
        json.dumps(
            {
                "project_no": payload["project_no"],
                "candidate_attachment_count": payload["candidate_attachment_count"],
                "attachment_count": payload["attachment_count"],
                "total_commitments": payload["total_commitments"],
                "fulfilled_commitments": payload["fulfilled_commitments"],
                "partial_commitments": payload["partial_commitments"],
                "missing_commitments": payload["missing_commitments"],
                "output": args.output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
