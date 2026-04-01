"""比对库管理 (Corpus Management).

负责管理远程挂载目录下的查重比对库，包括扫描、增量索引构建、
特征分片持久化和原文延迟加载。
"""

import hashlib
import json
import os
import resource
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

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
        self.inverted_dir = self.index_save_path.parent / "corpus_char4_inverted"
        self.shard_count = max(1, shard_count)
        self.index: CorpusIndex = CorpusIndex(shard_count=self.shard_count)
        self.retriever = SourceRetriever()
        self._feature_cache: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
        self._inverted_cache: Dict[str, Dict[str, List[str]]] = {}
        self._inverted_shard_count = 64

        self.index_save_path.parent.mkdir(parents=True, exist_ok=True)
        self.shard_dir.mkdir(parents=True, exist_ok=True)
        self.inverted_dir.mkdir(parents=True, exist_ok=True)
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
        
        return await self.scan_and_update_with_options(limit=limit)

    async def scan_and_update_with_options(
        self,
        limit: Optional[int] = None,
        batch_size: int = 100,
        max_concurrency: int = 2,
        save_every_batches: int = 5,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Dict[str, int]:
        """扫描挂载目录并增量更新索引。"""
        import asyncio

        stats = {"scanned": 0, "new": 0, "updated": 0, "deleted": 0, "failed": 0, "unchanged": 0}
        if not self.corpus_path.exists():
            print(f"[Corpus] 错误: 挂载路径不存在 {self.corpus_path}")
            return stats

        batch_size = max(1, int(batch_size))
        max_concurrency = max(1, int(max_concurrency))
        save_every_batches = max(1, int(save_every_batches))

        if self.index.documents and not self.has_inverted_index():
            print("[Corpus] char4 倒排索引缺失，开始一次性重建...")
            self.rebuild_inverted_index(progress_callback=progress_callback)

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
                dirty_shards = set()
                batch_changed = False

                async def wrapped_process(item: Tuple[str, Path, int, float]):
                    async with semaphore:
                        return await process_task(*item)

                tasks = [asyncio.create_task(wrapped_process(item)) for item in batch]
                for completed in asyncio.as_completed(tasks):
                    doc_id, doc_entry, outcome = await completed
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

                    processed_so_far = processed_count + sum(
                        1 for task in tasks if task.done()
                    )
                    if progress_callback:
                        elapsed_now = time.time() - started_at
                        avg_per_file_now = elapsed_now / processed_so_far if processed_so_far else 0.0
                        remaining_now = max(total_to_process - processed_so_far, 0)
                        progress_callback(
                            {
                                "processed": processed_so_far,
                                "total": total_to_process,
                                "batch_index": batch_index,
                                "batch_size": len(batch),
                                "elapsed_seconds": round(elapsed_now, 2),
                                "eta_seconds": int(avg_per_file_now * remaining_now) if avg_per_file_now > 0 else 0,
                                "stats": dict(stats),
                            }
                        )

                    if not doc_entry:
                        continue

                    self._remove_doc_from_inverted(doc_id)
                    dirty_shards.add(doc_entry.shard_id)
                    self.index.documents[doc_id] = doc_entry.model_copy(update={"features": None})
                    shard_features = self._load_shard_features(doc_entry.shard_id)
                    shard_features[doc_id] = doc_entry.features or {}
                    self._add_doc_to_inverted(doc_id, doc_entry.features or {})

                for shard_id in dirty_shards:
                    self._save_shard_features(shard_id)

                processed_count += len(batch)
                if batch_changed and batch_index % save_every_batches == 0:
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
                if progress_callback:
                    progress_callback(
                        {
                            "processed": processed_count,
                            "total": total_to_process,
                            "batch_index": batch_index,
                            "batch_size": len(batch),
                            "elapsed_seconds": round(elapsed, 2),
                            "eta_seconds": eta_seconds,
                            "stats": dict(stats),
                        }
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
            shard_features = self._load_shard_features(shard_id, cache=False)
            for doc_id in shard_doc_ids:
                doc = self.index.documents.get(doc_id)
                if not doc:
                    continue
                docs_with_features[doc_id] = doc.model_copy(
                    update={"features": shard_features.get(doc_id, {})}
                )
            del shard_features
        return docs_with_features

    def retrieve_candidate_doc_ids(
        self,
        primary_text: str,
        primary_excluded_ranges,
        top_k: int = 32,
        min_hits: int = 8,
        max_postings_per_gram: int = 80,
        max_query_grams: int = 1200,
    ) -> List[str]:
        """基于 char4 倒排索引做粗召回，仅返回候选 doc_id。"""
        windows = self.retriever._build_primary_windows(primary_text, primary_excluded_ranges or [])
        if not windows:
            return []

        print(f"[Corpus] 粗召回开始: windows={len(windows)}, rss={self._rss_mb():.1f}MB")
        doc_scores: Dict[str, float] = defaultdict(float)
        doc_gram_hits: Dict[str, int] = defaultdict(int)
        unique_query_grams: Set[str] = set()
        for window in windows:
            unique_query_grams.update(window.get("char4", set()))

        if len(unique_query_grams) > max_query_grams:
            unique_query_grams = set(list(unique_query_grams)[:max_query_grams])

        grams_by_shard: Dict[str, List[str]] = defaultdict(list)
        for gram in unique_query_grams:
            grams_by_shard[self._inverted_shard_id_for_gram(gram)].append(gram)

        skipped_high_df = 0
        for shard_id, grams in grams_by_shard.items():
            shard = self._load_inverted_shard(shard_id, cache=False)
            for gram in grams:
                postings = shard.get(gram, [])
                if not postings:
                    continue
                if len(postings) > max_postings_per_gram:
                    skipped_high_df += 1
                    continue
                idf = 1.0 / max(len(postings), 1)
                for doc_id in postings:
                    doc_scores[doc_id] += idf
                    doc_gram_hits[doc_id] += 1
            del shard

        if not doc_scores:
            print(
                f"[Corpus] 粗召回结束: candidates=0, query_grams={len(unique_query_grams)}, "
                f"skipped_high_df={skipped_high_df}, rss={self._rss_mb():.1f}MB"
            )
            return []

        ranked = []
        for doc_id, score in doc_scores.items():
            gram_hits = doc_gram_hits.get(doc_id, 0)
            if gram_hits < min_hits:
                continue
            ranked.append((doc_id, score, gram_hits))

        ranked.sort(key=lambda item: (-item[1], -item[2], item[0]))
        selected = [doc_id for doc_id, _, _ in ranked[:top_k]]
        print(
            f"[Corpus] 粗召回结束: candidates={len(selected)}, query_grams={len(unique_query_grams)}, "
            f"scored_docs={len(doc_scores)}, skipped_high_df={skipped_high_df}, rss={self._rss_mb():.1f}MB"
        )
        return selected

    def has_inverted_index(self) -> bool:
        return any(self.inverted_dir.glob("*.json"))

    def rebuild_inverted_index(self, progress_callback: Optional[Callable[[dict], None]] = None) -> None:
        self._inverted_cache = {}
        for path in self.inverted_dir.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass

        grouped_doc_ids = defaultdict(list)
        for doc_id, doc in self.index.documents.items():
            grouped_doc_ids[doc.shard_id or self._shard_id_for_doc(doc_id)].append(doc_id)

        total_docs = len(self.index.documents)
        processed_docs = 0
        started_at = time.time()
        print(f"[Corpus] 倒排重建开始: {total_docs} 个文档, feature_shards={len(grouped_doc_ids)}")

        for feature_shard_id, doc_ids in grouped_doc_ids.items():
            shard_started_at = time.time()
            print(
                f"[Corpus] 倒排重建: 读取 feature shard {feature_shard_id}, "
                f"docs={len(doc_ids)}, done={processed_docs}/{total_docs}"
            )
            shard_features = self._load_shard_features(feature_shard_id)
            for doc_id in doc_ids:
                features = shard_features.get(doc_id, {})
                for gram in features.get("char4", []) or []:
                    inv_shard_id = self._inverted_shard_id_for_gram(gram)
                    inv_shard = self._load_inverted_shard(inv_shard_id)
                    postings = inv_shard.setdefault(gram, [])
                    if doc_id not in postings:
                        postings.append(doc_id)
                processed_docs += 1
                if progress_callback and (
                    processed_docs <= 1
                    or processed_docs % 100 == 0
                    or processed_docs >= total_docs
                ):
                    elapsed = time.time() - started_at
                    avg_per_doc = elapsed / processed_docs if processed_docs else 0.0
                    remaining = max(total_docs - processed_docs, 0)
                    progress_callback(
                        {
                            "stage": "rebuild_inverted_index",
                            "processed": processed_docs,
                            "total": total_docs,
                            "feature_shard_id": feature_shard_id,
                            "elapsed_seconds": round(elapsed, 2),
                            "eta_seconds": int(avg_per_doc * remaining) if avg_per_doc > 0 else 0,
                            "stats": {
                                "documents": total_docs,
                                "inverted_shards_loaded": len(self._inverted_cache),
                            },
                        }
                    )
            print(
                f"[Corpus] 倒排重建: 完成 feature shard {feature_shard_id}, "
                f"耗时={time.time() - shard_started_at:.2f}s, "
                f"累计={processed_docs}/{total_docs}"
            )

        print(f"[Corpus] 倒排重建: 开始写回 {len(self._inverted_cache)} 个倒排分片")
        for shard_id in list(self._inverted_cache.keys()):
            self._save_inverted_shard(shard_id)
        elapsed_total = time.time() - started_at
        print(
            f"[Corpus] 倒排重建完成: docs={processed_docs}, "
            f"inverted_shards={len(self._inverted_cache)}, 耗时={elapsed_total:.2f}s"
        )
        if progress_callback:
            progress_callback(
                {
                    "stage": "rebuild_inverted_index_done",
                    "processed": processed_docs,
                    "total": total_docs,
                    "elapsed_seconds": round(elapsed_total, 2),
                    "eta_seconds": 0,
                    "stats": {
                        "documents": total_docs,
                        "inverted_shards_loaded": len(self._inverted_cache),
                    },
                }
            )

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

    def _load_shard_features(self, shard_id: str, cache: bool = True) -> Dict[str, Dict[str, List[str]]]:
        if cache and shard_id in self._feature_cache:
            return self._feature_cache[shard_id]

        shard_path = self._shard_path(shard_id)
        if not shard_path.exists():
            if cache:
                self._feature_cache[shard_id] = {}
                return self._feature_cache[shard_id]
            return {}

        try:
            with open(shard_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            shard_data = data if isinstance(data, dict) else {}
            if cache:
                self._feature_cache[shard_id] = shard_data
                return self._feature_cache[shard_id]
            return shard_data
        except Exception as e:
            print(f"[Corpus] 加载分片失败 {shard_path}: {e}")
            if cache:
                self._feature_cache[shard_id] = {}
                return self._feature_cache[shard_id]
            return {}

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
        self._remove_doc_from_inverted(doc_id)

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

    def _get_doc_features(self, doc_id: str) -> Dict[str, List[str]]:
        doc = self.index.documents.get(doc_id)
        if not doc:
            return {}
        shard_features = self._load_shard_features(doc.shard_id or self._shard_id_for_doc(doc_id))
        return shard_features.get(doc_id, {})

    def _inverted_shard_id_for_gram(self, gram: str) -> str:
        digest = hashlib.md5(gram.encode("utf-8")).hexdigest()
        shard_num = int(digest[:4], 16) % self._inverted_shard_count
        return f"{shard_num:02d}"

    def _inverted_shard_path(self, shard_id: str) -> Path:
        return self.inverted_dir / f"{shard_id}.json"

    def _load_inverted_shard(self, shard_id: str, cache: bool = True) -> Dict[str, List[str]]:
        if cache and shard_id in self._inverted_cache:
            return self._inverted_cache[shard_id]

        shard_path = self._inverted_shard_path(shard_id)
        if not shard_path.exists():
            if cache:
                self._inverted_cache[shard_id] = {}
                return self._inverted_cache[shard_id]
            return {}

        try:
            with open(shard_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            shard_data = data if isinstance(data, dict) else {}
            if cache:
                self._inverted_cache[shard_id] = shard_data
                return self._inverted_cache[shard_id]
            return shard_data
        except Exception as e:
            print(f"[Corpus] 加载倒排分片失败 {shard_path}: {e}")
            if cache:
                self._inverted_cache[shard_id] = {}
                return self._inverted_cache[shard_id]
            return {}

    def _save_inverted_shard(self, shard_id: str) -> None:
        self._write_json_atomic(self._inverted_shard_path(shard_id), self._inverted_cache.get(shard_id, {}))

    def _get_inverted_postings(self, gram: str) -> List[str]:
        shard_id = self._inverted_shard_id_for_gram(gram)
        shard = self._load_inverted_shard(shard_id)
        return shard.get(gram, [])

    def _add_doc_to_inverted(self, doc_id: str, features: Dict[str, List[str]]) -> None:
        dirty_shards = set()
        for gram in features.get("char4", []) or []:
            shard_id = self._inverted_shard_id_for_gram(gram)
            shard = self._load_inverted_shard(shard_id)
            postings = shard.setdefault(gram, [])
            if doc_id not in postings:
                postings.append(doc_id)
                dirty_shards.add(shard_id)
        for shard_id in dirty_shards:
            self._save_inverted_shard(shard_id)

    def _remove_doc_from_inverted(self, doc_id: str) -> None:
        old_features = self._get_doc_features(doc_id)
        dirty_shards = set()
        for gram in old_features.get("char4", []) or []:
            shard_id = self._inverted_shard_id_for_gram(gram)
            shard = self._load_inverted_shard(shard_id)
            postings = shard.get(gram)
            if not postings or doc_id not in postings:
                continue
            shard[gram] = [item for item in postings if item != doc_id]
            if not shard[gram]:
                del shard[gram]
            dirty_shards.add(shard_id)
        for shard_id in dirty_shards:
            self._save_inverted_shard(shard_id)

    def _rss_mb(self) -> float:
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024
        except OSError:
            pass
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if rss_kb > 10_000_000:
            return rss_kb / (1024 * 1024)
        return rss_kb / 1024
