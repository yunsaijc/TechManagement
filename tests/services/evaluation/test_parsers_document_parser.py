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
    assert any(chunk["section"] == "研究目标" and "搭建智能平台" in chunk["text"] for chunk in chunks)
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


def test_document_parser_build_page_chunks_marks_instruction_page_as_fill_guide():
    """填报说明页不应因列举章节名称被误归入业务章节"""
    parser = DocumentParser()

    sections = {
        "进度安排": "进度安排\n第一年（2025年）",
    }
    page_texts = [
        "\n".join(
            [
                "填报说明",
                "1.项目申报书分为“研究内容”“进度安排”“项目预算表”和“附件”四个部分。",
                "2.申报书内容须实事求是、准确完整、层次清晰。",
            ]
        )
    ]

    chunks = parser._build_page_chunks(page_texts=page_texts, sections=sections, file_name="demo.pdf")

    assert chunks
    assert all(chunk["section"] == "填报说明" for chunk in chunks)


def test_document_parser_build_page_chunks_keeps_attachment_page_under_attachment():
    """附件页中的附件名称不应被误切成业务章节"""
    parser = DocumentParser()

    sections = {
        "附件": "附件目录\n科普能力建设目标",
    }
    page_texts = [
        "\n".join(
            [
                "十一、附件",
                "附件目录：",
                "序号 | 附件类型 | 附件名称",
                "5 | 其他 | 科普能力建设目标",
                "6 | 其他 | 科普能力提升规划",
            ]
        )
    ]

    chunks = parser._build_page_chunks(page_texts=page_texts, sections=sections, file_name="demo.pdf")

    assert chunks
    assert all(chunk["section"] == "附件" for chunk in chunks)


def test_document_parser_build_page_chunks_does_not_promote_kpi_table_fragments_to_goal():
    """绩效表中的表头碎片不应被误识别为研究目标章节"""
    parser = DocumentParser()

    sections = {
        "项目绩效评价考核目标及指标": "总体目标\n指标名称\n指标值",
    }
    page_texts = [
        "\n".join(
            [
                "第六部分 项目绩效评价考核目标及指标",
                "总体",
                "目标",
                "形成示范应用方案。",
                "指标名称",
                "指标值",
            ]
        )
    ]

    chunks = parser._build_page_chunks(page_texts=page_texts, sections=sections, file_name="demo.pdf")

    assert chunks
    assert all(chunk["section"] == "项目绩效评价考核目标及指标" for chunk in chunks)
