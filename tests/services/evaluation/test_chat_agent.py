"""聊天问答测试"""
from pathlib import Path

import pytest

from src.common.models.evaluation import EvaluationRequest
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.chat.qa_agent import EvaluationQAAgent
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
