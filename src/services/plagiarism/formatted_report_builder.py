"""查重 HTML 报告生成器（保留Word格式版）

基于原始Word文档格式生成可离线查看的双栏查重 HTML 报告。
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import re
import sys

# 避免通过services/__init__.py导入，防止循环导入
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.file_handler.docx_html_converter import (
    DOCXtoHTMLConverter, HTMLDocument, convert_docx_to_html
)


class FormattedPlagiarismReportBuilder:
    """基于原始Word格式的查重HTML报告生成器"""

    def build_from_debug_file(
        self,
        debug_json_path: Path,
        output_html_path: Path,
        primary_docx_path: Optional[Path] = None,
        source_docx_path: Optional[Path] = None
    ) -> Path:
        """从debug文件生成HTML报告

        Args:
            debug_json_path: debug JSON文件路径
            output_html_path: 输出HTML路径
            primary_docx_path: 主文档DOCX路径（可选，优先使用）
            source_docx_path: 来源文档DOCX路径（可选，优先使用）

        Returns:
            输出HTML路径
        """
        data = json.loads(debug_json_path.read_text(encoding="utf-8"))
        html_content = self.build_html(data, primary_docx_path, source_docx_path)
        output_html_path.write_text(html_content, encoding="utf-8")
        return output_html_path

    def build_html(
        self,
        data: dict,
        primary_docx_path: Optional[Path] = None,
        source_docx_path: Optional[Path] = None
    ) -> str:
        """生成HTML报告

        Args:
            data: debug数据字典
            primary_docx_path: 主文档DOCX路径
            source_docx_path: 来源文档DOCX路径

        Returns:
            HTML字符串
        """
        primary_doc = data.get("primary_doc", "主文档")
        duplicate_segments = data.get("duplicate_segments", []) or []
        template_segments = data.get("template_segments", []) or []
        summary = data.get("summary", {}) or {}
        texts = data.get("documents", {}) or {}

        source_doc = self._pick_source_doc(duplicate_segments, template_segments)

        # 获取HTML内容
        primary_html_doc = self._get_document_html(
            primary_doc, texts.get(primary_doc, ""), primary_docx_path
        )
        source_html_doc = self._get_document_html(
            source_doc, texts.get(source_doc, ""), source_docx_path
        )

        # 应用高亮
        left_html = self._apply_highlights(
            primary_html_doc, duplicate_segments + template_segments, "primary"
        )
        right_html = self._apply_highlights(
            source_html_doc, duplicate_segments + template_segments, "source"
        )

        # 生成统计
        primary_text = primary_html_doc.plain_text if primary_html_doc else texts.get(primary_doc, "")
        stats = self._build_statistics(summary, primary_text, duplicate_segments, template_segments)
        match_cards = self._build_match_nav(duplicate_segments)

        return self._render_html_page(
            primary_doc=primary_doc,
            source_doc=source_doc,
            stats=stats,
            match_cards=match_cards,
            left_html=left_html,
            right_html=right_html,
            summary=summary
        )

    def _get_document_html(
        self,
        doc_name: str,
        plain_text: str,
        docx_path: Optional[Path]
    ) -> Optional[HTMLDocument]:
        """获取文档的HTML表示

        优先使用DOCX文件，否则使用纯文本
        """
        if docx_path and docx_path.exists():
            try:
                return convert_docx_to_html(str(docx_path))
            except Exception as e:
                print(f"[Warning] Failed to convert {docx_path}: {e}")

        # 回退到纯文本
        if plain_text:
            return HTMLDocument(
                html=f'<div class="docx-content"><p class="docx-paragraph">{html.escape(plain_text)}</p></div>',
                plain_text=plain_text,
                positions=[]
            )
        return None

    def _apply_highlights(
        self,
        html_doc: Optional[HTMLDocument],
        segments: List[dict],
        side: str
    ) -> str:
        """在HTML上应用高亮标记"""
        if not html_doc:
            return '<div class="empty">暂无内容</div>'

        html_content = html_doc.html
        plain_text = html_doc.plain_text

        # 收集高亮范围
        ranges = []
        for idx, segment in enumerate(segments, start=1):
            match_id = f"m{idx:03d}"

            if side == "primary":
                start = int(segment.get("primary_start", 0) or 0)
                end = int(segment.get("primary_end", 0) or 0)
            else:
                source = (segment.get("sources") or [{}])[0]
                start = int(source.get("start", 0) or 0)
                end = int(source.get("end", 0) or 0)

            if end > start:
                ranges.append((start, end, match_id))

        if not ranges:
            return html_content

        # 排序并合并重叠范围
        ranges.sort(key=lambda x: x[0])
        merged = self._normalize_ranges(ranges)

        # 构建带高亮的HTML
        return self._render_highlighted_html(html_content, plain_text, merged, html_doc.positions)

    def _render_highlighted_html(
        self,
        html_content: str,
        plain_text: str,
        ranges: List[Tuple[int, int, str]],
        positions: List
    ) -> str:
        """渲染带高亮的HTML

        由于精确映射比较复杂，这里采用一种实用的方法：
        1. 在纯文本上标记高亮位置
        2. 使用JavaScript在客户端进行高亮
        """
        # 将高亮数据嵌入HTML供JS使用
        highlight_data = []
        for start, end, match_id in ranges:
            # 获取高亮文本的预览
            preview = plain_text[start:end][:50] if plain_text else ""
            highlight_data.append({
                'start': start,
                'end': end,
                'matchId': match_id,
                'preview': preview
            })

        # 添加高亮数据属性
        highlight_json = json.dumps(highlight_data, ensure_ascii=False)

        # 在容器上添加数据属性
        if 'class="docx-content"' in html_content:
            html_content = html_content.replace(
                'class="docx-content"',
                f'class="docx-content" data-highlights=\'{highlight_json}\''
            )

        return html_content

    def _render_html_page(
        self,
        primary_doc: str,
        source_doc: str,
        stats: str,
        match_cards: str,
        left_html: str,
        right_html: str,
        summary: dict
    ) -> str:
        """渲染完整HTML页面"""
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
    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 280px 1fr; gap: 12px; padding: 12px; }}
    .sidebar {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; overflow: auto; }}
    .content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; }}
    .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; display: flex; flex-direction: column; min-height: 0; }}
    .panel-header {{ padding: 12px 14px; border-bottom: 1px solid #e5e7eb; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; background: #f8fafc; }}
    .panel-body {{ padding: 16px; overflow: auto; scroll-behavior: smooth; }}
    .nav-title {{ font-weight: 700; margin-bottom: 10px; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 10px; margin-bottom: 8px; cursor: pointer; }}
    .nav-item:hover {{ border-color: #fca5a5; background: #fff5f5; }}
    .nav-item.active {{ border-color: #ef4444; background: #fef2f2; }}
    .nav-item small {{ display: block; color: #6b7280; margin-top: 4px; font-size: 11px; }}
    .empty {{ color: #9ca3af; font-size: 13px; padding: 20px; text-align: center; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; width: 100%; }}
    .stat-card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 4px; font-size: 20px; font-weight: 700; color: #0f172a; }}

    /* DOCX内容样式 */
    .docx-content {{ line-height: 1.8; font-size: 14px; }}
    .docx-content h1, .docx-content h2, .docx-content h3, .docx-content h4 {{
      margin: 16px 0 12px;
      font-weight: 700;
      color: #1f2937;
    }}
    .docx-content h1 {{ font-size: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
    .docx-content h2 {{ font-size: 18px; }}
    .docx-content h3 {{ font-size: 16px; }}
    .docx-content p {{ margin: 8px 0; }}
    .docx-content table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 13px;
    }}
    .docx-content td, .docx-content th {{
      border: 1px solid #d1d5db;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    .docx-content tr:nth-child(even) {{ background: #f9fafb; }}
    .docx-content tr:hover {{ background: #f3f4f6; }}

    /* 高亮样式 */
    .hit {{
      background: rgba(239, 68, 68, .20);
      color: #991b1b;
      border-radius: 3px;
      padding: 1px 2px;
      cursor: pointer;
      transition: all .15s ease;
      box-decoration-break: clone;
    }}
    .hit:hover {{
      background: rgba(239, 68, 68, .35);
    }}
    .hit.active {{
      background: rgba(220, 38, 38, .45);
      box-shadow: 0 0 0 2px rgba(220,38,38,.20);
    }}
    .hit.template {{
      background: rgba(245, 158, 11, .20);
      color: #92400e;
    }}

    /* 行号显示 */
    .line-marker {{
      position: absolute;
      left: 0;
      color: #9ca3af;
      font-size: 11px;
      width: 30px;
      text-align: right;
      padding-right: 8px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="toolbar">
      <div>
        <div class="title">查重可视化报告</div>
        <div style="font-size: 13px; color: #6b7280; margin-top: 4px;">左侧主文档：{html.escape(primary_doc)} ｜ 右侧来源文档：{html.escape(source_doc)}</div>
        <div class="stats">{stats}</div>
      </div>
      <div class="meta">
        <div class="pill">有效重复段：{summary.get("total_effective_segments", 0)}</div>
        <div class="pill">模板段：{summary.get("total_template_segments", 0)}</div>
        <div class="pill">有效字符：{summary.get("total_effective_chars", 0)}</div>
      </div>
    </div>
    <div class="main">
      <aside class="sidebar">
        <div class="nav-title">重复片段导航</div>
        {match_cards or '<div class="empty">暂无有效重复片段</div>'}
      </aside>
      <section class="content">
        <div class="panel">
          <div class="panel-header"><span>Primary</span><span>{html.escape(primary_doc)}</span></div>
          <div id="primary-panel" class="panel-body">{left_html}</div>
        </div>
        <div class="panel">
          <div class="panel-header"><span>Source</span><span>{html.escape(source_doc)}</span></div>
          <div id="source-panel" class="panel-body">{right_html}</div>
        </div>
      </section>
    </div>
  </div>
  <script>
    // 高亮功能
    (function() {{
      // 获取所有高亮数据
      const panels = document.querySelectorAll('.panel-body');
      const highlightMap = new Map();

      // 处理每个面板的高亮
      panels.forEach(panel => {{
        const content = panel.querySelector('.docx-content');
        if (!content) return;

        const highlightsData = content.dataset.highlights;
        if (!highlightsData) return;

        try {{
          const highlights = JSON.parse(highlightsData);
          const plainText = content.innerText;

          // 为每个高亮范围创建标记
          highlights.forEach(hl => {{
            if (!highlightMap.has(hl.matchId)) {{
              highlightMap.set(hl.matchId, []);
            }}
            highlightMap.get(hl.matchId).push({{
              panel: panel.id,
              start: hl.start,
              end: hl.end,
              preview: hl.preview
            }});
          }});

          // 应用高亮（简化版：使用文本搜索）
          applyHighlights(content, highlights);
        }} catch (e) {{
          console.error('Failed to parse highlights:', e);
        }}
      }});

      function applyHighlights(container, highlights) {{
        // 获取纯文本
        const text = container.innerText;
        const html = container.innerHTML;

        // 按位置倒序排序，避免替换时位置偏移
        const sorted = highlights.slice().sort((a, b) => b.start - a.start);

        let result = html;
        const processedRanges = new Set();

        sorted.forEach(hl => {{
          const rangeKey = `${{hl.start}}-${{hl.end}}`;
          if (processedRanges.has(rangeKey)) return;
          processedRanges.add(rangeKey);

          // 获取要高亮的文本
          const highlightText = text.substring(hl.start, hl.end);
          if (!highlightText) return;

          // 转义特殊字符用于正则
          const escaped = highlightText.replace(/[.*+?^${{}}()|[\]\\]/g, '\\$&');

          // 创建高亮span
          const side = container.id === 'primary-panel' ? 'primary' : 'source';
          const highlightSpan = `<span class="hit" data-side="${{side}}" data-match-id="${{hl.matchId}}">${{highlightText}}</span>`;

          // 替换（只替换第一个匹配）
          const regex = new RegExp(escaped, 'g');
          let matchCount = 0;
          result = result.replace(regex, (match) => {{
            matchCount++;
            // 只替换第一个未在标签内的匹配
            if (matchCount === 1) {{
              return highlightSpan;
            }}
            return match;
          }});
        }});

        container.innerHTML = result;
      }}

      // 导航点击事件
      window.activateMatch = function(matchId) {{
        // 移除所有active
        document.querySelectorAll('.hit.active').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-item.active').forEach(el => el.classList.remove('active'));

        // 添加active到当前
        const targets = document.querySelectorAll(`[data-match-id="${{matchId}}"]`);
        targets.forEach(el => el.classList.add('active'));

        // 高亮导航项
        const navItem = document.querySelector(`.nav-item[data-match-id="${{matchId}}"]`);
        if (navItem) navItem.classList.add('active');

        // 滚动到视图
        const primary = document.querySelector(`.hit[data-side="primary"][data-match-id="${{matchId}}"]`);
        const source = document.querySelector(`.hit[data-side="source"][data-match-id="${{matchId}}"]`);

        if (primary) primary.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        if (source) setTimeout(() => source.scrollIntoView({{ behavior: 'smooth', block: 'center' }}), 100);
      }};

      // 绑定点击事件
      document.querySelectorAll('.nav-item').forEach(el => {{
        el.addEventListener('click', () => window.activateMatch(el.dataset.matchId));
      }});

      // 委托事件处理高亮点击
      document.querySelectorAll('.panel-body').forEach(panel => {{
        panel.addEventListener('click', (e) => {{
          const hit = e.target.closest('.hit');
          if (hit) {{
            window.activateMatch(hit.dataset.matchId);
          }}
        }});
      }});
    }})();
  </script>
</body>
</html>
"""

    def _build_match_nav(self, segments: List[dict]) -> str:
        """构建导航卡片"""
        nav_parts: List[str] = []

        for idx, segment in enumerate(segments, start=1):
            match_id = f"m{idx:03d}"
            source = (segment.get("sources") or [{}])[0]
            similarity = segment.get("similarity_score", 0)
            primary_line = segment.get("primary_line", 0)
            source_line = source.get("line", 0)
            is_template = segment.get("is_template", False)
            type_label = "模板" if is_template else "重复"

            nav_parts.append(
                f'<button class="nav-item" data-match-id="{match_id}">'
                f'#{idx} <span style="color: #ef4444; font-size: 11px;">[{type_label}]</span>'
                f'<small>Primary L{primary_line} → Source L{source_line} ｜ 相似度 {similarity:.2f}</small>'
                f'</button>'
            )

        return "".join(nav_parts)

    def _pick_source_doc(self, duplicate_segments: List[dict], template_segments: List[dict]) -> str:
        """选择来源文档"""
        for pool in (duplicate_segments, template_segments):
            for segment in pool:
                sources = segment.get("sources") or []
                if sources and sources[0].get("doc"):
                    return sources[0]["doc"]
        return "来源文档"

    def _build_statistics(
        self,
        summary: dict,
        primary_text: str,
        duplicate_segments: List[dict],
        template_segments: List[dict]
    ) -> str:
        """构建统计卡片"""
        total_chars = len(primary_text)
        effective_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in duplicate_segments
        ])
        template_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in template_segments
        ])
        total_duplicate_chars = self._union_length([
            (seg.get("primary_start", 0), seg.get("primary_end", 0))
            for seg in duplicate_segments + template_segments
        ])

        total_rate = self._ratio(total_duplicate_chars, total_chars)
        effective_rate = self._ratio(effective_chars, total_chars)
        template_rate = self._ratio(template_chars, total_chars)

        cards = [
            ("总重复率", total_rate),
            ("有效重复率", effective_rate),
            ("模板重复率", template_rate),
            ("总字数", f"{total_chars:,}"),
            ("重复字数", f"{total_duplicate_chars:,}"),
            ("有效重复字数", f"{effective_chars:,}"),
        ]
        return "".join(
            f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>'
            for label, value in cards
        )

    def _normalize_ranges(self, ranges: List[Tuple[int, int, str]]) -> List[Tuple[int, int, str]]:
        """归一化范围，处理重叠"""
        normalized: List[Tuple[int, int, str]] = []
        last_end = -1
        for start, end, match_id in ranges:
            if start < last_end:
                start = last_end
            if end <= start:
                continue
            normalized.append((start, end, match_id))
            last_end = end
        return normalized

    def _union_length(self, ranges: List[Tuple[int, int]]) -> int:
        """计算并集长度"""
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

    def _ratio(self, numerator: int, denominator: int) -> str:
        """计算百分比"""
        if denominator <= 0:
            return "0.00%"
        return f"{(numerator / denominator) * 100:.2f}%"
