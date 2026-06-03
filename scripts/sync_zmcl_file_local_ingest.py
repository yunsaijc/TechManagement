#!/usr/bin/env python3
"""从 K 盘批量同步 zmcl 提名材料到本地 file_local_ingest。

目标结构：
  /home/tdkx/workspace/tech/data/plagiarism/file_local_ingest/zmcl{year}/{xmtjbh}/{xmtjbh}.doc(x)

数据基准：
  xmsbnew.ps_xmpsxx.nd (年度) + xmsbnew.t_xm_cl.xmtjbh (提名号)

说明：
- 2024 年及以后：默认期望 .docx
- 2023 年及以前：默认期望 .doc
- 若本地已存在同名另一扩展（doc/docx），视为已同步（可用 --strict-ext 强制只认期望扩展）
- 支持断点续跑：会把缺失清单与失败清单写入输出目录

依赖：
- 需要配置 SMB 环境变量（或 .env）：
  REVIEW_SMB_HOST / REVIEW_SMB_SHARE / REVIEW_SMB_USERNAME / REVIEW_SMB_PASSWORD
- 需要配置 DB 环境变量（或 .env）：
  DB_REWARD_HOST / DB_REWARD_PORT / DB_REWARD_USER / DB_REWARD_PASSWORD
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.plagiarism.smb_file_reader import SMBReviewFileReader  # noqa: E402


DEFAULT_LOCAL_ROOT = Path("/home/tdkx/workspace/tech/data/plagiarism/file_local_ingest")
DEFAULT_K_ROOT = r"K:\FJCL\static\rpw"

def _is_remote_missing_error(msg: str) -> bool:
    m = str(msg or "")
    low = m.lower()
    return (
        "no such file or directory" in low
        or "0xc0000034" in low
        or "status_object_name_not_found" in low
        or "ntstatus 0xc0000034" in low
    )


def _is_auth_error(msg: str) -> bool:
    low = str(msg or "").lower()
    return "failed to authenticate" in low or "spnegoerror" in low or "no username or password" in low


def _is_credits_error(msg: str) -> bool:
    low = str(msg or "").lower()
    return "request requires" in low and "credits" in low


def _expected_ext(year: int) -> str:
    return ".docx" if year >= 2024 else ".doc"


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _write_bytes_if_changed(dest: Path, content: bytes) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            if dest.stat().st_size == len(content):
                existing = dest.read_bytes()
                if _md5_bytes(existing) == _md5_bytes(content):
                    return "skipped"
        except OSError:
            pass
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, dest)
    return "written"


@dataclass(frozen=True)
class ExpectedItem:
    year: int
    xmtjbh: str

    @property
    def expected_ext(self) -> str:
        return _expected_ext(self.year)


def _connect_db() -> pymysql.Connection:
    host = os.getenv("DB_REWARD_HOST")
    port = int(os.getenv("DB_REWARD_PORT", "3306"))
    user = os.getenv("DB_REWARD_USER")
    password = os.getenv("DB_REWARD_PASSWORD")
    if not host or not user or not password:
        raise SystemExit("缺少 DB_REWARD_HOST/DB_REWARD_USER/DB_REWARD_PASSWORD（请检查 .env）")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_expected_items(years: Set[int] | None = None) -> Dict[int, Set[str]]:
    """返回 {year: {xmtjbh}}。"""
    conn = _connect_db()
    by_year: Dict[int, Set[str]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT CAST(p.nd AS UNSIGNED) AS nd, c.xmtjbh AS xmtjbh
                FROM xmsbnew.ps_xmpsxx p
                JOIN xmsbnew.t_xm_cl c ON c.xmbh=p.xmbh
                WHERE p.nd REGEXP '^[0-9]{4}$'
                  AND c.xmtjbh IS NOT NULL
                  AND TRIM(c.xmtjbh) <> ''
                """
            )
            for row in cur.fetchall():
                try:
                    y = int(row["nd"])
                except Exception:
                    continue
                if years is not None and y not in years:
                    continue
                x = str(row.get("xmtjbh") or "").strip()
                if not x:
                    continue
                by_year.setdefault(y, set()).add(x)
    finally:
        conn.close()
    return by_year


def compute_missing(
    by_year: Dict[int, Set[str]],
    local_root: Path,
    strict_ext: bool,
) -> List[ExpectedItem]:
    missing: List[ExpectedItem] = []
    for y in sorted(by_year.keys()):
        exp = _expected_ext(y)
        for x in sorted(by_year[y]):
            base = local_root / f"zmcl{y}" / x / f"{x}{exp}"
            if base.exists():
                continue
            if not strict_ext:
                alt = local_root / f"zmcl{y}" / x / (f"{x}.docx" if exp == ".doc" else f"{x}.doc")
                if alt.exists():
                    continue
            missing.append(ExpectedItem(year=y, xmtjbh=x))
    return missing


