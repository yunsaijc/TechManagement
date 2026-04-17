"""Compile formal scenario contracts into legacy engine scenarios."""

from __future__ import annotations

from collections import OrderedDict

from src.common.models.simulation import (
    BaselineSnapshot,
    BaselineTopicState,
    CompiledScenario,
    PolicyAction,
    PolicyShock,
    ScenarioConstraint,
    ScenarioConstraints,
    ScenarioContract,
    ScenarioDefinition,
    ValidationDisclosure,
)
from src.services.sandbox.simulation.engine import DEFAULT_RULES

_SUPPORTED_CONSTRAINT_TYPES = {
    "budget_limit",
    "spillover_budget_share",
    "risk_threshold",
    "max_risk_increase",
}


def compile_scenario_contract(
    contract: ScenarioContract,
    *,
    baseline: BaselineSnapshot,
) -> CompiledScenario:
    if contract.baseline.baseline_id != baseline.baseline_id:
        raise ValueError("contract.baseline.baseline_id 与当前 baseline 不一致")

    disclosures: list[ValidationDisclosure] = []
    legacy_adapter = isinstance(contract.metadata.get("legacy_adapter"), dict)
    if legacy_adapter:
        adapter_kind = str(contract.metadata["legacy_adapter"].get("kind") or "unknown")
        disclosures.append(
            ValidationDisclosure(
                code="legacy_adapter_applied",
                severity="info",
                message=f"当前请求通过 legacy adapter 转换为 ScenarioContract，adapter={adapter_kind}",
                field_path="metadata.legacy_adapter",
            )
        )

    baseline_topic_ids = _resolve_topics(
        baseline=baseline,
        requested_topic_ids=contract.baseline.topic_ids,
        requested_topic_labels=contract.baseline.topic_labels,
        disclosures=disclosures,
        field_path="baseline",
    )
    if not baseline_topic_ids:
        baseline_topic_ids = [topic.topic_id for topic in baseline.topics]

    legacy_constraints = _compile_constraints(contract.constraints, disclosures)
    constraint_parameters = _constraint_parameters(legacy_constraints)

    if contract.evaluation_goals:
        disclosures.append(
            ValidationDisclosure(
                code="evaluation_goals_not_enforced",
                severity="warning",
                message="evaluation_goals 当前只做记录与回显，尚未进入 simulation engine 约束求解。",
                field_path="evaluation_goals",
            )
        )

    policy_shocks: list[PolicyShock] = []
    action_target_topic_ids: dict[str, list[str]] = {}
    for index, action in enumerate(contract.actions, start=1):
        resolved_topic_ids = _resolve_action_topic_ids(
            action,
            baseline=baseline,
            baseline_topic_ids=baseline_topic_ids,
            disclosures=disclosures,
            action_index=index - 1,
        )
        action_target_topic_ids[action.action_id] = resolved_topic_ids
        if action.rules:
            disclosures.append(
                ValidationDisclosure(
                    code="policy_rules_not_enforced",
                    severity="warning",
                    message=f"action={action.action_id} 的 rules 仅透传到 compiled parameters，尚未覆盖 engine 默认规则。",
                    field_path=f"actions[{index - 1}].rules",
                )
            )
        if action.action_type not in DEFAULT_RULES:
            disclosures.append(
                ValidationDisclosure(
                    code="action_type_not_supported",
                    severity="warning",
                    message=f"action_type={action.action_type} 未命中当前 engine 规则集，结果可能退化为近似无效动作。",
                    field_path=f"actions[{index - 1}].action_type",
                )
            )
        policy_shocks.append(
            PolicyShock(
                shock_id=action.action_id,
                shock_type=action.action_type,
                target_topics=resolved_topic_ids,
                intensity=action.intensity,
                coverage=action.coverage,
                lag=action.lag,
                parameters=_build_action_parameters(
                    action=action,
                    constraint_parameters=constraint_parameters,
                ),
            )
        )

    scenario_definition = ScenarioDefinition(
        scenario_id=contract.scenario_id,
        baseline_id=contract.baseline.baseline_id,
        forecast_window=contract.forecast_window,
        policy_shocks=policy_shocks,
        constraints=legacy_constraints,
        tags=contract.tags,
        assumptions=contract.assumptions,
    )

    return CompiledScenario(
        contract=contract,
        scenario_definition=scenario_definition,
        support_level=_support_level(legacy_adapter=legacy_adapter, disclosures=disclosures),
        disclosures=disclosures,
        baseline_topic_ids=baseline_topic_ids,
        action_target_topic_ids=action_target_topic_ids,
    )


def _resolve_action_topic_ids(
    action: PolicyAction,
    *,
    baseline: BaselineSnapshot,
    baseline_topic_ids: list[str],
    disclosures: list[ValidationDisclosure],
    action_index: int,
) -> list[str]:
    resolved_topic_ids = _resolve_topics(
        baseline=baseline,
        requested_topic_ids=action.target_scope.topic_ids,
        requested_topic_labels=action.target_scope.topic_labels,
        disclosures=disclosures,
        field_path=f"actions[{action_index}].target_scope",
    )
    if resolved_topic_ids:
        return resolved_topic_ids
    if action.target_scope.topic_ids or action.target_scope.topic_labels:
        disclosures.append(
            ValidationDisclosure(
                code="action_targets_unresolved",
                severity="warning",
                message=f"action={action.action_id} 未解析到任何 baseline topic ids，将退化为 no-op。",
                field_path=f"actions[{action_index}].target_scope",
            )
        )
        return []
    return list(baseline_topic_ids)


