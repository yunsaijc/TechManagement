"""评审报告生成器测试"""
import json
from pathlib import Path

import fitz

from src.services.evaluation.parsers import DocumentParser
from src.services.evaluation.scorers.report_generator import ReportGenerator


def _write_pdf(path: Path, text: str) -> None:
    """写入简单 PDF，供报告构建测试使用"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 96), text, fontsize=14)
    doc.save(path)
    doc.close()


def _write_multi_page_pdf(path: Path, page_texts: list[str]) -> None:
    """写入多页 PDF，供 packet 高亮回归测试使用"""
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 96), text, fontsize=14)
    doc.save(path)
    doc.close()


def _build_debug_payload(chat_ready: bool = True) -> dict:
    """构造最小调试载荷"""
    return {
        "source_name": "demo.pdf",
        "sections": {"项目简介": "项目目标：建设智能化服务平台。"},
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目简介",
                "text": "项目目标：建设智能化服务平台。",
            }
        ],
        "expert_qna": [
            {
                "question": "这个项目的研究目标是什么？",
                "answer": "研究目标是建设智能化服务平台。",
                "citations": [{"file": "demo.pdf", "page": 5, "snippet": "项目目标：建设智能化服务平台。"}],
            }
        ],
        "result": {
            "project_id": "demo-project",
            "project_name": "示例项目",
            "evaluation_id": "EVAL_DEMO",
            "overall_score": 8.6,
            "grade": "B",
            "summary": "总体可行。",
            "recommendations": [],
            "dimension_scores": [
                {
                    "dimension": "innovation",
                    "dimension_name": "创新性",
                    "score": 6.0,
                    "weight": 0.2,
                    "opinion": "创新点存在，但表述还不够聚焦。",
                    "issues": ["创新表达偏散"],
                    "highlights": ["技术路线与场景结合较好"],
                },
                {
                    "dimension": "risk",
                    "dimension_name": "风险控制",
                    "score": 4.0,
                    "weight": 0.1,
                    "opinion": "风险识别不足，缺少清晰应对方案。",
                    "issues": ["缺少明确风险对策"],
                    "highlights": [],
                },
            ],
            "evidence": [],
            "highlights": {},
            "errors": [],
            "industry_fit": None,
            "benchmark": None,
            "chat_ready": chat_ready,
            "created_at": "2026-04-02T12:00:00",
        },
    }


def test_report_generator_formal_html_contains_interactive_chat_panel():
    """正式报告应包含交互式聊天面板和调用脚本"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    assert 'id="report-document"' in html
    assert 'id="project-rail"' not in html
    assert 'id="document-rail"' not in html
    assert 'id="result-tabs"' in html
    assert 'data-tab-target="report-chat"' in html
    assert 'data-tab-target="report-fit"' not in html
    assert 'data-tab-target="report-benchmark"' in html
    assert 'id="report-chat"' in html
    assert 'id="report-benchmark"' in html
    assert "未执行技术摸底" in html
    assert 'id="chat-form"' in html
    assert "/api/v1/evaluation/chat/ask" in html
    assert "/api/v1/evaluation/chat/ask-stream" in html
    assert "/api/v1/evaluation/chat/citation-highlight" in html
    assert 'data-evaluation-id="EVAL_DEMO"' in html
    assert 'data-default-api-base="http://127.0.0.1:8888"' in html
    assert "return window.location.origin;" in html
    assert "研究目标是什么" in html
    assert 'id="dimension-accordion"' in html
    assert 'id="dimension-radar-svg"' in html
    assert 'class="dimension-detail-item is-active"' in html
    assert "风险控制" in html
    assert 'class="content-grid workspace-layout"' in html
    assert "hero-nav" not in html
    assert 'id="chat-empty"' in html
    assert 'id="chat-progress"' in html
    assert 'id="chat-progress-status"' in html
    assert "parseStructuredAnswer" in html
    assert "chat-answer-head" in html
    assert "chat-answer-tag" in html
    assert "chat-followup" in html
    assert "window.__evaluationJumpToTrigger" in html
    assert "requestChatAnswerStream" in html
    assert 'eventName === "status"' in html
    assert "streamMessage.setPhase" in html
    assert "setProgressState" in html
    assert "chat-citation-label" in html
    assert "chat-citation-snippet" not in html
    assert "chat-live-skeleton" in html
    assert "text/event-stream" not in html


