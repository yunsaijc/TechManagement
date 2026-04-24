"""技术摸底测试"""
from pathlib import Path

import pytest
import requests

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
async def test_benchmark_analyzer_uses_project_title_as_aux_query_when_results_sparse():
    """主查询结果过少时，应使用项目名称做一次辅助检索并合并结果"""
    seen_queries = []

    async def fake_tech_search(query: str, top_k: int):
        seen_queries.append(query)
        if len(seen_queries) == 1:
            return [
                {
                    "type": "literature",
                    "title": "数字技术在创伤骨科的应用 临床数字骨科（一）",
                    "snippet": "围绕骨科临床数字化展开。",
                    "year": 2011,
                    "score": 15.0,
                }
            ]
        return [
            {
                "type": "literature",
                "title": "智能与数字化技术在骨科领域的应用及临床研究",
                "snippet": "围绕骨科数字化和临床研究展开。",
                "year": 2022,
                "score": 18.0,
            }
        ]

    analyzer = BenchmarkAnalyzer(BenchmarkRetriever(ToolGateway(tech_search_handler=fake_tech_search)))

    result, _ = await analyzer.analyze(
        sections={
            "项目名称": "智能与数字化技术在骨科领域的应用及临床研究",
            "项目实施内容、技术路线及创新点": "构建骨科数字化平台并形成临床研究能力。",
        },
        highlights=None,
    )

    assert len(seen_queries) == 2
    assert seen_queries[1] == "智能与数字化技术在骨科领域的应用及临床研究"
    assert len(result.references) == 2


@pytest.mark.asyncio
async def test_evaluation_agent_benchmark_degrades_when_tool_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """未配置 tech_search 时应降级返回 benchmark 结果并标记 partial"""
    monkeypatch.setenv("EVALUATION_OPENALEX_ENABLED", "0")
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


def test_benchmark_analyzer_builds_query_from_fuzzy_section_titles():
    """未命中标准章节名时，应按章节关键词兜底构造查询"""
    analyzer = BenchmarkAnalyzer(BenchmarkRetriever(ToolGateway()))

    query = analyzer._build_query(
        sections={
            "概述": "项目围绕骨科数字化临床场景开展研究。",
            "项目实施内容、技术路线及创新点": "构建骨科数字化平台，形成临床研究与智能辅助诊疗能力。",
            "项目实施的预期经济社会效益目标": "提升基层骨科诊疗效率，形成推广应用价值。",
            "项目预算表": "预算信息不应进入检索词。",
        },
        highlights=None,
    )

    assert "骨科数字化平台" in query
    assert "临床研究与智能辅助诊疗能力" in query
    assert "提升基层骨科诊疗效率" in query
    assert "预算信息" not in query


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
        assert params["per-page"] == 10
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
            "score": 13.0,
        }
    ]


def test_openalex_search_client_retries_with_compact_query(monkeypatch: pytest.MonkeyPatch):
    """原始长查询无结果时，应自动收缩为关键词查询再试一次"""
    monkeypatch.setenv("EVALUATION_OPENALEX_ENABLED", "1")

    seen_queries = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        seen_queries.append(params["search"])
        if len(seen_queries) == 1:
            return FakeResponse({"results": []})
        return FakeResponse(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W3",
                            "display_name": "骨科机器人手术诊疗 compact query result",
                            "publication_year": 2023,
                        }
                    ]
                }
            )

    monkeypatch.setattr("src.services.evaluation.tools.search_client.requests.get", fake_get)

    client = EvaluationSearchClient()
    long_query = (
        "本项目通过智能和数字化技术研究与应用提升骨科领域诊疗水平并形成机器人辅助手术能力，"
        "并进一步建设数字化临床诊疗体系和医学影像导航平台，"
        "持续完善骨科专科数据库、临床决策支持系统、围手术期管理能力和基层推广应用路径。"
    )
    results = client._search_openalex(
        long_query,
        3,
    )

    assert len(seen_queries) == 2
    assert seen_queries[0] == long_query
    assert seen_queries[1] == "骨科 临床 机器人 手术 诊疗 医学"
    assert results[0]["title"] == "骨科机器人手术诊疗 compact query result"


def test_openalex_search_client_retries_compact_query_after_timeout(monkeypatch: pytest.MonkeyPatch):
    """原始查询超时后，应继续尝试紧凑查询，而不是直接降级失败"""
    monkeypatch.setenv("EVALUATION_OPENALEX_ENABLED", "1")

    seen_queries = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W3",
                        "display_name": "骨科机器人手术诊疗 compact query result",
                        "publication_year": 2023,
                    }
                ]
            }

    def fake_get(url, params, timeout):
        seen_queries.append(params["search"])
        if len(seen_queries) == 1:
            raise requests.Timeout("first query timeout")
        assert "select" in params
        return FakeResponse()

    monkeypatch.setattr("src.services.evaluation.tools.search_client.requests.get", fake_get)

    client = EvaluationSearchClient()
    results = client._search_openalex(
        "本项目通过智能和数字化技术研究与应用提升骨科领域诊疗水平并形成机器人辅助手术能力",
        3,
    )

    assert len(seen_queries) == 2
    assert seen_queries[1] != seen_queries[0]
    assert all(term in seen_queries[1].split() for term in ["骨科", "机器人", "手术", "诊疗", "数字化", "智能"])
    assert results[0]["title"] == "骨科机器人手术诊疗 compact query result"