def _build_action_parameters(
    *,
    action: PolicyAction,
    constraint_parameters: dict[str, float],
) -> dict[str, object]:
    parameters: dict[str, object] = dict(action.parameters)
    if action.target_scope.enable_spillover:
        parameters.setdefault("enable_spillover", True)
    if action.target_scope.propagation_strength is not None:
        parameters.setdefault("propagation_strength", action.target_scope.propagation_strength)
    if action.target_scope.min_similarity is not None:
        parameters.setdefault("min_similarity", action.target_scope.min_similarity)
    if action.target_scope.max_neighbors is not None:
        parameters.setdefault("max_neighbors", action.target_scope.max_neighbors)
    for key, value in constraint_parameters.items():
        parameters.setdefault(key, value)
    if action.rules:
        parameters.setdefault("contract_rules", [rule.model_dump() for rule in action.rules])
    return parameters


def _compile_constraints(
    constraints: list[ScenarioConstraint],
    disclosures: list[ValidationDisclosure],
) -> ScenarioConstraints | None:
    if not constraints:
        return None

    payload: dict[str, float | None] = {
        "budget_limit": None,
        "spillover_budget_share": None,
        "risk_threshold": None,
        "max_risk_increase": None,
    }
    for index, constraint in enumerate(constraints):
        key = str(constraint.constraint_type or "").strip().lower()
        if key not in _SUPPORTED_CONSTRAINT_TYPES:
            disclosures.append(
                ValidationDisclosure(
                    code="constraint_type_not_supported",
                    severity="warning",
                    message=f"constraint_type={constraint.constraint_type} 当前未映射到 legacy engine。",
                    field_path=f"constraints[{index}].constraint_type",
                )
            )
            continue
        value = _optional_float(constraint.value)
        if value is None:
            disclosures.append(
                ValidationDisclosure(
                    code="constraint_value_invalid",
                    severity="warning",
                    message=f"constraint_type={constraint.constraint_type} 的 value 无法转成数值，已忽略。",
                    field_path=f"constraints[{index}].value",
                )
            )
            continue
        payload[key] = value

    if not any(value is not None for value in payload.values()):
        return None
    return ScenarioConstraints(**payload)


def _constraint_parameters(constraints: ScenarioConstraints | None) -> dict[str, float]:
    if constraints is None:
        return {}
    parameters: dict[str, float] = {}
    for key in ("budget_limit", "spillover_budget_share", "risk_threshold", "max_risk_increase"):
        value = getattr(constraints, key)
        if value is not None:
            parameters[key] = value
    return parameters


def _resolve_topics(
    *,
    baseline: BaselineSnapshot,
    requested_topic_ids: list[str],
    requested_topic_labels: list[str],
    disclosures: list[ValidationDisclosure],
    field_path: str,
) -> list[str]:
    by_id = {topic.topic_id: topic for topic in baseline.topics}
    resolved = OrderedDict[str, None]()

    for topic_id in requested_topic_ids:
        if topic_id in by_id:
            resolved[topic_id] = None
            continue
        disclosures.append(
            ValidationDisclosure(
                code="topic_id_not_found",
                severity="warning",
                message=f"topic_id={topic_id} 不存在于当前 baseline。",
                field_path=f"{field_path}.topic_ids",
            )
        )

    for topic_label in requested_topic_labels:
        matches = [topic.topic_id for topic in baseline.topics if _baseline_topic_label(topic) == topic_label]
        if not matches:
            disclosures.append(
                ValidationDisclosure(
                    code="topic_label_not_found",
                    severity="warning",
                    message=f"topic_label={topic_label} 未匹配到当前 baseline。",
                    field_path=f"{field_path}.topic_labels",
                )
            )
            continue
        for topic_id in matches:
            resolved[topic_id] = None
        disclosures.append(
            ValidationDisclosure(
                code="topic_label_resolved",
                severity="info",
                message=f"topic_label={topic_label} 已解析为 {len(matches)} 个 baseline topic ids。",
                field_path=f"{field_path}.topic_labels",
            )
        )

    return list(resolved.keys())


def _baseline_topic_label(topic: BaselineTopicState) -> str:
    label = str(topic.topic_label or "").strip()
    if label:
        return label
    topic_id = str(topic.topic_id or "").strip()
    if "-" not in topic_id:
        return topic_id
    prefix, remainder = topic_id.split("-", 1)
    if prefix and remainder and len(prefix.replace("_", "")) >= 6 and prefix.isascii() and prefix.replace("_", "").isalnum():
        return remainder.strip()
    return topic_id


def _support_level(*, legacy_adapter: bool, disclosures: list[ValidationDisclosure]) -> str:
    if any(item.severity == "error" for item in disclosures):
        return "unsupported"
    if any(item.severity == "warning" for item in disclosures):
        return "partial"
    if legacy_adapter:
        return "legacy_compatible"
    return "supported"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
