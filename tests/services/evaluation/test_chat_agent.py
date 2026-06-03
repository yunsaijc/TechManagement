"""聊天问答测试"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common.models.evaluation import EvaluationRequest
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.chat import qa_agent as qa_agent_module
from src.services.evaluation.chat.qa_agent import EvaluationQAAgent
from src.services.evaluation.storage.storage import EvaluationStorage


class BrokenLLM:
    """始终失败的模型，用于验证降级路径"""

    async def ainvoke(self, prompt):
        raise RuntimeError("Connection error")


class StreamingChunk:
    """最小流式 chunk 替身"""

    def __init__(self, content: str):
        self.content = content


class StreamingLLM:
    """支持流式输出的模型替身"""

    async def ainvoke(self, prompt):
        return StreamingChunk("结论：研究目标明确。\n依据：\n1. 建设智能化科普咨询平台。\n不足：量化指标仍需补充。")

    async def astream(self, prompt):
        for part in [
            "结论：研究目标明确。\n",
            "依据：\n1. 建设智能化科普咨询平台。\n",
            "不足：量化指标仍需补充。",
        ]:
            yield StreamingChunk(part)


class NativeCompatibleLLM:
    """模拟默认 LangChain 模型，用于触发原生兼容客户端分支"""


NativeCompatibleLLM.__module__ = "langchain_openai.chat_models.base"


class FakeNativeCompletion:
    """最小原生 completion 响应"""

    def __init__(self, content: str):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]


class FakeNativeStream:
    """最小原生流式响应"""

    def __init__(self, parts: list[str]):
        self.parts = parts

    def __aiter__(self):
        async def generator():
            for part in self.parts:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=part))])

        return generator()


class FakeNativeClient:
    """最小原生兼容客户端"""

    def __init__(self, content: str, stream_parts: list[str]):
        self.content = content
        self.stream_parts = stream_parts
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeNativeStream(self.stream_parts)
        return FakeNativeCompletion(self.content)


@pytest.mark.asyncio
async def test_evaluation_agent_chat_index_and_ask_degrades_without_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """开启聊天索引后，应能在 LLM 异常时仍返回引用结果"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {
            "项目简介": "建设目标：开展线上线下科普活动，开发 AI 智能问答平台。",
            "项目目的和意义": "目的：解决现有科普载体单一问题，建设智能化科普咨询平台。",
        },
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 4,
                "section": "项目简介",
                "text": "项目简介\n建设目标\n1、开展线上线下科普活动。\n2、开发 AI 智能问答平台。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目目的和意义",
                "text": "目的：解决现有科普载体单一问题，建设智能化科普咨询平台。",
            },
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 2,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-project",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )

    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")

    assert result.chat_ready is True

    answer = await agent.ask(result.evaluation_id, "这个项目的研究目标是什么？")

    assert answer.answer
    assert answer.citations
    assert answer.citations[0].file == "demo.pdf"
    assert answer.citations[0].page in {4, 5}


@pytest.mark.asyncio
async def test_evaluation_agent_ask_requires_existing_chat_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """评审记录存在但未构建聊天索引时，应返回明确错误"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {"项目简介": "建设目标：建设智能化科普咨询平台。"},
        "page_chunks": [],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 1,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-project-no-chat",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=False,
    )
    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")

    with pytest.raises(ValueError, match="该评审记录未构建聊天索引"):
        await agent.ask(result.evaluation_id, "研究目标是什么？")


@pytest.mark.asyncio
async def test_evaluation_agent_ask_auto_rebuilds_chat_index_from_debug_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """缺少索引时应自动重建，并正常返回回答与引用"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {"项目简介": "项目目标：建设智能化科普咨询平台。"},
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 6,
                "section": "项目简介",
                "text": "项目简介\n项目目标：建设智能化科普咨询平台。",
            }
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 1,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-project-rebuild",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=False,
    )
    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")

    monkeypatch.setattr(
        agent,
        "_load_debug_payload",
        lambda project_id: {
            "evaluation_id": result.evaluation_id,
            "page_chunks": content["page_chunks"],
            "meta": {"file_path": ""},
        },
    )

    answer = await agent.ask(result.evaluation_id, "这个项目的研究目标是什么？")

    assert answer.answer
    assert answer.citations
    assert answer.citations[0].file == "demo.pdf"
    assert answer.citations[0].page == 6

    rebuilt_index = await agent.storage.load_chat_index(result.evaluation_id)
    assert rebuilt_index is not None
    assert rebuilt_index.get("chunk_count", 0) > 0

    refreshed_result = await agent.storage.get_by_evaluation_id(result.evaluation_id)
    assert refreshed_result is not None
    assert refreshed_result.chat_ready is True


