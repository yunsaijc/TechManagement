#!/usr/bin/env python3
"""一键串行执行 Step3、Step4、Step5。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_cmd(args: list[str]) -> int:
    proc = subprocess.run(args, cwd=PROJECT_ROOT)
    return int(proc.returncode)


def main() -> int:
    venv_py = PROJECT_ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable

    print("[RUN] Step3 宏观研判（默认快速模式）")
    rc3 = run_cmd([py, "scripts/sandbox_macro_insight_step3.py"])
    if rc3 != 0:
        print(f"[ERROR] Step3 失败，退出码={rc3}")
        return rc3

    print("[RUN] Step4 简报编排")
    rc4 = run_cmd([py, "scripts/sandbox_briefing_step4.py"])
    if rc4 != 0:
        print(f"[ERROR] Step4 失败，退出码={rc4}")
        return rc4

    print("[RUN] Step5 GraphRAG")
    rc5 = run_cmd([py, "scripts/sandbox_graph_rag_step5.py"])
    if rc5 != 0:
        print(f"[ERROR] Step5 失败，退出码={rc5}")
        return rc5

    print("[SUCCESS] Step3 + Step4 + Step5 一键跑通")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
