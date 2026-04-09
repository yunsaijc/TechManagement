"""评审报告生成器测试"""
from pathlib import Path

from src.services.evaluation.parsers import DocumentParser
from src.services.evaluation.scorers.report_generator import ReportGenerator


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
    assert 'id="document-rail"' in html
    assert 'id="result-tabs"' in html
    assert 'data-tab-target="report-chat"' in html
    assert 'id="report-chat"' in html
    assert 'id="chat-form"' in html
    assert "/api/v1/evaluation/chat/ask" in html
    assert 'data-evaluation-id="EVAL_DEMO"' in html
    assert "http://127.0.0.1:8888" in html
    assert "研究目标是什么" in html
    assert 'id="dimension-accordion"' in html
    assert 'class="score-item is-open"' in html
    assert "风险控制" in html
    assert 'class="content-grid workspace-layout"' in html
    assert "hero-nav" not in html


def test_report_generator_debug_html_hides_interactive_chat_panel():
    """调试报告不应渲染交互式聊天面板"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=True)

    assert "专家即时问答" not in html
    assert 'id="report-chat"' not in html
    assert 'id="document-rail"' not in html
    assert 'id="result-tabs"' not in html


def test_report_generator_dimension_accordion_opens_lowest_score_by_default():
    """维度评分应默认展开最低分项，避免整屏平铺"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=False)

    risk_index = html.find("风险控制")
    innovation_index = html.find("创新性")
    first_open_index = html.find('class="score-item is-open"')

    assert first_open_index != -1
    assert risk_index != -1 and innovation_index != -1
    assert abs(first_open_index - risk_index) < abs(first_open_index - innovation_index)


def test_report_generator_chat_panel_allows_first_ask_when_chat_not_ready():
    """未预构建索引时也应允许提问，由后端首问自动重建"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(chat_ready=False), debug_mode=False)

    assert "可直接提问，系统会在首问时自动尝试构建索引" in html
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
    debug_json.write_text(__import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "demo.pdf").write_bytes(b"fake")

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

    assert 'id="doc-page-3"' in html
    assert "自动补齐的正文内容" in html
    assert '"page_chunks"' in updated_json


def test_report_generator_build_from_debug_file_injects_workspace_project_nav(
    tmp_path: Path,
    monkeypatch,
):
    """正式报告应在左侧注入同目录项目切换栏，但不影响单项目主体结构"""
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
    debug_json.write_text(__import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "demo.pdf").write_bytes(b"fake")

    other_payload = _build_debug_payload()
    other_payload["result"]["project_id"] = "another-project"
    other_payload["result"]["project_name"] = "另一个项目"
    (tmp_path / "EVAL_another-project.json").write_text(
        __import__("json").dumps(other_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    async def fake_parse(self, file_path: str, source_name: str = ""):
        return {
            "page_chunks": payload["page_chunks"],
            "meta": payload["meta"],
        }

    monkeypatch.setattr(DocumentParser, "parse", fake_parse)

    generator.build_from_debug_file(debug_json, output_html, debug_mode=False)

    html = output_html.read_text(encoding="utf-8")
    assert 'id="project-rail"' in html
    assert "另一个项目" in html
    assert 'href="EVAL_another-project.html"' in html
    assert 'id="document-rail"' in html
    assert 'id="report-chat"' in html


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
