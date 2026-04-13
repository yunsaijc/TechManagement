import argparse
import asyncio
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.perfcheck import get_perfcheck_service
from src.services.perfcheck.reporter import PerfCheckReporter


@dataclass(frozen=True)
class Pair:
    project_id: str
    declaration_path: Path
    task_path: Path


def _choose_best_file(base: Path, stem: str) -> Optional[Path]:
    candidates = []
    for ext in ["docx"]:
        p = base / f"{stem}.{ext}"
        if p.exists() and p.is_file() and not p.name.startswith("~$"):
            candidates.append(p)
    if candidates:
        return candidates[0]
    return None


def _collect_pairs(sbs_dir: Path, hts_dir: Path) -> list[Pair]:
    sbs_stems = {p.stem for p in sbs_dir.iterdir() if p.is_file() and p.suffix.lower() in {".docx"} and not p.name.startswith("~$")}
    hts_stems = {p.stem for p in hts_dir.iterdir() if p.is_file() and p.suffix.lower() in {".docx"} and not p.name.startswith("~$")}
    common = sorted(sbs_stems & hts_stems)

    pairs: list[Pair] = []
    for pid in common:
        dec = _choose_best_file(sbs_dir, pid)
        task = _choose_best_file(hts_dir, pid)
        if dec is None or task is None:
            continue
        pairs.append(Pair(project_id=pid, declaration_path=dec, task_path=task))
    return pairs


def _parse_project_ids(raw: str) -> list[str]:
    if not raw:
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for token in str(raw).replace("\n", ",").split(","):
        pid = token.strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)
    return ids


def _risk_counts(result) -> dict:
    levels = {"RED": 0, "YELLOW": 0, "GREEN": 0}
    buckets = [
        getattr(result, "metrics_risks", []) or [],
        getattr(result, "content_risks", []) or [],
        getattr(result, "budget_risks", []) or [],
        getattr(result, "other_risks", []) or [],
        getattr(result, "unit_budget_risks", []) or [],
    ]
    for bucket in buckets:
        for item in bucket:
            lv = str(getattr(item, "risk_level", "") or "").upper()
            if lv in levels:
                levels[lv] += 1
    return levels