def test_openalex_search_client_compacts_short_chinese_sentence_into_terms():
    """即便查询未超过 80 字，也不应把整句中文当成单个检索词"""
    client = EvaluationSearchClient()

    query = "通过创新驱动，通过智能和数字化技术研究与应用，提升骨科领域诊疗水平和患者满意度"

    compact_query = client._build_compact_query(query)
    assert compact_query != query
    assert compact_query.startswith("骨科 诊疗 数字化 智能")
    assert client._extract_query_terms(query)[:4] == ["骨科", "诊疗", "数字化", "智能"]


def test_openalex_search_client_falls_back_to_openalex_results_when_local_rerank_is_too_strict():
    """本地重排全军覆没时，至少保留 OpenAlex 原始高相关结果，避免技术摸底整块空掉"""
    client = EvaluationSearchClient()
    items = [
        {
            "type": "literature",
            "source": "openalex",
            "title": "Orthopedic surgical robotics and digital navigation",
            "snippet": "Clinical diagnosis imaging workflow and robotic surgery.",
            "year": 2024,
            "url": "https://openalex.org/W10",
            "score": 18.2,
        }
    ]

    results = client._rerank_and_filter_results(
        items,
        "通过创新驱动，通过智能和数字化技术研究与应用，提升骨科领域诊疗水平和患者满意度",
        3,
    )

    assert len(results) == 1
    assert results[0]["title"] == "Orthopedic surgical robotics and digital navigation"


def test_openalex_search_client_filters_noisy_results_after_rerank():
    """应优先保留高相关文献，并过滤明显噪声条目"""
    client = EvaluationSearchClient()
    items = [
        {
            "type": "literature",
            "source": "openalex",
            "title": "数字技术在创伤骨科的应用 临床数字骨科（一）",
            "snippet": "涉及骨科、临床诊疗、机器人辅助手术与医学影像。",
            "year": 2011,
            "url": "https://openalex.org/W1",
            "score": 15.3,
        },
        {
            "type": "literature",
            "source": "openalex",
            "title": "ESPnet2 pretrained model, xxx",
            "snippet": "Python API model zoo recipe in espnet",
            "year": 2021,
            "url": "https://openalex.org/W2",
            "score": 20.0,
        },
        {
            "type": "literature",
            "source": "openalex",
            "title": "1例以消化道症状为主诉的高龄原发性甲状旁腺功能亢进症患者的护理",
            "snippet": "围绕内分泌护理与消化道症状管理展开。",
            "year": 2012,
            "url": "https://openalex.org/W3",
            "score": 11.8,
        },
    ]

    results = client._rerank_and_filter_results(items, "骨科 临床 机器人 手术 诊疗 医疗", 3)

    assert len(results) == 1
    assert results[0]["title"] == "数字技术在创伤骨科的应用 临床数字骨科（一）"


def test_openalex_search_client_filters_obvious_cjk_topic_mismatch():
    """中文结果若与中文查询主题完全不沾边，应直接过滤"""
    client = EvaluationSearchClient()
    items = [
        {
            "type": "literature",
            "source": "openalex",
            "title": "药物发现领域有哪些推荐的文献检索工具?",
            "snippet": "围绕创新药情报检索与药物发现工具展开。",
            "year": 2025,
            "url": "https://openalex.org/W2",
            "score": 20.0,
        },
        {
            "type": "literature",
            "source": "openalex",
            "title": "数字技术在创伤骨科的应用 临床数字骨科（一）",
            "snippet": "涉及骨科、临床诊疗、机器人辅助手术与医学影像。",
            "year": 2011,
            "url": "https://openalex.org/W1",
            "score": 15.3,
        },
    ]

    results = client._rerank_and_filter_results(items, "骨科 临床 机器人 手术 诊疗 医疗", 3)

    assert len(results) == 1
    assert results[0]["title"] == "数字技术在创伤骨科的应用 临床数字骨科（一）"


def test_openalex_search_client_does_not_return_raw_noisy_fallback(monkeypatch: pytest.MonkeyPatch):
    """若候选结果全部被过滤，不应再回退到原始噪声结果"""
    monkeypatch.setenv("EVALUATION_OPENALEX_ENABLED", "1")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W2",
                        "display_name": "药物发现领域有哪些推荐的文献检索工具?",
                        "publication_year": 2025,
                        "relevance_score": 20.0,
                    },
                    {
                        "id": "https://openalex.org/W3",
                        "display_name": "ESPnet2 pretrained model, xxx",
                        "publication_year": 2021,
                        "relevance_score": 19.0,
                    },
                ]
            }

    monkeypatch.setattr("src.services.evaluation.tools.search_client.requests.get", lambda *args, **kwargs: FakeResponse())

    client = EvaluationSearchClient()
    results = client._search_openalex("智能与数字化技术在骨科领域的应用及临床研究", 4)

    assert results == []


@pytest.mark.asyncio
async def test_openalex_search_client_reuses_cached_results(monkeypatch: pytest.MonkeyPatch):
    """相同查询应复用缓存，避免重复请求 OpenAlex"""
    monkeypatch.setenv("EVALUATION_OPENALEX_ENABLED", "1")

    calls = {"count": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W2",
                        "display_name": "Cached result",
                        "publication_year": 2025,
                    }
                ]
            }

    def fake_get(url, params, timeout):
        calls["count"] += 1
        return FakeResponse()

    monkeypatch.setattr("src.services.evaluation.tools.search_client.requests.get", fake_get)

    client = EvaluationSearchClient()
    first = await client.tech_search("cached query", 5)
    second = await client.tech_search("cached   query", 5)

    assert first == second
    assert calls["count"] == 1
