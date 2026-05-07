"""项目画像自适应评审测试"""

from pathlib import Path

import pytest

from src.common.models.evaluation import EvaluationRequest
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.storage.storage import EvaluationStorage


class BrokenLLM:
    """始终失败的模型，用于验证规则降级路径"""

    async def ainvoke(self, prompt):
        raise RuntimeError("Connection error")


@pytest.mark.asyncio
async def test_science_popularization_profile_relaxes_missing_technical_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """科普实施类项目缺少技术路线时，不应被直接打回 5 分默认值"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="science-pop-demo",
            dimensions=["feasibility", "schedule", "risk_control"],
            enable_highlight=False,
            enable_industry_fit=False,
            enable_benchmark=False,
            enable_chat_index=False,
        ),
        content={
            "sections": {
                "项目简介": "围绕基层科普传播开展线上直播和线下活动。",
                "建设目标": "建设智能化科普服务体系，形成资源库和传播矩阵。",
                "科普内容产出": "制作原创科普作品，开展公众号传播。",
                "科普活动开展": "组织专题展览和义诊活动。",
                "项目组织实施机制": "建立实施协调与资源保障机制。",
            },
            "page_chunks": [],
            "meta": {"file_name": "demo.pdf"},
        },
        source_name="demo.pdf",
    )

    scores = {item.dimension: item for item in result.dimension_scores}
    assert scores["feasibility"].score > 5.0
    assert "不再强制要求独立技术路线章节" in scores["feasibility"].opinion
    assert scores["schedule"].score > 5.0
    assert scores["risk_control"].score > 5.0


@pytest.mark.asyncio
async def test_project_profile_does_not_leak_between_evaluations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """同一个 agent 连续评审不同项目时，画像口径不能串用"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    science_result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="science-pop-seq",
            dimensions=["feasibility"],
            enable_highlight=False,
            enable_industry_fit=False,
            enable_benchmark=False,
            enable_chat_index=False,
        ),
        content={
            "sections": {
                "建设目标": "建设智能化科普服务体系。",
                "科普活动开展": "组织线上线下科普活动。",
                "科普内容产出": "建设传播资源库。",
            },
            "page_chunks": [],
            "meta": {"file_name": "science.pdf"},
        },
        source_name="science.pdf",
    )

    tech_result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="tech-rnd-seq",
            dimensions=["feasibility"],
            enable_highlight=False,
            enable_industry_fit=False,
            enable_benchmark=False,
            enable_chat_index=False,
        ),
        content={
            "sections": {
                "项目简介": "围绕关键芯片开展研发。",
                "研究目标": "突破关键瓶颈。",
            },
            "page_chunks": [],
            "meta": {"file_name": "tech.pdf"},
        },
        source_name="tech.pdf",
    )

    assert science_result.dimension_scores[0].score > 5.0
    assert tech_result.dimension_scores[0].score == 5.0
    assert "未找到技术路线相关内容" in tech_result.dimension_scores[0].opinion


@pytest.mark.asyncio
async def test_science_popularization_profile_relaxes_outcome_and_benefit_dimensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """科普实施类项目未单列成果/效益章节时，应按绩效和推广类内容替代评估"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="science-pop-benefit",
            dimensions=["outcome", "social_benefit", "economic_benefit"],
            enable_highlight=False,
            enable_industry_fit=False,
            enable_benchmark=False,
            enable_chat_index=False,
        ),
        content={
            "sections": {
                "项目简介": "围绕基层科普传播能力提升建设服务体系。",
                "主要指标、效益": "预计形成可复制推广模式，扩大区域覆盖，提升公共服务效能。",
                "项目绩效评价考核目标及指标": "制作科普内容 120 件，开展线上线下活动，形成持续服务能力。",
                "科普内容产出": "形成视频、图文和资源包等内容产出。",
                "普及前景": "模式可复制与推广，可向更多地区延展。",
            },
            "page_chunks": [],
            "meta": {"file_name": "science-benefit.pdf"},
        },
        source_name="science-benefit.pdf",
    )

    scores = {item.dimension: item for item in result.dimension_scores}
    assert scores["outcome"].score > 5.0
    assert "未找到预期成果相关内容" not in scores["outcome"].opinion
    assert scores["social_benefit"].score > 5.0
    assert "未找到社会效益相关内容" not in scores["social_benefit"].opinion
    assert scores["economic_benefit"].score > 5.0
    assert "未找到经济效益相关内容" not in scores["economic_benefit"].opinion


@pytest.mark.asyncio
async def test_demonstration_profile_relaxes_missing_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """示范应用类项目未单列相关章节时，应按示范与推广内容替代评估"""
    agent = EvaluationAgent(llm=BrokenLLM())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="demo-application",
            dimensions=["feasibility", "outcome", "risk_control", "schedule"],
            enable_highlight=False,
            enable_industry_fit=False,
            enable_benchmark=False,
            enable_chat_index=False,
        ),
        content={
            "sections": {
                "应用示范方案": "围绕低空巡检场景开展多区域应用示范。",
                "推广应用": "形成分阶段推广机制和示范路线。",
                "项目实施的预期绩效目标": "明确年度示范覆盖范围与绩效指标。",
                "技术风险": "极端天气下稳定性不足，需要冗余验证。",
                "项目组织实施机制": "建立多单位协同推进与保障机制。",
            },
            "page_chunks": [],
            "meta": {"file_name": "demo-application.pdf"},
        },
        source_name="demo-application.pdf",
    )

    scores = {item.dimension: item for item in result.dimension_scores}
    assert scores["feasibility"].score > 5.0
    assert "未找到技术路线相关内容" not in scores["feasibility"].opinion
    assert scores["outcome"].score > 5.0
    assert "未找到预期成果相关内容" not in scores["outcome"].opinion
    assert scores["risk_control"].score > 5.0
    assert "未找到风险控制相关内容" not in scores["risk_control"].opinion
    assert scores["schedule"].score > 5.0
    assert "未找到进度安排相关内容" not in scores["schedule"].opinion
