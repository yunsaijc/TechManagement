#!/usr/bin/env python3
"""Generate fixed review regression cases.

The output is intentionally static JSONL. Random sampling is only used when
creating the file, with a recorded seed, so future test runs are comparable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.database.connection import get_reward_connection
from src.services.review.doc_types import get_doc_type_label, normalize_doc_type
from src.services.review.reward_review_service import DOC_TYPE_TO_LX, QTFJCL_DOC_TYPES


DEFAULT_DOC_TYPES = (
    "tjdwyj",
    "gzdwyj",
    "wcr",
    "wcdw",
    "hzdw",
    "dywcrcns",
    "dywcdwcns",
    "qysm",
)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _normalize_file_path(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = text.replace("/", "\\")
    return re.sub(r"\\+", r"\\", text)


def _case_id(doc_type: str, project_id: str, file_path: str) -> str:
    filename = Path(str(file_path).replace("\\", "/")).name
    stem = Path(filename).stem or hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:12]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{doc_type}_{project_id}_{stem}").strip("_")
    digest = hashlib.sha1(f"{project_id}|{doc_type}|{file_path}".encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


def _split_multiline(value: str) -> list[str]:
    parts = []
    for item in re.split(r"[\r\n]+", value or ""):
        cleaned = item.strip().strip('"').strip()
        if cleaned:
            parts.append(cleaned)
    return parts


def _parse_review_url(url: str) -> dict[str, str]:
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    out = {key: values[0] for key, values in query.items() if values}
    return {
        "project_id": _clean_text(out.get("project_id")),
        "doc_type": normalize_doc_type(_clean_text(out.get("doc_type")), default=""),
        "file_path": _clean_text(out.get("file_path")),
    }


def load_special_cases(excel_path: Path) -> list[dict[str, Any]]:
    if not excel_path.exists():
        return []

    import pandas as pd

    cases: list[dict[str, Any]] = []
    df = pd.read_excel(excel_path)
    for row_index, row in df.iterrows():
        project_id = _clean_text(row.get("项目编号"))
        problem = _clean_text(row.get("形审问题"))
        test_problem = _clean_text(row.get("测试问题"))
        nomination_no = _clean_text(row.get("提名号"))
        urls = _split_multiline(_clean_text(row.get("接口地址")))
        paths = _split_multiline(_clean_text(row.get("文件路径")))
        parsed_urls = [_parse_review_url(url) for url in urls if "review/path" in url]

        if parsed_urls:
            for sub_index, item in enumerate(parsed_urls, start=1):
                doc_type = item["doc_type"] or "unknown"
                file_path = _normalize_file_path(item["file_path"])
                pid = item["project_id"] or project_id
                if not pid or not file_path:
                    continue
                cases.append(
                    {
                        "case_id": _case_id(doc_type, pid, file_path),
                        "source": "special",
                        "row": int(row_index) + 2,
                        "sub_index": sub_index,
                        "project_id": pid,
                        "doc_type": doc_type,
                        "doc_type_label": get_doc_type_label(doc_type),
                        "file_path": file_path,
                        "title": "",
                        "lx": DOC_TYPE_TO_LX.get(doc_type, ""),
                        "nomination_no": nomination_no,
                        "problem": problem,
                        "test_problem": test_problem,
                        "gt_hint": {
                            "source": "special_case_description",
                            "review_required": True,
                            "problem": problem,
                            "test_problem": test_problem,
                        },
                    }
                )
            continue

        for sub_index, file_path in enumerate(paths, start=1):
            file_path = _normalize_file_path(file_path)
            if not project_id or not file_path:
                continue
            doc_type = "unknown"
            cases.append(
                {
                    "case_id": _case_id(doc_type, project_id, file_path),
                    "source": "special",
                    "row": int(row_index) + 2,
                    "sub_index": sub_index,
                    "project_id": project_id,
                    "doc_type": doc_type,
                    "doc_type_label": get_doc_type_label(doc_type),
                    "file_path": file_path,
                    "title": "",
                    "lx": "",
                    "nomination_no": nomination_no,
                    "problem": problem,
                    "test_problem": test_problem,
                    "gt_hint": {
                        "source": "special_case_description",
                        "review_required": True,
                        "problem": problem,
                        "test_problem": test_problem,
                    },
                }
            )
    return _dedupe_cases(cases)


def _query_random_candidates(doc_type: str, limit: int, rng: random.Random) -> list[dict[str, Any]]:
    lx = DOC_TYPE_TO_LX.get(doc_type, "")
    if not lx:
        return []

    table = "t_xm_qtfjcl" if doc_type in QTFJCL_DOC_TYPES else "t_xm_gzy"
    if table == "t_xm_qtfjcl":
        sql = """
        SELECT q.XMBH AS project_id, q.ND AS nd, q.LX AS lx, q.FJMC AS title, q.FJLJ AS file_name,
               COALESCE(gg.XMTJH, qy.XMTJH) AS nomination_no
        FROM t_xm_qtfjcl q
        LEFT JOIN t_xm_ggjbxx gg ON gg.XMBH = q.XMBH
        LEFT JOIN t_qyjscx_qyjbqk qy ON qy.XMBH = q.XMBH
        WHERE q.LX = %s AND q.FJLJ IS NOT NULL AND q.FJLJ <> ''
        ORDER BY q.XMBH, q.FJLJ
        LIMIT 5000
        """
    else:
        sql = """
        SELECT g.XMBH AS project_id, g.ND AS nd, g.LX AS lx, g.FJMC AS title, g.FJLJ AS file_name, gg.XMTJH AS nomination_no
        FROM t_xm_gzy g
        LEFT JOIN t_xm_ggjbxx gg ON gg.XMBH = g.XMBH
        WHERE g.LX = %s AND g.FJLJ IS NOT NULL AND g.FJLJ <> ''
        ORDER BY g.XMBH, g.FJLJ
        LIMIT 5000
        """

    conn = get_reward_connection("xmsbnew")
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (lx,))
            rows = list(cursor.fetchall())
    finally:
        conn.close()

    rng.shuffle(rows)
    selected: list[dict[str, Any]] = []
    seen_projects: set[str] = set()

    # Prefer spreading cases across projects first.
    for row in rows:
        project_id = _clean_text(row.get("project_id"))
        if not project_id or project_id in seen_projects:
            continue
        selected.append(row)
        seen_projects.add(project_id)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        selected_keys = {(row.get("project_id"), row.get("file_name")) for row in selected}
        for row in rows:
            key = (row.get("project_id"), row.get("file_name"))
            if key in selected_keys:
                continue
            selected.append(row)
            selected_keys.add(key)
            if len(selected) >= limit:
                break

    return [_row_to_case(doc_type, row) for row in selected]


def _row_to_case(doc_type: str, row: dict[str, Any]) -> dict[str, Any]:
    project_id = _clean_text(row.get("project_id"))
    nd = _clean_text(row.get("nd"))
    title = _clean_text(row.get("title"))
    file_name = _clean_text(row.get("file_name"))
    nomination_no = _clean_text(row.get("nomination_no"))
    root = "zmcl" if doc_type in QTFJCL_DOC_TYPES else "gzy"
    mid = nomination_no or ""
    if not mid and title:
        mid = ""
    if mid:
        file_path = f"FJCL\\static\\rpw\\{root}{nd}\\{mid}\\{file_name}"
    else:
        # Some qtfjcl rows do not carry XMTJH; keep the best-known stable share path.
        file_path = f"FJCL\\static\\rpw\\{root}{nd}\\{file_name}"
    return {
        "case_id": _case_id(doc_type, project_id, file_path),
        "source": "random",
        "project_id": project_id,
        "doc_type": doc_type,
        "doc_type_label": get_doc_type_label(doc_type),
        "file_path": file_path,
        "title": title,
        "lx": _clean_text(row.get("lx")) or DOC_TYPE_TO_LX.get(doc_type, ""),
        "nomination_no": nomination_no,
        "sample_meta": {
            "nd": nd,
            "file_name": file_name,
        },
    }


def _dedupe_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[tuple[str, str, str]] = set()
    for case in cases:
        key = (
            _clean_text(case.get("project_id")),
            normalize_doc_type(_clean_text(case.get("doc_type")), default=""),
            _clean_text(case.get("file_path")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(case)
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/review_tests")
    parser.add_argument("--special-excel", default="/home/tdkx/workspace/data/签字盖章问题.xlsx")
    parser.add_argument("--per-type", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260511)
    parser.add_argument("--doc-types", nargs="*", default=list(DEFAULT_DOC_TYPES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    rng = random.Random(args.seed)
    doc_types = [normalize_doc_type(item) for item in args.doc_types]

    special_cases = load_special_cases(Path(args.special_excel))
    random_cases: list[dict[str, Any]] = []
    for doc_type in doc_types:
        random_cases.extend(_query_random_candidates(doc_type, args.per_type, rng))

    cases = _dedupe_cases([*special_cases, *random_cases])
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
        "per_type": args.per_type,
        "doc_types": doc_types,
        "special_excel": str(args.special_excel),
        "counts": {
            "special": len(special_cases),
            "random": len(random_cases),
            "total_after_dedupe": len(cases),
            "by_doc_type": {},
        },
    }
    for case in cases:
        doc_type = str(case.get("doc_type") or "")
        manifest["counts"]["by_doc_type"][doc_type] = manifest["counts"]["by_doc_type"].get(doc_type, 0) + 1

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if args.dry_run:
        for row in cases[:5]:
            print(json.dumps(row, ensure_ascii=False))
        return 0

    write_jsonl(output_dir / "cases.jsonl", cases)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
