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
        else:
            left_html = self._build_fallback_content(data, "primary")

        if source_docx_path and Path(source_docx_path).exists():
            right_html, _ = convert_docx_to_html_mammoth(source_docx_path)
        else:
            right_html = self._build_fallback_content(data, "source")
        
        # 同时处理两侧高亮，确保每个片段都有两侧匹配
        left_html, right_html = self._apply_highlights_both_sides(
            left_html, right_html, data
        )
        
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

    def _apply_highlights_both_sides(
        self,
        left_html: str,
        right_html: str,
        data: Dict
    ) -> Tuple[str, str]:
        """同时在两侧HTML上应用查重高亮
        
        关键策略：每个片段必须在两侧都找到匹配才会创建高亮。
        这样可以确保每个match-id都有两个高亮（左和右），
        从而保证导航跳转时两侧都能正常工作。
        """
        segments = data.get("duplicate_segments", [])
        if not segments:
            return left_html, right_html
        
        print(f"[DEBUG] _apply_highlights_both_sides: 共 {len(segments)} 个片段")

        left_result = left_html
        right_result = right_html
        
        # 按文本长度排序（长的先处理，避免短文本干扰）
        sorted_segments = sorted(
            enumerate(segments),
            key=lambda x: len(x[1].get("primary_text", "")),
            reverse=True
        )
        
        matched_count = 0
        for seg_idx, segment in sorted_segments:
            match_id = f"m{seg_idx+1:03d}"
            is_template = segment.get("is_template", False)
            
            # 获取两侧文本
            left_text = segment.get("primary_text", "")
            sources = segment.get("sources", [])
            right_text = sources[0].get("text", "") if sources else ""
            
            if not left_text or not right_text or len(left_text) < 3 or len(right_text) < 3:
                print(f"[DEBUG] {match_id}: 跳过 - 文本太短或为空")
                continue
            
            # 清理文本 - 去除表格行标记、管道符和多余空格
            import re
            left_text = re.sub(r'\[表格行\d+\]', '', left_text)
            right_text = re.sub(r'\[表格行\d+\]', '', right_text)
            # 去除表格中的管道符（HTML转换后表格单元格分隔符会消失）
            left_text = re.sub(r'\s*\|\s*', ' ', left_text)
            right_text = re.sub(r'\s*\|\s*', ' ', right_text)
            left_clean = ' '.join(left_text.split())
            right_clean = ' '.join(right_text.split())
            
            # 尝试在两侧都找到匹配位置
            left_match = self._find_match_in_html(left_result, left_clean)
            right_match = self._find_match_in_html(right_result, right_clean)
            
            if not left_match:
                print(f"[DEBUG] {match_id}: 左侧未找到匹配 (文本前30字: {left_clean[:30]}...)")
            if not right_match:
                print(f"[DEBUG] {match_id}: 右侧未找到匹配 (文本前30字: {right_clean[:30]}...)")
            
            # 关键：只有两侧都找到匹配时才创建高亮
            if left_match and right_match:
                matched_count += 1
                left_start, left_end = left_match
                right_start, right_end = right_match
                
                # 应用左侧高亮
                template_class = " template" if is_template else ""
                left_highlight = f'<span class="hit{template_class}" data-match-id="{match_id}" data-side="primary">{left_result[left_start:left_end]}</span>'
                left_result = left_result[:left_start] + left_highlight + left_result[left_end:]
                
                # 应用右侧高亮
                right_highlight = f'<span class="hit{template_class}" data-match-id="{match_id}" data-side="source">{right_result[right_start:right_end]}</span>'
                right_result = right_result[:right_start] + right_highlight + right_result[right_end:]
        
        print(f"[DEBUG] _apply_highlights_both_sides: 成功匹配 {matched_count} 个片段")
        return left_result, right_result
    
    def _find_match_in_html(self, html_content: str, search_text: str) -> Optional[Tuple[int, int]]:
        """在HTML内容中查找文本匹配位置
        
        返回: (start_pos, end_pos) 或 None（如果未找到）
        """
        if not search_text or len(search_text) < 3:
            return None
        
        # 提取纯文本
        plain_text = re.sub(r'<[^>]+>', ' ', html_content)
        plain_text = ' '.join(plain_text.split())
        
        # 首先尝试匹配完整文本
        clean_search = ' '.join(search_text.split())
        match_pos = plain_text.find(clean_search)
        
        if match_pos != -1:
            # 完整匹配，直接映射到HTML
            return self._map_plain_to_html_exact(html_content, plain_text, match_pos, len(clean_search))
        
        # 尝试不同长度的搜索文本（从长到短）
        for search_len in [50, 40, 30, 25, 20, 15, 10, 8, 5]:
            if search_len > len(search_text):
                continue
            if search_len < 5:
                continue
            
            # 尝试从不同偏移位置开始匹配
            for offset in [0, 10, 15, 20, 25, 30]:
                if offset + search_len > len(search_text):
                    continue
                search_str = search_text[offset:offset+search_len]
                match_pos = plain_text.find(search_str)
                
                if match_pos != -1:
                    # 找到锚点，映射回HTML位置
                    # 使用实际找到的锚点长度
                    return self._map_plain_to_html_exact(html_content, plain_text, match_pos, search_len)
        
        return None
    
    def _map_plain_to_html_exact(
        self,
        html_content: str,
        plain_text: str,
        match_start_plain: int,
        match_length: int
    ) -> Optional[Tuple[int, int]]:
        """将纯文本位置精确映射回HTML位置
        
        Args:
            html_content: HTML内容
            plain_text: 纯文本（已去除HTML标签）
            match_start_plain: 匹配在纯文本中的起始位置
            match_length: 匹配的长度
        """
        # 找到HTML中的起始位置
        html_pos = 0
        plain_pos = 0
        match_start_html = -1
        
        while html_pos < len(html_content) and plain_pos <= match_start_plain:
            if html_content[html_pos] == '<':
                # 跳过标签
                while html_pos < len(html_content) and html_content[html_pos] != '>':
                    html_pos += 1
                html_pos += 1
            else:
                if plain_pos == match_start_plain:
                    match_start_html = html_pos
                    break
                plain_pos += 1
                html_pos += 1
        
        if match_start_html == -1:
            return None
        
        # 找到结束位置（匹配match_length个字符）
        match_end_html = match_start_html
        chars_matched = 0
        
        while chars_matched < match_length and match_end_html < len(html_content):
            if html_content[match_end_html] == '<':
                # 跳过标签
                while match_end_html < len(html_content) and html_content[match_end_html] != '>':
                    match_end_html += 1
                match_end_html += 1
            else:
                chars_matched += 1
                match_end_html += 1
        
        return (match_start_html, match_end_html)

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
        
        # 计算总字数
        total_chars = sum(text_lengths.values()) if text_lengths else 0
        if total_chars == 0:
            docs = data.get("documents", {})
            if docs:
                total_chars = sum(len(text) for text in docs.values() if isinstance(text, str))
        
        # 有效重复字符数（来自summary或计算）
        effective_chars = summary.get("total_effective_chars", 0)
        if effective_chars == 0:
            # 从 duplicate_segments 计算（排除模板片段）
            effective_chars = sum(
                s.get("char_count", 0) 
                for s in segments 
                if not s.get("is_template", False)
            )
        
        # 模板重复字符数
        template_chars = summary.get("total_template_chars", 0)
        if template_chars == 0 and template_segments:
            template_chars = sum(s.get("char_count", 0) for s in template_segments)
        
        # 总重复字符数
        duplicate_chars = effective_chars + template_chars
        
        # 计算重复率
        total_rate = (duplicate_chars / total_chars * 100) if total_chars > 0 else 0
        effective_rate = (effective_chars / total_chars * 100) if total_chars > 0 else 0
        template_rate = (template_chars / total_chars * 100) if total_chars > 0 else 0

        return f"""<div class="stat-card"><div class="stat-label">总重复率</div><div class="stat-value">{total_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">有效重复率</div><div class="stat-value">{effective_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">模板重复率</div><div class="stat-value">{template_rate:.2f}%</div></div><div class="stat-card"><div class="stat-label">总字数</div><div class="stat-value">{total_chars:,}</div></div><div class="stat-card"><div class="stat-label">重复字数</div><div class="stat-value">{duplicate_chars:,}</div></div><div class="stat-card"><div class="stat-label">有效重复字数</div><div class="stat-value">{effective_chars:,}</div></div>"""

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
          if (!highlightMap.has(matchId)) {{
            highlightMap.set(matchId, []);
          }}
          highlightMap.get(matchId).push(el);
        }});
        console.log('Initialized highlights:', highlightMap.size);
      }}
      
      const activateMatch = (matchId) => {{
        console.log('Activating match:', matchId);
        
        // 清除所有激活状态
        document.querySelectorAll('.hit.active').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-item.active').forEach(el => el.classList.remove('active'));
        
        // 激活当前匹配的高亮元素
        const hits = highlightMap.get(matchId) || [];
        console.log('Found hits:', hits.length);
        hits.forEach(el => el.classList.add('active'));
        
        // 激活导航项
        const navItem = document.querySelector(`.nav-item[data-match-id="${{matchId}}"]`);
        if (navItem) navItem.classList.add('active');
        
        // 滚动到第一个匹配
        if (hits.length > 0) {{
          const firstHit = hits[0];
          firstHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          
          // 同时滚动另一侧的对应元素
          if (hits.length > 1) {{
            const secondHit = hits[1];
            const otherPanel = secondHit.closest('.panel-body');
            if (otherPanel) {{
              secondHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
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
