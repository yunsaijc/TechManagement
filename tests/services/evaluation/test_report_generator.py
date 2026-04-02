"""评审报告生成器测试"""
from src.services.evaluation.scorers.report_generator import ReportGenerator


def _build_debug_payload(chat_ready: bool = True) -> dict:
    """构造最小调试载荷"""
    return {
        "source_name": "demo.pdf",
        "sections": {"项目简介": "项目目标：建设智能化服务平台。"},
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

    assert "专家即时问答" in html
    assert 'id="report-chat"' in html
    assert 'id="chat-form"' in html
    assert "/api/v1/evaluation/chat/ask" in html
    assert 'data-evaluation-id="EVAL_DEMO"' in html
    assert "http://127.0.0.1:8888" in html
    assert "研究目标是什么" in html
    assert 'id="dimension-accordion"' in html
    assert 'class="score-item is-open"' in html
    assert "风险控制" in html


def test_report_generator_debug_html_hides_interactive_chat_panel():
    """调试报告不应渲染交互式聊天面板"""
    generator = ReportGenerator()

    html = generator.build_html(_build_debug_payload(), debug_mode=True)

    assert "专家即时问答" not in html
    assert 'id="report-chat"' not in html


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
