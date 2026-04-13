#!/usr/bin/env python3
"""兼容入口：调用 sandbox 服务目录下的 GDS 预检实现。"""

from src.services.sandbox.neo4j_gds_preflight import main


if __name__ == "__main__":
    raise SystemExit(main())
