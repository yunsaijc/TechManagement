#!/usr/bin/env python3
"""Generate draft ground-truth targets for fixed review test cases.

This file deliberately does not call OCR/LLM. It only records database targets
and special-case hints, so later evaluation can compare system output against a
stable input set.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.review.reward_review_service import RewardReviewService


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSON") from exc
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _build_gt_row(service: RewardReviewService, case: dict[str, Any]) -> dict[str, Any]:
    context = service.build_context(
        project_id=str(case.get("project_id") or ""),
        file_path=str(case.get("file_path") or ""),
        doc_type=str(case.get("doc_type") or ""),
    )
    errors = list(context.get("errors") or [])
    target_values = dict(context.get("target_values") or {})
    special_hint = case.get("gt_hint") if isinstance(case.get("gt_hint"), dict) else None

    review_required = bool(special_hint) or bool(errors) or not target_values
    gt_source = "special_case_plus_db" if special_hint and target_values else "special_case_description" if special_hint else "db"
    if errors or not target_values:
        gt_source = "needs_investigation"

    return {
        "case_id": case.get("case_id"),
        "project_id": case.get("project_id"),
        "doc_type": case.get("doc_type"),
        "source_case": case.get("source"),
        "gt_source": gt_source,
        "review_required": review_required,
        "expected_targets": target_values,
        "special_hint": special_hint,
        "db_binding": {
            "matched_attachment": bool(context.get("attachment_record")),
            "attachment_title": (context.get("attachment_record") or {}).get("FJMC"),
            "attachment_lx": (context.get("attachment_record") or {}).get("LX"),
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="data/review_tests/cases.jsonl")
    parser.add_argument("--output", default="data/review_tests/expected_draft.jsonl")
    parser.add_argument("--manifest", default="data/review_tests/gt_manifest.json")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest)

    cases = _read_jsonl(cases_path)
    service = RewardReviewService()
    rows = [_build_gt_row(service, case) for case in cases]
    _write_jsonl(output_path, rows)

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases": str(cases_path),
        "output": str(output_path),
        "counts": {
            "total": len(rows),
            "review_required": sum(1 for row in rows if row.get("review_required")),
            "with_errors": sum(1 for row in rows if row.get("errors")),
            "by_gt_source": dict(Counter(str(row.get("gt_source") or "") for row in rows)),
            "by_doc_type": dict(Counter(str(row.get("doc_type") or "") for row in rows)),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
