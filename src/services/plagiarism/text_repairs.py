"""Small deterministic text repairs for known DOCX extraction artifacts."""

from __future__ import annotations

import re


_TEXT_REPAIRS = [
    (
        re.compile(r"(^|\n)目通过(?=科技创新与产业实践)"),
        r"\1项目通过",
    ),
]

_HTML_REPAIRS = [
    (
        re.compile(r"(</a>)目通过(?=科技创新与产业实践)"),
        r"\1项目通过",
    ),
    (
        re.compile(r"(>)(目通过)(?=科技创新与产业实践)"),
        r"\1项目通过",
    ),
]


def repair_extracted_text_artifacts(text: str) -> str:
    """Repair stable extraction artifacts in canonical text."""
    if not text:
        return text

    repaired = text
    for pattern, replacement in _TEXT_REPAIRS:
        repaired = pattern.sub(replacement, repaired)
    return repaired


def repair_mammoth_html_artifacts(html_content: str) -> str:
    """Repair the same artifacts on mammoth HTML so coordinates stay aligned."""
    if not html_content:
        return html_content

    repaired = html_content
    for pattern, replacement in _HTML_REPAIRS:
        repaired = pattern.sub(replacement, repaired)
    return repaired
