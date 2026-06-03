#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.remote_accept_helper import run_scp, run_ssh
from src.services.accept.evidence import AttachmentEvidenceExtractor
from src.services.accept.kpi import KPIExtractor
from src.services.accept.models import ParsedAcceptanceDocument


REMOTE_ROOT = "/mnt/expansion/Volume1/public/jhxm_fj/FJ/sbr"
BLOCK_START = "===FILE==="
BLOCK_END = "===END==="


@dataclass
class RemoteDoc:
    year: str
    kind: str
    file_name: str
    remote_path: str
    text: str
    project_name: str
    project_no: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.project_name, self.project_no)


@dataclass
class SamplePair:
    year: str
    project_name: str
    project_no: str
    hts: RemoteDoc
    yssq: RemoteDoc
    yssqfj_dir: str
    attachment_count: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build acceptance sampling batch under debug_accept.")
    parser.add_argument("--host", default="192.168.0.198")
    parser.add_argument("--user", default="tdkx")
    parser.add_argument("--password", default="tdkx@linux")
    parser.add_argument("--year", default="2019")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--candidate-multiplier", type=int, default=8)
    parser.add_argument("--output-dir", default="debug_accept")
    return parser.parse_args()


def _normalize_text(text: str) -> str:
    text = text.replace("\x0c", "\n")
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _extract_project_meta(text: str) -> tuple[str, str]:
    flat = _compact(text)
    name = ""
    number = ""
    name_match = re.search(r"项目名称[:：]?(.*?)(?:项目编号|项目起止年月|签订年度)[:：]", flat)
    if name_match:
        name = name_match.group(1).strip("：:")
    number_match = re.search(r"项目编号[:：]?([0-9A-Za-z-]+)", flat)
    if number_match:
        number = number_match.group(1).strip()
    return name, number


def _list_files(host: str, user: str, password: str, year: str, kind: str) -> list[str]:
    remote_cmd = f"find {REMOTE_ROOT}/{year}/{kind} -maxdepth 1 -type f | sort"
    output = run_ssh(host, user, password, remote_cmd)
    return [line.strip() for line in output.splitlines() if line.strip().startswith("/")]


def _list_attachment_dirs(host: str, user: str, password: str, year: str) -> dict[str, int]:
    remote_cmd = (
        f"find {REMOTE_ROOT}/{year}/yssqfj -mindepth 1 -maxdepth 1 -type d | sort | "
        "while read d; do "
        'count=$(find "$d" -maxdepth 1 -type f | wc -l); '
        'printf "%s\\t%s\\n" "$(basename "$d")" "$count"; '
        "done"
    )
    output = run_ssh(host, user, password, remote_cmd, timeout=300)
    result: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 2:
            continue
        result[parts[0]] = int(parts[1])
    return result


def _batch_extract_docs(
    host: str,
    user: str,
    password: str,
    year: str,
    kind: str,
    remote_paths: list[str],
) -> list[RemoteDoc]:
    docs: list[RemoteDoc] = []
    batch_size = 25
    line_limit = 420 if kind == "hts" else 80
    for idx in range(0, len(remote_paths), batch_size):
        batch = remote_paths[idx : idx + batch_size]
        lines = []
        for path in batch:
            lines.append(f'echo "{BLOCK_START}\t{path}"')
            lines.append(f'pdftotext "{path}" - 2>/dev/null | head -n {line_limit}')
            lines.append(f'echo "{BLOCK_END}"')
        output = run_ssh(host, user, password, "; ".join(lines), timeout=600)
        docs.extend(_parse_doc_blocks(output, year=year, kind=kind))
    return docs


def _extract_matching_hts_docs(
    host: str,
    user: str,
    password: str,
    year: str,
    remote_paths: list[str],
    target_keys: set[tuple[str, str]],
    stop_after: int,
) -> list[RemoteDoc]:
    docs: list[RemoteDoc] = []
    matched_keys: set[tuple[str, str]] = set()
    batch_size = 25
    line_limit = 420
    for idx in range(0, len(remote_paths), batch_size):
        batch = remote_paths[idx : idx + batch_size]
        lines = []
        for path in batch:
            lines.append(f'echo "{BLOCK_START}\t{path}"')
            lines.append(f'pdftotext "{path}" - 2>/dev/null | head -n {line_limit}')
            lines.append(f'echo "{BLOCK_END}"')
        output = run_ssh(host, user, password, "; ".join(lines), timeout=600)
        for doc in _parse_doc_blocks(output, year=year, kind="hts"):
            if doc.key not in target_keys:
                continue
            docs.append(doc)
            matched_keys.add(doc.key)
        if len(matched_keys) >= stop_after:
            break
    return docs


