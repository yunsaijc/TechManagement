"""Comparison service for native sandbox simulation results."""

from __future__ import annotations

from collections import Counter
import re

from src.common.models.simulation import (
    SimulationTopicImpact,
    SimulationComparison,
    SimulationComparisonTopic,
    SimulationResult,
)

from . import repository

DIRECT_IMPACT = "direct_impact"
SPILLOVER_IMPACT = "spillover_impact"
STRUCTURAL_CHANGE = "structural_change"

_IMPACT_LABELS = {
    DIRECT_IMPACT: "直接影响",
    SPILLOVER_IMPACT: "外溢影响",
    STRUCTURAL_CHANGE: "结构变化",
}

_IMPACT_ORIGIN_LABELS = {
    "direct": "直接作用",
    "spillover": "外溢传导",
    "mixed": "直接+外溢叠加",
    "none": "未识别来源",
}

_MANAGEMENT_ACTION_LABELS = {
    "add": "建议加码",
    "stop_loss": "建议止损",
    "side_effect": "副作用预警",
    "observe": "继续观察",
}

_TOPIC_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_]{6,}$")


def compare_result(result: SimulationResult) -> SimulationComparison:
    impacts = list(result.impacts)
    topic_count = len({_topic_label_key(item) for item in impacts})

    avg_delta_application_count = _avg(item.delta_application_count for item in impacts)
    avg_delta_funded_count = _avg(item.delta_funded_count for item in impacts)
    avg_delta_funding_amount = _avg(item.delta_funding_amount for item in impacts)
    avg_delta_collaboration_density = _avg(item.delta_collaboration_density for item in impacts)
    avg_delta_topic_centrality = _avg(item.delta_topic_centrality for item in impacts)
    avg_delta_migration_strength = _avg(item.delta_migration_strength for item in impacts)
    avg_delta_proxy_risk = _avg(item.delta_proxy_risk for item in impacts)

    opportunities = _top_unique_impacts(impacts, score_fn=_opportunity_score, limit=3)
    risks = _top_unique_impacts(impacts, score_fn=_risk_score, limit=3)
    impact_breakdown = build_result_impact_breakdown(result)
    management_summary = build_management_summary(result, impact_breakdown=impact_breakdown)

    return SimulationComparison(
        scenario_id=result.scenario_id,
        baseline_id=result.baseline_id,
        forecast_window=result.forecast_window,
        topic_count=topic_count,
        avg_delta_application_count=avg_delta_application_count,
        avg_delta_funded_count=avg_delta_funded_count,
        avg_delta_funding_amount=avg_delta_funding_amount,
        avg_delta_collaboration_density=avg_delta_collaboration_density,
        avg_delta_topic_centrality=avg_delta_topic_centrality,
        avg_delta_migration_strength=avg_delta_migration_strength,
        avg_delta_proxy_risk=avg_delta_proxy_risk,
        top_opportunities=[_to_summary(item) for item in opportunities],
        top_risks=[_to_summary(item) for item in risks],
        metadata={
            "sourceRunId": result.run_id,
            "engine": result.metadata.get("engine"),
            "metricSemantics": {
                "application_count": "申报项目数",
                "funded_count": "立项项目数",
                "funding_amount": "合同专项经费",
                "score_proxy": "评审强度代理值",
                "collaboration_density": "协作密度",
                "topic_centrality": "主题中心性",
                "migration_strength": "热点迁移强度",
                "proxy_risk": "风险代理值",
            },
            "impactBreakdown": impact_breakdown,
            "managementSummary": management_summary,
        },
    )


def compare_latest_result() -> SimulationComparison | None:
    latest = repository.load_latest_scenario_result()
    if latest is None:
        return None
    return compare_result(latest)


def build_result_impact_breakdown(result: SimulationResult) -> dict[str, object]:
    topic_layers = [build_topic_impact_layers(item) for item in result.impacts]
    dominant_type_counts = Counter(layer["dominant_type"] for layer in topic_layers)
    return {
        "topicLayers": topic_layers,
        "dominantTypeCounts": [
            {
                "impact_type": impact_type,
                "label": _IMPACT_LABELS[impact_type],
                "topic_count": count,
            }
            for impact_type, count in dominant_type_counts.most_common()
        ],
        "impactOriginCounts": _impact_origin_counts(topic_layers),
        "topDirectImpactTopics": _top_topic_layers(topic_layers, DIRECT_IMPACT),
        "topSpilloverImpactTopics": _top_topic_layers(topic_layers, SPILLOVER_IMPACT),
        "topStructuralChangeTopics": _top_topic_layers(topic_layers, STRUCTURAL_CHANGE),
    }


