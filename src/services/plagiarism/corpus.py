"""比对库管理 (Corpus Management)

负责管理远程挂载目录下的查重比对库，包括扫描、预索引构建、特征持久化和原文延迟加载。
"""

import json
import os
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from src.common.file_handler import get_parser
from src.services.plagiarism.retrieval import SourceRetriever
from src.services.plagiarism.text_repairs import repair_extracted_text_artifacts


class CorpusDocument(BaseModel):
    """库文档元数据与特征"""
    doc_id: str
    path: str
    file_hash: str
    char_count: int
    features: Dict[str, List[str]]  # char2, char4, char8 n-grams


class CorpusIndex(BaseModel):
    """库索引数据结构"""
    documents: Dict[str, CorpusDocument] = Field(default_factory=dict)
    last_updated: float = Field(default_factory=time.time)


class CorpusManager:
    """比对库管理器"""

    def __init__(
        self,
        corpus_path: Optional[str] = None,
        index_save_path: str = "data/plagiarism/corpus_index.json",
    ):
        """初始化库管理器

        Args:
            corpus_path: 库文档挂载路径，优先从环境变量 PLAGIARISM_CORPUS_PATH 读取
            index_save_path: 索引持久化路径
        """
        # 优先从环境变量读取，确保环境一致性
        env_path = os.getenv("PLAGIARISM_CORPUS_PATH")
        self.corpus_path = Path(corpus_path or env_path or "/mnt/remote_corpus/2025/sbs")
        self.index_save_path = Path(index_save_path)
        self.index: CorpusIndex = CorpusIndex()
        self.retriever = SourceRetriever()
        
        # 确保索引目录存在
        self.index_save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 加载现有索引
        self.load_index()

    def load_index(self):
        """从磁盘加载索引"""
        if self.index_save_path.exists():
            try:
                with open(self.index_save_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.index = CorpusIndex(**data)
                print(f"[Corpus] 已加载索引: {len(self.index.documents)} 个文档 (路径锁定: {self.corpus_path})")
            except Exception as e:
                print(f"[Corpus] 加载索引失败: {e}")
                self.index = CorpusIndex()
        else:
            self.index = CorpusIndex()

    def save_index(self):
        """将索引保存到磁盘"""
        try:
            with open(self.index_save_path, "w", encoding="utf-8") as f:
                f.write(self.index.model_dump_json(indent=2))
            print(f"[Corpus] 索引已保存到: {self.index_save_path}")
        except Exception as e:
            print(f"[Corpus] 保存索引失败: {e}")

    async def scan_and_update(self, limit: Optional[int] = None) -> Dict[str, int]:
        """扫描挂载目录并增量更新索引

        Args:
            limit: 限制处理的文件数量（用于测试）

        Returns:
            统计信息: {"scanned": int, "new": int, "updated": int, "failed": int}
        """
        import asyncio
        stats = {"scanned": 0, "new": 0, "updated": 0, "failed": 0}
        
        if not self.corpus_path.exists():
            print(f"[Corpus] 错误: 挂载路径不存在 {self.corpus_path}")
            return stats

        # 1. 预选出需要处理的文件（仅 docx）
        to_process = []
        for root, _, files in os.walk(self.corpus_path):
            for filename in files:
                if not filename.lower().endswith(".docx"):
                    continue
                
                stats["scanned"] += 1
                file_path = Path(root) / filename
                # 统一使用相对于 corpus_path 的相对路径作为 ID 和存储路径
                try:
                    doc_id = str(file_path.relative_to(self.corpus_path))
                except ValueError:
                    # 如果不在 corpus_path 下（例如本地测试用例），使用绝对路径
                    doc_id = f"custom_{filename}"

                try:
                    file_hash = self._calculate_hash(file_path)
                    if doc_id in self.index.documents and self.index.documents[doc_id].file_hash == file_hash:
                        continue
                    
                    to_process.append((doc_id, file_path, file_hash))
                    if limit and len(to_process) >= limit:
                        break
                except Exception as e:
                    print(f"[Corpus] 计算哈希失败 {filename}: {e}")
                    stats["failed"] += 1
            
            if limit and len(to_process) >= limit:
                break

        if not to_process:
            print(f"[Corpus] {self.corpus_path} 下没有需要更新的 docx 文件")
            return stats

        print(f"[Corpus] 开始并发处理 {len(to_process)} 个文件...")

        # 2. 并发处理（使用信号量控制并发数，避免 IO 负载过高）
        semaphore = asyncio.Semaphore(10) # 建议控制在 10 个左右，因为涉及远程文件读取

        async def process_task(doc_id, file_path, file_hash):
            async with semaphore:
                try:
                    doc_entry = await self._build_doc_entry(doc_id, file_path, file_hash)
                    if doc_entry:
                        return doc_id, doc_entry
                    return doc_id, None
                except Exception as e:
                    print(f"[Corpus] 异步处理失败 {doc_id}: {e}")
                    return doc_id, None

        tasks = [process_task(did, path, h) for did, path, h in to_process]
        results = await asyncio.gather(*tasks)

        # 3. 更新索引
        for doc_id, doc_entry in results:
            if doc_entry:
                if doc_id in self.index.documents:
                    stats["updated"] += 1
                else:
                    stats["new"] += 1
                self.index.documents[doc_id] = doc_entry
            else:
                stats["failed"] += 1

        if stats["new"] > 0 or stats["updated"] > 0:
            self.index.last_updated = time.time()
            self.save_index()
            
        return stats

    async def get_document_text(self, doc_id: str) -> Optional[str]:
        """延迟加载库文档原文

        Args:
            doc_id: 文档 ID

        Returns:
            文档正文文本
        """
        if doc_id not in self.index.documents:
            print(f"[Corpus] 文档不存在: {doc_id}")
            return None
            
        doc_entry = self.index.documents[doc_id]
        
        # 路径解析策略：
        # 1. 如果是绝对路径，直接尝试
        # 2. 如果是相对路径，相对于当前的 corpus_path
        
        file_path = Path(doc_entry.path)
        if not file_path.is_absolute():
            file_path = self.corpus_path / doc_entry.path
        
        if not file_path.exists():
            print(f"[Corpus] 错误: 无法定位文件物理路径 (当前路径锁定: {self.corpus_path})")
            print(f"[Corpus]   - doc_id: {doc_id}")
            print(f"[Corpus]   - 期望路径: {file_path}")
            return None
            
        try:
            suffix = file_path.suffix.lower()[1:]
            parser = get_parser(suffix)
            with open(file_path, "rb") as f:
                content = f.read()
                result = await parser.parse(content)
                return repair_extracted_text_artifacts(result.content.to_text())
        except Exception as e:
            print(f"[Corpus] 读取文档失败 {doc_id}: {e}")
            return None

    def _calculate_hash(self, file_path: Path) -> str:
        """计算文件 MD5"""
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    async def _build_doc_entry(self, doc_id: str, file_path: Path, file_hash: str) -> Optional[CorpusDocument]:
        """解析文档并提取 N-gram 特征"""
        try:
            suffix = file_path.suffix.lower()[1:]
            parser = get_parser(suffix)
            
            with open(file_path, "rb") as f:
                content = f.read()
                parse_result = await parser.parse(content)
                full_text = repair_extracted_text_artifacts(parse_result.content.to_text())
                
                # 提取特征
                features_raw = self.retriever._build_doc_features(full_text, [])
                
                # 转换为 List 以便 JSON 序列化
                features_json = {
                    k: list(v) for k, v in features_raw.items()
                }
                
                # 存储相对路径（如果在 corpus_path 下），否则存储绝对路径
                try:
                    rel_path = str(file_path.relative_to(self.corpus_path))
                except ValueError:
                    rel_path = str(file_path.absolute())

                return CorpusDocument(
                    doc_id=doc_id,
                    path=rel_path,
                    file_hash=file_hash,
                    char_count=len(full_text),
                    features=features_json
                )
        except Exception as e:
            print(f"[Corpus] 构建索引项失败 {doc_id}: {e}")
            return None
