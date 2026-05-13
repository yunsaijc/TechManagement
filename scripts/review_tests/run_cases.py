#!/usr/bin/env python3
"""Run fixed review regression cases against a live review API."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _compact_final(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    bad_checks: list[dict[str, Any]] = []
    for group, items in checks.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") != "passed":
                bad_checks.append(
                    {
                        "group": group,
                        "code": item.get("code"),
                        "status": item.get("status"),
                        "message": item.get("message"),
                    }
                )
    return {
        "review_id": data.get("id") or data.get("review_id"),
        "status": data.get("status"),
        "summary": data.get("summary"),
        "processing_time": data.get("processing_time"),
        "recognized": data.get("recognized"),
        "verification": data.get("verification"),
        "retry": data.get("retry"),
        "bad_checks": bad_checks,
        "suggestions": data.get("suggestions"),
        "db_binding": data.get("db_binding"),
    }


def _submit_case(session: requests.Session, base_url: str, case: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any]]:
    response = session.post(
        f"{base_url.rstrip('/')}/api/v1/review/path",
        params={
            "project_id": case.get("project_id"),
            "doc_type": case.get("doc_type"),
            "file_path": case.get("file_path"),
        },
        timeout=timeout,
    )
    text = response.text
    payload: dict[str, Any] = {}
    try:
        payload = response.json()
    except Exception:
        payload = {"raw_text": text}
    return response.status_code, payload


def _poll_result(
    session: requests.Session,
    base_url: str,
    review_id: str,
    poll_interval: float,
    max_wait: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.time() + max_wait
    latest: dict[str, Any] = {}
    transient_errors: list[str] = []
    while time.time() < deadline:
        try:
            response = session.get(
                f"{base_url.rstrip('/')}/api/v1/review/{review_id}",
                params={"debug": "true"},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            transient_errors.append(str(exc))
            time.sleep(poll_interval)
            continue

        try:
            latest = response.json()
        except Exception:
            latest = {"raw_text": response.text, "status_code": response.status_code}
        if transient_errors:
            latest["poll_transient_errors"] = transient_errors[-5:]

        data = latest.get("data") if isinstance(latest.get("data"), dict) else {}
        status = data.get("status")
        retry = data.get("retry") if isinstance(data.get("retry"), dict) else {}
        if status in {"done", "failed"} and not retry.get("in_progress"):
            return latest
        time.sleep(poll_interval)
    latest["poll_timeout"] = True
    return latest


def _run_one(args: tuple[dict[str, Any], str, float, float, float]) -> dict[str, Any]:
    case, base_url, request_timeout, poll_interval, max_wait = args
    started = time.time()
    session = requests.Session()
    out: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "project_id": case.get("project_id"),
        "doc_type": case.get("doc_type"),
        "source": case.get("source"),
        "file_path": case.get("file_path"),
    }
    try:
        submit_status, submit_payload = _submit_case(session, base_url, case, request_timeout)
        out["submit_status_code"] = submit_status
        out["submit"] = submit_payload
        review_id = ((submit_payload.get("data") or {}) if isinstance(submit_payload, dict) else {}).get("id")
        out["review_id"] = review_id
        if not review_id:
            out["error"] = "submit returned no review_id"
            return out
        final_payload = _poll_result(session, base_url, str(review_id), poll_interval, max_wait, request_timeout)
        out["final"] = _compact_final(final_payload)
        out["raw_final"] = final_payload
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        out["elapsed"] = round(time.time() - started, 2)
        session.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="data/review_tests/cases.jsonl")
    parser.add_argument("--base-url", default="http://192.168.0.200:8887")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--max-wait", type=float, default=900.0)
    args = parser.parse_args()

    cases = _read_jsonl(Path(args.cases))
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case.get("case_id") in wanted]
    else:
        cases = cases[args.offset :]
        if args.limit:
            cases = cases[: args.limit]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir or f"data/review_tests/runs/run_{stamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    worker_args = [(case, args.base_url, args.request_timeout, args.poll_interval, args.max_wait) for case in cases]
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        futures = [executor.submit(_run_one, item) for item in worker_args]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(
                json.dumps(
                    {
                        "done": index,
                        "total": len(futures),
                        "case_id": result.get("case_id"),
                        "summary": (result.get("final") or {}).get("summary"),
                        "error": result.get("error"),
                        "elapsed": result.get("elapsed"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            _write_jsonl(output_dir / "results.partial.jsonl", results)

    _write_jsonl(output_dir / "results.jsonl", results)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "cases": args.cases,
        "count": len(results),
        "concurrency": args.concurrency,
        "errors": sum(1 for item in results if item.get("error")),
        "output": str(output_dir / "results.jsonl"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
