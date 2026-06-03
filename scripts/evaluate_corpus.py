#!/usr/bin/env python3
"""评估查重库索引质量"""
import json
import os
import sys
from pathlib import Path

sys.path.append(os.getcwd())

from src.services.plagiarism.corpus import CorpusManager


def main():
    index_path = "data/plagiarism/corpus_index.json"

    if not os.path.exists(index_path):
        print(f"错误: 索引文件不存在 {index_path}")
        return

    manager = CorpusManager(index_save_path=index_path)
    docs = manager.index.documents

    print("=== 库索引质量评估 ===\n")

    # 基础统计
    print(f"文档总数: {len(docs)}")
    if not docs:
        return

    total_chars = sum(d.char_count for d in docs.values())
    print(f"总字符数: {total_chars:,}")
    print(f"平均字符数: {total_chars // len(docs):,}\n")

    # 特征统计
    char2_counts = [len(d.features.get("char2", [])) for d in docs.values()]
    char4_counts = [len(d.features.get("char4", [])) for d in docs.values()]
    char8_counts = [len(d.features.get("char8", [])) for d in docs.values()]

    print(f"平均 char2 特征数: {sum(char2_counts) // len(char2_counts):,}")
    print(f"平均 char4 特征数: {sum(char4_counts) // len(char4_counts):,}")
    print(f"平均 char8 特征数: {sum(char8_counts) // len(char8_counts):,}\n")

    # 路径检查
    corpus_path = manager.corpus_path
    missing = []
    for doc_id, doc in docs.items():
        file_path = Path(doc.path)
        if not file_path.is_absolute():
            file_path = corpus_path / doc.path
        if not file_path.exists():
            missing.append(doc_id)

    print(f"路径有效性: {len(docs) - len(missing)}/{len(docs)}")
    if missing:
        print(f"缺失文件数: {len(missing)}")
        print("前 5 个缺失文件:")
        for doc_id in missing[:5]:
            print(f"  - {doc_id}")


if __name__ == "__main__":
    main()
