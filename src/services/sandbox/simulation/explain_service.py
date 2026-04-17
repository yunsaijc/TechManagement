"""Explanation service for native sandbox simulation results."""

from __future__ import annotations

import re

from src.common.models.simulation import (
    SimulationExplanation,
    SimulationResult,
    SimulationTopicExplanation,
)

from . import repository
from .compare_service import (
    DIRECT_IMPACT,
    SPILLOVER_IMPACT,
    STRUCTURAL_CHANGE,
    build_management_summary,
    build_result_impact_breakdown,
    build_topic_impact_layers,
    classify_management_action,
)

_IMPACT_ORIGIN_LABELS = {
    "direct": "直接作用",
    "spillover": "外溢传导",
    "mixed": "直接作用与外溢传导叠加",
    "none": "未识别明确来源",
}

_TOPIC_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_]{6,}$")


def explain_result(result: SimulationResult) -> SimulationExplanation:
    ordered = sorted(
        result.impacts,
        key=lambda item: abs(item.delta_funding_amount)
        + abs(item.delta_funded_count)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_proxy_risk),
        reverse=True,
    )
    ordered = _dedupe_impacts_by_topic_label(ordered)
    impact_breakdown = build_result_impact_breakdown(result)
    management_summary = build_management_summary(result, impact_breakdown=impact_breakdown)
    topics = [_explain_topic(item) for item in ordered[:5]]

    summary = list(management_summary["executiveSummary"])
    summary.append(
        (
            "总体均值变化: "
            f"申报数 {with_sign(_avg_delta(result, 'delta_application_count'))}, "
            f"立项数 {with_sign(_avg_delta(result, 'delta_funded_count'))}, "
            f"合同经费 {with_sign(_avg_delta(result, 'delta_funding_amount'))}, "
            f"协作密度 {with_sign(_avg_delta(result, 'delta_collaboration_density'))}, "
            f"风险代理 {with_sign(_avg_delta(result, 'delta_proxy_risk'))}."
        )
    )
    summary.append(_build_origin_distribution_summary(impact_breakdown))
    if ordered:
        summary.append(
            f"变化最显著的主题是 {_topic_label(ordered[0])}，主要受{_impact_source_brief(ordered[0])}驱动。"
        )

    return SimulationExplanation(
        scenario_id=result.scenario_id,
        baseline_id=result.baseline_id,
        forecast_window=result.forecast_window,
        summary=summary,
        topics=topics,
        metadata={
            "sourceRunId": result.run_id,
            "topicCount": len(result.impacts),
            "impactBreakdown": impact_breakdown,
            "managementSummary": management_summary,
        },
    )


def explain_latest_result() -> SimulationExplanation | None:
    latest = repository.load_latest_scenario_result()
    if latest is None:
        return None
    return explain_result(latest)


def _explain_topic(item) -> SimulationTopicExplanation:
    topic_layers = build_topic_impact_layers(item)
    reasons = [
        _layer_reason("直接影响", topic_layers[DIRECT_IMPACT]),
        _layer_reason("外溢影响", topic_layers[SPILLOVER_IMPACT]),
        _layer_reason("结构变化", topic_layers[STRUCTURAL_CHANGE]),
    ]
    reasons.append(_impact_source_reason(item))

    return SimulationTopicExplanation(
        topic_id=item.topic_id,
        topic_label=_topic_label(item),
        headline=_build_headline(item, topic_layers),
        reasons=reasons,
        action_hint=_build_action_hint(item, topic_layers),
    )


def _build_headline(item, topic_layers: dict[str, object]) -> str:
    action = classify_management_action(item, layers=topic_layers)
    if action == "add":
        if item.impact_origin == "mixed":
            return "建议加码，直接作用与外溢传导同步显现"
        if item.impact_origin == "spillover":
            return "建议加码，外溢带动已开始转化为直接收益"
        if topic_layers[SPILLOVER_IMPACT]["direction"] == "positive":
            return "建议加码，直接收益和外溢带动同步显现"
        return "建议加码，直接收益明确且结构稳定"
    if action == "stop_loss":
        return "建议止损，直接产出转弱且回报承压"
    if action == "side_effect":
        if item.impact_origin == "mixed":
            return "直接收益存在，但叠加传导后的副作用抬头"
        return "收益存在但副作用抬头，建议控节奏"
    if topic_layers[STRUCTURAL_CHANGE]["direction"] == "positive":
        return "结构改善开始显现，建议继续观察兑现"
    return "变化有限，暂以跟踪观察为主"