def test_report_generator_benchmark_uses_readable_chinese_labels_and_reference_cards():
    """技术摸底应使用中文新颖性标签和精简参考条目"""
    generator = ReportGenerator()
    payload = _build_debug_payload()
    payload["result"]["benchmark"] = {
        "novelty_level": "medium",
        "literature_position": "已检索到 2 条相关文献",
        "patent_overlap": "专利对比待接入",
        "conclusion": "项目与同类研究存在可比较改进空间。",
        "references": [
            {
                "source": "literature",
                "title": "数字技术在创伤骨科的应用 临床数字骨科（一）",
                "year": 2011,
            }
        ],
    }

    html = generator.build_html(payload, debug_mode=False)

    assert "对比参考" in html
    assert "中等" in html
    assert "benchmark-reference-item" in html
    assert "论文 · 2011" in html
    assert "literature / 数字技术在创伤骨科的应用 临床数字骨科（一） / 2011" not in html


def test_report_generator_debug_html_hides_interactive_chat_panel():
    """调试报告不应渲染交互式聊天面板"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=True)

    assert "专家即时问答" not in html
    assert 'id="report-chat"' not in html
    assert 'id="document-rail"' not in html
    assert 'id="result-tabs"' not in html


def test_report_generator_dimension_dashboard_defaults_to_lowest_score_item():
    """维度评分应默认选中最低分维度"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    active_index = html.find('class="dimension-detail-item is-active"')
    risk_index = html.find("风险控制")
    innovation_index = html.find("创新性")

    assert active_index != -1
    assert risk_index != -1 and innovation_index != -1
    assert abs(active_index - risk_index) < abs(active_index - innovation_index)


def test_report_generator_dimension_dashboard_uses_radar_and_single_detail_panel():
    """维度评分应展示雷达图和单一详情面板，而不是旧 accordion 和条子导航"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    assert 'class="dimension-radar-svg"' in html
    assert 'class="dimension-radar-sector"' in html
    assert 'class="dimension-detail-item"' in html
    assert 'class="dimension-nav-item"' not in html
    assert 'class="score-item is-open"' not in html
    assert "展开详情" not in html


def test_report_generator_dimension_detail_uses_structured_blocks():
    """维度详情应拆成判断、依据、优势、短板和建议动作"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    assert 'class="dimension-detail-blocks"' in html
    assert "一句话判断" in html
    assert "主要依据" in html
    assert "优势" in html
    assert "短板 / 待补充" in html
    assert "建议动作" in html


def test_report_generator_dimension_detail_filters_neutral_notes_from_issues_and_actions():
    """中性替代评估说明不应被当成短板和建议动作重复展示"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["result"]["dimension_scores"] = [
        {
            "dimension": "feasibility",
            "dimension_name": "技术可行性",
            "score": 6.5,
            "weight": 0.12,
            "opinion": "该项目更偏平台建设或科普实施类，当前未命中独立技术路线章节，已基于科普基础设施建设、科普内容产出、科普活动开展等替代材料进行基础可行性判断，不再强制要求独立技术路线章节。",
            "issues": ["未设置独立技术路线章节，已按科普基础设施建设、科普内容产出等替代内容评估"],
            "highlights": ["已识别章节：科普基础设施建设", "已识别章节：科普内容产出"],
        }
    ]

    html = generator.build_html(payload, debug_mode=False)

    assert "暂无明显短板" in html
    assert "暂无明确建议动作" in html
    assert "明确未设置独立技术路线章节" not in html
    assert "已识别章节：" not in html
    assert "已覆盖科普基础设施建设、科普内容产出等实施内容" in html


def test_report_generator_formal_html_flattens_result_panel_shells():
    """正式报告右侧结果区不应再叠加多层 panel 容器"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)
    normalized = " ".join(html.split())

    assert '<section class="panel result-shell" id="result-shell">' in html
    assert '<section class="result-panel is-active" id="report-overview"> <section class="panel">' not in normalized
    assert '<section class="result-panel" id="report-dimensions"> <section class="panel">' not in normalized
    assert '<section class="result-panel" id="report-chat"> <section class="panel">' not in normalized


