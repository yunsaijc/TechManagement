#!/usr/bin/env python3
"""Batch convert legacy .doc files to .docx for zmcl years.

Default behavior:
- Scan /home/tdkx/workspace/tech/data/plagiarism/file_local_ingest
- Include folders named zmclYYYY where YYYY <= 2023
- Convert every .doc (excluding .docx) to .docx in-place
- Skip when target .docx already exists (unless --overwrite)
- Print live progress and final summary
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_ROOT = Path("/home/tdkx/workspace/tech/data/plagiarism/file_local_ingest")
YEAR_DIR_PATTERN = re.compile(r"^zmcl(\d{4})$")


@dataclass
class Stats:
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def discover_year_dirs(root: Path, max_year: int) -> list[Path]:
    year_dirs: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        match = YEAR_DIR_PATTERN.match(child.name)
        if not match:
            continue
        year = int(match.group(1))
        if year <= max_year:
            year_dirs.append(child)
    return year_dirs


def discover_doc_files(year_dirs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for year_dir in year_dirs:
        for p in year_dir.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() != ".doc":
                continue
            files.append(p)
    return sorted(files)


def build_soffice_cmd(soffice_bin: str, src_doc: Path) -> list[str]:
    return [
        soffice_bin,
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--nodefault",
        "--nofirststartwizard",
        "--convert-to",
        "docx",
        "--outdir",
        str(src_doc.parent),
        str(src_doc),
    ]


def _build_soffice_env(profile_root: Path) -> tuple[dict[str, str], str]:
    env = os.environ.copy()
    home_dir = profile_root / "home"
    xdg_config = home_dir / ".config"
    xdg_cache = home_dir / ".cache"
    xdg_runtime = home_dir / ".run"
    user_installation = profile_root / "user-profile"

    for p in (home_dir, xdg_config, xdg_cache, xdg_runtime, user_installation):
        p.mkdir(parents=True, exist_ok=True)

    env["HOME"] = str(home_dir)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["XDG_RUNTIME_DIR"] = str(xdg_runtime)
    return env, user_installation.resolve().as_uri()


def convert_one(
    src_doc: Path,
    soffice_bin: str,
    timeout_sec: int,
    timeout_retries: int,
    retry_timeout_multiplier: float,
    overwrite: bool,
) -> tuple[str, str]:
    target_docx = src_doc.with_suffix(".docx")
    if target_docx.exists() and not overwrite:
        return "skipped", "target exists"

    cmd = build_soffice_cmd(soffice_bin, src_doc)
    attempts = max(1, timeout_retries + 1)
    current_timeout = max(1, int(timeout_sec))
    timeout_reasons: list[str] = []

    for attempt in range(1, attempts + 1):
        with tempfile.TemporaryDirectory(prefix="lo_batch_convert_") as tmp_dir:
            env, user_installation_uri = _build_soffice_env(Path(tmp_dir))
            cmd_with_profile = [
                soffice_bin,
                f"-env:UserInstallation={user_installation_uri}",
                *cmd[1:],
            ]
        try:
            proc = subprocess.run(
                cmd_with_profile,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=current_timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            timeout_reasons.append(f"attempt{attempt}=timeout({current_timeout}s)")
            current_timeout = max(
                current_timeout + 1,
                int(current_timeout * retry_timeout_multiplier),
            )
            continue
        except Exception as exc:  # noqa: BLE001
            return "failed", f"exception: {exc}"

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
            return "failed", f"returncode={proc.returncode}, msg={err[:240]}"

        if not target_docx.exists():
            err = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
            return "failed", f"no target docx created, msg={err[:240]}"

        # LibreOffice occasionally leaves zero-byte output for broken inputs.
        if target_docx.stat().st_size <= 0:
            return "failed", "target docx size=0"

        if timeout_reasons:
            return "success", f"recovered_after_retry: {'; '.join(timeout_reasons)}"
        return "success", ""

    return "failed", "; ".join(timeout_reasons)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch convert zmcl legacy .doc to .docx with progress."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"Root directory (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--max-year",
        type=int,
        default=2023,
        help="Process zmcl folders up to this year (default: 2023)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .docx files",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=120,
        help="Timeout in seconds per document conversion (default: 120)",
    )
    parser.add_argument(
        "--timeout-retries",
        type=int,
        default=1,
        help="Retry count when timeout happens (default: 1)",
    )
    parser.add_argument(
        "--retry-timeout-multiplier",
        type=float,
        default=2.0,
        help="Timeout multiplier applied for each timeout retry (default: 2.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for conversion (default: 1, sequential)",
    )
    parser.add_argument(
        "--fail-log",
        type=Path,
        default=Path("doc_to_docx_failures.log"),
        help="Failure log file path (default: ./doc_to_docx_failures.log)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] root does not exist or is not directory: {root}")
        return 2

    soffice_bin = shutil.which("libreoffice") or shutil.which("soffice")
    if not soffice_bin:
        print("[ERROR] libreoffice/soffice not found in PATH")
        return 2

    year_dirs = discover_year_dirs(root, args.max_year)
    if not year_dirs:
        print(f"[ERROR] no zmclYYYY directories found under: {root}")
        return 2

    doc_files = discover_doc_files(year_dirs)
    stats = Stats(total=len(doc_files))

    print(f"[INFO] soffice bin: {soffice_bin}")
    print(f"[INFO] root: {root}")
    print(f"[INFO] max_year: {args.max_year}")
    print(f"[INFO] year_dirs: {len(year_dirs)}")
    print(f"[INFO] total .doc files: {stats.total}")
    print(f"[INFO] workers: {max(1, int(args.workers))}")
    print("-" * 100)

    if stats.total == 0:
        print("[DONE] no .doc files to convert.")
        return 0

    start_ts = time.time()
    failures: list[str] = []

    worker_count = max(1, int(args.workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_doc = {
            executor.submit(
                convert_one,
                src_doc=doc_path,
                soffice_bin=soffice_bin,
                timeout_sec=args.timeout_sec,
                timeout_retries=args.timeout_retries,
                retry_timeout_multiplier=args.retry_timeout_multiplier,
                overwrite=args.overwrite,
            ): doc_path
            for doc_path in doc_files
        }

        for future in concurrent.futures.as_completed(future_to_doc):
            doc_path = future_to_doc[future]
            try:
                status, msg = future.result()
            except Exception as exc:  # noqa: BLE001
                status, msg = "failed", f"exception: {exc}"

            stats.processed += 1
            if status == "success":
                stats.success += 1
            elif status == "skipped":
                stats.skipped += 1
            else:
                stats.failed += 1
                failures.append(f"{doc_path}\t{msg}")

            elapsed = time.time() - start_ts
            speed = stats.processed / elapsed if elapsed > 0 else 0.0
            remain = stats.total - stats.processed
            eta = remain / speed if speed > 0 else 0.0
            print(
                f"[{stats.processed:>5}/{stats.total}] {status.upper():<7} "
                f"S={stats.success} F={stats.failed} K={stats.skipped} "
                f"ETA={format_seconds(eta)} :: {doc_path}"
            )
            if msg and status != "success":
                print(f"         reason: {msg}")

    total_elapsed = time.time() - start_ts
    print("-" * 100)
    print(
        "[SUMMARY] "
        f"processed={stats.processed}, success={stats.success}, failed={stats.failed}, "
        f"skipped={stats.skipped}, elapsed={format_seconds(total_elapsed)}"
    )

    if failures:
        fail_log_path = args.fail_log.resolve()
        fail_log_path.write_text("\n".join(failures) + "\n", encoding="utf-8")
        print(f"[SUMMARY] failure log saved: {fail_log_path}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