@pytest.mark.asyncio
async def test_evaluation_agent_resolve_chat_citation_highlight_supports_lazy_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """聊天引用高亮应支持独立懒加载，避免 ask 主链路同步补全"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {"项目简介": "项目目标：建设智能化科普咨询平台。"},
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 6,
                "section": "项目简介",
                "text": "项目简介\n项目目标：建设智能化科普咨询平台。",
            }
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 1,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-chat-highlight",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )
    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")

    monkeypatch.setattr(
        agent,
        "_load_debug_payload",
        lambda project_id: {
            "packet_assets": {
                "page_map": [
                    {
                        "source_name": "demo.pdf",
                        "source_file": "/tmp/demo.pdf",
                        "source_kind": "proposal",
                        "start_page": 10,
                        "end_page": 12,
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        agent.report_generator,
        "_resolve_packet_jump_payload",
        lambda packet_assets, source_file, page, snippet: {
            "packet_page": 12,
            "highlight_rects": [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}],
        },
    )

    answer = await agent.ask(result.evaluation_id, "这个项目的研究目标是什么？")

    assert answer.citations
    assert answer.citations[0].packet_page == 0
    assert answer.citations[0].highlight_rects == []

    highlight = await agent.resolve_chat_citation_highlight(
        evaluation_id=result.evaluation_id,
        file=answer.citations[0].file,
        page=answer.citations[0].page,
        snippet=answer.citations[0].snippet,
    )

    assert highlight.packet_page == 12
    assert highlight.highlight_rects == [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}]


@pytest.mark.asyncio
async def test_evaluation_agent_ask_reuses_in_memory_result_and_chat_index_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """同一进程内重复提问时，应优先复用内存缓存而不是重新读存储"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {"项目简介": "项目目标：建设智能化科普咨询平台。"},
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 6,
                "section": "项目简介",
                "text": "项目简介\n项目目标：建设智能化科普咨询平台。",
            }
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 1,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-cache",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )
    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")

    async def fail_get_by_evaluation_id(evaluation_id: str):
        raise AssertionError("不应重新扫描评审结果目录")

    async def fail_load_chat_index(evaluation_id: str):
        raise AssertionError("不应重新读取聊天索引 JSON")

    monkeypatch.setattr(agent.storage, "get_by_evaluation_id", fail_get_by_evaluation_id)
    monkeypatch.setattr(agent.storage, "load_chat_index", fail_load_chat_index)

    answer = await agent.ask(result.evaluation_id, "这个项目的研究目标是什么？")

    assert answer.answer
    assert answer.citations