def test_report_generator_formal_html_locks_outer_scroll_and_keeps_inner_scroll_regions():
    """正式报告应固定整体视口，仅让中右栏内部滚动"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    assert "height: 100dvh;" in html
    assert ".workspace-layout {\n      grid-template-columns: 150px minmax(0, 1.55fr) minmax(430px, 1.08fr);\n      overflow: hidden;" in html
    assert ".result-panels {\n      min-height: 0;\n      height: 100%;\n      overflow: auto;" in html


def test_report_generator_formal_html_renders_highlights_as_flat_blocks():
    """划重点应以扁平段落块展示，不再套有序列表"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["result"]["evidence"] = [
        {
            "source": "结构化摘要",
            "file": "demo.pdf",
            "page": 5,
            "snippet": "项目目标：建设智能化服务平台。",
            "category": "goal",
            "target": "建设智能化服务平台。",
        }
    ]
    payload["result"]["highlights"] = {
        "research_goals": ["建设智能化服务平台。"],
        "innovations": [],
        "technical_route": [],
    }

    html = generator.build_html(payload, debug_mode=False)

    assert 'class="highlight-list"' in html
    assert 'class="highlight-item-text"' in html
    assert 'class="highlight-item-evidence"' in html
    assert '<ol class="list">' not in html


def test_report_generator_formal_html_renders_fit_and_benchmark_as_flat_sections():
    """指南贴合与技术摸底应采用扁平分组，不再输出表格"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["result"]["industry_fit"] = {
        "fit_score": 0.82,
        "matched": ["契合指南方向A"],
        "gaps": ["缺少方向B支撑"],
        "suggestions": ["补充方向B论证"],
    }
    payload["result"]["benchmark"] = {
        "novelty_level": "中等偏上",
        "literature_position": "有一定差异化",
        "patent_overlap": "低",
        "conclusion": "具备一定创新空间",
        "references": [{"source": "论文", "title": "示例文献", "year": 2024}],
    }

    html = generator.build_html(payload, debug_mode=False)

    assert 'class="flat-stack"' in html
    assert 'class="flat-section"' in html
    assert 'class="flat-label">贴合度<' in html
    assert 'class="flat-label">综合结论<' in html
    assert '<table class="kv-table">' not in html


def test_report_generator_benchmark_references_render_as_flat_list():
    """技术摸底参考文献应保持扁平列表展示，避免改动原有版式"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["result"]["benchmark"] = {
        "novelty_level": "medium",
        "literature_position": "已检索到 1 条相关文献",
        "patent_overlap": "专利对比待接入",
        "conclusion": "当前公开论文对比显示具备一定相关基础。",
        "references": [
            {
                "source": "literature",
                "title": "数字技术在创伤骨科的应用 临床数字骨科（一）",
                "snippet": "围绕骨科临床数字化、导航与机器人辅助手术展开。",
                "year": 2011,
                "url": "https://openalex.org/W938609951",
            }
        ],
    }

    html = generator.build_html(payload, debug_mode=False)

    assert 'class="flat-list"' in html
    assert "literature / 数字技术在创伤骨科的应用 临床数字骨科（一） / 2011" in html
    assert 'class="benchmark-ref-card"' not in html
    assert "查看来源" not in html


def test_report_generator_chat_panel_allows_first_ask_when_chat_not_ready():
    """未预构建索引时也应允许提问，由后端首问自动重建"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(chat_ready=False), debug_mode=False)

    assert "busy || !evaluationId" in html
    assert "未构建聊天索引，无法发起实时问答" not in html


def test_report_generator_formal_html_exposes_document_jump_targets():
    """证据与引用应带统一的正文跳转标记"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["result"]["evidence"] = [
        {
            "source": "结构化摘要",
            "file": "demo.pdf",
            "page": 5,
            "snippet": "项目目标：建设智能化服务平台。",
            "category": "goal",
            "target": "建设智能化服务平台。",
        }
    ]
    payload["result"]["highlights"] = {
        "research_goals": ["建设智能化服务平台。"],
        "innovations": [],
        "technical_route": [],
    }

    html = generator.build_html(payload, debug_mode=False)

    assert 'data-doc-jump="true"' in html
    assert 'id="doc-page-5"' in html
    assert "jumpToEvidence" in html


