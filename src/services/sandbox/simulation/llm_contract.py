"""LLM-assisted contract drafting for sandbox simulation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field

from src.common.models.simulation import ScenarioConstraints

try:
    from src.common.llm.config import llm_config
    from src.common.llm.factory import get_llm_client
except ModuleNotFoundError:
    llm_config = None  # type: ignore[assignment]
    get_llm_client = None  # type: ignore[assignment]


_POLICY_SPLIT_PATTERN = re.compile(r"[\n\r]+|[;；]+")
_OBJECT_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_ARRAY_JSON_PATTERN = re.compile(r"\[.*\]", re.DOTALL)
_YEAR_WINDOW_PATTERN = re.compile(r"\b(20\d{2}(?:\s*[-~至到]\s*20\d{2})?)\b")
_RATIO_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%?)")

_SHOCK_KEYWORDS = {
    "funding": ("经费", "预算", "资助", "拨款", "投入", "配套", "funding", "budget"),
    "talent": ("人才", "团队", "专家", "青年", "talent", "team"),
    "collaboration": ("协作", "协同", "联合", "联盟", "合作", "spillover", "collaboration"),
    "infrastructure": ("平台", "设施", "试验线", "中试", "基础设施", "platform", "facility"),
    "risk_control": ("风险", "风控", "监管", "约束", "止损", "risk", "control"),
    "demand": ("场景", "应用", "示范", "采购", "需求", "market", "application"),
}

_TOPIC_FIELD_NAMES = ("target_topics", "topics", "targetTopics", "topic_ids", "topicIds")
_TEXT_FIELD_NAMES = ("title", "name", "description", "summary", "policy", "text", "source_text")
_KNOWN_POLICY_FIELDS = {
    "shock_id",
    "shock_type",
    "title",
    "name",
    "description",
    "summary",
    "policy",
    "text",
    "source_text",
    "target_topics",
    "topics",
    "targetTopics",
    "topic_ids",
    "topicIds",
    "intensity",
    "coverage",
    "lag",
    "parameters",
    "rationale",
}


class ScenarioContractPolicyItem(BaseModel):
    shock_id: str
    shock_type: str = "generic"
    title: str = ""
    target_topics: list[str] = Field(default_factory=list)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    lag: int = Field(default=0, ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    source_text: str = ""


class PolicyPackageNormalization(BaseModel):
    policy_package: list[ScenarioContractPolicyItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioContract(BaseModel):
    scenario_id: str
    baseline_id: str
    forecast_window: str
    prompt: str
    objective: str = ""
    summary: str = ""
    target_topics: list[str] = Field(default_factory=list)
    policy_package: list[ScenarioContractPolicyItem] = Field(default_factory=list)
    constraints: ScenarioConstraints = Field(default_factory=ScenarioConstraints)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractConsistencyReview(BaseModel):
    scenario_id: str
    ok: bool = True
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def draft_scenario_contract_from_prompt(
    prompt: str,
    *,
    baseline_id: str | None = None,
    forecast_window: str | None = None,
    scenario_id: str | None = None,
    policy_package: Any = None,
    constraints: Mapping[str, Any] | ScenarioConstraints | None = None,
    llm: Any | None = None,
) -> ScenarioContract:
    fallback_contract = _draft_contract_fallback(
        prompt=prompt,
        baseline_id=baseline_id,
        forecast_window=forecast_window,
        scenario_id=scenario_id,
        policy_package=policy_package,
        constraints=constraints,
    )
    client = _build_llm(llm=llm)
    if client is None:
        return fallback_contract

    prompt_text = (
        "你是政策沙盘 simulation 的 contract 起草助手。"
        "请把领导自然语言或半结构输入整理成 JSON 草案。"
        "不要编造不存在的事实；字段缺失时优先保留 fallback。"
        "输出 JSON 对象，字段包括: scenario_id, baseline_id, forecast_window, objective, summary, "
        "target_topics, policy_package, constraints, assumptions, warnings。\n\n"
        f"原始输入:\n{prompt.strip()}\n\n"
        f"fallback 草案:\n{json.dumps(fallback_contract.model_dump(mode='json'), ensure_ascii=False, indent=2)}"
    )
    payload = _invoke_json(client, prompt_text)
    if not isinstance(payload, Mapping):
        return _append_contract_warning(
            fallback_contract,
            "LLM 未返回可解析的 contract JSON，已使用规则草案。",
            mode="rule_fallback_due_to_parse_error",
        )

    merged_constraints = _merge_constraints(
        fallback_contract.constraints,
        payload.get("constraints"),
        constraints,
    )
    llm_policy_items = _normalize_policy_items(payload.get("policy_package"))
    contract = ScenarioContract(
        scenario_id=_clean_text(payload.get("scenario_id")) or fallback_contract.scenario_id,
        baseline_id=_clean_text(payload.get("baseline_id")) or fallback_contract.baseline_id,
        forecast_window=_clean_text(payload.get("forecast_window")) or fallback_contract.forecast_window,
        prompt=prompt.strip(),
        objective=_clean_text(payload.get("objective")) or fallback_contract.objective,
        summary=_clean_text(payload.get("summary")) or fallback_contract.summary,
        target_topics=_dedupe_strings(payload.get("target_topics") or fallback_contract.target_topics),
        policy_package=llm_policy_items or fallback_contract.policy_package,
        constraints=merged_constraints,
        assumptions=_dedupe_strings(payload.get("assumptions") or fallback_contract.assumptions),
        warnings=_dedupe_strings(list(fallback_contract.warnings) + _to_string_list(payload.get("warnings"))),
        metadata={
            **fallback_contract.metadata,
            "generationMode": "llm_enhanced",
            "llm": _active_llm_meta(),
        },
    )
    if not contract.target_topics:
        contract.target_topics = _dedupe_strings(_topics_from_policy_items(contract.policy_package))
    return contract


def normalize_policy_package_with_llm(
    policy_package: Any,
    *,
    llm: Any | None = None,
) -> PolicyPackageNormalization:
    fallback = _normalize_policy_package_fallback(policy_package)
    client = _build_llm(llm=llm)
    if client is None:
        return fallback

    prompt_text = (
        "你是政策沙盘 simulation 的 policy package 归一化助手。"
        "请把输入整理成 JSON，字段包括 policy_package 和 warnings。"
        "policy_package 的每个元素必须包含 shock_id, shock_type, title, target_topics, intensity, coverage, lag, parameters, rationale, source_text。\n\n"
        f"原始输入:\n{json.dumps(_json_safe_value(policy_package), ensure_ascii=False, indent=2)}\n\n"
        f"fallback 结果:\n{json.dumps(fallback.model_dump(mode='json'), ensure_ascii=False, indent=2)}"
    )
    payload = _invoke_json(client, prompt_text)
    if not isinstance(payload, Mapping):
        return PolicyPackageNormalization(
            policy_package=fallback.policy_package,
            warnings=_dedupe_strings(list(fallback.warnings) + ["LLM 未返回可解析 JSON，已使用规则归一化结果。"]),
            metadata={
                **fallback.metadata,
                "normalizationMode": "rule_fallback_due_to_parse_error",
                "llm": _active_llm_meta(),
            },
        )

    normalized_items = _normalize_policy_items(payload.get("policy_package"))
    return PolicyPackageNormalization(
        policy_package=normalized_items or fallback.policy_package,
        warnings=_dedupe_strings(list(fallback.warnings) + _to_string_list(payload.get("warnings"))),
        metadata={
            **fallback.metadata,
            "normalizationMode": "llm_enhanced",
            "llm": _active_llm_meta(),
        },
    )


def review_contract_consistency_with_llm(
    contract: ScenarioContract | Mapping[str, Any],
    *,
    llm: Any | None = None,
) -> ContractConsistencyReview:
    normalized_contract = _coerce_contract(contract)
    rule_review = _review_contract_rules(normalized_contract)
    client = _build_llm(llm=llm)
    if client is None:
        return rule_review

    prompt_text = (
        "你是政策沙盘 simulation 的 contract 审稿助手。"
        "请基于给定 contract 和规则审查结果输出 JSON。"
        "字段包括: issues, warnings, suggestions。"
        "不要重复输入中已经明确无问题的内容。\n\n"
        f"contract:\n{json.dumps(normalized_contract.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
        f"规则审查:\n{json.dumps(rule_review.model_dump(mode='json'), ensure_ascii=False, indent=2)}"
    )
    payload = _invoke_json(client, prompt_text)
    if not isinstance(payload, Mapping):
        return ContractConsistencyReview(
            scenario_id=rule_review.scenario_id,
            ok=rule_review.ok,
            issues=rule_review.issues,
            warnings=_dedupe_strings(list(rule_review.warnings) + ["LLM 审查输出不可解析，已返回规则审查结果。"]),
            suggestions=rule_review.suggestions,
            metadata={
                **rule_review.metadata,
                "reviewMode": "rule_fallback_due_to_parse_error",
                "llm": _active_llm_meta(),
            },
        )

    issues = _dedupe_strings(rule_review.issues + _to_string_list(payload.get("issues")))
    warnings = _dedupe_strings(rule_review.warnings + _to_string_list(payload.get("warnings")))
    suggestions = _dedupe_strings(rule_review.suggestions + _to_string_list(payload.get("suggestions")))
    return ContractConsistencyReview(
        scenario_id=normalized_contract.scenario_id,
        ok=not issues,
        issues=issues,
        warnings=warnings,
        suggestions=suggestions,
        metadata={
            **rule_review.metadata,
            "reviewMode": "llm_enhanced",
            "llm": _active_llm_meta(),
        },
    )


def _draft_contract_fallback(
    *,
    prompt: str,
    baseline_id: str | None,
    forecast_window: str | None,
    scenario_id: str | None,
    policy_package: Any,
    constraints: Mapping[str, Any] | ScenarioConstraints | None,
) -> ScenarioContract:
    normalized_policy = _normalize_policy_package_fallback(policy_package if policy_package is not None else prompt)
    resolved_window = _clean_text(forecast_window) or _extract_forecast_window(prompt) or "next_window"
    resolved_baseline = _clean_text(baseline_id) or "baseline-unspecified"
    resolved_scenario = _clean_text(scenario_id) or _stable_scenario_id(prompt)
    target_topics = _dedupe_strings(
        _extract_topics_from_text(prompt) + _topics_from_policy_items(normalized_policy.policy_package)
    )
    resolved_constraints = _merge_constraints(
        ScenarioConstraints(),
        _extract_constraints_from_text(prompt),
        constraints,
    )
    summary = _summarize_prompt(prompt)
    assumptions = _build_contract_assumptions(
        baseline_id=resolved_baseline,
        forecast_window=resolved_window,
        target_topics=target_topics,
        policy_count=len(normalized_policy.policy_package),
    )
    warnings = list(normalized_policy.warnings)
    if resolved_baseline == "baseline-unspecified":
        warnings.append("baseline_id 未显式提供，当前为稳定占位值，需要在真正运行前替换。")
    if resolved_window == "next_window":
        warnings.append("forecast_window 未显式给出，当前使用 next_window 占位。")

    return ScenarioContract(
        scenario_id=resolved_scenario,
        baseline_id=resolved_baseline,
        forecast_window=resolved_window,
        prompt=prompt.strip(),
        objective=_objective_from_prompt(prompt),
        summary=summary,
        target_topics=target_topics,
        policy_package=normalized_policy.policy_package,
        constraints=resolved_constraints,
        assumptions=assumptions,
        warnings=_dedupe_strings(warnings),
        metadata={
            "generationMode": "rule_fallback",
            "llm": _active_llm_meta(),
            "policyNormalizationMode": normalized_policy.metadata.get("normalizationMode", "rule_fallback"),
        },
    )


def _normalize_policy_package_fallback(policy_package: Any) -> PolicyPackageNormalization:
    entries = _policy_entries_from_source(policy_package)
    items = [_policy_item_from_entry(entry, index=index) for index, entry in enumerate(entries, start=1)]
    warnings: list[str] = []
    if policy_package in (None, "", [], {}):
        warnings.append("policy_package 为空，当前未生成具体 policy_shocks。")
    if not items and _clean_text(str(policy_package or "")):
        warnings.append("未从输入中稳定提取出可执行的 policy package 条目。")
    return PolicyPackageNormalization(
        policy_package=items,
        warnings=_dedupe_strings(warnings),
        metadata={
            "normalizationMode": "rule_fallback",
            "policyCount": len(items),
            "llm": _active_llm_meta(),
        },
    )


def _policy_entries_from_source(policy_package: Any) -> list[dict[str, Any]]:
    if policy_package is None:
        return []
    if isinstance(policy_package, Mapping):
        if isinstance(policy_package.get("policy_package"), Sequence) and not isinstance(policy_package.get("policy_package"), (str, bytes)):
            return [_entry_mapping(item) for item in policy_package.get("policy_package", [])]
        if isinstance(policy_package.get("items"), Sequence) and not isinstance(policy_package.get("items"), (str, bytes)):
            return [_entry_mapping(item) for item in policy_package.get("items", [])]
        return [_entry_mapping(policy_package)]
    if isinstance(policy_package, Sequence) and not isinstance(policy_package, (str, bytes)):
        return [_entry_mapping(item) for item in policy_package]

    text = _clean_text(str(policy_package))
    if not text:
        return []
    lines = [_clean_text(part) for part in _POLICY_SPLIT_PATTERN.split(text)]
    lines = [line for line in lines if line]
    if not lines:
        lines = [text]
    return [{"source_text": _strip_bullet_prefix(line), "title": _strip_bullet_prefix(line)} for line in lines]


def _entry_mapping(value: Any) -> dict[str, Any]:
    mapped = _mapping_from_value(value)
    if mapped:
        return mapped
    text = _clean_text(str(value))
    return {"source_text": text, "title": text}


def _policy_item_from_entry(entry: Mapping[str, Any], *, index: int) -> ScenarioContractPolicyItem:
    source_text = _clean_text(
        next((entry.get(name) for name in _TEXT_FIELD_NAMES if entry.get(name)), "")
    )
    title = _clean_text(entry.get("title") or entry.get("name")) or source_text[:48]
    target_topics = _dedupe_strings(_extract_topics_from_mapping(entry) or _extract_topics_from_text(source_text))
    intensity = _bounded_ratio(entry.get("intensity"), fallback=_extract_named_ratio(source_text, ("强度", "力度", "intensity")))
    coverage = _bounded_ratio(entry.get("coverage"), fallback=_extract_named_ratio(source_text, ("覆盖", "coverage")))
    lag = _coerce_int(entry.get("lag"), fallback=_extract_named_int(source_text, ("滞后", "lag")))
    shock_type = _clean_text(entry.get("shock_type")) or _infer_shock_type(title or source_text)
    rationale = _clean_text(entry.get("rationale")) or _build_policy_rationale(shock_type, target_topics, source_text)
    parameters = _policy_parameters(entry)
    return ScenarioContractPolicyItem(
        shock_id=_clean_text(entry.get("shock_id")) or f"shock-{index:02d}",
        shock_type=shock_type,
        title=title or f"policy-{index:02d}",
        target_topics=target_topics,
        intensity=intensity,
        coverage=coverage,
        lag=lag,
        parameters=parameters,
        rationale=rationale,
        source_text=source_text or title,
    )


def _normalize_policy_items(payload: Any) -> list[ScenarioContractPolicyItem]:
    entries = _policy_entries_from_source(payload)
    return [_policy_item_from_entry(entry, index=index) for index, entry in enumerate(entries, start=1)]


def _policy_parameters(entry: Mapping[str, Any]) -> dict[str, Any]:
    explicit = entry.get("parameters")
    if isinstance(explicit, Mapping):
        merged = {str(key): value for key, value in explicit.items()}
    else:
        merged = {}
    for key, value in entry.items():
        if key in _KNOWN_POLICY_FIELDS or value in (None, ""):
            continue
        merged[str(key)] = value
    return merged


def _coerce_contract(contract: ScenarioContract | Mapping[str, Any]) -> ScenarioContract:
    if isinstance(contract, ScenarioContract):
        return contract
    payload = _mapping_from_value(contract)
    baseline = _mapping_from_value(payload.get("baseline") or payload.get("baseline_scope"))
    intent = _mapping_from_value(payload.get("intent"))
    policy_source = payload.get("policy_package")
    if policy_source in (None, "", [], {}):
        policy_source = _policy_entries_from_actions(payload.get("actions"))
    normalized_policy = _normalize_policy_items(policy_source)
    prompt = (
        _clean_text(payload.get("prompt"))
        or _clean_text(intent.get("question"))
        or _clean_text(intent.get("narrative"))
        or _clean_text(payload.get("scenario_name"))
        or _clean_text(payload.get("summary"))
    )
    payload["policy_package"] = normalized_policy
    payload["constraints"] = _merge_constraints(ScenarioConstraints(), _constraint_mapping_from_source(payload.get("constraints")))
    payload["target_topics"] = _dedupe_strings(
        payload.get("target_topics") or payload.get("topics") or _topics_from_policy_items(normalized_policy)
    )
    payload["assumptions"] = _dedupe_strings(_to_string_list(payload.get("assumptions")))
    payload["warnings"] = _dedupe_strings(_to_string_list(payload.get("warnings")))
    payload["scenario_id"] = _clean_text(payload.get("scenario_id")) or _stable_scenario_id(prompt)
    payload["baseline_id"] = _clean_text(payload.get("baseline_id")) or _clean_text(baseline.get("baseline_id")) or "baseline-unspecified"
    payload["forecast_window"] = _clean_text(payload.get("forecast_window")) or "next_window"
    payload["prompt"] = prompt
    payload["objective"] = (
        _clean_text(payload.get("objective"))
        or _clean_text(intent.get("desired_outcome"))
        or _clean_text(intent.get("policy_problem"))
        or _clean_text(intent.get("question"))
    )
    payload["summary"] = _clean_text(payload.get("summary")) or _clean_text(payload.get("scenario_name"))
    payload["metadata"] = _mapping_from_value(payload.get("metadata"))
    return ScenarioContract.model_validate(payload)


def _review_contract_rules(contract: ScenarioContract) -> ContractConsistencyReview:
    issues: list[str] = []
    warnings = list(contract.warnings)
    suggestions: list[str] = []

    if not contract.policy_package:
        issues.append("policy_package 为空，当前 contract 无法映射为 ScenarioDefinition.policy_shocks。")
        suggestions.append("至少补充一个 policy shock，并明确 shock_type、target_topics、intensity。")
    if contract.baseline_id == "baseline-unspecified":
        issues.append("baseline_id 仍为占位值，需要在执行 simulation 前替换为真实 baseline。")
    if contract.forecast_window == "next_window":
        warnings.append("forecast_window 仍为占位值，建议补充明确年份或时间窗。")
        suggestions.append("补充 forecast_window，例如 2027 或 2027-2028。")
    if not contract.target_topics:
        warnings.append("未识别 target_topics，后续可能只能依赖 policy_package 内的 target_topics。")
        suggestions.append("补充总体 target_topics，方便领导视角检查覆盖范围。")

    shock_ids = [item.shock_id for item in contract.policy_package]
    duplicate_ids = sorted({item for item in shock_ids if shock_ids.count(item) > 1})
    if duplicate_ids:
        issues.append(f"shock_id 存在重复: {', '.join(duplicate_ids)}。")
        suggestions.append("为每个 policy shock 指定唯一 shock_id。")

    if contract.constraints.spillover_budget_share is not None:
        has_spillover = any(item.shock_type == "collaboration" for item in contract.policy_package)
        if not has_spillover:
            warnings.append("设置了 spillover_budget_share，但 policy_package 中未识别出明显的协同/外溢类 shock。")

    if contract.constraints.budget_limit is None:
        suggestions.append("如需预算约束，请补充 constraints.budget_limit。")
    if contract.constraints.risk_threshold is None and contract.constraints.max_risk_increase is None:
        suggestions.append("如需稳健性约束，请补充 risk_threshold 或 max_risk_increase。")

    return ContractConsistencyReview(
        scenario_id=contract.scenario_id,
        ok=not issues,
        issues=_dedupe_strings(issues),
        warnings=_dedupe_strings(warnings),
        suggestions=_dedupe_strings(suggestions),
        metadata={
            "reviewMode": "rule_fallback",
            "llm": _active_llm_meta(),
        },
    )


def _merge_constraints(*sources: Any) -> ScenarioConstraints:
    payload: dict[str, Any] = {}
    for source in sources:
        if source is None:
            continue
        if isinstance(source, ScenarioConstraints):
            data = source.model_dump(mode="json", exclude_none=True)
        elif isinstance(source, Mapping):
            data = {str(key): value for key, value in source.items() if value is not None}
        else:
            continue
        payload.update(data)
    return ScenarioConstraints.model_validate(payload)


def _constraint_mapping_from_source(source: Any) -> Any:
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
        return source
    payload: dict[str, Any] = {}
    for item in source:
        entry = _mapping_from_value(item)
        if not entry:
            continue
        key = _clean_text(entry.get("constraint_type") or entry.get("type")).lower()
        if key not in {"budget_limit", "spillover_budget_share", "risk_threshold", "max_risk_increase"}:
            continue
        value = entry.get("value")
        if value is None:
            continue
        payload[key] = value
    return payload


def _extract_constraints_from_text(prompt: str) -> dict[str, Any]:
    text = _clean_text(prompt)
    if not text:
        return {}
    constraints: dict[str, Any] = {}
    budget_value = _extract_named_number(text, ("预算上限", "预算不超过", "总预算", "budget_limit", "budget"))
    if budget_value is not None:
        constraints["budget_limit"] = budget_value
    spillover_share = _extract_named_ratio(text, ("外溢预算占比", "spillover_budget_share", "外溢占比"))
    if spillover_share is not None:
        constraints["spillover_budget_share"] = spillover_share
    risk_threshold = _extract_named_ratio(text, ("风险阈值", "risk_threshold"))
    if risk_threshold is not None:
        constraints["risk_threshold"] = risk_threshold
    max_risk_increase = _extract_named_ratio(text, ("风险增幅", "max_risk_increase", "风险上升"))
    if max_risk_increase is not None:
        constraints["max_risk_increase"] = max_risk_increase
    return constraints


def _extract_forecast_window(prompt: str) -> str | None:
    match = _YEAR_WINDOW_PATTERN.search(prompt)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1))


def _summarize_prompt(prompt: str) -> str:
    text = _clean_text(prompt)
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text[:120]


def _objective_from_prompt(prompt: str) -> str:
    text = _clean_text(prompt)
    if not text:
        return ""
    for marker in ("目标", "目的", "希望", "想看", "请评估"):
        index = text.find(marker)
        if index >= 0:
            return text[index : index + 80].strip("：: ")
    return text[:80]


def _build_contract_assumptions(
    *,
    baseline_id: str,
    forecast_window: str,
    target_topics: Sequence[str],
    policy_count: int,
) -> list[str]:
    assumptions = [
        "当前 contract 仅用于草案和人工校对，不替代引擎计算。",
        f"baseline_id={baseline_id}，forecast_window={forecast_window} 需要与真实 simulation 输入对齐。",
    ]
    if not target_topics:
        assumptions.append("target_topics 暂未稳定识别，需在提交前人工补充。")
    if policy_count == 0:
        assumptions.append("尚未形成 policy_package，当前仅保留输入意图。")
    return assumptions


def _append_contract_warning(contract: ScenarioContract, warning: str, *, mode: str) -> ScenarioContract:
    return contract.model_copy(
        update={
            "warnings": _dedupe_strings(list(contract.warnings) + [warning]),
            "metadata": {
                **contract.metadata,
                "generationMode": mode,
                "llm": _active_llm_meta(),
            },
        }
    )


def _topics_from_policy_items(items: Sequence[ScenarioContractPolicyItem]) -> list[str]:
    topics: list[str] = []
    for item in items:
        topics.extend(item.target_topics)
    return _dedupe_strings(topics)


def _extract_topics_from_mapping(entry: Mapping[str, Any]) -> list[str]:
    topics: list[str] = []
    for name in _TOPIC_FIELD_NAMES:
        value = entry.get(name)
        topics.extend(_to_string_list(value))
    return _dedupe_strings(topics)


def _extract_topics_from_text(text: str) -> list[str]:
    normalized = _clean_text(text)
    if not normalized:
        return []
    matches: list[str] = []
    patterns = [
        r"(?:主题|方向|topic|topics|target_topics?)\s*[:：=]\s*([^\n。；;]+)",
        r"(?:面向|聚焦|支持|加码|布局)\s*([^\n。；;]{2,60})",
        r"[\[【](.+?)[\]】]",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            matches.extend(_split_topic_candidates(match.group(1)))
    return _dedupe_strings(matches)


def _split_topic_candidates(text: str) -> list[str]:
    raw_parts = re.split(r"[、,，/]\s*", text)
    result: list[str] = []
    for part in raw_parts:
        candidate = _clean_text(part).strip("。.;；")
        if not candidate:
            continue
        if len(candidate) > 32:
            continue
        result.append(candidate)
    return result


def _infer_shock_type(text: str) -> str:
    normalized = _clean_text(text).lower()
    if not normalized:
        return "generic"
    for shock_type, keywords in _SHOCK_KEYWORDS.items():
        if any(keyword.lower() in normalized for keyword in keywords):
            return shock_type
    return "generic"


def _build_policy_rationale(shock_type: str, target_topics: Sequence[str], source_text: str) -> str:
    topic_text = "、".join(target_topics) if target_topics else "相关主题"
    if shock_type == "funding":
        return f"通过经费配置变化影响 {topic_text} 的申报与立项表现。"
    if shock_type == "collaboration":
        return f"通过协同或外溢链路影响 {topic_text} 的扩散与承接。"
    if shock_type == "risk_control":
        return f"通过风险约束调节 {topic_text} 的扩张节奏。"
    if source_text:
        return f"根据输入文本整理出的 {shock_type} 类政策动作。"
    return f"根据输入整理出的 {shock_type} 类政策动作。"


def _extract_named_ratio(text: str, labels: Sequence[str]) -> float | None:
    value = _extract_named_number(text, labels)
    if value is None:
        return None
    return value if value <= 1.0 else round(value / 100.0, 6)


def _extract_named_number(text: str, labels: Sequence[str]) -> float | None:
    for label in labels:
        pattern = re.compile(re.escape(label) + r"\s*[:：=]?\s*(\d+(?:\.\d+)?%?)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            return _parse_ratio_or_number(match.group(1))
    return None


def _extract_named_int(text: str, labels: Sequence[str]) -> int | None:
    value = _extract_named_number(text, labels)
    if value is None:
        return None
    return max(int(round(value)), 0)


def _bounded_ratio(value: Any, *, fallback: float | None) -> float:
    parsed = _parse_ratio_or_number(value)
    if parsed is None:
        parsed = fallback if fallback is not None else 0.5
    parsed = max(0.0, min(parsed, 1.0))
    return round(parsed, 6)


def _coerce_int(value: Any, *, fallback: int | None) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(int(round(value)), 0)
    text = _clean_text(str(value or ""))
    if text.isdigit():
        return int(text)
    if fallback is not None:
        return fallback
    return 0


def _parse_ratio_or_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(str(value))
    if not text:
        return None
    match = _RATIO_PATTERN.fullmatch(text)
    if not match:
        return None
    number = float(match.group("value"))
    if match.group("unit") == "%":
        return round(number / 100.0, 6)
    return number


def _stable_scenario_id(prompt: str) -> str:
    digest = hashlib.sha1(prompt.strip().encode("utf-8")).hexdigest()[:10]
    return f"scenario-contract-{digest}"


def _mapping_from_value(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return {str(key): item for key, item in value.model_dump(mode="json", exclude_none=True).items()}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _policy_entries_from_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray)):
        return []
    entries: list[dict[str, Any]] = []
    for action in actions:
        entry = _mapping_from_value(action)
        if not entry:
            continue
        target_scope = _mapping_from_value(entry.get("target_scope") or entry.get("targetScope"))
        notes = _to_string_list(entry.get("notes"))
        source_text = (
            _clean_text(entry.get("description"))
            or _clean_text(entry.get("summary"))
            or _clean_text(" ".join(notes))
            or _clean_text(entry.get("stage"))
        )
        entries.append(
            {
                "shock_id": entry.get("action_id") or entry.get("actionId"),
                "shock_type": entry.get("action_type") or entry.get("actionType"),
                "title": entry.get("title") or entry.get("name") or entry.get("action_id") or entry.get("action_type"),
                "target_topics": (
                    target_scope.get("topic_ids")
                    or target_scope.get("topicIds")
                    or target_scope.get("topic_labels")
                    or target_scope.get("topicLabels")
                    or entry.get("target_topics")
                    or entry.get("targetTopics")
                ),
                "intensity": entry.get("intensity"),
                "coverage": entry.get("coverage"),
                "lag": entry.get("lag"),
                "parameters": entry.get("parameters"),
                "rationale": entry.get("rationale") or source_text,
                "source_text": entry.get("source_text") or source_text,
            }
        )
    return entries


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _strip_bullet_prefix(text: str) -> str:
    return re.sub(r"^(?:[-*•]|[0-9]+[.)、])\s*", "", text).strip()


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _clean_text(value)
        if not text:
            return []
        if any(separator in text for separator in ("、", "，", ",", ";", "；", "/")):
            return _dedupe_strings(re.split(r"[、,，;；/]\s*", text))
        return [text]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return _dedupe_strings(_clean_text(item) for item in value)
    return [_clean_text(value)]


def _dedupe_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _build_llm(*, llm: Any | None) -> Any | None:
    if llm is not None:
        return llm
    if llm_config is None or get_llm_client is None:
        return None
    provider = _clean_text(getattr(llm_config, "provider", ""))
    api_key = _clean_text(getattr(llm_config, "api_key", ""))
    if not provider or not api_key:
        return None
    try:
        return get_llm_client(
            provider=provider,
            model=_clean_text(getattr(llm_config, "model", "")) or None,
            api_key=api_key,
            base_url=_clean_text(getattr(llm_config, "base_url", "")) or None,
            temperature=float(getattr(llm_config, "temperature", 0.2) or 0.2),
            max_tokens=int(getattr(llm_config, "max_tokens", 1200) or 1200),
            timeout=float(getattr(llm_config, "timeout", 30.0) or 30.0),
            max_retries=int(getattr(llm_config, "max_retries", 2) or 2),
        )
    except Exception:
        return None


def _active_llm_meta() -> dict[str, str]:
    if llm_config is None:
        return {"provider": "unknown", "model": "unknown"}
    return {
        "provider": _clean_text(getattr(llm_config, "provider", "")) or "unknown",
        "model": _clean_text(getattr(llm_config, "model", "")) or "unknown",
    }


def _invoke_json(llm: Any, prompt: str) -> Any | None:
    try:
        response = llm.invoke(prompt) if hasattr(llm, "invoke") else llm(prompt)
    except Exception:
        return None
    return _parse_json_payload(response)


def _parse_json_payload(response: Any) -> Any | None:
    if isinstance(response, (dict, list)):
        return response
    text = _response_text(response)
    if not text:
        return None
    for candidate in (text, _match_json_block(text, _OBJECT_JSON_PATTERN), _match_json_block(text, _ARRAY_JSON_PATTERN)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        parts = []
        for item in content:
            if isinstance(item, Mapping):
                parts.append(_clean_text(item.get("text") or item.get("content") or item))
            else:
                parts.append(_clean_text(item))
        return "\n".join(part for part in parts if part).strip()
    return _clean_text(response)


def _match_json_block(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(0)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe_value(item) for item in value]
    return value
