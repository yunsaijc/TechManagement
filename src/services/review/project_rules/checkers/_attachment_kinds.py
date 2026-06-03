"""附件类别聚合工具"""
from __future__ import annotations

from typing import Any, Iterable, Set

from src.services.review.doc_types import doc_type_to_legacy_doc_kind
from src.services.review.project_config import resolve_doc_type

_NON_SPECIFIC_KINDS = {"project_unknown_attachment", "project_other_supporting_material", "unknown"}


def collect_existing_doc_types(attachments: Iterable[Any]) -> Set[str]:
    """聚合上下文中已识别的附件类型（支持单文件多类别）。"""
    doc_types: Set[str] = set()
    for attachment in attachments or []:
        doc_type = resolve_doc_type(str(getattr(attachment, "doc_type", "") or getattr(attachment, "doc_kind", "") or ""))
        if doc_type and doc_type != "unknown":
            doc_types.add(doc_type)
        details = getattr(attachment, "classification_details", {}) or {}
        if not isinstance(details, dict):
            continue
        contains = details.get("contains_doc_types", [])
        if not isinstance(contains, list):
            contains = details.get("contains_doc_kinds", [])
        if isinstance(contains, list):
            for item in contains:
                value = resolve_doc_type(str(item or ""))
                if value and value != "unknown":
                    doc_types.add(value)
    return doc_types


def collect_specific_doc_types(attachments: Iterable[Any]) -> Set[str]:
    """聚合可用于规则判定的具体附件类型（排除 unknown/other）。"""
    return {doc_type for doc_type in collect_existing_doc_types(attachments) if doc_type not in _NON_SPECIFIC_KINDS}


def collect_existing_doc_kinds(attachments: Iterable[Any]) -> Set[str]:
    """兼容旧函数名，返回旧附件类别编码。"""
    return {doc_type_to_legacy_doc_kind(doc_type) for doc_type in collect_existing_doc_types(attachments) if doc_type}


def collect_specific_doc_kinds(attachments: Iterable[Any]) -> Set[str]:
    """兼容旧函数名，返回旧附件类别编码。"""
    return {doc_type_to_legacy_doc_kind(doc_type) for doc_type in collect_specific_doc_types(attachments) if doc_type}
