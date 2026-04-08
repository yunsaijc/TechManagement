"""Corpus manager for image plagiarism retrieval."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import (
    DEFAULT_HASH_HAMMING_MAX,
    IMAGE_PLAGIARISM_CHECKPOINT_PATH,
    IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH,
    IMAGE_PLAGIARISM_INDEX_PATH,
    IMAGE_PLAGIARISM_LOCAL_ROOT,
    IMAGE_PLAGIARISM_MANIFEST_PATH,
    IMAGE_PLAGIARISM_REMOTE_ROOT,
)
from .extractor import extract_images_from_file
from .hashing import ImageHasher, RuntimeImageFingerprint, phash_hamming
from .matcher import ImageMatcher
from .schemas import ImageAsset, ImageMatch


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


class ImageCorpusManager:
    def __init__(
        self,
        index_path: Path = IMAGE_PLAGIARISM_INDEX_PATH,
        manifest_path: Path = IMAGE_PLAGIARISM_MANIFEST_PATH,
        checkpoint_path: Path = IMAGE_PLAGIARISM_CHECKPOINT_PATH,
    ) -> None:
        self.index_path = Path(index_path)
        self.manifest_path = Path(manifest_path)
        self.checkpoint_path = Path(checkpoint_path)
        self.hasher = ImageHasher()

        self._index_cache: Optional[Dict] = None
        self._doc_fp_cache: Dict[Tuple[str, float], Dict[Tuple[int, int], Tuple[ImageAsset, RuntimeImageFingerprint]]] = {}

    def status(self) -> Dict:
        index = self._load_index()
        ckpt = self._load_checkpoint()
        return {
            "index_path": str(self.index_path),
            "manifest_path": str(self.manifest_path),
            "checkpoint_path": str(self.checkpoint_path),
            "index_exists": self.index_path.exists(),
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
        for p in (self.index_path, self.manifest_path, self.checkpoint_path):
            if p.exists():
                p.unlink()
                removed.append(str(p))
        self._index_cache = None
        self._doc_fp_cache.clear()
        return {"removed": removed}

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

        index = self._load_index()
        checkpoint = self._load_checkpoint()
        if index.get("corpus_path") != str(corpus_dir):
            reset_cursor = True
        if reset_cursor:
            checkpoint["next_cursor"] = 0

        all_docs = self._scan_docs(corpus_dir)
        manifest = {
            "corpus_path": str(corpus_dir),
            "total_docs": len(all_docs),
            "updated_at": time.time(),
            "docs": [
                {
                    "doc_id": p.stem,
                    "path": str(p),
                    "file_size": p.stat().st_size,
                    "file_mtime": p.stat().st_mtime,
                }
                for p in all_docs
            ],
        }
        _write_json_atomic(self.manifest_path, manifest)

        cursor = int(checkpoint.get("next_cursor") or 0)
        if cursor < 0 or cursor >= len(all_docs):
            cursor = 0
        selected = all_docs[cursor: cursor + limit]

        processed = 0
        failed: List[Dict] = []
        indexed_images = 0
        docs_meta = index.setdefault("documents", {})
        images_meta = index.setdefault("images", {})

        for path in selected:
            processed += 1
            doc_id = path.stem
            try:
                file_data = path.read_bytes()
                assets = extract_images_from_file(doc_id=doc_id, file_name=path.name, file_data=file_data)
                # clear old image entries for this doc
                stale_ids = [iid for iid, item in images_meta.items() if str(item.get("doc_id", "")) == doc_id]
                for iid in stale_ids:
                    images_meta.pop(iid, None)

                image_count = 0
                for asset in assets:
                    fp = self.hasher.build(asset)
                    if fp is None:
                        continue
                    image_count += 1
                    images_meta[asset.image_id] = {
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
                        "file_mtime": path.stat().st_mtime,
                        "updated_at": time.time(),
                    }
                docs_meta[doc_id] = {
                    "doc_id": doc_id,
                    "doc_path": str(path),
                    "file_size": path.stat().st_size,
                    "file_mtime": path.stat().st_mtime,
                    "image_count": image_count,
                    "updated_at": time.time(),
                }
                indexed_images += image_count
            except Exception as exc:
                failed.append({"doc_id": doc_id, "path": str(path), "error": str(exc)})

        next_cursor = cursor + len(selected)
        has_more = next_cursor < len(all_docs)

        # full pass completed: prune deleted docs
        if not has_more:
            doc_ids_set = {p.stem for p in all_docs}
            removed_docs = [did for did in list(docs_meta.keys()) if did not in doc_ids_set]
            for did in removed_docs:
                docs_meta.pop(did, None)
                stale_ids = [iid for iid, item in list(images_meta.items()) if str(item.get("doc_id", "")) == did]
                for iid in stale_ids:
                    images_meta.pop(iid, None)

        index.update(
            {
                "version": 1,
                "corpus_path": str(corpus_dir),
                "updated_at": time.time(),
            }
        )
        _write_json_atomic(self.index_path, index)
        self._index_cache = index

        checkpoint = {
            "next_cursor": next_cursor if has_more else 0,
            "has_more": has_more,
            "updated_at": time.time(),
            "total_docs": len(all_docs),
            "corpus_path": str(corpus_dir),
        }
        _write_json_atomic(self.checkpoint_path, checkpoint)

        return {
            "phase": "build",
            "corpus_path": str(corpus_dir),
            "selected": len(selected),
            "processed": processed,
            "indexed_images": indexed_images,
            "failed": len(failed),
            "remaining": max(0, len(all_docs) - next_cursor),
            "has_more": has_more,
            "next_cursor": checkpoint["next_cursor"],
            "total_docs": len(all_docs),
            "timings": {"total_seconds": round(time.time() - t0, 2)},
            "failed_docs": failed,
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
        index = self._load_index()
        images_meta = index.get("images", {})
        if not images_meta:
            return []

        candidates: List[Tuple[int, int, Dict]] = []
        query_sha = query_fp.meta.sha256_norm
        query_phash = query_fp.meta.phash_hex

        for entry in images_meta.values():
            src_doc = str(entry.get("doc_id", ""))
            if exclude_doc_id and src_doc == exclude_doc_id:
                continue
            src_sha = str(entry.get("sha256_norm", ""))
            if query_sha and src_sha and query_sha == src_sha:
                candidates.append((0, 0, entry))
                continue
            ham = phash_hamming(query_phash, str(entry.get("phash_hex", "")))
            if ham <= hash_hamming_max:
                candidates.append((1, ham, entry))

        candidates.sort(key=lambda x: (x[0], x[1]))
        shortlisted = candidates[: max(1, int(top_k_coarse))]

        matches: List[ImageMatch] = []
        for _, _, entry in shortlisted:
            loaded = self._load_runtime_fp_from_index_entry(entry)
            if loaded is None:
                continue
            source_asset, source_fp = loaded
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
        if loaded is None:
            return None
        asset, _ = loaded
        return asset.image_bytes

    def _scan_docs(self, corpus_dir: Path) -> List[Path]:
        docs = [p for p in corpus_dir.rglob("*.docx") if p.is_file()]
        docs.extend([p for p in corpus_dir.rglob("*.pdf") if p.is_file()])
        docs.sort(key=lambda p: str(p))
        return docs

    def _load_runtime_fp_from_index_entry(
        self,
        entry: Dict,
    ) -> Optional[Tuple[ImageAsset, RuntimeImageFingerprint]]:
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
        return cached.get(pos)

    def _load_index(self) -> Dict:
        if self._index_cache is not None:
            return self._index_cache
        data = _read_json(
            self.index_path,
            {
                "version": 1,
                "corpus_path": str(IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH),
                "documents": {},
                "images": {},
                "updated_at": None,
            },
        )
        if not isinstance(data.get("documents"), dict):
            data["documents"] = {}
        if not isinstance(data.get("images"), dict):
            data["images"] = {}
        self._index_cache = data
        return data

    def _load_checkpoint(self) -> Dict:
        return _read_json(
            self.checkpoint_path,
            {
                "next_cursor": 0,
                "has_more": False,
                "updated_at": None,
                "total_docs": 0,
                "corpus_path": str(IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH),
            },
        )


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
