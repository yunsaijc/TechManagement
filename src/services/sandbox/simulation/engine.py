"""Native policy simulation engine for sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import log1p

from src.common.models.simulation import (
    BaselineSnapshot,
    BaselineTopicState,
    PolicyShock,
    ScenarioDefinition,
    SimulationReplayFrame,
    SimulationReplayPortfolio,
    SimulationReplayTopic,
    SimulationResult,
    SimulationTopicImpact,
)

DEFAULT_RULES: dict[str, dict[str, float]] = {
    "funding_boost": {
        "application_count": 0.10,
        "funded_count": 0.08,
        "funding_amount": 0.18,
        "score_proxy": 0.03,
        "collaboration_density": 0.02,
        "topic_centrality": 0.03,
        "migration_strength": 0.04,
        "proxy_risk": -0.03,
    },
    "funding_cut": {
        "application_count": -0.08,
        "funded_count": -0.10,
        "funding_amount": -0.18,
        "score_proxy": -0.04,
        "collaboration_density": -0.02,
        "topic_centrality": -0.03,
        "migration_strength": -0.03,
        "proxy_risk": 0.05,
    },
    "topic_priority_shift": {
        "application_count": 0.12,
        "funded_count": 0.07,
        "funding_amount": 0.12,
        "score_proxy": 0.02,
        "collaboration_density": 0.01,
        "topic_centrality": 0.05,
        "migration_strength": 0.08,
        "proxy_risk": -0.01,
    },
    "collaboration_support": {
        "application_count": 0.04,
        "funded_count": 0.03,
        "funding_amount": 0.04,
        "score_proxy": 0.01,
        "collaboration_density": 0.10,
        "topic_centrality": 0.06,
        "migration_strength": 0.05,
        "proxy_risk": -0.03,
    },
    "quota_adjustment": {
        "application_count": 0.06,
        "funded_count": 0.09,
        "funding_amount": 0.07,
        "score_proxy": 0.01,
        "collaboration_density": 0.00,
        "topic_centrality": 0.02,
        "migration_strength": 0.03,
        "proxy_risk": -0.01,
    },
}


@dataclass(frozen=True)
class ShockApplication:
    shock: PolicyShock
    strength: float
    similarity: float = 1.0
    is_direct: bool = True
    budget_scale: float = 1.0
    risk_scale: float = 1.0
    risk_penalty: float = 0.0


REPLAY_STAGE_SPECS = (
    (
        "baseline",
        "当前情况",
        "推演开始前的实际情况。此时还没有政策动作、约束裁剪和外溢传导。",
    ),
    (
        "direct_shock",
        "直接作用",
        "先只看政策直接打到目标主题后的原始变化，不含预算和风险裁剪。",
    ),
    (
        "constraint_clip",
        "约束裁剪",
        "将预算约束和风险约束压上去，看直接作用有多少被削弱或拦截。",
    ),
    (
        "spillover",
        "外溢传导",
        "在受约束的直接作用基础上，观察变化如何沿相近主题继续扩散。",
    ),
    (
        "final",
        "最终落点",
        "综合直接作用、约束裁剪与外溢传导后的最终结果，供后续决策解释使用。",
    ),
)


def run_policy_simulation(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> SimulationResult:
    raw_shock_applications = _build_shock_applications(baseline.topics, scenario.policy_shocks)
    shock_applications = _apply_constraint_corrections(
        baseline.topics,
        raw_shock_applications,
    )
    simulation_frames = _build_simulation_frames(
        baseline.topics,
        raw_shock_applications,
        shock_applications,
        scenario.forecast_window,
    )
    impacts = [
        _simulate_topic(
            topic,
            shock_applications.get(topic.topic_id, []),
            scenario.forecast_window,
        )
        for topic in baseline.topics
    ]
    impacts.sort(
        key=lambda item: abs(item.delta_funding_amount)
        + abs(item.delta_funded_count)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_proxy_risk),
        reverse=True,
    )

    budget_constrained_shocks = {
        application.shock.shock_id
        for topic_applications in shock_applications.values()
        for application in topic_applications
        if application.budget_scale < 0.999999
    }
    risk_constrained_shocks = {
        application.shock.shock_id
        for topic_applications in shock_applications.values()
        for application in topic_applications
        if application.risk_scale < 0.999999 or application.risk_penalty > 0.0
    }

    return SimulationResult(
        run_id=datetime.now(UTC).isoformat(),
        scenario_id=scenario.scenario_id,
        baseline_id=baseline.baseline_id,
        forecast_window=scenario.forecast_window,
        impacts=impacts,
        simulation_frames=simulation_frames,
        assumptions=_merge_assumptions(baseline, scenario),
        metadata={
            "engine": "native_policy_simulation_v2_project_graph",
            "shockCount": len(scenario.policy_shocks),
            "spilloverEnabledShockCount": sum(1 for shock in scenario.policy_shocks if _spillover_enabled(shock)),
            "budgetConstrainedShockCount": len(budget_constrained_shocks),
            "riskConstrainedShockCount": len(risk_constrained_shocks),
            "topicCount": len(baseline.topics),
            "impactedTopicCount": sum(1 for item in impacts if _impact_signal(item) > 0.0),
            "replayStageCount": len(simulation_frames),
            "replayStageIds": [frame.stage_id for frame in simulation_frames],
            "scenarioTags": list(scenario.tags),
        },
    )


def _build_simulation_frames(
    topics: list[BaselineTopicState],
    raw_shock_applications: dict[str, list[ShockApplication]],
    constrained_shock_applications: dict[str, list[ShockApplication]],
    forecast_window: str,
) -> list[SimulationReplayFrame]:
    stage_application_sets = {
        "baseline": {topic.topic_id: [] for topic in topics},
        "direct_shock": _stage_applications(raw_shock_applications, direct_only=True, unconstrained=True),
        "constraint_clip": _stage_applications(constrained_shock_applications, direct_only=True),
        "spillover": _stage_applications(constrained_shock_applications),
        "final": _stage_applications(constrained_shock_applications),
    }
    frames: list[SimulationReplayFrame] = []
    for stage_order, (stage_id, stage_label, narrative) in enumerate(REPLAY_STAGE_SPECS):
        replay_topics = [
            _simulate_replay_topic(
                topic,
                stage_application_sets[stage_id].get(topic.topic_id, []),
                forecast_window,
            )
            for topic in topics
        ]
        replay_topics.sort(key=_replay_topic_sort_key, reverse=True)
        frames.append(
            SimulationReplayFrame(
                stage_id=stage_id,
                stage_label=stage_label,
                stage_order=stage_order,
                narrative=narrative,
                portfolio=_build_replay_portfolio(replay_topics),
                topics=replay_topics,
            )
        )
    return frames


def _stage_applications(
    applications: dict[str, list[ShockApplication]],
    *,
    direct_only: bool = False,
    unconstrained: bool = False,
) -> dict[str, list[ShockApplication]]:
    output: dict[str, list[ShockApplication]] = {}
    for topic_id, topic_applications in applications.items():
        filtered = []
        for application in topic_applications:
            if direct_only and not application.is_direct:
                continue
            filtered.append(_unconstrained_application(application) if unconstrained else application)
        output[topic_id] = filtered
    return output


def _unconstrained_application(application: ShockApplication) -> ShockApplication:
    return ShockApplication(
        shock=application.shock,
        strength=application.strength,
        similarity=application.similarity,
        is_direct=application.is_direct,
        budget_scale=1.0,
        risk_scale=1.0,
        risk_penalty=0.0,
    )


def _simulate_replay_topic(
    topic: BaselineTopicState,
    shock_applications: list[ShockApplication],
    forecast_window: str,
) -> SimulationReplayTopic:
    impact = _simulate_topic(topic, shock_applications, forecast_window)
    return SimulationReplayTopic(
        **impact.model_dump(),
        active_constraints=_topic_constraints(shock_applications),
    )


def _topic_constraints(shock_applications: list[ShockApplication]) -> list[str]:
    constraints: list[str] = []
    if any(application.budget_scale < 0.999999 for application in shock_applications):
        constraints.append("budget_guardrail")
    if any(
        application.risk_scale < 0.999999 or application.risk_penalty > 0.0
        for application in shock_applications
    ):
        constraints.append("risk_guardrail")
    return constraints


def _build_replay_portfolio(topics: list[SimulationReplayTopic]) -> SimulationReplayPortfolio:
    topic_count = len(topics)
    impacted_topic_count = sum(1 for item in topics if _impact_signal(item) > 0.0)
    positive_funding_topic_count = sum(1 for item in topics if item.delta_funding_amount > 0.0)
    negative_funding_topic_count = sum(1 for item in topics if item.delta_funding_amount < 0.0)
    positive_risk_topic_count = sum(1 for item in topics if item.delta_proxy_risk > 0.0)
    net_delta_funding_amount = round(sum(item.delta_funding_amount for item in topics), 6)
    net_delta_funded_count = sum(item.delta_funded_count for item in topics)
    avg_delta_proxy_risk = round(sum(item.delta_proxy_risk for item in topics) / max(topic_count, 1), 6)
    direct_topic_count = sum(1 for item in topics if item.impact_origin == "direct")
    spillover_topic_count = sum(1 for item in topics if item.impact_origin == "spillover")
    mixed_topic_count = sum(1 for item in topics if item.impact_origin == "mixed")
    constrained_topic_count = sum(1 for item in topics if item.active_constraints)
    return SimulationReplayPortfolio(
        topic_count=topic_count,
        impacted_topic_count=impacted_topic_count,
        positive_funding_topic_count=positive_funding_topic_count,
        negative_funding_topic_count=negative_funding_topic_count,
        positive_risk_topic_count=positive_risk_topic_count,
        net_delta_funding_amount=net_delta_funding_amount,
        net_delta_funded_count=net_delta_funded_count,
        avg_delta_proxy_risk=avg_delta_proxy_risk,
        direct_topic_count=direct_topic_count,
        spillover_topic_count=spillover_topic_count,
        mixed_topic_count=mixed_topic_count,
        constrained_topic_count=constrained_topic_count,
    )


def _replay_topic_sort_key(item: SimulationReplayTopic) -> float:
    return (
        abs(item.delta_funding_amount)
        + abs(item.delta_funded_count)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_proxy_risk)
    )


def _build_shock_applications(
    topics: list[BaselineTopicState],
    shocks: list[PolicyShock],
) -> dict[str, list[ShockApplication]]:
    topic_by_id = {topic.topic_id: topic for topic in topics}
    applications: dict[str, list[ShockApplication]] = {topic.topic_id: [] for topic in topics}

    for shock in shocks:
        base_strength = _shock_strength(shock)
        if base_strength <= 0.0:
            continue

        if shock.target_topics:
            target_ids = [topic_id for topic_id in shock.target_topics if topic_id in topic_by_id]
        else:
            target_ids = [topic.topic_id for topic in topics]

        if not target_ids:
            continue

        for topic_id in target_ids:
            applications[topic_id].append(
                ShockApplication(
                    shock=shock,
                    strength=base_strength,
                )
            )

        if not _spillover_enabled(shock) or not shock.target_topics:
            continue

        propagation_strength = _shock_parameter_float(shock, "propagation_strength", 0.35)
        min_similarity = _shock_parameter_float(shock, "min_similarity", 0.55)
        max_neighbors = max(0, int(_shock_parameter_float(shock, "max_neighbors", 8)))
        if propagation_strength <= 0.0 or max_neighbors == 0:
            continue

        spillover_scores: dict[str, ShockApplication] = {}
        direct_ids = set(target_ids)
        allowed_spillover_topic_ids = _document_allowed_topic_ids(shock, direct_ids=direct_ids)
        for target_id in target_ids:
            source = topic_by_id[target_id]
            for candidate in topics:
                if candidate.topic_id in direct_ids:
                    continue
                if allowed_spillover_topic_ids is not None and candidate.topic_id not in allowed_spillover_topic_ids:
                    continue
                similarity = _topic_similarity(source, candidate)
                if similarity < min_similarity:
                    continue
                spillover_strength = base_strength * propagation_strength * similarity
                current = spillover_scores.get(candidate.topic_id)
                if current is None or spillover_strength > current.strength:
                    spillover_scores[candidate.topic_id] = ShockApplication(
                        shock=shock,
                        strength=spillover_strength,
                        similarity=similarity,
                        is_direct=False,
                    )

        for topic_id, application in sorted(
            spillover_scores.items(),
            key=lambda item: item[1].strength,
            reverse=True,
        )[:max_neighbors]:
            if application.strength > 0.0:
                applications[topic_id].append(application)

    return applications


def _apply_constraint_corrections(
    topics: list[BaselineTopicState],
    applications: dict[str, list[ShockApplication]],
) -> dict[str, list[ShockApplication]]:
    topic_by_id = {topic.topic_id: topic for topic in topics}
    corrected: dict[str, list[ShockApplication]] = {topic.topic_id: [] for topic in topics}
    entries_by_shock: dict[str, list[tuple[BaselineTopicState, ShockApplication]]] = {}

    for topic_id, topic_applications in applications.items():
        topic = topic_by_id[topic_id]
        for application in topic_applications:
            entries_by_shock.setdefault(application.shock.shock_id, []).append((topic, application))

    for entries in entries_by_shock.values():
        if not entries:
            continue

        rules = _shock_rules(entries[0][1].shock)
        per_topic_risk: dict[str, float] = {}
        per_topic_penalty: dict[str, float] = {}
        per_topic_positive_funding: dict[str, float] = {}

        for topic, application in entries:
            risk_scale = _risk_scale(topic, application, rules)
            per_topic_risk[topic.topic_id] = risk_scale
            per_topic_penalty[topic.topic_id] = _risk_penalty(application, rules, risk_scale)
            per_topic_positive_funding[topic.topic_id] = _positive_funding_delta(topic, application, rules, risk_scale)

        budget_scales = _budget_scales(entries, per_topic_positive_funding, rules)
        for topic, application in entries:
            corrected[topic.topic_id].append(
                ShockApplication(
                    shock=application.shock,
                    strength=application.strength,
                    similarity=application.similarity,
                    is_direct=application.is_direct,
                    budget_scale=budget_scales.get(topic.topic_id, 1.0),
                    risk_scale=per_topic_risk.get(topic.topic_id, 1.0),
                    risk_penalty=per_topic_penalty.get(topic.topic_id, 0.0),
                )
            )

    return corrected


def _simulate_topic(
    topic: BaselineTopicState,
    shock_applications: list[ShockApplication],
    forecast_window: str,
) -> SimulationTopicImpact:
    application_count = float(topic.application_count)
    funded_count = float(topic.funded_count)
    funding_amount = topic.funding_amount
    score_proxy = _score_or_zero(topic.score_proxy)
    collaboration_density = topic.collaboration_density
    topic_centrality = topic.topic_centrality
    migration_strength = topic.migration_strength
    proxy_risk = topic.proxy_risk
    applied_shocks: list[str] = []
    direct_shocks: list[str] = []
    spillover_shocks: list[str] = []

    for application in shock_applications:
        rules = _shock_rules(application.shock)

        application_count += topic.application_count * _constrained_rate(rules["application_count"], application)
        funded_count += max(topic.funded_count, 1) * _constrained_rate(rules["funded_count"], application)
        funding_amount += topic.funding_amount * _constrained_rate(rules["funding_amount"], application)
        score_proxy += score_proxy * _constrained_rate(rules["score_proxy"], application)
        collaboration_density += _constrained_delta(rules["collaboration_density"], application)
        topic_centrality += _constrained_delta(rules["topic_centrality"], application)
        migration_strength += _constrained_delta(rules["migration_strength"], application)
        proxy_risk += _proxy_risk_delta(rules["proxy_risk"], application)
        _append_unique(applied_shocks, application.shock.shock_id)
        if application.is_direct:
            _append_unique(direct_shocks, application.shock.shock_id)
        else:
            _append_unique(spillover_shocks, application.shock.shock_id)

    projected_application_count = _round_count(application_count)
    projected_funded_count = _round_count(funded_count)
    projected_funding_amount = _round_amount(funding_amount)
    projected_score_proxy = _round_nullable(score_proxy)
    projected_collaboration_density = _clamp_unit(collaboration_density)
    projected_topic_centrality = _clamp_unit(topic_centrality)
    projected_migration_strength = _clamp_unit(migration_strength)
    projected_proxy_risk = _clamp_unit(proxy_risk)

    return SimulationTopicImpact(
        topic_id=topic.topic_id,
        topic_label=topic.topic_label,
        forecast_window=forecast_window,
        baseline_application_count=topic.application_count,
        projected_application_count=projected_application_count,
        delta_application_count=projected_application_count - topic.application_count,
        baseline_funded_count=topic.funded_count,
        projected_funded_count=projected_funded_count,
        delta_funded_count=projected_funded_count - topic.funded_count,
        baseline_funding_amount=topic.funding_amount,
        projected_funding_amount=projected_funding_amount,
        delta_funding_amount=round(projected_funding_amount - topic.funding_amount, 6),
        baseline_score_proxy=topic.score_proxy,
        projected_score_proxy=projected_score_proxy,
        delta_score_proxy=_delta_nullable(projected_score_proxy, topic.score_proxy),
        baseline_collaboration_density=topic.collaboration_density,
        projected_collaboration_density=projected_collaboration_density,
        delta_collaboration_density=round(projected_collaboration_density - topic.collaboration_density, 6),
        baseline_topic_centrality=topic.topic_centrality,
        projected_topic_centrality=projected_topic_centrality,
        delta_topic_centrality=round(projected_topic_centrality - topic.topic_centrality, 6),
        baseline_migration_strength=topic.migration_strength,
        projected_migration_strength=projected_migration_strength,
        delta_migration_strength=round(projected_migration_strength - topic.migration_strength, 6),
        baseline_proxy_risk=topic.proxy_risk,
        projected_proxy_risk=projected_proxy_risk,
        delta_proxy_risk=round(projected_proxy_risk - topic.proxy_risk, 6),
        applied_shocks=applied_shocks,
        direct_shocks=direct_shocks,
        spillover_shocks=spillover_shocks,
        impact_origin=_impact_origin(direct_shocks, spillover_shocks),
    )


def _merge_assumptions(
    baseline: BaselineSnapshot,
    scenario: ScenarioDefinition,
) -> list[str]:
    assumptions = list(baseline.assumptions)
    assumptions.extend(scenario.assumptions)
    assumptions.append("project_graph_policy_shocks_apply_with_lag_discount")
    if scenario.policy_shocks:
        assumptions.append("project_graph_policy_shocks_apply_budget_guardrails")
        assumptions.append("project_graph_policy_shocks_apply_risk_guardrails")
    if any(_shock_parameter_float(shock, "document_budget_cap", -1.0) >= 0.0 for shock in scenario.policy_shocks):
        assumptions.append("policy_documents_compile_budget_cap_guardrails")
    if any(_document_eligibility_gate_enabled(shock) for shock in scenario.policy_shocks):
        assumptions.append("policy_documents_compile_eligibility_guardrails")
    if any(_spillover_enabled(shock) for shock in scenario.policy_shocks):
        assumptions.append("project_graph_policy_shocks_apply_similarity_spillover")
        assumptions.append("project_graph_policy_shocks_apply_structural_similarity_spillover")
    return assumptions


def _impact_signal(item: SimulationTopicImpact) -> float:
    return (
        abs(item.delta_application_count)
        + abs(item.delta_funded_count)
        + abs(item.delta_funding_amount)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_migration_strength)
        + abs(item.delta_proxy_risk)
    )


def _impact_origin(direct_shocks: list[str], spillover_shocks: list[str]) -> str:
    if direct_shocks and spillover_shocks:
        return "mixed"
    if direct_shocks:
        return "direct"
    if spillover_shocks:
        return "spillover"
    return "none"


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _shock_strength(shock: PolicyShock) -> float:
    lag_factor = max(0.35, 1.0 - 0.15 * shock.lag)
    return shock.intensity * shock.coverage * lag_factor


def _spillover_enabled(shock: PolicyShock) -> bool:
    return bool(shock.parameters.get("enable_spillover", False))


def _document_eligibility_gate_enabled(shock: PolicyShock) -> bool:
    compiled_guardrails = shock.parameters.get("compiled_guardrails")
    if isinstance(compiled_guardrails, dict) and bool(compiled_guardrails.get("eligibility_gate")):
        return True
    constraint_types = shock.parameters.get("document_constraint_types")
    if isinstance(constraint_types, (list, tuple, set)):
        return "eligibility_gate" in {str(item).strip() for item in constraint_types}
    return False


def _document_allowed_topic_ids(
    shock: PolicyShock,
    *,
    direct_ids: set[str],
) -> set[str] | None:
    if not _document_eligibility_gate_enabled(shock):
        return None
    compiled_guardrails = shock.parameters.get("compiled_guardrails")
    if not isinstance(compiled_guardrails, dict):
        return set(direct_ids)
    topic_ids = compiled_guardrails.get("topic_ids")
    if not isinstance(topic_ids, (list, tuple, set)):
        return set(direct_ids)
    normalized = {str(item).strip() for item in topic_ids if str(item).strip()}
    return normalized or set(direct_ids)


def _shock_parameter_float(shock: PolicyShock, key: str, default: float) -> float:
    value = shock.parameters.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _topic_similarity(source: BaselineTopicState, candidate: BaselineTopicState) -> float:
    scale_similarity = _mean(
        [
            _ratio_similarity(float(source.application_count), float(candidate.application_count)),
            _ratio_similarity(float(source.funded_count), float(candidate.funded_count)),
            _ratio_similarity(source.funding_amount, candidate.funding_amount),
            _ratio_similarity(_average_award_size(source), _average_award_size(candidate)),
        ]
    )
    structure_similarity = _mean(
        [
            1.0 - abs(source.collaboration_density - candidate.collaboration_density),
            1.0 - abs(source.topic_centrality - candidate.topic_centrality),
            1.0 - abs(source.migration_strength - candidate.migration_strength),
            _ratio_similarity(_delivery_rate(source), _delivery_rate(candidate)),
        ]
    )
    quality_similarity = _mean(
        [
            _score_similarity(source.score_proxy, candidate.score_proxy),
            1.0 - abs(source.proxy_risk - candidate.proxy_risk),
        ]
    )
    code_similarity = _topic_code_similarity(source.topic_id, candidate.topic_id)
    return max(
        0.0,
        min(
            1.0,
            0.10 * code_similarity
            + 0.35 * scale_similarity
            + 0.35 * structure_similarity
            + 0.20 * quality_similarity,
        ),
    )


def _topic_code_similarity(source_topic_id: str, candidate_topic_id: str) -> float:
    source_code = _topic_code(source_topic_id)
    candidate_code = _topic_code(candidate_topic_id)
    if not source_code or not candidate_code:
        return 0.0

    max_len = min(len(source_code), len(candidate_code))
    prefix_len = 0
    for index in range(max_len):
        if source_code[index] != candidate_code[index]:
            break
        prefix_len += 1
    return prefix_len / max_len if max_len else 0.0


def _topic_code(topic_id: str) -> str:
    head = str(topic_id).split("-", 1)[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    return digits


def _score_similarity(source: float | None, candidate: float | None) -> float:
    if source is None or candidate is None:
        return 0.5
    return max(0.0, 1.0 - abs(source - candidate) / 30.0)


def _shock_rules(shock: PolicyShock) -> dict[str, float]:
    return DEFAULT_RULES.get(
        shock.shock_type,
        {
            "application_count": 0.0,
            "funded_count": 0.0,
            "funding_amount": 0.0,
            "score_proxy": 0.0,
            "collaboration_density": 0.0,
            "topic_centrality": 0.0,
            "migration_strength": 0.0,
            "proxy_risk": 0.0,
        },
    )


def _risk_scale(
    topic: BaselineTopicState,
    application: ShockApplication,
    rules: dict[str, float],
) -> float:
    if not _has_positive_pressure(rules):
        return 1.0

    stability = 1.0 - topic.proxy_risk
    execution = _mean(
        [
            topic.collaboration_density,
            topic.topic_centrality,
            _delivery_rate(topic),
            _score_capacity(topic.score_proxy),
        ]
    )
    capacity = 0.45 * stability + 0.35 * execution + 0.20 * topic.migration_strength
    spillover_discount = 1.0 if application.is_direct else max(0.7, application.similarity)
    return max(0.35, min(1.0, round(0.15 + capacity * spillover_discount, 6)))


def _risk_penalty(
    application: ShockApplication,
    rules: dict[str, float],
    risk_scale: float,
) -> float:
    if not _has_positive_pressure(rules):
        return 0.0
    if rules["proxy_risk"] >= 0.0:
        return 0.0
    spillover_factor = 1.0 if application.is_direct else 0.7
    return round(0.02 * application.strength * (1.0 - risk_scale) * spillover_factor, 6)


def _positive_funding_delta(
    topic: BaselineTopicState,
    application: ShockApplication,
    rules: dict[str, float],
    risk_scale: float,
) -> float:
    if rules["funding_amount"] <= 0.0:
        return 0.0
    return topic.funding_amount * rules["funding_amount"] * application.strength * risk_scale


def _budget_scales(
    entries: list[tuple[BaselineTopicState, ShockApplication]],
    per_topic_positive_funding: dict[str, float],
    rules: dict[str, float],
) -> dict[str, float]:
    if rules["funding_amount"] <= 0.0:
        return {}

    shock = entries[0][1].shock
    document_budget_cap = _shock_parameter_float(shock, "document_budget_cap", -1.0)
    per_topic_document_scales: dict[str, float] = {}
    if document_budget_cap >= 0.0:
        for topic, _ in entries:
            positive_delta = per_topic_positive_funding.get(topic.topic_id, 0.0)
            if positive_delta <= 0.0:
                per_topic_document_scales[topic.topic_id] = 1.0
                continue
            baseline_award_count = max(topic.funded_count, 1)
            allowed_total_funding = document_budget_cap * baseline_award_count
            allowed_positive_delta = max(0.0, allowed_total_funding - topic.funding_amount)
            per_topic_document_scales[topic.topic_id] = min(1.0, allowed_positive_delta / positive_delta)

    explicit_budget_limit = _shock_parameter_float(shock, "budget_limit", -1.0)
    if explicit_budget_limit >= 0.0:
        proposed_positive_total = sum(per_topic_positive_funding.values())
        if proposed_positive_total <= 0.0:
            return per_topic_document_scales
        scale = min(1.0, explicit_budget_limit / proposed_positive_total)
        return {
            topic.topic_id: min(
                per_topic_document_scales.get(topic.topic_id, 1.0),
                scale if per_topic_positive_funding.get(topic.topic_id, 0.0) > 0.0 else 1.0,
            )
            for topic, _ in entries
        }

    direct_budget = sum(
        topic.funding_amount * rules["funding_amount"] * _shock_strength(application.shock)
        for topic, application in entries
        if application.is_direct
    )
    if direct_budget <= 0.0:
        return per_topic_document_scales

    spillover_budget_share = max(0.0, _shock_parameter_float(shock, "spillover_budget_share", 0.25))
    direct_positive_total = sum(
        per_topic_positive_funding.get(topic.topic_id, 0.0)
        for topic, application in entries
        if application.is_direct
    )
    direct_scale = 1.0 if direct_positive_total <= 0.0 else min(1.0, direct_budget / direct_positive_total)
    spillover_budget = max(0.0, direct_budget * spillover_budget_share)
    spillover_positive_total = sum(
        per_topic_positive_funding.get(topic.topic_id, 0.0)
        for topic, application in entries
        if not application.is_direct
    )
    spillover_scale = 1.0 if spillover_positive_total <= 0.0 else min(1.0, spillover_budget / spillover_positive_total)

    return {
        topic.topic_id: min(
            per_topic_document_scales.get(topic.topic_id, 1.0),
            direct_scale if application.is_direct else spillover_scale,
        )
        for topic, application in entries
    }


def _constrained_rate(rule_rate: float, application: ShockApplication) -> float:
    rate = rule_rate * application.strength
    if rate > 0.0:
        rate *= application.risk_scale * application.budget_scale
    return rate


def _constrained_delta(rule_delta: float, application: ShockApplication) -> float:
    delta = rule_delta * application.strength
    if delta > 0.0:
        delta *= application.risk_scale * application.budget_scale
    return delta


def _proxy_risk_delta(rule_delta: float, application: ShockApplication) -> float:
    delta = rule_delta * application.strength
    if delta < 0.0:
        delta *= application.budget_scale * (0.5 + 0.5 * application.risk_scale)
    return delta + application.risk_penalty


def _has_positive_pressure(rules: dict[str, float]) -> bool:
    return any(
        rules[key] > 0.0
        for key in (
            "application_count",
            "funded_count",
            "funding_amount",
            "score_proxy",
            "collaboration_density",
            "topic_centrality",
            "migration_strength",
        )
    )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _ratio_similarity(source: float, candidate: float) -> float:
    source_value = max(0.0, source)
    candidate_value = max(0.0, candidate)
    if source_value == 0.0 and candidate_value == 0.0:
        return 1.0
    high = max(source_value, candidate_value, 1e-9)
    low = min(source_value, candidate_value)
    return max(0.0, min(1.0, low / high))


def _delivery_rate(topic: BaselineTopicState) -> float:
    if topic.application_count <= 0:
        return 0.0
    return max(0.0, min(1.0, topic.funded_count / topic.application_count))


def _average_award_size(topic: BaselineTopicState) -> float:
    if topic.funded_count <= 0:
        return 0.0
    return topic.funding_amount / topic.funded_count


def _score_capacity(score: float | None) -> float:
    if score is None:
        return 0.5
    normalized = log1p(max(0.0, score)) / log1p(100.0)
    return max(0.0, min(1.0, normalized))


def _score_or_zero(value: float | None) -> float:
    return float(value or 0.0)


def _round_count(value: float) -> int:
    return max(0, int(round(value)))


def _round_amount(value: float) -> float:
    return round(max(0.0, value), 6)


def _round_nullable(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, value), 6)


def _delta_nullable(projected: float | None, baseline: float | None) -> float | None:
    if projected is None or baseline is None:
        if projected is None and baseline is None:
            return None
        return round((projected or 0.0) - (baseline or 0.0), 6)
    return round(projected - baseline, 6)


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))
