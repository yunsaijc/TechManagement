"""DOCX 转 HTML 转换器

将 Word 文档转换为保留格式的 HTML，用于查重报告展示。
"""
from typing import List, Dict, Optional, Tuple, Generator, Union
import io
import re
import html
from dataclasses import dataclass, field

from docx import Document
from docx.document import Document as DocDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from lxml import etree


@dataclass
class TextPosition:
    """文本位置映射"""
    char_start: int  # 在纯文本中的起始位置
    char_end: int    # 在纯文本中的结束位置
    element_id: str  # HTML元素ID
    is_table: bool = False  # 是否为表格内容


@dataclass
class HTMLDocument:
    """HTML文档结果"""
    html: str           # HTML内容
    plain_text: str     # 纯文本（用于查重匹配）
    positions: List[TextPosition]  # 位置映射表


class DOCXtoHTMLConverter:
    """Word转HTML转换器，保留原始格式"""

    # 命名空间
    NS = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    }

    def __init__(self):
        self.char_count = 0
        self.positions: List[TextPosition] = []
        self.element_counter = 0

    def convert(self, file_data: bytes) -> HTMLDocument:
        """将DOCX转换为HTML

        Args:
            file_data: DOCX文件数据

        Returns:
            HTMLDocument对象，包含HTML、纯文本和位置映射
        """
        self.char_count = 0
        self.positions = []
        self.element_counter = 0

        doc = Document(io.BytesIO(file_data))

        html_parts = []
        html_parts.append('<div class="docx-content">')

        plain_text_parts = []

        # 遍历所有块级元素（保持原始顺序）
        for item in self._iter_block_items(doc):
            if isinstance(item, Paragraph):
                para_html, para_text = self._convert_paragraph(item)
                if para_html:
                    html_parts.append(para_html)
                if para_text:
                    plain_text_parts.append(para_text)

            elif isinstance(item, Table):
                table_html, table_text = self._convert_table(item)
                if table_html:
                    html_parts.append(table_html)
                if table_text:
                    plain_text_parts.append(table_text)

        html_parts.append('</div>')

        return HTMLDocument(
            html='\n'.join(html_parts),
            plain_text='\n'.join(plain_text_parts),
            positions=self.positions
        )

    def _iter_block_items(self, parent: DocDocument) -> Generator[Union[Paragraph, Table], None, None]:
        """按文档顺序遍历段落和表格"""
        parent_elm = parent.element.body
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _convert_paragraph(self, para: Paragraph) -> Tuple[str, str]:
        """转换段落为HTML

        Returns:
            (html, plain_text)
        """
        text = para.text or ''
        if not text.strip():
            return '', ''

        self.element_counter += 1
        element_id = f'p-{self.element_counter}'

        # 记录位置映射
        char_start = self.char_count
        char_end = self.char_count + len(text)
        self.positions.append(TextPosition(
            char_start=char_start,
            char_end=char_end,
            element_id=element_id,
            is_table=False
        ))
        self.char_count = char_end + 1  # +1 for newline

        # 确定标签和样式
        style_name = para.style.name if para.style else 'Normal'
        tag, css_class = self._get_paragraph_tag(style_name)

        # 获取对齐方式
        align_style = ''
        if para.alignment == WD_ALIGN_PARAGRAPH.CENTER:
            align_style = 'text-align: center;'
        elif para.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
            align_style = 'text-align: right;'

        # 转换runs（保留部分格式）
        runs_html = self._convert_runs(para, element_id)

        # 构建HTML
        style_attr = f' style="{align_style}"' if align_style else ''
        html_content = f'<{tag} id="{element_id}" class="{css_class}"{style_attr}>{runs_html}</{tag}>'

        return html_content, text

    def _get_paragraph_tag(self, style_name: str) -> Tuple[str, str]:
        """根据样式名称确定HTML标签"""
        style_lower = style_name.lower()

        if '标题 1' in style_name or 'heading 1' in style_lower:
            return 'h1', 'docx-h1'
        elif '标题 2' in style_name or 'heading 2' in style_lower:
            return 'h2', 'docx-h2'
        elif '标题 3' in style_name or 'heading 3' in style_lower:
            return 'h3', 'docx-h3'
        elif '标题' in style_name or 'heading' in style_lower:
            return 'h4', 'docx-h4'
        elif '表格' in style_name:
            return 'p', 'docx-table-caption'
        else:
            return 'p', 'docx-paragraph'

    def _convert_runs(self, para: Paragraph, parent_id: str) -> str:
        """转换段落中的runs，保留格式信息"""
        parts = []

        for run in para.runs:
            text = run.text
            if not text:
                continue

            # 转义HTML
            escaped = html.escape(text)

            # 应用格式
            if run.bold and run.italic:
                escaped = f'<strong><em>{escaped}</em></strong>'
            elif run.bold:
                escaped = f'<strong>{escaped}</strong>'
            elif run.italic:
                escaped = f'<em>{escaped}</em>'

            # 下划线
            if run.underline:
                escaped = f'<u>{escaped}</u>'

            # 颜色
            if run.font.color and run.font.color.rgb:
                color = str(run.font.color.rgb)
                escaped = f'<span style="color: #{color};">{escaped}</span>'

            parts.append(escaped)

        return ''.join(parts) if parts else html.escape(para.text or '')

    def _convert_table(self, table: Table) -> Tuple[str, str]:
        """转换表格为HTML

        Returns:
            (html, plain_text)
        """
        self.element_counter += 1
        table_id = f'tbl-{self.element_counter}'

        rows_html = []
        plain_rows = []

        for row_idx, row in enumerate(table.rows):
            cells_html = []
            cell_texts = []

            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    cell_texts.append(cell_text)
                    # 简化处理：单元格内容直接转义
                    cell_html = html.escape(cell_text).replace('\n', '<br>')
                    cells_html.append(f'<td class="docx-td">{cell_html}</td>')

            if cells_html:
                rows_html.append(f'<tr class="docx-tr">{ "".join(cells_html) }</tr>')
                plain_rows.append(f"[表格行{row_idx + 1}] {' | '.join(cell_texts)}")

        if not rows_html:
            return '', ''

        # 记录位置映射（整个表格）
        table_text = '\n'.join(plain_rows)
        char_start = self.char_count
        char_end = self.char_count + len(table_text)
        self.positions.append(TextPosition(
            char_start=char_start,
            char_end=char_end,
            element_id=table_id,
            is_table=True
        ))
        self.char_count = char_end + 1

        html_content = f'''
<table id="{table_id}" class="docx-table" border="1" cellpadding="6" cellspacing="0">
  <tbody>{"".join(rows_html)}</tbody>
</table>
'''
        return html_content, table_text

    def apply_highlights(self, html_doc: HTMLDocument, segments: List[Dict], side: str = "primary") -> str:
        """在HTML上应用高亮标记

        Args:
            html_doc: HTML文档对象
            segments: 重复片段列表
            side: 'primary' 或 'source'

        Returns:
            带高亮标记的HTML
        """
        html_content = html_doc.html
        plain_text = html_doc.plain_text
        positions = html_doc.positions

        # 构建位置到元素的映射
        char_to_elements = self._build_char_mapping(positions)

        # 收集所有需要高亮的范围
        highlight_ranges = []
        for idx, segment in enumerate(segments, start=1):
            match_id = f"m{idx:03d}"

            if side == "primary":
                start = segment.get("primary_start", 0)
                end = segment.get("primary_end", 0)
            else:
                source = (segment.get("sources") or [{}])[0]
                start = source.get("start", 0)
                end = source.get("end", 0)

            if end > start:
                highlight_ranges.append((start, end, match_id))

        if not highlight_ranges:
            return html_content

        # 按位置排序
        highlight_ranges.sort(key=lambda x: x[0])

        # 由于直接修改HTML比较复杂，我们采用一种简化的方法：
        # 在纯文本上标记，然后重新构建HTML
        # 这里我们使用一个更简单的方法：包裹文本节点

        return self._apply_highlights_to_html(html_content, plain_text, highlight_ranges, positions)

    def _build_char_mapping(self, positions: List[TextPosition]) -> Dict[int, List[str]]:
        """构建字符位置到元素ID的映射"""
        mapping = {}
        for pos in positions:
            for char_idx in range(pos.char_start, pos.char_end + 1):
                if char_idx not in mapping:
                    mapping[char_idx] = []
                mapping[char_idx].append(pos.element_id)
        return mapping

    def _apply_highlights_to_html(
        self,
        html_content: str,
        plain_text: str,
        highlight_ranges: List[Tuple[int, int, str]],
        positions: List[TextPosition]
    ) -> str:
        """将高亮应用到HTML

        策略：找到包含高亮文本的段落/表格，在该元素内添加高亮标记
        """
        # 简化实现：为每个元素添加data属性标记其文本范围
        # 然后使用JavaScript在客户端进行高亮

        # 首先，为每个元素添加文本范围标记
        for pos in positions:
            # 找到元素并添加data属性
            old_tag = f'id="{pos.element_id}"'
            new_tag = f'id="{pos.element_id}" data-char-start="{pos.char_start}" data-char-end="{pos.char_end}"'
            html_content = html_content.replace(old_tag, new_tag, 1)

        # 添加高亮数据（供JavaScript使用）
        highlight_data = []
        for start, end, match_id in highlight_ranges:
            highlight_data.append({
                'start': start,
                'end': end,
                'matchId': match_id
            })

        # 将高亮数据嵌入HTML
        script = f'''
<script>
window.HIGHLIGHT_RANGES = {highlight_data};
</script>
'''
        # 在</body>前插入脚本
        if '</body>' in html_content:
            html_content = html_content.replace('</body>', script + '</body>')
        else:
            html_content += script

        return html_content


def convert_docx_to_html(file_path: str) -> HTMLDocument:
    """便捷函数：将DOCX文件转换为HTML

    Args:
        file_path: DOCX文件路径

    Returns:
        HTMLDocument对象
    """
    with open(file_path, 'rb') as f:
        file_data = f.read()

    converter = DOCXtoHTMLConverter()
    return converter.convert(file_data)
