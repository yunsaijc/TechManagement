"""KJJH contract corpus metadata and local-ingest helpers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Optional

from src.common.database.connection import kjjh_execute
from src.services.plagiarism.config import (
    PLAGIARISM_KJJH_CHECKPOINT_PATH,
    PLAGIARISM_KJJH_INDEX_PATH,
    PLAGIARISM_KJJH_LOCAL_INGEST_DIR,
    PLAGIARISM_KJJH_MANIFEST_PATH,
    PLAGIARISM_KJJH_REMOTE_CORPUS_ROOT,
    PLAGIARISM_KJJH_SOURCE_CORPUS_ROOT,
    PLAGIARISM_KJJH_SQLITE_PATH,
)


class KJJHCorpusManager:
    """Manage KJJH metadata, mirrored docx files and local ingest paths."""

    def __init__(self) -> None:
        self.source_corpus_root = Path(PLAGIARISM_KJJH_SOURCE_CORPUS_ROOT)
        self.local_ingest_root = Path(PLAGIARISM_KJJH_LOCAL_INGEST_DIR)
        self.remote_corpus_root = Path(PLAGIARISM_KJJH_REMOTE_CORPUS_ROOT)
        self.index_path = Path(PLAGIARISM_KJJH_INDEX_PATH)
        self.sqlite_path = Path(PLAGIARISM_KJJH_SQLITE_PATH)
        self.manifest_path = Path(PLAGIARISM_KJJH_MANIFEST_PATH)
        self.checkpoint_path = Path(PLAGIARISM_KJJH_CHECKPOINT_PATH)

        self.source_corpus_root.mkdir(parents=True, exist_ok=True)
        self.local_ingest_root.mkdir(parents=True, exist_ok=True)

    def fetch_projects(
        self,
        *,
        min_year: int = 2022,
        limit: Optional[int] = None,
        xmbh: Optional[str] = None,
    ) -> list[dict]:
        sql = """
        SELECT
            htxx.[year] AS project_year,
            htxx.onlysign AS onlysign,
            htxx.xmbh AS xmbh
        FROM Ht_Jbxx htxx
        LEFT JOIN Ht_Sbzt htzt ON htzt.onlysign = htxx.id
        WHERE htxx.xmbh IS NOT NULL
          AND LTRIM(RTRIM(htxx.xmbh)) <> ''
          AND htxx.[year] > ?
          AND htxx.xmbh NOT LIKE 'syf'
        """
        params: list[object] = [int(min_year)]
        if xmbh and str(xmbh).strip():
            sql += " AND htxx.xmbh = ?"
            params.append(str(xmbh).strip())
        sql += " ORDER BY htxx.[year], htxx.xmbh, htxx.onlysign"
        if limit is not None and int(limit) > 0:
            sql += " OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
            params.append(int(limit))

        rows = kjjh_execute(sql, tuple(params))
        cleaned: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            year = str(row.get("project_year") or "").strip()
            onlysign = str(row.get("onlysign") or "").strip()
            project_id = str(row.get("xmbh") or "").strip()
            if not year or not onlysign or not project_id:
                continue
            key = (year, onlysign, project_id)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                {
                    "project_year": year,
                    "onlysign": onlysign,
                    "xmbh": project_id,
                }
            )
        return cleaned

    def get_project(self, xmbh: str, *, min_year: int = 2022) -> Optional[dict]:
        rows = self.fetch_projects(min_year=min_year, limit=1, xmbh=xmbh)
        return rows[0] if rows else None

    def build_doc_id(self, project_year: str | int, onlysign: str) -> str:
        return f"{str(project_year).strip()}/hts/{str(onlysign).strip()}.docx"

    def remote_doc_path(self, row: dict) -> Path:
        return self.remote_corpus_root / self.build_doc_id(row["project_year"], row["onlysign"])

    def local_doc_path(self, row: dict) -> Path:
        return self.source_corpus_root / self.build_doc_id(row["project_year"], row["onlysign"])

    def list_doc_ids(
        self,
        *,
        min_year: int = 2022,
        exclude_xmbh: Optional[str] = None,
        existing_doc_ids: Optional[Iterable[str]] = None,
    ) -> list[str]:
        existing = set(existing_doc_ids or [])
        rows = self.fetch_projects(min_year=min_year)
        doc_ids: list[str] = []
        seen: set[str] = set()
        excluded = str(exclude_xmbh or "").strip()
        for row in rows:
            if excluded and str(row.get("xmbh") or "").strip() == excluded:
                continue
            doc_id = self.build_doc_id(row["project_year"], row["onlysign"])
            if existing and doc_id not in existing:
                continue
            if doc_id in seen:
                continue
            seen.add(doc_id)
            doc_ids.append(doc_id)
        return doc_ids

    def create_corpus_manager(self):
        from src.services.plagiarism.corpus import CorpusManager

        env_keys = [
            "PLAGIARISM_CORPUS_PATH",
            "PLAGIARISM_CORPUS_INDEX_PATH",
            "PLAGIARISM_CORPUS_SQLITE_PATH",
            "PLAGIARISM_CORPUS_MANIFEST_PATH",
        ]
        previous = {key: os.environ.get(key) for key in env_keys}
        os.environ["PLAGIARISM_CORPUS_PATH"] = str(self.source_corpus_root)
        os.environ["PLAGIARISM_CORPUS_INDEX_PATH"] = str(self.index_path)
        os.environ["PLAGIARISM_CORPUS_SQLITE_PATH"] = str(self.sqlite_path)
        os.environ["PLAGIARISM_CORPUS_MANIFEST_PATH"] = str(self.manifest_path)
        try:
            return CorpusManager(
                corpus_path=str(self.source_corpus_root),
                index_save_path=str(self.index_path),
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def sync_local_files(self, *, min_year: int = 2022, limit: Optional[int] = None) -> dict:
        rows = self.fetch_projects(min_year=min_year, limit=limit)
        stats = {
            "selected_projects": len(rows),
            "copied": 0,
            "updated": 0,
            "skipped": 0,
            "missing_remote": 0,
            "failed": 0,
        }
        missing: list[dict] = []
        failed: list[dict] = []

        for row in rows:
            remote_path = self.remote_doc_path(row)
            local_path = self.local_doc_path(row)
            if not remote_path.is_file():
                stats["missing_remote"] += 1
                missing.append(
                    {
                        "xmbh": row["xmbh"],
                        "onlysign": row["onlysign"],
                        "project_year": row["project_year"],
                        "remote_path": str(remote_path),
                    }
                )
                continue

            try:
                changed, existed = self._copy_file_if_changed(remote_path, local_path)
                if changed and existed:
                    stats["updated"] += 1
                elif changed:
                    stats["copied"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                stats["failed"] += 1
                failed.append(
                    {
                        "xmbh": row["xmbh"],
                        "onlysign": row["onlysign"],
                        "project_year": row["project_year"],
                        "remote_path": str(remote_path),
                        "local_path": str(local_path),
                        "error": str(exc),
                    }
                )

        return {
            "stats": stats,
            "missing_remote_docs": missing,
            "failed_docs": failed,
            "source_corpus_root": str(self.source_corpus_root),
            "local_ingest_root": str(self.local_ingest_root),
            "index_path": str(self.index_path),
            "sqlite_path": str(self.sqlite_path),
            "manifest_path": str(self.manifest_path),
            "checkpoint_path": str(self.checkpoint_path),
        }

    def _copy_file_if_changed(self, src: Path, dst: Path) -> tuple[bool, bool]:
        existed = dst.exists()
        dst.parent.mkdir(parents=True, exist_ok=True)
        src_bytes = src.read_bytes()
        if existed:
            try:
                if dst.stat().st_size == len(src_bytes):
                    dst_bytes = dst.read_bytes()
                    if self._md5(dst_bytes) == self._md5(src_bytes):
                        return False, True
            except OSError:
                pass

        tmp_path = dst.with_name(f"{dst.name}.tmp")
        tmp_path.write_bytes(src_bytes)
        os.replace(tmp_path, dst)
        return True, existed

    @staticmethod
    def _md5(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()
