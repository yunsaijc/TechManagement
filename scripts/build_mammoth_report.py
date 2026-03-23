#!/usr/bin/env python3
"""生成使用mammoth的保留格式查重报告

使用mammoth库将Word文档转换为HTML，保留原始格式。
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.plagiarism.mammoth_report_builder import MammothPlagiarismReportBuilder


def main():
    # 路径配置
    debug_json = Path("debug_plagiarism/plagiarism_debug.json")
    output_html = Path("debug_plagiarism/plagiarism_report_mammoth.html")

    # 原始Word文档路径
    data_dir = Path("/home/tdkx/workspace/data/查重用例Word文档")
    
    # 从debug数据中获取文档路径
    import json
    data = json.loads(debug_json.read_text(encoding="utf-8"))

    primary_doc = data.get("primary_doc", "")
    source_doc = ""
    for segment in data.get("duplicate_segments", []):
        sources = segment.get("sources", [])
        if sources:
            source_doc = sources[0].get("doc", "")
            break

    # 查找原始docx文件
    primary_docx = None
    source_docx = None

    if primary_doc:
        for file in data_dir.iterdir():
            if file.is_file() and file.name == primary_doc:
                primary_docx = file
                break
    
    if source_doc:
        for file in data_dir.iterdir():
            if file.is_file() and file.name == source_doc:
                source_docx = file
                break

    print(f"[Report] Primary doc: {primary_doc}")
    print(f"[Report] Primary docx found: {primary_docx}")
    print(f"[Report] Source doc: {source_doc}")
    print(f"[Report] Source docx found: {source_docx}")

    # 生成报告
    builder = MammothPlagiarismReportBuilder()
    builder.build_from_debug_file(
        debug_json_path=debug_json,
        output_html_path=output_html,
        primary_docx_path=primary_docx,
        source_docx_path=source_docx
    )

    print(f"[Report] Mammoth HTML report generated: {output_html.absolute()}")
    print(f"[Report] Open this file in browser to view the formatted report")


if __name__ == "__main__":
    main()
