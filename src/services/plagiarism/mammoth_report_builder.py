"""查重 HTML 报告生成器（使用mammoth保留Word格式版）

基于mammoth库将Word文档转换为HTML，保留原始格式，并叠加查重高亮。
"""
from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 导入mammoth转换器
from common.file_handler.mammoth_converter import (
    convert_docx_to_html_mammoth,
    get_mammoth_styles
)
from src.services.plagiarism.coordinate_map import build_coordinate_map


class MammothPlagiarismReportBuilder:
    """基于mammoth的查重HTML报告生成器
    
    使用mammoth库将Word文档转换为HTML，保留原始格式，
    然后在HTML层上叠加查重高亮标记。
    """

    @dataclass
    class _HtmlIndex:
        html: str
        plain_text: str
        norm_text: str
        plain_to_html: List[int]
        norm_to_plain: List[int]

    def build_from_debug_file(
        self,
        debug_json_path: Path | str,
        output_html_path: Path | str,
        primary_docx_path: Optional[Path | str] = None,
        source_docx_path: Optional[Path | str] = None,
        source_docx_paths: Optional[Dict[str, Path | str]] = None,
        highlight_template_segments: bool = True,
    ) -> Path:
        """从debug JSON文件生成HTML报告

        Args:
            debug_json_path: debug JSON文件路径
            output_html_path: 输出HTML文件路径
            primary_docx_path: 主文档DOCX路径（可选）
            source_docx_path: 来源文档DOCX路径（可选）
            source_docx_paths: 多个来源文档DOCX路径映射（可选）
        """
        debug_json_path = Path(debug_json_path)
        output_html_path = Path(output_html_path)

        # 读取debug数据
        data = json.loads(debug_json_path.read_text(encoding="utf-8"))
        data["highlight_template_segments"] = bool(highlight_template_segments)

        # 获取文档信息
        primary_doc = data.get("primary_doc", "Unknown")
        hide_source_panel = (not highlight_template_segments) and self._get_effective_duplicate_chars(data) == 0
        source_docs = [] if hide_source_panel else self._collect_source_docs(data)
        source_doc = source_docs[0] if source_docs else ""
        if hide_source_panel:
            source_doc_display = "无有效重复来源"
        else:
            source_doc_display = "按片段切换" if len(source_docs) > 1 else source_doc

        # 转换DOCX为HTML
        left_html = ""
        right_html_by_doc: Dict[str, str] = {}
        source_path_lookup: Dict[str, Path] = {}

        for doc_name, doc_path in (source_docx_paths or {}).items():
            if doc_name and doc_path:
                source_path_lookup[str(doc_name)] = Path(doc_path)
        if source_doc and source_docx_path:
            source_path_lookup.setdefault(source_doc, Path(source_docx_path))

        if primary_docx_path and Path(primary_docx_path).exists():
            left_html, _ = convert_docx_to_html_mammoth(primary_docx_path)
        else:
            left_html = self._build_fallback_content(data, "primary")

        if hide_source_panel:
            right_html = '<div class="docx-content"><p class="empty">无有效重复来源</p></div>'
        elif source_docs:
            for doc_name in source_docs:
                source_path = source_path_lookup.get(doc_name)
                if source_path and source_path.exists():
                    right_html_by_doc[doc_name], _ = convert_docx_to_html_mammoth(source_path)
                else:
                    right_html_by_doc[doc_name] = self._build_source_fallback_content(data, doc_name)
            right_html = self._render_source_sections(right_html_by_doc, source_docs)
        else:
            right_html_by_doc[""] = self._build_fallback_content(data, "source")
            right_html = self._render_source_sections(right_html_by_doc, source_docs)
        
        # 同时处理两侧高亮，确保每个片段都有两侧匹配
        left_html, right_html_by_doc, match_results = self._apply_highlights_both_sides(
            left_html,
            right_html_by_doc,
            data,
            highlight_template_segments=highlight_template_segments,
        )
        if not hide_source_panel:
            right_html = self._render_source_sections(right_html_by_doc, source_docs)
        
        # 构建统计信息
        stats = self._build_statistics(data)

        # 构建匹配导航
        match_cards = self._build_match_nav(
            data,
            match_results,
            highlight_template_segments=highlight_template_segments,
        )

        # 渲染完整页面
        html_page = self._render_html_page(
            primary_doc=primary_doc,
            source_doc=source_doc_display,
            stats=stats,
            match_cards=match_cards,
            left_html=left_html,
            right_html=right_html,
            summary=data.get("summary", {}),
            matched_count=len(match_results),
            unmatched_count=max(0, len(data.get("duplicate_segments", [])) - len(match_results)),
        )

        # 写入文件
        output_html_path.write_text(html_page, encoding="utf-8")
        return output_html_path

    def _apply_highlights_both_sides(
        self,
        left_html: str,
        right_html_by_doc: Dict[str, str],
        data: Dict,
        highlight_template_segments: bool = True,
    ) -> Tuple[str, Dict[str, str], Dict[str, Dict[str, Any]]]:
        """优先使用 canonical 坐标映射，并在失败时回退到文本定位。"""
        segments = data.get("duplicate_segments", [])
        if not segments:
            return left_html, right_html_by_doc, {}

        primary_doc = data.get("primary_doc", "")
        documents = data.get("documents", {})
        left_canonical = documents.get(primary_doc, "")
        left_map = build_coordinate_map(left_canonical, left_html) if left_canonical else None
        left_index = self._build_html_index(left_html) if left_html else None
        right_states: Dict[str, Dict[str, Any]] = {}
        for source_doc, right_html in right_html_by_doc.items():
            right_canonical = documents.get(source_doc, "")
            right_states[source_doc] = {
                "canonical": right_canonical,
                "coord_map": build_coordinate_map(right_canonical, right_html) if right_canonical else None,
                "html_index": self._build_html_index(right_html) if right_html else None,
            }

        left_spans: List[Tuple[int, int, str, bool, str]] = []
        right_spans_by_doc: Dict[str, List[Tuple[int, int, str, bool, str]]] = {
            source_doc: [] for source_doc in right_html_by_doc
        }
        match_results: Dict[str, Dict[str, Any]] = {}

        sorted_segments = sorted(
            enumerate(segments),
            key=lambda x: (int(x[1].get("primary_start", 0) or 0), -len(x[1].get("primary_text", ""))),
        )

        for seg_idx, segment in sorted_segments:
            match_id = segment.get("match_id") or f"m{seg_idx+1:03d}"
            is_template = segment.get("is_template", False)
            match_type = segment.get("match_type", "exact")
            # 仅在指定分支关闭模板高亮时跳过模板重复
            if is_template and not highlight_template_segments:
                continue
            sources = segment.get("sources", [])
            if not sources:
                continue

            primary_start = int(segment.get("primary_start", 0) or 0)
            primary_end = int(segment.get("primary_end", 0) or 0)
            source = sources[0]
            source_doc = source.get("doc", "")
            source_start = int(source.get("start", 0) or 0)
            source_end = int(source.get("end", 0) or 0)
            if primary_end <= primary_start:
                continue
            if source_doc not in right_states:
                continue

            primary_text = segment.get("primary_text", "")
            if not primary_text and primary_end > primary_start and left_canonical:
                primary_text = left_canonical[primary_start:primary_end]

            right_canonical = right_states[source_doc]["canonical"]
            source_text = source.get("text", "")
            if not source_text and source_end > source_start and right_canonical:
                source_text = right_canonical[source_start:source_end]

            left_fragments, left_mode, left_conf = self._resolve_highlight_fragments(
                coord_map=left_map,
                html_index=left_index,
                segment_text=primary_text,
                span_start=primary_start,
                span_end=primary_end,
                total_len=len(left_canonical),
            )
            right_fragments, right_mode, right_conf = self._resolve_highlight_fragments(
                coord_map=right_states[source_doc]["coord_map"],
                html_index=right_states[source_doc]["html_index"],
                segment_text=source_text,
                span_start=source_start,
                span_end=source_end,
                total_len=len(right_canonical),
            )
            if not left_fragments or not right_fragments:
                continue

            left_filtered = self._sanitize_fragments(left_fragments)
            right_filtered = self._sanitize_fragments(right_fragments)
            if not left_filtered or not right_filtered:
                continue

            for left_start, left_end in left_filtered:
                left_spans.append((left_start, left_end, match_id, is_template, match_type))
            for right_start, right_end in right_filtered:
                right_spans_by_doc[source_doc].append((right_start, right_end, match_id, is_template, match_type))

            locate_mode = "full" if left_mode == "full" and right_mode == "full" else "core"
            coverage = min(left_conf, right_conf)
            match_results[match_id] = {
                "mode": locate_mode,
                "confidence": round(coverage, 4),
                "match_type": match_type,
                "source_doc": source_doc,
            }

        highlighted_right_html = {
            source_doc: self._inject_spans(right_html_by_doc[source_doc], spans, "source", source_doc=source_doc)
            for source_doc, spans in right_spans_by_doc.items()
        }
        return (
            self._inject_spans(left_html, left_spans, "primary"),
            highlighted_right_html,
            match_results,
        )

    def _resolve_highlight_fragments(
        self,
        coord_map,
        html_index: Optional[_HtmlIndex],
        segment_text: str,
        span_start: int,
        span_end: int,
        total_len: int,
    ) -> Tuple[List[Tuple[int, int]], str, float]:
        if coord_map and span_end > span_start:
            fragments, coverage = coord_map.span_to_html_fragments(span_start, span_end)
            if fragments:
                mode = "full" if coverage >= 0.85 else "core"
                return fragments, mode, coverage

        if html_index and segment_text:
            located = self._locate_segment_fragments(html_index, segment_text, span_start, total_len)
            if located:
                return located

        return [], "miss", 0.0

    def _sanitize_fragments(
        self,
        fragments: List[Tuple[int, int]],
        min_len: int = 3,
    ) -> List[Tuple[int, int]]:
        filtered: List[Tuple[int, int]] = []
        seen = set()
        for start, end in sorted(fragments):
            start = max(0, int(start))
            end = max(0, int(end))
            if end - start < min_len:
                continue
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            filtered.append(key)
        return filtered

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\[表格行\d+\]", "", text)
        text = re.sub(r"\s*\|\s*", " ", text)
        chars: List[str] = []
        for ch in text:
            norm = self._normalize_char(ch)
            if norm:
                chars.append(norm)
        return "".join(chars)

    def _normalize_char(self, ch: str) -> str:
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
        }
        return translate.get(ch, ch).lower()

    def _build_html_index(self, html_content: str) -> _HtmlIndex:
        plain_chars: List[str] = []
        plain_to_html: List[int] = []

        i = 0
        while i < len(html_content):
            if html_content[i] == "<":
                close = html_content.find(">", i + 1)
                if close == -1:
                    break
                i = close + 1
                continue
            plain_chars.append(html_content[i])
            plain_to_html.append(i)
            i += 1

        plain_text = "".join(plain_chars)
        norm_chars: List[str] = []
        norm_to_plain: List[int] = []
        for idx, ch in enumerate(plain_text):
            norm = self._normalize_char(ch)
            if not norm:
                continue
            norm_chars.append(norm)
            norm_to_plain.append(idx)

        return self._HtmlIndex(
            html=html_content,
            plain_text=plain_text,
            norm_text="".join(norm_chars),
            plain_to_html=plain_to_html,
            norm_to_plain=norm_to_plain,
        )

    def _locate_segment_span(
        self,
        index: _HtmlIndex,
        segment_norm: str,
        raw_start: int,
        raw_total_len: int,
    ) -> Optional[Tuple[int, int, str, float]]:
        if not segment_norm or len(segment_norm) < 8 or not index.norm_text:
            return None

        expected = 0
        if raw_total_len > 0:
            expected = int(raw_start / raw_total_len * len(index.norm_text))
        expected = max(0, min(expected, max(len(index.norm_text) - 1, 0)))

        exact_positions = self._find_all(index.norm_text, segment_norm)
        if exact_positions:
            start = min(exact_positions, key=lambda p: abs(p - expected))
            html_span = self._norm_span_to_html(index, start, start + len(segment_norm))
            if html_span:
                return html_span[0], html_span[1], "full", 1.0

        anchored = self._locate_with_anchors(index.norm_text, segment_norm, expected)
        if anchored is None:
            return None

        start, end, confidence = anchored
        html_span = self._norm_span_to_html(index, start, end)
        if not html_span:
            return None
        return html_span[0], html_span[1], "core", confidence

    def _locate_segment_fragments(
        self,
        index: _HtmlIndex,
        segment_text: str,
        raw_start: int,
        raw_total_len: int,
    ) -> Optional[Tuple[List[Tuple[int, int]], str, float]]:
        segment_norm = self._normalize_text(segment_text)
        if not segment_norm or len(segment_norm) < 8 or not index.norm_text:
            return None

        expected = 0
        if raw_total_len > 0:
            expected = int(raw_start / raw_total_len * len(index.norm_text))
        expected = max(0, min(expected, max(len(index.norm_text) - 1, 0)))

        exact_positions = self._find_all(index.norm_text, segment_norm)
        if exact_positions:
            start = min(exact_positions, key=lambda p: abs(p - expected))
            fragments = self._norm_span_to_html_fragments(index, start, start + len(segment_norm))
            if fragments:
                return fragments, "full", 1.0

        anchored = self._locate_with_anchors(index.norm_text, segment_norm, expected)
        if anchored is None:
            return None

        start, end, confidence = anchored
        fragments = self._norm_span_to_html_fragments(index, start, end)
        if not fragments:
            return None
        return fragments, "core", confidence

    def _locate_with_anchors(
        self,
        norm_text: str,
        segment_norm: str,
        expected: int,
    ) -> Optional[Tuple[int, int, float]]:
        seg_len = len(segment_norm)
        if seg_len < 8:
            return None

        anchor_lens = [min(seg_len, 120), min(seg_len, 80), min(seg_len, 60), min(seg_len, 40), min(seg_len, 24)]
        best: Optional[Tuple[int, int, float]] = None
        for anchor_len in anchor_lens:
            if anchor_len < 12:
                continue
            offsets = sorted({0, max(0, seg_len // 3), max(0, seg_len - anchor_len), max(0, seg_len // 2 - anchor_len // 2)})
            for offset in offsets:
                if offset + anchor_len > seg_len:
                    continue
                anchor = segment_norm[offset:offset + anchor_len]
                positions = self._find_all(norm_text, anchor)
                for pos in positions[:20]:
                    est_start = max(0, pos - offset)
                    est_end = min(len(norm_text), est_start + seg_len)
                    if est_end - est_start < max(12, seg_len // 3):
                        continue

                    # 在局部窗口内滑动，找与片段字符最接近的位置
                    local_best_start = est_start
                    local_best_ratio = 0.0
                    for shift in range(-24, 25):
                        cand_start = est_start + shift
                        cand_end = cand_start + seg_len
                        if cand_start < 0 or cand_end > len(norm_text):
                            continue
                        ratio = self._char_match_ratio(segment_norm, norm_text[cand_start:cand_end])
                        if ratio > local_best_ratio:
                            local_best_ratio = ratio
                            local_best_start = cand_start

                    score = local_best_ratio - (abs(local_best_start - expected) / max(len(norm_text), 1)) * 0.25
                    if local_best_ratio < 0.45:
                        continue

                    candidate = (local_best_start, min(len(norm_text), local_best_start + seg_len), score)
                    if best is None or candidate[2] > best[2]:
                        best = candidate

            if best:
                break

        if not best:
            return None
        conf = max(0.0, min(1.0, best[2]))
        return best[0], best[1], conf

    def _char_match_ratio(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        limit = min(len(a), len(b))
        matched = sum(1 for i in range(limit) if a[i] == b[i])
        return matched / limit if limit else 0.0

    def _find_all(self, text: str, pattern: str) -> List[int]:
        if not pattern:
            return []
        positions: List[int] = []
        start = 0
        while True:
            idx = text.find(pattern, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + 1
        return positions

    def _norm_span_to_html(
        self,
        index: _HtmlIndex,
        norm_start: int,
        norm_end: int,
    ) -> Optional[Tuple[int, int]]:
        if norm_start < 0 or norm_end <= norm_start or norm_end > len(index.norm_to_plain):
            return None
        plain_start = index.norm_to_plain[norm_start]
        plain_end = index.norm_to_plain[norm_end - 1]
        if plain_start >= len(index.plain_to_html) or plain_end >= len(index.plain_to_html):
            return None

        html_start = index.plain_to_html[plain_start]
        html_end = index.plain_to_html[plain_end] + 1
        while html_end < len(index.html) and index.html[html_end] == "<":
            close = index.html.find(">", html_end + 1)
            if close == -1:
                break
            html_end = close + 1
        return html_start, html_end

    def _norm_span_to_html_fragments(
        self,
        index: _HtmlIndex,
        norm_start: int,
        norm_end: int,
    ) -> List[Tuple[int, int]]:
        if norm_start < 0 or norm_end <= norm_start or norm_end > len(index.norm_to_plain):
            return []

        mapped: List[int] = []
        for norm_idx in range(norm_start, norm_end):
            plain_idx = index.norm_to_plain[norm_idx]
            if 0 <= plain_idx < len(index.plain_to_html):
                mapped.append(index.plain_to_html[plain_idx])
        if not mapped:
            return []

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
        return fragments

    def _has_overlap(self, used: List[Tuple[int, int]], start: int, end: int) -> bool:
        for s, e in used:
            if start < e and end > s:
                return True
        return False

    def _inject_spans(
        self,
        html_content: str,
        spans: List[Tuple[int, int, str, bool, str]],
        side: str,
        source_doc: str = "",
    ) -> str:
        if not html_content or not spans:
            return html_content

        normalized_spans: List[Tuple[int, int, str, bool, str]] = []
        content_len = len(html_content)
        for start, end, match_id, is_template, match_type in spans:
            start = max(0, min(int(start), content_len))
            end = max(0, min(int(end), content_len))
            if end <= start:
                continue
            normalized_spans.append((start, end, match_id, is_template, match_type))
        if not normalized_spans:
            return html_content

        boundaries = {0, content_len}
        for start, end, *_ in normalized_spans:
            boundaries.add(start)
            boundaries.add(end)
        sorted_boundaries = sorted(boundaries)

        parts: List[str] = []
        for idx in range(len(sorted_boundaries) - 1):
            chunk_start = sorted_boundaries[idx]
            chunk_end = sorted_boundaries[idx + 1]
            if chunk_end <= chunk_start:
                continue

            chunk_html = html_content[chunk_start:chunk_end]
            covering = [
                span for span in normalized_spans
                if span[0] < chunk_end and span[1] > chunk_start
            ]
            if not covering:
                parts.append(chunk_html)
                continue

            match_ids: List[str] = []
            seen_match_ids = set()
            has_template = False
            has_paraphrase = False
            primary_match_id = ""
            primary_match_type = "exact"
            for _, _, match_id, is_template, match_type in covering:
                if match_id not in seen_match_ids:
                    seen_match_ids.add(match_id)
                    match_ids.append(match_id)
                    if not primary_match_id:
                        primary_match_id = match_id
                        primary_match_type = match_type
                has_template = has_template or is_template
                has_paraphrase = has_paraphrase or match_type == "paraphrase"

            classes = ["hit"]
            if has_template:
                classes.append("template")
            if has_paraphrase:
                classes.append("paraphrase")

            attrs = [
                f'class="{" ".join(classes)}"',
                f'data-match-id="{html.escape(primary_match_id)}"',
                f'data-match-ids="{html.escape(",".join(match_ids))}"',
                f'data-side="{html.escape(side)}"',
                f'data-match-type="{html.escape(primary_match_type)}"',
            ]
            if source_doc:
                attrs.append(f'data-source-doc="{html.escape(source_doc)}"')

            parts.append(f'<span {" ".join(attrs)}>{chunk_html}</span>')

        return "".join(parts)

    def _get_effective_duplicate_chars(self, data: Dict) -> int:
        summary = data.get("summary", {}) or {}
        value = summary.get("effective_duplicate_chars")
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
        return self._union_length(
            [
                (int(s.get("primary_start", 0) or 0), int(s.get("primary_end", 0) or 0))
                for s in (data.get("duplicate_segments", []) or [])
            ]
        )

    def _collect_source_docs(self, data: Dict) -> List[str]:
        seen = set()
        source_docs: List[str] = []
        for segment in list(data.get("duplicate_segments", []) or []) + list(data.get("template_segments", []) or []):
            sources = segment.get("sources", [])
            if not sources:
                continue
            source_doc = str(sources[0].get("doc", "") or "").strip()
            if source_doc and source_doc not in seen:
                seen.add(source_doc)
                source_docs.append(source_doc)
        # 兜底：当片段为空时，尝试使用调试输出中的 report_source_doc
        if not source_docs:
            fallback_source_doc = str(data.get("report_source_doc", "") or "").strip()
            if fallback_source_doc:
                source_docs.append(fallback_source_doc)
        return source_docs

    def _build_source_fallback_content(self, data: Dict, source_doc: str) -> str:
        documents = data.get("documents", {})
        text = documents.get(source_doc, "") if source_doc else documents.get("source", "")
        if not text and source_doc:
            snippets: List[str] = []
            seen = set()
            for segment in data.get("duplicate_segments", []):
                sources = segment.get("sources", [])
                if not sources:
                    continue
                source = sources[0]
                if source.get("doc", "") != source_doc:
                    continue
                snippet = str(source.get("text", "") or "").strip()
                if not snippet or snippet in seen:
                    continue
                seen.add(snippet)
                snippets.append(snippet)
            text = "\n".join(snippets)

        if not text:
            return '<div class="docx-content"><p class="empty">无内容</p></div>'

        paragraphs = text.split('\n')
        html_paras = []
        for para in paragraphs:
            if para.strip():
                html_paras.append(f'<p>{html.escape(para)}</p>')
        return f'<div class="docx-content">\n{ "".join(html_paras) }\n</div>'

    def _render_source_sections(self, right_html_by_doc: Dict[str, str], source_docs: List[str]) -> str:
        if not right_html_by_doc:
            return '<div class="docx-content"><p class="empty">无内容</p></div>'

        ordered_docs = source_docs or list(right_html_by_doc.keys())
        sections: List[str] = []
        for idx, source_doc in enumerate(ordered_docs):
            content = right_html_by_doc.get(source_doc, '<div class="docx-content"><p class="empty">无内容</p></div>')
            hidden_class = " hidden" if idx > 0 else ""
            source_doc_value = html.escape(source_doc or "")
            source_name = html.escape(source_doc or "N/A")
            sections.append(
                f'<div class="source-doc-section{hidden_class}" data-source-doc="{source_doc_value}" data-source-name="{source_name}">{content}</div>'
            )
        return "".join(sections)

    def _apply_highlights(
        self,
        html_content: str,
        data: Dict,
        side: str
    ) -> str:
        """在HTML内容上应用查重高亮
        
        使用基于锚点的文本匹配策略，在HTML中定位并高亮重复内容。
        """
        segments = data.get("duplicate_segments", [])
        if not segments:
            return html_content

        result = html_content
        
        # 按文本长度排序（长的先处理，避免短文本干扰）
        sorted_segments = sorted(
            enumerate(segments),
            key=lambda x: len(x[1].get("primary_text", "") if side == "primary" else 
                          (x[1].get("sources", [{}])[0].get("text", "") if x[1].get("sources") else "")),
            reverse=True
        )
        
        for seg_idx, segment in sorted_segments:
            match_id = segment.get("match_id") or f"m{seg_idx+1:03d}"
            is_template = segment.get("is_template", False)
            
            if side == "primary":
                text = segment.get("primary_text", "")
            else:
                sources = segment.get("sources", [])
                if sources:
                    text = sources[0].get("text", "")
                else:
                    continue
            
            if not text or len(text) < 5:
                continue
            
            # 清理文本：去除多余空格
            clean_text = ' '.join(text.split())
            
            # 在 HTML 中查找文本（忽略 HTML 标签）
            # 策略：提取 HTML 中的纯文本，然后查找匹配
            plain_text = re.sub(r'<[^>]+>', ' ', result)
            plain_text = ' '.join(plain_text.split())
            
            # 在纯文本中查找
            search_text = clean_text[:min(50, len(clean_text))]
            match_start_plain = plain_text.find(search_text)
            if match_start_plain == -1:
                # 尝试更短的匹配
                search_text = clean_text[:min(30, len(clean_text))]
                match_start_plain = plain_text.find(search_text)
                if match_start_plain == -1:
                    continue
            
            # 将纯文本位置映射回 HTML 位置
            # 策略：遍历 HTML，跳过标签，找到对应位置
            html_pos = 0
            plain_pos = 0
            match_start_html = -1
            
            while html_pos < len(result) and plain_pos <= match_start_plain:
                if result[html_pos] == '<':
                    # 跳过标签
                    while html_pos < len(result) and result[html_pos] != '>':
                        html_pos += 1
                    html_pos += 1  # 跳过 '>'
                else:
                    if plain_pos == match_start_plain:
                        match_start_html = html_pos
                        break
                    plain_pos += 1
                    html_pos += 1
            
            if match_start_html == -1:
                continue
            
            # 从匹配起点开始，向后扩展找到完整匹配
            anchor_len = min(20, len(clean_text))
            anchor_pos = match_start_html
            
            # 从锚点开始，向后匹配完整文本
            # 策略：找到锚点后，向后扩展直到匹配完所有字符
            match_start = anchor_pos
            match_end = anchor_pos + anchor_len
            remaining_text = clean_text[anchor_len:]
            
            # 向后扫描，找到剩余文本
            search_pos = match_end
            text_pos = 0
            
            while text_pos < len(remaining_text) and search_pos < len(result):
                # 跳过HTML标签
                if result[search_pos] == '<':
                    while search_pos < len(result) and result[search_pos] != '>':
                        search_pos += 1
                    search_pos += 1  # 跳过 '>'
                    continue
                
                target_char = remaining_text[text_pos]
                actual_char = result[search_pos]
                
                # 检查是否匹配（忽略空格差异）
                if actual_char == target_char or (actual_char.isspace() and target_char.isspace()):
                    text_pos += 1
                    search_pos += 1
                else:
                    # 不匹配，可能是格式差异，跳过这个字符
                    search_pos += 1
            
            match_end = search_pos
            
            # 提取匹配的HTML
            matched_html = result[match_start:match_end]
            
            # 检查匹配质量
            matched_text = re.sub(r'<[^>]+>', '', matched_html)
            matched_text_clean = ''.join(matched_text.split())
            target_clean = ''.join(clean_text.split())
            
            # 计算匹配率
            match_ratio = len(matched_text_clean) / len(target_clean) if target_clean else 0
            
            if match_ratio < 0.3:  # 匹配率太低，跳过
                continue
            
            # 确保不切割HTML标签 - 调整边界到标签外
            # 向前调整
            while match_start > 0 and result[match_start - 1] != '>' and result[match_start] != '<':
                # 检查是否在标签内
                in_tag = False
                for i in range(match_start - 1, max(0, match_start - 100), -1):
                    if result[i] == '>':
                        break
                    if result[i] == '<':
                        in_tag = True
                        break
                if in_tag:
                    # 在标签内，向前移动
                    while match_start > 0 and result[match_start - 1] != '<':
                        match_start -= 1
                    match_start -= 1  # 移动到 '<'
                else:
                    break
            
            # 向后调整
            while match_end < len(result) and result[match_end - 1] != '>' and result[match_end] != '<':
                # 检查是否在标签内
                in_tag = False
                for i in range(match_end, min(len(result), match_end + 100)):
                    if result[i] == '<':
                        in_tag = True
                        break
                    if result[i] == '>':
                        break
                if in_tag:
                    # 在标签内，向后移动
                    while match_end < len(result) and result[match_end] != '>':
                        match_end += 1
                    match_end += 1  # 跳过 '>'
                else:
                    break
            
            # 重新提取
            matched_html = result[match_start:match_end]
            
            # 创建高亮HTML
            template_class = " template" if is_template else ""
            highlight_html = f'<span class="hit{template_class}" data-match-id="{match_id}" data-side="{side}">{matched_html}</span>'
            
            # 替换
            result = result[:match_start] + highlight_html + result[match_end:]

        return result

    def _build_fallback_content(self, data: Dict, side: str) -> str:
        """构建降级内容（当没有DOCX文件时使用）"""
        documents = data.get("documents", {})
        
        if side == "primary":
            text = documents.get("primary", "")
            title = data.get("primary_doc", "主文档")
        else:
            text = documents.get("source", "")
            title = "来源文档"
        
        if not text:
            return f'<div class="docx-content"><p class="empty">无内容</p></div>'
        
        # 简单分段
        paragraphs = text.split('\n')
        html_paras = []
        for para in paragraphs:
            if para.strip():
                html_paras.append(f'<p>{html.escape(para)}</p>')
        
        return f'<div class="docx-content">\n{ "".join(html_paras) }\n</div>'

    def _build_statistics(self, data: Dict) -> str:
        """构建统计信息HTML"""
        summary = data.get("summary", {})
        text_lengths = data.get("text_lengths", {})
        segments = data.get("duplicate_segments", [])
        template_segments = data.get("template_segments", [])
        primary_doc = data.get("primary_doc", "")
        highlight_template_segments = bool(data.get("highlight_template_segments", True))
        
        # 统计口径：统一按主文档字数计算，避免与普通HTML口径冲突
        total_chars = int(text_lengths.get(primary_doc, 0)) if primary_doc else 0
        if total_chars == 0:
            docs = data.get("documents", {})
            primary_text = docs.get(primary_doc, "") if primary_doc else ""
            if isinstance(primary_text, str) and primary_text:
                total_chars = len(primary_text)

        # 使用位置并集计算字符数，避免片段重叠导致重复计数
        effective_chars = self._union_length([
            (int(s.get("primary_start", 0) or 0), int(s.get("primary_end", 0) or 0))
            for s in segments
        ])

        template_chars = self._union_length([
            (int(s.get("primary_start", 0) or 0), int(s.get("primary_end", 0) or 0))
            for s in template_segments
        ])
        
        # 统计口径（可加和）：总重复 = 有效重复 + 模板重复
        # 注意：若两类在主文档坐标上有重叠，这里会按“相加口径”重复计入重叠部分，
        # 以保证“总重复率 = 有效重复率 + 模板重复率”成立。
        duplicate_chars = effective_chars + template_chars
        
        # 计算重复率
        total_rate = (duplicate_chars / total_chars * 100) if total_chars > 0 else 0
        effective_rate = (effective_chars / total_chars * 100) if total_chars > 0 else 0
        template_rate = (template_chars / total_chars * 100) if total_chars > 0 else 0

        return f"""<div class="stat-card"><div class="stat-label">总重复率</div><div class="stat-value">{total_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">有效重复率</div><div class="stat-value">{effective_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">模板重复率</div><div class="stat-value">{template_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">总字数</div><div class="stat-value">{total_chars:,}</div></div><div class="stat-card"><div class="stat-label">重复字数</div><div class="stat-value">{duplicate_chars:,}</div></div><div class="stat-card"><div class="stat-label">有效重复字数</div><div class="stat-value">{effective_chars:,}</div></div>"""

    @staticmethod
    def _union_length(ranges: List[Tuple[int, int]]) -> int:
        valid = sorted((max(0, s), max(0, e)) for s, e in ranges if e > s)
        if not valid:
            return 0

        total = 0
        cur_start, cur_end = valid[0]
        for start, end in valid[1:]:
            if start <= cur_end:
                cur_end = max(cur_end, end)
                continue
            total += cur_end - cur_start
            cur_start, cur_end = start, end
        total += cur_end - cur_start
        return total

    def _build_match_nav(
        self,
        data: Dict,
        match_results: Optional[Dict[str, Dict[str, Any]]] = None,
        highlight_template_segments: bool = True,
    ) -> str:
        """构建匹配片段导航"""
        segments = [
            s
            for s in (data.get("duplicate_segments", []) or [])
            if highlight_template_segments or not s.get("is_template", False)
        ]
        if not segments:
            return '<p class="empty">无重复片段</p>'

        cards = []
        for i, segment in enumerate(segments[:50], 1):  # 最多显示50个
            match_id = segment.get("match_id") or f"m{i:03d}"
            primary_text = self._clean_nav_text(segment.get("primary_text", ""))[:60]
            is_template = segment.get("is_template", False)
            similarity = segment.get("similarity_score", segment.get("similarity", 1.0))
            result = (match_results or {}).get(match_id)
            match_type = segment.get("match_type", "exact")
            locate_mode = result.get("mode") if result else "miss"
            
            sources = segment.get("sources", [])
            source_info = ""
            source_doc = ""
            if sources:
                source_doc = sources[0].get("doc", "")
                source_info = f"来源: {html.escape(source_doc)}"
            if result and result.get("source_doc"):
                source_doc = str(result.get("source_doc") or source_doc)
            
            template_badge = '<span class="template-badge">模板</span>' if is_template else ''
            type_badge = '<span class="template-badge" style="background:#2563eb;">改写</span>' if match_type == "paraphrase" else ''
            if result:
                locate_badge = '<span class="locate-badge ok">完整</span>' if result.get("mode") == "full" else '<span class="locate-badge partial">核心</span>'
            else:
                locate_badge = '<span class="locate-badge miss">未定位</span>'
            
            cards.append(f'''<button class="nav-item" data-match-id="{match_id}" data-source-doc="{html.escape(source_doc)}" data-template="{1 if is_template else 0}" data-type="{html.escape(match_type)}" data-locate="{html.escape(locate_mode or '')}">
                <div class="nav-header">#{i} {template_badge} {type_badge} {locate_badge}</div>
                <div class="nav-text">{html.escape(primary_text)}...</div>
                <small>相似度 {similarity:.2f} · {source_info}</small>
            </button>''')

        return "".join(cards) if cards else '<p class="empty">未定位到可高亮的重复片段</p>'

    def _clean_nav_text(self, text: str) -> str:
        cleaned = re.sub(r"\[表格行\d+\]", "", text or "")
        cleaned = cleaned.replace("|", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _render_html_page(
        self,
        primary_doc: str,
        source_doc: str,
        stats: str,
        match_cards: str,
        left_html: str,
        right_html: str,
        summary: dict,
        matched_count: int = 0,
        unmatched_count: int = 0,
    ) -> str:
        """渲染完整HTML页面"""
        
        # 计算摘要数据
        effective_count = summary.get("total_effective_segments", 0)
        template_count = summary.get("total_template_segments", 0)
        effective_chars = summary.get("total_effective_chars", 0)
        
        mammoth_styles = get_mammoth_styles()
        
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>查重可视化报告 - {html.escape(primary_doc)}</title>
  <style>
    {mammoth_styles}

    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-2: #f8fafc;
      --line: #e5e7eb;
      --line-2: rgba(148, 163, 184, 0.22);
      --ink: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --danger: #ef4444;
      --warn: #f59e0b;
      --ok: #16a34a;
      --radius: 12px;
      --shadow: 0 10px 28px rgba(15, 23, 42, 0.10);
    }}

    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: var(--bg); color: var(--ink); }}
    .page {{ height: 100vh; display: flex; flex-direction: column; }}

    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--line);
      padding: 12px 14px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: start;
    }}

    .title {{ font-size: 16px; font-weight: 900; letter-spacing: 0.2px; }}
    .sub {{ margin-top: 4px; font-size: 13px; color: var(--muted); line-height: 1.4; }}
    .toolbar-actions {{ display: inline-flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }}

    .btn {{
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
      transition: all 160ms ease;
      white-space: nowrap;
    }}
    .btn:hover {{ border-color: rgba(37, 99, 235, 0.35); box-shadow: 0 1px 0 rgba(15, 23, 42, 0.06); }}
    .btn.primary {{ background: rgba(37, 99, 235, 0.10); border-color: rgba(37, 99, 235, 0.35); color: #1e3a8a; }}
    .btn.danger {{ background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.35); color: #991b1b; }}
    .btn:disabled {{ opacity: 0.55; cursor: not-allowed; }}
    .btn:focus {{ outline: none; }}

    .meta {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    .pill {{ background: rgba(37, 99, 235, 0.10); color: #1e3a8a; border: 1px solid rgba(37, 99, 235, 0.22); border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 800; }}
    .pill.warn {{ background: rgba(245, 158, 11, 0.12); border-color: rgba(245, 158, 11, 0.22); color: #92400e; }}
    .pill.muted {{ background: rgba(148, 163, 184, 0.12); border-color: rgba(148, 163, 184, 0.22); color: #334155; }}

    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; width: 100%; }}
    .stat-card {{ background: var(--panel); border: 1px solid var(--line-2); border-radius: 12px; padding: 10px; box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05); }}
    .stat-label {{ font-size: 12px; color: var(--muted); font-weight: 800; }}
    .stat-value {{ margin-top: 6px; font-size: 18px; font-weight: 900; color: var(--ink); }}

    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 320px 1fr; gap: 12px; padding: 12px; align-items: stretch; }}
    .sidebar {{ background: var(--panel); border: 1px solid var(--line-2); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); display: flex; flex-direction: column; min-height: 0; }}
    .sidebar-top {{ padding: 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); background: var(--panel-2); }}
    .nav-title {{ font-weight: 900; font-size: 14px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
    .nav-counter {{ font-size: 12px; font-weight: 900; color: #334155; background: rgba(148, 163, 184, 0.12); border: 1px solid rgba(148, 163, 184, 0.22); padding: 2px 8px; border-radius: 999px; }}
    .nav-search {{ width: 100%; margin-top: 10px; border: 1px solid rgba(148, 163, 184, 0.28); border-radius: 10px; padding: 9px 10px; font-size: 13px; outline: none; }}
    .nav-search:focus {{ border-color: rgba(37, 99, 235, 0.45); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }}
    .filters {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }}
    .chip {{ border: 1px solid rgba(148, 163, 184, 0.28); background: #ffffff; color: #334155; border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 900; cursor: pointer; }}
    .chip.active {{ background: rgba(37, 99, 235, 0.10); border-color: rgba(37, 99, 235, 0.35); color: #1e3a8a; }}

    .nav-list {{ padding: 10px; overflow: auto; min-height: 0; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid rgba(148, 163, 184, 0.22); background: #fff; border-radius: 12px; padding: 10px; margin-bottom: 8px; cursor: pointer; font-size: 13px; transition: all 160ms ease; }}
    .nav-item:hover {{ border-color: rgba(37, 99, 235, 0.35); background: rgba(37, 99, 235, 0.04); }}
    .nav-item.active {{ border-color: rgba(239, 68, 68, 0.55); background: rgba(239, 68, 68, 0.06); }}
    .nav-item.hidden {{ display: none; }}
    .nav-header {{ font-weight: 900; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .nav-text {{ color: #334155; line-height: 1.55; margin-bottom: 6px; }}
    .nav-item small {{ display: block; color: var(--muted); font-size: 12px; line-height: 1.35; }}

    .template-badge {{ background: var(--warn); color: white; font-size: 10px; padding: 2px 6px; border-radius: 6px; }}
    .locate-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 6px; }}
    .locate-badge.ok {{ background: var(--ok); color: #fff; }}
    .locate-badge.partial {{ background: var(--accent); color: #fff; }}
    .locate-badge.miss {{ background: #94a3b8; color: #fff; }}

    .content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; height: 100%; align-items: stretch; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line-2); border-radius: var(--radius); display: flex; flex-direction: column; min-height: 0; height: 100%; overflow: hidden; box-shadow: var(--shadow); }}
    .panel-header {{ padding: 12px 16px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); font-weight: 900; font-size: 16px; display: flex; justify-content: space-between; gap: 8px; background: var(--panel-2); }}
    .panel-header span:last-child {{ font-size: 14px; color: var(--muted); word-break: break-all; text-align: right; }}
    .panel-body {{ padding: 20px 18px 32px; overflow: auto; scroll-behavior: smooth; flex: 1; min-height: 420px; background: #fff; }}
    .panel-body .docx-content {{ font-size: 16px !important; line-height: 1.9 !important; color: #111827; }}
    .panel-body .docx-content p,
    .panel-body .docx-content li,
    .panel-body .docx-content td,
    .panel-body .docx-content th,
    .panel-body .docx-content div,
    .panel-body .docx-content span {{ font-size: 16px; line-height: 1.9; overflow-wrap: anywhere; word-break: break-word; }}
    .panel-body .docx-content h1,
    .panel-body .docx-content h2,
    .panel-body .docx-content h3,
    .panel-body .docx-content h4,
    .panel-body .docx-content h5,
    .panel-body .docx-content h6 {{ line-height: 1.6; overflow-wrap: anywhere; word-break: break-word; }}
    .panel-body .docx-content table {{ display: block; width: 100%; overflow-x: auto; border-collapse: collapse; }}
    .panel-body .docx-content img {{ max-width: 100%; height: auto; }}
    .source-doc-section.hidden {{ display: none; }}

    .empty {{ color: #94a3b8; font-size: 13px; padding: 20px; text-align: center; }}
    .hit {{
      background: rgba(239, 68, 68, 0.18) !important;
      color: #991b1b !important;
      border-radius: 6px;
      padding: 0 2px;
      cursor: pointer;
      transition: all 160ms ease;
    }}
    .hit.template {{ background: rgba(245, 158, 11, 0.18) !important; color: #92400e !important; }}
    .hit.paraphrase {{ background: rgba(37, 99, 235, 0.18) !important; color: #1e3a8a !important; }}
    .hit.active {{ box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18); background: rgba(239, 68, 68, 0.28) !important; }}

    @media (min-width: 1400px) {{
      .content {{ grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.1fr); }}
      .panel-body {{ min-height: 520px; }}
    }}

    @media (max-width: 1100px) {{
      .main {{ grid-template-columns: 1fr; }}
      .content {{ grid-template-columns: 1fr; }}
      .panel-body {{ min-height: 320px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="toolbar">
      <div>
        <div class="title">查重可视化报告</div>
        <div class="sub">主文档：{html.escape(primary_doc)} ｜ 来源文档：{html.escape(source_doc or 'N/A')}</div>
        <div class="stats">{stats}</div>
      </div>
      <div>
        <div class="toolbar-actions" id="toolbar-actions">
          <button class="btn" id="btn-prev" type="button">上一处</button>
          <button class="btn" id="btn-next" type="button">下一处</button>
          <button class="btn" id="btn-top" type="button">回到顶部</button>
        </div>
        <div class="meta" style="margin-top: 10px;">
          <div class="pill">有效片段：{effective_count}</div>
          <div class="pill">模板片段：{template_count}</div>
          <div class="pill muted">未定位：{unmatched_count}</div>
          <div class="pill">有效字数：{effective_chars}</div>
        </div>
      </div>
    </div>
    <div class="main">
      <aside class="sidebar">
        <div class="sidebar-top">
          <div class="nav-title">
            <span>重复片段导航</span>
            <span class="nav-counter" id="nav-counter">0/0</span>
          </div>
          <input id="nav-search" class="nav-search" placeholder="搜索片段关键词（支持模糊匹配）" />
          <div class="filters" id="nav-filters">
            <button class="chip active" type="button" data-filter="all">全部</button>
            <button class="chip" type="button" data-filter="effective">有效</button>
            <button class="chip" type="button" data-filter="template">模板</button>
            <button class="chip" type="button" data-filter="paraphrase">改写</button>
          </div>
        </div>
        <div class="nav-list" id="nav-list">
          {match_cards}
        </div>
      </aside>
      <section class="content">
        <div class="panel">
          <div class="panel-header"><span>主文档</span><span>{html.escape(primary_doc)}</span></div>
          <div id="primary-panel" class="panel-body">
            {left_html}
          </div>
        </div>
        <div class="panel">
          <div class="panel-header"><span>来源文档</span><span id="source-doc-label">{html.escape(source_doc or 'N/A')}</span></div>
          <div id="source-panel" class="panel-body">
            {right_html}
          </div>
        </div>
      </section>
    </div>
  </div>
  <script>
    (function() {{
      const highlightMap = new Map();
      const sourceLabel = document.getElementById('source-doc-label');

      function getMatchIds(el) {{
        return String(el.dataset.matchIds || el.dataset.matchId || '')
          .split(',')
          .map(item => item.trim())
          .filter(Boolean);
      }}
      
      function initHighlights() {{
        document.querySelectorAll('.hit[data-match-id]').forEach(el => {{
          getMatchIds(el).forEach(matchId => {{
            if (!highlightMap.has(matchId)) {{
              highlightMap.set(matchId, []);
            }}
            highlightMap.get(matchId).push(el);
          }});
        }});
      }}

      function switchSourceDoc(sourceDoc) {{
        const sections = Array.from(document.querySelectorAll('#source-panel .source-doc-section[data-source-doc]'));
        if (!sections.length) {{
          return null;
        }}
        const target = sections.find(el => el.dataset.sourceDoc === sourceDoc) || sections[0];
        sections.forEach(el => el.classList.toggle('hidden', el !== target));
        if (sourceLabel) {{
          sourceLabel.textContent = target.dataset.sourceName || target.dataset.sourceDoc || 'N/A';
        }}
        return target;
      }}
      
      let currentMatchId = null;

      const activateMatch = (matchId) => {{
        document.querySelectorAll('.hit.active').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-item.active').forEach(el => el.classList.remove('active'));
        
        const hits = highlightMap.get(matchId) || [];
        hits.forEach(el => el.classList.add('active'));
        
        const navItem = document.querySelector(`.nav-item[data-match-id="${{matchId}}"]`);
        if (navItem) navItem.classList.add('active');
        currentMatchId = matchId;
        
        if (hits.length > 0) {{
          const primaryHit = hits.find(el => el.dataset.side === 'primary') || hits[0];
          const sourceDoc = (navItem && navItem.dataset.sourceDoc) || '';
          if (sourceDoc) {{
            switchSourceDoc(sourceDoc);
          }}
          const sourceHit = hits.find(el => el.dataset.side === 'source' && (!sourceDoc || el.dataset.sourceDoc === sourceDoc));

          if (primaryHit) {{
            primaryHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          }}

          if (sourceHit) {{
            sourceHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          }}
        }}

        refreshCounter();
      }};

      function getVisibleNavItems() {{
        return Array.from(document.querySelectorAll('.nav-item')).filter(el => !el.classList.contains('hidden'));
      }}

      function refreshCounter() {{
        const items = getVisibleNavItems();
        const total = items.length;
        let idx = -1;
        if (currentMatchId) {{
          idx = items.findIndex(el => el.dataset.matchId === currentMatchId);
        }}
        const text = total > 0 ? `${{idx >= 0 ? idx + 1 : 0}}/${{total}}` : '0/0';
        const el = document.getElementById('nav-counter');
        if (el) el.textContent = text;

        const btnPrev = document.getElementById('btn-prev');
        const btnNext = document.getElementById('btn-next');
        if (btnPrev) btnPrev.disabled = total === 0;
        if (btnNext) btnNext.disabled = total === 0;
      }}

      function applyNavFilter() {{
        const input = document.getElementById('nav-search');
        const q = (input ? input.value : '').trim().toLowerCase();
        const activeChip = document.querySelector('#nav-filters .chip.active');
        const mode = activeChip ? activeChip.dataset.filter : 'all';

        document.querySelectorAll('.nav-item').forEach(el => {{
          const text = (el.innerText || '').toLowerCase();
          const okText = !q || text.includes(q);
          const isTemplate = el.dataset.template === '1';
          const isParaphrase = el.dataset.type === 'paraphrase';
          const okMode = mode === 'all'
            || (mode === 'template' && isTemplate)
            || (mode === 'effective' && !isTemplate)
            || (mode === 'paraphrase' && isParaphrase);
          el.classList.toggle('hidden', !(okText && okMode));
        }});
        const items = getVisibleNavItems();
        if (items.length) {{
          const stillVisible = currentMatchId && items.some(el => el.dataset.matchId === currentMatchId);
          if (!stillVisible) {{
            activateMatch(items[0].dataset.matchId);
            return;
          }}
        }}
        refreshCounter();
      }}
      
      initHighlights();
      applyNavFilter();

      const first = getVisibleNavItems()[0];
      if (first) {{
        activateMatch(first.dataset.matchId);
      }}
      
      document.addEventListener('click', (e) => {{
        const hit = e.target.closest('.hit');
        const navItem = e.target.closest('.nav-item');
        const chip = e.target.closest('#nav-filters .chip');
        const btnPrev = e.target.closest('#btn-prev');
        const btnNext = e.target.closest('#btn-next');
        const btnTop = e.target.closest('#btn-top');
        
        if (hit) {{
          e.preventDefault();
          activateMatch(hit.dataset.matchId);
        }} else if (navItem) {{
          e.preventDefault();
          activateMatch(navItem.dataset.matchId);
        }} else if (chip) {{
          e.preventDefault();
          document.querySelectorAll('#nav-filters .chip').forEach(x => x.classList.remove('active'));
          chip.classList.add('active');
          applyNavFilter();
        }} else if (btnPrev || btnNext) {{
          e.preventDefault();
          const actions = document.getElementById('toolbar-actions');
          if (actions) {{
            actions.querySelectorAll('.btn').forEach(b => b.classList.remove('primary'));
            (btnPrev || btnNext).classList.add('primary');
          }}
          const items = getVisibleNavItems();
          if (!items.length) return;
          const idx = currentMatchId ? items.findIndex(el => el.dataset.matchId === currentMatchId) : -1;
          let nextIdx = 0;
          if (btnPrev) {{
            nextIdx = idx <= 0 ? items.length - 1 : idx - 1;
          }} else {{
            nextIdx = idx < 0 ? 0 : (idx >= items.length - 1 ? 0 : idx + 1);
          }}
          const target = items[nextIdx];
          if (target) activateMatch(target.dataset.matchId);
        }} else if (btnTop) {{
          e.preventDefault();
          const actions = document.getElementById('toolbar-actions');
          if (actions) {{
            actions.querySelectorAll('.btn').forEach(b => b.classList.remove('primary'));
            btnTop.classList.add('primary');
          }}
          window.scrollTo({{ top: 0, behavior: 'smooth' }});
          const pp = document.getElementById('primary-panel');
          const sp = document.getElementById('source-panel');
          if (pp) pp.scrollTo({{ top: 0, behavior: 'smooth' }});
          if (sp) sp.scrollTo({{ top: 0, behavior: 'smooth' }});
        }}
      }});

      const input = document.getElementById('nav-search');
      if (input) {{
        input.addEventListener('input', () => applyNavFilter());
      }}
    }})();
  </script>
</body>
</html>"""


def main():
    """测试报告生成"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mammoth_report_builder.py <debug_json> [output_html]")
        sys.exit(1)
    
    debug_json = Path(sys.argv[1])
    output_html = Path(sys.argv[2]) if len(sys.argv) > 2 else debug_json.with_suffix('.html')
    
    builder = MammothPlagiarismReportBuilder()
    builder.build_from_debug_file(debug_json, output_html)
    
    print(f"Report generated: {output_html}")


if __name__ == "__main__":
    main()