def _parse_doc_blocks(output: str, *, year: str, kind: str) -> list[RemoteDoc]:
    docs: list[RemoteDoc] = []
    current_path = ""
    buffer: list[str] = []
    for raw_line in output.splitlines():
        if raw_line.startswith(BLOCK_START):
            current_path = raw_line.split("\t", 1)[1].strip()
            buffer = []
            continue
        if raw_line.startswith(BLOCK_END):
            text = _normalize_text("\n".join(buffer))
            file_name = Path(current_path).name
            project_name, project_no = _extract_project_meta(text)
            docs.append(
                RemoteDoc(
                    year=year,
                    kind=kind,
                    file_name=file_name,
                    remote_path=current_path,
                    text=text,
                    project_name=project_name,
                    project_no=project_no,
                )
            )
            current_path = ""
            buffer = []
            continue
        if current_path:
            buffer.append(raw_line)
    return docs


def _choose_pairs(
    hts_docs: list[RemoteDoc],
    yssq_docs: list[RemoteDoc],
    attachment_dirs: dict[str, int],
    sample_size: int,
) -> list[SamplePair]:
    hts_by_key: dict[tuple[str, str], list[RemoteDoc]] = {}
    for doc in hts_docs:
        if not doc.project_name or not doc.project_no:
            continue
        hts_by_key.setdefault(doc.key, []).append(doc)

    pairs: list[SamplePair] = []
    seen_keys: set[tuple[str, str]] = set()
    for yssq in yssq_docs:
        if yssq.file_name.endswith("-null.pdf"):
            continue
        stem = Path(yssq.file_name).stem
        if stem not in attachment_dirs:
            continue
        key = yssq.key
        if not key[0] or not key[1] or key in seen_keys:
            continue
        matched_hts = hts_by_key.get(key)
        if not matched_hts:
            continue
        seen_keys.add(key)
        pairs.append(
            SamplePair(
                year=yssq.year,
                project_name=yssq.project_name,
                project_no=yssq.project_no,
                hts=matched_hts[0],
                yssq=yssq,
                yssqfj_dir=stem,
                attachment_count=attachment_dirs[stem],
            )
        )
        if len(pairs) >= sample_size:
            break
    return pairs


def _write_tsv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(headers)
        writer.writerows(rows)


def _download_pairs(host: str, user: str, password: str, output_dir: Path, pairs: list[SamplePair]) -> None:
    for pair in pairs:
        year_dir = output_dir / "sample_batch" / "files" / pair.year
        hts_dir = year_dir / "hts"
        yssq_dir = year_dir / "yssq"
        yssqfj_dir = year_dir / "yssqfj"
        hts_dir.mkdir(parents=True, exist_ok=True)
        yssq_dir.mkdir(parents=True, exist_ok=True)
        yssqfj_dir.mkdir(parents=True, exist_ok=True)
        run_scp(host, user, password, pair.hts.remote_path, str(hts_dir / pair.hts.file_name))
        run_scp(host, user, password, pair.yssq.remote_path, str(yssq_dir / pair.yssq.file_name))
        run_scp(
            host,
            user,
            password,
            f"{REMOTE_ROOT}/{pair.year}/yssqfj/{pair.yssqfj_dir}",
            str(yssqfj_dir / pair.yssqfj_dir),
        )


def _extract_attachment_docs(
    host: str,
    user: str,
    password: str,
    year: str,
    yssqfj_dir: str,
) -> list[ParsedAcceptanceDocument]:
    remote_cmd = (
        f"find {REMOTE_ROOT}/{year}/yssqfj/{yssqfj_dir} -maxdepth 1 -type f | sort | "
        "while read f; do "
        f'echo "{BLOCK_START}\t$f"; '
        'case "$f" in '
        '*.pdf) pdftotext "$f" - 2>/dev/null | head -n 80 ;; '
        '*.jpg|*.jpeg|*.png) true ;; '
        '*) true ;; '
        "esac; "
        f'echo "{BLOCK_END}"; '
        "done"
    )
    output = run_ssh(host, user, password, remote_cmd, timeout=600)
    docs: list[ParsedAcceptanceDocument] = []
    current_path = ""
    buffer: list[str] = []
    for raw_line in output.splitlines():
        if raw_line.startswith(BLOCK_START):
            current_path = raw_line.split("\t", 1)[1].strip()
            buffer = []
            continue
        if raw_line.startswith(BLOCK_END):
            text = _normalize_text("\n".join(buffer))
            file_name = Path(current_path).name
            file_type = Path(file_name).suffix.lower().lstrip(".")
            docs.append(
                ParsedAcceptanceDocument(
                    file_name=file_name,
                    file_type=file_type,
                    text=text,
                    lines=[line.strip() for line in text.splitlines() if line.strip()],
                    metadata={"remote_path": current_path},
                )
            )
            current_path = ""
            buffer = []
            continue
        if current_path:
            buffer.append(raw_line)
    return docs


