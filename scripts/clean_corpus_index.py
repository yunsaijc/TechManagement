#!/usr/bin/env python3
"""清理索引中不存在的文件"""
import os
import sys
from pathlib import Path

sys.path.append(os.getcwd())

from src.services.plagiarism.corpus import CorpusManager


def main():
    manager = CorpusManager()

    print(f"索引文档总数: {len(manager.index.documents)}")

    to_remove = []
    for doc_id, doc in manager.index.documents.items():
        file_path = Path(doc.path)
        if not file_path.is_absolute():
            file_path = manager.corpus_path / doc.path

        if not file_path.exists():
            to_remove.append(doc_id)

    print(f"发现 {len(to_remove)} 个文件不存在")

    if to_remove:
        for doc_id in to_remove:
            del manager.index.documents[doc_id]

        manager.save_index()
        print(f"已清理，剩余: {len(manager.index.documents)}")


if __name__ == "__main__":
    main()
