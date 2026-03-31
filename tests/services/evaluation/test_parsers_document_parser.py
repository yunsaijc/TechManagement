"""正文解析器测试"""
from src.services.evaluation.parsers.document_parser import DocumentParser


def test_document_parser_build_page_chunks_respects_in_page_section_switch():
    """同一页内出现新标题时，后续切片应切换到新章节"""
    parser = DocumentParser()

    sections = {
        "项目简介": "项目简介\n背景与意义\n建设目标",
        "进度安排": "进度安排\n第一年（2025年）",
    }
    page_texts = [
        "\n".join(
            [
                "项目简介",
                "背景与意义",
                "通过设施升级提升服务能力。",
                "建设目标",
                "搭建智能平台。",
                "进度安排",
                "第一年（2025年）",
                "完成平台原型开发。",
            ]
        )
    ]

    chunks = parser._build_page_chunks(page_texts=page_texts, sections=sections, file_name="demo.pdf")

    assert chunks
    assert any(chunk["section"] == "项目简介" and "搭建智能平台" in chunk["text"] for chunk in chunks)
    assert any(chunk["section"] == "进度安排" and "完成平台原型开发" in chunk["text"] for chunk in chunks)


def test_document_parser_build_page_chunks_carries_section_across_pages():
    """下一页没有新标题时，应继承上一页的章节上下文"""
    parser = DocumentParser()

    sections = {
        "进度安排": "进度安排\n第一年（2025年）\n第二年（2026年）",
    }
    page_texts = [
        "\n".join(
            [
                "进度安排",
                "第一年（2025年）",
                "完成平台原型开发。",
            ]
        ),
        "\n".join(
            [
                "第二年（2026年）",
                "扩大试点并形成阶段成果。",
            ]
        ),
    ]

    chunks = parser._build_page_chunks(page_texts=page_texts, sections=sections, file_name="demo.pdf")

    page_two_chunks = [chunk for chunk in chunks if chunk["page"] == 2]
    assert page_two_chunks
    assert all(chunk["section"] == "进度安排" for chunk in page_two_chunks)
    assert any("扩大试点并形成阶段成果" in chunk["text"] for chunk in page_two_chunks)
