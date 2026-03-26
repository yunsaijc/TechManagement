#!/usr/bin/env python3
"""Extract parsed text and structured schema from PDF/DOCX using current project code.

Usage:
  python scripts/extract_doc_content.py tests/申报书/a.docx
  python scripts/extract_doc_content.py tests/申报书/a.docx tests/任务书/b.pdf --save-json out.json
  python scripts/extract_doc_content.py a.docx --raw-chars 2000 --no-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Ensure "src" imports work when running this script directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.file_handler.factory import detect_file_type, get_parser
from src.services.perfcheck.parser import PerfCheckParser

SUPPORTED_TYPES = {"pdf", "docx"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract concrete content from PDF/DOCX with current parser implementation."
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Input file paths (.pdf/.docx).",
    )
    parser.add_argument(
        "--raw-chars",
        type=int,
        default=1600,
        help="How many raw parsed characters to print. Default: 1600",
    )
    parser.add_argument(
        "--save-json",
        default="",
        help="Optional path to save full extraction results as JSON.",
    )
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help="Only parse raw text; do not run PerfCheck schema extraction.",
    )
    return parser.parse_args()


def _shorten(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _schema_preview(schema_dict: dict[str, Any]) -> dict[str, Any]:
    research = schema_dict.get("research_contents") or []
    metrics = schema_dict.get("performance_targets") or []
    budget = schema_dict.get("budget") or {}
    basic = schema_dict.get("basic_info") or {}
    units = schema_dict.get("units_budget") or []

    return {
        "project_name": schema_dict.get("project_name", ""),
        "research_count": len(research),
        "metric_count": len(metrics),
        "budget_total": budget.get("total", 0),
        "budget_item_count": len(budget.get("items") or []),
        "unit_budget_count": len(units),
        "undertaking_unit": basic.get("undertaking_unit", ""),
    }


async def _extract_one(file_path: Path, raw_chars: int, no_schema: bool) -> dict[str, Any]:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    ftype = detect_file_type(file_path.name)
    if ftype not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported file type: {file_path.name} (detected={ftype})")

    data = file_path.read_bytes()

    parser = get_parser(ftype)
    parse_result = await parser.parse(data)
    raw_text = parse_result.content.to_text()

    result: dict[str, Any] = {
        "file": str(file_path),
        "file_type": ftype,
        "raw_text_length": len(raw_text),
        "raw_text_preview": _shorten(raw_text, raw_chars),
        "schema": None,
        "schema_preview": None,
    }

    if not no_schema:
        perf_parser = PerfCheckParser()
        schema = await perf_parser.extract_schema_from_text(raw_text, source_file_type=ftype)
        schema_dict = schema.model_dump()
        result["schema"] = schema_dict
        result["schema_preview"] = _schema_preview(schema_dict)

    return result


async def _run(args: argparse.Namespace) -> int:
    all_results: list[dict[str, Any]] = []

    for p in args.files:
        file_path = Path(p).expanduser().resolve()
        print(f"\n=== Extracting: {file_path} ===")
        try:
            item = await _extract_one(file_path, args.raw_chars, args.no_schema)
            all_results.append(item)

            print(f"Type: {item['file_type']}")
            print(f"Raw text length: {item['raw_text_length']}")
            print("\n[Raw text preview]")
            print(item["raw_text_preview"])

            if not args.no_schema and item["schema_preview"] is not None:
                print("\n[Schema preview]")
                print(json.dumps(item["schema_preview"], ensure_ascii=False, indent=2))

                print("\n[Research contents]")
                for rc in (item["schema"].get("research_contents") or []):
                    rid = rc.get("id", "")
                    txt = rc.get("text", "")
                    print(f"- {rid}: {txt}")

                print("\n[Performance targets]")
                for pt in (item["schema"].get("performance_targets") or []):
                    pid = pt.get("id", "")
                    ptype = pt.get("type", "")
                    val = pt.get("value", 0)
                    unit = pt.get("unit", "")
                    src = pt.get("source", "")
                    print(f"- {pid} | {ptype} | {val}{unit} | source={src}")

                budget = item["schema"].get("budget") or {}
                print("\n[Budget]")
                print(f"- total: {budget.get('total', 0)}")
                for bi in (budget.get("items") or []):
                    print(f"- item: {bi.get('type', '')} = {bi.get('amount', 0)}")

        except Exception as exc:
            print(f"ERROR: {exc}")

    if args.save_json:
        out_path = Path(args.save_json).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved JSON to: {out_path}")

    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
