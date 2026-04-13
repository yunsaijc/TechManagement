"""正文评审路由测试"""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from fastapi import HTTPException

from src.common.models.evaluation import (
    EvaluationChatAskRequest,
    EvaluationChatAskResponse,
    EvaluationResult,
    GuideEvaluationResult,
)


class StubEvaluationAgent:
    """用于路由测试的评审 Agent 替身"""

    def __init__(self):
        self.evaluate_calls = []
        self.ask_calls = []
        self.evaluate_by_guide_calls = []

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

    async def evaluate_by_guide(self, request):
        self.evaluate_by_guide_calls.append({"request": request})
        return GuideEvaluationResult(
            zndm=request.zndm,
            guide_name="示例指南",
            total=1,
            success=1,
            failed=0,
            results=[
                EvaluationResult(
                    project_id="guide-project",
                    project_name="示例项目",
                    overall_score=8.2,
                    grade="B",
                    dimension_scores=[],
                    summary="按指南代码评审完成",
                    recommendations=[],
                    evaluation_id="EVAL_GUIDE_DEMO",
                    chat_ready=bool(request.enable_chat_index),
                )
            ],
            errors=[],
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


def test_evaluate_by_guide_route_forwards_zndm_request():
    """按指南代码评审路由应转发真实参数"""
    route_module = load_evaluation_route_module()
    stub_agent = StubEvaluationAgent()
    route_module._agent = stub_agent

    result = asyncio.run(
        route_module.evaluate_by_guide(
            route_module.GuideEvaluationRequest(
                zndm="c2f3b7b1f9534463ad726e6936c91859",
                limit=10,
                enable_highlight=True,
                enable_chat_index=True,
            )
        )
    )

    assert result.zndm == "c2f3b7b1f9534463ad726e6936c91859"
    assert result.total == 1
    assert result.results[0].evaluation_id == "EVAL_GUIDE_DEMO"
    assert len(stub_agent.evaluate_by_guide_calls) == 1
    call = stub_agent.evaluate_by_guide_calls[0]
    assert call["request"].limit == 10
    assert call["request"].enable_highlight is True
    assert call["request"].enable_chat_index is True


def test_evaluate_by_guide_route_maps_missing_document_to_422():
    """按指南代码评审应透传真实正文缺失错误"""
    route_module = load_evaluation_route_module()

    class MissingDocAgent(StubEvaluationAgent):
        async def evaluate_by_guide(self, request):
            raise ValueError(
                "未找到项目申报文档: demo。当前按真实路径规则查找: /mnt/remote_corpus/2025/sbs/demo/demo.docx"
            )

    route_module._agent = MissingDocAgent()

    try:
        asyncio.run(
            route_module.evaluate_by_guide(
                route_module.GuideEvaluationRequest(zndm="demo")
            )
        )
        raise AssertionError("预期抛出 HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "/mnt/remote_corpus/2025/sbs/demo/demo.docx" in exc.detail
