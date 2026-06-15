"""评审报告生成器测试"""
import json
import os
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


def _write_multiline_pdf(path: Path, lines: list[str]) -> None:
    """写入多行 PDF，供完整证据范围高亮测试使用"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for index, line in enumerate(lines):
        page.insert_text((72, 96 + index * 24), line, fontsize=14)
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
    expected_port = os.getenv("APP_PORT", "8000")
    assert 'data-default-api-base=""' in html
    assert f'data-default-port="{expected_port}"' in html
    assert 'params.get("apiBase")' in html
    assert "tech_report_api_base" in html
    assert "currentHostBackendBase" in html
    assert "return window.location.origin;" in html
    assert "请确认正文评审服务已启动" in html
    assert "研究目标是什么" in html
    assert 'id="dimension-accordion"' in html
    assert 'id="dimension-radar-svg"' in html
    assert 'class="dimension-detail-item is-active"' in html
    assert "风险控制" in html
    assert 'class="content-grid evaluation-layout"' in html
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
    assert "buildCitationLink" in html
    assert "buildCitationLinks" in html
    assert "chat-citation-label" not in html
    assert "chat-citation-snippet" not in html
    assert "chat-live-skeleton" in html
    assert "text/event-stream" not in html


def test_report_generator_chat_extra_citations_attach_to_last_basis_item():
    """聊天证据多于依据时，应按目标文本分组，不单独空行展示。"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    assert "extraCitationHtml" not in html
    assert "groupCitationsByBasis" in html
    assert "citation.target_text" in html


def test_report_generator_reward_html_hides_benchmark_without_affecting_project():
    """奖励平台不展示技术摸底；计划项目仍保留该模块。"""
    generator = ReportGenerator()
    reward_payload = _build_debug_payload()
    reward_payload["meta"] = {"platform": "reward"}

    reward_html = generator.build_html(reward_payload, debug_mode=False)
    project_html = generator.build_html(_build_debug_payload(), debug_mode=False)

    assert 'data-tab-target="report-benchmark"' not in reward_html
    assert 'id="report-benchmark"' not in reward_html
    assert "技术摸底" not in reward_html
    assert 'data-tab-target="report-benchmark"' in project_html
    assert 'id="report-benchmark"' in project_html
    assert "技术摸底" in project_html


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


def test_report_generator_reward_dimension_corrects_docx_packet_page_with_structured_evidence(tmp_path):
    """奖励维度证据应按结构化来源校正 DOCX packet 页，并保持页码与高亮一致。"""
    packet_path = tmp_path / "packet.pdf"
    _write_multi_page_pdf(
        packet_path,
        [
            "cover",
            "source page one",
            "SCI included 3 papers",
            "mapped source page without target",
        ],
    )
    generator = ReportGenerator()
    payload = _build_debug_payload()
    payload["meta"] = {"platform": "reward"}
    payload["packet_assets"] = {
        "packet_abs_path": str(packet_path),
        "page_map": [
            {
                "source_file": "reward.docx",
                "source_kind": "proposal",
                "start_page": 3,
                "end_page": 4,
            }
        ],
    }
    payload["page_chunks"] = [
        {
            "id": 1,
            "file": "reward.docx",
            "page": 2,
            "section": "代表性论文",
            "text": "SCI included 3 papers and citation data.",
        }
    ]
    payload["result"]["dimension_scores"] = [
        {
            "dimension": "outcome",
            "dimension_name": "代表性成果",
            "score": 7.5,
            "weight": 0.2,
            "opinion": "材料已通过 SCI 收录支撑代表性成果判断，证据较充分。主要依据：材料体现 SCI 收录 3 篇。",
            "issues": [],
            "highlights": ["材料体现 SCI 收录 3 篇"],
            "details": {
                "reward_scoring_adjusted": True,
                "evidence_items": [
                    {
                        "claim": "SCI 收录",
                        "basis": "材料体现 SCI 收录 3 篇",
                        "source_section": "代表性论文",
                        "source_text": "SCI included 3 papers and citation data.",
                        "highlight_text": "SCI included 3 papers",
                    }
                ],
            },
        }
    ]

    html = generator.build_html(payload, debug_mode=False)

    assert "证据：SCI included 3 papers and citation data." in html
    assert 'data-page="2"' in html
    assert 'data-packet-page="3"' in html
    assert 'class="inline-citation"' in html
    assert "查看原文 · 第 3 页" in html
    assert "data-highlight-rects='[]" not in html


