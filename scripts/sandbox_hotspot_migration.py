#!/usr/bin/env python3
"""兼容入口：调用 sandbox 目录下的热点迁移实现。"""

import sys
from pathlib import Path

# 允许通过 `python3 scripts/...` 直接运行。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.sandbox.hotspot_migration_step2 import main


if __name__ == "__main__":
    raise SystemExit(main())
