#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.accept.service import AcceptanceService


async def run_case(service: AcceptanceService, case: dict[str, object]) -> dict[str, object]:
    taskbook_path = ROOT / str(case["taskbook_path"])
    yssq_path = ROOT / str(case["yssq_path"])
    attachment_dir = ROOT / str(case["attachment_dir"])
    year = str(case["year"])
    service.parser.cache_dir = ROOT / "debug_accept" / ".accept_parse_cache" / year

    taskbook = await service.parser.parse_bytes(
        file_data=taskbook_path.read_bytes(),
        file_type=taskbook_path.suffix.lower().lstrip("."),
        file_name=taskbook_path.name,
    )
    yssq = await service.parser.parse_bytes(
        file_data=yssq_path.read_bytes(),
        file_type=yssq_path.suffix.lower().lstrip("."),
        file_name=yssq_path.name,
    )
    attachments = [yssq]
    for file_path in sorted(attachment_dir.iterdir()):
        if not file_path.is_file():
            continue
        parsed = await service.parser.parse_bytes(
            file_data=file_path.read_bytes(),
            file_type=file_path.suffix.lower().lstrip("."),
            file_name=file_path.name,
        )
        if service.evidence_extractor.should_skip_attachment(parsed):
            continue
        attachments.append(parsed)

    result = service.check_from_documents(
        project_id=str(case["project_no"]),
        taskbook=taskbook,
        attachments=attachments,
    )
    expected = case.get("expected", {})
    success = (
        result.fulfilled_commitments == int(expected.get("fulfilled_commitments", -1))
        and result.partial_commitments == int(expected.get("partial_commitments", -1))
        and result.missing_commitments == int(expected.get("missing_commitments", -1))
    )
    return {
        "project_no": case["project_no"],
        "fulfilled_commitments": result.fulfilled_commitments,
        "partial_commitments": result.partial_commitments,
        "missing_commitments": result.missing_commitments,
        "fulfillment_rate": result.fulfillment_rate,
        "success": success,
    }


async def main() -> int:
    cases_path = ROOT / "debug_accept" / "regression_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    service = AcceptanceService()
    reports = []
    for case in cases:
        try:
            reports.append(await run_case(service, case))
        except ModuleNotFoundError as exc:
            print(f"{case['project_no']}: skipped missing dependency {exc.name}")
            reports.append(
                {
                    "project_no": case["project_no"],
                    "fulfilled_commitments": -1,
                    "partial_commitments": -1,
                    "missing_commitments": -1,
                    "fulfillment_rate": 0.0,
                    "success": False,
                }
            )
        except Exception as exc:
            print(f"{case['project_no']}: failed {exc}")
            reports.append(
                {
                    "project_no": case["project_no"],
                    "fulfilled_commitments": -1,
                    "partial_commitments": -1,
                    "missing_commitments": -1,
                    "fulfillment_rate": 0.0,
                    "success": False,
                }
            )
    failed = [item for item in reports if not item["success"]]
    for item in reports:
        print(
            f"{item['project_no']}: fulfilled={item['fulfilled_commitments']} "
            f"partial={item['partial_commitments']} missing={item['missing_commitments']} "
            f"rate={item['fulfillment_rate']:.2f} success={item['success']}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
