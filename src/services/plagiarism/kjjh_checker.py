"""Reusable KJJH upload-plagiarism helpers."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from src.services.plagiarism.config import get_section_config
from src.services.plagiarism.kjjh_corpus_manager import KJJHCorpusManager
from src.services.plagiarism.section_extractor import SectionExtractor
from src.services.plagiarism.smb_file_reader import SMBReviewFileReader


class FilteredCorpusManager:
    def __init__(self, base_manager, allowed_doc_ids: list[str]):
        self._base = base_manager
        seen: set[str] = set()
        ordered: list[str] = []
        for doc_id in allowed_doc_ids:
            cleaned = str(doc_id).strip()
            if not cleaned or cleaned in seen:
                continue
            if cleaned not in self._base.index.documents:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        self._allowed = ordered
        self._allowed_set = set(ordered)
        self.index = type(
            "CorpusIndexView",
            (),
            {"documents": {doc_id: self._base.index.documents[doc_id] for doc_id in ordered}},
        )()

    def has_inverted_index(self):
        return self._base.has_inverted_index()

    def retrieve_candidate_doc_ids(self, primary_text: str, primary_excluded_ranges: list, top_k: int = 50):
        candidates = self._base.retrieve_candidate_doc_ids(
            primary_text=primary_text,
            primary_excluded_ranges=primary_excluded_ranges,
            top_k=top_k,
        )
        return [doc_id for doc_id in candidates if doc_id in self._allowed_set]

    def get_retrieval_documents(self, doc_ids=None):
        if doc_ids is None:
            return self._base.get_retrieval_documents(self._allowed)
        filtered = [doc_id for doc_id in doc_ids if doc_id in self._allowed_set]
        return self._base.get_retrieval_documents(filtered)

    async def get_document_text(self, doc_id: str):
        if doc_id not in self._allowed_set:
            return ""
        return await self._base.get_document_text(doc_id)


def serialize_plagiarism_result(result) -> dict[str, Any]:
    return {
        "id": result.id,
        "total_pairs": result.total_pairs,
        "effective_duplicate_rate": result.effective_duplicate_rate,
        "effective_duplicate_chars": result.effective_duplicate_chars,
        "primary_scope_chars": result.primary_scope_chars,
        "source_rankings": result.source_rankings,
        "match_groups": result.match_groups,
        "processing_time": round(result.processing_time, 2),
    }


def resolve_section_config(
    *,
    doc_type: str = "default",
    section_config_json: Optional[str] = None,
    section_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if section_config is not None:
        config = section_config
    elif section_config_json:
        try:
            config = json.loads(section_config_json)
        except json.JSONDecodeError as exc:
            raise ValueError("section_config 必须是有效的 JSON 字符串") from exc
    else:
        config = get_section_config(doc_type)

    if not SectionExtractor.validate_config(config):
        raise ValueError("section_config 无效：primary 必须配置 start_pattern（可选 end_pattern）")
    return config


def validate_thresholds(*, threshold_high: float, threshold_medium: float) -> None:
    if threshold_high <= 0 or threshold_high > 1 or threshold_medium <= 0 or threshold_medium > 1:
        raise ValueError("threshold_high/threshold_medium 必须在 (0,1] 区间")
    if threshold_medium > threshold_high:
        raise ValueError("threshold_medium 不能大于 threshold_high")


def resolve_upload_file_bytes(file_path: str) -> tuple[bytes, str, str | None]:
    raw = str(file_path or "").strip()
    if not raw:
        raise ValueError("word_path 不能为空")

    local_path = Path(raw)
    if local_path.is_file():
        return local_path.read_bytes(), str(local_path), None

    reader = SMBReviewFileReader()
    content = reader.read_bytes(raw)
    suffix = Path(raw).suffix.lower() if Path(raw).suffix else ".docx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(content)
    tmp.close()
    return content, raw, tmp.name


def _build_primary_doc_id(*, xmbh: Optional[str], resolved_word_path: str, temp_primary_path: Optional[str]) -> str:
    effective_path = temp_primary_path or resolved_word_path
    suffix = Path(effective_path).suffix.lower() or ".docx"
    if suffix not in {".docx", ".doc", ".pdf"}:
        suffix = ".docx"
    if xmbh and str(xmbh).strip():
        return f"{str(xmbh).strip()}{suffix}"
    stem = Path(effective_path).stem or f"upload_{uuid.uuid4().hex}"
    return f"{stem}{suffix}"


async def run_kjjh_plagiarism(
    *,
    xmbh: Optional[str] = None,
    word_path: Optional[str] = None,
    threshold: float = 0.5,
    threshold_high: float = 0.8,
    threshold_medium: float = 0.5,
    doc_type: str = "default",
    section_config_json: Optional[str] = None,
    section_config: Optional[dict[str, Any]] = None,
    debug: bool = False,
    include_report: bool = True,
    debug_output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    normalized_xmbh = str(xmbh or "").strip()
    normalized_word_path = str(word_path or "").strip()

    validate_thresholds(threshold_high=threshold_high, threshold_medium=threshold_medium)
    config = resolve_section_config(
        doc_type=doc_type,
        section_config_json=section_config_json,
        section_config=section_config,
    )

    manager = KJJHCorpusManager()
    meta: Optional[dict[str, Any]] = None
    auto_word_path = ""
    if normalized_xmbh:
        meta = manager.get_project(normalized_xmbh)
        if not meta:
            raise LookupError(f"未找到项目编号 {normalized_xmbh} 对应的 kjjh 合同文档")
        local_doc_path = manager.local_doc_path(meta)
        if local_doc_path.is_file():
            auto_word_path = str(local_doc_path)
        elif not normalized_word_path:
            raise FileNotFoundError(
                f"项目 {normalized_xmbh} 的本地源文档不存在: {local_doc_path}。"
                "请先确认 kjjh_local_ingest_0422 数据目录，或手动传入 word_path。"
            )

    source_word_path = normalized_word_path or auto_word_path
    if not source_word_path:
        raise ValueError("未提供可用于查重的 word_path")

    temp_primary_path: str | None = None
    try:
        content, resolved_word_path, temp_primary_path = resolve_upload_file_bytes(source_word_path)
    except Exception:
        raise

    corpus_manager = manager.create_corpus_manager()
    corpus_doc_ids = set(corpus_manager.index.documents.keys())
    if not corpus_doc_ids:
        if temp_primary_path:
            try:
                os.unlink(temp_primary_path)
            except OSError:
                pass
        raise ValueError("kjjh_local_ingest 对比库为空，请先执行 kjjh 建库脚本。")

    if normalized_xmbh:
        self_doc_id = manager.build_doc_id(meta["project_year"], meta["onlysign"])
        allowed_doc_ids = manager.list_doc_ids(existing_doc_ids=corpus_doc_ids, exclude_xmbh=normalized_xmbh)
        if self_doc_id in allowed_doc_ids:
            allowed_doc_ids = [doc_id for doc_id in allowed_doc_ids if doc_id != self_doc_id]
    else:
        allowed_doc_ids = sorted(corpus_doc_ids)
        self_doc_id = None

    if not allowed_doc_ids:
        if temp_primary_path:
            try:
                os.unlink(temp_primary_path)
            except OSError:
                pass
        raise ValueError("kjjh 对比库中没有可用于比对的其他文档")

    from src.services.plagiarism.agent import PlagiarismAgent

    primary_doc_id = _build_primary_doc_id(
        xmbh=normalized_xmbh or None,
        resolved_word_path=resolved_word_path,
        temp_primary_path=temp_primary_path,
    )
    env_keys = [
        "PLAGIARISM_CORPUS_PATH",
        "PLAGIARISM_CORPUS_INDEX_PATH",
        "PLAGIARISM_CORPUS_SQLITE_PATH",
        "PLAGIARISM_CORPUS_MANIFEST_PATH",
    ]
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ["PLAGIARISM_CORPUS_PATH"] = str(manager.source_corpus_root)
    os.environ["PLAGIARISM_CORPUS_INDEX_PATH"] = str(manager.index_path)
    os.environ["PLAGIARISM_CORPUS_SQLITE_PATH"] = str(manager.sqlite_path)
    os.environ["PLAGIARISM_CORPUS_MANIFEST_PATH"] = str(manager.manifest_path)
    try:
        agent = PlagiarismAgent(
            threshold=threshold,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            section_config=config,
            debug=debug,
            capture_debug_output=include_report,
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    agent.corpus_manager = FilteredCorpusManager(corpus_manager, allowed_doc_ids)
    try:
        result = await agent.check(
            [(primary_doc_id, content)],
            file_paths={primary_doc_id: str(temp_primary_path or resolved_word_path)},
            use_corpus=True,
            debug_output_dir=debug_output_dir,
        )
    finally:
        if temp_primary_path:
            try:
                os.unlink(temp_primary_path)
            except OSError:
                pass

    report_path = None
    if debug and debug_output_dir:
        report_path = str(Path(debug_output_dir) / "plagiarism_report_mammoth.html")

    return {
        "xmbh": normalized_xmbh or None,
        "project_year": meta.get("project_year") if meta else None,
        "onlysign": meta.get("onlysign") if meta else None,
        "self_doc_id": self_doc_id,
        "primary_doc_id": primary_doc_id,
        "word_path": resolved_word_path,
        "corpus_root": str(manager.source_corpus_root),
        "index_root": str(manager.local_ingest_root),
        "available_corpus_docs": len(allowed_doc_ids),
        "debug_report_path": report_path,
        "result": serialize_plagiarism_result(result),
    }