def test_report_generator_formal_html_prefers_packet_viewer_when_available():
    """存在 packet 资产时，正式报告应优先渲染统一材料 viewer"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["packet_assets"] = {
        "viewer_file": "projects/demo-project/packet_viewer.html",
        "packet_abs_path": "/tmp/demo-project/evaluation_packet.pdf",
        "page_map": [
            {
                "source_file": "/tmp/demo.pdf",
                "source_name": "demo.pdf",
                "source_kind": "proposal",
                "start_page": 1,
                "end_page": 3,
            }
        ],
    }
    payload["result"]["evidence"] = [
        {
            "source": "结构化摘要",
            "file": "demo.pdf",
            "page": 2,
            "snippet": "项目目标：建设智能化服务平台。",
            "category": "goal",
            "target": "建设智能化服务平台。",
        }
    ]
    payload["result"]["highlights"] = {
        "research_goals": ["建设智能化服务平台。"],
        "innovations": [],
        "technical_route": [],
    }

    html = generator.build_html(payload, debug_mode=False)

    assert 'id="packet-viewer-frame"' in html
    assert 'src="projects/demo-project/packet_viewer.html"' in html
    assert 'data-file="demo.pdf"' in html
    assert 'data-packet-page="2"' in html
    assert "const pageMap = [{" in html
    assert 'id="doc-toast"' in html
    assert "未定位到精确片段，已跳转到对应页。" in html
    assert 'data-packet-page="${escapeHtml(citation.packet_page || "")}"' in html
    assert "JSON.stringify(citation.highlight_rects || [])" in html
    assert 'data-chat-citation="true"' in html


def test_report_generator_packet_page_matches_source_name_when_only_basename_is_available():
    """仅有文件名时，也应能按 page_map 的 source_name 映射 packet 页码"""
    generator = ReportGenerator()

    packet_page = generator._resolve_packet_page(
        packet_assets={
            "page_map": [
                {
                    "source_file": "/tmp/projects/demo.pdf",
                    "source_name": "demo.pdf",
                    "source_kind": "proposal",
                    "start_page": 4,
                    "end_page": 8,
                }
            ]
        },
        source_file="demo.pdf",
        page=2,
    )

    assert packet_page == 5


def test_report_generator_packet_highlight_can_correct_to_neighbor_page(tmp_path: Path):
    """packet 高亮应能在附近页纠正命中页，而不是死守传入页码"""
    generator = ReportGenerator()
    packet_pdf = tmp_path / "packet.pdf"
    _write_multi_page_pdf(
        packet_pdf,
        [
            "page one overview",
            "page two contains key sentence: intelligent service platform demonstration",
            "page three conclusion",
        ],
    )

    payload = generator._resolve_packet_jump_payload(
        packet_assets={
            "packet_abs_path": str(packet_pdf),
            "page_map": [
                {
                    "source_file": str(tmp_path / "demo.pdf"),
                    "source_name": "demo.pdf",
                    "source_kind": "proposal",
                    "start_page": 1,
                    "end_page": 3,
                    "page_count": 3,
                }
            ],
        },
        source_file=str(tmp_path / "demo.pdf"),
        page=1,
        snippet="intelligent service platform demonstration",
    )

    assert payload["packet_page"] == 2
    assert payload["highlight_rects"]


def test_report_generator_build_from_debug_file_recovers_missing_page_chunks(
    tmp_path: Path,
    monkeypatch,
):
    """旧 debug JSON 缺 page_chunks 时，应尝试回源补齐正文页切片"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload.pop("page_chunks", None)
    payload["meta"] = {
        "file_name": "demo.pdf",
        "file_path": str(tmp_path / "demo.pdf"),
        "page_estimated": False,
        "page_count": 1,
    }

    debug_json = tmp_path / "demo.json"
    output_html = tmp_path / "demo.html"
    debug_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _write_pdf(tmp_path / "demo.pdf", "自动补齐的正文内容")

    async def fake_parse(self, file_path: str, source_name: str = ""):
        return {
            "page_chunks": [
                {
                    "id": 1,
                    "file": source_name or "demo.pdf",
                    "page": 3,
                    "section": "项目简介",
                    "text": "自动补齐的正文内容",
                }
            ],
            "meta": {
                "file_name": source_name or "demo.pdf",
                "file_path": file_path,
                "page_count": 3,
                "page_estimated": False,
            },
        }

    monkeypatch.setattr(DocumentParser, "parse", fake_parse)

    generator.build_from_debug_file(debug_json, output_html, debug_mode=False)

    html = output_html.read_text(encoding="utf-8")
    updated_json = debug_json.read_text(encoding="utf-8")

    assert 'id="packet-viewer-frame"' in html
    assert "自动补齐的正文内容" in updated_json
    assert '"page_chunks"' in updated_json


