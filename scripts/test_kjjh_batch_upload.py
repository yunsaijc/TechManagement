#!/usr/bin/env python3
"""Batch test uploaded files against the KJJH corpus."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.plagiarism.batch_report_builder import BatchPlagiarismReportBuilder  # noqa: E402
from src.services.plagiarism.config import get_section_config  # noqa: E402
from src.services.plagiarism.kjjh_checker import run_kjjh_plagiarism  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("/home/tdkx/ljh/Tech/debug_plagiarism/results")
DEFAULT_INPUTS: list[tuple[str, str]] = [
    ("/home/tdkx/ljh/Tech/data/高水平人才团队建设专项", "gsprctdjszx"),
    ("/home/tdkx/ljh/Tech/data/科技研发平台专项", "kjyfptzx"),
    ("/home/tdkx/ljh/Tech/data/民生保障与社会安全协同创新专项(卫生健康)", "msbzyshaqxtcxzxwsjk"),
    ("/home/tdkx/ljh/Tech/data/生物医药产业创新专项(中医药定量化研究创新)", "swyycycxzxzyydlhyjcx"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch test uploaded docs against the KJJH corpus")
    parser.add_argument(
        "--input-dir",
        action="append",
        dest="input_dirs",
        default=[],
        help="Directory to scan. May be passed multiple times. Defaults to the 4 configured专项目录.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for batch json/html outputs",
    )
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--threshold-high", type=float, default=0.8)
    parser.add_argument("--threshold-medium", type=float, default=0.5)
    parser.add_argument("--limit-per-dir", type=int, default=0, help="Only process the first N docs in each directory")
    parser.add_argument("--run-name", default=None, help="Optional sub-directory name under output-dir")
    parser.add_argument("--start-index", type=int, default=1, help="1-based file index to start processing from")
    parser.add_argument("--end-index", type=int, default=0, help="1-based file index to stop processing at, 0 means all")
    parser.add_argument(
        "--skip-existing-successes",
        action="store_true",
        help="Reuse existing per-file Mammoth reports under the same run-dir instead of rerunning those files",
    )
    parser.add_argument(
        "--doc-type-override",
        default=None,
        help="Force all files to use the same doc_type instead of directory-based mapping",
    )
    return parser.parse_args()


def _normalize_path(path: str) -> str:
    return str(Path(path).resolve())


def _get_input_dir_map(args: argparse.Namespace) -> dict[str, str]:
    if args.input_dirs:
        if args.doc_type_override:
            return {_normalize_path(path): args.doc_type_override for path in args.input_dirs}
        return {_normalize_path(path): "default" for path in args.input_dirs}
    return {_normalize_path(path): doc_type for path, doc_type in DEFAULT_INPUTS}


def _scan_files(root: Path, *, limit_per_dir: int) -> list[Path]:
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".doc", ".docx"}
    ]
    if limit_per_dir > 0:
        return files[:limit_per_dir]
    return files


def _build_run_dir(output_dir: Path, run_name: str | None) -> Path:
    if run_name:
        return output_dir / run_name
    return output_dir / f"kjjh_upload_batch_{time.strftime('%Y%m%d_%H%M%S')}"


def _safe_id(file_path: Path) -> str:
    digest = hashlib.md5(str(file_path).encode("utf-8")).hexdigest()[:10]
    return f"{file_path.stem}_{digest}"


def _build_repro_command(args: argparse.Namespace) -> str:
    cmd = [
        "python",
        "scripts/test_kjjh_batch_upload.py",
        "--output-dir",
        args.output_dir,
        "--threshold",
        str(args.threshold),
        "--threshold-high",
        str(args.threshold_high),
        "--threshold-medium",
        str(args.threshold_medium),
    ]
    if args.limit_per_dir:
        cmd.extend(["--limit-per-dir", str(args.limit_per_dir)])
    if args.run_name:
        cmd.extend(["--run-name", args.run_name])
    if args.start_index != 1:
        cmd.extend(["--start-index", str(args.start_index)])
    if args.end_index:
        cmd.extend(["--end-index", str(args.end_index)])
    if args.skip_existing_successes:
        cmd.append("--skip-existing-successes")
    if args.doc_type_override:
        cmd.extend(["--doc-type-override", args.doc_type_override])
    for item in args.input_dirs:
        cmd.extend(["--input-dir", item])
    return " ".join(shlex.quote(part) for part in cmd)


async def _run_single(
    *,
    index: int,
    total: int,
    file_path: Path,
    doc_type: str,
    run_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    file_id = _safe_id(file_path)
    report_dir = run_dir / "reports" / f"{index:03d}_{file_id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    item_started = time.time()
    print(f"[{index}/{total}] {file_path}")

    try:
        payload = await run_kjjh_plagiarism(
            word_path=str(file_path),
            threshold=args.threshold,
            threshold_high=args.threshold_high,
            threshold_medium=args.threshold_medium,
            doc_type=doc_type,
            section_config=get_section_config(doc_type),
            debug=True,
            include_report=True,
            debug_output_dir=report_dir,
        )
        result_data = payload["result"]
        record = {
            "status": "success",
            "elapsed_seconds": round(time.time() - item_started, 3),
            "file_path": str(file_path),
            "source_dir": str(file_path.parent),
            "doc_type": doc_type,
            "doc_type_name": get_section_config(doc_type).get("name"),
            "data": payload,
        }
        report_item = {
            "project": {
                "id": file_id,
                "xmmc": file_path.name,
                "guide_name": file_path.parent.name,
                "file_path": str(file_path),
                "doc_type": doc_type,
            },
            "result": result_data,
            "debug": {
                "report_html_path": payload.get("debug_report_path"),
            },
        }
        print(
            "  -> success:"
            f" rate={result_data.get('effective_duplicate_rate', 0):.4f}"
            f", chars={result_data.get('effective_duplicate_chars', 0)}"
        )
        return {"record": record, "report_item": report_item, "failed_item": None}
    except Exception as exc:  # noqa: BLE001
        failed = {
            "id": file_id,
            "xmmc": file_path.name,
            "guide_name": file_path.parent.name,
            "file_path": str(file_path),
            "doc_type": doc_type,
            "error": str(exc),
        }
        record = {
            "status": "error",
            "elapsed_seconds": round(time.time() - item_started, 3),
            "file_path": str(file_path),
            "source_dir": str(file_path.parent),
            "doc_type": doc_type,
            "error": str(exc),
        }
        print(f"  -> failed: {exc}")
        return {"record": record, "report_item": None, "failed_item": failed}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_report_metric(html_text: str, label: str, *, percent: bool = False) -> float | int:
    pattern = re.escape(f'<div class="stat-label">{label}</div><div class="stat-value">') + r'([^<]+)</div>'
    match = re.search(pattern, html_text)
    if not match:
        return 0.0 if percent else 0
    value = match.group(1).replace(",", "").replace("%", "").strip()
    if percent:
        try:
            return float(value) / 100.0
        except ValueError:
            return 0.0
    try:
        return int(float(value))
    except ValueError:
        return 0


def _restore_success_from_report(
    *,
    index: int,
    file_path: Path,
    doc_type: str,
    report_path: Path,
) -> dict[str, Any]:
    html_text = report_path.read_text(encoding="utf-8")
    match_ids = list(
        dict.fromkeys(
            match_id
            for match_id in re.findall(r'data-match-id="([^"]+)"', html_text)
            if match_id and "$" not in match_id and "{" not in match_id and "}" not in match_id
        )
    )
    effective_duplicate_chars = int(_parse_report_metric(html_text, "有效重复字数"))
    effective_duplicate_rate = float(_parse_report_metric(html_text, "有效重复率", percent=True))
    duplicate_chars = int(_parse_report_metric(html_text, "重复字数"))
    duplicate_rate = float(_parse_report_metric(html_text, "总重复率", percent=True))
    total_chars = int(_parse_report_metric(html_text, "总字数"))

    file_id = _safe_id(file_path)
    result_data = {
        "match_groups": [{"restored_match_id": match_id} for match_id in match_ids],
        "effective_duplicate_chars": effective_duplicate_chars,
        "effective_duplicate_rate": effective_duplicate_rate,
        "duplicate_chars": duplicate_chars,
        "duplicate_rate": duplicate_rate,
        "total_chars": total_chars,
    }
    record = {
        "status": "success",
        "elapsed_seconds": None,
        "file_path": str(file_path),
        "source_dir": str(file_path.parent),
        "doc_type": doc_type,
        "restored_from_existing_report": True,
        "data": {
            "result": result_data,
            "debug_report_path": str(report_path),
        },
    }
    report_item = {
        "project": {
            "id": file_id,
            "xmmc": file_path.name,
            "guide_name": file_path.parent.name,
            "file_path": str(file_path),
            "doc_type": doc_type,
        },
        "result": result_data,
        "debug": {
            "report_html_path": str(report_path),
        },
    }
    print(
        f"[{index}] reuse existing report: {file_path.name}"
        f" rate={effective_duplicate_rate:.4f}, chars={effective_duplicate_chars}"
    )
    return {"record": record, "report_item": report_item, "failed_item": None}


def _load_existing_success_reports(run_dir: Path) -> dict[int, Path]:
    existing: dict[int, Path] = {}
    reports_root = run_dir / "reports"
    if not reports_root.exists():
        return existing
    for report_path in sorted(reports_root.glob("*/plagiarism_report_mammoth.html")):
        folder_name = report_path.parent.name
        prefix = folder_name.split("_", 1)[0]
        if prefix.isdigit():
            existing[int(prefix)] = report_path
    return existing


def _build_progress_payload(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    run_dir: Path,
    batch_started_at: int,
    total: int,
    scan_summary: list[dict[str, Any]],
    records: list[dict[str, Any]],
    report_results: list[dict[str, Any]],
    failed_projects: list[dict[str, Any]],
    batch_report_path: str | None = None,
) -> dict[str, Any]:
    return {
        "meta": {
            "started_at": batch_started_at,
            "threshold": args.threshold,
            "threshold_high": args.threshold_high,
            "threshold_medium": args.threshold_medium,
            "limit_per_dir": args.limit_per_dir,
            "start_index": args.start_index,
            "end_index": args.end_index,
            "skip_existing_successes": args.skip_existing_successes,
            "output_dir": str(output_dir),
            "run_dir": str(run_dir),
            "batch_report_path": batch_report_path,
            "success_count": len(report_results),
            "failed_count": len(failed_projects),
            "total_files": total,
            "processed_count": len(records),
            "scan_summary": scan_summary,
        },
        "records": records,
        "report_results": report_results,
        "failed_projects": failed_projects,
    }


async def _run_batch(args: argparse.Namespace) -> dict[str, Any]:
    input_dir_map = _get_input_dir_map(args)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = _build_run_dir(output_dir, args.run_name).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    batch_started_at = int(time.time())

    files_to_process: list[tuple[Path, str]] = []
    scan_summary: list[dict[str, Any]] = []
    for directory, doc_type in input_dir_map.items():
        root = Path(directory)
        if not root.exists():
            scan_summary.append(
                {
                    "directory": directory,
                    "doc_type": doc_type,
                    "exists": False,
                    "file_count": 0,
                }
            )
            continue
        files = _scan_files(root, limit_per_dir=max(args.limit_per_dir, 0))
        files_to_process.extend((file_path, doc_type) for file_path in files)
        scan_summary.append(
            {
                "directory": directory,
                "doc_type": doc_type,
                "exists": True,
                "file_count": len(files),
            }
        )

    if not files_to_process:
        raise ValueError("未在输入目录中找到可测试的 doc/docx 文件")

    records: list[dict[str, Any]] = []
    report_results: list[dict[str, Any]] = []
    failed_projects: list[dict[str, Any]] = []

    total = len(files_to_process)
    if args.start_index < 1 or args.start_index > total:
        raise ValueError(f"--start-index 超出范围: 1..{total}")
    end_index = args.end_index or total
    if end_index < args.start_index or end_index > total:
        raise ValueError(f"--end-index 超出范围: {args.start_index}..{total}")

    progress_path = run_dir / "progress.json"
    existing_successes = _load_existing_success_reports(run_dir) if args.skip_existing_successes else {}

    for index, (file_path, doc_type) in enumerate(files_to_process, start=1):
        if index < args.start_index or index > end_index:
            continue
        if index in existing_successes:
            outcome = _restore_success_from_report(
                index=index,
                file_path=file_path,
                doc_type=doc_type,
                report_path=existing_successes[index],
            )
        else:
            outcome = await _run_single(
                index=index,
                total=total,
                file_path=file_path,
                doc_type=doc_type,
                run_dir=run_dir,
                args=args,
            )
        records.append(outcome["record"])
        if outcome["report_item"]:
            report_results.append(outcome["report_item"])
        if outcome["failed_item"]:
            failed_projects.append(outcome["failed_item"])
        _write_json(
            progress_path,
            _build_progress_payload(
                args=args,
                output_dir=output_dir,
                run_dir=run_dir,
                batch_started_at=batch_started_at,
                total=total,
                scan_summary=scan_summary,
                records=records,
                report_results=report_results,
                failed_projects=failed_projects,
            ),
        )

    batch_report_path = None
    if report_results or failed_projects:
        batch_report_path = str(
            BatchPlagiarismReportBuilder().build(
                results=report_results,
                failed_projects=failed_projects,
                output_html_path=run_dir / "plagiarism_batch_report.html",
            )
        )

    payload = _build_progress_payload(
        args=args,
        output_dir=output_dir,
        run_dir=run_dir,
        batch_started_at=batch_started_at,
        total=total,
        scan_summary=scan_summary,
        records=records,
        report_results=report_results,
        failed_projects=failed_projects,
        batch_report_path=batch_report_path,
    )
    return payload


def main() -> None:
    args = parse_args()
    started = time.time()
    payload = asyncio.run(_run_batch(args))
    payload["meta"]["finished_at"] = int(time.time())
    payload["meta"]["elapsed_seconds"] = round(time.time() - started, 3)

    run_dir = Path(payload["meta"]["run_dir"])
    result_path = run_dir / "batch_result.json"
    progress_path = run_dir / "progress.json"
    command_path = run_dir / "rerun.sh"
    _write_json(result_path, payload)
    _write_json(progress_path, payload)
    command_path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n" + _build_repro_command(args) + "\n",
        encoding="utf-8",
    )

    print("\nBatch test finished")
    print(f"- success: {payload['meta']['success_count']}")
    print(f"- failed:  {payload['meta']['failed_count']}")
    print(f"- result:  {result_path}")
    print(f"- report:  {payload['meta']['batch_report_path']}")
    print(f"- rerun:   {command_path}")


if __name__ == "__main__":
    main()
