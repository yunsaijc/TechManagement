#!/usr/bin/env python3
"""查重库管理工具

用法:
    python scripts/manage_corpus.py --action build --path /mnt/remote_corpus/
    python scripts/manage_corpus.py --action status
    python scripts/manage_corpus.py --action refresh --limit 50
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.append(os.getcwd())

from src.services.plagiarism.corpus import CorpusManager


async def build_index(corpus_path: str, index_path: str, limit: int = None):
    """构建索引"""
    print(f"--- 查重库索引构建 ---")
    print(f"目标目录: {corpus_path}")
    print(f"索引路径: {index_path}")

    if not os.path.exists(corpus_path):
        print(f"错误: 目录不存在 {corpus_path}")
        return

    manager = CorpusManager(corpus_path=corpus_path, index_save_path=index_path)

    docx_count = sum(1 for root, _, files in os.walk(corpus_path)
                     for f in files if f.lower().endswith(".docx"))
    print(f"发现 {docx_count} 个 docx 文件")

    if not docx_count:
        print("未发现文件，停止构建")
        return

    print(f"开始扫描{'（限前 ' + str(limit) + ' 个）' if limit else ''}...")
    stats = await manager.scan_and_update(limit=limit)

    print(f"\n完成: {stats}")
    print(f"索引文档数: {len(manager.index.documents)}")


async def show_status(index_path: str):
    """显示索引状态"""
    manager = CorpusManager(index_save_path=index_path)

    print(f"--- 索引状态 ---")
    print(f"索引路径: {index_path}")
    print(f"文档总数: {len(manager.index.documents)}")
    print(f"最后更新: {manager.index.last_updated}")

    if manager.index.documents:
        total_chars = sum(doc.char_count for doc in manager.index.documents.values())
        print(f"总字符数: {total_chars:,}")


async def refresh_index(corpus_path: str, index_path: str, limit: int = None):
    """增量刷新"""
    print(f"--- 增量刷新 ---")
    manager = CorpusManager(corpus_path=corpus_path, index_save_path=index_path)
    stats = await manager.scan_and_update(limit=limit)
    print(f"完成: {stats}")


async def main():
    parser = argparse.ArgumentParser(description="查重库管理工具")
    parser.add_argument("--action", required=True, choices=["build", "status", "refresh"])
    parser.add_argument("--path", default="/mnt/remote_corpus/")
    parser.add_argument("--index", default="data/plagiarism/corpus_index.json")
    parser.add_argument("--limit", type=int, help="限制处理文件数")

    args = parser.parse_args()

    if args.action == "build":
        await build_index(args.path, args.index, args.limit)
    elif args.action == "status":
        await show_status(args.index)
    elif args.action == "refresh":
        await refresh_index(args.path, args.index, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
