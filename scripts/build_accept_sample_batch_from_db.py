#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pymssql


def _run_remote_helper(action: str, host: str, user: str, password: str, *args: str, timeout: int = 600) -> str:
    helper = PROJECT_ROOT / "scripts" / "remote_accept_helper.py"
    cmd = ["python3", str(helper), action, "--host", host, "--user", user, "--password", password]
    if action == "ssh":
        cmd.extend(["--timeout", str(timeout), args[0]])
    else:
        cmd.extend(["--timeout", str(timeout), args[0], args[1]])
    completed = subprocess.run(cmd, check=True, text=True, capture_output=True, timeout=timeout + 20)
    return completed.stdout


def _run_ssh(host: str, user: str, password: str, remote_cmd: str, timeout: int = 120) -> str:
    return _run_remote_helper("ssh", host, user, password, remote_cmd, timeout=timeout)


def _run_scp(host: str, user: str, password: str, remote_path: str, local_path: str, timeout: int = 600) -> str:
    return _run_remote_helper("scp", host, user, password, remote_path, local_path, timeout=timeout)


remote_helper_module = types.ModuleType("scripts.remote_accept_helper")
remote_helper_module.run_ssh = _run_ssh
remote_helper_module.run_scp = _run_scp
sys.modules.setdefault("scripts.remote_accept_helper", remote_helper_module)

from scripts.build_accept_sample_batch import (
    RemoteDoc,
    SamplePair,
    _batch_extract_docs,
    _download_pairs,
    _list_attachment_dirs,
    _list_files,
    _write_extract_outputs,
    _write_tsv,
)

REMOTE_ROOT = "/mnt/expansion/Volume1/public/jhxm_fj/FJ/sbr"


@dataclass(frozen=True)
class DbPairRow:
    year: str
    project_name: str
    project_no: str
    hts_id: str
    yssq_id: str
    hts_file_hint: str = ""
    yssq_file_hint: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build acceptance batch using kjhxm.yssq_jbxx.onlysign -> Ht_Jbxx.id pairing."
    )
    parser.add_argument("--host", default="192.168.0.198", help="file server host")
    parser.add_argument("--user", default="tdkx", help="file server user")
    parser.add_argument("--password", default="tdkx@linux", help="file server password")
    parser.add_argument("--year", default="2019")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--output-dir", default="debug_accept")

    parser.add_argument("--db-host", default="192.168.0.190")
    parser.add_argument("--db-user", default="sa")
    parser.add_argument("--db-password", default="tdkx")
    parser.add_argument("--db-name", default="kjhxm")
    parser.add_argument("--db-port", type=int, default=1433)
    parser.add_argument("--db-timeout", type=int, default=30)
    parser.add_argument("--hts-table", default="Ht_Jbxx")
    parser.add_argument("--yssq-table", default="yssq_jbxx")
    parser.add_argument("--hts-id-column", default="id")
    parser.add_argument("--yssq-id-column", default="id")
    parser.add_argument("--yssq-onlysign-column", default="onlysign")
    parser.add_argument("--project-name-column", default="xmmc")
    parser.add_argument("--project-no-column", default="xmbh")
    parser.add_argument("--year-column", default="", help="optional yssq year column used to filter DB rows")
    parser.add_argument("--hts-file-column", default="", help="optional hts file-name/path column")
    parser.add_argument("--yssq-file-column", default="", help="optional yssq file-name/path column")
    return parser.parse_args()


def q(identifier: str) -> str:
    return "[" + identifier.replace("]", "]]") + "]"


def compact_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    name = Path(text.replace("\\", "/")).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return re.sub(r"\s+", "", name).lower()


def file_candidates(*values: object) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        names = [text, Path(text.replace("\\", "/")).name]
        for name in names:
            if not name:
                continue
            variants = [name]
            if "." not in Path(name).name:
                variants.append(f"{name}.pdf")
            for variant in variants:
                key = variant.lower()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(variant)
    return candidates