def build_management_summary(
    result: SimulationResult,
    *,
    impact_breakdown: dict[str, object] | None = None,
) -> dict[str, object]:
    topic_layers = _topic_layers_from_breakdown(result, impact_breakdown)
    impact_origin_summary = _impact_origin_counts(topic_layers)
    recommended_add = sorted(
        (
            layer
            for layer in topic_layers
            if layer["management_action"] == "add"
        ),
        key=lambda item: item["management_priority"],
        reverse=True,
    )
    recommended_add = _top_unique_layers(recommended_add, limit=5)
    recommended_stop_loss = sorted(
        (
            layer
            for layer in topic_layers
            if layer["management_action"] == "stop_loss"
        ),
        key=lambda item: item["management_priority"],
        reverse=True,
    )
    recommended_stop_loss = _top_unique_layers(recommended_stop_loss, limit=5)
    side_effect_topics = sorted(
        (
            layer
            for layer in topic_layers
            if layer["management_action"] == "side_effect"
        ),
        key=lambda item: item["management_priority"],
        reverse=True,
    )
    side_effect_topics = _top_unique_layers(side_effect_topics, limit=5)
    observe_count = len(
        {
            _topic_label_key_from_layer(layer)
            for layer in topic_layers
            if layer["management_action"] == "observe"
        }
    )

    return {
        "recommendedAddTopics": [_to_management_topic(layer) for layer in recommended_add],
        "recommendedStopLossTopics": [_to_management_topic(layer) for layer in recommended_stop_loss],
        "sideEffectTopics": [_to_management_topic(layer) for layer in side_effect_topics],
        "observeTopicCount": observe_count,
        "impactOriginSummary": impact_origin_summary,
        "executiveSummary": _build_executive_summary(
            result,
            topic_layers=topic_layers,
            impact_origin_summary=impact_origin_summary,
            recommended_add=recommended_add,
            recommended_stop_loss=recommended_stop_loss,
            side_effect_topics=side_effect_topics,
            observe_count=observe_count,
        ),
    }


def build_topic_impact_layers(item: SimulationTopicImpact) -> dict[str, object]:
    direct_score = _direct_score(item)
    spillover_score = _spillover_score(item)
    structural_score = _structural_score(item)
    layers = {
        DIRECT_IMPACT: _layer_payload(
            label=_IMPACT_LABELS[DIRECT_IMPACT],
            score=direct_score,
            signals=_direct_signals(item),
            source_shocks=item.direct_shocks,
        ),
        SPILLOVER_IMPACT: _layer_payload(
            label=_IMPACT_LABELS[SPILLOVER_IMPACT],
            score=spillover_score,
            signals=_spillover_signals(item),
            source_shocks=item.spillover_shocks,
        ),
        STRUCTURAL_CHANGE: _layer_payload(
            label=_IMPACT_LABELS[STRUCTURAL_CHANGE],
            score=structural_score,
            signals=_structural_signals(item),
            source_shocks=item.applied_shocks,
        ),
    }
    dominant_type = max(
        layers.items(),
        key=lambda pair: abs(pair[1]["score"]),
    )[0]
    management_action = classify_management_action(item, layers=layers)
    return {
        "topic_id": item.topic_id,
        "topic_label": _topic_label(item),
        "dominant_type": dominant_type,
        "dominant_label": _IMPACT_LABELS[dominant_type],
        "management_action": management_action,
        "management_action_label": _MANAGEMENT_ACTION_LABELS[management_action],
        "management_priority": _management_priority(item, layers, management_action),
        "applied_shocks": list(item.applied_shocks),
        "direct_shocks": list(item.direct_shocks),
        "spillover_shocks": list(item.spillover_shocks),
        "impact_origin": item.impact_origin,
        "impact_origin_label": _IMPACT_ORIGIN_LABELS.get(item.impact_origin, _IMPACT_ORIGIN_LABELS["none"]),
        DIRECT_IMPACT: layers[DIRECT_IMPACT],
        SPILLOVER_IMPACT: layers[SPILLOVER_IMPACT],
        STRUCTURAL_CHANGE: layers[STRUCTURAL_CHANGE],
    }


