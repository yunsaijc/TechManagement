#!/usr/bin/env python3
"""奖励库字段文本查重 - 建库管理工具

用法:
    python scripts/manage_reward_corpus.py --action build-batch --dict-type xmjj --scope dn --limit 200
    python scripts/manage_reward_corpus.py --action build --dict-type xmjj --scope lshj --limit 200
    python scripts/manage_reward_corpus.py --action build-all --limit 500
    python scripts/manage_reward_corpus.py --action status
    python scripts/manage_reward_corpus.py --action reset-cursor --dict-type xmjj --scope dn
    python scripts/manage_reward_corpus.py --action reset-dict --dict-type xmjj
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.append(os.getcwd())

from src.services.plagiarism.reward_corpus_manager import RewardCorpusManager


def _print_payload(payload: dict) -> None:
    keys = [
        "dict_type",
        "scope",
        "current_nomination_year",
        "cursor_xmbh",
        "next_cursor_xmbh",
        "requested_ids",
        "loaded_docs",
        "upserted_docs",
        "has_more",
        "updated_at",
        "reason",
    ]
    lines = []
    for key in keys:
        if key in payload:
            lines.append(f"{key}: {payload.get(key)}")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="奖励库字段文本查重 - 建库管理工具")
    parser.add_argument(
        "--action",
        required=True,
        choices=["build-batch", "build", "build-all", "status", "reset-cursor", "reset-dict"],
    )
    parser.add_argument("--db-name", default="xmsbnew")
    parser.add_argument("--dict-type", default="xmjj")
    parser.add_argument("--scope", default="dn")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--cursor-xmbh", default=None)
    parser.add_argument("--reset-cursor", action="store_true")
    parser.add_argument("--reset-all-cursors", action="store_true")

    args = parser.parse_args()
    manager = RewardCorpusManager(db_name=args.db_name)

    if args.action == "status":
        print(f"sqlite_path: {manager.sqlite_path}")
        print(f"index_path: {manager.index_path}")
        print(f"manifest_path: {manager.manifest_path}")
        print(f"checkpoint_path: {manager.checkpoint_path}")
        return

    dict_type = str(args.dict_type or "").strip().lower()
    scope = str(args.scope or "").strip().lower()
    if args.action == "reset-dict":
        if not dict_type:
            raise SystemExit("dict-type 不能为空")
        manager._clear_dict_type(dict_type)
        print(f"已清空 dict_type={dict_type} 在本地 sqlite 中的缓存")
        return

    if args.action == "reset-cursor":
        if not dict_type or not scope:
            raise SystemExit("dict-type / scope 不能为空")
        manager.reset_checkpoint_cursor(dict_type=dict_type, scope=scope)
        print(f"已重置 cursor: dict_type={dict_type}, scope={scope}")
        return

    if args.action == "build-batch":
        payload = manager.build_scope_batch(
            dict_type=dict_type,
            scope=scope,
            limit=int(args.limit),
            cursor_xmbh=args.cursor_xmbh,
            reset_cursor=bool(args.reset_cursor),
        )
        _print_payload(payload)
        return

    if args.action == "build":
        has_more = True
        cursor = args.cursor_xmbh
        reset = bool(args.reset_cursor)
        while has_more:
            payload = manager.build_scope_batch(
                dict_type=dict_type,
                scope=scope,
                limit=int(args.limit),
                cursor_xmbh=cursor,
                reset_cursor=reset,
            )
            _print_payload(payload)
            has_more = bool(payload.get("has_more"))
            cursor = payload.get("next_cursor_xmbh")
            reset = False
        return

    if args.action == "build-all":
        dict_types = ["xmjj", "cxd", "zscq", "jhmc"]
        scopes = ["dn", "lshj"]

        for dict_type_item in dict_types:
            for scope_item in scopes:
                if args.reset_all_cursors:
                    manager.reset_checkpoint_cursor(dict_type=dict_type_item, scope=scope_item)

                print(f"\n=== build: dict_type={dict_type_item}, scope={scope_item} ===")
                has_more = True
                cursor = None
                reset = False
                while has_more:
                    payload = manager.build_scope_batch(
                        dict_type=dict_type_item,
                        scope=scope_item,
                        limit=int(args.limit),
                        cursor_xmbh=cursor,
                        reset_cursor=reset,
                    )
                    _print_payload(payload)
                    has_more = bool(payload.get("has_more"))
                    cursor = payload.get("next_cursor_xmbh")
                    reset = False
        return


if __name__ == "__main__":
    main()