@pytest.mark.asyncio
async def test_evaluation_agent_build_expert_qna_reuses_existing_chat_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """典型问答应复用已生成的聊天索引，避免重复 build"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))

    page_chunks = [
        {
            "id": 1,
            "file": "demo.pdf",
            "page": 6,
            "section": "项目简介",
            "text": "项目简介\n项目目标：建设智能化科普咨询平台。",
        }
    ]

    call_count = {"count": 0}
    original_build = agent.chat_indexer.build

    def counting_build(evaluation_id: str, page_chunks):
        call_count["count"] += 1
        return original_build(evaluation_id=evaluation_id, page_chunks=page_chunks)

    monkeypatch.setattr(agent.chat_indexer, "build", counting_build)

    await agent._run_chat_index("EVAL_CACHE_DEMO", page_chunks)
    qna = await agent._build_expert_qna("EVAL_CACHE_DEMO", page_chunks)

    assert qna
    assert call_count["count"] == 1


@pytest.mark.asyncio
async def test_evaluation_agent_ask_stream_returns_delta_and_done_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """流式问答应先返回 delta，再返回 done 与 citations"""
    agent = EvaluationAgent(llm=StreamingLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {"项目简介": "项目目标：建设智能化科普咨询平台。"},
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 6,
                "section": "项目简介",
                "text": "项目简介\n项目目标：建设智能化科普咨询平台。",
            }
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 1,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-stream",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )
    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")

    events = [
        event
        async for event in agent.ask_stream(
            evaluation_id=result.evaluation_id,
            question="这个项目的研究目标是什么？",
        )
    ]

    assert events
    assert events[0]["event"] == "status"
    assert any(event["event"] == "delta" for event in events)
    assert events[-1]["event"] == "done"
    assert "研究目标明确" in events[-1]["answer"]
    assert events[-1]["citations"]


@pytest.mark.asyncio
async def test_qa_agent_native_qwen_path_disables_thinking_and_returns_structured_answer(
    monkeypatch: pytest.MonkeyPatch,
):
    """qwen 热路径应走原生兼容客户端，并显式关闭 thinking"""
    monkeypatch.setattr(qa_agent_module.llm_config, "provider", "qwen")
    monkeypatch.setattr(qa_agent_module.llm_config, "model", "qwen3.5-flash")
    monkeypatch.setattr(qa_agent_module.llm_config, "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(qa_agent_module.llm_config, "api_key", "test-key")
    monkeypatch.setattr(qa_agent_module.llm_config, "max_tokens", 4096)
    monkeypatch.setattr(qa_agent_module.llm_config, "timeout", 30.0)

    fake_client = FakeNativeClient(
        content="结论：研究目标明确。\n依据：\n1. 建设智能化科普咨询平台。\n不足：量化指标仍需补充。",
        stream_parts=[
            "结论：研究目标明确。\n",
            "依据：\n1. 建设智能化科普咨询平台。\n",
            "不足：量化指标仍需补充。",
        ],
    )
    monkeypatch.setattr(qa_agent_module.EvaluationQAAgent, "_build_native_client", lambda self, llm: fake_client)

    agent = EvaluationQAAgent(llm=NativeCompatibleLLM())
    index_payload = agent.indexer.build(
        evaluation_id="EVAL_NATIVE",
        page_chunks=[
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目简介",
                "text": "项目目标：建设智能化科普咨询平台。",
            }
        ],
    )

    answer = await agent.ask("这个项目的研究目标是什么？", index_payload=index_payload)

    assert "结论：" in answer.answer
    assert fake_client.calls
    assert fake_client.calls[0]["extra_body"]["enable_thinking"] is False
    assert fake_client.calls[0]["max_tokens"] == 220


@pytest.mark.asyncio
async def test_evaluation_agent_ask_validation_data_stays_cautious(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证数据问题在缺少直接证据时应保持谨慎，并返回引用"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {
            "项目绩效评价考核目标及指标": "总体目标：创作优质科普内容20件，吸引阅读量超过10万次。",
            "项目简介": "建设目标：开发 AI 智能问答平台，开展科普活动。",
        },
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 11,
                "section": "项目绩效评价考核目标及指标",
                "text": "项目绩效评价考核目标及指标\n总体目标：创作优质科普内容20件，吸引阅读量超过10万次。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 4,
                "section": "项目简介",
                "text": "项目简介\n建设目标：开发 AI 智能问答平台，开展科普活动。",
            },
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 2,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-validation",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )

    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")
    answer = await agent.ask(result.evaluation_id, "有验证数据吗？")

    assert "未能直接定位到明确的验证数据章节" in answer.answer
    assert answer.citations
    assert answer.citations[0].page == 11


@pytest.mark.asyncio
async def test_evaluation_agent_ask_expected_benefits_extracts_benefit_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """预期效益问题应返回效益相关要点，并命中对应引用"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {
            "合作网络构建": "项目效益：社会效益明显；经济效益体现在品牌建设与推广应用。",
            "普及前景": "模式可复制与推广，可为其他机构提供示范。",
        },
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 7,
                "section": "合作网络构建",
                "text": "合作网络构建\n项目效益：社会效益明显；经济效益体现在品牌建设与推广应用。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 9,
                "section": "普及前景",
                "text": "普及前景\n模式可复制与推广，可为其他机构提供示范。",
            },
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 2,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-benefit",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )

    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")
    answer = await agent.ask(result.evaluation_id, "这项工作有哪些预期效益？")

    assert "效益" in answer.answer
    assert any(keyword in answer.answer for keyword in ("社会效益", "经济效益"))
    assert answer.citations
    assert answer.citations[0].page == 7


