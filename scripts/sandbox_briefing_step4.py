#!/usr/bin/env python3
"""兼容入口：调用 sandbox 第四步简报编排实现。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.sandbox.briefing_orchestrator_step4 import main


if __name__ == "__main__":
    raise SystemExit(main())
