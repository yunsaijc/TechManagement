"""聊天问答测试"""
from pathlib import Path

import pytest

from src.common.models.evaluation import EvaluationRequest
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.storage.storage import EvaluationStorage


class BrokenLLM:
    """始终失败的模型，用于验证降级路径"""

    async def ainvoke(self, prompt):
        raise RuntimeError("Connection error")


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
