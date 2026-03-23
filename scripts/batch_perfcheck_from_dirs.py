"""按同名文件配对批量执行 PerfCheck 核验。

用法:
  python scripts/batch_perfcheck_from_dirs.py \
    --declaration-dir tests/申报书 \
    --task-dir tests/任务书 \
    --output-dir debug_pefcheck/batch_runs \
    --enable-llm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

# 允许通过 `python scripts/xxx.py` 直接运行时导入 src 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models.perfcheck import PerfCheckResult
from src.services.perfcheck import get_perfcheck_service
from src.services.perfcheck.reporter import PerfCheckReporter


def _print(msg: str) -> None:
    print(msg, flush=True)


def _iter_valid_files(folder: Path) -> Iterable[Path]:
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith("~$"):
            continue
        if p.suffix.lower() not in {".docx", ".pdf", ".txt", ".doc"}:
            continue
        yield p


def _risk_order(v: str) -> int:
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    return order.get(v, 0)


async def _run_one(
    *,
    project_id: str,
    declaration_path: Path,
    task_path: Path,
    strict_mode: bool,
    budget_shift_threshold: float,
    enable_llm: bool,
) -> PerfCheckResult:
    service = get_perfcheck_service()
    dec_bytes = declaration_path.read_bytes()
    task_bytes = task_path.read_bytes()

    return await service.compare_files(
        project_id=project_id,
        declaration_file=dec_bytes,
        declaration_file_type=declaration_path.suffix.lstrip(".").lower(),
        task_file=task_bytes,
        task_file_type=task_path.suffix.lstrip(".").lower(),
        strict_mode=strict_mode,
        budget_shift_threshold=budget_shift_threshold,
        enable_llm_enhancement=enable_llm,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Batch perfcheck by same filename")
    parser.add_argument("--declaration-dir", required=True, help="申报书目录")
    parser.add_argument("--task-dir", required=True, help="任务书目录")
    parser.add_argument("--output-dir", default="debug_pefcheck/batch_runs", help="输出目录")
    parser.add_argument("--strict-mode", action="store_true", default=True, help="是否严格模式")
    parser.add_argument("--budget-shift-threshold", type=float, default=0.15, help="预算阈值")
    parser.add_argument("--enable-llm", action="store_true", help="启用 LLM 增强")
    args = parser.parse_args()

    declaration_dir = Path(args.declaration_dir)
    task_dir = Path(args.task_dir)
    output_dir = Path(args.output_dir)

    if not declaration_dir.exists() or not declaration_dir.is_dir():
        raise SystemExit(f"申报书目录不存在: {declaration_dir}")
    if not task_dir.exists() or not task_dir.is_dir():
        raise SystemExit(f"任务书目录不存在: {task_dir}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    declaration_map = {p.name: p for p in _iter_valid_files(declaration_dir)}
    task_map = {p.name: p for p in _iter_valid_files(task_dir)}

    common_names = sorted(set(declaration_map.keys()) & set(task_map.keys()))
    only_decl = sorted(set(declaration_map.keys()) - set(task_map.keys()))
    only_task = sorted(set(task_map.keys()) - set(declaration_map.keys()))

    reporter = PerfCheckReporter()

    summary: dict = {
        "run_at": ts,
        "declaration_dir": str(declaration_dir),
        "task_dir": str(task_dir),
        "output_dir": str(run_dir),
        "strict_mode": args.strict_mode,
        "budget_shift_threshold": args.budget_shift_threshold,
        "enable_llm": bool(args.enable_llm),
        "paired_count": len(common_names),
        "only_declaration": only_decl,
        "only_task": only_task,
        "projects": [],
    }

    total = len(common_names)
    ok_count = 0
    err_count = 0
    _print(f"[batch] 配对项目: {total}")
    _print(f"[batch] 仅申报书目录存在: {len(only_decl)}")
    _print(f"[batch] 仅任务书目录存在: {len(only_task)}")
    _print(f"[batch] 输出目录: {run_dir}")

    for idx, name in enumerate(common_names, start=1):
        project_id = Path(name).stem
        dec_path = declaration_map[name]
        task_path = task_map[name]
        progress = (idx / total * 100.0) if total else 100.0
        _print(f"[batch][{idx}/{total}][{progress:.1f}%] 开始: {project_id}")

        try:
            result = await _run_one(
                project_id=project_id,
                declaration_path=dec_path,
                task_path=task_path,
                strict_mode=args.strict_mode,
                budget_shift_threshold=args.budget_shift_threshold,
                enable_llm=bool(args.enable_llm),
            )
            result_json = result.model_dump(mode="json")
            result_md = reporter.build_markdown(result)

            (run_dir / f"{project_id}.json").write_text(
                json.dumps(result_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / f"{project_id}.md").write_text(result_md, encoding="utf-8")

            project_summary = {
                "index": idx,
                "project_id": project_id,
                "file_name": name,
                "overall_risk": result.summary.overall_risk.value,
                "critical": result.summary.critical_count,
                "high": result.summary.high_count,
                "medium": result.summary.medium_count,
                "low": result.summary.low_count,
                "finding_count": len(result.findings),
                "has_goal_warning": any(f.rule_id == "R-GOAL-001" for f in result.findings),
                "has_budget_warning": any(f.rule_id.startswith("R-BUD-") for f in result.findings),
                "has_indicator_warning": any(f.rule_id.startswith("R-IND-") for f in result.findings),
                "has_research_warning": any(f.rule_id.startswith("R-RSCH-") for f in result.findings),
            }
            summary["projects"].append(project_summary)
            ok_count += 1
            _print(
                "[batch] 完成: "
                f"{project_id} risk={project_summary['overall_risk']} "
                f"findings={project_summary['finding_count']} "
                f"(ok={ok_count}, err={err_count})"
            )
        except Exception as exc:
            summary["projects"].append(
                {
                    "index": idx,
                    "project_id": project_id,
                    "file_name": name,
                    "error": str(exc),
                }
            )
            err_count += 1
            _print(f"[batch] 失败: {project_id} error={exc} (ok={ok_count}, err={err_count})")

    summary["projects"].sort(
        key=lambda x: _risk_order(x.get("overall_risk", "")),
        reverse=True,
    )

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Batch PerfCheck Summary ({ts})",
        "",
        f"- 配对项目数: {len(common_names)}",
        f"- 仅申报书目录存在: {len(only_decl)}",
        f"- 仅任务书目录存在: {len(only_task)}",
        f"- 启用 LLM: {bool(args.enable_llm)}",
        "",
        "## 项目结果",
        "",
    ]
    for p in summary["projects"]:
        if "error" in p:
            lines.append(f"- {p['project_id']}: ERROR - {p['error']}")
            continue
        lines.append(
            "- "
            f"{p['project_id']}: risk={p['overall_risk']}, "
            f"findings={p['finding_count']} "
            f"(critical={p['critical']}, high={p['high']}, medium={p['medium']}, low={p['low']})"
        )

    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    _print(f"[batch] 全部完成: total={total}, ok={ok_count}, err={err_count}")
    _print(f"[batch] 汇总文件: {summary_path}")
    _print(str(run_dir))


if __name__ == "__main__":
    asyncio.run(main())