async def _run_one(
    *,
    pair: Pair,
    budget_shift_threshold: float,
    strict_mode: bool,
    enable_llm_enhancement: bool,
    enable_table_vision_extraction: bool,
    enable_llm_entailment: bool,
    timeout_seconds: int,
    on_progress: Optional[Callable[[float, str, str], None]] = None,
) -> Tuple[dict, object]:
    service = get_perfcheck_service()
    dec_bytes = pair.declaration_path.read_bytes()
    task_bytes = pair.task_path.read_bytes()
    dec_type = pair.declaration_path.suffix.lower().lstrip(".")
    task_type = pair.task_path.suffix.lower().lstrip(".")
    result = await asyncio.wait_for(
        service.compare_files(
            project_id=pair.project_id,
            declaration_file=dec_bytes,
            declaration_file_type=dec_type,
            task_file=task_bytes,
            task_file_type=task_type,
            budget_shift_threshold=budget_shift_threshold,
            strict_mode=strict_mode,
            enable_llm_enhancement=enable_llm_enhancement,
            enable_table_vision_extraction=enable_table_vision_extraction,
            enable_llm_entailment=enable_llm_entailment,
            on_progress=on_progress,
        ),
        timeout=float(timeout_seconds),
    )
    summary = {
        "project_id": pair.project_id,
        "declaration_file": str(pair.declaration_path),
        "task_file": str(pair.task_path),
        "task_id": getattr(result, "task_id", ""),
        "summary": getattr(result, "summary", ""),
        "risk_counts": _risk_counts(result),
        "warnings": list(getattr(result, "warnings", []) or []),
    }
    return summary, result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbs-dir", default="/mnt/remote_corpus/2025/sbs")
    parser.add_argument("--hts-dir", default="/mnt/remote_corpus/2025/hts")
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2025)
    parser.add_argument("--docx-only", action="store_true", default=True)
    parser.add_argument("--budget-shift-threshold", type=float, default=0.10)
    parser.add_argument("--strict-mode", action="store_true", default=True)
    parser.add_argument("--no-strict-mode", action="store_false", dest="strict_mode")
    parser.add_argument("--enable-llm-enhancement", action="store_true", default=False)
    parser.add_argument("--enable-table-vision-extraction", action="store_true", default=True)
    parser.add_argument("--disable-table-vision-extraction", action="store_false", dest="enable_table_vision_extraction")
    parser.add_argument("--enable-llm-entailment", action="store_true", default=False)
    parser.add_argument("--show-progress", action="store_true", default=True)
    parser.add_argument("--no-show-progress", action="store_false", dest="show_progress")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--output-dir", default="/home/tdkx/ljh/Tech/debug_perfcheck")
    parser.add_argument(
        "--project-ids",
        default="",
        help="仅运行指定项目ID，多个用逗号分隔；设置后将忽略 sample-size/seed 抽样",
    )
    args = parser.parse_args()

    sbs_dir = Path(args.sbs_dir)
    hts_dir = Path(args.hts_dir)
    if not sbs_dir.exists() or not hts_dir.exists():
        raise SystemExit("输入目录不存在")

    pairs = _collect_pairs(sbs_dir, hts_dir)
    if not pairs:
        raise SystemExit("未找到可匹配的申报书/任务书对")

    project_ids = _parse_project_ids(args.project_ids)
    if project_ids:
        pair_by_id = {p.project_id: p for p in pairs}
        selected: list[Pair] = []
        missing_ids: list[str] = []
        for pid in project_ids:
            pair = pair_by_id.get(pid)
            if pair is None:
                missing_ids.append(pid)
                continue
            selected.append(pair)
        if missing_ids:
            print(f"warning: 以下项目ID未在输入目录中找到，已跳过: {', '.join(missing_ids)}", flush=True)
        if not selected:
            raise SystemExit("project-ids 指定的项目均不可用")
    else:
        rnd = random.Random(args.seed)
        sample_size = max(1, min(int(args.sample_size), len(pairs)))
        selected = rnd.sample(pairs, sample_size)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path(args.output_dir) / f"batch_perfcheck_{ts}"
    out_root.mkdir(parents=True, exist_ok=True)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    (Path(args.output_dir) / "LATEST_BATCH.txt").write_text(str(out_root), encoding="utf-8")

    reporter = PerfCheckReporter()
    summaries: list[dict] = []
    failures: list[dict] = []

    total = len(selected)
    for idx, pair in enumerate(selected, start=1):
        progress_state = {"printed": False, "p": 0.0, "stage": ""}

        def _print_progress(progress: float, stage: str, message: str) -> None:
            if not bool(args.show_progress):
                return
            p = float(progress or 0.0)
            st = str(stage or "")
            msg = " ".join(str(message or "").split())
            if st == progress_state["stage"] and (p - float(progress_state["p"])) < 0.03:
                return
            progress_state["p"] = p
            progress_state["stage"] = st
            progress_state["printed"] = True
            percent = max(0, min(100, int(round(p * 100))))
            line = f"[{idx}/{total}] {pair.project_id}  {st} {percent:>3}%  {msg}"
            if len(line) > 140:
                line = line[:140] + "…"
            print("\r" + line.ljust(160), end="", flush=True)

        try:
            summary, result = await _run_one(
                pair=pair,
                budget_shift_threshold=float(args.budget_shift_threshold),
                strict_mode=bool(args.strict_mode),
                enable_llm_enhancement=bool(args.enable_llm_enhancement),
                enable_table_vision_extraction=bool(args.enable_table_vision_extraction),
                enable_llm_entailment=bool(args.enable_llm_entailment),
                timeout_seconds=int(args.timeout_seconds),
                on_progress=_print_progress,
            )
            summaries.append(summary)
            project_dir = out_root / pair.project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "result.json").write_text(result.model_dump_json(ensure_ascii=False, indent=2), encoding="utf-8")
            (project_dir / "report.md").write_text(reporter.build_markdown(result), encoding="utf-8")
            (project_dir / "input.json").write_text(
                json.dumps(
                    {
                        "project_id": pair.project_id,
                        "declaration_file": str(pair.declaration_path),
                        "task_file": str(pair.task_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            if progress_state["printed"]:
                print("\r" + (" " * 160) + "\r", end="", flush=True)
            print(
                f"[{idx}/{total}] {pair.project_id} OK  RED={summary['risk_counts']['RED']} YELLOW={summary['risk_counts']['YELLOW']}",
                flush=True,
            )
        except Exception as e:
            failures.append({"project_id": pair.project_id, "error_type": type(e).__name__, "error": str(e)})
            msg = str(e).strip()
            tip = msg if msg else type(e).__name__
            if progress_state["printed"]:
                print("\r" + (" " * 160) + "\r", end="", flush=True)
            print(f"[{idx}/{total}] {pair.project_id} FAILED  {tip}", flush=True)

    (out_root / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

    total_red = sum(int(s.get("risk_counts", {}).get("RED", 0) or 0) for s in summaries)
    total_yellow = sum(int(s.get("risk_counts", {}).get("YELLOW", 0) or 0) for s in summaries)
    print(f"saved: {out_root}", flush=True)
    print(f"projects: {len(summaries)} ok, {len(failures)} failed  total RED={total_red} YELLOW={total_yellow}", flush=True)
    return 0 if not failures else 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(asyncio.run(main()))
