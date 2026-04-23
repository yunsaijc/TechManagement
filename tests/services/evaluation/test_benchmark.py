"""技术摸底测试"""
from pathlib import Path

import pytest

from src.common.models.evaluation import EvaluationRequest, StructuredHighlights
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.benchmark import BenchmarkAnalyzer, BenchmarkRetriever
from src.services.evaluation.storage.storage import EvaluationStorage
from src.services.evaluation.tools.gateway import ToolGateway
from src.services.evaluation.tools.search_client import EvaluationSearchClient


@pytest.mark.asyncio
async def test_benchmark_retriever_maps_tool_results():
    """检索器应把工具结果映射为标准参考条目"""

    async def fake_tech_search(query: str, top_k: int):
        assert "多模态" in query
        assert top_k == 3
        return [
            {
                "type": "literature",
                "title": "多模态科普交互系统研究",
                "snippet": "围绕智能问答与交互展示展开。",
                "year": "2024",
                "url": "https://example.com/paper",
                "score": "0.91",
            },
            {
                "source": "patent",
                "title": "一种智能问答科普平台",
                "abstract": "涉及知识组织与交互问答。",
                "year": 2023,
                "score": 0.76,
            },
        ]

    retriever = BenchmarkRetriever(ToolGateway(tech_search_handler=fake_tech_search))

    references = await retriever.retrieve("多模态 智能问答", top_k=3)

    assert len(references) == 2
    assert references[0].source == "literature"
    assert references[0].year == 2024
    assert references[0].score == 0.91
    assert references[1].source == "patent"
    assert references[1].snippet == "涉及知识组织与交互问答。"


@pytest.mark.asyncio
async def test_benchmark_analyzer_builds_result_from_references():
    """分析器在有检索结果时应返回结论与证据"""

    async def fake_tech_search(query: str, top_k: int):
        assert "原创" in query
        return [
            {
                "type": "literature",
                "title": "原创智能问答研究综述",
                "snippet": "聚焦多模态问答与场景化应用。",
                "year": 2025,
                "score": 0.95,
            },
            {
                "type": "literature",
                "title": "科普平台交互式知识服务研究",
                "snippet": "讨论知识组织、反馈闭环与应用推广。",
                "year": 2024,
                "score": 0.88,
            },
            {
                "type": "patent",
                "title": "一种多模态知识问答平台",
                "snippet": "涉及智能检索与人机交互。",
                "year": 2025,
                "score": 0.73,
            },
        ]

    analyzer = BenchmarkAnalyzer(
        BenchmarkRetriever(ToolGateway(tech_search_handler=fake_tech_search)),
        patent_search_enabled=True,
    )
    highlights = StructuredHighlights(
        research_goals=["构建原创多模态智能问答平台"],
        innovations=["形成原创交互机制", "突破知识服务闭环"],
        technical_route=[],
    )

    result, evidence = await analyzer.analyze(
        sections={
            "研究目标": "项目拟原创突破多模态智能问答关键能力。",
            "创新点": "形成原创交互机制与知识服务闭环。",
        },
        highlights=highlights,
    )

    assert result.references
    assert result.novelty_level in {"medium_high", "high"}
    assert "已检索到 2 条相关文献" in result.literature_position
    assert "存在部分专利交叉" in result.patent_overlap
    assert evidence
    assert evidence[0].source == "tech_search"


@pytest.mark.asyncio
async def test_evaluation_agent_benchmark_degrades_when_tool_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """未配置 tech_search 时应降级返回 benchmark 结果并标记 partial"""
    agent = EvaluationAgent(llm=object())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    async def fake_run_checks(sections, dimensions, profile_result):
        return []

    monkeypatch.setattr(agent, "_run_checks", fake_run_checks)

    request = EvaluationRequest(
        project_id="benchmark-fallback",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=True,
        enable_chat_index=False,
    )

    result = await agent.evaluate(
        request=request,
        content={
            "sections": {
                "项目简介": "拟建设科普智能问答平台。",
                "研究目标": "形成可推广的智能问答服务能力。",
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
    assert result.benchmark is not None
    assert result.benchmark.novelty_level == "unknown"
    assert result.benchmark.literature_position == "技术摸底工具不可用"
    assert result.benchmark.patent_overlap == "专利对比待接入"
    assert result.benchmark.conclusion == "当前仅基于申报书内容，外部对比结论待补充"
    assert result.errors
    assert result.errors[0].code == "TOOL_UNAVAILABLE"
    assert result.errors[0].module == "benchmark"


def test_openalex_search_client_maps_works(monkeypatch: pytest.MonkeyPatch):
    """OpenAlex 结果应映射为统一论文条目"""
    monkeypatch.setenv("EVALUATION_OPENALEX_ENABLED", "1")
    monkeypatch.setenv("EVALUATION_OPENALEX_MAILTO", "review@example.com")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "Graph neural networks for scheduling",
                        "publication_year": 2024,
                        "relevance_score": 9.5,
                        "abstract_inverted_index": {
                            "Graph": [0],
                            "methods": [1],
                            "improve": [2],
                            "scheduling": [3],
                        },
                    }
                ]
            }

    def fake_get(url, params, timeout):
        assert url == "https://api.openalex.org/works"
        assert params["search"] == "graph scheduling"
        assert params["per-page"] == 3
        assert params["mailto"] == "review@example.com"
        assert timeout == 12.0
        return FakeResponse()

    monkeypatch.setattr("src.services.evaluation.tools.search_client.requests.get", fake_get)

    client = EvaluationSearchClient()
    results = client._search_openalex("graph scheduling", 3)

    assert results == [
        {
            "type": "literature",
            "source": "openalex",
            "title": "Graph neural networks for scheduling",
            "snippet": "Graph methods improve scheduling",
            "year": 2024,
            "url": "https://openalex.org/W1",
            "score": 9.5,
        }
    ]
