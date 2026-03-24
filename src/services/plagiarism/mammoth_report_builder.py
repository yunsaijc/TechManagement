"""查重 HTML 报告生成器（使用mammoth保留Word格式版）

基于mammoth库将Word文档转换为HTML，保留原始格式，并叠加查重高亮。
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 导入mammoth转换器
from common.file_handler.mammoth_converter import (
    convert_docx_to_html_mammoth,
    get_mammoth_styles
)


class MammothPlagiarismReportBuilder:
    """基于mammoth的查重HTML报告生成器
    
    使用mammoth库将Word文档转换为HTML，保留原始格式，
    然后在HTML层上叠加查重高亮标记。
    """

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
            # 添加高亮（安全方式，不破坏表格结构）
            left_html = self._apply_highlights(left_html, data, "primary")
        else:
            left_html = self._build_fallback_content(data, "primary")

        if source_docx_path and Path(source_docx_path).exists():
            right_html, _ = convert_docx_to_html_mammoth(source_docx_path)
            # 添加高亮（安全方式，不破坏表格结构）
            right_html = self._apply_highlights(right_html, data, "source")
        else:
            right_html = self._build_fallback_content(data, "source")

        # 构建统计信息
        stats = self._build_statistics(data)

        # 构建匹配导航
        match_cards = self._build_match_nav(data)

        # 渲染完整页面
        html_page = self._render_html_page(
            primary_doc=primary_doc,
            source_doc=source_doc,
            stats=stats,
            match_cards=match_cards,
            left_html=left_html,
            right_html=right_html,
            summary=data.get("summary", {})
        )

        # 写入文件
        output_html_path.write_text(html_page, encoding="utf-8")
        return output_html_path

    def _apply_highlights(
        self,
        html_content: str,
        data: Dict,
        side: str
    ) -> str:
        """在HTML内容上应用查重高亮
        
        安全策略：只在文本节点内部添加高亮，绝不跨越HTML标签边界，
        确保表格等复杂结构不被破坏。
        """
        from html.parser import HTMLParser
        
        segments = data.get("duplicate_segments", [])
        if not segments:
            return html_content

        # 收集需要高亮的文本片段
        highlights = []
        for seg_idx, segment in enumerate(segments):
            match_id = f"m{seg_idx+1:03d}"
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
            
            # 清理文本用于匹配
            clean_text = ' '.join(text.split())
            highlights.append({
                'match_id': match_id,
                'text': clean_text,
                'is_template': is_template
            })
        
        if not highlights:
            return html_content
        
        # 按文本长度排序（长的先处理）
        highlights.sort(key=lambda x: len(x['text']), reverse=True)
        
        # 使用HTML解析器安全地处理
        return self._safe_highlight_in_text(html_content, highlights, side)
    
    def _safe_highlight_in_text(self, html_content: str, highlights: List[Dict], side: str) -> str:
        """安全地在HTML文本节点中添加高亮
        
        策略：
        1. 将HTML分割成标签和文本片段
        2. 在整个文档级别查找匹配（跨片段匹配）
        3. 标记需要高亮的文本片段范围
        4. 用span包裹匹配的文本，不破坏标签结构
        """
        # 解析HTML，分离标签和文本
        parts = []
        i = 0
        while i < len(html_content):
            if html_content[i] == '<':
                end = html_content.find('>', i)
                if end == -1:
                    parts.append(('text', html_content[i:]))
                    break
                parts.append(('tag', html_content[i:end+1]))
                i = end + 1
            else:
                end = html_content.find('<', i)
                if end == -1:
                    parts.append(('text', html_content[i:]))
                    break
                parts.append(('text', html_content[i:end]))
                i = end
        
        # 构建字符映射表：记录每个非空格字符来自哪个文本片段和位置
        char_map = []  # [(part_index, char_index, char), ...]
        text_parts_indices = []  # 记录哪些part索引是文本片段
        
        for part_idx, (part_type, content) in enumerate(parts):
            if part_type == 'text':
                text_parts_indices.append(part_idx)
                for char_idx, c in enumerate(content):
                    if not c.isspace():
                        char_map.append((part_idx, char_idx, c))
        
        if not char_map:
            return html_content
        
        # 查找所有匹配区间（在整个文档级别）
        all_matches = []  # [(start_char_idx, end_char_idx, match_id, is_template), ...]
        
        for hl in highlights:
            target = hl['text']
            match_id = hl['match_id']
            is_template = hl['is_template']
            
            if not target or len(target) < 5:
                continue
            
            # 提取目标文本的字符序列
            target_chars = [c for c in target if not c.isspace()]
            if len(target_chars) < 5:
                continue
            
            # 在整个文档中查找匹配
            doc_chars = [c for (_, _, c) in char_map]
            
            # 滑动窗口查找最佳匹配
            best_match_len = 0
            best_start = -1
            
            for start in range(len(doc_chars) - len(target_chars) + 1):
                match_len = 0
                for j, tc in enumerate(target_chars):
                    if start + j < len(doc_chars) and doc_chars[start + j] == tc:
                        match_len += 1
                    else:
                        break
                
                # 要求匹配率至少40%（降低阈值以处理相似但不完全相同的文本）
                if match_len >= len(target_chars) * 0.4 and match_len > best_match_len:
                    best_match_len = match_len
                    best_start = start
            
            if best_start >= 0:
                # 记录匹配区间
                end_char_idx = best_start + best_match_len - 1
                all_matches.append((best_start, end_char_idx, match_id, is_template))
        
        if not all_matches:
            return html_content
        
        # 合并重叠的匹配
        all_matches.sort(key=lambda x: x[0])
        merged_matches = []
        for match in all_matches:
            if not merged_matches:
                merged_matches.append(match)
            else:
                last = merged_matches[-1]
                if match[0] <= last[1]:  # 重叠
                    # 扩展上一个匹配的结束位置
                    merged_matches[-1] = (last[0], max(last[1], match[1]), last[2], last[3])
                else:
                    merged_matches.append(match)
        
        # 将字符级别的匹配转换为文本片段级别的标记
        # 对于每个文本片段，记录需要高亮的区间
        part_highlights = {}  # {part_idx: [(start, end, match_id, is_template), ...]}
        
        for match_start, match_end, match_id, is_template in merged_matches:
            # 找到对应的文本片段
            start_part_idx = char_map[match_start][0]
            end_part_idx = char_map[match_end][0]
            
            if start_part_idx == end_part_idx:
                # 匹配在同一个文本片段内
                start_in_part = char_map[match_start][1]
                end_in_part = char_map[match_end][1]
                if start_part_idx not in part_highlights:
                    part_highlights[start_part_idx] = []
                part_highlights[start_part_idx].append((start_in_part, end_in_part + 1, match_id, is_template))
            else:
                # 匹配跨越多个文本片段
                # 第一个片段：从匹配开始到片段结束
                start_in_part = char_map[match_start][1]
                part_content = parts[start_part_idx][1]
                if start_part_idx not in part_highlights:
                    part_highlights[start_part_idx] = []
                part_highlights[start_part_idx].append((start_in_part, len(part_content), match_id, is_template))
                
                # 中间片段：整个片段
                for mid_part_idx in range(start_part_idx + 1, end_part_idx):
                    if mid_part_idx not in part_highlights:
                        part_highlights[mid_part_idx] = []
                    mid_content = parts[mid_part_idx][1]
                    part_highlights[mid_part_idx].append((0, len(mid_content), match_id, is_template))
                
                # 最后一个片段：从片段开始到匹配结束
                end_in_part = char_map[match_end][1]
                if end_part_idx not in part_highlights:
                    part_highlights[end_part_idx] = []
                part_highlights[end_part_idx].append((0, end_in_part + 1, match_id, is_template))
        
        # 应用高亮到文本片段
        result_parts = []
        for part_idx, (part_type, content) in enumerate(parts):
            if part_type == 'tag':
                result_parts.append(content)
            elif part_idx in part_highlights:
                # 对这个文本片段应用高亮
                highlighted = self._apply_highlight_to_part(content, part_highlights[part_idx], side)
                result_parts.append(highlighted)
            else:
                result_parts.append(content)
        
        return ''.join(result_parts)
    
    def _apply_highlight_to_part(self, text: str, highlights: List[Tuple], side: str) -> str:
        """对单个文本片段应用高亮标记
        
        highlights: [(start, end, match_id, is_template), ...]
        """
        if not highlights:
            return text
        
        # 按位置排序
        highlights.sort(key=lambda x: x[0])
        
        # 合并重叠区间
        merged = []
        for start, end, match_id, is_template in highlights:
            if not merged:
                merged.append((start, end, match_id, is_template))
            else:
                last_start, last_end, last_id, last_template = merged[-1]
                if start <= last_end:
                    # 重叠，合并
                    merged[-1] = (last_start, max(last_end, end), last_id, last_template)
                else:
                    merged.append((start, end, match_id, is_template))
        
        # 构建结果
        result = []
        last_end = 0
        for start, end, match_id, is_template in merged:
            # 添加高亮前的文本
            if start > last_end:
                result.append(text[last_end:start])
            
            # 添加高亮文本
            matched_text = text[start:end]
            template_class = " template" if is_template else ""
            highlight_html = f'<span class="hit{template_class}" data-match-id="{match_id}" data-side="{side}">{matched_text}</span>'
            result.append(highlight_html)
            
            last_end = end
        
        # 添加剩余文本
        if last_end < len(text):
            result.append(text[last_end:])
        
        return ''.join(result)

    def _build_fallback_content(self, data: Dict, side: str) -> str:
        """构建降级内容（当没有DOCX文件时使用）"""
        documents = data.get("documents", {})
        primary_doc = data.get("primary_doc", "")
        
        if side == "primary":
            text = documents.get(primary_doc, "")
            title = primary_doc or "主文档"
        else:
            # 找到来源文档（非主文档）
            source_doc = ""
            for doc_name in documents.keys():
                if doc_name != primary_doc:
                    source_doc = doc_name
                    break
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
        
        # 从 summary 获取数据
        total_effective_segments = summary.get("total_effective_segments", 0)
        total_template_segments = summary.get("total_template_segments", 0)
        total_effective_chars = summary.get("total_effective_chars", 0)
        total_template_chars = summary.get("total_template_chars", 0)
        
        # 计算重复率
        documents = data.get("documents", {})
        primary_doc = data.get("primary_doc", "")
        primary_text = documents.get(primary_doc, "") if documents else ""
        total_chars = len(primary_text)
        
        total_duplicate_chars = total_effective_chars + total_template_chars
        total_rate = (total_duplicate_chars / total_chars * 100) if total_chars > 0 else 0
        effective_rate = (total_effective_chars / total_chars * 100) if total_chars > 0 else 0
        template_rate = (total_template_chars / total_chars * 100) if total_chars > 0 else 0

        return f"""<div class="stat-card"><div class="stat-label">总重复率</div><div class="stat-value">{total_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">有效重复率</div><div class="stat-value">{effective_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">模板重复率</div><div class="stat-value">{template_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">总字数</div><div class="stat-value">{total_chars:,}</div></div><div class="stat-card"><div class="stat-label">重复字数</div><div class="stat-value">{total_duplicate_chars:,}</div></div><div class="stat-card"><div class="stat-label">有效重复字数</div><div class="stat-value">{total_effective_chars:,}</div></div>"""

    def _build_match_nav(self, data: Dict) -> str:
        """构建匹配片段导航"""
        segments = data.get("duplicate_segments", [])
        if not segments:
            return '<p class="empty">无重复片段</p>'

        cards = []
        for i, segment in enumerate(segments[:50], 1):  # 最多显示50个
            match_id = segment.get("match_id") or f"m{i:03d}"
            primary_text = segment.get("primary_text", "")[:60]
            is_template = segment.get("is_template", False)
            similarity = segment.get("similarity_score", segment.get("similarity", 1.0))
            
            sources = segment.get("sources", [])
            source_info = ""
            if sources:
                source_doc = sources[0].get("doc", "")
                source_text = sources[0].get("text", "")[:40]
                source_info = f"来源: {html.escape(source_doc)}"
            
            template_badge = '<span class="template-badge">模板</span>' if is_template else ''
            
            cards.append(f'''<button class="nav-item" data-match-id="{match_id}">
                <div class="nav-header">#{i} {template_badge}</div>
                <div class="nav-text">{html.escape(primary_text)}...</div>
                <small>相似度: {similarity:.2f} | {source_info}</small>
            </button>''')

        return "".join(cards)

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
          const side = el.dataset.side;
          if (!highlightMap.has(matchId)) {{
            highlightMap.set(matchId, {{}});
          }}
          highlightMap.get(matchId)[side] = el;
        }});
        console.log('Initialized highlights:', highlightMap.size);
      }}
      
      const activateMatch = (matchId) => {{
        console.log('Activating match:', matchId);
        
        // 清除所有激活状态
        document.querySelectorAll('.hit.active').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-item.active').forEach(el => el.classList.remove('active'));
        
        // 激活当前匹配的高亮元素
        const hits = highlightMap.get(matchId) || {{}};
        const primaryHit = hits['primary'];
        const sourceHit = hits['source'];
        
        console.log('Found hits - primary:', !!primaryHit, 'source:', !!sourceHit);
        
        if (primaryHit) primaryHit.classList.add('active');
        if (sourceHit) sourceHit.classList.add('active');
        
        // 激活导航项
        const navItem = document.querySelector(`.nav-item[data-match-id="${{matchId}}"]`);
        if (navItem) navItem.classList.add('active');
        
        // 同步滚动两侧面板
        const primaryPanel = document.getElementById('primary-panel');
        const sourcePanel = document.getElementById('source-panel');
        
        if (primaryHit && primaryPanel) {{
          const primaryRect = primaryHit.getBoundingClientRect();
          const panelRect = primaryPanel.getBoundingClientRect();
          const scrollTop = primaryPanel.scrollTop + primaryRect.top - panelRect.top - panelRect.height / 2 + primaryRect.height / 2;
          primaryPanel.scrollTo({{ top: scrollTop, behavior: 'smooth' }});
        }}
        
        if (sourceHit && sourcePanel) {{
          const sourceRect = sourceHit.getBoundingClientRect();
          const panelRect = sourcePanel.getBoundingClientRect();
          const scrollTop = sourcePanel.scrollTop + sourceRect.top - panelRect.top - panelRect.height / 2 + sourceRect.height / 2;
          sourcePanel.scrollTo({{ top: scrollTop, behavior: 'smooth' }});
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
