"""正文评审路由测试"""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from fastapi import HTTPException

from src.common.models.evaluation import EvaluationChatAskRequest, EvaluationChatAskResponse, EvaluationResult


class StubEvaluationAgent:
    """用于路由测试的评审 Agent 替身"""

    def __init__(self):
        self.evaluate_calls = []
        self.ask_calls = []

    async def evaluate(self, request, file_path=None, content=None, source_name=""):
        self.evaluate_calls.append(
            {
                "request": request,
                "file_path": file_path,
                "content": content,
                "source_name": source_name,
            }
        )
        return EvaluationResult(
            project_id=request.project_id,
            project_name="示例项目",
            overall_score=8.4,
            grade="B",
            dimension_scores=[],
            summary="测试评审结果",
            recommendations=["补充论证细节"],
            evaluation_id="EVAL_API_DEMO",
            chat_ready=bool(request.enable_chat_index),
        )

    async def ask(self, evaluation_id: str, question: str):
        self.ask_calls.append({"evaluation_id": evaluation_id, "question": question})
        if evaluation_id == "missing":
            raise ValueError(f"评审记录不存在: {evaluation_id}")
        if evaluation_id == "no-index":
            raise ValueError("该评审记录未构建聊天索引，请重新评审并启用 enable_chat_index")
        return EvaluationChatAskResponse(
            answer="已定位到研究目标相关内容。",
            citations=[
                {
                    "file": "demo.pdf",
                    "page": 5,
                    "snippet": "项目目标：建设智能科普服务平台。",
                }
            ],
        )


class FakeUploadFile:
    """最小上传文件替身，仅覆盖路由实际使用的属性与方法"""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def load_evaluation_route_module():
    """按文件加载路由模块，避免触发 evaluation 包重依赖初始化"""
    package_module = types.ModuleType("src.services.evaluation")
    package_module.__path__ = []  # type: ignore[attr-defined]
    sys.modules["src.services.evaluation"] = package_module

    agent_module = types.ModuleType("src.services.evaluation.agent")
    agent_module.EvaluationAgent = StubEvaluationAgent
    sys.modules["src.services.evaluation.agent"] = agent_module
    package_module.agent = agent_module

    config_path = Path(__file__).resolve().parents[3] / "src/services/evaluation/config.py"
    config_spec = importlib.util.spec_from_file_location("src.services.evaluation.config", config_path)
    if config_spec is None or config_spec.loader is None:
        raise RuntimeError("无法加载 evaluation config 模块")
    config_module = importlib.util.module_from_spec(config_spec)
    sys.modules["src.services.evaluation.config"] = config_module
    config_spec.loader.exec_module(config_module)
    package_module.config = config_module

    route_path = Path(__file__).resolve().parents[3] / "src/app/routes/evaluation.py"
    route_spec = importlib.util.spec_from_file_location("evaluation_route_test", route_path)
    if route_spec is None or route_spec.loader is None:
        raise RuntimeError("无法加载 evaluation 路由模块")
    route_module = importlib.util.module_from_spec(route_spec)
    route_spec.loader.exec_module(route_module)
    return route_module


def test_evaluate_file_route_returns_result():
    """上传文件路由应返回评审结果并解析表单参数"""
    route_module = load_evaluation_route_module()
    stub_agent = StubEvaluationAgent()
    route_module._agent = stub_agent

    upload = FakeUploadFile(filename="demo.pdf", data=b"%PDF-1.4 fake")
    result = asyncio.run(
        route_module.evaluate_file(
            file=upload,
            project_id="api-demo",
            dimensions="team,innovation",
            weights=None,
            include_sections=None,
            enable_highlight=True,
            enable_industry_fit=False,
            enable_benchmark=True,
            enable_chat_index=True,
        )
    )

    assert result.project_id == "api-demo"
    assert result.evaluation_id == "EVAL_API_DEMO"
    assert result.chat_ready is True

    assert len(stub_agent.evaluate_calls) == 1
    call = stub_agent.evaluate_calls[0]
    assert call["source_name"] == "demo.pdf"
    assert call["request"].dimensions == ["team", "innovation"]
    assert call["request"].enable_highlight is True
    assert call["request"].enable_benchmark is True
    assert call["request"].enable_chat_index is True


def test_chat_ask_route_returns_answer():
    """聊天路由应返回 answer 与 citations"""
    route_module = load_evaluation_route_module()
    stub_agent = StubEvaluationAgent()
    route_module._agent = stub_agent

    result = asyncio.run(
        route_module.ask_question(
            EvaluationChatAskRequest(
                evaluation_id="EVAL_API_DEMO",
                question="研究目标是什么？",
            )
        )
    )

    assert "研究目标" in result.answer
    assert result.citations[0].file == "demo.pdf"
    assert stub_agent.ask_calls[0]["evaluation_id"] == "EVAL_API_DEMO"


def test_chat_ask_route_maps_not_found_to_404():
    """聊天路由应把缺失评审记录映射为 404"""
    route_module = load_evaluation_route_module()
    route_module._agent = StubEvaluationAgent()

    try:
        asyncio.run(
            route_module.ask_question(
                EvaluationChatAskRequest(
                    evaluation_id="missing",
                    question="研究目标是什么？",
                )
            )
        )
        raise AssertionError("预期抛出 HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "评审记录不存在" in exc.detail


def test_chat_ask_route_maps_missing_index_to_422():
    """聊天路由应把未构建索引映射为 422"""
    route_module = load_evaluation_route_module()
    route_module._agent = StubEvaluationAgent()

    try:
        asyncio.run(
            route_module.ask_question(
                EvaluationChatAskRequest(
                    evaluation_id="no-index",
                    question="研究目标是什么？",
                )
            )
        )
        raise AssertionError("预期抛出 HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "未构建聊天索引" in exc.detail