def test_report_generator_build_from_debug_file_keeps_single_project_layout(
    tmp_path: Path,
    monkeypatch,
):
    """正式报告重建时应保持单项目布局，不注入多项目切换栏"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["meta"] = {
        "file_name": "demo.pdf",
        "file_path": str(tmp_path / "demo.pdf"),
        "page_estimated": False,
        "page_count": 1,
    }
    debug_json = tmp_path / "EVAL_demo-project.json"
    output_html = tmp_path / "EVAL_demo-project.html"
    debug_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _write_pdf(tmp_path / "demo.pdf", "项目目标：建设智能化服务平台。")

    other_payload = _build_debug_payload()
    other_payload["result"]["project_id"] = "another-project"
    other_payload["result"]["project_name"] = "另一个项目"
    (tmp_path / "EVAL_another-project.json").write_text(json.dumps(other_payload, ensure_ascii=False), encoding="utf-8")

    async def fake_parse(self, file_path: str, source_name: str = ""):
        return {
            "page_chunks": payload["page_chunks"],
            "meta": payload["meta"],
        }

    monkeypatch.setattr(DocumentParser, "parse", fake_parse)

    generator.build_from_debug_file(debug_json, output_html, debug_mode=False)

    html = output_html.read_text(encoding="utf-8")
    assert 'id="project-rail"' not in html
    assert "另一个项目" not in html
    assert 'href="EVAL_another-project.html"' not in html
    assert 'id="document-rail"' not in html
    assert 'id="report-chat"' in html


def test_report_generator_build_index_html_ignores_hash_docx_project_name(
    tmp_path: Path,
    monkeypatch,
):
    """多项目索引页的左侧项目栏不应把 hash docx 文件名当成项目名称"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["result"]["project_name"] = "示例项目"
    payload["meta"] = {
        "file_name": "demo.pdf",
        "file_path": str(tmp_path / "demo.pdf"),
        "page_estimated": False,
        "page_count": 1,
    }
    debug_json = tmp_path / "EVAL_demo-project.json"
    output_html = tmp_path / "EVAL_demo-project.html"
    debug_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _write_pdf(tmp_path / "demo.pdf", "项目目标：建设智能化服务平台。")

    other_payload = _build_debug_payload()
    other_payload["project_name"] = "ffb75a4c639d4ebab2c33e21d75d7bac.docx"
    other_payload["result"]["project_id"] = "ffb75a4c639d4ebab2c33e21d75d7bac"
    other_payload["result"]["project_name"] = "ffb75a4c639d4ebab2c33e21d75d7bac.docx"
    other_payload["sections"] = {
        "概述": (
            "河北省创新能力提升计划项目申报书 "
            "项 目 名 称 ：生殖健康科普示范基地标准化建设与创新模式探索 "
            "承 担 单 位 ：河北医科大学第四医院"
        )
    }
    (tmp_path / "EVAL_ffb75a4c639d4ebab2c33e21d75d7bac.json").write_text(
        json.dumps(other_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    async def fake_parse(self, file_path: str, source_name: str = ""):
        return {
            "page_chunks": payload["page_chunks"],
            "meta": payload["meta"],
        }

    monkeypatch.setattr(DocumentParser, "parse", fake_parse)

    generator.build_from_debug_file(debug_json, output_html, debug_mode=False)

    records = [
        {
            **payload["result"],
            "payload": payload,
            "html_file": "EVAL_demo-project.html",
        },
        {
            **other_payload["result"],
            "payload": other_payload,
            "html_file": "EVAL_ffb75a4c639d4ebab2c33e21d75d7bac.html",
        },
    ]
    index_html = generator.build_index_html(records)
    assert "生殖健康科普示范基地标准化建设与创新模式探索" in index_html
    assert "ffb75a4c639d4ebab2c33e21d75d7bac.docx" not in index_html


def test_report_generator_build_from_debug_file_backfills_packet_assets(tmp_path: Path):
    """旧 debug JSON 缺少 packet 资产时，应自动回源生成统一材料 viewer"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    pdf_path = tmp_path / "demo.pdf"
    _write_pdf(pdf_path, "项目目标：建设智能化服务平台。")

    payload["meta"] = {
        "file_name": "demo.pdf",
        "file_path": str(pdf_path),
        "page_estimated": False,
        "page_count": 1,
    }

    debug_json = tmp_path / "EVAL_demo-project.json"
    output_html = tmp_path / "EVAL_demo-project.html"
    debug_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    generator.build_from_debug_file(debug_json, output_html, debug_mode=False)

    html = output_html.read_text(encoding="utf-8")
    updated_json = debug_json.read_text(encoding="utf-8")

    assert 'id="packet-viewer-frame"' in html
    assert 'src="projects/demo-project/packet_viewer.html"' in html
    assert '"packet_assets"' in updated_json
    assert (tmp_path / "projects" / "demo-project" / "packet_viewer.html").exists()


def test_report_generator_build_from_debug_file_backfills_missing_highlights(tmp_path: Path):
    """旧 debug JSON 缺少划重点结果时，应按当前提取器回填并写回 JSON"""
    generator = ReportGenerator()

    payload = _build_debug_payload()
    payload["sections"] = {
        "项目简介": "建设目标：建设智能化服务平台，形成统一数据底座，支撑跨场景智能分析与服务。",
        "创新点": "创新点1 智能问答平台。创新点2 多模态数据融合技术。",
        "技术路线": "技术路线：搭建平台，整合数据，开发模型，形成应用闭环。",
    }
    payload["page_chunks"] = [
        {
            "id": 1,
            "file": "demo.pdf",
            "page": 2,
            "section": "项目简介",
            "text": "建设目标：建设智能化服务平台，形成统一数据底座，支撑跨场景智能分析与服务。",
        },
        {
            "id": 2,
            "file": "demo.pdf",
            "page": 3,
            "section": "创新点",
            "text": "创新点1 智能问答平台。创新点2 多模态数据融合技术。",
        },
        {
            "id": 3,
            "file": "demo.pdf",
            "page": 4,
            "section": "技术路线",
            "text": "技术路线：搭建平台，整合数据，开发模型，形成应用闭环。",
        },
    ]
    payload["result"]["highlights"] = {}
    payload["result"]["evidence"] = []
    payload["meta"] = {
        "file_name": "demo.pdf",
        "file_path": str(tmp_path / "demo.pdf"),
        "page_estimated": False,
        "page_count": 4,
    }

    debug_json = tmp_path / "EVAL_demo-project.json"
    output_html = tmp_path / "EVAL_demo-project.html"
    debug_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _write_pdf(tmp_path / "demo.pdf", "项目目标：建设智能化服务平台。")

    generator.build_from_debug_file(debug_json, output_html, debug_mode=False)

    updated = json.loads(debug_json.read_text(encoding="utf-8"))
    highlights = updated["result"]["highlights"]
    evidence = updated["result"]["evidence"]
    html = output_html.read_text(encoding="utf-8")

    assert highlights["research_goals"]
    assert highlights["innovations"]
    assert highlights["technical_route"]
    assert evidence
    assert "建设智能化服务平台" in html


def test_report_generator_build_index_html_creates_multi_project_workspace():
    """索引页应升级为多项目工作台，而不是简单表格索引"""
    generator = ReportGenerator()

    html = generator.build_index_html(
        [
            {
                "project_id": "demo-project-a",
                "project_name": "示例项目A",
                "overall_score": 8.8,
                "grade": "A",
                "html_file": "EVAL_demo-project-a.html",
                "debug_html_file": "EVAL_demo-project-a.debug.html",
                "json_file": "EVAL_demo-project-a.json",
                "payload": {"result": {"summary": "项目A摘要"}},
            },
            {
                "project_id": "demo-project-b",
                "project_name": "示例项目B",
                "overall_score": 7.6,
                "grade": "B",
                "html_file": "EVAL_demo-project-b.html",
                "debug_html_file": "EVAL_demo-project-b.debug.html",
                "json_file": "EVAL_demo-project-b.json",
                "payload": {"result": {"summary": "项目B摘要"}},
            },
        ]
    )

    assert "项目评审工作台" in html
    assert 'class="project-item is-active"' in html
    assert 'data-project-html="EVAL_demo-project-a.html"' in html
    assert 'data-project-html="EVAL_demo-project-b.html"' in html
    assert 'id="evaluation-workspace-frame"' in html
    assert 'src="EVAL_demo-project-a.html"' in html
    assert "左侧切项目，右侧查看该项目完整评审报告。" not in html
    assert "project-item-summary" not in html
    assert "project-item-links" not in html
    assert "height: 100dvh;" in html
    assert "overflow: hidden;" in html
    assert "html, body {" in html
