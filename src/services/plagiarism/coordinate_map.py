"""Canonical text <-> mammoth HTML coordinate mapping."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple


@dataclass
class CoordinateMap:
    """Maps canonical text offsets onto HTML offsets."""

    canonical_text: str
    html: str
    canonical_to_html: List[int]
    mapped_ratio: float

    def span_to_html(self, start: int, end: int) -> Optional[Tuple[int, int, float]]:
        if start < 0 or end <= start or start >= len(self.canonical_text):
            return None

        end = min(end, len(self.canonical_text))
        mapped = [
            self.canonical_to_html[i]
            for i in range(start, end)
            if 0 <= i < len(self.canonical_to_html) and self.canonical_to_html[i] >= 0
        ]
        if not mapped:
            return None

        html_start = min(mapped)
        html_end = max(mapped) + 1
        while html_end < len(self.html) and self.html[html_end] == "<":
            close = self.html.find(">", html_end + 1)
            if close == -1:
                break
            html_end = close + 1

        covered = len(mapped) / max(end - start, 1)
        return html_start, html_end, covered

    def span_to_html_fragments(self, start: int, end: int) -> Tuple[List[Tuple[int, int]], float]:
        """Map a canonical span to text-only HTML fragments.

        Each returned fragment is fully inside a contiguous text run of the HTML,
        so wrapping it with `<span>` will not cross block tags and break the DOM.
        """
        if start < 0 or end <= start or start >= len(self.canonical_text):
            return [], 0.0

        end = min(end, len(self.canonical_text))
        mapped = [
            self.canonical_to_html[i]
            for i in range(start, end)
            if 0 <= i < len(self.canonical_to_html) and self.canonical_to_html[i] >= 0
        ]
        if not mapped:
            return [], 0.0

        fragments: List[Tuple[int, int]] = []
        frag_start = mapped[0]
        frag_end = mapped[0] + 1
        for pos in mapped[1:]:
            if pos == frag_end:
                frag_end = pos + 1
                continue
            fragments.append((frag_start, frag_end))
            frag_start = pos
            frag_end = pos + 1
        fragments.append((frag_start, frag_end))

        covered = len(mapped) / max(end - start, 1)
        return fragments, covered


def build_coordinate_map(canonical_text: str, html: str) -> CoordinateMap:
    plain_text, plain_to_html = _extract_plain_text_with_html_positions(html)
    canonical_to_html = [-1] * len(canonical_text)
    if not canonical_text or not plain_text:
        return CoordinateMap(
            canonical_text=canonical_text,
            html=html,
            canonical_to_html=canonical_to_html,
            mapped_ratio=0.0,
        )

    canonical_norm, canon_norm_to_raw = _normalize_with_raw_positions(canonical_text)
    plain_norm, plain_norm_to_raw = _normalize_with_raw_positions(plain_text)

    canonical_to_plain = [-1] * len(canonical_text)
    if canonical_norm and plain_norm:
        matcher = SequenceMatcher(None, canonical_norm, plain_norm, autojunk=False)
        for block in matcher.get_matching_blocks():
            if block.size <= 0:
                continue
            for offset in range(block.size):
                canon_norm_idx = block.a + offset
                plain_norm_idx = block.b + offset
                if canon_norm_idx >= len(canon_norm_to_raw) or plain_norm_idx >= len(plain_norm_to_raw):
                    continue
                canon_raw_idx = canon_norm_to_raw[canon_norm_idx]
                plain_raw_idx = plain_norm_to_raw[plain_norm_idx]
                if 0 <= canon_raw_idx < len(canonical_to_plain):
                    canonical_to_plain[canon_raw_idx] = plain_raw_idx

    for idx, plain_idx in enumerate(canonical_to_plain):
        if plain_idx < 0:
            continue
        if 0 <= plain_idx < len(plain_to_html):
            canonical_to_html[idx] = plain_to_html[plain_idx]

    mapped = sum(1 for pos in canonical_to_html if pos >= 0)
    ratio = mapped / max(len(canonical_text), 1)
    return CoordinateMap(
        canonical_text=canonical_text,
        html=html,
        canonical_to_html=canonical_to_html,
        mapped_ratio=ratio,
    )


def _extract_plain_text_with_html_positions(html: str) -> Tuple[str, List[int]]:
    chars: List[str] = []
    positions: List[int] = []
    idx = 0
    while idx < len(html):
        if html[idx] == "<":
            close = html.find(">", idx + 1)
            if close == -1:
                break
            idx = close + 1
            continue
        chars.append(html[idx])
        positions.append(idx)
        idx += 1
    return "".join(chars), positions


def _normalize_with_raw_positions(text: str) -> Tuple[str, List[int]]:
    ignored = [False] * len(text)
    for m in re.finditer(r"\[表格行\d+\]", text):
        for i in range(m.start(), m.end()):
            if 0 <= i < len(ignored):
                ignored[i] = True

    norm_chars: List[str] = []
    raw_positions: List[int] = []
    for idx, ch in enumerate(text):
        if ignored[idx]:
            continue
        normalized = _normalize_char(ch)
        if not normalized:
            continue
        norm_chars.append(normalized)
        raw_positions.append(idx)
    return "".join(norm_chars), raw_positions


def _normalize_char(ch: str) -> str:
    if ch.isspace():
        return ""
    translate = {
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": "\"",
        "”": "\"",
        "‘": "'",
        "’": "'",
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "！": "!",
        "？": "?",
        "|": "",
    }
    return translate.get(ch, ch).lower()
