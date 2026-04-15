"""查重 HTML 报告生成器（使用mammoth保留Word格式版）

基于mammoth库将Word文档转换为HTML，保留原始格式，并叠加查重高亮。
"""
from __future__ import annotations

import html
import json
import re
import sys
from difflib import SequenceMatcher
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

        # 转换DOCX为HTML
        left_html = ""

        if primary_docx_path and Path(primary_docx_path).exists():
            left_html, _ = convert_docx_to_html_mammoth(primary_docx_path)
        else:
            left_html = self._build_fallback_content(data, "primary")

        left_html = repair_mammoth_html_artifacts(left_html)

        if primary_canonical and primary_scope:
            left_html = self._clip_primary_html_to_scope(left_html, primary_canonical)

        # 仅在 Primary 全文做高亮；右侧改为多来源片段面板
        left_html, match_results = self._apply_highlights_primary(left_html, data)

        # 构建统计信息
        stats = self._build_statistics(data)

        # 构建匹配导航
        match_cards = self._build_match_nav(data, match_results)
        source_panel_html = self._build_source_snippet_panel(data, match_results)
        source_doc_count = self._count_source_docs(data)

        # 渲染完整页面
        html_page = self._render_html_page(
            primary_doc=primary_doc,
            source_doc_count=source_doc_count,
            stats=stats,
            match_cards=match_cards,
            left_html=left_html,
            source_panel_html=source_panel_html,
            summary=data.get("summary", {}),
            matched_count=len(match_results),
            unmatched_count=max(0, len((data.get("match_groups") or data.get("duplicate_segments", []))) - len(match_results)),
        )

        # 写入文件
        output_html_path.write_text(html_page, encoding="utf-8")
        return output_html_path

    def _apply_highlights_primary(
        self,
        left_html: str,
        data: Dict
    ) -> Tuple[str, Dict[str, Dict[str, Any]]]:
        """基于 canonical 坐标映射在 Primary HTML 应用高亮。"""
        # 优先使用归并后的 match_groups
        segments = data.get("match_groups") or data.get("duplicate_segments", [])
        if not segments:
            return left_html, {}

        primary_doc = data.get("primary_doc", "")
        documents = data.get("documents", {})
        left_canonical = documents.get(primary_doc, "")
        left_map = build_coordinate_map(left_canonical, left_html) if left_canonical else None

        left_spans: List[Tuple[int, int, str, bool, str, str]] = []
        left_occupied: List[Tuple[int, int]] = []
        match_results: Dict[str, Dict[str, Any]] = {}

        sorted_segments = sorted(
            enumerate(segments),
            key=lambda x: (int(x[1].get("primary_start", 0) or 0), -len(x[1].get("primary_text", ""))),
        )

        for seg_idx, segment in sorted_segments:
            match_id = segment.get("match_id") or segment.get("group_id") or f"m{seg_idx+1:03d}"
            is_template = segment.get("is_template", False)
            match_type = segment.get("match_type", "exact")
            similarity = float(segment.get("similarity_score", segment.get("similarity", 0.0)) or 0.0)
            tone = self._highlight_tone(similarity)
            all_sources = segment.get("sources", [])
            primary_start = int(segment.get("primary_start", 0) or 0)
            primary_end = int(segment.get("primary_end", 0) or 0)

            if primary_end <= primary_start:
                continue

            mapped_primary = False
            if left_map:
                left_fragments, _ = left_map.span_to_html_fragments(primary_start, primary_end)
                if left_fragments:
                    left_fragments = self._clean_fragments_for_side(left_fragments, left_html, "primary")
                    left_filtered = self._filter_non_overlapping_fragments(left_fragments, left_occupied)
                    for left_start, left_end in left_filtered:
                        left_occupied.append((left_start, left_end))
                        left_spans.append((left_start, left_end, match_id, is_template, match_type, tone))
                    if left_filtered:
                        mapped_primary = True
            else:
                # 无坐标映射时保留该分组，避免纯文本兜底模式下导航被清空
                mapped_primary = True

            # 仅保留能在 Primary 侧落点的分组，避免右侧有卡片但左侧无高亮
            if not mapped_primary:
                continue

            heading_mode = self._heading_alignment_mode(segment)

            match_results[match_id] = {
                "mode": "full" if similarity >= 0.85 and heading_mode == "aligned" else "core",
                "confidence": round(similarity, 4),
                "match_type": match_type,
                "tone": tone,
                "similarity": round(similarity, 4),
                "source_count": len(all_sources),
            }

        return self._inject_spans(left_html, left_spans, "primary"), match_results

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
            primary_doc = data.get("primary_doc", "")
            text = documents.get(primary_doc, "")
            title = data.get("primary_doc", "主文档")
        else:
            source_doc = data.get("report_source_doc", "")
            text = documents.get(source_doc, "")
            title = source_doc or "来源文档"
        
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
        primary_doc = data.get("primary_doc", "")
        
        # 统计口径：优先使用 MultiSourceAggregator 计算出的有效值
        total_chars = int(summary.get("primary_scope_chars") or text_lengths.get(primary_doc, 0))
        if total_chars == 0:
            docs = data.get("documents", {})
            primary_text = docs.get(primary_doc, "") if primary_doc else ""
            if isinstance(primary_text, str) and primary_text:
                total_chars = len(primary_text)

        # 优先使用归并后的值
        effective_chars = int(summary.get("effective_duplicate_chars") or self._union_length([
            (int(s.get("primary_start", 0) or 0), int(s.get("primary_end", 0) or 0))
            for s in data.get("duplicate_segments", [])
        ]))

        duplicate_chars = self._union_length([
            (int(s.get("primary_start", 0) or 0), int(s.get("primary_end", 0) or 0))
            for s in (data.get("duplicate_segments", []) + data.get("template_segments", []))
        ])
        
        # 计算重复率
        effective_rate = (effective_chars / total_chars * 100) if total_chars > 0 else 0
        # 总重复率按“有效段+模板段”的并集字符计算，避免重叠区间重复计数导致 >100%
        total_rate = (duplicate_chars / total_chars * 100) if total_chars > 0 else 0
        total_rate = min(total_rate, 100.0)

        return f"""<div class="stat-card"><div class="stat-label">有效重复率</div><div class="stat-value" style="color: #dc2626;">{effective_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">总重复率</div><div class="stat-value">{total_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">有效/总字数</div><div class="stat-value" style="font-size: 16px;">{effective_chars:,} / {total_chars:,}</div></div>"""

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
        segments = data.get("match_groups") or data.get("duplicate_segments", [])
        if not segments:
            return '<p class="empty">无重复片段</p>'

        visible_ids = set((match_results or {}).keys())
        cards = []
        display_idx = 0
        for i, segment in enumerate(segments[:100], 1):  # 增加显示数量
            match_id = segment.get("match_id") or segment.get("group_id") or f"m{i:03d}"
            if visible_ids and match_id not in visible_ids:
                continue
            display_idx += 1
            primary_text = self._clean_nav_text(segment.get("primary_text", ""))[:60]
            is_template = segment.get("is_template", False)
            similarity = float(segment.get("similarity_score", segment.get("similarity", 1.0)) or 0.0)

            all_sources = segment.get("sources", [])
            unique_docs = []
            seen_docs = set()
            doc_hit_count = {}
            doc_score = {}
            for source in all_sources:
                doc = str(source.get("doc") or "")
                if not doc:
                    continue
                if doc not in seen_docs:
                    unique_docs.append(doc)
                    seen_docs.add(doc)
                doc_hit_count[doc] = int(doc_hit_count.get(doc, 0)) + 1
                score_val = float(source.get("similarity_score", similarity) or 0.0)
                doc_score[doc] = max(float(doc_score.get(doc, 0.0)), score_val)

            source_doc_count = len(unique_docs)
            source_piece_count = len(all_sources)
            top_doc = ""
            if unique_docs:
                top_doc = sorted(
                    unique_docs,
                    key=lambda d: (-float(doc_score.get(d, 0.0)), -int(doc_hit_count.get(d, 0)), d),
                )[0]
            source_info = f"主来源: {html.escape(top_doc)}" if top_doc else "主来源: -"

            source_badge = ""
            if source_doc_count > 1:
                source_badge = f'<span class="pill" style="padding: 2px 6px; font-size: 10px;">{source_doc_count}个来源文档</span>'
            elif source_piece_count > 1:
                source_badge = f'<span class="pill" style="padding: 2px 6px; font-size: 10px;">{source_piece_count}个来源片段</span>'
            template_badge = '<span class="template-badge">模板</span>' if is_template else ''
            
            cards.append(f'''<button class="nav-item" data-match-id="{match_id}">
                <div class="nav-header">#{display_idx} {template_badge} {source_badge}</div>
                <div class="nav-text">{html.escape(primary_text)}...</div>
                <small>相似度 {similarity:.2f} · {source_info}</small>
            </button>''')

        return "".join(cards) if cards else '<p class="empty">未定位到可高亮的重复片段</p>'

    def _build_source_snippet_panel(
        self,
        data: Dict,
        match_results: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        segments = data.get("match_groups") or data.get("duplicate_segments", [])
        if not segments:
            return '<p class="empty">无来源片段</p>'

        visible_ids = set((match_results or {}).keys())
        cards: List[str] = []
        for i, segment in enumerate(segments, 1):
            match_id = segment.get("match_id") or segment.get("group_id") or f"m{i:03d}"
            if visible_ids and match_id not in visible_ids:
                continue

            primary_full_text = self._clean_nav_text(segment.get("primary_text", ""))
            primary_text = primary_full_text[:90]
            sources = segment.get("sources", []) or []
            if not sources:
                continue
            ordered_sources = sorted(
                sources,
                key=lambda source: (
                    str(source.get("doc") or ""),
                    int(source.get("start", 0) or 0),
                    int(source.get("line", 0) or 0),
                ),
            )

            source_items: List[str] = []
            for source in ordered_sources[:8]:
                source_doc = html.escape(str(source.get("doc") or "-"))
                source_line = source.get("line")
                source_text = self._resolve_source_display_text(data, source, primary_hint=primary_full_text)
                source_similarity = self._display_similarity(primary_full_text, source_text)
                line_info = f" L{int(source_line)}" if isinstance(source_line, int) or (isinstance(source_line, str) and source_line.isdigit()) else ""
                source_items.append(
                    f'''<div class="source-item">
  <div class="source-meta">{source_doc}{line_info} · 相似度 {source_similarity:.2f}</div>
  <div class="source-text"><span class="hit soft" data-side="source" data-match-id="{match_id}">{html.escape(source_text or "(无片段文本)")}</span></div>
</div>'''
                )

            more = ""
            if len(ordered_sources) > 8:
                more = f'<div class="source-more">其余 {len(ordered_sources) - 8} 个来源已折叠</div>'

            cards.append(
                f'''<div class="source-card" data-match-id="{match_id}">
  <div class="source-card-title">#{i} {html.escape(primary_text)}...</div>
  <div class="source-list">
    {"".join(source_items)}
    {more}
  </div>
</div>'''
            )

        return "".join(cards) if cards else '<p class="empty">无来源片段</p>'

    def _resolve_source_display_text(
        self,
        data: Dict,
        source: Dict[str, Any],
        primary_hint: str = "",
        max_chars: int = 480,
    ) -> str:
        documents = data.get("documents", {}) or {}
        doc_id = str(source.get("doc") or "")
        doc_text = documents.get(doc_id, "")

        start = int(source.get("start", 0) or 0)
        end = int(source.get("end", 0) or 0)
        text = ""
        if isinstance(doc_text, str) and doc_text and end > start:
            text_len = len(doc_text)
            if 0 <= start < text_len and 0 < end <= text_len + 1:
                # 轻量上下文，避免把不相关句子带进右侧证据片段。
                clip_start = max(0, start - 12)
                clip_end = min(text_len, end + 20)
                if clip_end > clip_start:
                    text = doc_text[clip_start:clip_end]

        if not text:
            text = str(source.get("text", "") or "")

        cleaned = self._clean_nav_text(text)
        if primary_hint:
            return self._extract_overlap_excerpt(primary_hint, cleaned, max_chars=max_chars)
        if len(cleaned) > max_chars:
            return cleaned[:max_chars] + "..."
        return cleaned

    def _display_similarity(self, primary_text: str, source_text: str) -> float:
        primary_compact = re.sub(r"\s+", "", primary_text or "")
        source_compact = re.sub(r"\s+", "", source_text or "")
        if len(primary_compact) < 12 or len(source_compact) < 12:
            return 0.0
        ratio = SequenceMatcher(
            None,
            primary_compact[:4000],
            source_compact[:4000],
            autojunk=False,
        ).ratio()
        return round(float(ratio), 4)

    def _extract_overlap_excerpt(self, primary_text: str, source_text: str, max_chars: int = 480) -> str:
        source_clean = self._clean_nav_text(source_text or "")
        primary_clean = self._clean_nav_text(primary_text or "")
        if not source_clean:
            return ""
        if not primary_clean:
            return source_clean[:max_chars] + ("..." if len(source_clean) > max_chars else "")

        source_compact, source_map = self._compact_with_map(source_clean)
        primary_compact, _ = self._compact_with_map(primary_clean)
        if len(source_compact) < 12 or len(primary_compact) < 12:
            return source_clean[:max_chars] + ("..." if len(source_clean) > max_chars else "")

        matcher = SequenceMatcher(None, primary_compact[:6000], source_compact[:12000], autojunk=False)
        match = matcher.find_longest_match(0, min(len(primary_compact), 6000), 0, min(len(source_compact), 12000))

        if match.size < 20:
            target_chars = min(max_chars, 220)
            excerpt = source_clean[:target_chars]
            return excerpt + ("..." if len(source_clean) > target_chars else "")

        # 以最长重叠为核心，窗口大小跟随实际重叠长度，避免“证据段”过长。
        overlap_chars = max(match.size, 60)
        side_context = min(80, max(24, overlap_chars // 3))
        target_chars = min(max_chars, max(160, overlap_chars + side_context * 2))

        start_compact = max(0, match.b - side_context)
        end_compact = min(len(source_compact), match.b + match.size + side_context)
        current_len = end_compact - start_compact
        if current_len > target_chars:
            center = match.b + (match.size // 2)
            half = target_chars // 2
            start_compact = max(0, center - half)
            end_compact = min(len(source_compact), start_compact + target_chars)
            if end_compact - start_compact < target_chars:
                start_compact = max(0, end_compact - target_chars)
            current_len = end_compact - start_compact
        if current_len < target_chars:
            extra = target_chars - current_len
            left_extra = extra // 2
            right_extra = extra - left_extra
            start_compact = max(0, start_compact - left_extra)
            end_compact = min(len(source_compact), end_compact + right_extra)

        start_orig = source_map[start_compact] if source_map and start_compact < len(source_map) else 0
        if source_map and end_compact > 0:
            end_orig = source_map[end_compact - 1] + 1
        else:
            end_orig = len(source_clean)
        start_orig = max(0, min(start_orig, len(source_clean)))
        end_orig = max(start_orig, min(end_orig, len(source_clean)))
        excerpt = source_clean[start_orig:end_orig].strip()
        if not excerpt:
            excerpt = source_clean[:target_chars]
        if start_orig > 0:
            excerpt = "..." + excerpt
        if end_orig < len(source_clean):
            excerpt = excerpt + "..."
        return excerpt

    def _compact_with_map(self, text: str) -> Tuple[str, List[int]]:
        compact_chars: List[str] = []
        index_map: List[int] = []
        for idx, ch in enumerate(text):
            if ch.isspace():
                continue
            compact_chars.append(ch)
            index_map.append(idx)
        return "".join(compact_chars), index_map

    def _count_source_docs(self, data: Dict) -> int:
        segments = data.get("match_groups") or data.get("duplicate_segments", [])
        docs = set()
        for segment in segments:
            for source in segment.get("sources", []) or []:
                doc = source.get("doc")
                if doc:
                    docs.add(str(doc))
        return len(docs)

    def _clean_nav_text(self, text: str) -> str:
        cleaned = re.sub(r"\[表格行\d+\]", "", text or "")
        cleaned = cleaned.replace("|", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _render_html_page(
        self,
        primary_doc: str,
        source_doc_count: int,
        stats: str,
        match_cards: str,
        left_html: str,
        source_panel_html: str,
        summary: dict,
        matched_count: int = 0,
        unmatched_count: int = 0,
    ) -> str:
        """渲染完整HTML页面"""
        
        # 统一使用多源归并后的统计口径；旧 summary 仅作为兼容兜底。
        effective_count = int(summary.get("group_count") or summary.get("total_effective_segments") or 0)
        template_count = int(summary.get("total_template_segments") or 0)
        effective_chars = int(summary.get("effective_duplicate_chars") or summary.get("total_effective_chars") or 0)
        
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

    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 320px 1fr; gap: 12px; padding: 12px; }}
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
    .source-card {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; margin-bottom: 10px; background: #ffffff; }}
    .source-card-title {{ font-size: 12px; color: #0f172a; font-weight: 600; margin-bottom: 8px; }}
    .source-item {{ border-top: 1px dashed #e2e8f0; padding-top: 8px; margin-top: 8px; }}
    .source-item:first-child {{ border-top: 0; padding-top: 0; margin-top: 0; }}
    .source-meta {{ font-size: 11px; color: #475569; margin-bottom: 4px; }}
    .source-text {{ font-size: 13px; line-height: 1.6; color: #1f2937; }}
    .source-more {{ margin-top: 8px; font-size: 11px; color: #64748b; }}
    .hit {{ color: inherit !important; border-radius: 3px; padding: 0 1px; transition: background .12s ease; }}
    .hit.strong {{ background: rgba(220, 38, 38, 0.34) !important; }}
    .hit.strong:hover {{ background: rgba(220, 38, 38, 0.42) !important; }}
    .hit.soft {{ background: rgba(248, 113, 113, 0.20) !important; }}
    .hit.soft:hover {{ background: rgba(248, 113, 113, 0.28) !important; }}
    .hit.active {{
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
        <div style="font-size: 13px; color: #6b7280; margin-top: 4px;">左侧主文档：{html.escape(primary_doc)} ｜ 右侧来源片段：{source_doc_count} 个文档</div>
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
          <div class="panel-header"><span>Sources</span><span>{source_doc_count} docs</span></div>
          <div id="source-panel" class="panel-body">
            {source_panel_html}
          </div>
        </div>
      </section>
    </div>
  </div>
  <script>
    (function() {{
      const highlightMap = new Map();
      
      function initHighlights() {{
        document.querySelectorAll('.hit[data-match-id]').forEach(el => {{
          const matchId = el.dataset.matchId;
          if (!highlightMap.has(matchId)) {{
            highlightMap.set(matchId, []);
          }}
          highlightMap.get(matchId).push(el);
        }});
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
          const sourceHit = hits.find(el => el.dataset.side === 'source');

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