def _build_action_hint(item, topic_layers: dict[str, object]) -> str:
    action = classify_management_action(item, layers=topic_layers)
    if action == "add":
        if item.impact_origin == "mixed":
            return "建议纳入优先加码池，同时稳住直接投入和协作扩散两条链路，并继续跟踪风险约束是否抬头。"
        if item.impact_origin == "spillover":
            return "建议沿外溢传导链继续补强协作承接，验证扩散增益能否稳定转化为立项和合同经费。"
        return "建议纳入优先加码池，优先保障合同经费和立项配额，并继续跟踪外溢带动是否兑现。"
    if action == "stop_loss":
        return "建议先收缩投入，复核该主题的立项效率、合同兑现和后续承接能力。"
    if action == "side_effect":
        if item.impact_origin == "mixed":
            return "建议保留组合试点但压住放大节奏，分别检查直接投放和外溢扩散哪一条链路在推高风险。"
        return "建议保留政策试点但压住节奏，先做风险缓释和结构校正，再决定是否继续放大。"
    if topic_layers[SPILLOVER_IMPACT]["direction"] == "positive":
        return "建议继续观察协作扩散能否转化为立项和合同经费的直接改善。"
    return "建议继续监测下一时间窗的项目与图谱状态变化。"


def _avg_delta(result: SimulationResult, field: str) -> float:
    if not result.impacts:
        return 0.0
    return round(sum(getattr(item, field) for item in result.impacts) / len(result.impacts), 6)


def with_sign(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.3f}"


def _layer_reason(label: str, layer: dict[str, object]) -> str:
    signals = list(layer["signals"])
    if not signals:
        return f"{label}: 未形成显著变化"
    parts = [_signal_text(signal) for signal in signals[:3]]
    return f"{label}: {'，'.join(parts)}"


def _signal_text(signal: dict[str, object]) -> str:
    delta = float(signal["delta"])
    direction = "上升" if delta > 0 else "下降"
    if signal["metric"] in {"application_count", "funded_count"}:
        direction = "增加" if delta > 0 else "减少"
        return f"{signal['label']}{direction} {abs(delta):.0f}"
    return f"{signal['label']}{direction} {abs(delta):.3f}"


def _build_origin_distribution_summary(impact_breakdown: dict[str, object]) -> str:
    origin_counts = impact_breakdown.get("impactOriginCounts", [])
    if not origin_counts:
        return "影响来源分布: 暂无可用信息。"
    parts = [f"{item['label']} {item['topic_count']} 个" for item in origin_counts]
    return "影响来源分布: " + "，".join(parts) + "。"


def _impact_source_reason(item) -> str:
    if item.impact_origin == "none" and item.applied_shocks:
        return f"影响来源: 命中冲击 {_shock_list_text(item.applied_shocks)}"
    if item.impact_origin == "mixed":
        return (
            f"影响来源: 直接冲击 {_shock_list_text(item.direct_shocks)}；"
            f"外溢传导 {_shock_list_text(item.spillover_shocks)}"
        )
    if item.impact_origin == "direct":
        return f"影响来源: 直接冲击 {_shock_list_text(item.direct_shocks)}"
    if item.impact_origin == "spillover":
        return f"影响来源: 外溢传导 {_shock_list_text(item.spillover_shocks)}"
    return "影响来源: 未识别明确冲击来源"


def _impact_source_brief(item) -> str:
    if item.impact_origin == "none" and item.applied_shocks:
        return f"命中冲击 {_shock_list_text(item.applied_shocks)}"
    if item.impact_origin == "mixed":
        return (
            f"直接冲击 {_shock_list_text(item.direct_shocks)} "
            f"与外溢传导 {_shock_list_text(item.spillover_shocks)}"
        )
    if item.impact_origin == "direct":
        return f"直接冲击 {_shock_list_text(item.direct_shocks)}"
    if item.impact_origin == "spillover":
        return f"外溢传导 {_shock_list_text(item.spillover_shocks)}"
    return _IMPACT_ORIGIN_LABELS["none"]


def _shock_list_text(shocks: list[str]) -> str:
    return "、".join(shocks) if shocks else "未命名冲击"


def _dedupe_impacts_by_topic_label(items: list) -> list:
    selected = []
    seen: set[str] = set()
    for item in items:
        key = _normalize_topic_label(_topic_label(item))
        if key in seen:
            continue
        selected.append(item)
        seen.add(key)
    return selected


def _topic_label(item) -> str:
    label = str(getattr(item, "topic_label", "") or "").strip()
    if label:
        return label
    return _fallback_topic_label(str(getattr(item, "topic_id", "") or ""))


def _fallback_topic_label(topic_id: str) -> str:
    text = " ".join(topic_id.strip().split())
    if "-" not in text:
        return text
    prefix, remainder = text.split("-", 1)
    remainder = " ".join(remainder.strip().split())
    if prefix and remainder and _TOPIC_PREFIX_PATTERN.fullmatch(prefix):
        return remainder
    return text


def _normalize_topic_label(label: str) -> str:
    return " ".join(label.strip().split()).lower()