def index_remote_files(paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        name = Path(path).name
        result.setdefault(name.lower(), path)
        result.setdefault(Path(name).stem.lower(), path)
    return result


def find_remote_file(index: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        name = Path(candidate.replace("\\", "/")).name
        for key in (name.lower(), Path(name).stem.lower()):
            if key in index:
                return index[key]
    return ""


def find_attachment_dir(attachment_dirs: dict[str, int], candidates: list[str]) -> tuple[str, int]:
    lowered = {name.lower(): (name, count) for name, count in attachment_dirs.items()}
    for candidate in candidates:
        stem = Path(candidate.replace("\\", "/")).stem.lower()
        if stem in lowered:
            return lowered[stem]
    return "", 0


def table_columns(conn: pymssql.Connection, table_name: str) -> set[str]:
    cur = conn.cursor(as_dict=True)
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE LOWER(TABLE_NAME)=LOWER(%s)
        """,
        (table_name,),
    )
    return {str(row["COLUMN_NAME"]) for row in cur.fetchall()}


def choose_column(columns: set[str], explicit: str, candidates: list[str]) -> str:
    if explicit:
        return explicit
    lowered = {col.lower(): col for col in columns}
    for candidate in candidates:
        found = lowered.get(candidate.lower())
        if found:
            return found
    return ""


def fetch_db_pair_rows(args: argparse.Namespace) -> list[DbPairRow]:
    try:
        conn = pymssql.connect(
            server=args.db_host,
            port=args.db_port,
            user=args.db_user,
            password=args.db_password,
            database=args.db_name,
            login_timeout=args.db_timeout,
            timeout=args.db_timeout,
            charset="utf8",
        )
    except Exception as exc:  # pragma: no cover - depends on local network credentials
        raise SystemExit(
            f"无法连接项目库 {args.db_host}:{args.db_port}/{args.db_name}，"
            f"用户 {args.db_user} 登录失败或无权限；请确认数据库账号、端口和 SQL Server 认证方式。原始错误：{exc}"
        ) from exc
    try:
        hts_columns = table_columns(conn, args.hts_table)
        yssq_columns = table_columns(conn, args.yssq_table)
        hts_file_col = choose_column(
            hts_columns,
            args.hts_file_column,
            ["file_name", "filename", "wjmc", "wjm", "htswj", "hts_file", "filepath", "file_path", "wjlj"],
        )
        yssq_file_col = choose_column(
            yssq_columns,
            args.yssq_file_column,
            ["file_name", "filename", "wjmc", "wjm", "yssqwj", "yssq_file", "filepath", "file_path", "wjlj"],
        )
        year_col = choose_column(yssq_columns, args.year_column, ["year", "nd", "nf", "sqsj", "tbsj"])

        select_parts = [
            f"h.{q(args.hts_id_column)} AS hts_id",
            f"y.{q(args.yssq_id_column)} AS yssq_id",
            f"h.{q(args.project_name_column)} AS project_name",
            f"h.{q(args.project_no_column)} AS project_no",
        ]
        if hts_file_col:
            select_parts.append(f"h.{q(hts_file_col)} AS hts_file_hint")
        else:
            select_parts.append("CAST('' AS varchar(1)) AS hts_file_hint")
        if yssq_file_col:
            select_parts.append(f"y.{q(yssq_file_col)} AS yssq_file_hint")
        else:
            select_parts.append("CAST('' AS varchar(1)) AS yssq_file_hint")
        if year_col:
            select_parts.append(f"y.{q(year_col)} AS row_year")
        else:
            select_parts.append("CAST('' AS varchar(1)) AS row_year")

        where_parts = [
            f"y.{q(args.yssq_onlysign_column)} = h.{q(args.hts_id_column)}",
            f"y.{q(args.yssq_onlysign_column)} IS NOT NULL",
        ]
        params: list[Any] = []
        if year_col:
            where_parts.append(f"CONVERT(varchar(32), y.{q(year_col)}, 120) LIKE %s")
            params.append(f"%{args.year}%")

        sql = f"""
        SELECT TOP {int(args.sample_size) * 8}
            {', '.join(select_parts)}
        FROM {q(args.yssq_table)} y
        INNER JOIN {q(args.hts_table)} h
            ON y.{q(args.yssq_onlysign_column)} = h.{q(args.hts_id_column)}
        WHERE {' AND '.join(where_parts)}
        ORDER BY y.{q(args.yssq_id_column)}
        """
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, tuple(params))
        rows: list[DbPairRow] = []
        seen: set[tuple[str, str]] = set()
        for row in cur.fetchall():
            hts_id = str(row.get("hts_id") or "").strip()
            yssq_id = str(row.get("yssq_id") or "").strip()
            if not hts_id or not yssq_id:
                continue
            key = (hts_id, yssq_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                DbPairRow(
                    year=args.year,
                    project_name=str(row.get("project_name") or "").strip(),
                    project_no=str(row.get("project_no") or "").strip(),
                    hts_id=hts_id,
                    yssq_id=yssq_id,
                    hts_file_hint=str(row.get("hts_file_hint") or "").strip(),
                    yssq_file_hint=str(row.get("yssq_file_hint") or "").strip(),
                )
            )
        return rows
    finally:
        conn.close()


def build_pairs(args: argparse.Namespace, db_rows: list[DbPairRow]) -> tuple[list[SamplePair], list[list[object]], dict[str, int]]:
    hts_paths = _list_files(args.host, args.user, args.password, args.year, "hts")
    yssq_paths = _list_files(args.host, args.user, args.password, args.year, "yssq")
    attachment_dirs = _list_attachment_dirs(args.host, args.user, args.password, args.year)
    hts_index = index_remote_files(hts_paths)
    yssq_index = index_remote_files([path for path in yssq_paths if not path.endswith("-null.pdf")])

    pairs: list[SamplePair] = []
    audit_rows: list[list[object]] = []
    yssq_docs_to_extract: list[str] = []
    hts_docs_to_extract: list[str] = []
    pending: list[tuple[DbPairRow, str, str, str, int]] = []

    for row in db_rows:
        hts_candidates = file_candidates(row.hts_file_hint, row.hts_id)
        yssq_candidates = file_candidates(row.yssq_file_hint, row.yssq_id)
        hts_path = find_remote_file(hts_index, hts_candidates)
        yssq_path = find_remote_file(yssq_index, yssq_candidates)
        yssqfj_dir, attachment_count = find_attachment_dir(attachment_dirs, yssq_candidates)
        audit_rows.append(
            [
                row.year,
                row.project_no,
                row.project_name,
                row.hts_id,
                row.yssq_id,
                row.hts_file_hint,
                row.yssq_file_hint,
                Path(hts_path).name if hts_path else "",
                Path(yssq_path).name if yssq_path else "",
                yssqfj_dir,
                attachment_count,
                "ok" if hts_path and yssq_path and yssqfj_dir else "missing_file_or_attachment",
            ]
        )
        if not (hts_path and yssq_path and yssqfj_dir):
            continue
        pending.append((row, hts_path, yssq_path, yssqfj_dir, attachment_count))
        hts_docs_to_extract.append(hts_path)
        yssq_docs_to_extract.append(yssq_path)
        if len(pending) >= args.sample_size:
            break

    hts_docs = {doc.remote_path: doc for doc in _batch_extract_docs(args.host, args.user, args.password, args.year, "hts", hts_docs_to_extract)}
    yssq_docs = {doc.remote_path: doc for doc in _batch_extract_docs(args.host, args.user, args.password, args.year, "yssq", yssq_docs_to_extract)}

    for row, hts_path, yssq_path, yssqfj_dir, attachment_count in pending:
        hts_doc = hts_docs.get(hts_path) or RemoteDoc(row.year, "hts", Path(hts_path).name, hts_path, "", row.project_name, row.project_no)
        yssq_doc = yssq_docs.get(yssq_path) or RemoteDoc(row.year, "yssq", Path(yssq_path).name, yssq_path, "", row.project_name, row.project_no)
        hts_doc.project_name = hts_doc.project_name or row.project_name
        hts_doc.project_no = hts_doc.project_no or row.project_no
        yssq_doc.project_name = yssq_doc.project_name or row.project_name
        yssq_doc.project_no = yssq_doc.project_no or row.project_no
        pairs.append(
            SamplePair(
                year=row.year,
                project_name=row.project_name or hts_doc.project_name or yssq_doc.project_name,
                project_no=row.project_no or hts_doc.project_no or yssq_doc.project_no,
                hts=hts_doc,
                yssq=yssq_doc,
                yssqfj_dir=yssqfj_dir,
                attachment_count=attachment_count,
            )
        )
    return pairs, audit_rows, attachment_dirs


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    db_rows = fetch_db_pair_rows(args)
    pairs, audit_rows, attachment_dirs = build_pairs(args, db_rows)

    _write_tsv(
        output_dir / "project_pairing.tsv",
        ["year", "project_no", "project_name", "hts_file", "yssq_file", "yssqfj_dir", "attachment_count"],
        [[p.year, p.project_no, p.project_name, p.hts.file_name, p.yssq.file_name, p.yssqfj_dir, p.attachment_count] for p in pairs],
    )
    _write_tsv(
        output_dir / "project_pairing_db_audit.tsv",
        [
            "year", "project_no", "project_name", "hts_id", "yssq_id", "hts_file_hint", "yssq_file_hint",
            "matched_hts_file", "matched_yssq_file", "matched_yssqfj_dir", "attachment_count", "status",
        ],
        audit_rows,
    )
    _write_tsv(
        output_dir / "project_pairing_summary.tsv",
        ["year", "db_join_count", "yssqfj_dir_count", "matched_count", "sampled_count"],
        [[args.year, len(db_rows), len(attachment_dirs), len([r for r in audit_rows if r[-1] == "ok"]), len(pairs)]],
    )

    _download_pairs(args.host, args.user, args.password, output_dir, pairs)
    _write_extract_outputs(output_dir, pairs, args.host, args.user, args.password)
    print(f"Built {len(pairs)} DB-backed sample pairs in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
