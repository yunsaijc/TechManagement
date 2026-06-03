"""Scenario contract builders and legacy adapters."""

from __future__ import annotations

from typing import Any

from src.common.models.simulation import (
    BaselineScope,
    PolicyAction,
    ScenarioConstraint,
    ScenarioContract,
    TargetScope,
)


def build_scenario_contract(
    *,
    scenario_id: str,
    baseline_id: str,
    forecast_window: str,
    actions: list[PolicyAction] | None = None,
    constraints: list[ScenarioConstraint] | None = None,
    tags: list[str] | None = None,
    assumptions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    **extra_fields: Any,
) -> ScenarioContract:
    return ScenarioContract(
        scenario_id=scenario_id,
        baseline=BaselineScope(baseline_id=baseline_id),
        forecast_window=forecast_window,
        actions=actions or [],
        constraints=constraints or [],
        tags=tags or [],
        assumptions=assumptions or [],
        metadata=metadata or {},
        **extra_fields,
    )


def build_compose_constraints(
    *,
    budget_limit: float | None = None,
    spillover_budget_share: float | None = None,
    max_risk_increase: float | None = None,
) -> list[ScenarioConstraint]:
    constraints: list[ScenarioConstraint] = []
    if budget_limit is not None:
        constraints.append(ScenarioConstraint(constraint_type="budget_limit", value=budget_limit, hard_limit=True))
    if spillover_budget_share is not None:
        constraints.append(
            ScenarioConstraint(
                constraint_type="spillover_budget_share",
                value=spillover_budget_share,
            )
        )
    if max_risk_increase is not None:
        constraints.append(
            ScenarioConstraint(
                constraint_type="max_risk_increase",
                value=max_risk_increase,
                hard_limit=True,
            )
        )
    return constraints


def adapt_legacy_policy_shocks_to_contract(
    *,
    scenario_id: str,
    baseline_id: str,
    forecast_window: str,
    policy_shocks: list[dict[str, Any]],
    tags: list[str] | None = None,
    assumptions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ScenarioContract:
    actions = [
        PolicyAction(
            action_id=str(item.get("shock_id") or item.get("shockId") or f"action_{index}"),
            action_type=str(item.get("shock_type") or item.get("shockType") or "funding_boost"),
            target_scope=TargetScope(
                topic_ids=list(item.get("target_topics") or item.get("targetTopics") or []),
                enable_spillover=bool((item.get("parameters") or {}).get("enable_spillover", False)),
                propagation_strength=_optional_float((item.get("parameters") or {}).get("propagation_strength")),
                min_similarity=_optional_float((item.get("parameters") or {}).get("min_similarity")),
                max_neighbors=_optional_int((item.get("parameters") or {}).get("max_neighbors")),
            ),
            intensity=float(item.get("intensity", 0.5)),
            coverage=float(item.get("coverage", 1.0)),
            lag=int(item.get("lag", 0)),
            parameters=dict(item.get("parameters") or {}),
        )
        for index, item in enumerate(policy_shocks, start=1)
    ]
    contract_metadata = dict(metadata or {})
    contract_metadata["legacy_adapter"] = {
        "kind": "policy_shocks",
        "shock_count": len(policy_shocks),
    }
    return build_scenario_contract(
        scenario_id=scenario_id,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        actions=actions,
        tags=tags,
        assumptions=assumptions,
        metadata=contract_metadata,
    )


def adapt_legacy_compose_to_contract(
    *,
    scenario_id: str,
    baseline_id: str,
    forecast_window: str,
    topic_id: str | None,
    shock_type: str,
    intensity: float,
    coverage: float,
    lag: int,
    enable_spillover: bool,
    propagation_strength: float,
    min_similarity: float,
    max_neighbors: int,
    actions: list[dict[str, Any]] | None = None,
    constraints: list[ScenarioConstraint] | None = None,
    tags: list[str] | None = None,
    assumptions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ScenarioContract:
    if actions:
        normalized_actions = [
            PolicyAction(
                action_id=str(item.get("action_id") or item.get("actionId") or f"action_{index}"),
                action_type=str(item.get("action_type") or item.get("actionType") or "funding_boost"),
                target_scope=TargetScope(
                    topic_ids=list(
                        (item.get("target_scope") or item.get("targetScope") or {}).get("topic_ids")
                        or (item.get("target_scope") or item.get("targetScope") or {}).get("topicIds")
                        or item.get("target_topics")
                        or item.get("targetTopics")
                        or []
                    ),
                    topic_labels=list(
                        (item.get("target_scope") or item.get("targetScope") or {}).get("topic_labels")
                        or (item.get("target_scope") or item.get("targetScope") or {}).get("topicLabels")
                        or []
                    ),
                    enable_spillover=bool(
                        (item.get("target_scope") or item.get("targetScope") or {}).get("enable_spillover")
                        or (item.get("target_scope") or item.get("targetScope") or {}).get("enableSpillover")
                        or (item.get("parameters") or {}).get("enable_spillover", False)
                    ),
                    propagation_strength=_optional_float(
                        (item.get("target_scope") or item.get("targetScope") or {}).get("propagation_strength")
                        or (item.get("target_scope") or item.get("targetScope") or {}).get("propagationStrength")
                        or (item.get("parameters") or {}).get("propagation_strength")
                    ),
                    min_similarity=_optional_float(
                        (item.get("target_scope") or item.get("targetScope") or {}).get("min_similarity")
                        or (item.get("target_scope") or item.get("targetScope") or {}).get("minSimilarity")
                        or (item.get("parameters") or {}).get("min_similarity")
                    ),
                    max_neighbors=_optional_int(
                        (item.get("target_scope") or item.get("targetScope") or {}).get("max_neighbors")
                        or (item.get("target_scope") or item.get("targetScope") or {}).get("maxNeighbors")
                        or (item.get("parameters") or {}).get("max_neighbors")
                    ),
                ),
                intensity=float(item.get("intensity", 0.5)),
                coverage=float(item.get("coverage", 1.0)),
                lag=int(item.get("lag", 0)),
                parameters=dict(item.get("parameters") or {}),
            )
            for index, item in enumerate(actions, start=1)
        ]
        adapter_kind = "compose_actions"
    else:
        normalized_actions = [
            PolicyAction(
                action_id="action_legacy_compose",
                action_type=shock_type,
                target_scope=TargetScope(
                    topic_ids=[topic_id] if topic_id else [],
                    enable_spillover=enable_spillover,
                    propagation_strength=propagation_strength if enable_spillover else None,
                    min_similarity=min_similarity if enable_spillover else None,
                    max_neighbors=max_neighbors if enable_spillover else None,
                ),
                intensity=intensity,
                coverage=coverage,
                lag=lag,
                parameters={
                    "enable_spillover": enable_spillover,
                    **(
                        {
                            "propagation_strength": propagation_strength,
                            "min_similarity": min_similarity,
                            "max_neighbors": max_neighbors,
                        }
                        if enable_spillover
                        else {}
                    ),
                },
            )
        ]
        adapter_kind = "compose_legacy_fields"

    contract_metadata = dict(metadata or {})
    contract_metadata["legacy_adapter"] = {"kind": adapter_kind}
    if topic_id:
        contract_metadata["legacy_topic_selection"] = topic_id

    return build_scenario_contract(
        scenario_id=scenario_id,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        actions=normalized_actions,
        constraints=constraints,
        tags=tags,
        assumptions=assumptions,
        metadata=contract_metadata,
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
