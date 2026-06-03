#!/usr/bin/env python3
"""Build reusable local ingest index from reward DB text fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.plagiarism.config import (
    PLAGIARISM_REWARD_DICT_CONFIG,
    PLAGIARISM_REWARD_SCOPE_CONFIG,
)
from src.services.plagiarism.reward_corpus_manager import RewardCorpusManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build reward-field plagiarism corpus index")
    parser.add_argument("--dict-type", required=True, choices=sorted(PLAGIARISM_REWARD_DICT_CONFIG.keys()))
    parser.add_argument("--scope", required=True, choices=sorted(PLAGIARISM_REWARD_SCOPE_CONFIG.keys()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reset", action="store_true", help="Clear dict_type documents before rebuilding")
    parser.add_argument("--db-name", default="xmsbnew")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manager = RewardCorpusManager(db_name=args.db_name)
    result = manager.build_scope_index(
        dict_type=args.dict_type,
        scope=args.scope,
        limit=args.limit,
        reset=args.reset,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
