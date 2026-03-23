"""使用mammoth的DOCX转HTML转换器

mammoth是一个成熟的docx转html库，能很好地保留文档格式。
"""
from __future__ import annotations

import mammoth
from pathlib import Path
from typing import Optional, Dict, Any
import re


def convert_docx_to_html_mammoth(docx_path: Path | str) -> tuple[str, Dict[str, Any]]:
    """使用mammoth将DOCX转换为HTML
    
    Args:
        docx_path: DOCX文件路径
        
    Returns:
        (html_content, metadata)
    """
    docx_path = Path(docx_path)
    
    # 读取docx文件
    with open(docx_path, "rb") as docx_file:
        # 使用mammoth转换
        result = mammoth.convert_to_html(
            docx_file,
            convert_image=mammoth.images.data_uri,
            ignore_empty_paragraphs=True,
        )
    
    html_content = result.value
    
    # 后处理HTML，添加样式
    html_content = _post_process_html(html_content)
    
    # 收集元数据
    metadata = {
        "messages": result.messages,
        "file_name": docx_path.name,
    }
    
    return html_content, metadata


def _post_process_html(html: str) -> str:
    """对mammoth生成的HTML进行后处理"""
    
    # 添加CSS类到表格
    html = re.sub(
        r'<table',
        '<table class="docx-table"',
        html
    )
    
    # 添加CSS类到段落
    html = re.sub(
        r'<p>',
        '<p class="docx-paragraph">',
        html
    )
    
    # 添加CSS类到标题
    for i in range(1, 7):
        html = re.sub(
            rf'<h{i}',
            f'<h{i} class="docx-heading docx-h{i}"',
            html
        )
    
    # 添加CSS类到列表
    html = re.sub(
        r'<ul',
        '<ul class="docx-list docx-ul"',
        html
    )
    html = re.sub(
        r'<ol',
        '<ol class="docx-list docx-ol"',
        html
    )
    
    # 添加CSS类到图片
    html = re.sub(
        r'<img',
        '<img class="docx-image"',
        html
    )
    
    # 包裹在容器中
    html = f'<div class="docx-content">\n{html}\n</div>'
    
    return html


def get_mammoth_styles() -> str:
    """获取mammoth转换后的文档样式"""
    return """
    /* mammoth转换的DOCX内容样式 */
    .docx-content {
        line-height: 1.6;
        font-size: 14px;
        color: #333;
    }
    
    .docx-content p {
        margin: 0.5em 0;
    }
    
    .docx-content h1, .docx-content h2, .docx-content h3,
    .docx-content h4, .docx-content h5, .docx-content h6 {
        margin: 1em 0 0.5em;
        font-weight: bold;
        color: #1a1a1a;
    }
    
    .docx-content h1 { font-size: 1.5em; }
    .docx-content h2 { font-size: 1.3em; }
    .docx-content h3 { font-size: 1.15em; }
    
    .docx-content table {
        width: 100%;
        border-collapse: collapse;
        margin: 1em 0;
    }
    
    .docx-content table td,
    .docx-content table th {
        border: 1px solid #ddd;
        padding: 8px;
        text-align: left;
    }
    
    .docx-content table th {
        background: #f5f5f5;
        font-weight: bold;
    }
    
    .docx-content ul, .docx-content ol {
        margin: 0.5em 0;
        padding-left: 2em;
    }
    
    .docx-content li {
        margin: 0.25em 0;
    }
    
    .docx-content img {
        max-width: 100%;
        height: auto;
    }
    
    .docx-content strong {
        font-weight: bold;
    }
    
    .docx-content em {
        font-style: italic;
    }
    
    /* 高亮样式 */
    .docx-content .hit {
        background: rgba(239, 68, 68, 0.25);
        color: #991b1b;
        border-radius: 2px;
        padding: 1px 2px;
        cursor: pointer;
        transition: background 0.2s;
    }
    
    .docx-content .hit:hover {
        background: rgba(239, 68, 68, 0.4);
    }
    
    .docx-content .hit.active {
        background: rgba(220, 38, 38, 0.5);
        box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.2);
    }
    """


if __name__ == "__main__":
    # 测试转换
    import sys
    
    if len(sys.argv) > 1:
        docx_path = Path(sys.argv[1])
        html, meta = convert_docx_to_html_mammoth(docx_path)
        
        output_path = docx_path.with_suffix('.html')
        output_path.write_text(html, encoding='utf-8')
        
        print(f"Converted: {docx_path} -> {output_path}")
        print(f"Messages: {meta['messages']}")
    else:
        print("Usage: python mammoth_converter.py <docx_file>")