@pytest.mark.asyncio
async def test_evaluation_agent_ask_goal_reranks_away_from_kpi_and_instruction_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """研究目标问答应优先引用目标正文，而不是说明页或绩效表"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {
            "填报说明": "项目申报书分为研究内容、进度安排、绩效指标等部分。",
            "项目绩效评价考核目标及指标": "总体目标：完成论文和专利等指标。",
            "项目目的和意义": "目的：建设智能化科普咨询平台，整合资源并提升基层传播能力。",
        },
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 2,
                "section": "填报说明",
                "text": "填报说明\n项目申报书分为研究内容、进度安排、绩效指标等部分。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 9,
                "section": "项目绩效评价考核目标及指标",
                "text": "[表格行1] 总体目标 | 实施期目标\n[表格行2] 完成论文和专利等指标。",
            },
            {
                "id": 3,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目目的和意义",
                "text": "目的：建设智能化科普咨询平台，整合资源并提升基层传播能力。",
            },
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 3,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-goal-rerank",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )

    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")
    answer = await agent.ask(result.evaluation_id, "这个项目的研究目标是什么？")

    assert answer.citations
    assert answer.citations[0].page == 5


@pytest.mark.asyncio
async def test_evaluation_agent_ask_progress_reranks_to_schedule_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """进展问答应优先引用进度安排，而不是说明页"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    content = {
        "sections": {
            "填报说明": "项目申报书分为研究内容、进度安排等部分。",
            "进度安排": "第二年（2026年）：优化系统并开展测试。第三年（2027年）：扩大试点并形成阶段成果。",
        },
        "page_chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 2,
                "section": "填报说明",
                "text": "填报说明\n项目申报书分为研究内容、进度安排等部分。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 14,
                "section": "进度安排",
                "text": "第二年（2026年）：优化系统并开展测试。第三年（2027年）：扩大试点并形成阶段成果。",
            },
        ],
        "meta": {
            "file_name": "demo.pdf",
            "page_count": 2,
            "parser_version": "test",
            "page_estimated": False,
        },
    }

    request = EvaluationRequest(
        project_id="demo-progress-rerank",
        dimensions=["team"],
        enable_highlight=False,
        enable_industry_fit=False,
        enable_benchmark=False,
        enable_chat_index=True,
    )

    result = await agent.evaluate(request=request, content=content, source_name="demo.pdf")
    answer = await agent.ask(result.evaluation_id, "这项工作目前进展到什么程度了？")

    assert answer.citations
    assert answer.citations[0].page == 14


