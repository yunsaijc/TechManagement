#!/usr/bin/env python3
"""对目录内申报书/任务书批量跑逻辑自洽，每文件生成一份 Markdown + JSON 报告。"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 项目根：scripts/ 上一级
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.logicon import get_logicon_service
from src.services.logicon.reporter import LogicOnReporter


def list_docs(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.name.startswith("~$"):
            continue
        if p.suffix.lower() not in (".pdf", ".docx"):
            continue
        out.append(p)
    return out


async def run_file(
    svc,
    path: Path,
    doc_kind: str,
    *,
    enable_llm: bool,
    enable_agent: bool,
    agent_max_turns: int,
    enable_equivalence_probe: bool,
    out_dir: Path,
) -> dict:
    ft = path.suffix.lower().strip(".")
    data = path.read_bytes()
    t0 = asyncio.get_event_loop().time()
    # 防止同 stem 的 docx/pdf 输出互相覆盖（如 xxx.docx 与 xxx.pdf）。
    slug = f"{path.stem}_{ft}_{doc_kind}"
    try:
        r = await svc.check_file(
            file_data=data,
            file_type=ft,
            doc_kind=doc_kind,
            enable_llm=enable_llm,
            return_graph=False,
            enable_agent=enable_agent,
            agent_max_turns=agent_max_turns,
            enable_equivalence_probe=enable_equivalence_probe,
        )
        elapsed = asyncio.get_event_loop().time() - t0
        rep = LogicOnReporter()
        md_path = out_dir / f"{slug}.md"
        json_path = out_dir / f"{slug}.json"
        md_path.write_text(rep.build_markdown(r), encoding="utf-8")
        json_path.write_text(rep.build_json(r), encoding="utf-8")
        return {
            "ok": True,
            "path": str(path),
            "slug": slug,
            "doc_id": r.doc_id,
            "conflict_count": len(r.conflicts or []),
            "partial": r.partial,
            "elapsed_sec": round(elapsed, 2),
            "report_md": str(md_path),
            "report_json": str(json_path),
        }
    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - t0
        err_path = out_dir / f"{slug}_ERROR.txt"
        err_path.write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
        return {
            "ok": False,
            "path": str(path),
            "slug": slug,
            "error": f"{type(e).__name__}: {e}",
            "elapsed_sec": round(elapsed, 2),
            "error_log": str(err_path),
        }


def _parse_json_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dim_block(data: dict[str, Any], rule_id: str) -> dict[str, Any] | None:
    for b in data.get("dimension_summaries") or []:
        if isinstance(b, dict) and b.get("rule_id") == rule_id:
            return b
    return None


def _first_line_match(lines: list[Any], pattern: str) -> str | None:
    for line in lines or []:
        if not isinstance(line, str):
            continue
        m = re.search(pattern, line)
        if m:
            return m.group(1).strip() if m.lastindex else line.strip()
    return None


def write_paired_reports(out_root: Path, summary: list[dict]) -> Path | None:
    """同一 stem 下任务书/申报书并列：执行期、直接费用合计、指标冲突条数。"""
    by_stem: dict[str, dict[str, Path]] = {}
    by_stem_fmt: dict[str, dict[str, str]] = {}
    for row in summary:
        if not row.get("ok"):
            continue
        slug = str(row.get("slug") or "")
        jp = row.get("report_json")
        if not jp:
            continue
        path = Path(str(jp))
        if not path.is_file():
            continue
        m = re.match(r"^(?P<stem>.+?)_(?:(?P<fmt>docx|pdf)_)?(?P<kind>task|declaration)$", slug, re.I)
        if not m:
            continue
        stem = (m.group("stem") or "").strip()
        fmt = (m.group("fmt") or "").strip().lower()
        kind = (m.group("kind") or "").strip().lower()
        if not stem or kind not in {"task", "declaration"}:
            continue
        slot = by_stem.setdefault(stem, {})
        fmt_slot = by_stem_fmt.setdefault(stem, {})
        prev_fmt = fmt_slot.get(kind, "")
        # 同一 stem 同一侧若既有 docx 又有 pdf，优先用 docx。
        if kind in slot and prev_fmt == "docx" and fmt != "docx":
            continue
        slot[kind] = path
        fmt_slot[kind] = fmt

    lines: list[str] = [
        "# 任务书与申报书成对核对",
        "",
        "对同一 `stem`（文件名不含 `_task` / `_declaration` 后缀）同时存在任务书与申报书时，从 JSON 的维度摘要抽取关键字段并列，便于人工核对「前后」是否一致。",
        "",
        "| stem | 侧 | 执行期（摘要） | 预算直接费用（万） | R-METRIC 冲突 |",
        "| --- | --- | --- | --- | --- |",
    ]
    n = 0
    for stem in sorted(by_stem.keys()):
        pair = by_stem[stem]
        if "task" not in pair or "declaration" not in pair:
            continue
        n += 1
        for side, label in (("task", "任务书"), ("declaration", "申报书")):
            data = _parse_json_result(pair[side])
            tlines = (_dim_block(data, "R-TIME-01") or {}).get("detail_lines") or []
            blines = (_dim_block(data, "R-BUDGET-01") or {}).get("detail_lines") or []
            exec_s = (
                _first_line_match(tlines, r"执行期(?:（抽取）)?：(.+?)。")
                or "—"
            )
            bud_s = (
                _first_line_match(blines, r"预算总额(?:（抽取）)?：([\d.]+)\s*万元")
                or _first_line_match(blines, r"（一）直接费用(?:（抽取）)?：([\d.]+)\s*万元")
                or "—"
            )
            mc = len([c for c in (data.get("conflicts") or []) if c.get("rule_id") == "R-METRIC-01"])
            lines.append(f"| `{stem}` | {label} | {exec_s} | {bud_s} | {mc} |")

    if n == 0:
        return None
    out = out_root / "paired_task_declaration.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


async def main_async(args: argparse.Namespace) -> None:
    task_dir = Path(args.task_dir)
    decl_dir = Path(args.decl_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path(args.out_root) / f"batch_{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)

    svc = get_logicon_service()
    jobs: list[tuple[str, Path]] = []
    for p in list_docs(task_dir):
        jobs.append(("task", p))
    for p in list_docs(decl_dir):
        jobs.append(("declaration", p))

    summary: list[dict] = []
    for kind, p in jobs:
        print(f"[{kind}] {p.name} ...", flush=True)
        row = await run_file(
            svc,
            p,
            kind,
            enable_llm=args.enable_llm,
            enable_agent=args.enable_agent,
            agent_max_turns=args.agent_max_turns,
            enable_equivalence_probe=args.enable_equivalence_probe,
            out_dir=out_root,
        )
        summary.append(row)
        if row.get("ok"):
            print(f"  -> {row['conflict_count']} conflicts, {row['report_md']}")
        else:
            print(f"  !! {row.get('error')}")

    index = out_root / "index.json"
    index.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    paired = write_paired_reports(out_root, summary)
    print(f"\n输出目录: {out_root}")
    print(f"索引: {index}")
    if paired:
        print(f"成对核对: {paired}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="批量逻辑自洽并生成每文件报告")
    p.add_argument(
        "--task-dir",
        default=str(ROOT / "data" / "samples_2025_docx" / "hts"),
        help="任务书目录",
    )
    p.add_argument(
        "--decl-dir",
        default=str(ROOT / "data" / "samples_2025_docx" / "sbs"),
        help="申报书目录",
    )
    p.add_argument(
        "--out-root",
        default=str(ROOT / "debug_logicon" / "reports"),
        help="报告根目录（其下会建 batch_时间戳）",
    )
    p.add_argument(
        "--enable-llm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否启用 LLM 指标语义归一（默认：开启）",
    )
    p.add_argument(
        "--enable-agent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否启用工具调用 Agent 复核（默认：开启；大批量可 --no-enable-agent）",
    )
    p.add_argument(
        "--agent-max-turns",
        type=int,
        default=8,
        help="Agent 最大对话轮数（默认：8）",
    )
    p.add_argument(
        "--enable-equivalence-probe",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否为 Agent 注册「语义等价探测」工具 semantic_metric_equivalence_probe（默认：关闭，避免额外 LLM）",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
