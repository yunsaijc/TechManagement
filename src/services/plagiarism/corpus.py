"""比对库管理 (Corpus Management).

负责管理远程挂载目录下的查重比对库，包括扫描、增量索引构建、
特征分片持久化和原文延迟加载。
"""

import hashlib
import json
import os
import resource
import sqlite3
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from src.common.file_handler import get_parser
from src.services.plagiarism.config import (
    PLAGIARISM_DEFAULT_CORPUS_PATH,
    PLAGIARISM_DEFAULT_INDEX_PATH,
    PLAGIARISM_DEFAULT_MANIFEST_PATH,
    PLAGIARISM_DEFAULT_SQLITE_PATH,
)
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
    format_version: int = 3


class CorpusManager:
    """比对库管理器。"""

    def __init__(
        self,
        corpus_path: Optional[str] = None,
        index_save_path: str = str(PLAGIARISM_DEFAULT_INDEX_PATH),
        shard_count: int = 16,
        scan_only: bool = False,
    ):
        env_path = os.getenv("PLAGIARISM_CORPUS_PATH")
        env_index_path = os.getenv("PLAGIARISM_CORPUS_INDEX_PATH")
        env_sqlite_path = os.getenv("PLAGIARISM_CORPUS_SQLITE_PATH")
        env_manifest_path = os.getenv("PLAGIARISM_CORPUS_MANIFEST_PATH")
        self.corpus_path = Path(corpus_path or env_path or PLAGIARISM_DEFAULT_CORPUS_PATH)
        self.index_save_path = Path(env_index_path or index_save_path)
        self.shard_dir = self.index_save_path.with_suffix("")
        self.shard_dir = self.shard_dir.parent / f"{self.shard_dir.name}_shards"
        self.inverted_dir = self.index_save_path.parent / "corpus_char4_inverted"
        self.sqlite_path = Path(env_sqlite_path) if env_sqlite_path else Path(PLAGIARISM_DEFAULT_SQLITE_PATH)
        self.manifest_path = Path(env_manifest_path) if env_manifest_path else Path(PLAGIARISM_DEFAULT_MANIFEST_PATH)
        self.shard_count = max(1, shard_count)
        self.max_postings_grams_per_doc = max(
            256,
            int(os.getenv("PLAGIARISM_CORPUS_MAX_POSTINGS_GRAMS_PER_DOC", "4096")),
        )
        self.write_json_debug = os.getenv("PLAGIARISM_CORPUS_WRITE_JSON", "0") == "1"
        self.scan_only = scan_only
        self.index: CorpusIndex = CorpusIndex(shard_count=self.shard_count)
        self.retriever = SourceRetriever()
        self._feature_cache: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
        self._inverted_cache: Dict[str, Dict[str, List[str]]] = {}
        self._inverted_shard_count = 64
        self._sqlite_ready = False

        self.index_save_path.parent.mkdir(parents=True, exist_ok=True)
        if self.write_json_debug:
            self.shard_dir.mkdir(parents=True, exist_ok=True)
            self.inverted_dir.mkdir(parents=True, exist_ok=True)
        self.load_index()
        if not self.scan_only:
            self._ensure_sqlite_schema()
            self._sqlite_ready = self._has_sqlite_retrieval_index()

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
            format_version=int(data.get("format_version") or 3),
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

    def scan_manifest(
        self,
        cursor_doc_id: Optional[str] = None,
        max_scan: Optional[int] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Dict[str, object]:
        """仅扫描目录并生成待处理 manifest，不执行解析建库。"""
        stats = {"scanned": 0, "new": 0, "updated": 0, "deleted": 0, "failed": 0, "unchanged": 0}
        if not self.corpus_path.exists():
            print(f"[Corpus] 错误: 挂载路径不存在 {self.corpus_path}")
            return stats

        max_scan = int(max_scan) if max_scan else None
        scan_started_at = time.time()
        last_seen_doc_id: Optional[str] = cursor_doc_id
        scan_truncated = False
        manifest = self._load_manifest()

        if progress_callback:
            progress_callback(
                {
                    "stage": "scan_manifest",
                    "processed": 0,
                    "total": 0,
                    "elapsed_seconds": 0,
                    "eta_seconds": 0,
                    "stats": dict(stats),
                }
            )

        for file_path in self._iter_docx_files(self.corpus_path):
            doc_id = self._doc_id_for_path(file_path)
            if cursor_doc_id and doc_id <= cursor_doc_id:
                continue

            stats["scanned"] += 1
            last_seen_doc_id = doc_id
            if progress_callback and (stats["scanned"] <= 1 or stats["scanned"] % 200 == 0):
                progress_callback(
                    {
                        "stage": "scan_manifest",
                        "processed": stats["scanned"],
                        "total": 0,
                        "elapsed_seconds": round(time.time() - scan_started_at, 2),
                        "eta_seconds": 0,
                        "stats": {
                            **dict(stats),
                            "current_path": str(file_path),
                            "cursor_doc_id": cursor_doc_id,
                        },
                    }
                )

            try:
                stat = file_path.stat()
            except OSError as e:
                print(f"[Corpus] 读取文件状态失败 {file_path.name}: {e}")
                stats["failed"] += 1
                if max_scan and stats["scanned"] >= max_scan:
                    scan_truncated = True
                    break
                continue

            file_size = int(stat.st_size)
            file_mtime = float(stat.st_mtime)
            stored_path = self._storage_path_for_file(file_path)
            existing = self.index.documents.get(doc_id)
            action = "unchanged"
            if existing:
                if existing.path != stored_path:
                    action = "fix_path"
                    stats["updated"] += 1
                elif existing.file_size != file_size or abs(existing.file_mtime - file_mtime) >= 1e-6:
                    action = "update"
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
            else:
                action = "new"
                stats["new"] += 1

            if action != "unchanged":
                manifest[doc_id] = {
                    "doc_id": doc_id,
                    "path": stored_path,
                    "file_size": file_size,
                    "file_mtime": file_mtime,
                    "action": action,
                    "updated_at": time.time(),
                }

            if max_scan and stats["scanned"] >= max_scan:
                scan_truncated = True
                break

        self._save_manifest(manifest)
        elapsed = time.time() - scan_started_at
        print(
            f"[Corpus] manifest 扫描完成: scanned={stats['scanned']}, "
            f"pending={len(manifest)}, elapsed={elapsed:.2f}s, "
            f"cursor={cursor_doc_id or '-'}, next_cursor={last_seen_doc_id or '-'}, truncated={scan_truncated}"
        )
        return {
            **stats,
            "pending": len(manifest),
            "cursor_doc_id": cursor_doc_id,
            "next_cursor": last_seen_doc_id,
            "has_more": scan_truncated,
        }

    async def build_batch_from_manifest(
        self,
        limit: int = 5,
        max_concurrency: int = 1,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Dict[str, object]:
        """从 manifest 中取一小批文档构建 SQLite 索引。"""
        import asyncio

        manifest = self._load_manifest()
        pending_items = [
            item for _, item in sorted(manifest.items(), key=lambda pair: pair[0])
            if item.get("action") in {"new", "update", "fix_path"}
        ]
        selected = pending_items[: max(1, int(limit))]
        max_concurrency = max(1, int(max_concurrency))
        stats = {
            "selected": len(selected),
            "processed": 0,
            "indexed": 0,
            "fixed_path": 0,
            "failed": 0,
            "remaining": max(len(pending_items) - len(selected), 0),
            "max_concurrency": max_concurrency,
        }
        if not selected:
            return {
                **stats,
                "has_more": False,
                "next_doc_id": None,
            }

        batch_started_at = time.time()
        parse_started_at = time.time()
        parse_jobs: List[dict] = []
        for item in selected:
            action = str(item["action"])
            if action == "fix_path":
                continue
            parse_jobs.append(item)

        async def parse_job(item: dict, semaphore: asyncio.Semaphore):
            async with semaphore:
                doc_id = str(item["doc_id"])
                file_path = Path(str(item["path"]))
                try:
                    stat = file_path.stat()
                    file_hash = self._calculate_hash(file_path)
                    doc_entry = await self._build_doc_entry(
                        doc_id=doc_id,
                        file_path=file_path,
                        file_hash=file_hash,
                        file_size=int(stat.st_size),
                        file_mtime=float(stat.st_mtime),
                    )
                    if not doc_entry:
                        raise RuntimeError(f"构建索引项失败: {doc_id}")
                    return doc_id, doc_entry, None
                except Exception as e:
                    return doc_id, None, str(e)

        parsed_results: Dict[str, Tuple[Optional[CorpusDocument], Optional[str]]] = {}
        if parse_jobs:
            semaphore = asyncio.Semaphore(max_concurrency)
            tasks = [
                asyncio.create_task(parse_job(item, semaphore))
                for item in parse_jobs
            ]
            for completed in asyncio.as_completed(tasks):
                doc_id, doc_entry, error = await completed
                parsed_results[doc_id] = (doc_entry, error)
        parse_elapsed = time.time() - parse_started_at

        fix_path_docs: List[CorpusDocument] = []
        sqlite_updates: List[CorpusDocument] = []
        processed_doc_ids: List[str] = []
        failed_docs: List[Tuple[str, str]] = []

        started_at = time.time()
        for item in selected:
            doc_id = str(item["doc_id"])
            action = str(item["action"])
            file_path = Path(str(item["path"]))
            stats["processed"] += 1
            if progress_callback:
                progress_callback(
                    {
                        "stage": "build_batch_prepare",
                        "processed": stats["processed"],
                        "total": len(selected),
                        "elapsed_seconds": round(time.time() - started_at, 2),
                        "eta_seconds": 0,
                        "stats": {
                            **dict(stats),
                            "doc_id": doc_id,
                            "action": action,
                            "parse_elapsed_seconds": round(parse_elapsed, 2),
                        },
                    }
                )

            try:
                if action == "fix_path":
                    existing = self.index.documents.get(doc_id)
                    if not existing:
                        raise RuntimeError(f"索引中不存在文档: {doc_id}")
                    existing.path = str(file_path)
                    try:
                        stat = file_path.stat()
                        existing.file_size = int(stat.st_size)
                        existing.file_mtime = float(stat.st_mtime)
                    except OSError:
                        pass
                    fix_path_docs.append(existing.model_copy())
                    processed_doc_ids.append(doc_id)
                    stats["fixed_path"] += 1
                    continue

                doc_entry, parse_error = parsed_results.get(doc_id, (None, "解析结果缺失"))
                if parse_error:
                    raise RuntimeError(parse_error)
                if not doc_entry:
                    raise RuntimeError(f"构建索引项失败: {doc_id}")
                self.index.documents[doc_id] = doc_entry.model_copy(update={"features": None})
                sqlite_updates.append(doc_entry)
                processed_doc_ids.append(doc_id)
                stats["indexed"] += 1
            except Exception as e:
                stats["failed"] += 1
                failed_docs.append((doc_id, str(e)))
                print(f"[Corpus] build_batch 失败 {doc_id}: {e}")

        sqlite_started_at = time.time()
        conn = self._connect_sqlite()
        try:
            conn.execute("BEGIN")
            if fix_path_docs:
                self._bulk_upsert_sqlite_doc_metadata(conn, fix_path_docs)
            if sqlite_updates:
                self._apply_sqlite_doc_feature_batch_updates(conn, sqlite_updates)
            conn.commit()
            for doc_id in processed_doc_ids:
                manifest.pop(doc_id, None)
        except Exception as e:
            conn.rollback()
            print(f"[Corpus] build_batch SQLite 批量写入失败: {e}")
            raise
        finally:
            conn.close()

        sqlite_elapsed = time.time() - sqlite_started_at
        save_started_at = time.time()
        try:
            self.save_index()
            self._save_manifest(manifest)
        finally:
            save_elapsed = time.time() - save_started_at

        total_elapsed = time.time() - batch_started_at
        print(
            "[Corpus] build_batch 完成: "
            f"selected={len(selected)}, indexed={stats['indexed']}, fixed_path={stats['fixed_path']}, "
            f"failed={stats['failed']}, parse={parse_elapsed:.2f}s, sqlite={sqlite_elapsed:.2f}s, "
            f"save={save_elapsed:.2f}s, total={total_elapsed:.2f}s"
        )

        remaining = len(
            [
                item for item in manifest.values()
                if item.get("action") in {"new", "update", "fix_path"}
            ]
        )
        return {
            **stats,
            "remaining": remaining,
            "has_more": remaining > 0,
            "next_doc_id": min(manifest.keys()) if manifest else None,
            "timings": {
                "parse_seconds": round(parse_elapsed, 2),
                "sqlite_seconds": round(sqlite_elapsed, 2),
                "save_seconds": round(save_elapsed, 2),
                "total_seconds": round(total_elapsed, 2),
            },
            "failed_docs": failed_docs,
        }

    def clear_coarse_index(self) -> None:
        """清空粗召回索引，保留 docs 与 doc_features。"""
        conn = self._connect_sqlite()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM postings_char4")
            conn.execute("DELETE FROM gram_stats_char4")
            conn.execute("UPDATE doc_features SET coarse_char4_json = '[]'")
            conn.commit()
            self._sqlite_ready = False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rebuild_coarse_index(
        self,
        progress_callback: Optional[Callable[[dict], None]] = None,
        batch_size: int = 50,
    ) -> Dict[str, object]:
        """基于现有 doc_features 全量重建粗召回倒排。"""
        batch_size = max(1, int(batch_size))
        conn = self._connect_sqlite()
        started_at = time.time()
        processed_docs = 0
        total_postings = 0

        try:
            total_docs = int(conn.execute("SELECT COUNT(*) FROM doc_features").fetchone()[0])
            if total_docs == 0:
                return {
                    "documents": 0,
                    "postings": 0,
                    "elapsed_seconds": 0.0,
                }

            conn.execute("BEGIN")
            conn.execute("DROP TABLE IF EXISTS temp.coarse_postings_stage")
            conn.execute("CREATE TEMP TABLE coarse_postings_stage (gram TEXT NOT NULL, doc_id TEXT NOT NULL)")

            cursor = conn.execute(
                """
                SELECT doc_id, char4_json
                FROM doc_features
                ORDER BY doc_id ASC
                """
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break

                feature_updates = []
                posting_rows = []
                for row in rows:
                    doc_id = str(row["doc_id"])
                    grams = json.loads(row["char4_json"])
                    coarse_grams = self._select_representative_char4_grams(conn, grams)
                    feature_updates.append((self._feature_json(coarse_grams), doc_id))
                    posting_rows.extend((gram, doc_id) for gram in coarse_grams)

                if feature_updates:
                    conn.executemany(
                        "UPDATE doc_features SET coarse_char4_json = ? WHERE doc_id = ?",
                        feature_updates,
                    )
                if posting_rows:
                    conn.executemany(
                        "INSERT INTO temp.coarse_postings_stage (gram, doc_id) VALUES (?, ?)",
                        posting_rows,
                    )

                processed_docs += len(rows)
                total_postings += len(posting_rows)
                if progress_callback and (
                    processed_docs <= 1
                    or processed_docs % 100 == 0
                    or processed_docs >= total_docs
                ):
                    elapsed = time.time() - started_at
                    avg_per_doc = elapsed / processed_docs if processed_docs else 0.0
                    remaining_docs = max(total_docs - processed_docs, 0)
                    progress_callback(
                        {
                            "stage": "rebuild_coarse_index",
                            "processed": processed_docs,
                            "total": total_docs,
                            "elapsed_seconds": round(elapsed, 2),
                            "eta_seconds": int(avg_per_doc * remaining_docs) if avg_per_doc > 0 else 0,
                            "stats": {
                                "documents": total_docs,
                                "processed_docs": processed_docs,
                                "postings": total_postings,
                            },
                        }
                    )

            conn.execute("DROP INDEX IF EXISTS idx_postings_char4_doc_id")
            conn.execute("DELETE FROM postings_char4")
            conn.execute("DELETE FROM gram_stats_char4")
            conn.execute(
                """
                INSERT INTO postings_char4 (gram, doc_id)
                SELECT gram, doc_id
                FROM temp.coarse_postings_stage
                GROUP BY gram, doc_id
                ORDER BY gram, doc_id
                """
            )
            conn.execute(
                """
                INSERT INTO gram_stats_char4 (gram, df)
                SELECT gram, COUNT(*)
                FROM temp.coarse_postings_stage
                GROUP BY gram
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_postings_char4_doc_id
                ON postings_char4 (doc_id)
                """
            )
            conn.execute("DROP TABLE IF EXISTS temp.coarse_postings_stage")
            conn.commit()
            self._sqlite_ready = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        elapsed_total = time.time() - started_at
        print(
            f"[Corpus] coarse index 重建完成: docs={processed_docs}, "
            f"postings={total_postings}, elapsed={elapsed_total:.2f}s"
        )
        return {
            "documents": processed_docs,
            "postings": total_postings,
            "elapsed_seconds": round(elapsed_total, 2),
        }

    async def scan_and_update_with_options(
        self,
        limit: Optional[int] = None,
        batch_size: int = 100,
        max_concurrency: int = 2,
        save_every_batches: int = 5,
        cursor_doc_id: Optional[str] = None,
        max_scan: Optional[int] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Dict[str, object]:
        """扫描挂载目录并增量更新索引。"""
        import asyncio

        stats = {"scanned": 0, "new": 0, "updated": 0, "deleted": 0, "failed": 0, "unchanged": 0}
        if not self.corpus_path.exists():
            print(f"[Corpus] 错误: 挂载路径不存在 {self.corpus_path}")
            return stats

        batch_size = max(1, int(batch_size))
        max_concurrency = max(1, int(max_concurrency))
        save_every_batches = max(1, int(save_every_batches))
        max_scan = int(max_scan) if max_scan else None

        if self.index.documents and not self._sqlite_ready:
            print("[Corpus] SQLite 检索索引缺失，开始基于现有 JSON 分片重建...")
            self.rebuild_sqlite_index(progress_callback=progress_callback)
        if self.write_json_debug and self.index.documents and not any(self.inverted_dir.glob("*.json")):
            print("[Corpus] char4 倒排索引缺失，开始一次性重建...")
            self.rebuild_inverted_index(progress_callback=progress_callback)

        seen_doc_ids = set()
        to_process: List[Tuple[str, Path, int, float]] = []
        metadata_updates: List[CorpusDocument] = []
        scan_started_at = time.time()
        last_seen_doc_id: Optional[str] = cursor_doc_id
        scan_truncated = False
        limit_reached = False

        if progress_callback:
            progress_callback(
                {
                    "stage": "scan_files",
                    "processed": 0,
                    "total": 0,
                    "elapsed_seconds": 0,
                    "eta_seconds": 0,
                    "stats": dict(stats),
                }
            )

        for file_path in self._iter_docx_files(self.corpus_path):
            doc_id = self._doc_id_for_path(file_path)
            if cursor_doc_id and doc_id <= cursor_doc_id:
                continue

            stats["scanned"] += 1
            last_seen_doc_id = doc_id
            if progress_callback and (
                stats["scanned"] <= 1
                or stats["scanned"] % 200 == 0
            ):
                elapsed_scan = time.time() - scan_started_at
                progress_callback(
                    {
                        "stage": "scan_files",
                        "processed": stats["scanned"],
                        "total": 0,
                        "elapsed_seconds": round(elapsed_scan, 2),
                        "eta_seconds": 0,
                        "stats": {
                            **dict(stats),
                            "current_path": str(file_path),
                            "cursor_doc_id": cursor_doc_id,
                        },
                    }
                )
            seen_doc_ids.add(doc_id)

            try:
                stat = file_path.stat()
            except OSError as e:
                print(f"[Corpus] 读取文件状态失败 {file_path.name}: {e}")
                stats["failed"] += 1
                if max_scan and stats["scanned"] >= max_scan:
                    scan_truncated = True
                    break
                continue

            file_size = int(stat.st_size)
            file_mtime = float(stat.st_mtime)
            stored_path = self._storage_path_for_file(file_path)
            existing = self.index.documents.get(doc_id)
            if (
                existing
                and existing.file_size == file_size
                and abs(existing.file_mtime - file_mtime) < 1e-6
            ):
                if existing.path != stored_path:
                    existing.path = stored_path
                    existing.file_size = file_size
                    existing.file_mtime = file_mtime
                    metadata_updates.append(existing.model_copy())
                    stats["updated"] += 1
                    print(f"[Corpus] 修正路径映射: {doc_id} -> {stored_path}")
                    if max_scan and stats["scanned"] >= max_scan:
                        scan_truncated = True
                        break
                    continue
                stats["unchanged"] += 1
                if max_scan and stats["scanned"] >= max_scan:
                    scan_truncated = True
                    break
                continue

            to_process.append((doc_id, file_path, file_size, file_mtime))
            if limit and len(to_process) >= limit:
                limit_reached = True
                scan_truncated = True
                break
            if max_scan and stats["scanned"] >= max_scan:
                scan_truncated = True
                break

        print(
            f"[Corpus] 扫描完成: scanned={stats['scanned']}, "
            f"to_process={len(to_process)}, metadata_updates={len(metadata_updates)}, "
            f"elapsed={time.time() - scan_started_at:.2f}s, "
            f"cursor={cursor_doc_id or '-'}, next_cursor={last_seen_doc_id or '-'}, "
            f"truncated={scan_truncated}"
        )
        if progress_callback:
            progress_callback(
                {
                    "stage": "scan_files_done",
                    "processed": stats["scanned"],
                    "total": stats["scanned"],
                    "elapsed_seconds": round(time.time() - scan_started_at, 2),
                    "eta_seconds": 0,
                    "stats": {
                        **dict(stats),
                        "to_process": len(to_process),
                        "metadata_updates": len(metadata_updates),
                        "cursor_doc_id": cursor_doc_id,
                        "next_cursor": last_seen_doc_id,
                        "scan_truncated": scan_truncated,
                    },
                }
            )

        if metadata_updates:
            meta_started_at = time.time()
            print(f"[Corpus] 批量写入路径修正开始: count={len(metadata_updates)}")
            conn = self._connect_sqlite()
            try:
                conn.execute("BEGIN")
                self._bulk_upsert_sqlite_doc_metadata(conn, metadata_updates)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            print(
                f"[Corpus] 批量写入路径修正完成: count={len(metadata_updates)}, "
                f"耗时={time.time() - meta_started_at:.2f}s"
            )
            if progress_callback:
                progress_callback(
                    {
                        "stage": "sync_metadata_done",
                        "processed": len(metadata_updates),
                        "total": len(metadata_updates),
                        "elapsed_seconds": round(time.time() - meta_started_at, 2),
                        "eta_seconds": 0,
                        "stats": {
                            **dict(stats),
                            "metadata_updates": len(metadata_updates),
                        },
                    }
                )

        # 只有完整全量扫描时才允许删除缺失文档，避免短任务误删
        full_scan_completed = not scan_truncated and not cursor_doc_id
        removed_doc_ids: List[str] = []
        if full_scan_completed:
            removed_doc_ids = [doc_id for doc_id in self.index.documents.keys() if doc_id not in seen_doc_ids]
            if removed_doc_ids:
                for doc_id in removed_doc_ids:
                    self._remove_document(doc_id)
                stats["deleted"] = len(removed_doc_ids)

        if not to_process and not removed_doc_ids:
            print(f"[Corpus] {self.corpus_path} 下没有需要更新的 docx 文件")
            return {
                **stats,
                "cursor_doc_id": cursor_doc_id,
                "next_cursor": last_seen_doc_id,
                "has_more": scan_truncated,
                "full_scan_completed": full_scan_completed,
                "limit_reached": limit_reached,
            }

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
                dirty_inverted_shards = set()
                batch_changed = False
                handled_in_batch = 0
                sqlite_updates: List[Tuple[CorpusDocument, Dict[str, List[str]]]] = []
                sqlite_conn = self._connect_sqlite()
                sqlite_conn.execute("BEGIN")

                async def wrapped_process(item: Tuple[str, Path, int, float]):
                    async with semaphore:
                        return await process_task(*item)

                tasks = [asyncio.create_task(wrapped_process(item)) for item in batch]
                try:
                    for completed in asyncio.as_completed(tasks):
                        doc_id, doc_entry, outcome = await completed
                        handled_in_batch += 1
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

                        processed_so_far = processed_count + handled_in_batch
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

                        old_features = self._get_doc_features(doc_id)
                        if self.write_json_debug:
                            self._remove_doc_from_inverted(
                                doc_id,
                                old_features=old_features,
                                dirty_shards=dirty_inverted_shards,
                                save=False,
                            )
                            dirty_shards.add(doc_entry.shard_id)
                        self.index.documents[doc_id] = doc_entry.model_copy(update={"features": None})
                        if self.write_json_debug:
                            shard_features = self._load_shard_features(doc_entry.shard_id)
                            shard_features[doc_id] = doc_entry.features or {}
                            self._add_doc_to_inverted(
                                doc_id,
                                doc_entry.features or {},
                                dirty_shards=dirty_inverted_shards,
                                save=False,
                            )
                        sqlite_updates.append((doc_entry, old_features))
                    self._apply_sqlite_batch_updates(sqlite_conn, sqlite_updates)
                    sqlite_conn.commit()
                except Exception:
                    sqlite_conn.rollback()
                    raise
                finally:
                    sqlite_conn.close()

                if self.write_json_debug:
                    print(
                        f"[Corpus] 批后写盘开始: batch={batch_index}, "
                        f"feature_shards={len(dirty_shards)}, inverted_shards={len(dirty_inverted_shards)}"
                    )
                    for shard_id in dirty_shards:
                        self._save_shard_features(shard_id)
                    for shard_id in dirty_inverted_shards:
                        self._save_inverted_shard(shard_id)
                    print(
                        f"[Corpus] 批后写盘完成: batch={batch_index}, "
                        f"feature_shards={len(dirty_shards)}, inverted_shards={len(dirty_inverted_shards)}, "
                        f"耗时={time.time() - batch_started_at:.2f}s"
                    )

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

        return {
            **stats,
            "cursor_doc_id": cursor_doc_id,
            "next_cursor": last_seen_doc_id,
            "has_more": scan_truncated,
            "full_scan_completed": full_scan_completed,
            "limit_reached": limit_reached,
        }

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
        if self._sqlite_ready and doc_ids:
            return self._get_retrieval_documents_from_sqlite(doc_ids)

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
            unique_query_grams = set(sorted(unique_query_grams)[:max_query_grams])

        if self._sqlite_ready:
            return self._retrieve_candidate_doc_ids_from_sqlite(
                unique_query_grams=sorted(unique_query_grams),
                top_k=top_k,
                min_hits=min_hits,
                max_postings_per_gram=max_postings_per_gram,
            )

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
        return self._sqlite_ready or (self.write_json_debug and any(self.inverted_dir.glob("*.json")))

    def rebuild_sqlite_index(self, progress_callback: Optional[Callable[[dict], None]] = None) -> None:
        """基于现有 JSON 分片重建 SQLite 在线检索索引。"""
        self._ensure_sqlite_schema()
        conn = self._connect_sqlite()
        conn.execute("DELETE FROM gram_stats_char4")
        conn.execute("DELETE FROM postings_char4")
        conn.execute("DELETE FROM doc_features")
        conn.execute("DELETE FROM docs")
        conn.commit()

        grouped_doc_ids = defaultdict(list)
        for doc_id, doc in self.index.documents.items():
            grouped_doc_ids[doc.shard_id or self._shard_id_for_doc(doc_id)].append(doc_id)

        total_docs = len(self.index.documents)
        processed_docs = 0
        started_at = time.time()
        print(f"[Corpus] SQLite 重建开始: docs={total_docs}, feature_shards={len(grouped_doc_ids)}")

        for feature_shard_id, doc_ids in grouped_doc_ids.items():
            shard_started_at = time.time()
            shard_features = self._load_shard_features(feature_shard_id, cache=False)
            conn.execute("BEGIN")
            for doc_id in doc_ids:
                doc = self.index.documents.get(doc_id)
                if not doc:
                    continue
                features = shard_features.get(doc_id, {})
                doc_entry = doc.model_copy(update={"features": features})
                self._replace_doc_in_sqlite(conn, doc_entry, old_features={})
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
                            "stage": "rebuild_sqlite_index",
                            "processed": processed_docs,
                            "total": total_docs,
                            "feature_shard_id": feature_shard_id,
                            "elapsed_seconds": round(elapsed, 2),
                            "eta_seconds": int(avg_per_doc * remaining) if avg_per_doc > 0 else 0,
                            "stats": {
                                "documents": total_docs,
                                "sqlite_path": str(self.sqlite_path),
                            },
                        }
                    )
            conn.commit()
            print(
                f"[Corpus] SQLite 重建: 完成 feature shard {feature_shard_id}, "
                f"耗时={time.time() - shard_started_at:.2f}s, 累计={processed_docs}/{total_docs}"
            )

        conn.close()
        self._sqlite_ready = self._has_sqlite_retrieval_index()
        elapsed_total = time.time() - started_at
        print(f"[Corpus] SQLite 重建完成: docs={processed_docs}, 耗时={elapsed_total:.2f}s")
        if progress_callback:
            progress_callback(
                {
                    "stage": "rebuild_sqlite_index_done",
                    "processed": processed_docs,
                    "total": total_docs,
                    "elapsed_seconds": round(elapsed_total, 2),
                    "eta_seconds": 0,
                    "stats": {
                        "documents": total_docs,
                        "sqlite_path": str(self.sqlite_path),
                    },
                }
            )

    def rebuild_inverted_index(self, progress_callback: Optional[Callable[[dict], None]] = None) -> None:
        if not self.write_json_debug:
            print("[Corpus] 跳过倒排 JSON 重建: 当前运行模式仅维护 SQLite")
            return
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

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _ensure_sqlite_schema(self) -> None:
        conn = self._connect_sqlite()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as e:
            print(f"[Corpus] 跳过 journal_mode=WAL: {e}")
        try:
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError as e:
            print(f"[Corpus] 跳过 synchronous=NORMAL: {e}")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (
                doc_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                file_size INTEGER NOT NULL,
                file_mtime REAL NOT NULL,
                shard_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS doc_features (
                doc_id TEXT PRIMARY KEY,
                char2_json TEXT NOT NULL,
                char4_json TEXT NOT NULL,
                char8_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS postings_char4 (
                gram TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                PRIMARY KEY (gram, doc_id)
            );
            CREATE TABLE IF NOT EXISTS gram_stats_char4 (
                gram TEXT PRIMARY KEY,
                df INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_postings_char4_doc_id
            ON postings_char4 (doc_id);
            """
        )
        doc_features_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(doc_features)").fetchall()
        }
        if "coarse_char4_json" not in doc_features_columns:
            conn.execute(
                "ALTER TABLE doc_features ADD COLUMN coarse_char4_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.commit()
        conn.close()

    def _has_sqlite_retrieval_index(self) -> bool:
        if not self.sqlite_path.exists():
            return False
        try:
            conn = self._connect_sqlite()
            docs_count = int(conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0])
            grams_count = int(conn.execute("SELECT COUNT(*) FROM gram_stats_char4").fetchone()[0])
            conn.close()
            return docs_count > 0 and grams_count > 0
        except Exception as e:
            print(f"[Corpus] 检查 SQLite 检索索引失败: {e}")
            return False

    def _upsert_sqlite_doc_metadata(self, doc: CorpusDocument) -> None:
        if not self.sqlite_path.exists():
            return
        conn = self._connect_sqlite()
        cursor = self._bulk_upsert_sqlite_doc_metadata(conn, [doc])
        if cursor.rowcount:
            conn.commit()
        conn.close()

    def _bulk_upsert_sqlite_doc_metadata(
        self,
        conn: sqlite3.Connection,
        docs: List[CorpusDocument],
    ) -> sqlite3.Cursor:
        return conn.executemany(
            """
            UPDATE docs
            SET
                path = ?,
                file_hash = ?,
                char_count = ?,
                file_size = ?,
                file_mtime = ?,
                shard_id = ?
            WHERE doc_id = ?
            """,
            [
                (
                    doc.path,
                    doc.file_hash,
                    doc.char_count,
                    doc.file_size,
                    doc.file_mtime,
                    doc.shard_id,
                    doc.doc_id,
                )
                for doc in docs
            ],
        )

    def _replace_doc_in_sqlite(
        self,
        conn: sqlite3.Connection,
        doc_entry: CorpusDocument,
        old_features: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self._remove_doc_from_sqlite(conn, doc_entry.doc_id, old_features=old_features)
        features = doc_entry.features or {}
        coarse_grams = self._select_representative_char4_grams(
            conn,
            features.get("char4", []) or [],
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO docs (doc_id, path, file_hash, char_count, file_size, file_mtime, shard_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_entry.doc_id,
                doc_entry.path,
                doc_entry.file_hash,
                doc_entry.char_count,
                doc_entry.file_size,
                doc_entry.file_mtime,
                doc_entry.shard_id,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO doc_features (doc_id, char2_json, char4_json, char8_json, coarse_char4_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                doc_entry.doc_id,
                self._feature_json(features.get("char2", [])),
                self._feature_json(features.get("char4", [])),
                self._feature_json(features.get("char8", [])),
                self._feature_json(coarse_grams),
            ),
        )
        if coarse_grams:
            conn.executemany(
                "INSERT OR IGNORE INTO postings_char4 (gram, doc_id) VALUES (?, ?)",
                [(gram, doc_entry.doc_id) for gram in coarse_grams],
            )
            conn.executemany(
                """
                INSERT INTO gram_stats_char4 (gram, df) VALUES (?, 1)
                ON CONFLICT(gram) DO UPDATE SET df = df + 1
                """,
                [(gram,) for gram in coarse_grams],
            )
        self._sqlite_ready = True

    def _apply_sqlite_doc_feature_batch_updates(
        self,
        conn: sqlite3.Connection,
        updates: List[CorpusDocument],
    ) -> None:
        """仅写 docs 与 doc_features，不增量维护粗召回倒排。"""
        if not updates:
            return

        doc_rows = []
        feature_rows = []
        for doc_entry in updates:
            features = doc_entry.features or {}
            doc_rows.append(
                (
                    doc_entry.doc_id,
                    doc_entry.path,
                    doc_entry.file_hash,
                    doc_entry.char_count,
                    doc_entry.file_size,
                    doc_entry.file_mtime,
                    doc_entry.shard_id,
                )
            )
            feature_rows.append(
                (
                    doc_entry.doc_id,
                    self._feature_json(features.get("char2", [])),
                    self._feature_json(features.get("char4", [])),
                    self._feature_json(features.get("char8", [])),
                    "[]",
                )
            )

        conn.executemany(
            """
            INSERT OR REPLACE INTO docs (doc_id, path, file_hash, char_count, file_size, file_mtime, shard_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            doc_rows,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO doc_features (doc_id, char2_json, char4_json, char8_json, coarse_char4_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            feature_rows,
        )

    def _apply_sqlite_batch_updates(
        self,
        conn: sqlite3.Connection,
        updates: List[Tuple[CorpusDocument, Dict[str, List[str]]]],
    ) -> None:
        if not updates:
            return

        doc_rows = []
        feature_rows = []
        posting_deletes = []
        posting_inserts = []
        gram_deltas: Dict[str, int] = defaultdict(int)
        representative_cache: Dict[str, List[str]] = {}

        for doc_entry, old_features in updates:
            old_grams = set(old_features.get("coarse_char4", []) or [])
            features = doc_entry.features or {}
            representative_grams = self._select_representative_char4_grams(
                conn,
                features.get("char4", []) or [],
            )
            representative_cache[doc_entry.doc_id] = representative_grams
            new_grams = set(representative_grams)

            removed_grams = old_grams - new_grams
            added_grams = new_grams - old_grams

            if removed_grams:
                posting_deletes.extend((gram, doc_entry.doc_id) for gram in removed_grams)
                for gram in removed_grams:
                    gram_deltas[gram] -= 1
            if added_grams:
                posting_inserts.extend((gram, doc_entry.doc_id) for gram in added_grams)
                for gram in added_grams:
                    gram_deltas[gram] += 1

            doc_rows.append(
                (
                    doc_entry.doc_id,
                    doc_entry.path,
                    doc_entry.file_hash,
                    doc_entry.char_count,
                    doc_entry.file_size,
                    doc_entry.file_mtime,
                    doc_entry.shard_id,
                )
            )
            feature_rows.append(
                (
                    doc_entry.doc_id,
                    self._feature_json(features.get("char2", [])),
                    self._feature_json(features.get("char4", [])),
                    self._feature_json(features.get("char8", [])),
                    self._feature_json(representative_cache[doc_entry.doc_id]),
                )
            )

        if posting_deletes:
            conn.executemany(
                "DELETE FROM postings_char4 WHERE gram = ? AND doc_id = ?",
                posting_deletes,
            )
        if posting_inserts:
            conn.executemany(
                "INSERT OR IGNORE INTO postings_char4 (gram, doc_id) VALUES (?, ?)",
                posting_inserts,
            )

        conn.executemany(
            """
            INSERT OR REPLACE INTO docs (doc_id, path, file_hash, char_count, file_size, file_mtime, shard_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            doc_rows,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO doc_features (doc_id, char2_json, char4_json, char8_json, coarse_char4_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            feature_rows,
        )

        positive_deltas = [(gram, delta) for gram, delta in gram_deltas.items() if delta > 0]
        negative_deltas = [(gram, -delta) for gram, delta in gram_deltas.items() if delta < 0]

        if positive_deltas:
            conn.executemany(
                """
                INSERT INTO gram_stats_char4 (gram, df) VALUES (?, ?)
                ON CONFLICT(gram) DO UPDATE SET df = df + excluded.df
                """,
                positive_deltas,
            )
        if negative_deltas:
            conn.executemany(
                "UPDATE gram_stats_char4 SET df = df - ? WHERE gram = ?",
                [(delta, gram) for gram, delta in negative_deltas],
            )
            conn.executemany(
                "DELETE FROM gram_stats_char4 WHERE gram = ? AND df <= 0",
                [(gram,) for gram, _ in negative_deltas],
            )

        self._sqlite_ready = True

    def _remove_doc_from_sqlite(
        self,
        conn: sqlite3.Connection,
        doc_id: str,
        old_features: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        features = old_features
        if features is None:
            row = conn.execute(
                "SELECT char4_json, coarse_char4_json FROM doc_features WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            features = (
                {
                    "char4": json.loads(row["char4_json"]),
                    "coarse_char4": json.loads(row["coarse_char4_json"]),
                }
                if row else {}
            )
        for gram in features.get("coarse_char4", []) or []:
            cursor = conn.execute(
                "DELETE FROM postings_char4 WHERE gram = ? AND doc_id = ?",
                (gram, doc_id),
            )
            if cursor.rowcount:
                conn.execute("UPDATE gram_stats_char4 SET df = df - 1 WHERE gram = ?", (gram,))
                conn.execute("DELETE FROM gram_stats_char4 WHERE gram = ? AND df <= 0", (gram,))
        conn.execute("DELETE FROM doc_features WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))

    def _feature_json(self, values: List[str]) -> str:
        return json.dumps(values, ensure_ascii=False, separators=(",", ":"))

    def _select_representative_char4_grams(
        self,
        conn: sqlite3.Connection,
        grams: List[str],
    ) -> List[str]:
        """选择代表性粗召回 gram：优先参考已有 df，并保证全文覆盖。"""
        ordered_unique = list(dict.fromkeys(grams))
        if len(ordered_unique) <= self.max_postings_grams_per_doc:
            return ordered_unique

        df_map = self._load_gram_df_map(conn, ordered_unique)
        segment_count = min(8, max(4, len(ordered_unique) // 512))
        segment_size = max(1, len(ordered_unique) // segment_count)
        per_segment_budget = max(1, self.max_postings_grams_per_doc // segment_count)
        selected: List[str] = []
        selected_set: Set[str] = set()

        for segment_start in range(0, len(ordered_unique), segment_size):
            segment = ordered_unique[segment_start : segment_start + segment_size]
            ranked_segment = sorted(
                segment,
                key=lambda gram: (
                    df_map.get(gram, 0),
                    hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(),
                ),
            )
            for gram in ranked_segment[:per_segment_budget]:
                if gram in selected_set:
                    continue
                selected.append(gram)
                selected_set.add(gram)
                if len(selected) >= self.max_postings_grams_per_doc:
                    return selected

        if len(selected) < self.max_postings_grams_per_doc:
            remaining = [gram for gram in ordered_unique if gram not in selected_set]
            ranked_remaining = sorted(
                remaining,
                key=lambda gram: (
                    df_map.get(gram, 0),
                    hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(),
                ),
            )
            for gram in ranked_remaining:
                selected.append(gram)
                if len(selected) >= self.max_postings_grams_per_doc:
                    break

        return selected

    def _load_gram_df_map(
        self,
        conn: sqlite3.Connection,
        grams: List[str],
    ) -> Dict[str, int]:
        if not grams:
            return {}
        df_map: Dict[str, int] = {}
        for chunk in self._iter_string_chunks(grams, 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT gram, df FROM gram_stats_char4 WHERE gram IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                df_map[str(row["gram"])] = int(row["df"])
        return df_map

    def _get_doc_features_from_sqlite(self, doc_id: str) -> Dict[str, List[str]]:
        if not self.sqlite_path.exists():
            return {}
        conn = self._connect_sqlite()
        row = conn.execute(
            """
            SELECT char2_json, char4_json, char8_json, coarse_char4_json
            FROM doc_features
            WHERE doc_id = ?
            """,
            (doc_id,),
        ).fetchone()
        conn.close()
        if not row:
            return {}
        return {
            "char2": json.loads(row["char2_json"]),
            "char4": json.loads(row["char4_json"]),
            "char8": json.loads(row["char8_json"]),
            "coarse_char4": json.loads(row["coarse_char4_json"]),
        }

    def _retrieve_candidate_doc_ids_from_sqlite(
        self,
        unique_query_grams: List[str],
        top_k: int,
        min_hits: int,
        max_postings_per_gram: int,
    ) -> List[str]:
        conn = self._connect_sqlite()
        conn.execute("DROP TABLE IF EXISTS temp.tmp_query_grams")
        conn.execute("CREATE TEMP TABLE tmp_query_grams (gram TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT OR IGNORE INTO temp.tmp_query_grams (gram) VALUES (?)",
            [(gram,) for gram in unique_query_grams],
        )
        skipped_high_df = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM temp.tmp_query_grams q
                JOIN gram_stats_char4 s ON s.gram = q.gram
                WHERE s.df > ?
                """,
                (max_postings_per_gram,),
            ).fetchone()[0]
        )
        scored_docs = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT p.doc_id
                    FROM temp.tmp_query_grams q
                    JOIN gram_stats_char4 s ON s.gram = q.gram
                    JOIN postings_char4 p ON p.gram = q.gram
                    WHERE s.df <= ?
                    GROUP BY p.doc_id
                    HAVING COUNT(*) >= ?
                ) ranked
                """,
                (max_postings_per_gram, min_hits),
            ).fetchone()[0]
        )
        rows = conn.execute(
            """
            SELECT ranked.doc_id, ranked.score, ranked.gram_hits
            FROM (
                SELECT
                    p.doc_id AS doc_id,
                    SUM(1.0 / s.df) AS score,
                    COUNT(*) AS gram_hits
                FROM temp.tmp_query_grams q
                JOIN gram_stats_char4 s ON s.gram = q.gram
                JOIN postings_char4 p ON p.gram = q.gram
                WHERE s.df <= ?
                GROUP BY p.doc_id
                HAVING COUNT(*) >= ?
            ) ranked
            ORDER BY ranked.score DESC, ranked.gram_hits DESC, ranked.doc_id ASC
            LIMIT ?
            """,
            (max_postings_per_gram, min_hits, top_k),
        ).fetchall()
        conn.execute("DROP TABLE IF EXISTS temp.tmp_query_grams")
        conn.close()
        selected = [str(row["doc_id"]) for row in rows]
        print(
            f"[Corpus] 粗召回结束: candidates={len(selected)}, query_grams={len(unique_query_grams)}, "
            f"scored_docs={scored_docs}, skipped_high_df={skipped_high_df}, rss={self._rss_mb():.1f}MB"
        )
        return selected

    def _get_retrieval_documents_from_sqlite(self, doc_ids: List[str]) -> Dict[str, CorpusDocument]:
        docs_with_features: Dict[str, CorpusDocument] = {}
        conn = self._connect_sqlite()
        for chunk in self._iter_doc_id_chunks(doc_ids, 200):
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT
                    d.doc_id,
                    d.path,
                    d.file_hash,
                    d.char_count,
                    d.file_size,
                    d.file_mtime,
                    d.shard_id,
                    f.char2_json,
                    f.char4_json,
                    f.char8_json
                FROM docs d
                JOIN doc_features f ON f.doc_id = d.doc_id
                WHERE d.doc_id IN ({placeholders})
                """,
                chunk,
            ).fetchall()
            for row in rows:
                docs_with_features[str(row["doc_id"])] = CorpusDocument(
                    doc_id=str(row["doc_id"]),
                    path=str(row["path"]),
                    file_hash=str(row["file_hash"]),
                    char_count=int(row["char_count"]),
                    file_size=int(row["file_size"]),
                    file_mtime=float(row["file_mtime"]),
                    shard_id=str(row["shard_id"]),
                    features={
                        "char2": json.loads(row["char2_json"]),
                        "char4": json.loads(row["char4_json"]),
                        "char8": json.loads(row["char8_json"]),
                    },
                )
        conn.close()
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
            normalized = self.retriever._normalize(full_text)
            features_json = {
                "char2": self._ordered_unique_ngrams(normalized, 2),
                "char4": self._ordered_unique_ngrams(normalized, 4),
                "char8": self._ordered_unique_ngrams(normalized, 8),
            }
            rel_path = self._storage_path_for_file(file_path)
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

    def _storage_path_for_file(self, file_path: Path) -> str:
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
        if not self.write_json_debug:
            return
        shard_path = self._shard_path(shard_id)
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(shard_path, self._feature_cache.get(shard_id, {}))

    def _remove_document(self, doc_id: str) -> None:
        doc = self.index.documents.pop(doc_id, None)
        if not doc:
            return
        shard_id = doc.shard_id or self._shard_id_for_doc(doc_id)
        old_features = self._get_doc_features(doc_id)
        if self.write_json_debug:
            shard_features = self._load_shard_features(shard_id)
            if doc_id in shard_features:
                del shard_features[doc_id]
                self._save_shard_features(shard_id)
            self._remove_doc_from_inverted(doc_id, old_features=old_features)
        conn = self._connect_sqlite()
        self._remove_doc_from_sqlite(conn, doc_id, old_features=old_features)
        conn.commit()
        conn.close()

    def _iter_batches(self, items: List[Tuple[str, Path, int, float]], batch_size: int):
        iterator = iter(items)
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break
            yield batch

    def _iter_docx_files(self, root: Path) -> Iterator[Path]:
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            yield from self._iter_docx_files(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".docx"):
                            yield Path(entry.path)
                    except OSError as e:
                        print(f"[Corpus] 扫描目录项失败 {entry.path}: {e}")
        except OSError as e:
            print(f"[Corpus] 扫描目录失败 {root}: {e}")

    def _iter_doc_id_chunks(self, doc_ids: List[str], chunk_size: int):
        iterator = iter(doc_ids)
        while True:
            chunk = list(islice(iterator, chunk_size))
            if not chunk:
                break
            yield chunk

    def _iter_string_chunks(self, items: List[str], chunk_size: int):
        iterator = iter(items)
        while True:
            chunk = list(islice(iterator, chunk_size))
            if not chunk:
                break
            yield chunk

    def _load_manifest(self) -> Dict[str, dict]:
        if not self.manifest_path.exists():
            return {}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[Corpus] 加载 manifest 失败: {e}")
            return {}

    def _save_manifest(self, manifest: Dict[str, dict]) -> None:
        self._write_json_atomic(self.manifest_path, manifest)

    def _write_json_atomic(self, target_path: Path, data: object) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f"{target_path.name}.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target_path)

    def _get_doc_features(self, doc_id: str) -> Dict[str, List[str]]:
        if self._sqlite_ready:
            features = self._get_doc_features_from_sqlite(doc_id)
            if features:
                return features
        if not self.write_json_debug:
            return {}
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
        if not self.write_json_debug:
            return {}
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
        if not self.write_json_debug:
            return
        self._write_json_atomic(self._inverted_shard_path(shard_id), self._inverted_cache.get(shard_id, {}))

    def _get_inverted_postings(self, gram: str) -> List[str]:
        shard_id = self._inverted_shard_id_for_gram(gram)
        shard = self._load_inverted_shard(shard_id)
        return shard.get(gram, [])

    def _ordered_unique_ngrams(self, text: str, n: int) -> List[str]:
        if len(text) < n:
            return [text] if text else []
        seen: Set[str] = set()
        ordered: List[str] = []
        for idx in range(len(text) - n + 1):
            gram = text[idx : idx + n]
            if gram in seen:
                continue
            seen.add(gram)
            ordered.append(gram)
        return ordered

    def _add_doc_to_inverted(
        self,
        doc_id: str,
        features: Dict[str, List[str]],
        dirty_shards: Optional[Set[str]] = None,
        save: bool = True,
    ) -> None:
        target_dirty_shards = dirty_shards if dirty_shards is not None else set()
        for gram in features.get("char4", []) or []:
            shard_id = self._inverted_shard_id_for_gram(gram)
            shard = self._load_inverted_shard(shard_id)
            postings = shard.setdefault(gram, [])
            if doc_id not in postings:
                postings.append(doc_id)
                target_dirty_shards.add(shard_id)
        if save:
            for shard_id in target_dirty_shards:
                self._save_inverted_shard(shard_id)

    def _remove_doc_from_inverted(
        self,
        doc_id: str,
        old_features: Optional[Dict[str, List[str]]] = None,
        dirty_shards: Optional[Set[str]] = None,
        save: bool = True,
    ) -> None:
        target_dirty_shards = dirty_shards if dirty_shards is not None else set()
        old_features = old_features if old_features is not None else self._get_doc_features(doc_id)
        for gram in old_features.get("char4", []) or []:
            shard_id = self._inverted_shard_id_for_gram(gram)
            shard = self._load_inverted_shard(shard_id)
            postings = shard.get(gram)
            if not postings or doc_id not in postings:
                continue
            shard[gram] = [item for item in postings if item != doc_id]
            if not shard[gram]:
                del shard[gram]
            target_dirty_shards.add(shard_id)
        if save:
            for shard_id in target_dirty_shards:
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