def test_qa_agent_extract_progress_points_prefers_schedule_actions_over_prior_achievements():
    """进展抽取应优先提取进度安排中的动作，不应被前期成果页带偏"""
    agent = EvaluationQAAgent(llm=None)

    chunks = [
        {
            "page": 15,
            "section": "进度安排",
            "text": (
                "第四部分 进度安排\n"
                "（1）进行激光雷达、高光谱相机、高清相机等设备选型，设计与无人机适配方案，完成装备样机试制与初步集成；\n"
                "（2）构建多要素空间数据底座，形成超低空精细化空间数据库；\n"
                "（3）完成路基边坡区域厘米级精细化三维建模；"
            ),
        },
        {
            "page": 12,
            "section": "申报单位在该研究方向的前期任务承担情况、相关研究成果",
            "text": "项目入选试点，顺利通过验收，荣获国家级科技奖励2项。",
        },
    ]

    points = agent._extract_progress_points(chunks)

    assert points
    assert "完成装备样机试制与初步集成" in points[0]
    assert all("通过验收" not in point for point in points)


def test_qa_agent_extract_goal_points_handles_wrapped_overall_goal():
    """目标抽取应能处理跨行的总体目标正文"""
    agent = EvaluationQAAgent(llm=None)

    chunks = [
        {
            "page": 7,
            "section": "项目简介",
            "text": (
                "本项目的总体目标是通过创新驱动，通过智能和数字化技术研究与应用，提升骨科\n"
                "领域诊疗水平和患者满意度，成为智能与数字化骨科领域的重要科研和人才培养基地。"
            ),
        }
    ]

    points = agent._extract_goal_points(chunks)

    assert points
    assert "总体目标" not in points[0]
    assert "提升骨科领域诊疗水平" in points[0]


def test_qa_agent_extract_goal_points_handles_kpi_goal_fragment():
    """目标抽取应能处理绩效表里倒序混入的总体目标内容"""
    agent = EvaluationQAAgent(llm=None)

    chunks = [
        {
            "page": 19,
            "section": "项目绩效评价考核目标及指标",
            "text": (
                "实施期目标\n第一年度目标\n形成《低空多源感知病害检测和灾害监测装备研发与应用示范研究报\n"
                "告》；研发一套高集成智能化检监测装备，建设基于多要素空间数据底座的超低空高精度数字航图；\n"
                "开发适用于道路灾病害监测及路面异常状态识别等应用场景智能算法；完成5G、6G通信技术在低空监测场景的示范应用。\n"
                "总体\n目标"
            ),
        }
    ]

    points = agent._extract_goal_points(chunks)

    assert points
    assert "研发一套高集成智能化检监测装备" in points[0]


def test_qa_agent_extract_outcome_points_skips_heading_only_matches():
    """成果抽取应优先返回具体成果/效益，而不是章节标题"""
    agent = EvaluationQAAgent(llm=None)

    chunks = [
        {
            "page": 7,
            "section": "项目实施的预期经济社会效益目标",
            "text": (
                "三、项目实施的预期经济社会效益目标\n"
                "技术应用突破研究：拟申报1-2 项省级科研项目，5-10 篇高水平科研论文。\n"
                "数据驱动决策：拟建立数据库建设达到50,000 例。\n"
                "科研转化与应用：拟申请3-5 项技术专利。"
            ),
        }
    ]

    points = agent._extract_outcome_points(chunks)

    assert points
    assert "项目实施的预期经济社会效益目标" not in points[0]
    assert any(keyword in points[0] for keyword in ("科研项目", "论文", "数据库", "专利"))


def test_qa_agent_extract_outcome_points_avoids_goal_like_benefit_sentence():
    """成果抽取不应把总体目标或愿景型描述误当成具体成果"""
    agent = EvaluationQAAgent(llm=None)

    chunks = [
        {
            "page": 7,
            "section": "项目实施的预期经济社会效益目标",
            "text": (
                "本项目的总体目标是提升诊疗水平和患者满意度，成为重要科研和人才培养基地。\n"
                "拟建立数据库建设达到50,000 例。\n"
                "拟申请3-5 项技术专利。"
            ),
        }
    ]

    points = agent._extract_outcome_points(chunks)

    assert points
    assert all("人才培养基地" not in point for point in points)
    assert any("50,000" in point or "技术专利" in point for point in points)


