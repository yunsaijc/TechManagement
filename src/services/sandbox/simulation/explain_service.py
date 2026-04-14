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
        key=lambda item: abs(item.delta_risk) + abs(item.delta_conversion) + abs(item.delta_share),
        reverse=True,
    )
    topics = [_explain_topic(item) for item in ordered[:5]]

    summary = [
        f"共推演 {len(result.impacts)} 个主题，场景 {result.scenario_id} 相对 baseline {result.baseline_id} 已生成结构化影响。",
        f"平均变化: share {result_and_sign(_avg_delta(result, 'delta_share'))}, conversion {result_and_sign(_avg_delta(result, 'delta_conversion'))}, risk {result_and_sign(_avg_delta(result, 'delta_risk'))}.",
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
    if item.delta_share > 0:
        reasons.append(f"主题份额提升 {item.delta_share:.3f}")
    elif item.delta_share < 0:
        reasons.append(f"主题份额下降 {abs(item.delta_share):.3f}")

    if item.delta_conversion > 0:
        reasons.append(f"转化效率提升 {item.delta_conversion:.3f}")
    elif item.delta_conversion < 0:
        reasons.append(f"转化效率下降 {abs(item.delta_conversion):.3f}")

    if item.delta_risk > 0:
        reasons.append(f"风险上升 {item.delta_risk:.3f}")
    elif item.delta_risk < 0:
        reasons.append(f"风险下降 {abs(item.delta_risk):.3f}")

    if item.delta_momentum > 0:
        reasons.append(f"动量增强 {item.delta_momentum:.3f}")
    elif item.delta_momentum < 0:
        reasons.append(f"动量减弱 {abs(item.delta_momentum):.3f}")

    shock_text = ", ".join(item.applied_shocks) if item.applied_shocks else "当前无命中冲击"
    reasons.append(f"命中冲击: {shock_text}")

    return SimulationTopicExplanation(
        topic_id=item.topic_id,
        headline=_build_headline(item),
        reasons=reasons,
        action_hint=_build_action_hint(item),
    )


def _build_headline(item) -> str:
    if item.delta_risk > 0 and item.delta_conversion < 0:
        return "高风险且转化承压"
    if item.delta_conversion > 0 and item.delta_risk <= 0:
        return "转化改善且风险可控"
    if item.delta_share > 0 and item.delta_momentum > 0:
        return "热度与动量同步增强"
    if item.delta_share < 0 and item.delta_momentum < 0:
        return "热度与动量同步走弱"
    return "结构变化待持续观察"


def _build_action_hint(item) -> str:
    if item.delta_risk > 0.03:
        return "优先做风险缓释，必要时降低该主题政策强度。"
    if item.delta_conversion > 0.03:
        return "可以继续加码转化配套，放大已有收益。"
    if item.delta_share > 0.03 and item.delta_risk <= 0:
        return "适合纳入下一周期重点支持清单。"
    return "建议继续监测，等待下一轮基线更新。"


def _avg_delta(result: SimulationResult, field: str) -> float:
    if not result.impacts:
        return 0.0
    return round(sum(getattr(item, field) for item in result.impacts) / len(result.impacts), 6)


def result_and_sign(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.3f}"