def test_report_generator_reward_dimension_highlight_uses_precise_fact_not_context(tmp_path):
    """奖励证据展示可保留上下文，但 PDF 高亮只定位事实句。"""
    packet_path = tmp_path / "packet.pdf"
    _write_multi_page_pdf(
        packet_path,
        [
            "cover",
            (
                "三价早熟疫苗能够提供抗球虫病的免疫保护。"
                "该项目形成代表性论文6篇，其中SCI收录3篇，引用64次，他引53次，"
                "为球虫的虫种鉴定与早熟活疫苗的研究提供了可靠的理论依据。"
            ),
        ],
    )
    generator = ReportGenerator()
    payload = _build_debug_payload()
    payload["meta"] = {"platform": "reward"}
    payload["packet_assets"] = {
        "packet_abs_path": str(packet_path),
        "page_map": [
            {
                "source_file": "reward.docx",
                "source_kind": "proposal",
                "start_page": 2,
                "end_page": 2,
            }
        ],
    }
    source_text = (
        "三价早熟疫苗能够提供抗球虫病的免疫保护。"
        "该项目形成代表性论文6篇，其中SCI收录3篇，引用64次，他引53次，"
        "为球虫的虫种鉴定与早熟活疫苗的研究提供了可靠的理论依据。"
    )
    payload["page_chunks"] = [
        {
            "id": 1,
            "file": "reward.docx",
            "page": 1,
            "section": "项目简介（限1200字）",
            "text": source_text,
        }
    ]
    payload["result"]["dimension_scores"] = [
        {
            "dimension": "outcome",
            "dimension_name": "代表性成果",
            "score": 7.5,
            "weight": 0.2,
            "opinion": "材料已通过代表性论文支撑成果判断，证据较充分。主要依据：形成代表性论文6篇。",
            "issues": [],
            "highlights": ["形成代表性论文6篇"],
            "details": {
                "reward_scoring_adjusted": True,
                "evidence_items": [
                    {
                        "claim": "代表性论文",
                        "basis": "形成代表性论文6篇",
                        "source_section": "项目简介（限1200字）",
                        "source_text": source_text,
                        "highlight_text": "代表性论文",
                    }
                ],
            },
        }
    ]

    html = generator.build_html(payload, debug_mode=False)

    assert "证据：三价早熟疫苗能够提供抗球虫病的免疫保护" in html
    assert 'data-highlight-text="形成代表性论文6篇，其中SCI收录3篇，引用64次，他引53次，为球虫的虫种鉴定与早熟活疫苗的研究提供了可靠的理论依据"' in html
    highlight_attr = html.split('data-highlight-text="', 1)[1].split('"', 1)[0]
    assert "三价早熟疫苗能够提供抗球虫病的免疫保护" not in highlight_attr


def test_report_generator_reward_dimension_weak_highlight_uses_sentence_not_tiny_word():
    """弱标签命中时应高亮所在短句，不能只高亮两三个字。"""
    generator = ReportGenerator()

    highlight = generator._build_reward_precise_highlight_snippet(
        "兔球虫病是一类寄生性原虫病，给养兔业造成重大经济损失，对我国养兔业危害较严重。",
        "养兔业",
    )

    assert highlight == "兔球虫病是一类寄生性原虫病，给养兔业造成重大经济损失，对我国养兔业危害较严重。"