@pytest.mark.asyncio
async def test_qa_agent_ask_returns_structured_goal_answer():
    """研究目标问答应输出结构化回答，而不是单句模板"""
    agent = EvaluationQAAgent(llm=None)
    index_payload = agent.indexer.build(
        evaluation_id="EVAL_TEST_GOAL",
        page_chunks=[
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目目的和意义",
                "text": "目的：建设智能化科普咨询平台，整合资源并提升基层传播能力。",
            }
        ],
    )

    answer = await agent.ask("这个项目的研究目标是什么？", index_payload=index_payload)

    assert "结论：" in answer.answer
    assert "依据：" in answer.answer
    assert "不足：" in answer.answer
    assert answer.citations
    assert answer.citations[0].page == 5


@pytest.mark.asyncio
async def test_qa_agent_ask_innovation_prefers_innovation_section():
    """创新点问题应优先返回创新章节证据，而不是一般目标描述"""
    agent = EvaluationQAAgent(llm=None)
    index_payload = agent.indexer.build(
        evaluation_id="EVAL_TEST_INNOVATION",
        page_chunks=[
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 4,
                "section": "项目简介",
                "text": "建设目标：打造科普服务平台，完善基础能力。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 7,
                "section": "创新点",
                "text": "1、技术创新：通过AI智能问答和大数据推送实现个性化科普内容推荐。2、模式创新：将医疗服务流程与科普传播深度融合。",
            },
        ],
    )

    answer = await agent.ask("这个项目的创新点是什么？", index_payload=index_payload)

    assert "结论：" in answer.answer
    assert "AI智能问答" in answer.answer or "模式创新" in answer.answer
    assert answer.citations
    assert answer.citations[0].page == 7


@pytest.mark.asyncio
async def test_qa_agent_ask_validation_distinguishes_completed_and_planned_evidence():
    """验证数据问答应优先抓已完成验证证据，并保留谨慎语气"""
    agent = EvaluationQAAgent(llm=None)
    index_payload = agent.indexer.build(
        evaluation_id="EVAL_TEST_VALIDATION",
        page_chunks=[
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 12,
                "section": "可行性分析",
                "text": "已完成3轮性能测试，实测准确率达到92.4%，累计样本量120例。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 13,
                "section": "研究计划",
                "text": "后续拟继续扩大样本量，并开展多中心验证。",
            },
        ],
    )

    answer = await agent.ask("有验证数据吗？", index_payload=index_payload)

    assert "结论：" in answer.answer
    assert "验证" in answer.answer or "测试" in answer.answer
    assert "92.4%" in answer.answer or "120例" in answer.answer
    assert answer.citations
    assert answer.citations[0].page == 12


@pytest.mark.asyncio
async def test_qa_agent_ask_mass_production_stays_cautious_for_demo_only():
    """只有示范推广证据时，不应直接给出可以量产的结论"""
    agent = EvaluationQAAgent(llm=None)
    index_payload = agent.indexer.build(
        evaluation_id="EVAL_TEST_PRODUCTION",
        page_chunks=[
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 15,
                "section": "成果转化与应用示范",
                "text": "项目拟联合医院和社区开展应用示范，推动成果转化与推广应用。",
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 16,
                "section": "项目效益",
                "text": "预期形成较好的社会效益和示范效应。",
            },
        ],
    )

    answer = await agent.ask("这项技术有可能量产吗？", index_payload=index_payload)

    assert "不足以支持“可以量产”的确定性判断" in answer.answer or "尚不能直接等同为已具备量产条件" in answer.answer
    assert answer.citations
    assert answer.citations[0].page == 15