def classify_management_action(
    item: SimulationTopicImpact,
    *,
    layers: dict[str, dict[str, object]] | None = None,
) -> str:
    resolved_layers = layers or {
        DIRECT_IMPACT: _layer_payload(label=_IMPACT_LABELS[DIRECT_IMPACT], score=_direct_score(item), signals=[]),
        SPILLOVER_IMPACT: _layer_payload(
            label=_IMPACT_LABELS[SPILLOVER_IMPACT],
            score=_spillover_score(item),
            signals=[],
        ),
        STRUCTURAL_CHANGE: _layer_payload(
            label=_IMPACT_LABELS[STRUCTURAL_CHANGE],
            score=_structural_score(item),
            signals=[],
        ),
    }
    direct_score = float(resolved_layers[DIRECT_IMPACT]["score"])
    spillover_score = float(resolved_layers[SPILLOVER_IMPACT]["score"])
    structural_score = float(resolved_layers[STRUCTURAL_CHANGE]["score"])

    if item.delta_proxy_risk > 0.03 and (direct_score > 0.05 or structural_score < -0.02):
        return "side_effect"
    if direct_score < -0.08 or (
        item.delta_funding_amount < 0.0 and item.delta_funded_count <= 0 and item.delta_proxy_risk >= 0.0
    ):
        return "stop_loss"
    if direct_score > 0.10 and structural_score >= -0.02 and item.delta_proxy_risk <= 0.03:
        return "add"
    if direct_score > 0.0 and (spillover_score < 0.0 or structural_score < -0.02):
        return "side_effect"
    return "observe"


def _to_summary(item) -> SimulationComparisonTopic:
    net_score = round(_opportunity_score(item), 6)
    dominant_change = max(
        (
            ("application_count", abs(_safe_ratio(item.delta_application_count, item.baseline_application_count))),
            ("funded_count", abs(_safe_ratio(item.delta_funded_count, item.baseline_funded_count))),
            ("funding_amount", abs(_safe_ratio(item.delta_funding_amount, item.baseline_funding_amount))),
            ("collaboration_density", abs(item.delta_collaboration_density)),
            ("topic_centrality", abs(item.delta_topic_centrality)),
            ("migration_strength", abs(item.delta_migration_strength)),
            ("proxy_risk", abs(item.delta_proxy_risk)),
        ),
        key=lambda pair: pair[1],
    )[0]
    return SimulationComparisonTopic(
        topic_id=item.topic_id,
        topic_label=_topic_label(item),
        net_score=net_score,
        dominant_change=dominant_change,
        applied_shocks=list(item.applied_shocks),
    )


def _opportunity_score(item) -> float:
    return (
        _safe_ratio(item.delta_application_count, item.baseline_application_count)
        + _safe_ratio(item.delta_funded_count, item.baseline_funded_count)
        + _safe_ratio(item.delta_funding_amount, item.baseline_funding_amount)
        + item.delta_collaboration_density
        + item.delta_topic_centrality
        + item.delta_migration_strength
        - item.delta_proxy_risk
        + _safe_ratio(item.delta_score_proxy or 0.0, item.baseline_score_proxy or 1.0)
    )


def _risk_score(item) -> float:
    return (
        item.delta_proxy_risk
        - _safe_ratio(item.delta_funded_count, item.baseline_funded_count)
        - _safe_ratio(item.delta_application_count, item.baseline_application_count)
        - item.delta_topic_centrality
        - item.delta_collaboration_density
    )


def _safe_ratio(delta: float, baseline: float) -> float:
    return round(delta / max(abs(float(baseline)), 1.0), 6)


