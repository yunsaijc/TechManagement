"""Compile formal scenario contracts into legacy engine scenarios."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass

from src.common.models.simulation import (
    BasisDocumentRef,
    BaselineSnapshot,
    BaselineTopicState,
    CompiledPolicyAction,
    CompiledScenario,
    PolicyAction,
    PolicyShock,
    ScenarioConstraint,
    ScenarioConstraints,
    ScenarioContract,
    ScenarioDefinition,
    ValidationDisclosure,
)
from src.services.sandbox.data import PolicyBinding, PolicyDocument, SandboxDataService
from src.services.sandbox.simulation.engine import DEFAULT_RULES

_SUPPORTED_CONSTRAINT_TYPES = {
    "budget_limit",
    "spillover_budget_share",
    "risk_threshold",
    "max_risk_increase",
}

_DOCUMENT_CONSTRAINT_TYPES = {
    "budget_cap",
    "budget_floor",
    "quota_limit",
    "eligibility_gate",
    "ratio_requirement",
}


@dataclass(frozen=True)
class _PolicyContext:
    documents_by_id: dict[str, PolicyDocument]
    bindings_by_document_id: dict[str, list[PolicyBinding]]
    topic_ids_by_program_id: dict[str, list[str]]
    window_start_year: int | None
    window_end_year: int | None


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

    policy_context = _load_policy_context(contract=contract, baseline=baseline, disclosures=disclosures)
    basis_documents = _resolve_contract_basis_documents(
        contract=contract,
        policy_context=policy_context,
        disclosures=disclosures,
    )
    basis_document_ids = [item.document_id for item in basis_documents]

    legacy_constraints = _compile_constraints(
        contract.constraints,
        disclosures,
        contract_basis_document_ids=basis_document_ids,
        policy_context=policy_context,
    )
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
    compiled_actions: list[CompiledPolicyAction] = []
    action_target_topic_ids: dict[str, list[str]] = {}
    for index, action in enumerate(contract.actions, start=1):
        action_basis_document_ids = _resolve_action_basis_document_ids(
            action=action,
            contract_basis_documents=basis_documents,
            policy_context=policy_context,
            disclosures=disclosures,
            action_index=index - 1,
        )
        document_scope = _collect_document_scope(action_basis_document_ids, policy_context)
        resolved_stage = _resolve_action_stage(
            action=action,
            action_basis_document_ids=action_basis_document_ids,
            policy_context=policy_context,
            disclosures=disclosures,
            action_index=index - 1,
        )
        resolved_topic_ids = _resolve_action_topic_ids(
            action,
            baseline=baseline,
            baseline_topic_ids=baseline_topic_ids,
            disclosures=disclosures,
            action_index=index - 1,
            document_scope=document_scope,
        )
        action_target_topic_ids[action.action_id] = resolved_topic_ids
        compiled_guardrails = _compile_action_guardrails(
            action_basis_document_ids=action_basis_document_ids,
            document_scope=document_scope,
        )
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
        if action_basis_document_ids and not resolved_topic_ids:
            disclosures.append(
                ValidationDisclosure(
                    code="document_scope_compiled_to_noop",
                    severity="warning",
                    message=f"action={action.action_id} 虽有正式文本依据，但文本范围未映射到任何 baseline topic，当前退化为 no-op。",
                    field_path=f"actions[{index - 1}].basis_document_ids",
                )
            )

        parameters = _build_action_parameters(
            action=action,
            constraint_parameters=constraint_parameters,
            basis_document_ids=action_basis_document_ids,
            compiled_guardrails=compiled_guardrails,
            resolved_stage=resolved_stage,
        )
        policy_shocks.append(
            PolicyShock(
                shock_id=action.action_id,
                shock_type=action.action_type,
                target_topics=resolved_topic_ids,
                intensity=action.intensity,
                coverage=action.coverage,
                lag=action.lag,
                parameters=parameters,
            )
        )
        compiled_actions.append(
            CompiledPolicyAction(
                action_id=action.action_id,
                action_type=action.action_type,
                stage=resolved_stage,
                support_level=_compiled_action_support_level(
                    action=action,
                    action_basis_document_ids=action_basis_document_ids,
                    resolved_topic_ids=resolved_topic_ids,
                    compiled_guardrails=compiled_guardrails,
                ),
                basis_document_ids=action_basis_document_ids,
                resolved_topic_ids=resolved_topic_ids,
                resolved_topic_labels=[
                    _baseline_topic_label(topic)
                    for topic in baseline.topics
                    if topic.topic_id in resolved_topic_ids
                ],
                rule=action.rule,
                parameters=parameters,
                compiled_guardrails=compiled_guardrails,
                evidence_requirement=list(action.evidence_requirement),
                notes=list(action.notes),
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
        metadata={
            "basis_document_ids": basis_document_ids,
            "policyWindow": {
                "start_year": policy_context.window_start_year,
                "end_year": policy_context.window_end_year,
            },
            "compiledActions": [item.model_dump(mode="json") for item in compiled_actions],
        },
    )

    return CompiledScenario(
        contract=contract,
        scenario_definition=scenario_definition,
        support_level=_support_level(legacy_adapter=legacy_adapter, disclosures=disclosures),
        disclosures=disclosures,
        baseline_topic_ids=baseline_topic_ids,
        action_target_topic_ids=action_target_topic_ids,
        basis_document_ids=basis_document_ids,
        compiled_actions=compiled_actions,
    )


def _load_policy_context(
    *,
    contract: ScenarioContract,
    baseline: BaselineSnapshot,
    disclosures: list[ValidationDisclosure],
) -> _PolicyContext:
    if not _needs_policy_context(contract):
        return _PolicyContext({}, {}, {}, None, None)

    start_year, end_year = _policy_window_from_baseline(baseline)
    try:
        service = SandboxDataService()
        documents = service.load_policy_documents(start_year=start_year, end_year=end_year)
        project_facts = service.load_project_facts(
            start_year=start_year or 2020,
            end_year=end_year or start_year or 2020,
        )
        bindings = service.build_policy_bindings(
            start_year=start_year or 2020,
            end_year=end_year or start_year or 2020,
            document_start_year=start_year,
            document_end_year=end_year,
        )
    except Exception as exc:
        disclosures.append(
            ValidationDisclosure(
                code="policy_context_load_failed",
                severity="warning",
                message=f"正式文本依据层加载失败，当前退回到无依据编译。 error={type(exc).__name__}",
                field_path="basis_documents",
            )
        )
        return _PolicyContext({}, {}, {}, start_year, end_year)

    bindings_by_document_id: dict[str, list[PolicyBinding]] = defaultdict(list)
    for item in bindings:
        bindings_by_document_id[item.document_id].append(item)
    return _PolicyContext(
        documents_by_id={item.document_id: item for item in documents},
        bindings_by_document_id=dict(bindings_by_document_id),
        topic_ids_by_program_id=_build_topic_ids_by_program_id(project_facts),
        window_start_year=start_year,
        window_end_year=end_year,
    )


def _needs_policy_context(contract: ScenarioContract) -> bool:
    if contract.basis_documents:
        return True
    if any(action.basis_document_ids for action in contract.actions):
        return True
    if any(constraint.basis_document_ids for constraint in contract.constraints):
        return True
    return False


def _policy_window_from_baseline(baseline: BaselineSnapshot) -> tuple[int | None, int | None]:
    metadata = baseline.metadata or {}
    start_year = _optional_int(metadata.get("startYear"))
    end_year = _optional_int(metadata.get("endYear"))
    return start_year, end_year


def _resolve_contract_basis_documents(
    *,
    contract: ScenarioContract,
    policy_context: _PolicyContext,
    disclosures: list[ValidationDisclosure],
) -> list[BasisDocumentRef]:
    if not contract.basis_documents:
        return []

    output: list[BasisDocumentRef] = []
    seen: set[str] = set()
    for index, ref in enumerate(contract.basis_documents):
        resolved_id = _resolve_document_id(ref, policy_context)
        if not resolved_id:
            disclosures.append(
                ValidationDisclosure(
                    code="basis_document_not_found",
                    severity="warning",
                    message=f"basis_document[{index}] 未匹配到共享层中的正式文本对象。",
                    field_path=f"basis_documents[{index}]",
                )
            )
            continue
        document = policy_context.documents_by_id.get(resolved_id)
        if document is None or resolved_id in seen:
            continue
        output.append(
            BasisDocumentRef(
                document_id=resolved_id,
                document_type=document.document_type,
                title=document.title,
                publish_date=document.publish_date.isoformat() if document.publish_date else None,
                source_system="sys_article",
                support_scope=list(ref.support_scope),
                link_keys=dict(ref.link_keys),
                notes=list(ref.notes),
            )
        )
        seen.add(resolved_id)
    return output


def _resolve_action_basis_document_ids(
    *,
    action: PolicyAction,
    contract_basis_documents: list[BasisDocumentRef],
    policy_context: _PolicyContext,
    disclosures: list[ValidationDisclosure],
    action_index: int,
) -> list[str]:
    resolved: OrderedDict[str, None] = OrderedDict()
    for raw_id in action.basis_document_ids:
        if raw_id in policy_context.documents_by_id:
            resolved[raw_id] = None
            continue
        disclosures.append(
            ValidationDisclosure(
                code="action_basis_document_not_found",
                severity="warning",
                message=f"action={action.action_id} 引用的 basis_document_id={raw_id} 不存在。",
                field_path=f"actions[{action_index}].basis_document_ids",
            )
        )

    if resolved:
        return list(resolved.keys())

    for ref in contract_basis_documents:
        support_scope = {item.strip() for item in ref.support_scope if item and item.strip()}
        if not support_scope:
            resolved[ref.document_id] = None
            continue
        if "policy_package" in support_scope or "actions" in support_scope or f"action:{action.action_id}" in support_scope:
            resolved[ref.document_id] = None
    return list(resolved.keys())


def _resolve_action_stage(
    *,
    action: PolicyAction,
    action_basis_document_ids: list[str],
    policy_context: _PolicyContext,
    disclosures: list[ValidationDisclosure],
    action_index: int,
) -> str | None:
    document_scope = _collect_document_scope(action_basis_document_ids, policy_context)
    document_stages = list(document_scope["stage_names"])
    if action.stage:
        if document_stages and action.stage not in document_stages:
            disclosures.append(
                ValidationDisclosure(
                    code="action_stage_document_mismatch",
                    severity="warning",
                    message=f"action={action.action_id} 声明的 stage={action.stage} 与文本依据阶段 {document_stages} 不一致。",
                    field_path=f"actions[{action_index}].stage",
                )
            )
        return action.stage
    if len(document_stages) == 1:
        return document_stages[0]
    if len(document_stages) > 1:
        disclosures.append(
            ValidationDisclosure(
                code="action_stage_ambiguous",
                severity="warning",
                message=f"action={action.action_id} 的文本依据命中了多个阶段 {document_stages}，当前未自动选定单一 stage。",
                field_path=f"actions[{action_index}].basis_document_ids",
            )
        )
    return None


def _collect_document_scope(
    document_ids: list[str],
    policy_context: _PolicyContext,
) -> dict[str, object]:
    topic_ids: OrderedDict[str, None] = OrderedDict()
    program_ids: OrderedDict[str, None] = OrderedDict()
    stage_names: OrderedDict[str, None] = OrderedDict()
    constraint_types: OrderedDict[str, None] = OrderedDict()
    budget_caps: list[float] = []
    budget_floors: list[float] = []
    quota_limits: list[int] = []
    quota_limit_scope_types: OrderedDict[str, None] = OrderedDict()
    quota_limit_source_modes: OrderedDict[str, None] = OrderedDict()
    quota_limit_executable = False

    for document_id in document_ids:
        document = policy_context.documents_by_id.get(document_id)
        if document is not None:
            keys = document.extracted_keys
            guide_code_hint = _text_value(keys.get("guide_code_hint"))
            if guide_code_hint:
                topic_ids[guide_code_hint] = None
            for stage_name in _string_list(keys.get("stage_names")):
                stage_names[stage_name] = None
            for constraint_type in _string_list(keys.get("constraint_types")):
                constraint_types[constraint_type] = None
            if _optional_float(keys.get("budget_cap_value")) is not None:
                budget_caps.append(float(keys["budget_cap_value"]))
            if _optional_float(keys.get("budget_floor_value")) is not None:
                budget_floors.append(float(keys["budget_floor_value"]))
            quota_limit_scope_type = _text_value(keys.get("quota_limit_scope_type"))
            if quota_limit_scope_type:
                quota_limit_scope_types[quota_limit_scope_type] = None
            quota_limit_source_mode = _text_value(keys.get("quota_limit_source_mode"))
            if quota_limit_source_mode:
                quota_limit_source_modes[quota_limit_source_mode] = None
            if _bool_value(keys.get("quota_limit_executable")):
                quota_limit_executable = True
            if _bool_value(keys.get("quota_limit_executable")) and _optional_int(keys.get("quota_limit_value")) is not None:
                quota_limits.append(int(keys["quota_limit_value"]))

        for binding in policy_context.bindings_by_document_id.get(document_id, []):
            if binding.binding_type == "topic" and binding.topic_id:
                topic_ids[binding.topic_id] = None
            elif binding.binding_type == "program" and binding.program_id:
                program_ids[binding.program_id] = None
            elif binding.binding_type == "stage" and binding.stage_name:
                stage_names[binding.stage_name] = None
            elif binding.binding_type == "constraint" and binding.constraint_type:
                constraint_types[binding.constraint_type] = None

    for program_id in list(program_ids.keys()):
        for topic_id in policy_context.topic_ids_by_program_id.get(program_id, []):
            topic_ids[topic_id] = None

    return {
        "topic_ids": list(topic_ids.keys()),
        "program_ids": list(program_ids.keys()),
        "stage_names": list(stage_names.keys()),
        "constraint_types": list(constraint_types.keys()),
        "budget_cap": min(budget_caps) if budget_caps else None,
        "budget_floor": max(budget_floors) if budget_floors else None,
        "quota_limit": min(quota_limits) if quota_limits else None,
        "quota_limit_scope_type": _single_or_mixed(list(quota_limit_scope_types.keys())),
        "quota_limit_source_mode": _single_or_mixed(list(quota_limit_source_modes.keys())),
        "quota_limit_executable": quota_limit_executable,
    }


def _resolve_action_topic_ids(
    action: PolicyAction,
    *,
    baseline: BaselineSnapshot,
    baseline_topic_ids: list[str],
    disclosures: list[ValidationDisclosure],
    action_index: int,
    document_scope: dict[str, object] | None = None,
) -> list[str]:
    resolved_topic_ids = _resolve_topics(
        baseline=baseline,
        requested_topic_ids=action.target_scope.topic_ids,
        requested_topic_labels=action.target_scope.topic_labels,
        disclosures=disclosures,
        field_path=f"actions[{action_index}].target_scope",
    )
    scoped_topic_ids = [
        topic_id
        for topic_id in _string_list((document_scope or {}).get("topic_ids"))
        if any(topic.topic_id == topic_id for topic in baseline.topics)
    ]

    if resolved_topic_ids and scoped_topic_ids:
        intersected = [topic_id for topic_id in resolved_topic_ids if topic_id in set(scoped_topic_ids)]
        if not intersected:
            disclosures.append(
                ValidationDisclosure(
                    code="action_document_scope_conflict",
                    severity="warning",
                    message=f"action={action.action_id} 的 target_scope 与正式文本范围没有交集，当前退化为 no-op。",
                    field_path=f"actions[{action_index}].basis_document_ids",
                )
            )
            return []
        return intersected
    if resolved_topic_ids:
        return resolved_topic_ids
    if scoped_topic_ids:
        disclosures.append(
            ValidationDisclosure(
                code="action_scope_from_basis_documents",
                severity="info",
                message=f"action={action.action_id} 未显式给出 target_scope，已按正式文本范围收缩到 {len(scoped_topic_ids)} 个 topic。",
                field_path=f"actions[{action_index}].basis_document_ids",
            )
        )
        return scoped_topic_ids
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
    document_scope_has_basis = any(
        bool((document_scope or {}).get(key))
        for key in (
            "topic_ids",
            "program_ids",
            "stage_names",
            "constraint_types",
            "budget_cap",
            "budget_floor",
            "quota_limit",
            "quota_limit_scope_type",
            "quota_limit_source_mode",
            "quota_limit_executable",
        )
    )
    if document_scope_has_basis:
        disclosures.append(
            ValidationDisclosure(
                code="action_scope_not_inferable_from_basis_documents",
                severity="warning",
                message=(
                    f"action={action.action_id} 仅引用了未映射到 topic/program 的正式文本依据，"
                    "且未显式给出 target_scope；当前不再默认扩展到整个 baseline。"
                ),
                field_path=f"actions[{action_index}].basis_document_ids",
            )
        )
        return []
    return list(baseline_topic_ids)


def _build_topic_ids_by_program_id(project_facts: list[object]) -> dict[str, list[str]]:
    grouped: dict[str, OrderedDict[str, None]] = defaultdict(OrderedDict)
    for fact in project_facts:
        program_id = _text_value(getattr(fact, "program_id", None))
        topic_id = _text_value(getattr(fact, "topic_id", None))
        if program_id and topic_id:
            grouped[program_id][topic_id] = None
    return {program_id: list(topic_ids.keys()) for program_id, topic_ids in grouped.items()}


def _build_action_parameters(
    *,
    action: PolicyAction,
    constraint_parameters: dict[str, float],
    basis_document_ids: list[str],
    compiled_guardrails: dict[str, object],
    resolved_stage: str | None,
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
    if basis_document_ids:
        parameters.setdefault("basis_document_ids", list(basis_document_ids))
    if resolved_stage:
        parameters.setdefault("resolved_stage", resolved_stage)
    if compiled_guardrails:
        parameters.setdefault("compiled_guardrails", dict(compiled_guardrails))
        if compiled_guardrails.get("budget_cap") is not None:
            parameters.setdefault("document_budget_cap", compiled_guardrails["budget_cap"])
        if compiled_guardrails.get("budget_floor") is not None:
            parameters.setdefault("document_budget_floor", compiled_guardrails["budget_floor"])
        if compiled_guardrails.get("quota_limit_executable") is not None:
            parameters.setdefault("document_quota_limit_executable", bool(compiled_guardrails["quota_limit_executable"]))
        if compiled_guardrails.get("quota_limit_scope_type"):
            parameters.setdefault("document_quota_limit_scope_type", compiled_guardrails["quota_limit_scope_type"])
        if compiled_guardrails.get("quota_limit_source_mode"):
            parameters.setdefault("document_quota_limit_source_mode", compiled_guardrails["quota_limit_source_mode"])
        if compiled_guardrails.get("quota_limit_executable") and compiled_guardrails.get("quota_limit") is not None:
            parameters.setdefault("document_quota_limit", compiled_guardrails["quota_limit"])
        if compiled_guardrails.get("constraint_types"):
            parameters.setdefault("document_constraint_types", list(compiled_guardrails["constraint_types"]))
        if compiled_guardrails.get("stage_scope"):
            parameters.setdefault("document_stage_scope", list(compiled_guardrails["stage_scope"]))
    if action.rules:
        parameters.setdefault("contract_rules", [rule.model_dump() for rule in action.rules])
    return parameters


def _compile_action_guardrails(
    *,
    action_basis_document_ids: list[str],
    document_scope: dict[str, object],
) -> dict[str, object]:
    if not action_basis_document_ids:
        return {}
    return {
        "basis_document_ids": list(action_basis_document_ids),
        "constraint_types": list(_string_list(document_scope.get("constraint_types"))),
        "stage_scope": list(_string_list(document_scope.get("stage_names"))),
        "topic_ids": list(_string_list(document_scope.get("topic_ids"))),
        "program_ids": list(_string_list(document_scope.get("program_ids"))),
        "budget_cap": _optional_float(document_scope.get("budget_cap")),
        "budget_floor": _optional_float(document_scope.get("budget_floor")),
        "quota_limit": _optional_int(document_scope.get("quota_limit")),
        "quota_limit_scope_type": _text_value(document_scope.get("quota_limit_scope_type")),
        "quota_limit_source_mode": _text_value(document_scope.get("quota_limit_source_mode")),
        "quota_limit_executable": _bool_value(document_scope.get("quota_limit_executable")),
        "eligibility_gate": "eligibility_gate" in _string_list(document_scope.get("constraint_types")),
    }


def _compile_constraints(
    constraints: list[ScenarioConstraint],
    disclosures: list[ValidationDisclosure],
    *,
    contract_basis_document_ids: list[str],
    policy_context: _PolicyContext,
) -> ScenarioConstraints | None:
    if not constraints:
        if contract_basis_document_ids:
            document_scope = _collect_document_scope(contract_basis_document_ids, policy_context)
            unsupported = [
                item
                for item in _string_list(document_scope.get("constraint_types"))
                if item in _DOCUMENT_CONSTRAINT_TYPES
            ]
            if unsupported:
                disclosures.append(
                    ValidationDisclosure(
                        code="document_constraints_compiled_to_action_guardrails_only",
                        severity="info",
                        message=f"正式文本中识别到 {unsupported}，当前先编译到 action guardrails，尚未进入 scenario-level legacy constraints。",
                        field_path="basis_documents",
                    )
                )
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
        if constraint.basis_document_ids:
            missing_ids = [item for item in constraint.basis_document_ids if item not in policy_context.documents_by_id]
            if missing_ids:
                disclosures.append(
                    ValidationDisclosure(
                        code="constraint_basis_document_not_found",
                        severity="warning",
                        message=f"constraint={constraint.constraint_type} 引用的 basis_document_ids={missing_ids} 不存在。",
                        field_path=f"constraints[{index}].basis_document_ids",
                    )
                )
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


def _resolve_document_id(ref: BasisDocumentRef, policy_context: _PolicyContext) -> str | None:
    if ref.document_id and ref.document_id in policy_context.documents_by_id:
        return ref.document_id
    title = str(ref.title or "").strip()
    if not title:
        return None
    normalized_title = _normalize_text_key(title)
    for document_id, document in policy_context.documents_by_id.items():
        if _normalize_text_key(document.title) == normalized_title:
            return document_id
    return None


def _baseline_topic_label(topic: BaselineTopicState) -> str:
    label = str(topic.topic_label or "").strip()
    if label:
        if "-" in label:
            prefix, remainder = label.split("-", 1)
            if prefix and remainder and len(prefix.replace("_", "")) >= 6 and prefix.isascii() and prefix.replace("_", "").isalnum():
                return remainder.strip()
        return label
    topic_id = str(topic.topic_id or "").strip()
    if "-" not in topic_id:
        return topic_id
    prefix, remainder = topic_id.split("-", 1)
    if prefix and remainder and len(prefix.replace("_", "")) >= 6 and prefix.isascii() and prefix.replace("_", "").isalnum():
        return remainder.strip()
    return topic_id


def _compiled_action_support_level(
    *,
    action: PolicyAction,
    action_basis_document_ids: list[str],
    resolved_topic_ids: list[str],
    compiled_guardrails: dict[str, object],
) -> str:
    if action.action_type not in DEFAULT_RULES:
        return "unsupported"
    if action_basis_document_ids and not resolved_topic_ids:
        return "partial"
    if action_basis_document_ids and compiled_guardrails:
        return "supported"
    if action_basis_document_ids:
        return "partial"
    return action.support_level


def _support_level(*, legacy_adapter: bool, disclosures: list[ValidationDisclosure]) -> str:
    if any(item.severity == "error" for item in disclosures):
        return "unsupported"
    if any(item.severity == "warning" for item in disclosures):
        return "partial"
    if legacy_adapter:
        return "legacy_compatible"
    return "supported"


def _normalize_text_key(value: object) -> str:
    return "".join(str(value or "").strip().lower().split())


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        output: list[str] = []
        for item in value:
            text = _text_value(item)
            if text:
                output.append(text)
        return output
    text = _text_value(value)
    return [text] if text else []


def _text_value(value: object) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _single_or_mixed(values: list[str]) -> str | None:
    cleaned = [item for item in values if item]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return "mixed"
