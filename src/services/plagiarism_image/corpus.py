"""Corpus manager for image plagiarism retrieval."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fcntl
import numpy as np

from .config import (
    DEFAULT_FEATURE_DESCRIPTOR_ROWS,
    DEFAULT_HASH_HAMMING_MAX,
    IMAGE_BUILD_FEATURE_WORKERS,
    IMAGE_BUILD_IOWAIT_CHECK_EVERY_DOCS,
    IMAGE_BUILD_IOWAIT_RATIO_THRESHOLD,
    IMAGE_BUILD_IOWAIT_SAMPLE_SECONDS,
    IMAGE_BUILD_IOWAIT_SLEEP_SECONDS,
    IMAGE_PLAGIARISM_CHECKPOINT_PATH,
    IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH,
    IMAGE_BUILD_LARGE_CORPUS_DOC_THRESHOLD,
    IMAGE_BUILD_MIN_LIMIT_LARGE_CORPUS,
    IMAGE_PLAGIARISM_FEATURE_DB_PATH,
    IMAGE_PLAGIARISM_BUILD_LOCK_PATH,
    IMAGE_PLAGIARISM_INDEX_PATH,
    IMAGE_PLAGIARISM_LOCAL_ROOT,
    IMAGE_PLAGIARISM_MANIFEST_PATH,
    IMAGE_PLAGIARISM_REMOTE_ROOT,
    IMAGE_PLAGIARISM_SHADOW_DIR,
)
from .extractor import extract_images_from_file
from .hashing import (
    ImageHasher,
    RuntimeImageFingerprint,
    deserialize_feature_blob,
    phash_hex_to_int,
    serialize_feature_blob,
)
from .matcher import ImageMatcher
from .schemas import ImageAsset, ImageFingerprint, ImageMatch


def _build_doc_payload(path_str: str) -> Dict:
    path = Path(path_str)
    doc_id = path.stem
    stat = path.stat()
    file_data = path.read_bytes()
    assets = extract_images_from_file(doc_id=doc_id, file_name=path.name, file_data=file_data)
    hasher = ImageHasher()
    image_rows: List[Dict] = []
    feature_rows: List[Dict] = []
    for asset in assets:
        fp = hasher.build(asset)
        if fp is None:
            continue
        now = time.time()
        image_rows.append(
            {
                "image_id": asset.image_id,
                "doc_id": doc_id,
                "doc_path": str(path),
                "page": int(asset.page),
                "image_index": int(asset.image_index),
                "width": int(asset.width),
                "height": int(asset.height),
                "sha256_raw": fp.meta.sha256_raw,
                "sha256_norm": fp.meta.sha256_norm,
                "phash_hex": fp.meta.phash_hex,
                "file_mtime": float(stat.st_mtime),
                "updated_at": now,
            }
        )
        feature_rows.append(
            {
                "image_id": asset.image_id,
                "doc_id": asset.doc_id,
                "doc_path": str(path),
                "file_mtime": float(stat.st_mtime),
                "page": int(asset.page),
                "image_index": int(asset.image_index),
                "width": int(asset.width),
                "height": int(asset.height),
                "sha256_norm": fp.meta.sha256_norm,
                "phash_hex": fp.meta.phash_hex,
                "feature_blob": serialize_feature_blob(fp, max_descriptor_rows=DEFAULT_FEATURE_DESCRIPTOR_ROWS),
                "updated_at": now,
            }
        )
    return {
        "doc_id": doc_id,
        "doc_path": str(path),
        "file_size": int(stat.st_size),
        "file_mtime": float(stat.st_mtime),
        "image_count": len(image_rows),
        "updated_at": time.time(),
        "image_rows": image_rows,
        "feature_rows": feature_rows,
    }


def _read_json(path: Path, default: Dict) -> Dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(default)


def _write_json_atomic(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_checkpoint_json(path: Path) -> Dict:
    return _read_json(
        path,
        {
            "next_cursor": 0,
            "has_more": False,
            "updated_at": None,
            "total_docs": 0,
            "corpus_path": str(IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH),
        },
    )


@dataclass
class _BKNode:
    value: int
    image_ids: List[str]
    children: Dict[int, int]


class _PhashBKTree:
    def __init__(self) -> None:
        self._nodes: List[_BKNode] = []

    def insert(self, value: int, image_id: str) -> None:
        if not self._nodes:
            self._nodes.append(_BKNode(value=value, image_ids=[image_id], children={}))
            return

        idx = 0
        while True:
            node = self._nodes[idx]
            dist = (value ^ node.value).bit_count()
            if dist == 0:
                node.image_ids.append(image_id)
                return

            child_idx = node.children.get(dist)
            if child_idx is None:
                new_idx = len(self._nodes)
                self._nodes.append(_BKNode(value=value, image_ids=[image_id], children={}))
                node.children[dist] = new_idx
                return
            idx = child_idx

    def query(self, value: int, radius: int) -> List[str]:
        if not self._nodes:
            return []

        radius = max(0, int(radius))
        out: List[str] = []
        stack = [0]
        while stack:
            idx = stack.pop()
            node = self._nodes[idx]
            dist = (value ^ node.value).bit_count()
            if dist <= radius:
                out.extend(node.image_ids)

            lower = dist - radius
            upper = dist + radius
            for child_dist, child_idx in node.children.items():
                if lower <= child_dist <= upper:
                    stack.append(child_idx)
        return out


class ImageCorpusManager:
    def __init__(
        self,
        index_path: Path = IMAGE_PLAGIARISM_INDEX_PATH,
        manifest_path: Path = IMAGE_PLAGIARISM_MANIFEST_PATH,
        checkpoint_path: Path = IMAGE_PLAGIARISM_CHECKPOINT_PATH,
        feature_db_path: Path = IMAGE_PLAGIARISM_FEATURE_DB_PATH,
        build_lock_path: Path = IMAGE_PLAGIARISM_BUILD_LOCK_PATH,
    ) -> None:
        self.index_path = Path(index_path)
        self.manifest_path = Path(manifest_path)
        self.checkpoint_path = Path(checkpoint_path)
        self.feature_db_path = Path(feature_db_path)
        self.build_lock_path = Path(build_lock_path)
        self.hasher = ImageHasher()

        self._index_cache: Optional[Dict] = None
        self._feature_conn: Optional[sqlite3.Connection] = None

        self._doc_fp_cache: Dict[
            Tuple[str, float],
            Dict[Tuple[int, int], Tuple[ImageAsset, RuntimeImageFingerprint]],
        ] = {}
        self._image_fp_cache: Dict[str, Tuple[ImageAsset, RuntimeImageFingerprint]] = {}
        self._image_fp_cache_limit = 5000

        self._fast_index_token: Optional[Tuple[object, int]] = None
        self._entry_by_image_id: Dict[str, Dict] = {}
        self._sha_to_image_ids: Dict[str, List[str]] = {}
        self._phash_int_by_image_id: Dict[str, int] = {}
        self._phash_tree = _PhashBKTree()

    def _db_index_snapshot(self) -> Dict:
        conn = self._get_feature_conn()
        state = self._load_checkpoint()
        documents: Dict[str, Dict] = {}
        images: Dict[str, Dict] = {}

        for row in conn.execute(
            "SELECT doc_id, doc_path, file_size, file_mtime, image_count, updated_at FROM documents"
        ).fetchall():
            documents[str(row[0])] = {
                "doc_id": str(row[0]),
                "doc_path": str(row[1]),
                "file_size": int(row[2] or 0),
                "file_mtime": float(row[3] or 0.0),
                "image_count": int(row[4] or 0),
                "updated_at": float(row[5] or 0.0),
            }

        for row in conn.execute(
            (
                "SELECT image_id, doc_id, doc_path, page, image_index, width, height, "
                "sha256_raw, sha256_norm, phash_hex, file_mtime, updated_at "
                "FROM images"
            )
        ).fetchall():
            images[str(row[0])] = {
                "image_id": str(row[0]),
                "doc_id": str(row[1]),
                "doc_path": str(row[2]),
                "page": int(row[3] or 0),
                "image_index": int(row[4] or 0),
                "width": int(row[5] or 0),
                "height": int(row[6] or 0),
                "sha256_raw": str(row[7] or ""),
                "sha256_norm": str(row[8] or ""),
                "phash_hex": str(row[9] or ""),
                "file_mtime": float(row[10] or 0.0),
                "updated_at": float(row[11] or 0.0),
            }

        return {
            "version": 3,
            "corpus_path": state.get("corpus_path", str(IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH)),
            "documents": documents,
            "images": images,
            "updated_at": state.get("updated_at"),
        }

    def status(self) -> Dict:
        index = self._load_index()
        ckpt = self._load_checkpoint()
        return {
            "index_path": str(self.index_path),
            "manifest_path": str(self.manifest_path),
            "checkpoint_path": str(self.checkpoint_path),
            "feature_db_path": str(self.feature_db_path),
            "build_lock_path": str(self.build_lock_path),
            "feature_db_exists": self.feature_db_path.exists(),
            "index_exists": self.feature_db_path.exists(),
            "indexed_images": len(index.get("images", {})),
            "indexed_docs": len(index.get("documents", {})),
            "updated_at": index.get("updated_at"),
            "corpus_path": index.get("corpus_path"),
            "checkpoint": ckpt,
            "local_root": str(IMAGE_PLAGIARISM_LOCAL_ROOT),
            "remote_root": str(IMAGE_PLAGIARISM_REMOTE_ROOT),
        }

    def reset(self) -> Dict:
        removed = []
        for p in (
            self.index_path,
            self.manifest_path,
            self.checkpoint_path,
            self.feature_db_path,
            self.build_lock_path,
        ):
            if p.exists():
                p.unlink()
                removed.append(str(p))
        self._index_cache = None
        self._doc_fp_cache.clear()
        self._image_fp_cache.clear()
        self._invalidate_fast_index()
        if self._feature_conn is not None:
            self._feature_conn.close()
            self._feature_conn = None
        return {"removed": removed}

    def close(self) -> None:
        if self._feature_conn is not None:
            self._feature_conn.close()
            self._feature_conn = None

    def shadow_db_path(self, job_id: str) -> Path:
        IMAGE_PLAGIARISM_SHADOW_DIR.mkdir(parents=True, exist_ok=True)
        return IMAGE_PLAGIARISM_SHADOW_DIR / f"{job_id}.sqlite3"

    def create_build_job(
        self,
        corpus_path: Optional[Path],
        limit: int,
        reset_cursor: bool,
    ) -> Dict:
        corpus_dir = Path(corpus_path or IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH)
        if not corpus_dir.exists() or not corpus_dir.is_dir():
            raise FileNotFoundError(f"corpus_path 不存在或不是目录: {corpus_dir}")
        conn = self._get_feature_conn()
        job_id = uuid.uuid4().hex
        now = time.time()
        conn.execute(
            (
                "INSERT INTO build_jobs("
                "job_id, status, corpus_path, limit_value, reset_cursor, created_at, updated_at, worker_pid"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (job_id, "queued", str(corpus_dir), int(limit), 1 if reset_cursor else 0, now, now, None),
        )
        conn.commit()
        return self.get_build_job(job_id) or {"job_id": job_id, "status": "queued"}

    def get_build_job(self, job_id: str) -> Optional[Dict]:
        conn = self._get_feature_conn()
        row = conn.execute(
            (
                "SELECT job_id, status, corpus_path, limit_value, reset_cursor, created_at, updated_at, "
                "started_at, finished_at, worker_pid, result_json, error_text "
                "FROM build_jobs WHERE job_id = ?"
            ),
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        result_json = row[10]
        result = None
        if result_json:
            try:
                result = json.loads(str(result_json))
            except Exception:
                result = None
        return {
            "job_id": str(row[0]),
            "status": str(row[1]),
            "corpus_path": str(row[2]),
            "limit": int(row[3] or 0),
            "reset_cursor": bool(row[4]),
            "created_at": float(row[5]) if row[5] is not None else None,
            "updated_at": float(row[6]) if row[6] is not None else None,
            "started_at": float(row[7]) if row[7] is not None else None,
            "finished_at": float(row[8]) if row[8] is not None else None,
            "worker_pid": int(row[9]) if row[9] is not None else None,
            "result": result,
            "error": str(row[11]) if row[11] is not None else None,
        }

    def start_build_job(self, job_id: str) -> Optional[Dict]:
        conn = self._get_feature_conn()
        now = time.time()
        cur = conn.execute(
            (
                "UPDATE build_jobs SET status = 'running', started_at = ?, updated_at = ? "
                "WHERE job_id = ? AND status = 'queued'"
            ),
            (now, now, job_id),
        )
        conn.commit()
        if cur.rowcount <= 0:
            return self.get_build_job(job_id)
        return self.get_build_job(job_id)

    def attach_build_job_pid(self, job_id: str, worker_pid: int) -> None:
        conn = self._get_feature_conn()
        conn.execute(
            "UPDATE build_jobs SET worker_pid = ?, updated_at = ? WHERE job_id = ?",
            (int(worker_pid), time.time(), job_id),
        )
        conn.commit()

    def finish_build_job(self, job_id: str, status: str, result: Optional[Dict], error: Optional[str]) -> None:
        conn = self._get_feature_conn()
        now = time.time()
        conn.execute(
            (
                "UPDATE build_jobs SET status = ?, updated_at = ?, finished_at = ?, worker_pid = NULL, "
                "result_json = ?, error_text = ? WHERE job_id = ?"
            ),
            (
                str(status),
                now,
                now,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error,
                job_id,
            ),
        )
        conn.commit()

    def promote_shadow_db(self, shadow_db_path: Path) -> None:
        shadow_db_path = Path(shadow_db_path)
        if not shadow_db_path.exists():
            raise FileNotFoundError(f"shadow db 不存在: {shadow_db_path}")
        lock_fp = self._acquire_build_lock()
        try:
            conn = self._get_feature_conn()
            shadow_alias = "shadowdb"
            conn.execute(f"ATTACH DATABASE ? AS {shadow_alias}", (str(shadow_db_path),))
            try:
                conn.execute("BEGIN IMMEDIATE")
                for table in ("documents", "images", "manifest_docs", "build_state", "image_features"):
                    conn.execute(f"DELETE FROM {table}")
                conn.execute(
                    "INSERT INTO documents SELECT * FROM shadowdb.documents"
                )
                conn.execute(
                    "INSERT INTO images SELECT * FROM shadowdb.images"
                )
                conn.execute(
                    "INSERT INTO manifest_docs SELECT * FROM shadowdb.manifest_docs"
                )
                conn.execute(
                    "INSERT INTO build_state SELECT * FROM shadowdb.build_state"
                )
                conn.execute(
                    "INSERT INTO image_features SELECT * FROM shadowdb.image_features"
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute(f"DETACH DATABASE {shadow_alias}")
            self._index_cache = None
            self._doc_fp_cache.clear()
            self._image_fp_cache.clear()
            self._invalidate_fast_index()
        finally:
            self._release_build_lock(lock_fp)

    def cleanup_shadow_db(self, shadow_db_path: Path) -> None:
        shadow_db_path = Path(shadow_db_path)
        candidates = [
            shadow_db_path,
            shadow_db_path.with_name(shadow_db_path.name + "-wal"),
            shadow_db_path.with_name(shadow_db_path.name + "-shm"),
        ]
        for path in candidates:
            if path.exists():
                path.unlink()

    def clone_active_db_to_shadow(self, shadow_db_path: Path) -> None:
        shadow_db_path = Path(shadow_db_path)
        self.cleanup_shadow_db(shadow_db_path)
        src = self._get_feature_conn()
        dst = sqlite3.connect(str(shadow_db_path), timeout=30.0, check_same_thread=False)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()

    def build_batch(
        self,
        corpus_path: Optional[Path] = None,
        limit: int = 20,
        reset_cursor: bool = False,
    ) -> Dict:
        t0 = time.time()
        limit = max(1, int(limit))
        corpus_dir = Path(corpus_path or IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH)
        if not corpus_dir.exists() or not corpus_dir.is_dir():
            raise FileNotFoundError(f"corpus_path 不存在或不是目录: {corpus_dir}")
        lock_fp = self._acquire_build_lock()
        try:
            conn = self._get_feature_conn()
            index = self._load_index()
            checkpoint = self._load_checkpoint()
            if index.get("corpus_path") != str(corpus_dir):
                reset_cursor = True
            if reset_cursor:
                checkpoint["next_cursor"] = 0

            self._assert_build_safety(corpus_dir=corpus_dir, checkpoint=checkpoint, limit=limit)
            all_docs, used_manifest_cache = self._resolve_docs_for_build(
                corpus_dir=corpus_dir,
                checkpoint=checkpoint,
                reset_cursor=reset_cursor,
            )
            # Second guard after corpus size is known to block pathological tiny-batch loops deterministically.
            self._assert_build_safety(
                corpus_dir=corpus_dir,
                checkpoint={**checkpoint, "total_docs": len(all_docs)},
                limit=limit,
            )

            cursor = int(checkpoint.get("next_cursor") or 0)
            if cursor < 0 or cursor >= len(all_docs):
                cursor = 0
            selected = all_docs[cursor: cursor + limit]

            processed = 0
            failed: List[Dict] = []
            indexed_images = 0
            skipped_docs = 0
            throttle_events = 0
            docs_to_process: List[Path] = []
            for path in selected:
                processed += 1
                if processed % IMAGE_BUILD_IOWAIT_CHECK_EVERY_DOCS == 0 and self._maybe_throttle_for_io_pressure():
                    throttle_events += 1
                if self._is_doc_unchanged(conn, path):
                    skipped_docs += 1
                    continue
                docs_to_process.append(path)

            if docs_to_process:
                max_workers = max(1, min(int(IMAGE_BUILD_FEATURE_WORKERS), 4, len(docs_to_process)))
                with ProcessPoolExecutor(max_workers=max_workers) as pool:
                    for path, result, error in pool.map(self._process_doc_for_build, [str(p) for p in docs_to_process]):
                        doc_id = Path(path).stem
                        if error is not None:
                            failed.append({"doc_id": doc_id, "path": path, "error": error})
                            continue
                        self._apply_doc_payload(conn, result)
                        indexed_images += int(result.get("image_count", 0) or 0)

            next_cursor = cursor + len(selected)
            has_more = next_cursor < len(all_docs)

            # full pass completed: prune deleted docs
            if not has_more:
                doc_ids_set = {p.stem for p in all_docs}
                removed_docs = [
                    str(row[0])
                    for row in conn.execute("SELECT doc_id FROM documents").fetchall()
                    if str(row[0]) not in doc_ids_set
                ]
                for did in removed_docs:
                    stale_ids = self._get_image_ids_for_doc(conn, did)
                    if stale_ids:
                        self._delete_feature_rows(conn, stale_ids)
                    conn.execute("DELETE FROM images WHERE doc_id = ?", (did,))
                    conn.execute("DELETE FROM documents WHERE doc_id = ?", (did,))

            now = time.time()
            self._write_checkpoint_db(
                conn=conn,
                next_cursor=next_cursor if has_more else 0,
                has_more=has_more,
                total_docs=len(all_docs),
                corpus_path=str(corpus_dir),
                updated_at=now,
            )
            conn.commit()

            self._index_cache = {
                "version": 3,
                "corpus_path": str(corpus_dir),
                "documents": {},
                "images": {},
                "updated_at": now,
            }
            self._doc_fp_cache.clear()
            self._image_fp_cache.clear()
            self._invalidate_fast_index()

            checkpoint = self._load_checkpoint(force_refresh=True)

            return {
                "phase": "build",
                "corpus_path": str(corpus_dir),
                "selected": len(selected),
                "processed": processed,
                "indexed_images": indexed_images,
                "skipped_docs": skipped_docs,
                "failed": len(failed),
                "remaining": max(0, len(all_docs) - next_cursor),
                "has_more": has_more,
                "next_cursor": checkpoint["next_cursor"],
                "total_docs": len(all_docs),
                "timings": {"total_seconds": round(time.time() - t0, 2)},
                "manifest_cache": bool(used_manifest_cache),
                "throttle_events": throttle_events,
                "failed_docs": failed,
            }
        finally:
            self._release_build_lock(lock_fp)

    def retrieve_candidates_for_query_image(
        self,
        query_asset: ImageAsset,
        query_fp: RuntimeImageFingerprint,
        hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX,
        top_k_coarse: int = 80,
        top_k_final: int = 8,
        exclude_doc_id: Optional[str] = None,
    ) -> Dict[str, object]:
        index = self._load_index()
        images_meta = index.get("images", {})
        if not images_meta:
            return {"exact_matches": [], "verify_candidates": [], "coarse_candidates": 0}

        self._ensure_fast_index(index)

        query_sha = query_fp.meta.sha256_norm
        if query_sha:
            exact_ids = self._sha_to_image_ids.get(query_sha, [])
            exact_matches: List[ImageMatch] = []
            for image_id in exact_ids:
                entry = self._entry_by_image_id.get(image_id)
                if not isinstance(entry, dict):
                    continue
                source_doc = str(entry.get("doc_id", ""))
                if exclude_doc_id and source_doc == exclude_doc_id:
                    continue
                exact_matches.append(
                    ImageMatch(
                        query_doc=query_asset.doc_id,
                        query_image_id=query_asset.image_id,
                        source_doc=source_doc,
                        source_image_id=str(entry.get("image_id", "")),
                        score=1.0,
                        hash_hamming=0,
                        hash_score=1.0,
                        inliers=0,
                        geometry_score=1.0,
                        level="high",
                        reason="exact_sha256_norm_index",
                        query_page=query_asset.page,
                        source_page=int(entry.get("page", 0) or 0),
                    )
                )
            if exact_matches:
                exact_matches.sort(key=lambda x: (x.source_doc, x.source_image_id))
                return {
                    "exact_matches": exact_matches[: max(1, int(top_k_final))],
                    "verify_candidates": [],
                    "coarse_candidates": len(exact_ids),
                }

        query_phash = query_fp.meta.phash_hex
        query_phash_int = phash_hex_to_int(query_phash)
        if query_phash_int is None:
            return {"exact_matches": [], "verify_candidates": [], "coarse_candidates": 0}

        candidate_ids = self._phash_tree.query(query_phash_int, int(hash_hamming_max))
        query_area = max(1.0, float(query_asset.width * query_asset.height))

        candidates: List[Tuple[int, Dict]] = []
        for image_id in candidate_ids:
            entry = self._entry_by_image_id.get(image_id)
            if not isinstance(entry, dict):
                continue
            source_doc = str(entry.get("doc_id", ""))
            if exclude_doc_id and source_doc == exclude_doc_id:
                continue

            source_area = max(1.0, float(int(entry.get("width", 0) or 0) * int(entry.get("height", 0) or 0)))
            area_ratio = query_area / source_area
            if area_ratio < 0.25 or area_ratio > 4.0:
                continue

            source_phash_int = self._phash_int_by_image_id.get(image_id)
            if source_phash_int is None:
                continue
            ham = (query_phash_int ^ source_phash_int).bit_count()
            if ham > hash_hamming_max:
                continue
            candidates.append((ham, entry))

        candidates.sort(key=lambda x: x[0])
        shortlisted = candidates[: max(1, int(top_k_coarse))]

        shortlisted_entries = [entry for _, entry in shortlisted]
        loaded_map = self._load_runtime_fps_for_entries(shortlisted_entries)
        verify_candidates: List[Tuple[ImageAsset, RuntimeImageFingerprint]] = []
        for entry in shortlisted_entries:
            image_id = str(entry.get("image_id", ""))
            loaded = loaded_map.get(image_id)
            if loaded is None:
                continue
            verify_candidates.append(loaded)

        return {
            "exact_matches": [],
            "verify_candidates": verify_candidates,
            "coarse_candidates": len(candidates),
        }

    def retrieve_matches_for_query_image(
        self,
        query_asset: ImageAsset,
        query_fp: RuntimeImageFingerprint,
        matcher: ImageMatcher,
        include_low: bool = False,
        hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX,
        top_k_coarse: int = 80,
        top_k_final: int = 8,
        exclude_doc_id: Optional[str] = None,
    ) -> List[ImageMatch]:
        retrieval = self.retrieve_candidates_for_query_image(
            query_asset=query_asset,
            query_fp=query_fp,
            hash_hamming_max=hash_hamming_max,
            top_k_coarse=top_k_coarse,
            top_k_final=top_k_final,
            exclude_doc_id=exclude_doc_id,
        )

        exact_matches = retrieval.get("exact_matches", [])
        if exact_matches:
            return list(exact_matches)[: max(1, int(top_k_final))]

        matches: List[ImageMatch] = []
        for source_asset, source_fp in retrieval.get("verify_candidates", []):
            m = matcher.compare(
                query_asset=query_asset,
                source_asset=source_asset,
                query_fp=query_fp,
                source_fp=source_fp,
            )
            if m is None:
                continue
            if not include_low and m.level == "low":
                continue
            matches.append(m)

        matches.sort(key=lambda x: (-x.score, x.source_doc, x.source_image_id))
        return matches[: max(1, int(top_k_final))]

    def get_image_bytes(self, image_id: str) -> Optional[bytes]:
        index = self._load_index()
        entry = (index.get("images", {}) or {}).get(image_id)
        if not isinstance(entry, dict):
            return None
        loaded = self._load_runtime_fp_from_index_entry(entry)
        if loaded is not None and loaded[0].image_bytes:
            return loaded[0].image_bytes
        return self._load_asset_bytes_from_doc(entry)

    def _scan_docs(self, corpus_dir: Path) -> List[Path]:
        docs = [p for p in corpus_dir.rglob("*.docx") if p.is_file()]
        docs.extend([p for p in corpus_dir.rglob("*.pdf") if p.is_file()])
        docs.sort(key=lambda p: str(p))
        return docs

    def _acquire_build_lock(self):
        self.build_lock_path.parent.mkdir(parents=True, exist_ok=True)
        fp = self.build_lock_path.open("a+")
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fp.close()
            raise ValueError("已有图片建库任务在运行中，请稍后再试（build lock）")
        fp.seek(0)
        fp.truncate()
        fp.write(str(time.time()))
        fp.flush()
        return fp

    @staticmethod
    def _release_build_lock(lock_fp) -> None:
        if lock_fp is None:
            return
        try:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            lock_fp.close()
        except Exception:
            pass

    def _resolve_docs_for_build(
        self,
        corpus_dir: Path,
        checkpoint: Dict,
        reset_cursor: bool,
    ) -> Tuple[List[Path], bool]:
        use_manifest_cache = (
            not reset_cursor
            and bool(checkpoint.get("has_more"))
            and str(checkpoint.get("corpus_path", "")) == str(corpus_dir)
        )
        if use_manifest_cache:
            conn = self._get_feature_conn()
            rows = conn.execute(
                "SELECT path FROM manifest_docs WHERE corpus_path = ? ORDER BY seq ASC",
                (str(corpus_dir),),
            ).fetchall()
            cached_paths = [Path(str(row[0])) for row in rows if str(row[0])]
            if cached_paths:
                return cached_paths, True

        all_docs = self._scan_docs(corpus_dir)
        conn = self._get_feature_conn()
        conn.execute("DELETE FROM manifest_docs WHERE corpus_path = ?", (str(corpus_dir),))
        rows = [
            (idx, p.stem, str(p), int(p.stat().st_size), float(p.stat().st_mtime), str(corpus_dir))
            for idx, p in enumerate(all_docs)
        ]
        conn.executemany(
            (
                "INSERT INTO manifest_docs(seq, doc_id, path, file_size, file_mtime, corpus_path) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            ),
            rows,
        )
        conn.commit()
        return all_docs, False

    @staticmethod
    def _process_doc_for_build(path_str: str) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            return path_str, _build_doc_payload(path_str), None
        except Exception as exc:
            return path_str, None, str(exc)

    def _is_doc_unchanged(self, conn: sqlite3.Connection, path: Path) -> bool:
        row = conn.execute(
            "SELECT file_size, file_mtime FROM documents WHERE doc_id = ?",
            (path.stem,),
        ).fetchone()
        if row is None:
            return False
        stat = path.stat()
        return int(row[0] or 0) == int(stat.st_size) and abs(float(row[1] or 0.0) - float(stat.st_mtime)) < 1e-6

    def _apply_doc_payload(self, conn: sqlite3.Connection, payload: Dict) -> None:
        doc_id = str(payload["doc_id"])
        stale_ids = self._get_image_ids_for_doc(conn, doc_id)
        if stale_ids:
            self._delete_feature_rows(conn, stale_ids)
        conn.execute("DELETE FROM images WHERE doc_id = ?", (doc_id,))

        for row in payload.get("image_rows", []):
            conn.execute(
                (
                    "INSERT INTO images("
                    "image_id, doc_id, doc_path, page, image_index, width, height, "
                    "sha256_raw, sha256_norm, phash_hex, file_mtime, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    row["image_id"],
                    row["doc_id"],
                    row["doc_path"],
                    row["page"],
                    row["image_index"],
                    row["width"],
                    row["height"],
                    row["sha256_raw"],
                    row["sha256_norm"],
                    row["phash_hex"],
                    row["file_mtime"],
                    row["updated_at"],
                ),
            )
        for row in payload.get("feature_rows", []):
            conn.execute(
                (
                    "INSERT INTO image_features("
                    "image_id, doc_id, doc_path, file_mtime, page, image_index, width, height, "
                    "sha256_norm, phash_hex, feature_blob, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    row["image_id"],
                    row["doc_id"],
                    row["doc_path"],
                    row["file_mtime"],
                    row["page"],
                    row["image_index"],
                    row["width"],
                    row["height"],
                    row["sha256_norm"],
                    row["phash_hex"],
                    sqlite3.Binary(row["feature_blob"]),
                    row["updated_at"],
                ),
            )
        conn.execute(
            (
                "INSERT INTO documents(doc_id, doc_path, file_size, file_mtime, image_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(doc_id) DO UPDATE SET "
                "doc_path=excluded.doc_path, file_size=excluded.file_size, "
                "file_mtime=excluded.file_mtime, image_count=excluded.image_count, "
                "updated_at=excluded.updated_at"
            ),
            (
                payload["doc_id"],
                payload["doc_path"],
                payload["file_size"],
                payload["file_mtime"],
                payload["image_count"],
                payload["updated_at"],
            ),
        )

    def _assert_build_safety(
        self,
        corpus_dir: Path,
        checkpoint: Dict,
        limit: int,
    ) -> None:
        estimated_total = 0
        if str(checkpoint.get("corpus_path", "")) == str(corpus_dir):
            estimated_total = int(checkpoint.get("total_docs") or 0)
        if estimated_total <= 0:
            conn = self._get_feature_conn()
            row = conn.execute(
                "SELECT COUNT(1) FROM manifest_docs WHERE corpus_path = ?",
                (str(corpus_dir),),
            ).fetchone()
            estimated_total = int(row[0] or 0) if row else 0

        if (
            estimated_total >= IMAGE_BUILD_LARGE_CORPUS_DOC_THRESHOLD
            and int(limit) < IMAGE_BUILD_MIN_LIMIT_LARGE_CORPUS
        ):
            raise ValueError(
                (
                    "build-batch 已触发 IO 保护阈值："
                    f"当前语料约 {estimated_total} 文档，limit={limit} 过小，"
                    f"请设置 limit >= {IMAGE_BUILD_MIN_LIMIT_LARGE_CORPUS} "
                    "（建议 3000~5000），避免小批次循环导致磁盘 IO 打满。"
                )
            )

    def _maybe_throttle_for_io_pressure(self) -> bool:
        before = self._read_proc_stat_cpu_times()
        if before is None:
            return False
        time.sleep(IMAGE_BUILD_IOWAIT_SAMPLE_SECONDS)
        after = self._read_proc_stat_cpu_times()
        if after is None:
            return False

        total_delta = after[0] - before[0]
        iowait_delta = after[1] - before[1]
        if total_delta <= 0:
            return False

        ratio = float(iowait_delta) / float(total_delta)
        if ratio < IMAGE_BUILD_IOWAIT_RATIO_THRESHOLD:
            return False

        time.sleep(IMAGE_BUILD_IOWAIT_SLEEP_SECONDS)
        return True

    @staticmethod
    def _read_proc_stat_cpu_times() -> Optional[Tuple[int, int]]:
        try:
            line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        except Exception:
            return None
        parts = line.split()
        if len(parts) < 7 or parts[0] != "cpu":
            return None
        values = [int(item) for item in parts[1:]]
        total = sum(values)
        iowait = values[4] if len(values) > 4 else 0
        return total, iowait

    def _load_runtime_fp_from_index_entry(
        self,
        entry: Dict,
    ) -> Optional[Tuple[ImageAsset, RuntimeImageFingerprint]]:
        image_id = str(entry.get("image_id", ""))
        if image_id and image_id in self._image_fp_cache:
            return self._image_fp_cache[image_id]

        loaded = self._load_runtime_fp_from_feature_db(entry)
        if loaded is not None:
            self._put_feature_cache(image_id, loaded)
            return loaded

        # Fallback path for legacy indexes without persisted features.
        doc_path = Path(str(entry.get("doc_path", "")))
        if not doc_path.exists() or not doc_path.is_file():
            return None
        file_mtime = float(entry.get("file_mtime") or 0.0)
        key = (str(doc_path), file_mtime)
        cached = self._doc_fp_cache.get(key)
        if cached is None:
            try:
                file_data = doc_path.read_bytes()
            except Exception:
                return None
            doc_id = str(entry.get("doc_id") or doc_path.stem)
            assets = extract_images_from_file(doc_id=doc_id, file_name=doc_path.name, file_data=file_data)
            by_pos: Dict[Tuple[int, int], Tuple[ImageAsset, RuntimeImageFingerprint]] = {}
            for asset in assets:
                fp = self.hasher.build(asset)
                if fp is None:
                    continue
                by_pos[(int(asset.page), int(asset.image_index))] = (asset, fp)
            self._doc_fp_cache[key] = by_pos
            cached = by_pos

        pos = (int(entry.get("page", 0) or 0), int(entry.get("image_index", 0) or 0))
        loaded = cached.get(pos)
        if loaded is None:
            return None

        # Backfill the feature DB lazily to avoid repeated doc parse.
        try:
            conn = self._get_feature_conn()
            self._upsert_feature_row(
                conn=conn,
                asset=loaded[0],
                fp=loaded[1],
                doc_path=doc_path,
                file_mtime=file_mtime,
            )
            conn.commit()
        except Exception:
            pass

        source_asset = self._strip_asset_bytes(loaded[0])
        light_fp = self._to_lightweight_fp(loaded[1])
        out = (source_asset, light_fp)
        self._put_feature_cache(image_id, out)
        return out

    def _load_runtime_fp_from_feature_db(
        self,
        entry: Dict,
    ) -> Optional[Tuple[ImageAsset, RuntimeImageFingerprint]]:
        image_id = str(entry.get("image_id", ""))
        if not image_id:
            return None

        conn = self._get_feature_conn()
        row = conn.execute(
            (
                "SELECT doc_id, doc_path, page, image_index, width, height, "
                "sha256_norm, phash_hex, feature_blob "
                "FROM image_features WHERE image_id = ?"
            ),
            (image_id,),
        ).fetchone()
        if row is None:
            return None
        return self._build_runtime_from_feature_row(image_id=image_id, entry=entry, row=row)

    def _load_runtime_fps_for_entries(
        self,
        entries: List[Dict],
    ) -> Dict[str, Tuple[ImageAsset, RuntimeImageFingerprint]]:
        out: Dict[str, Tuple[ImageAsset, RuntimeImageFingerprint]] = {}
        pending_entries: List[Dict] = []
        pending_ids: List[str] = []

        for entry in entries:
            image_id = str(entry.get("image_id", ""))
            if not image_id:
                continue
            cached = self._image_fp_cache.get(image_id)
            if cached is not None:
                out[image_id] = cached
                continue
            pending_entries.append(entry)
            pending_ids.append(image_id)

        if not pending_ids:
            return out

        # Batch fetch feature rows in one SQL roundtrip to avoid N selects per query image.
        conn = self._get_feature_conn()
        placeholders = ",".join("?" for _ in pending_ids)
        rows = conn.execute(
            (
                "SELECT image_id, doc_id, doc_path, page, image_index, width, height, "
                "sha256_norm, phash_hex, feature_blob "
                f"FROM image_features WHERE image_id IN ({placeholders})"
            ),
            tuple(pending_ids),
        ).fetchall()
        row_map: Dict[str, Tuple] = {}
        for row in rows:
            row_map[str(row[0])] = row

        missing_entries: List[Dict] = []
        for entry in pending_entries:
            image_id = str(entry.get("image_id", ""))
            row = row_map.get(image_id)
            if row is None:
                missing_entries.append(entry)
                continue
            loaded = self._build_runtime_from_feature_row(image_id=image_id, entry=entry, row=row[1:])
            self._put_feature_cache(image_id, loaded)
            out[image_id] = loaded

        for entry in missing_entries:
            image_id = str(entry.get("image_id", ""))
            loaded = self._load_runtime_fp_from_index_entry(entry)
            if loaded is None:
                continue
            out[image_id] = loaded
        return out

    def _build_runtime_from_feature_row(
        self,
        image_id: str,
        entry: Dict,
        row: Tuple,
    ) -> Tuple[ImageAsset, RuntimeImageFingerprint]:
        doc_id = str(row[0] or entry.get("doc_id", ""))
        doc_path = str(row[1] or entry.get("doc_path", ""))
        page = int(row[2] or entry.get("page", 0) or 0)
        image_index = int(row[3] or entry.get("image_index", 0) or 0)
        width = int(row[4] or entry.get("width", 0) or 0)
        height = int(row[5] or entry.get("height", 0) or 0)
        sha256_norm = str(row[6] or entry.get("sha256_norm", ""))
        phash_hex = str(row[7] or entry.get("phash_hex", ""))
        feature_blob = bytes(row[8] or b"")

        keypoint_pts, descriptors = deserialize_feature_blob(feature_blob)

        meta = ImageFingerprint(
            image_id=image_id,
            doc_id=doc_id,
            sha256_raw=str(entry.get("sha256_raw", "")),
            sha256_norm=sha256_norm,
            phash_hex=phash_hex,
            width=width,
            height=height,
            keypoints=int(len(keypoint_pts)),
            descriptor_rows=int(descriptors.shape[0]) if descriptors is not None else 0,
        )
        asset = ImageAsset(
            doc_id=doc_id,
            image_id=image_id,
            file_name=Path(doc_path).name,
            page=page,
            image_index=image_index,
            image_bytes=b"",
            width=width,
            height=height,
        )
        fp = RuntimeImageFingerprint(
            meta=meta,
            normalized_bgr=np.empty((0, 0, 3), dtype=np.uint8),
            gray=np.empty((0, 0), dtype=np.uint8),
            keypoint_pts=keypoint_pts,
            descriptors=descriptors,
        )
        return asset, fp

    def _load_asset_bytes_from_doc(self, entry: Dict) -> Optional[bytes]:
        doc_path = Path(str(entry.get("doc_path", "")))
        if not doc_path.exists() or not doc_path.is_file():
            return None
        try:
            file_data = doc_path.read_bytes()
        except Exception:
            return None

        doc_id = str(entry.get("doc_id") or doc_path.stem)
        page = int(entry.get("page", 0) or 0)
        image_index = int(entry.get("image_index", 0) or 0)
        try:
            assets = extract_images_from_file(doc_id=doc_id, file_name=doc_path.name, file_data=file_data)
        except Exception:
            return None
        for asset in assets:
            if int(asset.page) == page and int(asset.image_index) == image_index:
                return asset.image_bytes
        return None

    def _put_feature_cache(
        self,
        image_id: str,
        value: Tuple[ImageAsset, RuntimeImageFingerprint],
    ) -> None:
        if not image_id:
            return
        self._image_fp_cache[image_id] = value
        if len(self._image_fp_cache) > self._image_fp_cache_limit:
            stale_key = next(iter(self._image_fp_cache.keys()))
            self._image_fp_cache.pop(stale_key, None)

    def _to_lightweight_fp(self, fp: RuntimeImageFingerprint) -> RuntimeImageFingerprint:
        return RuntimeImageFingerprint(
            meta=fp.meta,
            normalized_bgr=np.empty((0, 0, 3), dtype=np.uint8),
            gray=np.empty((0, 0), dtype=np.uint8),
            keypoint_pts=fp.keypoint_pts,
            descriptors=fp.descriptors,
        )

    def _strip_asset_bytes(self, asset: ImageAsset) -> ImageAsset:
        return ImageAsset(
            doc_id=asset.doc_id,
            image_id=asset.image_id,
            file_name=asset.file_name,
            page=asset.page,
            image_index=asset.image_index,
            image_bytes=b"",
            width=asset.width,
            height=asset.height,
        )

    def _ensure_fast_index(self, index: Dict) -> None:
        images_meta = index.get("images", {}) or {}
        token = (index.get("updated_at"), len(images_meta))
        if self._fast_index_token == token:
            return

        entry_by_image_id: Dict[str, Dict] = {}
        sha_to_image_ids: Dict[str, List[str]] = {}
        phash_int_by_image_id: Dict[str, int] = {}
        tree = _PhashBKTree()

        for image_id, raw_entry in images_meta.items():
            if not isinstance(raw_entry, dict):
                continue
            iid = str(raw_entry.get("image_id") or image_id)
            if not iid:
                continue

            entry_by_image_id[iid] = raw_entry

            sha = str(raw_entry.get("sha256_norm", ""))
            if sha:
                sha_to_image_ids.setdefault(sha, []).append(iid)

            phash_int = phash_hex_to_int(str(raw_entry.get("phash_hex", "")))
            if phash_int is None:
                continue
            phash_int_by_image_id[iid] = phash_int
            tree.insert(phash_int, iid)

        self._entry_by_image_id = entry_by_image_id
        self._sha_to_image_ids = sha_to_image_ids
        self._phash_int_by_image_id = phash_int_by_image_id
        self._phash_tree = tree
        self._fast_index_token = token

    def _invalidate_fast_index(self) -> None:
        self._fast_index_token = None
        self._entry_by_image_id = {}
        self._sha_to_image_ids = {}
        self._phash_int_by_image_id = {}
        self._phash_tree = _PhashBKTree()

    def _get_feature_conn(self) -> sqlite3.Connection:
        if self._feature_conn is None:
            self.feature_db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.feature_db_path), timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS documents ("
                    "doc_id TEXT PRIMARY KEY,"
                    "doc_path TEXT NOT NULL,"
                    "file_size INTEGER NOT NULL,"
                    "file_mtime REAL NOT NULL,"
                    "image_count INTEGER NOT NULL,"
                    "updated_at REAL NOT NULL"
                    ")"
                )
            )
            conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS images ("
                    "image_id TEXT PRIMARY KEY,"
                    "doc_id TEXT NOT NULL,"
                    "doc_path TEXT NOT NULL,"
                    "page INTEGER NOT NULL,"
                    "image_index INTEGER NOT NULL,"
                    "width INTEGER NOT NULL,"
                    "height INTEGER NOT NULL,"
                    "sha256_raw TEXT,"
                    "sha256_norm TEXT,"
                    "phash_hex TEXT,"
                    "file_mtime REAL NOT NULL,"
                    "updated_at REAL NOT NULL"
                    ")"
                )
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_doc_id ON images(doc_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_sha_norm ON images(sha256_norm)")
            conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS manifest_docs ("
                    "seq INTEGER NOT NULL,"
                    "doc_id TEXT NOT NULL,"
                    "path TEXT NOT NULL,"
                    "file_size INTEGER NOT NULL,"
                    "file_mtime REAL NOT NULL,"
                    "corpus_path TEXT NOT NULL,"
                    "PRIMARY KEY (corpus_path, seq)"
                    ")"
                )
            )
            conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS build_state ("
                    "id INTEGER PRIMARY KEY CHECK (id = 1),"
                    "next_cursor INTEGER NOT NULL,"
                    "has_more INTEGER NOT NULL,"
                    "updated_at REAL,"
                    "total_docs INTEGER NOT NULL,"
                    "corpus_path TEXT NOT NULL"
                    ")"
                )
            )
            conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS build_jobs ("
                    "job_id TEXT PRIMARY KEY,"
                    "status TEXT NOT NULL,"
                    "corpus_path TEXT NOT NULL,"
                    "limit_value INTEGER NOT NULL,"
                    "reset_cursor INTEGER NOT NULL,"
                    "created_at REAL NOT NULL,"
                    "updated_at REAL NOT NULL,"
                    "started_at REAL,"
                    "finished_at REAL,"
                    "worker_pid INTEGER,"
                    "result_json TEXT,"
                    "error_text TEXT"
                    ")"
                )
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_build_jobs_status ON build_jobs(status)")
            conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS image_features ("
                    "image_id TEXT PRIMARY KEY,"
                    "doc_id TEXT NOT NULL,"
                    "doc_path TEXT NOT NULL,"
                    "file_mtime REAL NOT NULL,"
                    "page INTEGER NOT NULL,"
                    "image_index INTEGER NOT NULL,"
                    "width INTEGER NOT NULL,"
                    "height INTEGER NOT NULL,"
                    "sha256_norm TEXT,"
                    "phash_hex TEXT,"
                    "feature_blob BLOB,"
                    "updated_at REAL NOT NULL"
                    ")"
                )
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_features_sha_norm ON image_features(sha256_norm)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_features_doc_id ON image_features(doc_id)")
            self._ensure_runtime_schema(conn)
            self._maybe_migrate_legacy_json(conn)
            conn.commit()
            self._feature_conn = conn
        return self._feature_conn

    @staticmethod
    def _ensure_runtime_schema(conn: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(build_jobs)").fetchall()
        }
        if "worker_pid" not in columns:
            conn.execute("ALTER TABLE build_jobs ADD COLUMN worker_pid INTEGER")

    def _delete_feature_rows(self, conn: sqlite3.Connection, image_ids: List[str]) -> None:
        if not image_ids:
            return
        conn.executemany(
            "DELETE FROM image_features WHERE image_id = ?",
            [(iid,) for iid in image_ids],
        )
        for iid in image_ids:
            self._image_fp_cache.pop(iid, None)

    def _get_image_ids_for_doc(self, conn: sqlite3.Connection, doc_id: str) -> List[str]:
        return [str(row[0]) for row in conn.execute("SELECT image_id FROM images WHERE doc_id = ?", (doc_id,)).fetchall()]

    def _write_checkpoint_db(
        self,
        conn: sqlite3.Connection,
        next_cursor: int,
        has_more: bool,
        total_docs: int,
        corpus_path: str,
        updated_at: float,
    ) -> None:
        conn.execute(
            (
                "INSERT INTO build_state(id, next_cursor, has_more, updated_at, total_docs, corpus_path) "
                "VALUES (1, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "next_cursor=excluded.next_cursor, has_more=excluded.has_more, updated_at=excluded.updated_at, "
                "total_docs=excluded.total_docs, corpus_path=excluded.corpus_path"
            ),
            (int(next_cursor), 1 if has_more else 0, float(updated_at), int(total_docs), str(corpus_path)),
        )

    def _maybe_migrate_legacy_json(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT COUNT(1) FROM images").fetchone()
        has_db_images = bool(row and int(row[0] or 0) > 0)
        row = conn.execute("SELECT COUNT(1) FROM documents").fetchone()
        has_db_docs = bool(row and int(row[0] or 0) > 0)
        row = conn.execute("SELECT COUNT(1) FROM manifest_docs").fetchone()
        has_manifest = bool(row and int(row[0] or 0) > 0)
        row = conn.execute("SELECT COUNT(1) FROM build_state").fetchone()
        has_checkpoint = bool(row and int(row[0] or 0) > 0)

        if not has_db_docs or not has_db_images:
            legacy_index = _read_json(
                self.index_path,
                {
                    "documents": {},
                    "images": {},
                },
            )
            documents = legacy_index.get("documents", {}) or {}
            images = legacy_index.get("images", {}) or {}
            if not has_db_docs and isinstance(documents, dict) and documents:
                conn.executemany(
                    (
                        "INSERT OR REPLACE INTO documents(doc_id, doc_path, file_size, file_mtime, image_count, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        (
                            str(item.get("doc_id") or doc_id),
                            str(item.get("doc_path", "")),
                            int(item.get("file_size", 0) or 0),
                            float(item.get("file_mtime", 0.0) or 0.0),
                            int(item.get("image_count", 0) or 0),
                            float(item.get("updated_at", 0.0) or 0.0),
                        )
                        for doc_id, item in documents.items()
                        if isinstance(item, dict)
                    ],
                )
            if not has_db_images and isinstance(images, dict) and images:
                conn.executemany(
                    (
                        "INSERT OR REPLACE INTO images("
                        "image_id, doc_id, doc_path, page, image_index, width, height, "
                        "sha256_raw, sha256_norm, phash_hex, file_mtime, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        (
                            str(item.get("image_id") or image_id),
                            str(item.get("doc_id", "")),
                            str(item.get("doc_path", "")),
                            int(item.get("page", 0) or 0),
                            int(item.get("image_index", 0) or 0),
                            int(item.get("width", 0) or 0),
                            int(item.get("height", 0) or 0),
                            str(item.get("sha256_raw", "")),
                            str(item.get("sha256_norm", "")),
                            str(item.get("phash_hex", "")),
                            float(item.get("file_mtime", 0.0) or 0.0),
                            float(item.get("updated_at", 0.0) or 0.0),
                        )
                        for image_id, item in images.items()
                        if isinstance(item, dict)
                    ],
                )

        if not has_manifest:
            legacy_manifest = _read_json(self.manifest_path, {})
            if isinstance(legacy_manifest.get("docs"), list) and legacy_manifest.get("docs"):
                conn.executemany(
                    (
                        "INSERT OR REPLACE INTO manifest_docs(seq, doc_id, path, file_size, file_mtime, corpus_path) "
                        "VALUES (?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        (
                            idx,
                            str(item.get("doc_id", "")),
                            str(item.get("path", "")),
                            int(item.get("file_size", 0) or 0),
                            float(item.get("file_mtime", 0.0) or 0.0),
                            str(legacy_manifest.get("corpus_path", IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH)),
                        )
                        for idx, item in enumerate(legacy_manifest.get("docs", []))
                        if isinstance(item, dict)
                    ],
                )

        if not has_checkpoint:
            legacy_checkpoint = _load_checkpoint_json(self.checkpoint_path)
            self._write_checkpoint_db(
                conn=conn,
                next_cursor=int(legacy_checkpoint.get("next_cursor") or 0),
                has_more=bool(legacy_checkpoint.get("has_more")),
                total_docs=int(legacy_checkpoint.get("total_docs") or 0),
                corpus_path=str(legacy_checkpoint.get("corpus_path", IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH)),
                updated_at=float(legacy_checkpoint.get("updated_at") or 0.0),
            )

    def _upsert_feature_row(
        self,
        conn: sqlite3.Connection,
        asset: ImageAsset,
        fp: RuntimeImageFingerprint,
        doc_path: Path,
        file_mtime: float,
    ) -> None:
        blob = serialize_feature_blob(fp, max_descriptor_rows=DEFAULT_FEATURE_DESCRIPTOR_ROWS)
        conn.execute(
            (
                "INSERT INTO image_features("
                "image_id, doc_id, doc_path, file_mtime, page, image_index, width, height, "
                "sha256_norm, phash_hex, feature_blob, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(image_id) DO UPDATE SET "
                "doc_id=excluded.doc_id, "
                "doc_path=excluded.doc_path, "
                "file_mtime=excluded.file_mtime, "
                "page=excluded.page, "
                "image_index=excluded.image_index, "
                "width=excluded.width, "
                "height=excluded.height, "
                "sha256_norm=excluded.sha256_norm, "
                "phash_hex=excluded.phash_hex, "
                "feature_blob=excluded.feature_blob, "
                "updated_at=excluded.updated_at"
            ),
            (
                asset.image_id,
                asset.doc_id,
                str(doc_path),
                float(file_mtime),
                int(asset.page),
                int(asset.image_index),
                int(asset.width),
                int(asset.height),
                fp.meta.sha256_norm,
                fp.meta.phash_hex,
                sqlite3.Binary(blob),
                time.time(),
            ),
        )

    def _load_index(self) -> Dict:
        if self._index_cache is not None:
            return self._index_cache
        data = self._db_index_snapshot()
        self._index_cache = data
        return data

    def _load_checkpoint(self, force_refresh: bool = False) -> Dict:
        if force_refresh:
            self._index_cache = None
        conn = self._get_feature_conn()
        row = conn.execute(
            "SELECT next_cursor, has_more, updated_at, total_docs, corpus_path FROM build_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return {
                "next_cursor": 0,
                "has_more": False,
                "updated_at": None,
                "total_docs": 0,
                "corpus_path": str(IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH),
            }
        return {
            "next_cursor": int(row[0] or 0),
            "has_more": bool(row[1]),
            "updated_at": float(row[2]) if row[2] is not None else None,
            "total_docs": int(row[3] or 0),
            "corpus_path": str(row[4] or IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH),
        }


def read_status() -> Dict:
    return ImageCorpusManager().status()


def resolve_project_doc(project_id: str, year: str, read_remote_if_missing: bool = True) -> Dict:
    candidates = [
        IMAGE_PLAGIARISM_LOCAL_ROOT / "sbs_5000" / f"{project_id}.docx",
        IMAGE_PLAGIARISM_LOCAL_ROOT / "sbs_10000" / f"{project_id}.docx",
        IMAGE_PLAGIARISM_LOCAL_ROOT / str(year) / "sbs" / f"{project_id}.docx",
        IMAGE_PLAGIARISM_LOCAL_ROOT / f"{project_id}.docx",
    ]
    local_path: Optional[Path] = next((p for p in candidates if p.is_file()), None)
    remote_path = IMAGE_PLAGIARISM_REMOTE_ROOT / str(year) / "sbs" / f"{project_id}.docx"
    remote_exists = remote_path.is_file()

    resolved_path: Optional[Path] = local_path
    storage = "local" if local_path else None
    if resolved_path is None and read_remote_if_missing and remote_exists:
        resolved_path = remote_path
        storage = "remote"

    return {
        "resolved_path": resolved_path,
        "storage": storage,
        "expected_local_paths": [str(p) for p in candidates],
        "remote_path": str(remote_path),
        "remote_exists": bool(remote_exists),
    }
