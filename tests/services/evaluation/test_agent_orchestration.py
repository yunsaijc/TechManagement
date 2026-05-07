"""评审编排测试"""
from pathlib import Path

import pytest

from src.common.models.evaluation import (
    BenchmarkResult,
    CheckResult,
    EvaluationRequest,
    EvidenceItem,
    IndustryFitResult,
    StructuredHighlights,
)
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.storage.storage import EvaluationStorage


@pytest.mark.asyncio
async def test_evaluation_agent_merges_outputs_from_all_enabled_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """同时开启多个模块时，应合并所有结果到同一 EvaluationResult"""
    agent = EvaluationAgent(llm=object())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    async def fake_run_checks(sections, dimensions, profile_result):
        return [
            CheckResult(
                dimension="team",
                score=8.2,
                confidence=0.85,
                opinion="团队结构较完整。",
                issues=[],
                highlights=["负责人经验较丰富"],
                items=[],
            )
        ]

    async def fake_run_highlight(sections, page_chunks, meta):
        return {
            "highlights": StructuredHighlights(
                research_goals=["建设智能科普服务平台"],
                innovations=["形成多模态交互能力"],
                technical_route=["搭建平台并开展试点验证"],
            ),
            "evidence": [
                EvidenceItem(
                    source="document",
                    file="demo.pdf",
                    page=3,
                    snippet="建设智能科普服务平台。",
                )
            ],
        }

    async def fake_run_industry_fit(sections, page_chunks):
        return {
            "industry_fit": IndustryFitResult(
                fit_score=0.8,
                matched=["新一代信息技术"],
                gaps=["缺少标准符合性与认证路径说明"],
                suggestions=["补充标准/认证路径及关键里程碑"],
            ),
            "evidence": [
                EvidenceItem(
                    source="guide_search",
                    file="guide-2025",
                    page=12,
                    snippet="新一代信息技术",
                )
            ],
        }

    async def fake_run_benchmark(sections):
        return {
            "benchmark": BenchmarkResult(
                novelty_level="medium_high",
                literature_position="已检索到 2 条相关文献，项目与近年同类研究存在可比较改进空间",
                patent_overlap="未检索到直接专利重叠证据",
                conclusion="技术新颖性中高；存在一定比较优势。",
                references=[],
            ),
            "evidence": [
                EvidenceItem(
                    source="tech_search",
                    file="literature",
                    page=2025,
                    snippet="多模态科普交互系统研究",
                )
            ],
        }

    async def fake_run_chat_index(evaluation_id, page_chunks):
        return {"chat_ready": True}

    monkeypatch.setattr(agent, "_run_checks", fake_run_checks)
    monkeypatch.setattr(agent, "_run_highlight", fake_run_highlight)
    monkeypatch.setattr(agent, "_run_industry_fit", fake_run_industry_fit)
    monkeypatch.setattr(agent, "_run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(agent, "_run_chat_index", fake_run_chat_index)

    result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="orchestration-demo",
            dimensions=["team"],
            enable_highlight=True,
            enable_industry_fit=True,
            enable_benchmark=True,
            enable_chat_index=True,
        ),
        content={
            "sections": {"项目名称": "示例项目", "项目简介": "建设智能科普服务平台。"},
            "page_chunks": [{"file": "demo.pdf", "page": 3, "section": "项目简介", "text": "建设智能科普服务平台。"}],
            "meta": {
                "file_name": "demo.pdf",
                "page_count": 1,
                "parser_version": "test",
                "page_estimated": False,
            },
        },
        source_name="demo.pdf",
    )

    assert result.partial is False
    assert result.chat_ready is True
    assert result.highlights is not None
    assert result.highlights.research_goals == ["建设智能科普服务平台"]
    assert result.industry_fit is not None
    assert result.industry_fit.fit_score == 0.8
    assert result.benchmark is not None
    assert result.benchmark.novelty_level == "medium_high"
    assert len(result.evidence) == 3
    assert {item.source for item in result.evidence} == {"document", "guide_search", "tech_search"}


@pytest.mark.asyncio
async def test_evaluation_agent_extracts_project_name_from_overview_when_section_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """缺少显式项目名称章节时，应从概述正文中提取真实项目名"""
    agent = EvaluationAgent(llm=object())
    agent.storage = EvaluationStorage(storage_dir=str(tmp_path / "evaluation"))
    monkeypatch.setattr(agent, "_save_debug_artifacts", lambda **kwargs: None)

    async def fake_run_checks(sections, dimensions, profile_result):
        return [
            CheckResult(
                dimension="team",
                score=8.0,
                confidence=0.8,
                opinion="团队信息完整。",
                issues=[],
                highlights=[],
                items=[],
            )
        ]

    monkeypatch.setattr(agent, "_run_checks", fake_run_checks)

    result = await agent.evaluate(
        request=EvaluationRequest(
            project_id="8170da049eae4caf88322ef03f410310",
            dimensions=["team"],
            enable_highlight=False,
            enable_industry_fit=False,
            enable_benchmark=False,
            enable_chat_index=False,
        ),
        content={
            "sections": {
                "概述": (
                    "河北省中央引导地方科技发展资金 项目申报书 "
                    "项目名称：智能与数字化技术在骨科领域的应用及临床研究 "
                    "申报单位：华北医疗健康集团峰峰总医院"
                ),
                "项目简介": "围绕骨科数字化场景开展临床应用研究。",
            },
            "page_chunks": [],
            "meta": {"file_name": "8170da049eae4caf88322ef03f410310.docx"},
        },
        source_name="8170da049eae4caf88322ef03f410310.docx",
    )

    assert result.project_name == "智能与数字化技术在骨科领域的应用及临床研究"


def test_evaluation_agent_project_name_prefers_cover_over_table_garbage():
    """封面项目名与表格串同时存在时，应优先采用封面中的真实名称"""
    agent = EvaluationAgent(llm=object())

    project_name = agent._resolve_project_name(
        sections={
            "概述": (
                "河北省创新能力提升计划项目申报书 "
                "项 目 名 称 ：生殖健康科普示范基地标准化建设与创新模式探索 "
                "承 担 单 位 ：河北医科大学第四医院"
            ),
            "项目基本信息": (
                "[表格表头1] 项目名称 | 项目名称 | 项目名称 | "
                "生殖健康科普示范基地标准化建设与创新模式探索 | 所属专项"
            ),
        },
        meta={"file_name": "ffb75a4c639d4ebab2c33e21d75d7bac.docx"},
        project_id="ffb75a4c639d4ebab2c33e21d75d7bac",
        source_name="ffb75a4c639d4ebab2c33e21d75d7bac.docx",
    )

    assert project_name == "生殖健康科普示范基地标准化建设与创新模式探索"
