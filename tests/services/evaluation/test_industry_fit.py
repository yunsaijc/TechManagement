"""产业指南贴合测试"""
from pathlib import Path

import pytest

from src.common.models.evaluation import EvaluationRequest
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.highlight import IndustryFitAnalyzer
from src.services.evaluation.storage.storage import EvaluationStorage
from src.services.evaluation.tools.gateway import ToolGateway


@pytest.mark.asyncio
async def test_industry_fit_analyzer_builds_result_and_evidence():
    """指南检索正常时应生成匹配、差距、建议与证据"""

    async def fake_guide_search(query: str, top_k: int):
        assert "人工智能" in query
        assert top_k == 6
        return [
            {"title": "新一代信息技术", "source": "guide-2025", "page": 12},
            {"title": "人工智能应用创新", "source": "guide-2025", "page": 18},
        ]

    analyzer = IndustryFitAnalyzer(ToolGateway(guide_search_handler=fake_guide_search))

    result, evidence = await analyzer.analyze(
        sections={
            "研究目标": "围绕人工智能问答与科普服务建设平台。",
            "经济效益": "形成长期运营能力。",
        },
        page_chunks=[
            {
                "file": "demo.pdf",
                "page": 6,
                "section": "应用场景",
                "text": "项目应用于基层科普服务与产业推广场景。",
            }
        ],
        query_text="人工智能 科普服务 平台建设",
    )

    assert result.matched
    assert "新一代信息技术" in result.matched
    assert result.fit_score > 0
    assert any("量产路径" in gap for gap in result.gaps)
    assert any("量产计划" in item for item in result.suggestions)
    assert evidence
    assert evidence[0].source == "guide_search"


@pytest.mark.asyncio
async def test_evaluation_agent_industry_fit_degrades_when_tool_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """未配置 guide_search 时应降级返回 industry_fit 结果并标记 partial"""
    agent = EvaluationAgent(llm=object())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    async def fake_run_checks(sections, dimensions):
        return []

    monkeypatch.setattr(agent, "_run_checks", fake_run_checks)

    request = EvaluationRequest(
        project_id="industry-fit-fallback",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=True,
        enable_benchmark=False,
        enable_chat_index=False,
    )

    result = await agent.evaluate(
        request=request,
        content={
            "sections": {
                "项目简介": "围绕人工智能平台开展科普服务。",
                "研究目标": "形成可推广的数字化服务能力。",
            },
            "page_chunks": [],
            "meta": {
                "file_name": "demo.pdf",
                "page_count": 1,
                "parser_version": "test",
                "page_estimated": False,
            },
        },
        source_name="demo.pdf",
    )

    assert result.partial is True
    assert result.industry_fit is not None
    assert result.industry_fit.fit_score == 0.0
    assert result.industry_fit.gaps == ["产业指南检索不可用，结果待核验"]
    assert result.industry_fit.suggestions == ["待检索工具恢复后补充指南映射"]
    assert result.errors
    assert result.errors[0].code == "TOOL_UNAVAILABLE"
    assert result.errors[0].module == "industry_fit"
