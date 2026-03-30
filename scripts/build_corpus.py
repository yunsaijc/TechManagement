import asyncio
import os
import sys
from pathlib import Path

# 将项目根目录添加到 python 路径
sys.path.append(os.getcwd())

from src.services.plagiarism.corpus import CorpusManager

async def main():
    """针对指定目录构建查重库索引"""
    corpus_path = "/mnt/remote_corpus/2025/sbs"
    index_path = "data/plagiarism/corpus_index.json"
    
    print(f"--- 查重库索引构建开始 ---")
    print(f"目标目录: {corpus_path}")
    print(f"索引保存路径: {index_path}")
    
    # 检查路径是否存在
    if not os.path.exists(corpus_path):
        print(f"错误: 目录 {corpus_path} 不存在。请确保 NFS 已正确挂载。")
        return

    # 初始化管理器
    manager = CorpusManager(
        corpus_path=corpus_path,
        index_save_path=index_path
    )
    
    # 统计现有文件（仅 docx）
    docx_files = []
    for root, _, files in os.walk(corpus_path):
        for f in files:
            if f.lower().endswith(".docx"):
                docx_files.append(os.path.join(root, f))
    
    print(f"发现待处理的 docx 文件总数: {len(docx_files)}")
    
    if not docx_files:
        print("未发现任何 docx 文件，停止构建。")
        return

    # 扫描并更新索引（限制处理前 100 个文件）
    print("正在扫描文件并并发提取特征（限前 100 个文件）...")
    start_time = asyncio.get_event_loop().time()
    
    stats = await manager.scan_and_update(limit=100)
    
    end_time = asyncio.get_event_loop().time()
    duration = end_time - start_time
    
    print(f"\n--- 构建完成 ---")
    print(f"耗时: {duration:.2f} 秒")
    print(f"统计信息: {stats}")
    print(f"索引库当前总文档数: {len(manager.index.documents)}")
    print(f"索引文件位置: {os.path.abspath(index_path)}")

if __name__ == "__main__":
    asyncio.run(main())
