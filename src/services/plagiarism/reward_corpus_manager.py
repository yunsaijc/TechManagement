"""Reward DB corpus manager with reusable local ingest index."""

from __future__ import annotations

import html as html_lib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.common.database.connection import reward_execute
from src.services.plagiarism.config import (
    PLAGIARISM_REWARD_CHECKPOINT_PATH,
    PLAGIARISM_REWARD_DICT_CONFIG,
    PLAGIARISM_REWARD_INDEX_PATH,
    PLAGIARISM_REWARD_MANIFEST_PATH,
    PLAGIARISM_REWARD_SCOPE_TABLE,
    PLAGIARISM_REWARD_SQLITE_PATH,
)
from src.services.plagiarism.retrieval import SourceRetriever


class RewardCorpusManager:
    """Manage reward-field corpus with sqlite + manifest + index json."""
    _CHECKPOINT_FORMAT_VERSION = 2


    def __init__(self, db_name: str = "xmsbnew"):
        self.db_name = db_name
        self.index_path = Path(PLAGIARISM_REWARD_INDEX_PATH)
        self.sqlite_path = Path(PLAGIARISM_REWARD_SQLITE_PATH)
        self.manifest_path = Path(PLAGIARISM_REWARD_MANIFEST_PATH)
        self.checkpoint_path = Path(PLAGIARISM_REWARD_CHECKPOINT_PATH)
        self.retriever = SourceRetriever()
        self._scope_table_checked = False

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    def get_current_nomination_year(self) -> Optional[str]:
        rows = reward_execute(
            self.db_name,
            """
            SELECT nd AS nd
            FROM t_xm_xtsjsz
            WHERE dqzt = 1
            ORDER BY nd DESC
            LIMIT 1
            """,
        )
        if not rows:
            return None
        nd = rows[0].get("nd")
        return str(nd).strip() if nd is not None else None

    def get_scope_project_ids(self, scope: str, current_nd: Optional[str]) -> List[str]:
        self._ensure_scope_table_exists()
        if scope == "dn":
            if not current_nd:
                return []
            rows = reward_execute(
                self.db_name,
                f"""
                SELECT xmbh AS xmbh
                FROM {PLAGIARISM_REWARD_SCOPE_TABLE}
                WHERE nd = %s
                """,
                (current_nd,),
            )
        elif scope == "lshj":
            rows = reward_execute(
                self.db_name,
                f"""
                SELECT xmbh AS xmbh
                FROM {PLAGIARISM_REWARD_SCOPE_TABLE}
                WHERE xm_zsbh IS NOT NULL
                  AND TRIM(xm_zsbh) <> ''
                """,
            )
        else:
            return []

        dedup: List[str] = []
        seen = set()
        for row in rows:
            xmbh = str(row.get("xmbh") or "").strip()
            if not xmbh or xmbh in seen:
                continue
            seen.add(xmbh)
            dedup.append(xmbh)
        return dedup

    def build_scope_index(
        self,
        dict_type: str,
        scope: str,
        limit: Optional[int] = None,
        reset: bool = False,
    ) -> dict:
        if dict_type not in PLAGIARISM_REWARD_DICT_CONFIG:
            raise ValueError(f"不支持的 dict_type: {dict_type}")

        if reset:
            self._clear_dict_type(dict_type)

        current_nd = self.get_current_nomination_year()
        scope_ids = self.get_scope_project_ids(scope, current_nd)
        if limit and limit > 0:
            scope_ids = scope_ids[: int(limit)]

        text_map = self.fetch_field_texts(dict_type=dict_type, project_ids=scope_ids)
        changed = self.upsert_documents(dict_type=dict_type, text_map=text_map)
        checkpoint = {
            "dict_type": dict_type,
            "scope": scope,
            "current_nomination_year": current_nd,
            "requested_ids": len(scope_ids),
            "loaded_docs": len(text_map),
            "upserted_docs": changed,
            "updated_at": int(time.time()),
        }
        self._write_json(self.checkpoint_path, checkpoint)
        self._write_manifest_and_index()
        return checkpoint

    def build_scope_batch(
        self,
        dict_type: str,
        scope: str,
        limit: int = 200,
        cursor_xmbh: Optional[str] = None,
        reset_cursor: bool = False,
    ) -> dict:
        if dict_type not in PLAGIARISM_REWARD_DICT_CONFIG:
            raise ValueError(f"不支持的 dict_type: {dict_type}")
        if scope not in {"dn", "lshj"}:
            raise ValueError(f"不支持的 scope: {scope}")

        current_nd = self.get_current_nomination_year()
        if scope == "dn" and not current_nd:
            return {
                "dict_type": dict_type,
                "scope": scope,
                "current_nomination_year": current_nd,
                "cursor_xmbh": cursor_xmbh,
                "next_cursor_xmbh": None,
                "requested_ids": 0,
                "loaded_docs": 0,
                "upserted_docs": 0,
                "has_more": False,
                "updated_at": int(time.time()),
                "reason": "no_current_nomination_year",
            }

        key = self._checkpoint_key(dict_type, scope)
        stored = None if reset_cursor else self.get_checkpoint_cursor(dict_type=dict_type, scope=scope)
        effective_cursor = None
        if cursor_xmbh and str(cursor_xmbh).strip():
            effective_cursor = str(cursor_xmbh).strip()
        elif stored and str(stored).strip():
            effective_cursor = str(stored).strip()

        scope_ids = self._fetch_scope_project_ids_chunk(
            scope=scope,
            current_nd=current_nd,
            cursor_xmbh=effective_cursor,
            limit=int(limit),
        )
        if not scope_ids:
            payload = {
                "dict_type": dict_type,
                "scope": scope,
                "current_nomination_year": current_nd,
                "cursor_xmbh": effective_cursor,
                "next_cursor_xmbh": None,
                "requested_ids": 0,
                "loaded_docs": 0,
                "upserted_docs": 0,
                "has_more": False,
                "updated_at": int(time.time()),
            }
            self._write_checkpoint_item(key, payload)
            return payload

        text_map = self.fetch_field_texts(dict_type=dict_type, project_ids=scope_ids)
        changed = self.upsert_documents(dict_type=dict_type, text_map=text_map)
        self._write_manifest_and_index()

        next_cursor = scope_ids[-1]
        has_more = len(scope_ids) >= max(1, int(limit))
        payload = {
            "dict_type": dict_type,
            "scope": scope,
            "current_nomination_year": current_nd,
            "cursor_xmbh": effective_cursor,
            "next_cursor_xmbh": next_cursor,
            "requested_ids": len(scope_ids),
            "loaded_docs": len(text_map),
            "upserted_docs": changed,
            "has_more": has_more,
            "updated_at": int(time.time()),
        }
        self._write_checkpoint_item(key, payload)
        return payload

    def ensure_documents(self, dict_type: str, project_ids: Sequence[str]) -> int:
        missing_ids = self.get_missing_ids(dict_type, project_ids)
        if not missing_ids:
            return 0
        text_map = self.fetch_field_texts(dict_type=dict_type, project_ids=missing_ids)
        changed = self.upsert_documents(dict_type=dict_type, text_map=text_map)
        if changed:
            self._write_manifest_and_index()
        return changed

    def get_text_by_xmbh(self, dict_type: str, xmbh: str) -> str:
        rows = self._query_sqlite(
            """
            SELECT text_content
            FROM reward_corpus_docs
            WHERE dict_type = ? AND xmbh = ?
            """,
            (dict_type, xmbh),
        )
        if rows:
            existing = str(rows[0][0] or "")
            if self._needs_entity_cleanup(existing):
                self.upsert_documents(dict_type=dict_type, text_map={xmbh: existing})
                self._write_manifest_and_index()
                rows2 = self._query_sqlite(
                    """
                    SELECT text_content
                    FROM reward_corpus_docs
                    WHERE dict_type = ? AND xmbh = ?
                    """,
                    (dict_type, xmbh),
                )
                if rows2:
                    return str(rows2[0][0] or "")
            return existing

        text_map = self.fetch_field_texts(dict_type=dict_type, project_ids=[xmbh])
        if not text_map:
            return ""
        self.upsert_documents(dict_type=dict_type, text_map=text_map)
        self._write_manifest_and_index()
        return str(text_map.get(xmbh) or "")

    def get_texts(self, dict_type: str, xmbh_ids: Sequence[str]) -> Dict[str, str]:
        cleaned = [str(x).strip() for x in xmbh_ids if str(x).strip()]
        if not cleaned:
            return {}

        placeholders = ",".join(["?"] * len(cleaned))
        rows = self._query_sqlite(
            f"""
            SELECT xmbh, text_content
            FROM reward_corpus_docs
            WHERE dict_type = ? AND xmbh IN ({placeholders})
            """,
            (dict_type, *cleaned),
        )
        existing = {str(row[0]): str(row[1] or "") for row in rows}
        dirty_ids = [pid for pid, text in existing.items() if self._needs_entity_cleanup(text)]
        dirty_present = bool(dirty_ids)
        missing = [pid for pid in cleaned if pid not in existing]
        if missing:
            self.ensure_documents(dict_type=dict_type, project_ids=missing)
        if dirty_ids:
            self.upsert_documents(dict_type=dict_type, text_map={pid: existing.get(pid, "") for pid in dirty_ids})
            self._write_manifest_and_index()
        if missing or dirty_present:
            rows2 = self._query_sqlite(
                f"""
                SELECT xmbh, text_content
                FROM reward_corpus_docs
                WHERE dict_type = ? AND xmbh IN ({placeholders})
                """,
                (dict_type, *cleaned),
            )
            existing = {str(row[0]): str(row[1] or "") for row in rows2}
        return existing

    def get_retrieval_documents(self, dict_type: str, xmbh_ids: Sequence[str]) -> Dict[str, dict]:
        cleaned = [str(x).strip() for x in xmbh_ids if str(x).strip()]
        if not cleaned:
            return {}

        self.ensure_documents(dict_type=dict_type, project_ids=cleaned)
        placeholders = ",".join(["?"] * len(cleaned))
        rows = self._query_sqlite(
            f"""
            SELECT xmbh, features_json
            FROM reward_corpus_docs
            WHERE dict_type = ? AND xmbh IN ({placeholders})
            """,
            (dict_type, *cleaned),
        )
        documents: Dict[str, dict] = {}
        for xmbh, features_json in rows:
            try:
                features = json.loads(features_json or "{}")
            except json.JSONDecodeError:
                features = {}
            documents[str(xmbh)] = {"features": features}
        return documents

    def fetch_field_texts(self, dict_type: str, project_ids: Iterable[str]) -> Dict[str, str]:
        mapping = PLAGIARISM_REWARD_DICT_CONFIG[dict_type]
        table = mapping["table"]
        field = mapping["field"]
        cleaned_ids = [str(pid).strip() for pid in project_ids if str(pid).strip()]
        if not cleaned_ids:
            return {}

        result: Dict[str, str] = {}
        chunk_size = 500
        for i in range(0, len(cleaned_ids), chunk_size):
            chunk = cleaned_ids[i : i + chunk_size]
            placeholders = ",".join(["%s"] * len(chunk))
            sql = f"""
                SELECT
                    xmbh AS xmbh,
                    GROUP_CONCAT(COALESCE({field}, '') SEPARATOR '\n') AS content
                FROM {table}
                WHERE xmbh IN ({placeholders})
                GROUP BY xmbh
            """
            rows = reward_execute(self.db_name, sql, tuple(chunk))
            for row in rows:
                xmbh = str(row.get("xmbh") or "").strip()
                if not xmbh:
                    continue
                result[xmbh] = self._normalize_text(str(row.get("content") or ""))
        return result

    def get_innovation_item_by_id(self, record_id: str) -> Optional[dict]:
        cleaned = str(record_id).strip()
        if not cleaned:
            return None

        rows = reward_execute(
            self.db_name,
            """
            SELECT
                id AS id,
                XMBH AS xmbh,
                XH AS xh,
                ND AS nd,
                COALESCE(NULLIF(TRIM(JSCXD), ''), NULLIF(TRIM(JSCXD_V), ''), '') AS content
            FROM t_xm_cxd
            WHERE id = %s
              AND (del_flag IS NULL OR del_flag <> '1')
            LIMIT 1
            """,
            (cleaned,),
        )
        if not rows:
            return None

        row = rows[0]
        text = self._normalize_text(str(row.get("content") or ""))
        return {
            "id": cleaned,
            "xmbh": str(row.get("xmbh") or "").strip(),
            "xh": str(row.get("xh") or "").strip(),
            "nd": str(row.get("nd") or "").strip(),
            "text": text,
        }

    def fetch_innovation_items_by_project_ids(
        self,
        project_ids: Iterable[str],
        exclude_record_ids: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        cleaned_ids = [str(pid).strip() for pid in project_ids if str(pid).strip()]
        if not cleaned_ids:
            return []

        excluded = {str(record_id).strip() for record_id in (exclude_record_ids or []) if str(record_id).strip()}
        chunk_size = 500
        items: List[dict] = []
        for i in range(0, len(cleaned_ids), chunk_size):
            chunk = cleaned_ids[i : i + chunk_size]
            placeholders = ",".join(["%s"] * len(chunk))
            rows = reward_execute(
                self.db_name,
                f"""
                SELECT
                    id AS id,
                    XMBH AS xmbh,
                    XH AS xh,
                    ND AS nd,
                    COALESCE(NULLIF(TRIM(JSCXD), ''), NULLIF(TRIM(JSCXD_V), ''), '') AS content
                FROM t_xm_cxd
                WHERE XMBH IN ({placeholders})
                  AND (del_flag IS NULL OR del_flag <> '1')
                ORDER BY XMBH, XH, id
                """,
                tuple(chunk),
            )
            for row in rows:
                record_id = str(row.get("id") or "").strip()
                if not record_id or record_id in excluded:
                    continue
                text = self._normalize_text(str(row.get("content") or ""))
                if not text:
                    continue
                items.append(
                    {
                        "id": record_id,
                        "xmbh": str(row.get("xmbh") or "").strip(),
                        "xh": str(row.get("xh") or "").strip(),
                        "nd": str(row.get("nd") or "").strip(),
                        "text": text,
                    }
                )
        return items

    def fetch_field_items_by_project_ids(
        self,
        dict_type: str,
        project_ids: Iterable[str],
        exclude_record_ids: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        if dict_type == "cxd":
            return self.fetch_innovation_items_by_project_ids(
                project_ids=project_ids,
                exclude_record_ids=exclude_record_ids,
            )

        mapping = PLAGIARISM_REWARD_DICT_CONFIG[dict_type]
        table = mapping["table"]
        field = mapping["field"]
        order_field = mapping.get("order_field") or "id"
        cleaned_ids = [str(pid).strip() for pid in project_ids if str(pid).strip()]
        if not cleaned_ids:
            return []

        excluded = {str(record_id).strip() for record_id in (exclude_record_ids or []) if str(record_id).strip()}
        chunk_size = 500
        items: List[dict] = []
        for i in range(0, len(cleaned_ids), chunk_size):
            chunk = cleaned_ids[i : i + chunk_size]
            placeholders = ",".join(["%s"] * len(chunk))
            rows = reward_execute(
                self.db_name,
                f"""
                SELECT
                    id AS id,
                    XMBH AS xmbh,
                    {order_field} AS item_order,
                    ND AS nd,
                    COALESCE(NULLIF(TRIM({field}), ''), '') AS content
                FROM {table}
                WHERE XMBH IN ({placeholders})
                  AND (del_flag IS NULL OR del_flag <> '1')
                ORDER BY XMBH, {order_field}, id
                """,
                tuple(chunk),
            )
            for row in rows:
                record_id = str(row.get("id") or "").strip()
                if not record_id or record_id in excluded:
                    continue
                text = self._normalize_text(str(row.get("content") or ""))
                if not text:
                    continue
                items.append(
                    {
                        "id": record_id,
                        "xmbh": str(row.get("xmbh") or "").strip(),
                        "xh": str(row.get("item_order") or "").strip(),
                        "nd": str(row.get("nd") or "").strip(),
                        "text": text,
                    }
                )
        return items

    def build_retrieval_documents_from_text_map(self, text_map: Dict[str, str]) -> Dict[str, dict]:
        documents: Dict[str, dict] = {}
        for doc_id, text in (text_map or {}).items():
            cleaned = str(doc_id).strip()
            norm = self._normalize_text(text)
            if not cleaned or not norm:
                continue
            documents[cleaned] = {"features": self._build_features(norm)}
        return documents

    def get_missing_ids(self, dict_type: str, project_ids: Sequence[str]) -> List[str]:
        cleaned = [str(x).strip() for x in project_ids if str(x).strip()]
        if not cleaned:
            return []
        placeholders = ",".join(["?"] * len(cleaned))
        rows = self._query_sqlite(
            f"""
            SELECT xmbh
            FROM reward_corpus_docs
            WHERE dict_type = ? AND xmbh IN ({placeholders})
            """,
            (dict_type, *cleaned),
        )
        existing = {str(row[0]) for row in rows}
        return [pid for pid in cleaned if pid not in existing]

    def upsert_documents(self, dict_type: str, text_map: Dict[str, str]) -> int:
        if not text_map:
            return 0
        changed = 0
        now_ts = int(time.time())
        with sqlite3.connect(self.sqlite_path) as conn:
            for xmbh, text in text_map.items():
                norm = self._normalize_text(text)
                if not norm:
                    continue
                features = self._build_features(norm)
                conn.execute(
                    """
                    INSERT INTO reward_corpus_docs (
                        dict_type, xmbh, text_content, char_count, features_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dict_type, xmbh) DO UPDATE SET
                        text_content=excluded.text_content,
                        char_count=excluded.char_count,
                        features_json=excluded.features_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        dict_type,
                        xmbh,
                        norm,
                        len(norm),
                        json.dumps(features, ensure_ascii=False),
                        now_ts,
                    ),
                )
                changed += 1
            conn.commit()
        return changed

    def reset_checkpoint_cursor(self, dict_type: str, scope: str) -> None:
        key = self._checkpoint_key(dict_type, scope)
        checkpoint = self._read_checkpoint()
        items = checkpoint.get("items") if isinstance(checkpoint.get("items"), dict) else {}
        if key in items:
            items[key]["cursor_xmbh"] = None
            items[key]["next_cursor_xmbh"] = None
            items[key]["has_more"] = True
            items[key]["updated_at"] = int(time.time())
            checkpoint["items"] = items
            self._write_json(self.checkpoint_path, checkpoint)

    def get_checkpoint_cursor(self, dict_type: str, scope: str) -> Optional[str]:
        key = self._checkpoint_key(dict_type, scope)
        checkpoint = self._read_checkpoint()
        items = checkpoint.get("items") if isinstance(checkpoint.get("items"), dict) else {}
        item = items.get(key) if isinstance(items.get(key), dict) else None
        if not item:
            return None
        value = item.get("next_cursor_xmbh") or item.get("cursor_xmbh")
        return str(value).strip() if value else None

    def _clear_dict_type(self, dict_type: str) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute("DELETE FROM reward_corpus_docs WHERE dict_type = ?", (dict_type,))
            conn.commit()

    def _write_manifest_and_index(self) -> None:
        rows = self._query_sqlite(
            """
            SELECT dict_type, xmbh, char_count, updated_at
            FROM reward_corpus_docs
            ORDER BY dict_type, xmbh
            """,
        )
        docs = {
            f"{dict_type}:{xmbh}": {
                "dict_type": dict_type,
                "xmbh": xmbh,
                "char_count": int(char_count or 0),
                "updated_at": int(updated_at or 0),
            }
            for dict_type, xmbh, char_count, updated_at in rows
        }
        now_ts = int(time.time())
        self._write_json(
            self.index_path,
            {
                "documents": docs,
                "last_updated": now_ts,
                "format_version": 1,
            },
        )
        grouped: Dict[str, int] = {}
        for doc in docs.values():
            key = str(doc["dict_type"])
            grouped[key] = grouped.get(key, 0) + 1
        self._write_json(
            self.manifest_path,
            {
                "updated_at": now_ts,
                "total_documents": len(docs),
                "documents_by_dict_type": grouped,
                "sqlite_path": str(self.sqlite_path),
                "index_path": str(self.index_path),
            },
        )

    def _fetch_scope_project_ids_chunk(
        self,
        scope: str,
        current_nd: Optional[str],
        cursor_xmbh: Optional[str],
        limit: int,
    ) -> List[str]:
        self._ensure_scope_table_exists()
        limit = max(1, int(limit))
        cursor = str(cursor_xmbh).strip() if cursor_xmbh else None

        if scope == "dn":
            if not current_nd:
                return []
            if cursor:
                rows = reward_execute(
                    self.db_name,
                    f"""
                    SELECT xmbh AS xmbh
                    FROM {PLAGIARISM_REWARD_SCOPE_TABLE}
                    WHERE nd = %s
                      AND xmbh > %s
                    ORDER BY xmbh
                    LIMIT %s
                    """,
                    (current_nd, cursor, limit),
                )
            else:
                rows = reward_execute(
                    self.db_name,
                    f"""
                    SELECT xmbh AS xmbh
                    FROM {PLAGIARISM_REWARD_SCOPE_TABLE}
                    WHERE nd = %s
                    ORDER BY xmbh
                    LIMIT %s
                    """,
                    (current_nd, limit),
                )
        elif scope == "lshj":
            if cursor:
                rows = reward_execute(
                    self.db_name,
                    f"""
                    SELECT xmbh AS xmbh
                    FROM {PLAGIARISM_REWARD_SCOPE_TABLE}
                    WHERE xm_zsbh IS NOT NULL
                      AND TRIM(xm_zsbh) <> ''
                      AND xmbh > %s
                    ORDER BY xmbh
                    LIMIT %s
                    """,
                    (cursor, limit),
                )
            else:
                rows = reward_execute(
                    self.db_name,
                    f"""
                    SELECT xmbh AS xmbh
                    FROM {PLAGIARISM_REWARD_SCOPE_TABLE}
                    WHERE xm_zsbh IS NOT NULL
                      AND TRIM(xm_zsbh) <> ''
                    ORDER BY xmbh
                    LIMIT %s
                    """,
                    (limit,),
                )
        else:
            return []

        dedup: List[str] = []
        seen = set()
        for row in rows:
            xmbh = str(row.get("xmbh") or "").strip()
            if not xmbh or xmbh in seen:
                continue
            seen.add(xmbh)
            dedup.append(xmbh)
        return dedup

    def _checkpoint_key(self, dict_type: str, scope: str) -> str:
        return f"{str(dict_type).strip().lower()}:{str(scope).strip().lower()}"

    def _read_checkpoint(self) -> dict:
        if not self.checkpoint_path.exists():
            return {
                "format_version": self._CHECKPOINT_FORMAT_VERSION,
                "items": {},
            }
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "format_version": self._CHECKPOINT_FORMAT_VERSION,
                "items": {},
            }
        if isinstance(payload, dict) and isinstance(payload.get("items"), dict):
            payload.setdefault("format_version", self._CHECKPOINT_FORMAT_VERSION)
            return payload
        if not isinstance(payload, dict):
            return {
                "format_version": self._CHECKPOINT_FORMAT_VERSION,
                "items": {},
            }
        dict_type = str(payload.get("dict_type") or "").strip().lower()
        scope = str(payload.get("scope") or "").strip().lower()
        if not dict_type or not scope:
            return {
                "format_version": self._CHECKPOINT_FORMAT_VERSION,
                "items": {},
            }
        key = self._checkpoint_key(dict_type, scope)
        return {
            "format_version": self._CHECKPOINT_FORMAT_VERSION,
            "items": {key: payload},
        }

    def _write_checkpoint_item(self, key: str, item: dict) -> None:
        checkpoint = self._read_checkpoint()
        items = checkpoint.get("items") if isinstance(checkpoint.get("items"), dict) else {}
        items[key] = item
        checkpoint["items"] = items
        checkpoint["format_version"] = self._CHECKPOINT_FORMAT_VERSION
        self._write_json(self.checkpoint_path, checkpoint)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</?(p|div|li|tr|td|th|h[1-6])\b[^>]*>", "\n", cleaned)
        cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"&nbsp;|&#160;", " ", cleaned)
        for _ in range(4):
            unescaped = html_lib.unescape(cleaned)
            if unescaped == cleaned:
                break
            cleaned = unescaped
        cleaned = re.sub(r"&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]{2,12});", " ", cleaned)
        cleaned = cleaned.replace("\u00a0", " ")
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

        normalized_lines = []
        for raw_line in cleaned.split("\n"):
            line = re.sub(r"[^\S\n]+", " ", raw_line).strip()
            if line:
                normalized_lines.append(line)

        return "\n".join(normalized_lines).strip()

    @staticmethod
    def _needs_entity_cleanup(text: str) -> bool:
        if not text:
            return False
        return bool(re.search(r"&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]{2,12});", text))

    def _build_features(self, text: str) -> Dict[str, List[str]]:
        normalized = self.retriever._normalize(text)
        return {
            "char2": sorted(self.retriever._char_ngrams(normalized, 2)),
            "char4": sorted(self.retriever._char_ngrams(normalized, 4)),
            "char8": sorted(self.retriever._char_ngrams(normalized, 8)),
        }

    def _ensure_sqlite_schema(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reward_corpus_docs (
                    dict_type TEXT NOT NULL,
                    xmbh TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    features_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (dict_type, xmbh)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reward_corpus_docs_dict_type ON reward_corpus_docs(dict_type)"
            )
            conn.commit()

    def _query_sqlite(self, sql: str, params: Tuple = ()) -> List[Tuple]:
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    def _ensure_scope_table_exists(self) -> None:
        if self._scope_table_checked:
            return
        rows = reward_execute(
            self.db_name,
            f"SHOW TABLES LIKE '{PLAGIARISM_REWARD_SCOPE_TABLE}'",
        )
        if not rows:
            raise ValueError(f"未找到查询范围配置中的项目评审表: {PLAGIARISM_REWARD_SCOPE_TABLE}")
        self._scope_table_checked = True