def test_report_generator_packet_highlight_prefers_full_evidence_range(tmp_path):
    """长证据应优先高亮完整相关范围，且连续文本尽量合成一个展示框。"""
    packet_path = tmp_path / "packet.pdf"
    _write_multiline_pdf(
        packet_path,
        [
            "Project team materials are listed below.",
            "Main contributor form includes member information.",
            "Completion unit is Hebei North University with unit statement.",
            "Work unit statement confirms materials are valid.",
        ],
    )
    generator = ReportGenerator()

    payload = generator._resolve_packet_jump_payload(
        {
            "packet_abs_path": str(packet_path),
            "page_map": [
                {
                    "source_file": "reward.docx",
                    "source_kind": "proposal",
                    "start_page": 1,
                    "end_page": 1,
                }
            ],
        },
        "reward.docx",
        1,
        (
            "Main contributor form includes member information. "
            "Completion unit is Hebei North University with unit statement. "
            "Work unit statement confirms materials are valid."
        ),
        strict_highlight=True,
    )

    assert payload["packet_page"] == 1
    assert len(payload["highlight_rects"]) == 1
    assert payload["highlight_rects"][0]["h"] > 0.08


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
    assert ".evaluation-layout {\n      grid-template-columns: minmax(0, 2.05fr) minmax(360px, 0.92fr);\n      overflow: hidden;" in html
    assert ".result-panels {\n      min-height: 0;\n      height: 100%;\n      overflow: auto;" in html


def test_report_generator_reward_overview_uses_nomination_sections():
    """奖励平台首页应展示提名书口径，不影响项目申报书三段摘要"""
    generator = ReportGenerator()
    payload = _build_debug_payload()
    payload["meta"] = {"platform": "reward"}
    payload["sections"] = {
        "项目简介（限1200字）": "奖励项目简介内容。",
        "重要科学发现": "重要科学发现内容。",
        "客观评价（不超过2页）": "客观评价内容。",
        "代表性论文(专著)目录（不超过6篇）": "代表性论文内容。",
    }

    html = generator.build_html(payload, debug_mode=False)

    assert "总体判断" in html
    assert "核心贡献" in html
    assert "总体可行。" in html
    assert "重要科学发现" in html
    assert "重要科学发现内容。" in html
    assert "客观评价内容。" in html
    assert "成果支撑" in html
    assert "代表性论文内容。" in html
    assert "研究目标</div>" not in html


def test_report_generator_reward_overview_cleans_docx_table_markers():
    """奖励平台首页不应把 DOCX 表格解析标记直接展示给评审人"""
    generator = ReportGenerator()
    payload = _build_debug_payload()
    payload["meta"] = {"platform": "reward"}
    payload["sections"] = {
        "项目简介（限1200字）": "[表格表头4] 兔球虫病是一类由艾美耳属兔球虫引起的寄生性原虫病。",
        "重要科学发现": (
            "[表格表头6] 序号 | 主要发现点 | 证明材料 | 所属学科 "
            "[表格行23] 序号:1 ; 主要发现点:发现了一种新的兔艾美耳球虫 ; 证明材料:1.1.1 ; 所属学科:家畜寄生虫学"
        ),
        "代表性论文(专著)目录（不超过6篇）": (
            "[表格表头8] 序号 | 论文（专著） 名称 | 发表刊物 (出版社) | 发表（出版）时间（年月日） | 他引总次数 | 检索数据库 | 所支持发现点 "
            "[表格行26] 序号:1 ; 论文（专著） 名称:A new species of Eimeria ; 发表刊物 (出版社):Parasitology Research ; "
            "发表（出版）时间（年月日）:2024-01-01 ; 他引总次数:4 ; 检索数据库:SCI ; 所支持发现点:1"
        ),
        "客观评价（不超过2页）": "客观评价内容。",
    }
    payload["page_chunks"] = [
        {
            "id": 1,
            "file": "reward.docx",
            "page": 2,
            "section": "项目简介（限1200字）",
            "text": "无关开头。" * 40 + "兔球虫病是一类由艾美耳属兔球虫引起的寄生性原虫病。" + "无关结尾。" * 40,
        },
        {
            "id": 2,
            "file": "reward.docx",
            "page": 3,
            "section": "重要科学发现",
            "text": "发现了一种新的兔艾美耳球虫，证明材料为1.1.1。",
        },
        {
            "id": 3,
            "file": "reward.docx",
            "page": 4,
            "section": "代表性论文",
            "text": "A new species of Eimeria 发表刊物 Parasitology Research。",
        },
    ]

    html = generator.build_html(payload, debug_mode=False)

    assert "[表格表头" not in html
    assert "[表格行" not in html
    assert "兔球虫病是一类由艾美耳属兔球虫引起的寄生性原虫病。" in html
    assert "1. 发现了一种新的兔艾美耳球虫" in html
    assert "证明材料：1.1.1" in html
    assert "A new species of Eimeria" in html
    assert "发表刊物 (出版社)：Parasitology Research" in html
    assert "核心贡献" in html
    assert "成果支撑" in html
    assert "兔球虫病是一类由艾美耳属兔球虫引起的寄生性原虫病" in html
    assert "证据：" in html
    assert 'class="inline-citation"' in html
    assert 'data-file="reward.docx"' in html
    overview_html = html.split('id="report-overview"', 1)[1].split('id="report-dimensions"', 1)[0]
    assert 'class="jump-link-row"' not in overview_html
    visible_evidence = overview_html.split('data-highlight-text="', 1)[0]
    assert ("无关开头。" * 20) not in visible_evidence
    assert ("无关开头。" * 20) not in overview_html
    assert ("无关结尾。" * 20) not in overview_html


