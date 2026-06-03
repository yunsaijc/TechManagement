#!/usr/bin/env python3
"""Random batch test for reward-field plagiarism checks."""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.plagiarism.config import (  # noqa: E402
    PLAGIARISM_REWARD_DICT_CONFIG,
    PLAGIARISM_REWARD_SCOPE_CONFIG,
)
from src.services.plagiarism.reward_corpus import RewardCorpusPlagiarismService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch test by randomly sampled xmbh from reward DB scope"
    )
    parser.add_argument("--dict-type", required=True, choices=sorted(PLAGIARISM_REWARD_DICT_CONFIG.keys()))
    parser.add_argument("--scope", required=True, choices=sorted(PLAGIARISM_REWARD_SCOPE_CONFIG.keys()))
    parser.add_argument("--batch-size", type=int, default=5, help="Random sample count")
    parser.add_argument(
        "--xmbh-prefix",
        default=None,
        help="Only sample xmbh that starts with this prefix, e.g. 2024",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--threshold-high", type=float, default=0.8)
    parser.add_argument("--threshold-medium", type=float, default=0.5)
    parser.add_argument("--max-sources", type=int, default=1000)
    parser.add_argument("--db-name", default="xmsbnew")
    parser.add_argument(
        "--output-dir",
        default="/home/tdkx/ljh/Tech/debug_plagiarism/text",
        help="Directory for batch result and saved command",
    )
    return parser.parse_args()


def _serialize_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    result_obj = raw.get("result")
    if hasattr(result_obj, "model_dump"):
        result_data = result_obj.model_dump()
    elif dataclasses.is_dataclass(result_obj):
        result_data = dataclasses.asdict(result_obj)
    else:
        result_data = result_obj

    return {
        "current_nomination_year": raw.get("current_nomination_year"),
        "scope_total_projects": raw.get("scope_total_projects"),
        "loaded_text_projects": raw.get("loaded_text_projects"),
        "selected_source_docs": raw.get("selected_source_docs", []),
        "corpus_saved_path": raw.get("corpus_saved_path"),
        "html_report_path": raw.get("html_report_path"),
        "result": result_data,
    }


def _build_repro_command(args: argparse.Namespace) -> str:
    cmd = [
        "uv",
        "run",
        "python",
        "scripts/test_reward_random_batch.py",
        "--dict-type",
        args.dict_type,
        "--scope",
        args.scope,
        "--batch-size",
        str(args.batch_size),
        "--threshold-high",
        str(args.threshold_high),
        "--threshold-medium",
        str(args.threshold_medium),
        "--max-sources",
        str(args.max_sources),
        "--db-name",
        args.db_name,
        "--output-dir",
        args.output_dir,
    ]
    if args.xmbh_prefix:
        cmd.extend(["--xmbh-prefix", args.xmbh_prefix])
    if args.seed is not None:
        cmd.extend(["--seed", str(args.seed)])
    return " ".join(shlex.quote(p) for p in cmd)


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size 必须大于 0")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    service = RewardCorpusPlagiarismService(db_name=args.db_name)
    current_nd = service.get_current_nomination_year()
    scope_ids = service.get_scope_project_ids(scope=args.scope, current_nd=current_nd)
    if args.xmbh_prefix:
        scope_ids = [x for x in scope_ids if x.startswith(args.xmbh_prefix)]
    if not scope_ids:
        raise ValueError("指定 scope 下没有可用项目")

    sample_size = min(args.batch_size, len(scope_ids))
    rng = random.Random(args.seed)
    sampled_ids = rng.sample(scope_ids, sample_size)

    run_started = int(time.time())
    run_records: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0

    for index, xmbh in enumerate(sampled_ids, start=1):
        print(f"[{index}/{sample_size}] testing xmbh={xmbh}")
        item_started = time.time()
        try:
            raw_result = service.check_by_scope(
                xmbh=xmbh,
                dict_type=args.dict_type,
                scope=args.scope,
                threshold_high=args.threshold_high,
                threshold_medium=args.threshold_medium,
                max_sources=args.max_sources,
            )
            run_records.append(
                {
                    "xmbh": xmbh,
                    "status": "success",
                    "elapsed_seconds": round(time.time() - item_started, 3),
                    "data": _serialize_result(raw_result),
                }
            )
            ok_count += 1
        except Exception as exc:  # noqa: BLE001
            run_records.append(
                {
                    "xmbh": xmbh,
                    "status": "error",
                    "elapsed_seconds": round(time.time() - item_started, 3),
                    "error": str(exc),
                }
            )
            fail_count += 1
            print(f"  -> failed: {exc}")

    ts = int(time.time())
    result_path = output_dir / f"reward_random_batch_{args.dict_type}_{args.scope}_{ts}.json"
    command_path = output_dir / f"reward_random_batch_{args.dict_type}_{args.scope}_{ts}.sh"

    payload = {
        "meta": {
            "dict_type": args.dict_type,
            "scope": args.scope,
            "batch_size_requested": args.batch_size,
            "batch_size_actual": sample_size,
            "seed": args.seed,
            "threshold_high": args.threshold_high,
            "threshold_medium": args.threshold_medium,
            "max_sources": args.max_sources,
            "db_name": args.db_name,
            "current_nomination_year": current_nd,
            "scope_total_projects": len(scope_ids),
            "xmbh_prefix": args.xmbh_prefix,
            "started_at": run_started,
            "finished_at": int(time.time()),
            "success_count": ok_count,
            "failed_count": fail_count,
        },
        "sampled_xmbh": sampled_ids,
        "records": run_records,
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    command_text = _build_repro_command(args)
    command_path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + command_text + "\n", encoding="utf-8")

    print("\nBatch test finished")
    print(f"- success: {ok_count}")
    print(f"- failed:  {fail_count}")
    print(f"- result:  {result_path}")
    print(f"- rerun:   {command_path}")


if __name__ == "__main__":
    main()