def _avg(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _direct_score(item: SimulationTopicImpact) -> float:
    return round(
        _safe_ratio(item.delta_application_count, item.baseline_application_count)
        + _safe_ratio(item.delta_funded_count, item.baseline_funded_count)
        + _safe_ratio(item.delta_funding_amount, item.baseline_funding_amount)
        + _safe_ratio(item.delta_score_proxy or 0.0, item.baseline_score_proxy or 1.0),
        6,
    )


def _spillover_score(item: SimulationTopicImpact) -> float:
    return round(item.delta_collaboration_density, 6)


def _structural_score(item: SimulationTopicImpact) -> float:
    return round(item.delta_topic_centrality + item.delta_migration_strength - item.delta_proxy_risk, 6)


def _layer_payload(
    *,
    label: str,
    score: float,
    signals: list[dict[str, object]],
    source_shocks: list[str],
) -> dict[str, object]:
    return {
        "label": label,
        "score": round(score, 6),
        "direction": _direction(score),
        "signals": signals,
        "source_shocks": list(source_shocks),
    }


def _direction(score: float, threshold: float = 0.03) -> str:
    if score > threshold:
        return "positive"
    if score < -threshold:
        return "negative"
    return "neutral"


def _direct_signals(item: SimulationTopicImpact) -> list[dict[str, object]]:
    return _signals(
        [
            ("application_count", "申报项目数", float(item.delta_application_count)),
            ("funded_count", "立项项目数", float(item.delta_funded_count)),
            ("funding_amount", "合同专项经费", float(item.delta_funding_amount)),
            ("score_proxy", "评审强度代理值", float(item.delta_score_proxy or 0.0)),
        ]
    )


def _spillover_signals(item: SimulationTopicImpact) -> list[dict[str, object]]:
    return _signals(
        [
            ("collaboration_density", "协作密度", float(item.delta_collaboration_density)),
        ]
    )


def _structural_signals(item: SimulationTopicImpact) -> list[dict[str, object]]:
    return _signals(
        [
            ("topic_centrality", "主题中心性", float(item.delta_topic_centrality)),
            ("migration_strength", "热点迁移强度", float(item.delta_migration_strength)),
            ("proxy_risk", "风险代理值", float(item.delta_proxy_risk)),
        ]
    )


def _signals(entries: list[tuple[str, str, float]]) -> list[dict[str, object]]:
    output = [
        {
            "metric": metric,
            "label": label,
            "delta": round(delta, 6),
        }
        for metric, label, delta in entries
        if abs(delta) > 1e-9
    ]
    output.sort(key=lambda item: abs(float(item["delta"])), reverse=True)
    return output


def _top_topic_layers(
    topic_layers: list[dict[str, object]],
    impact_type: str,
    limit: int = 5,
) -> list[dict[str, object]]:
    ranked = sorted(
        topic_layers,
        key=lambda layer: abs(float(layer[impact_type]["score"])),
        reverse=True,
    )
    return [
        {
            "topic_id": layer["topic_id"],
            "topic_label": layer.get("topic_label"),
            "score": layer[impact_type]["score"],
            "direction": layer[impact_type]["direction"],
            "management_action": layer["management_action"],
            "management_action_label": layer["management_action_label"],
            "impact_origin": layer["impact_origin"],
            "impact_origin_label": layer["impact_origin_label"],
            "source_shocks": list(layer[impact_type]["source_shocks"]),
        }
        for layer in _top_unique_layers(ranked, limit=limit)
    ]


def _topic_layers_from_breakdown(
    result: SimulationResult,
    impact_breakdown: dict[str, object] | None,
) -> list[dict[str, object]]:
    if impact_breakdown and isinstance(impact_breakdown.get("topicLayers"), list):
        return list(impact_breakdown["topicLayers"])
    return [build_topic_impact_layers(item) for item in result.impacts]


def _to_management_topic(layer: dict[str, object]) -> dict[str, object]:
    return {
        "topic_id": layer["topic_id"],
        "topic_label": layer.get("topic_label"),
        "management_action": layer["management_action"],
        "management_action_label": layer["management_action_label"],
        "dominant_type": layer["dominant_type"],
        "dominant_label": layer["dominant_label"],
        "impact_origin": layer["impact_origin"],
        "impact_origin_label": layer["impact_origin_label"],
        "direct_score": layer[DIRECT_IMPACT]["score"],
        "spillover_score": layer[SPILLOVER_IMPACT]["score"],
        "structural_score": layer[STRUCTURAL_CHANGE]["score"],
        "applied_shocks": list(layer["applied_shocks"]),
        "direct_shocks": list(layer["direct_shocks"]),
        "spillover_shocks": list(layer["spillover_shocks"]),
    }


def _build_executive_summary(
    result: SimulationResult,
    *,
    topic_layers: list[dict[str, object]],
    impact_origin_summary: list[dict[str, object]],
    recommended_add: list[dict[str, object]],
    recommended_stop_loss: list[dict[str, object]],
    side_effect_topics: list[dict[str, object]],
    observe_count: int,
) -> list[str]:
    total_topics = len({_topic_label_key_from_layer(layer) for layer in topic_layers})
    return [
        (
            f"本次推演覆盖 {total_topics} 个主题。"
            f"建议加码 {len(recommended_add)} 个主题，"
            f"建议止损 {len(recommended_stop_loss)} 个主题，"
            f"需重点防副作用 {len(side_effect_topics)} 个主题，"
            f"其余 {observe_count} 个主题继续观察。"
        ),
        f"影响来源分布: {_impact_origin_distribution_text(impact_origin_summary)}。",
        (
            "直接影响主要看申报、立项与合同经费的即时变化；"
            f"当前最值得加码的是 {_topic_names(recommended_add)}。"
        ),
        (
            "外溢影响主要看协作扩散是否形成联动；"
            f"当前外溢带动最强的是 {_topic_names(_top_origin_topics(topic_layers, {'spillover', 'mixed'}, SPILLOVER_IMPACT))}。"
        ),
        (
            "结构变化重点看主题中心性、热点迁移与风险是否同步改善；"
            f"当前需要重点控风险的是 {_topic_names(side_effect_topics or recommended_stop_loss)}。"
        ),
    ]


def _management_priority(
    item: SimulationTopicImpact,
    layers: dict[str, dict[str, object]],
    action: str,
) -> float:
    direct_score = abs(float(layers[DIRECT_IMPACT]["score"]))
    spillover_score = abs(float(layers[SPILLOVER_IMPACT]["score"]))
    structural_score = abs(float(layers[STRUCTURAL_CHANGE]["score"]))
    if action == "add":
        return round(direct_score + 0.5 * spillover_score + 0.5 * structural_score, 6)
    if action == "stop_loss":
        return round(abs(min(float(layers[DIRECT_IMPACT]["score"]), 0.0)) + max(item.delta_proxy_risk, 0.0), 6)
    if action == "side_effect":
        return round(max(item.delta_proxy_risk, 0.0) + 0.5 * direct_score + structural_score, 6)
    return round(direct_score + spillover_score + structural_score, 6)


def _topic_names(topic_layers: list[dict[str, object]]) -> str:
    if not topic_layers:
        return "暂无显著主题"
    return "、".join(_topic_label_from_layer(item) for item in topic_layers[:3])


def _impact_origin_counts(topic_layers: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered_origins = ("direct", "spillover", "mixed", "none")
    return [
        {
            "impact_origin": origin,
            "label": _IMPACT_ORIGIN_LABELS[origin],
            "topic_count": sum(1 for layer in topic_layers if layer["impact_origin"] == origin),
            "sample_topics": _unique_sample_topics(
                [layer for layer in topic_layers if layer["impact_origin"] == origin]
            ),
        }
        for origin in ordered_origins
    ]


def _impact_origin_distribution_text(impact_origin_summary: list[dict[str, object]]) -> str:
    return "，".join(
        f"{item['label']} {item['topic_count']} 个主题"
        for item in impact_origin_summary
    )


def _top_origin_topics(
    topic_layers: list[dict[str, object]],
    origins: set[str],
    impact_type: str,
    limit: int = 3,
) -> list[dict[str, object]]:
    ranked = sorted(
        (layer for layer in topic_layers if layer["impact_origin"] in origins),
        key=lambda layer: abs(float(layer[impact_type]["score"])),
        reverse=True,
    )
    return _top_unique_layers(ranked, limit=limit)


def _top_unique_impacts(
    impacts: list[SimulationTopicImpact],
    *,
    score_fn,
    limit: int,
) -> list[SimulationTopicImpact]:
    ranked = sorted(impacts, key=score_fn, reverse=True)
    selected: list[SimulationTopicImpact] = []
    seen: set[str] = set()
    for item in ranked:
        key = _topic_label_key(item)
        if key in seen:
            continue
        selected.append(item)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def _top_unique_layers(
    layers: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    for layer in layers:
        key = _topic_label_key_from_layer(layer)
        if key in seen:
            continue
        selected.append(layer)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def _unique_sample_topics(topic_layers: list[dict[str, object]], limit: int = 3) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for layer in topic_layers:
        label = _topic_label_from_layer(layer)
        key = _topic_label_key_from_layer(layer)
        if key in seen:
            continue
        output.append(label)
        seen.add(key)
        if len(output) >= limit:
            break
    return output


def _topic_label(item: SimulationTopicImpact | SimulationComparisonTopic) -> str:
    label = str(getattr(item, "topic_label", "") or "").strip()
    if label:
        return label
    return _fallback_topic_label(str(getattr(item, "topic_id", "") or ""))


def _topic_label_key(item: SimulationTopicImpact | SimulationComparisonTopic) -> str:
    return _normalize_topic_label(_topic_label(item))


def _topic_label_from_layer(layer: dict[str, object]) -> str:
    label = str(layer.get("topic_label") or "").strip()
    if label:
        return label
    return _fallback_topic_label(str(layer.get("topic_id") or ""))


def _topic_label_key_from_layer(layer: dict[str, object]) -> str:
    return _normalize_topic_label(_topic_label_from_layer(layer))


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
