"""按目录批量执行 LogiCons 逻辑自洽检测。

用法示例:
  python scripts/batch_logicons_from_dirs.py \
    --declaration-dir tests/申报书 \
    --task-dir tests/任务书 \
    --output-dir debug_logicons/batch_runs \
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

from src.common.models.logicons import LogiConsResult
from src.services.logicons import get_logicons_service

SUPPORTED_EXTS = {".docx", ".pdf", ".txt", ".doc"}


def _print(msg: str) -> None:
    print(msg, flush=True)


def _iter_valid_files(folder: Path) -> Iterable[Path]:
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith("~$"):
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        yield p


def _risk_score(result: LogiConsResult) -> int:
    return result.summary.high * 3 + result.summary.medium * 2 + result.summary.low


async def _run_one(
    *,
    source: str,
    project_id: str,
    path: Path,
    budget_tolerance: float,
    timeline_grace_years: int,
    enable_llm: bool,
) -> LogiConsResult:
    service = get_logicons_service()
    file_data = path.read_bytes()

    return await service.check_file(
        project_id=project_id,
        file_data=file_data,
        file_type=path.suffix.lstrip(".").lower(),
        budget_tolerance=budget_tolerance,
        timeline_grace_years=timeline_grace_years,
        enable_llm_enhancement=enable_llm,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Batch logicons by declaration/task dirs")
    parser.add_argument("--declaration-dir", required=True, help="申报书目录")
    parser.add_argument("--task-dir", required=True, help="任务书目录")
    parser.add_argument("--output-dir", default="debug_logicons/batch_runs", help="输出目录")
    parser.add_argument("--budget-tolerance", type=float, default=0.01, help="预算容差比例")
    parser.add_argument("--timeline-grace-years", type=int, default=0, help="时间宽限年数")
    parser.add_argument("--enable-llm", action="store_true", help="启用 LLM 增强")
    parser.add_argument("--max-projects", type=int, default=0, help="最多处理项目数，0 表示全部")
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
    (run_dir / "projects").mkdir(parents=True, exist_ok=True)

    declaration_map = {p.name: p for p in _iter_valid_files(declaration_dir)}
    task_map = {p.name: p for p in _iter_valid_files(task_dir)}

    all_names = sorted(set(declaration_map.keys()) | set(task_map.keys()))
    if args.max_projects and args.max_projects > 0:
        all_names = all_names[: args.max_projects]

    only_decl = sorted(set(declaration_map.keys()) - set(task_map.keys()))
    only_task = sorted(set(task_map.keys()) - set(declaration_map.keys()))
    both_count = len(set(declaration_map.keys()) & set(task_map.keys()))

    summary: dict = {
        "run_at": ts,
        "declaration_dir": str(declaration_dir),
        "task_dir": str(task_dir),
        "output_dir": str(run_dir),
        "budget_tolerance": args.budget_tolerance,
        "timeline_grace_years": args.timeline_grace_years,
        "enable_llm": bool(args.enable_llm),
        "total_projects": len(all_names),
        "both_count": both_count,
        "only_declaration": only_decl,
        "only_task": only_task,
        "projects": [],
        "stats": {
            "ok": 0,
            "error": 0,
            "declaration_processed": 0,
            "task_processed": 0,
            "total_conflicts": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
    }

    _print(f"[batch] 总项目数(并集): {len(all_names)}")
    _print(f"[batch] 两目录同名项目: {both_count}")
    _print(f"[batch] 仅申报书目录存在: {len(only_decl)}")
    _print(f"[batch] 仅任务书目录存在: {len(only_task)}")
    _print(f"[batch] 输出目录: {run_dir}")

    for idx, name in enumerate(all_names, start=1):
        project_id = Path(name).stem
        progress = (idx / len(all_names) * 100.0) if all_names else 100.0
        _print(f"[batch][{idx}/{len(all_names)}][{progress:.1f}%] 开始: {project_id}")

        project_dir = run_dir / "projects" / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        project_summary: dict = {
            "index": idx,
            "project_id": project_id,
            "file_name": name,
            "declaration": None,
            "task": None,
            "error": None,
        }

        try:
            dec_path = declaration_map.get(name)
            if dec_path is not None:
                dec_result = await _run_one(
                    source="declaration",
                    project_id=project_id,
                    path=dec_path,
                    budget_tolerance=args.budget_tolerance,
                    timeline_grace_years=args.timeline_grace_years,
                    enable_llm=bool(args.enable_llm),
                )
                dec_json = dec_result.model_dump(mode="json")
                (project_dir / "declaration.json").write_text(
                    json.dumps(dec_json, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                project_summary["declaration"] = {
                    "source_file": dec_path.name,
                    "check_id": dec_result.check_id,
                    "summary": dec_json["summary"],
                    "warnings": dec_result.warnings,
                    "risk_score": _risk_score(dec_result),
                }
                summary["stats"]["declaration_processed"] += 1
                summary["stats"]["total_conflicts"] += dec_result.summary.total
                summary["stats"]["high"] += dec_result.summary.high
                summary["stats"]["medium"] += dec_result.summary.medium
                summary["stats"]["low"] += dec_result.summary.low

            task_path = task_map.get(name)
            if task_path is not None:
                task_result = await _run_one(
                    source="task",
                    project_id=project_id,
                    path=task_path,
                    budget_tolerance=args.budget_tolerance,
                    timeline_grace_years=args.timeline_grace_years,
                    enable_llm=bool(args.enable_llm),
                )
                task_json = task_result.model_dump(mode="json")
                (project_dir / "task.json").write_text(
                    json.dumps(task_json, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                project_summary["task"] = {
                    "source_file": task_path.name,
                    "check_id": task_result.check_id,
                    "summary": task_json["summary"],
                    "warnings": task_result.warnings,
                    "risk_score": _risk_score(task_result),
                }
                summary["stats"]["task_processed"] += 1
                summary["stats"]["total_conflicts"] += task_result.summary.total
                summary["stats"]["high"] += task_result.summary.high
                summary["stats"]["medium"] += task_result.summary.medium
                summary["stats"]["low"] += task_result.summary.low

            summary["stats"]["ok"] += 1
            summary["projects"].append(project_summary)
            _print(f"[batch] 完成: {project_id} (ok={summary['stats']['ok']}, err={summary['stats']['error']})")
        except Exception as exc:
            project_summary["error"] = str(exc)
            summary["projects"].append(project_summary)
            summary["stats"]["error"] += 1
            _print(f"[batch] 失败: {project_id} error={exc} (ok={summary['stats']['ok']}, err={summary['stats']['error']})")

    summary["projects"].sort(
        key=lambda p: max(
            p.get("declaration", {}).get("risk_score", 0) if isinstance(p.get("declaration"), dict) else 0,
            p.get("task", {}).get("risk_score", 0) if isinstance(p.get("task"), dict) else 0,
        ),
        reverse=True,
    )

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Batch LogiCons Summary ({ts})",
        "",
        f"- 总项目数(并集): {summary['total_projects']}",
        f"- 两目录同名项目: {summary['both_count']}",
        f"- 仅申报书目录存在: {len(summary['only_declaration'])}",
        f"- 仅任务书目录存在: {len(summary['only_task'])}",
        f"- 启用 LLM: {summary['enable_llm']}",
        f"- 处理成功: {summary['stats']['ok']}",
        f"- 处理失败: {summary['stats']['error']}",
        f"- 文档冲突总数: {summary['stats']['total_conflicts']} "
        f"(high={summary['stats']['high']}, medium={summary['stats']['medium']}, low={summary['stats']['low']})",
        "",
        "## 项目明细",
        "",
    ]

    for p in summary["projects"]:
        if p.get("error"):
            lines.append(f"- {p['project_id']}: ERROR - {p['error']}")
            continue

        dec = p.get("declaration")
        task = p.get("task")
        if isinstance(dec, dict):
            dsum = dec["summary"]
            lines.append(
                f"- {p['project_id']} / declaration: total={dsum['total']} "
                f"(high={dsum['high']}, medium={dsum['medium']}, low={dsum['low']})"
            )
        if isinstance(task, dict):
            tsum = task["summary"]
            lines.append(
                f"- {p['project_id']} / task: total={tsum['total']} "
                f"(high={tsum['high']}, medium={tsum['medium']}, low={tsum['low']})"
            )

    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    _print(f"[batch] 全部完成: ok={summary['stats']['ok']}, err={summary['stats']['error']}")
    _print(f"[batch] 汇总文件: {summary_path}")
    _print(str(run_dir))


if __name__ == "__main__":
    asyncio.run(main())
