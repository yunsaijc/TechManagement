"""附件类别聚合工具"""
from __future__ import annotations

from typing import Any, Iterable, Set


_NON_SPECIFIC_KINDS = {"unknown_attachment", "other_supporting_material"}


def collect_existing_doc_kinds(attachments: Iterable[Any]) -> Set[str]:
    """聚合上下文中已识别的附件类别（支持单文件多类别）"""
    kinds: Set[str] = set()
    for attachment in attachments or []:
        doc_kind = str(getattr(attachment, "doc_kind", "") or "").strip()
        if doc_kind:
            kinds.add(doc_kind)
        details = getattr(attachment, "classification_details", {}) or {}
        if not isinstance(details, dict):
            continue
        contains = details.get("contains_doc_kinds", [])
        if isinstance(contains, list):
            for item in contains:
                value = str(item or "").strip()
                if value:
                    kinds.add(value)
    return kinds


def collect_specific_doc_kinds(attachments: Iterable[Any]) -> Set[str]:
    """聚合可用于规则判定的具体附件类别（排除 unknown/other）"""
    return {kind for kind in collect_existing_doc_kinds(attachments) if kind not in _NON_SPECIFIC_KINDS}