def build_k_path(k_root: str, year: int, xmtjbh: str, ext: str) -> str:
    return fr"{k_root}\zmcl{year}\{xmtjbh}\{xmtjbh}{ext}"


def parse_years(raw: str | None) -> Set[int] | None:
    if not raw:
        return None
    out: Set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a.strip())
            b = int(b.strip())
            for y in range(min(a, b), max(a, b) + 1):
                out.add(y)
        else:
            out.add(int(part))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 K 盘 zmcl 材料到本地 file_local_ingest")
    parser.add_argument("--local-root", default=str(DEFAULT_LOCAL_ROOT))
    parser.add_argument("--k-root", default=DEFAULT_K_ROOT)
    parser.add_argument("--years", default=None, help="例如: 2012 或 2007-2025 或 2012,2024-2025")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--strict-ext", action="store_true", help="只认期望扩展（<=2023 doc, >=2024 docx）")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 个缺失项（用于试跑）")
    parser.add_argument("--dry-run", action="store_true", help="只统计缺失，不下载")
    parser.add_argument("--out-dir", default=str(Path.cwd() / "tmp_sync_zmcl"), help="输出缺失/失败清单目录")
    parser.add_argument("--retry-failed", default=None, help="只重试某次 failed.json（路径）中的可重试项")

    args = parser.parse_args()
    load_dotenv("/home/tdkx/ljh/Tech/.env")

    local_root = Path(args.local_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing: List[ExpectedItem] = []
    if args.retry_failed:
        raw = json.loads(Path(args.retry_failed).read_text(encoding="utf-8"))
        for item in raw:
            try:
                y = int(item.get("year"))
                x = str(item.get("xmtjbh") or "").strip()
            except Exception:
                continue
            if not x:
                continue
            missing.append(ExpectedItem(year=y, xmtjbh=x))
        print(f"retry_failed_loaded={len(missing)} from {args.retry_failed}")
    else:
        years = parse_years(args.years)
        by_year = fetch_expected_items(years=years)
        all_years = sorted(by_year.keys())
        print(f"year_range={all_years[0]}..{all_years[-1]}" if all_years else "year_range=EMPTY")

        missing = compute_missing(by_year, local_root=local_root, strict_ext=bool(args.strict_ext))
        if args.limit:
            missing = missing[: int(args.limit)]

        missing_json = out_dir / "missing.json"
        missing_json.write_text(
            json.dumps(
                [{"year": m.year, "xmtjbh": m.year and m.xmtjbh, "ext": m.expected_ext} for m in missing],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"missing_count={len(missing)} (saved: {missing_json})")
        if args.dry_run:
            return 0

    reader = SMBReviewFileReader()
    sem = __import__("asyncio").Semaphore(max(1, int(args.concurrency)))

    stats = {"written": 0, "skipped": 0, "failed": 0}
    failed: List[dict] = []
    missing_remote: List[dict] = []
    retryable_failed: List[dict] = []
    started = time.time()

    async def one(item: ExpectedItem) -> None:
        nonlocal stats, failed
        async with sem:
            ext = item.expected_ext
            k_path = build_k_path(args.k_root, item.year, item.xmtjbh, ext)
            dest = local_root / f"zmcl{item.year}" / item.xmtjbh / f"{item.xmtjbh}{ext}"
            try:
                content = await __import__("asyncio").to_thread(reader.read_bytes, k_path)
                res = await __import__("asyncio").to_thread(_write_bytes_if_changed, dest, content)
                stats[res] += 1
            except Exception as e:
                stats["failed"] += 1
                err = str(e)
                row = {"year": item.year, "xmtjbh": item.xmtjbh, "path": k_path, "error": err}
                failed.append(row)
                if _is_remote_missing_error(err):
                    missing_remote.append(row)
                else:
                    retryable_failed.append(row)

    async def runner():
        tasks = [__import__("asyncio").create_task(one(item)) for item in missing]
        for i, fut in enumerate(__import__("asyncio").as_completed(tasks), 1):
            await fut
            if i % 200 == 0 or i == len(tasks):
                elapsed = round(time.time() - started, 2)
                print(f"[progress] {i}/{len(missing)} stats={stats} elapsed={elapsed}s")

    __import__("asyncio").run(runner())

    failed_json = out_dir / "failed.json"
    failed_json.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "failed_remote_missing.json").write_text(
        json.dumps(missing_remote, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "failed_retryable.json").write_text(
        json.dumps(retryable_failed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"done stats={stats} failed_count={len(failed)} (saved: {failed_json})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

