"""比对库管理 (Corpus Management).

负责管理远程挂载目录下的查重比对库，包括扫描、增量索引构建、
特征分片持久化和原文延迟加载。
"""

import hashlib
import json
import os
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from src.common.file_handler import get_parser
from src.services.plagiarism.retrieval import SourceRetriever
from src.services.plagiarism.text_repairs import repair_extracted_text_artifacts


class CorpusDocument(BaseModel):
    """库文档元数据与召回特征。"""

    doc_id: str
    path: str
    file_hash: str
    char_count: int
    file_size: int = 0
    file_mtime: float = 0.0
    shard_id: str = "00"
    features: Optional[Dict[str, List[str]]] = None


class CorpusIndex(BaseModel):
    """库索引清单。

    `documents` 只保存元数据，不再把全部特征直接塞进一个大 JSON。
    """

    documents: Dict[str, CorpusDocument] = Field(default_factory=dict)
    last_updated: float = Field(default_factory=time.time)
    shard_count: int = 16
    format_version: int = 2


class CorpusManager:
    """比对库管理器。"""

    def __init__(
        self,
        corpus_path: Optional[str] = None,
        index_save_path: str = "data/plagiarism/corpus_index.json",
        shard_count: int = 16,
    ):
        env_path = os.getenv("PLAGIARISM_CORPUS_PATH")
        self.corpus_path = Path(corpus_path or env_path or "/mnt/remote_corpus/2025/sbs")
        self.index_save_path = Path(index_save_path)
        self.shard_dir = self.index_save_path.with_suffix("")
        self.shard_dir = self.shard_dir.parent / f"{self.shard_dir.name}_shards"
        self.shard_count = max(1, shard_count)
        self.index: CorpusIndex = CorpusIndex(shard_count=self.shard_count)
        self.retriever = SourceRetriever()
        self._feature_cache: Dict[str, Dict[str, Dict[str, List[str]]]] = {}

        self.index_save_path.parent.mkdir(parents=True, exist_ok=True)
        self.shard_dir.mkdir(parents=True, exist_ok=True)
        self.load_index()

    def load_index(self):
        """从磁盘加载索引清单。兼容旧版单文件结构。"""
        if not self.index_save_path.exists():
            self.index = CorpusIndex(shard_count=self.shard_count)
            return

        try:
            with open(self.index_save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[Corpus] 加载索引失败: {e}")
            self.index = CorpusIndex(shard_count=self.shard_count)
            return

        # 兼容旧版：documents 里直接带 features
        documents = {}
        loaded_shards = int(data.get("shard_count") or self.shard_count)
        for doc_id, raw in (data.get("documents") or {}).items():
            doc = CorpusDocument(**raw)
            if doc.features:
                shard_id = doc.shard_id or self._shard_id_for_doc(doc_id)
                shard_features = self._load_shard_features(shard_id)
                shard_features[doc_id] = doc.features
                self._save_shard_features(shard_id)
                doc.features = None
                doc.shard_id = shard_id
            documents[doc_id] = doc

        self.index = CorpusIndex(
            documents=documents,
            last_updated=float(data.get("last_updated") or time.time()),
            shard_count=loaded_shards,
            format_version=int(data.get("format_version") or 2),
        )
        self.shard_count = self.index.shard_count
        print(f"[Corpus] 已加载索引: {len(self.index.documents)} 个文档 (路径锁定: {self.corpus_path})")

    def save_index(self):
        """将索引清单保存到磁盘。"""
        try:
            self._write_json_atomic(self.index_save_path, self.index.model_dump(mode="json"))
            print(f"[Corpus] 索引已保存到: {self.index_save_path}")
        except Exception as e:
            print(f"[Corpus] 保存索引失败: {e}")

    async def scan_and_update(self, limit: Optional[int] = None) -> Dict[str, int]:
        """扫描挂载目录并增量更新索引。"""
        import asyncio

        stats = {"scanned": 0, "new": 0, "updated": 0, "deleted": 0, "failed": 0, "unchanged": 0}
        if not self.corpus_path.exists():
            print(f"[Corpus] 错误: 挂载路径不存在 {self.corpus_path}")
            return stats

        seen_doc_ids = set()
        to_process: List[Tuple[str, Path, int, float]] = []

        for root, _, files in os.walk(self.corpus_path):
            for filename in files:
                if not filename.lower().endswith(".docx"):
                    continue

                stats["scanned"] += 1
                file_path = Path(root) / filename
                doc_id = self._doc_id_for_path(file_path)
                seen_doc_ids.add(doc_id)

                try:
                    stat = file_path.stat()
                except OSError as e:
                    print(f"[Corpus] 读取文件状态失败 {filename}: {e}")
                    stats["failed"] += 1
                    continue

                file_size = int(stat.st_size)
                file_mtime = float(stat.st_mtime)
                existing = self.index.documents.get(doc_id)
                if (
                    existing
                    and existing.file_size == file_size
                    and abs(existing.file_mtime - file_mtime) < 1e-6
                ):
                    stats["unchanged"] += 1
                    continue

                to_process.append((doc_id, file_path, file_size, file_mtime))
                if limit and len(to_process) >= limit:
                    break
            if limit and len(to_process) >= limit:
                break

        # 删除已经不在磁盘上的文档
        removed_doc_ids = [doc_id for doc_id in self.index.documents.keys() if doc_id not in seen_doc_ids]
        if removed_doc_ids:
            for doc_id in removed_doc_ids:
                self._remove_document(doc_id)
            stats["deleted"] = len(removed_doc_ids)

        if not to_process and not removed_doc_ids:
            print(f"[Corpus] {self.corpus_path} 下没有需要更新的 docx 文件")
            return stats

        if to_process:
            total_to_process = len(to_process)
            batch_size = 200
            max_concurrency = 6
            processed_count = 0
            started_at = time.time()
            print(
                f"[Corpus] 开始并发处理 {total_to_process} 个文件..."
                f" (batch_size={batch_size}, concurrency={max_concurrency})"
            )

            async def process_task(doc_id: str, file_path: Path, file_size: int, file_mtime: float):
                try:
                    file_hash = self._calculate_hash(file_path)
                    existing = self.index.documents.get(doc_id)
                    if existing and existing.file_hash == file_hash:
                        existing.file_size = file_size
                        existing.file_mtime = file_mtime
                        return doc_id, None, "unchanged"

                    doc_entry = await self._build_doc_entry(doc_id, file_path, file_hash, file_size, file_mtime)
                    if doc_entry:
                        return doc_id, doc_entry, "updated" if existing else "new"
                    return doc_id, None, "failed"
                except Exception as e:
                    print(f"[Corpus] 异步处理失败 {doc_id}: {e}")
                    return doc_id, None, "failed"

            for batch_index, batch in enumerate(self._iter_batches(to_process, batch_size), start=1):
                batch_started_at = time.time()
                semaphore = asyncio.Semaphore(max_concurrency)

                async def wrapped_process(item: Tuple[str, Path, int, float]):
                    async with semaphore:
                        return await process_task(*item)

                results = await asyncio.gather(*(wrapped_process(item) for item in batch))

                dirty_shards = set()
                batch_changed = False
                for doc_id, doc_entry, outcome in results:
                    if outcome == "new":
                        stats["new"] += 1
                        batch_changed = True
                    elif outcome == "updated":
                        stats["updated"] += 1
                        batch_changed = True
                    elif outcome == "unchanged":
                        stats["unchanged"] += 1
                    else:
                        stats["failed"] += 1

                    if not doc_entry:
                        continue

                    dirty_shards.add(doc_entry.shard_id)
                    self.index.documents[doc_id] = doc_entry.model_copy(update={"features": None})
                    shard_features = self._load_shard_features(doc_entry.shard_id)
                    shard_features[doc_id] = doc_entry.features or {}

                for shard_id in dirty_shards:
                    self._save_shard_features(shard_id)

                processed_count += len(batch)
                if batch_changed:
                    self.index.last_updated = time.time()
                    self.save_index()

                elapsed = time.time() - started_at
                avg_per_file = elapsed / processed_count if processed_count else 0.0
                remaining = max(total_to_process - processed_count, 0)
                eta_seconds = int(avg_per_file * remaining) if avg_per_file > 0 else 0
                print(
                    "[Corpus] 进度 "
                    f"{processed_count}/{total_to_process} "
                    f"({processed_count / total_to_process:.1%}), "
                    f"batch={batch_index}, "
                    f"batch耗时={time.time() - batch_started_at:.2f}s, "
                    f"累计耗时={elapsed:.2f}s, "
                    f"ETA≈{eta_seconds}s, "
                    f"new={stats['new']}, updated={stats['updated']}, "
                    f"unchanged={stats['unchanged']}, failed={stats['failed']}"
                )

        if any(stats[key] > 0 for key in ("new", "updated", "deleted")):
            self.index.last_updated = time.time()
            self.save_index()

        return stats

    async def get_document_text(self, doc_id: str) -> Optional[str]:
        """延迟加载库文档原文。"""
        doc_entry = self.index.documents.get(doc_id)
        if not doc_entry:
            print(f"[Corpus] 文档不存在: {doc_id}")
            return None

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

    def get_retrieval_documents(self, doc_ids: Optional[List[str]] = None) -> Dict[str, CorpusDocument]:
        """返回带 features 的文档视图，用于召回层。"""
        target_ids = doc_ids or list(self.index.documents.keys())
        grouped_doc_ids = defaultdict(list)
        for doc_id in target_ids:
            doc = self.index.documents.get(doc_id)
            if not doc:
                continue
            grouped_doc_ids[doc.shard_id or self._shard_id_for_doc(doc_id)].append(doc_id)

        docs_with_features: Dict[str, CorpusDocument] = {}
        for shard_id, shard_doc_ids in grouped_doc_ids.items():
            shard_features = self._load_shard_features(shard_id)
            for doc_id in shard_doc_ids:
                doc = self.index.documents.get(doc_id)
                if not doc:
                    continue
                docs_with_features[doc_id] = doc.model_copy(
                    update={"features": shard_features.get(doc_id, {})}
                )
        return docs_with_features

    def _calculate_hash(self, file_path: Path) -> str:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    async def _build_doc_entry(
        self,
        doc_id: str,
        file_path: Path,
        file_hash: str,
        file_size: int,
        file_mtime: float,
    ) -> Optional[CorpusDocument]:
        try:
            suffix = file_path.suffix.lower()[1:]
            parser = get_parser(suffix)
            with open(file_path, "rb") as f:
                content = f.read()
            parse_result = await parser.parse(content)
            full_text = repair_extracted_text_artifacts(parse_result.content.to_text())
            features_raw = self.retriever._build_doc_features(full_text, [])
            features_json = {key: sorted(value) for key, value in features_raw.items()}
            rel_path = self._relative_or_absolute_path(file_path)
            shard_id = self._shard_id_for_doc(doc_id)
            return CorpusDocument(
                doc_id=doc_id,
                path=rel_path,
                file_hash=file_hash,
                char_count=len(full_text),
                file_size=file_size,
                file_mtime=file_mtime,
                shard_id=shard_id,
                features=features_json,
            )
        except Exception as e:
            print(f"[Corpus] 构建索引项失败 {doc_id}: {e}")
            return None

    def _doc_id_for_path(self, file_path: Path) -> str:
        try:
            return str(file_path.relative_to(self.corpus_path))
        except ValueError:
            return f"custom_{file_path.name}"

    def _relative_or_absolute_path(self, file_path: Path) -> str:
        try:
            return str(file_path.relative_to(self.corpus_path))
        except ValueError:
            return str(file_path.absolute())

    def _shard_id_for_doc(self, doc_id: str) -> str:
        digest = hashlib.md5(doc_id.encode("utf-8")).hexdigest()
        shard_num = int(digest[:4], 16) % self.shard_count
        return f"{shard_num:02d}"

    def _shard_path(self, shard_id: str) -> Path:
        return self.shard_dir / f"{shard_id}.json"

    def _load_shard_features(self, shard_id: str) -> Dict[str, Dict[str, List[str]]]:
        if shard_id in self._feature_cache:
            return self._feature_cache[shard_id]

        shard_path = self._shard_path(shard_id)
        if not shard_path.exists():
            self._feature_cache[shard_id] = {}
            return self._feature_cache[shard_id]

        try:
            with open(shard_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._feature_cache[shard_id] = data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[Corpus] 加载分片失败 {shard_path}: {e}")
            self._feature_cache[shard_id] = {}
        return self._feature_cache[shard_id]

    def _save_shard_features(self, shard_id: str) -> None:
        shard_path = self._shard_path(shard_id)
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(shard_path, self._feature_cache.get(shard_id, {}))

    def _remove_document(self, doc_id: str) -> None:
        doc = self.index.documents.pop(doc_id, None)
        if not doc:
            return
        shard_id = doc.shard_id or self._shard_id_for_doc(doc_id)
        shard_features = self._load_shard_features(shard_id)
        if doc_id in shard_features:
            del shard_features[doc_id]
            self._save_shard_features(shard_id)

    def _iter_batches(self, items: List[Tuple[str, Path, int, float]], batch_size: int):
        iterator = iter(items)
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break
            yield batch

    def _write_json_atomic(self, target_path: Path, data: object) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f"{target_path.name}.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target_path)
