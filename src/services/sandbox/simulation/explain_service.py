"""Explanation service for native sandbox simulation results."""

from __future__ import annotations

from src.common.models.simulation import (
    SimulationExplanation,
    SimulationResult,
    SimulationTopicExplanation,
)

from . import repository


def explain_result(result: SimulationResult) -> SimulationExplanation:
    ordered = sorted(
        result.impacts,
        key=lambda item: abs(item.delta_funding_amount)
        + abs(item.delta_funded_count)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_proxy_risk),
        reverse=True,
    )
    topics = [_explain_topic(item) for item in ordered[:5]]

    summary = [
        f"共推演 {len(result.impacts)} 个主题，场景 {result.scenario_id} 基于项目库与图谱状态变量完成结构推演。",
        (
            "平均变化: "
            f"申报数 {with_sign(_avg_delta(result, 'delta_application_count'))}, "
            f"立项数 {with_sign(_avg_delta(result, 'delta_funded_count'))}, "
            f"经费 {with_sign(_avg_delta(result, 'delta_funding_amount'))}, "
            f"协作密度 {with_sign(_avg_delta(result, 'delta_collaboration_density'))}, "
            f"风险代理 {with_sign(_avg_delta(result, 'delta_proxy_risk'))}."
        ),
    ]
    if ordered:
        summary.append(f"最显著主题是 {ordered[0].topic_id}，主要受 {', '.join(ordered[0].applied_shocks) or '未命名冲击'} 驱动。")

    return SimulationExplanation(
        scenario_id=result.scenario_id,
        baseline_id=result.baseline_id,
        forecast_window=result.forecast_window,
        summary=summary,
        topics=topics,
        metadata={
            "sourceRunId": result.run_id,
            "topicCount": len(result.impacts),
        },
    )


def explain_latest_result() -> SimulationExplanation | None:
    latest = repository.load_latest_scenario_result()
    if latest is None:
        return None
    return explain_result(latest)


def _explain_topic(item) -> SimulationTopicExplanation:
    reasons: list[str] = []
    if item.delta_application_count > 0:
        reasons.append(f"申报数增加 {item.delta_application_count}")
    elif item.delta_application_count < 0:
        reasons.append(f"申报数减少 {abs(item.delta_application_count)}")

    if item.delta_funded_count > 0:
        reasons.append(f"立项数增加 {item.delta_funded_count}")
    elif item.delta_funded_count < 0:
        reasons.append(f"立项数减少 {abs(item.delta_funded_count)}")

    if item.delta_funding_amount > 0:
        reasons.append(f"立项经费增加 {item.delta_funding_amount:.3f}")
    elif item.delta_funding_amount < 0:
        reasons.append(f"立项经费减少 {abs(item.delta_funding_amount):.3f}")

    if item.delta_collaboration_density > 0:
        reasons.append(f"协作密度提升 {item.delta_collaboration_density:.3f}")
    elif item.delta_collaboration_density < 0:
        reasons.append(f"协作密度下降 {abs(item.delta_collaboration_density):.3f}")

    if item.delta_topic_centrality > 0:
        reasons.append(f"图谱中心性提升 {item.delta_topic_centrality:.3f}")
    elif item.delta_topic_centrality < 0:
        reasons.append(f"图谱中心性下降 {abs(item.delta_topic_centrality):.3f}")

    if item.delta_migration_strength > 0:
        reasons.append(f"热点迁移强度上升 {item.delta_migration_strength:.3f}")
    elif item.delta_migration_strength < 0:
        reasons.append(f"热点迁移强度下降 {abs(item.delta_migration_strength):.3f}")

    if item.delta_proxy_risk > 0:
        reasons.append(f"风险代理上升 {item.delta_proxy_risk:.3f}")
    elif item.delta_proxy_risk < 0:
        reasons.append(f"风险代理下降 {abs(item.delta_proxy_risk):.3f}")

    shock_text = ", ".join(item.applied_shocks) if item.applied_shocks else "当前无命中冲击"
    reasons.append(f"命中冲击: {shock_text}")

    return SimulationTopicExplanation(
        topic_id=item.topic_id,
        headline=_build_headline(item),
        reasons=reasons,
        action_hint=_build_action_hint(item),
    )


def _build_headline(item) -> str:
    if item.delta_proxy_risk > 0.03 and (item.delta_funded_count < 0 or item.delta_application_count < 0):
        return "项目支持承压且风险代理上升"
    if item.delta_funded_count > 0 and item.delta_funding_amount > 0 and item.delta_proxy_risk <= 0:
        return "项目支持增强且风险代理可控"
    if item.delta_collaboration_density > 0 and item.delta_migration_strength > 0:
        return "协作与热点迁移同步增强"
    if item.delta_application_count < 0 and item.delta_topic_centrality < 0:
        return "申报热度与图谱中心性走弱"
    return "结构变化待持续观察"


def _build_action_hint(item) -> str:
    if item.delta_proxy_risk > 0.03:
        return "优先做风险缓释，并复核该主题的配额和资助节奏。"
    if item.delta_funding_amount > 0 and item.delta_funded_count > 0:
        return "可继续维持支持力度，观察是否形成稳定的立项优势。"
    if item.delta_collaboration_density > 0.04:
        return "建议进一步放大跨单位协作机制，巩固网络效应。"
    return "建议继续监测下一时间窗的项目与图谱状态变化。"


def _avg_delta(result: SimulationResult, field: str) -> float:
    if not result.impacts:
        return 0.0
    return round(sum(getattr(item, field) for item in result.impacts) / len(result.impacts), 6)


def with_sign(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.3f}"