def test_report_generator_reward_core_contribution_filters_background_sentences():
    """奖励核心贡献不应展示疾病背景、行业现状或研究热点句"""
    generator = ReportGenerator()
    payload = _build_debug_payload()
    payload["meta"] = {"platform": "reward"}
    payload["sections"] = {
        "项目简介（限1200字）": (
            "兔球虫病危害较严重。"
            "尽管化学药物是目前控制兔球虫病的常用手段，但随着耐药虫株的不断出现和化学药物残留问题的日益凸现，"
            "越来越多的学者寻求用免疫学方法来防控该病，使得活疫苗接种在不久的将来成为控制球虫病的主要措施，"
            "兔球虫诸多方面的研究逐渐成为热点。"
            "本项目首先进行虫种调查，在调查基础上，然后对致病性强的优势虫种进行早熟选育。"
            "成功分离出大型艾美耳球虫、黄艾美耳球虫、肠艾美耳球虫、中型艾美耳球虫及穿孔艾美耳球虫。"
        ),
        "重要科学发现": "",
        "客观评价（不超过2页）": "",
        "代表性论文(专著)目录（不超过6篇）": "",
    }

    html = generator.build_html(payload, debug_mode=False)
    core_html = html.split("核心贡献", 1)[1].split("重要科学发现", 1)[0]

    assert "尽管化学药物" not in core_html
    assert "研究逐渐成为热点" not in core_html
    assert "本项目首先进行虫种调查" in core_html
    assert "成功分离出大型艾美耳球虫" in core_html


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
    payload["meta"] = {
        "reward_local_material_groups": {
            "主材料": [
                {
                    "title": "提名书",
                    "file_name": "demo.pdf",
                    "local_path": "/tmp/demo.pdf",
                }
            ],
            "相关佐证材料": [
                {
                    "title": "成果证明材料",
                    "file_name": "proof.pdf",
                    "local_path": "/tmp/proof.pdf",
                }
            ],
        }
    }
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
            },
            {
                "source_file": "/tmp/proof.pdf",
                "source_name": "proof.pdf",
                "source_kind": "support",
                "start_page": 4,
                "end_page": 5,
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
    assert 'class="doc-local-nav"' in html
    assert 'class="doc-nav-group"' in html
    assert "文件导航" in html
    assert "主材料" in html
    assert "相关佐证材料" in html
    assert "提名书" in html
    assert "01. 成果证明材料" in html
    assert 'data-packet-nav="true"' in html
    assert 'data-packet-page="4"' in html
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
