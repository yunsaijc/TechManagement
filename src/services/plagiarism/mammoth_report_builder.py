"""查重 HTML 报告生成器（使用mammoth保留Word格式版）

基于mammoth库将Word文档转换为HTML，保留原始格式，并叠加查重高亮。
"""
from __future__ import annotations

import html
import json
import re
import sys
from bisect import bisect_left
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
from src.services.plagiarism.text_repairs import repair_mammoth_html_artifacts


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
        source_docx_path: Optional[Path | str] = None
    ) -> Path:
        """从debug JSON文件生成HTML报告

        Args:
            debug_json_path: debug JSON文件路径
            output_html_path: 输出HTML文件路径
            primary_docx_path: 主文档DOCX路径（可选）
            source_docx_path: 来源文档DOCX路径（可选）
        """
        debug_json_path = Path(debug_json_path)
        output_html_path = Path(output_html_path)

        # 读取debug数据
        data = json.loads(debug_json_path.read_text(encoding="utf-8"))

        # 获取文档信息
        primary_doc = data.get("primary_doc", "Unknown")
        documents = data.get("documents", {})
        primary_scope = data.get("primary_scope") or {}
        primary_canonical = documents.get(primary_doc, "") if primary_doc else ""
        source_doc = ""
        for segment in data.get("duplicate_segments", []):
            sources = segment.get("sources", [])
            if sources:
                source_doc = sources[0].get("doc", "")
                break

        # 转换DOCX为HTML
        left_html = ""
        right_html = ""

        if primary_docx_path and Path(primary_docx_path).exists():
            left_html, _ = convert_docx_to_html_mammoth(primary_docx_path)
        else:
            left_html = self._build_fallback_content(data, "primary")

        if source_docx_path and Path(source_docx_path).exists():
            right_html, _ = convert_docx_to_html_mammoth(source_docx_path)
        else:
            right_html = self._build_fallback_content(data, "source")

        left_html = repair_mammoth_html_artifacts(left_html)
        right_html = repair_mammoth_html_artifacts(right_html)

        if primary_canonical and primary_scope:
            left_html = self._clip_primary_html_to_scope(left_html, primary_canonical)
        
        # 同时处理两侧高亮，确保每个片段都有两侧匹配
        left_html, right_html, match_results = self._apply_highlights_both_sides(
            left_html, right_html, data
        )
        
        # 构建统计信息
        stats = self._build_statistics(data)

        # 构建匹配导航
        match_cards = self._build_match_nav(data, match_results)

        # 渲染完整页面
        html_page = self._render_html_page(
            primary_doc=primary_doc,
            source_doc=source_doc,
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
        right_html: str,
        data: Dict
    ) -> Tuple[str, str, Dict[str, Dict[str, Any]]]:
        """基于 canonical 坐标映射在两侧 HTML 应用高亮。"""
        segments = data.get("duplicate_segments", [])
        if not segments:
            return left_html, right_html, {}

        primary_doc = data.get("primary_doc", "")
        documents = data.get("documents", {})
        source_doc = next(
            (s.get("sources", [{}])[0].get("doc", "") for s in segments if s.get("sources")),
            "",
        )
        left_canonical = documents.get(primary_doc, "")
        right_canonical = documents.get(source_doc, "")
        left_map = build_coordinate_map(left_canonical, left_html) if left_canonical else None
        right_map = build_coordinate_map(right_canonical, right_html) if right_canonical else None

        left_spans: List[Tuple[int, int, str, bool, str, str]] = []
        right_spans: List[Tuple[int, int, str, bool, str, str]] = []
        left_occupied: List[Tuple[int, int]] = []
        right_occupied: List[Tuple[int, int]] = []
        match_results: Dict[str, Dict[str, Any]] = {}

        sorted_segments = sorted(
            enumerate(segments),
            key=lambda x: (int(x[1].get("primary_start", 0) or 0), -len(x[1].get("primary_text", ""))),
        )

        for seg_idx, segment in sorted_segments:
            match_id = segment.get("match_id") or f"m{seg_idx+1:03d}"
            is_template = segment.get("is_template", False)
            match_type = segment.get("match_type", "exact")
            similarity = float(segment.get("similarity_score", segment.get("similarity", 0.0)) or 0.0)
            tone = self._highlight_tone(similarity)
            sources = segment.get("sources", [])
            if not sources:
                continue

            primary_start = int(segment.get("primary_start", 0) or 0)
            primary_end = int(segment.get("primary_end", 0) or 0)
            source_start = int(sources[0].get("start", 0) or 0) if sources else 0
            source_end = int(sources[0].get("end", 0) or 0) if sources else 0
            if primary_end <= primary_start or source_end <= source_start:
                continue

            if not left_map or not right_map:
                continue
            left_fragments, left_cov = left_map.span_to_html_fragments(primary_start, primary_end)
            right_fragments, right_cov = right_map.span_to_html_fragments(source_start, source_end)
            if not left_fragments or not right_fragments:
                continue

            left_fragments = self._clean_fragments_for_side(left_fragments, left_html, "primary")
            right_fragments = self._clean_fragments_for_side(right_fragments, right_html, "source")
            if not left_fragments or not right_fragments:
                continue

            left_filtered = self._filter_non_overlapping_fragments(left_fragments, left_occupied)
            right_filtered = self._filter_non_overlapping_fragments(right_fragments, right_occupied)
            if not left_filtered or not right_filtered:
                continue

            for left_start, left_end in left_filtered:
                left_occupied.append((left_start, left_end))
                left_spans.append((left_start, left_end, match_id, is_template, match_type, tone))
            for right_start, right_end in right_filtered:
                right_occupied.append((right_start, right_end))
                right_spans.append((right_start, right_end, match_id, is_template, match_type, tone))

            coverage = min(left_cov, right_cov)
            heading_mode = self._heading_alignment_mode(segment)
            match_results[match_id] = {
                "mode": "full" if coverage >= 0.85 and heading_mode == "aligned" else "core",
                "confidence": round(coverage, 4),
                "match_type": match_type,
                "tone": tone,
                "similarity": round(similarity, 4),
            }

        return (
            self._inject_spans(left_html, left_spans, "primary"),
            self._inject_spans(right_html, right_spans, "source"),
            match_results,
        )

    def _filter_non_overlapping_fragments(
        self,
        fragments: List[Tuple[int, int]],
        occupied: List[Tuple[int, int]],
    ) -> List[Tuple[int, int]]:
        filtered: List[Tuple[int, int]] = []
        total = len(fragments)
        for idx, (start, end) in enumerate(fragments):
            if self._is_discardable_short_fragment(fragments, idx):
                continue
            if self._has_overlap(occupied, start, end):
                continue
            filtered.append((start, end))
        return filtered

    def _is_discardable_short_fragment(
        self,
        fragments: List[Tuple[int, int]],
        idx: int,
    ) -> bool:
        start, end = fragments[idx]
        length = end - start
        if length >= 3:
            return False

        fragment_count = len(fragments)
        if fragment_count <= 1:
            return True

        prev_exists = idx > 0
        next_exists = idx + 1 < fragment_count

        # 被 Word 内联格式切开的连续高亮片段，2 字碎片也要保留。
        if length == 2 and prev_exists and next_exists:
            return False
        if length == 2 and (prev_exists or next_exists):
            return False
        return True

    def _clean_fragments_for_side(
        self,
        fragments: List[Tuple[int, int]],
        html_content: str,
        side: str,
    ) -> List[Tuple[int, int]]:
        if len(fragments) <= 1:
            return fragments

        annotated = []
        for start, end in fragments:
            text = self._fragment_text(html_content[start:end])
            annotated.append((start, end, text, self._looks_like_heading_text(text)))

        if side == "source":
            has_narrative = any((not is_heading) and len(text) >= 40 for _, _, text, is_heading in annotated)
            if has_narrative:
                cleaned = [
                    (start, end)
                    for start, end, text, is_heading in annotated
                    if not (is_heading and len(text) <= 40)
                ]
                if cleaned:
                    return cleaned

        return [(start, end) for start, end, _, _ in annotated]

    def _heading_alignment_mode(self, segment: Dict[str, Any]) -> str:
        primary_text = segment.get("primary_text", "") or ""
        sources = segment.get("sources", []) or []
        source_text = sources[0].get("text", "") if sources else ""
        primary_heading = self._extract_leading_heading(primary_text)
        source_heading = self._extract_leading_heading(source_text)

        if not primary_heading and not source_heading:
            return "aligned"
        if not primary_heading or not source_heading:
            return "mismatch"
        return "aligned" if self._normalize_heading(primary_heading) == self._normalize_heading(source_heading) else "mismatch"

    def _extract_leading_heading(self, text: str) -> str:
        cleaned = self._clean_nav_text(text)
        if not cleaned:
            return ""
        patterns = [
            r"^(项目简介|项目立项背景及意义)",
            r"^(第[一二三四五六七八九十百]+部分[^\s]{0,20})",
            r"^([一二三四五六七八九十]+[、\.．][^。！？；]{1,40})",
            r"^(\d+[、\.．][^。！？；]{1,40})",
        ]
        for pattern in patterns:
            match = re.match(pattern, cleaned)
            if match:
                return match.group(1).strip()
        return ""

    def _normalize_heading(self, text: str) -> str:
        cleaned = re.sub(r"\s+", "", text or "")
        cleaned = cleaned.replace(".", "．")
        return cleaned

    def _fragment_text(self, html_fragment: str) -> str:
        text = re.sub(r"<[^>]+>", "", html_fragment or "")
        return re.sub(r"\s+", " ", text).strip()

    def _looks_like_heading_text(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if not normalized:
            return False
        return bool(re.match(
            r"^(项目简介|项目立项背景及意义|第[一二三四五六七八九十百]+部分|第一部分|第二部分|第三部分|第四部分|第五部分|第六部分|"
            r"[一二三四五六七八九十]+[、\.．]|"
            r"\d+[、\.．])",
            normalized,
        )) and len(normalized) <= 50

    def _clip_primary_html_to_scope(self, html_content: str, canonical_text: str) -> str:
        if not html_content or not canonical_text:
            return html_content

        coord_map = build_coordinate_map(canonical_text, html_content)
        mapped_positions = sorted({pos for pos in coord_map.canonical_to_html if pos >= 0})
        if not mapped_positions:
            return html_content

        wrapper_match = re.search(r'<div class="docx-content">', html_content)
        if not wrapper_match:
            return html_content

        inner_start = wrapper_match.end()
        inner_end = html_content.rfind("</div>")
        if inner_end <= inner_start:
            return html_content

        prefix = html_content[:inner_start]
        suffix = html_content[inner_end:]
        inner_html = html_content[inner_start:inner_end]
        clipped_inner = self._clip_docx_inner_html(inner_html, inner_start, mapped_positions)
        if not clipped_inner.strip():
            return html_content
        return prefix + clipped_inner + suffix

    def _clip_docx_inner_html(
        self,
        inner_html: str,
        base_offset: int,
        mapped_positions: List[int],
    ) -> str:
        kept_parts: List[str] = []
        for kind, rel_start, rel_end, payload in self._extract_top_level_blocks(inner_html):
            abs_start = base_offset + rel_start
            abs_end = base_offset + rel_end
            if kind == "table":
                clipped_table = self._clip_table_block(str(payload), abs_start, mapped_positions)
                if clipped_table:
                    kept_parts.append(clipped_table)
                continue
            if self._has_mapped_position(mapped_positions, abs_start, abs_end):
                kept_parts.append(str(payload))
        return "".join(kept_parts)

    def _extract_top_level_blocks(
        self,
        html_fragment: str,
    ) -> List[Tuple[str, int, int, str]]:
        blocks: List[Tuple[str, int, int, str]] = []
        pos = 0
        while pos < len(html_fragment):
            if html_fragment[pos] != "<":
                pos += 1
                continue
            if html_fragment.startswith("<p", pos):
                end = self._find_tag_end(html_fragment, pos, "p")
                if end != -1:
                    blocks.append(("p", pos, end, html_fragment[pos:end]))
                    pos = end
                    continue
            if html_fragment.startswith("<table", pos):
                end = self._find_tag_end(html_fragment, pos, "table")
                if end != -1:
                    blocks.append(("table", pos, end, html_fragment[pos:end]))
                    pos = end
                    continue
            pos += 1
        return blocks

    def _clip_table_block(
        self,
        table_html: str,
        table_abs_start: int,
        mapped_positions: List[int],
    ) -> str:
        open_end = table_html.find(">")
        close_start = table_html.rfind("</table>")
        if open_end == -1 or close_start == -1 or close_start <= open_end:
            if self._has_mapped_position(mapped_positions, table_abs_start, table_abs_start + len(table_html)):
                return table_html
            return ""

        open_tag = table_html[:open_end + 1]
        close_tag = table_html[close_start:]
        inner_html = table_html[open_end + 1:close_start]

        kept_rows: List[str] = []
        pos = 0
        while pos < len(inner_html):
            row_start = inner_html.find("<tr", pos)
            if row_start == -1:
                break
            row_end = self._find_tag_end(inner_html, row_start, "tr")
            if row_end == -1:
                break
            abs_start = table_abs_start + open_end + 1 + row_start
            abs_end = table_abs_start + open_end + 1 + row_end
            if self._has_mapped_position(mapped_positions, abs_start, abs_end):
                kept_rows.append(inner_html[row_start:row_end])
            pos = row_end

        if not kept_rows:
            return ""
        return open_tag + "".join(kept_rows) + close_tag

    def _find_tag_end(self, html_fragment: str, start: int, tag_name: str) -> int:
        close_tag = f"</{tag_name}>"
        close_idx = html_fragment.find(close_tag, start)
        if close_idx == -1:
            return -1
        return close_idx + len(close_tag)

    def _has_mapped_position(
        self,
        mapped_positions: List[int],
        start: int,
        end: int,
    ) -> bool:
        if end <= start or not mapped_positions:
            return False
        idx = bisect_left(mapped_positions, start)
        return idx < len(mapped_positions) and mapped_positions[idx] < end

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

    def _has_overlap(self, used: List[Tuple[int, int]], start: int, end: int) -> bool:
        for s, e in used:
            if start < e and end > s:
                return True
        return False

    def _inject_spans(
        self,
        html_content: str,
        spans: List[Tuple[int, int, str, bool, str, str]],
        side: str,
    ) -> str:
        result = html_content
        for start, end, match_id, is_template, match_type, tone in sorted(spans, key=lambda x: x[0], reverse=True):
            classes = ["hit"]
            if is_template:
                classes.append("template")
            classes.append(tone)
            class_attr = " ".join(classes)
            wrapped = (
                f'<span class="{class_attr}" data-match-id="{match_id}" data-side="{side}" data-match-type="{match_type}" data-tone="{tone}">'
                f"{result[start:end]}</span>"
            )
            result = result[:start] + wrapped + result[end:]
        return result

    def _highlight_tone(self, similarity: float) -> str:
        return "strong" if similarity >= 0.78 else "soft"

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
        
        duplicate_chars = self._union_length([
            (int(s.get("primary_start", 0) or 0), int(s.get("primary_end", 0) or 0))
            for s in segments + template_segments
        ])
        
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

    def _build_match_nav(self, data: Dict, match_results: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
        """构建匹配片段导航"""
        segments = data.get("duplicate_segments", [])
        if not segments:
            return '<p class="empty">无重复片段</p>'

        cards = []
        for i, segment in enumerate(segments[:50], 1):  # 最多显示50个
            match_id = segment.get("match_id") or f"m{i:03d}"
            primary_text = self._clean_nav_text(segment.get("primary_text", ""))[:60]
            is_template = segment.get("is_template", False)
            similarity = segment.get("similarity_score", segment.get("similarity", 1.0))
            
            sources = segment.get("sources", [])
            source_info = ""
            if sources:
                source_doc = sources[0].get("doc", "")
                source_info = f"来源: {html.escape(source_doc)}"
            
            template_badge = '<span class="template-badge">模板</span>' if is_template else ''
            
            cards.append(f'''<button class="nav-item" data-match-id="{match_id}">
                <div class="nav-header">#{i} {template_badge}</div>
                <div class="nav-text">{html.escape(primary_text)}...</div>
                <small>相似度: {similarity:.2f} | {source_info}</small>
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
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif; background: #f5f7fb; color: #1f2937; }}
    .page {{ height: 100vh; display: flex; flex-direction: column; }}
    .toolbar {{ position: sticky; top: 0; z-index: 20; background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 14px 18px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
    .title {{ font-size: 18px; font-weight: 700; }}
    .meta {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 300px 1fr; gap: 12px; padding: 12px; }}
    .sidebar {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; overflow: auto; }}
    .content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; }}
    .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }}
    .panel-header {{ padding: 12px 14px; border-bottom: 1px solid #e5e7eb; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; background: #f8fafc; }}
    .panel-body {{ padding: 16px; overflow: auto; scroll-behavior: smooth; }}
    .nav-title {{ font-weight: 700; margin-bottom: 10px; font-size: 14px; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 10px; margin-bottom: 8px; cursor: pointer; font-size: 13px; }}
    .nav-item:hover {{ border-color: #fca5a5; background: #fff5f5; }}
    .nav-item.active {{ border-color: #ef4444; background: #fef2f2; }}
    .nav-header {{ font-weight: 600; margin-bottom: 4px; }}
    .nav-text {{ color: #374151; margin-bottom: 4px; }}
    .nav-item small {{ display: block; color: #6b7280; font-size: 11px; }}
    .template-badge {{ background: #f59e0b; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 4px; }}
    .docx-content .hit {{ color: inherit !important; }}
    .docx-content .hit.strong {{ background: rgba(220, 38, 38, 0.34) !important; }}
    .docx-content .hit.strong:hover {{ background: rgba(220, 38, 38, 0.42) !important; }}
    .docx-content .hit.soft {{ background: rgba(248, 113, 113, 0.20) !important; }}
    .docx-content .hit.soft:hover {{ background: rgba(248, 113, 113, 0.28) !important; }}
    .docx-content .hit.active {{
      box-shadow: 0 0 0 2px rgba(153, 27, 27, 0.35) !important;
      outline: 1px solid rgba(127, 29, 29, 0.65);
      background-image: linear-gradient(rgba(253, 224, 71, 0.72), rgba(253, 224, 71, 0.72)) !important;
      background-blend-mode: multiply;
    }}
    .empty {{ color: #9ca3af; font-size: 13px; padding: 20px; text-align: center; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; width: 100%; }}
    .stat-card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 4px; font-size: 20px; font-weight: 700; color: #0f172a; }}
    
    {mammoth_styles}
  </style>
</head>
<body>
  <div class="page">
    <div class="toolbar">
      <div>
        <div class="title">查重可视化报告</div>
        <div style="font-size: 13px; color: #6b7280; margin-top: 4px;">左侧主文档：{html.escape(primary_doc)} ｜ 右侧来源文档：{html.escape(source_doc or 'N/A')}</div>
        <div class="stats">{stats}</div>
      </div>
      <div class="meta">
        <div class="pill">有效重复段：{effective_count}</div>
        <div class="pill">已高亮：{matched_count}</div>
        <div class="pill">未定位：{unmatched_count}</div>
        <div class="pill">模板段：{template_count}</div>
        <div class="pill">有效字符：{effective_chars}</div>
      </div>
    </div>
    <div class="main">
      <aside class="sidebar">
        <div class="nav-title">重复片段导航</div>
        {match_cards}
      </aside>
      <section class="content">
        <div class="panel">
          <div class="panel-header"><span>Primary</span><span>{html.escape(primary_doc)}</span></div>
          <div id="primary-panel" class="panel-body">
            {left_html}
          </div>
        </div>
        <div class="panel">
          <div class="panel-header"><span>Source</span><span>{html.escape(source_doc or 'N/A')}</span></div>
          <div id="source-panel" class="panel-body">
            {right_html}
          </div>
        </div>
      </section>
    </div>
  </div>
  <script>
    // 高亮交互功能
    (function() {{
      // 存储所有高亮元素的位置信息
      const highlightMap = new Map();
      
      // 初始化：收集所有高亮元素的位置
      function initHighlights() {{
        document.querySelectorAll('.hit[data-match-id]').forEach(el => {{
          const matchId = el.dataset.matchId;
          if (!highlightMap.has(matchId)) {{
            highlightMap.set(matchId, []);
          }}
          highlightMap.get(matchId).push(el);
        }});
      }}
      
      const activateMatch = (matchId) => {{
        // 清除所有激活状态
        document.querySelectorAll('.hit.active').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-item.active').forEach(el => el.classList.remove('active'));
        
        // 激活当前匹配的高亮元素
        const hits = highlightMap.get(matchId) || [];
        hits.forEach(el => el.classList.add('active'));
        
        // 激活导航项
        const navItem = document.querySelector(`.nav-item[data-match-id="${{matchId}}"]`);
        if (navItem) navItem.classList.add('active');
        
        // 左右两侧分别滚动到首个匹配片段。
        // 一个 match_id 现在可能被拆成多个 fragment，不能再假设 hits[0]/hits[1] 分别对应左右两侧。
        if (hits.length > 0) {{
          const primaryHit = hits.find(el => el.dataset.side === 'primary') || hits[0];
          const sourceHit = hits.find(el => el.dataset.side === 'source');

          if (primaryHit) {{
            primaryHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          }}

          if (sourceHit) {{
            sourceHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          }}
        }}
      }};
      
      // 初始化
      initHighlights();
      
      // 绑定点击事件 - 使用事件委托
      document.addEventListener('click', (e) => {{
        const hit = e.target.closest('.hit');
        const navItem = e.target.closest('.nav-item');
        
        if (hit) {{
          e.preventDefault();
          activateMatch(hit.dataset.matchId);
        }} else if (navItem) {{
          e.preventDefault();
          activateMatch(navItem.dataset.matchId);
        }}
      }});
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