def _write_extract_outputs(
    output_dir: Path,
    pairs: list[SamplePair],
    host: str,
    user: str,
    password: str,
) -> None:
    kpi_extractor = KPIExtractor()
    evidence_extractor = AttachmentEvidenceExtractor()

    field_rows: list[list[object]] = []
    mapping_rows: list[list[object]] = []

    for pair in pairs:
        taskbook_doc = ParsedAcceptanceDocument(
            file_name=pair.hts.file_name,
            file_type="pdf",
            text=pair.hts.text,
            lines=[line.strip() for line in pair.hts.text.splitlines() if line.strip()],
            metadata={"remote_path": pair.hts.remote_path},
        )
        commitments = kpi_extractor.extract(taskbook_doc)
        for item in commitments:
            field_rows.append(
                [
                    pair.year,
                    pair.project_no,
                    pair.project_name,
                    "hts",
                    pair.hts.file_name,
                    item.metric_category,
                    item.metric_name,
                    item.target_value,
                    item.target_unit,
                    item.comparator,
                    item.source_line,
                ]
            )

        attachment_docs = _extract_attachment_docs(host, user, password, pair.year, pair.yssqfj_dir)
        for doc in attachment_docs:
            evidence_items = evidence_extractor.extract(doc)
            mapping_rows.append(
                [
                    pair.year,
                    pair.project_no,
                    pair.project_name,
                    pair.yssq.file_name,
                    pair.yssqfj_dir,
                    doc.file_name,
                    doc.file_type,
                    len(doc.lines),
                    len(evidence_items),
                ]
            )
            for item in evidence_items:
                field_rows.append(
                    [
                        pair.year,
                        pair.project_no,
                        pair.project_name,
                        "yssqfj",
                        doc.file_name,
                        item.metric_category,
                        item.metric_name,
                        item.value if item.value is not None else item.implicit_count,
                        item.unit,
                        "",
                        item.excerpt,
                    ]
                )

    _write_tsv(
        output_dir / "project_field_extract.tsv",
        [
            "year",
            "project_no",
            "project_name",
            "source_kind",
            "source_file",
            "metric_category",
            "metric_name",
            "value",
            "unit",
            "comparator",
            "source_excerpt",
        ],
        field_rows,
    )
    _write_tsv(
        output_dir / "yssq_yssqfj_mapping_summary.tsv",
        [
            "year",
            "project_no",
            "project_name",
            "yssq_file",
            "yssqfj_dir",
            "attachment_file",
            "attachment_type",
            "text_line_count",
            "evidence_item_count",
        ],
        mapping_rows,
    )


def main() -> int:
    args = _parse_args()
    output_dir = Path(args.output_dir)

    hts_paths = _list_files(args.host, args.user, args.password, args.year, "hts")
    yssq_paths = _list_files(args.host, args.user, args.password, args.year, "yssq")
    attachment_dirs = _list_attachment_dirs(args.host, args.user, args.password, args.year)

    yssq_candidate_paths = []
    for path in yssq_paths:
        if path.endswith("-null.pdf"):
            continue
        stem = Path(path).stem
        if stem not in attachment_dirs:
            continue
        yssq_candidate_paths.append(path)
        if len(yssq_candidate_paths) >= args.sample_size * args.candidate_multiplier:
            break

    yssq_docs = _batch_extract_docs(args.host, args.user, args.password, args.year, "yssq", yssq_candidate_paths)
    target_keys = {doc.key for doc in yssq_docs if doc.project_name and doc.project_no}
    hts_docs = _extract_matching_hts_docs(
        args.host,
        args.user,
        args.password,
        args.year,
        hts_paths,
        target_keys,
        stop_after=args.sample_size,
    )

    pairs = _choose_pairs(hts_docs, yssq_docs, attachment_dirs, args.sample_size)

    _write_tsv(
        output_dir / "project_pairing.tsv",
        [
            "year",
            "project_no",
            "project_name",
            "hts_file",
            "yssq_file",
            "yssqfj_dir",
            "attachment_count",
        ],
        [
            [
                pair.year,
                pair.project_no,
                pair.project_name,
                pair.hts.file_name,
                pair.yssq.file_name,
                pair.yssqfj_dir,
                pair.attachment_count,
            ]
            for pair in pairs
        ],
    )

    _write_tsv(
        output_dir / "project_pairing_summary.tsv",
        ["year", "hts_count", "yssq_count", "yssq_non_null_count", "yssqfj_dir_count", "matched_count", "sampled_count"],
        [
            [
                args.year,
                len(hts_paths),
                len(yssq_paths),
                len([path for path in yssq_paths if not path.endswith("-null.pdf")]),
                len(attachment_dirs),
                len({(pair.project_name, pair.project_no) for pair in pairs}),
                len(pairs),
            ]
        ],
    )

    _download_pairs(args.host, args.user, args.password, output_dir, pairs)
    _write_extract_outputs(output_dir, pairs, args.host, args.user, args.password)
    print(f"Built {len(pairs)} sample pairs in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
