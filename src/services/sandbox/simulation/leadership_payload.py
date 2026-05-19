"""Leadership-oriented payload builders for sandbox simulation reports."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src.common.database.connection import project_execute
from src.common.models.simulation import (
    BaselineSnapshot,
    CompiledScenario,
    EvaluationGoal,
    PolicyAction,
    ScenarioConstraint,
    ScenarioContract,
    ScenarioDefinition,
    SimulationComparison,
    SimulationExplanation,
    SimulationResult,
    SimulationTopicImpact,
    ValidationDisclosure,
)
from src.services.sandbox.data import load_project_facts
_SUPPORT_LABELS = {
    "supported": "正式支持",
    "legacy_compatible": "结果预演",
    "partial": "部分支持",
    "unsupported": "当前不支持",
    "observed-grounded": "事实锚定",
    "proxy-grounded": "代理推演",
    "assumption-heavy": "假设驱动",
    "unknown": "待确认",
}

_DISCLOSURE_SEVERITY_LABELS = {
    "info": "说明",
    "warning": "提醒",
    "error": "限制",
}

_TOPIC_METRIC_LABELS = {
    "delta_application_count": "申报项目数变化",
    "delta_funded_count": "立项数变化",
    "delta_funding_amount": "合同专项经费变化",
    "delta_score_proxy": "评审强度代理变化",
    "delta_collaboration_density": "协作密度变化",
    "delta_topic_centrality": "主题中心性变化",
    "delta_migration_strength": "迁移强度变化",
    "delta_proxy_risk": "风险代理变化",
}

_BACKTEST_TRAINING_START_YEAR = 2015
_BACKTEST_EARLIEST_VALIDATION_YEAR = 2020

_GOVERNANCE_STAGE_SPECS = (
    {
        "stage_id": "application_response",
        "stage_label": "申报响应",
        "narrative": "先判断政策包会改变谁来报、报多少、报多大，先看申报端的进入与退出。",
        "support_level": "proxy-grounded",
    },
    {
        "stage_id": "review_selection",
        "stage_label": "评审选择",
        "narrative": "再看评审边界、竞争压力和入围结果，判断哪些主题开始挤入或被挤出。",
        "support_level": "proxy-grounded",
    },
    {
        "stage_id": "award_contract",
        "stage_label": "立项与合同配置",
        "narrative": "随后把预算、配额和资助强度压上去，看最终合同专项经费如何重分配。",
        "support_level": "proxy-grounded",
    },
    {
        "stage_id": "structural_spillover",
        "stage_label": "结构外溢",
        "narrative": "最后观察协作、中心性、迁移和风险是否发生结构性转移，这一层默认属于代理结果。",
        "support_level": "assumption-heavy",
    },
)


def build_leadership_payload(
    baseline: BaselineSnapshot | None = None,
    scenario: Any = None,
    result: SimulationResult | None = None,
    comparison: SimulationComparison | None = None,
    explanation: SimulationExplanation | None = None,
    *,
    contract: ScenarioContract | Mapping[str, Any] | None = None,
    compiled: CompiledScenario | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a leadership-facing report payload for baseline or scenario artifacts."""
    scenario_contract = _build_contract_section(contract=contract, scenario=scenario, result=result, baseline=baseline)
    compiled_section = _build_compiled_section(compiled=compiled, scenario_contract=scenario_contract)
    stage_impacts, stage_notes = _build_stage_impacts(result)
    topic_identity_profiles = _load_topic_identity_profiles(stage_impacts)
    stage_impacts = _humanize_stage_impacts(
        stage_impacts,
        scenario_contract.get("actions", []),
        topic_identity_profiles=topic_identity_profiles,
    )
    portfolio_assessment = _build_portfolio_assessment(result, comparison, explanation)
    disclosures = _build_disclosures(
        scenario_contract=scenario_contract,
        compiled_section=compiled_section,
        result=result,
        comparison=comparison,
        stage_notes=stage_notes,
    )
    counterfactual = _build_counterfactual_comparison(result, comparison)
    evidence_chain = _build_evidence_chain(
        scenario_contract=scenario_contract,
        compiled_section=compiled_section,
        explanation=explanation,
        result=result,
        disclosures=disclosures,
    )
    reading_frame = _build_reading_frame(
        scenario_contract=scenario_contract,
        compiled_section=compiled_section,
    )
    executive_summary = _build_executive_summary(
        baseline=baseline,
        scenario_contract=scenario_contract,
        compiled_section=compiled_section,
        counterfactual=counterfactual,
        portfolio_assessment=portfolio_assessment,
        disclosures=disclosures,
        stage_impacts=stage_impacts,
    )
    technical_appendix = {
        "result": result.model_dump(mode="json") if result else None,
        "comparison": comparison.model_dump(mode="json") if comparison else None,
        "explanation": explanation.model_dump(mode="json") if explanation else None,
    }
    graph = _build_graph_section(
        baseline=baseline,
        scenario_contract=scenario_contract,
        compiled_section=compiled_section,
        stage_impacts=stage_impacts,
        counterfactual=counterfactual,
    )
    leadership_page = _build_leadership_page(
        scenario_contract=scenario_contract,
        compiled_section=compiled_section,
        counterfactual=counterfactual,
        stage_impacts=stage_impacts,
        graph=graph,
        evidence_chain=evidence_chain,
        disclosures=disclosures,
    )
    visual_scene = _build_visual_scene(
        scenario_contract=scenario_contract,
        leadership_page=leadership_page,
        stage_impacts=stage_impacts,
    )
    _enrich_visual_scene_with_project_data(visual_scene)
    leadership_page["propagation_graph"] = {
        "nodes": visual_scene.get("topics", []),
        "edges": visual_scene.get("edges", []),
    }
    sanity_summary = build_sanity_summary(
        baseline=baseline,
        result=result,
        comparison=comparison,
        compiled_section=compiled_section,
        stage_impacts=stage_impacts,
        disclosures=disclosures,
    )

    return {
        "context": {
            "baseline_id": _pick_first(
                baseline.baseline_id if baseline else None,
                result.baseline_id if result else None,
                scenario_contract.get("baseline_id"),
            ),
            "scenario_id": _pick_first(
                scenario_contract.get("scenario_id"),
                result.scenario_id if result else None,
            ),
            "run_id": result.run_id if result else None,
            "forecast_window": _pick_first(
                result.forecast_window if result else None,
                scenario_contract.get("forecast_window"),
                baseline.forecast_window if baseline else None,
            ),
            "engine": result.metadata.get("engine") if result else None,
        },
        "executive_summary": executive_summary,
        "baseline": _build_baseline_section(baseline),
        "scenario_contract": scenario_contract,
        "compiled": compiled_section,
        "reading_frame": reading_frame,
        "scenario": _model_dump_if_needed(scenario),
        "stage_impacts": stage_impacts,
        "counterfactual_comparison": counterfactual,
        "portfolio_assessment": portfolio_assessment,
        "evidence_chain": evidence_chain,
        "disclosures": disclosures,
        "leadership_page": leadership_page,
        "visual_scene": visual_scene,
        "derived_views": {
            "stage_summary": stage_impacts,
            "counterfactual_summary": counterfactual,
            "portfolio_summary": portfolio_assessment,
            "leadership_summary": {
                "executive_summary": executive_summary,
                "reading_frame": reading_frame,
                "page": leadership_page,
                "visual_scene": visual_scene,
            },
        },
        "audit": {
            "compiled": compiled_section,
            "evidence_chain": evidence_chain,
            "disclosures": disclosures,
            "technical_appendix": technical_appendix,
        },
        "technical_appendix": technical_appendix,
        "sanity_summary": sanity_summary,
    }


def build_sanity_summary(
    *,
    baseline: BaselineSnapshot | None = None,
    result: SimulationResult | None = None,
    comparison: SimulationComparison | None = None,
    compiled_section: dict[str, Any] | None = None,
    stage_impacts: list[dict[str, Any]] | None = None,
    disclosures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a compact audit summary for the generated report."""
    warnings = [
        item["message"]
        for item in (disclosures or [])
        if item.get("severity") in {"warning", "error"}
    ]
    return {
        "baseline": {
            "topic_count": len(baseline.topics) if baseline else 0,
            "source": _baseline_source(baseline),
        },
        "result": {
            "topic_count": len(result.impacts) if result else 0,
            "run_id": result.run_id if result else None,
            "stage_count": len(stage_impacts or []),
        },
        "comparison": {
            "available": comparison is not None,
            "topic_count": comparison.topic_count if comparison else 0,
        },
        "compiled": {
            "support_level": (compiled_section or {}).get("support_level", "unknown"),
            "disclosure_count": len((compiled_section or {}).get("disclosures", [])),
        },
        "warnings": warnings,
    }


def _build_leadership_page(
    *,
    scenario_contract: Mapping[str, Any],
    compiled_section: Mapping[str, Any],
    counterfactual: Mapping[str, Any],
    stage_impacts: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
    evidence_chain: Sequence[Mapping[str, Any]],
    disclosures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    action_resolution = [_as_dict(item) for item in compiled_section.get("action_resolution", []) or [] if _as_dict(item)]
    topic_metrics = _leadership_topic_delta_index(graph)
    selected_targets = _leadership_collect_targets(action_resolution, topic_metrics)
    application_top10 = _leadership_stage_chart(stage_impacts, "application_response")
    funded_top10 = _leadership_stage_chart(stage_impacts, "review_selection")
    funding_top10 = _leadership_stage_chart(stage_impacts, "award_contract")
    impact_table = _leadership_impact_table(stage_impacts)
    summary_cards = [
        _as_dict(item)
        for item in (counterfactual.get("metric_cards") or [])
        if _as_dict(item) and not _leadership_skip_summary_card(_as_dict(item))
    ][:4]
    summary_cards.append(
        {
            "key": "action_count",
            "label": "方案设定数",
            "value": len(action_resolution),
            "format": "int",
        }
    )
    summary_cards.append(
        {
            "key": "affected_topics",
            "label": "影响主题数",
            "value": len(selected_targets),
            "format": "int",
        }
    )
    return {
        "control_panel": {
            "scenario_window": scenario_contract.get("forecast_window"),
            "action_count": len(action_resolution),
            "summary": _leadership_adjustment_summary(selected_targets),
            "targets": selected_targets,
        },
        "summary_cards": summary_cards,
        "application_top10": application_top10,
        "funded_top10": funded_top10,
        "funding_distribution": {
            "items": funding_top10,
        },
        "propagation_graph": {
            "nodes": [
                item
                for item in graph.get("nodes", []) or []
                if _as_dict(item).get("node_type") == "topic"
            ],
            "edges": [
                item
                for item in graph.get("edges", []) or []
                if _as_dict(item).get("edge_type") in {"propagates", "spills_over", "targets"}
            ],
        },
        "impact_table": impact_table,
        "narrative": _leadership_narrative(
            selected_targets=selected_targets,
            application_top10=application_top10,
            funded_top10=funded_top10,
            funding_top10=funding_top10,
            evidence_chain=evidence_chain,
        ),
        "confidence": _leadership_confidence(disclosures),
    }


def _build_baseline_section(baseline: BaselineSnapshot | None) -> dict[str, Any] | None:
    if baseline is None:
        return None

    topics = list(baseline.topics)
    top_topics = sorted(topics, key=lambda item: item.funding_amount, reverse=True)[:8]
    return {
        "baseline_id": baseline.baseline_id,
        "forecast_window": baseline.forecast_window,
        "topic_count": len(topics),
        "source": _baseline_source(baseline),
        "assumptions": list(baseline.assumptions),
        "versions": {
            "data_version": baseline.metadata.get("dataVersion"),
            "feature_version": baseline.metadata.get("featureVersion"),
            "baseline_method": baseline.metadata.get("baselineMethod"),
        },
        "portfolio": {
            "application_count": sum(item.application_count for item in topics),
            "funded_count": sum(item.funded_count for item in topics),
            "funding_amount": round(sum(item.funding_amount for item in topics), 3),
            "avg_proxy_risk": round(sum(item.proxy_risk for item in topics) / len(topics), 6) if topics else 0.0,
        },
        "top_topics": [
            {
                "topic_id": item.topic_id,
                "topic_label": item.topic_label or item.topic_id,
                "application_count": item.application_count,
                "funded_count": item.funded_count,
                "funding_amount": item.funding_amount,
                "proxy_risk": item.proxy_risk,
            }
            for item in top_topics
        ],
        "metadata": baseline.metadata,
    }


def _build_contract_section(
    *,
    contract: ScenarioContract | Mapping[str, Any] | None,
    scenario: Any,
    result: SimulationResult | None,
    baseline: BaselineSnapshot | None,
) -> dict[str, Any]:
    if isinstance(contract, ScenarioContract):
        contract_payload = contract.model_dump(mode="json")
    elif isinstance(contract, Mapping):
        contract_payload = dict(contract)
    else:
        contract_payload = _synthesize_contract_from_scenario(scenario, result=result, baseline=baseline)

    baseline_scope = _as_dict(contract_payload.get("baseline"))
    if not baseline_scope:
        baseline_scope = _as_dict(contract_payload.get("baseline_scope"))

    contract_metadata = _as_dict(contract_payload.get("metadata"))
    if "contract_source" not in contract_metadata:
        if contract is not None:
            contract_metadata["contract_source"] = "scenario_contract"
        elif scenario is not None:
            contract_metadata["contract_source"] = "legacy_scenario_definition"
        else:
            contract_metadata["contract_source"] = "result_only"
    if "baseline_window" not in contract_metadata and baseline is not None:
        contract_metadata["baseline_window"] = baseline.forecast_window

    topic_catalog = _build_topic_catalog(baseline=baseline, result=result)

    actions = [_normalize_action(item) for item in contract_payload.get("actions", []) if _as_dict(item)]
    if not actions:
        actions = [_normalize_action(item) for item in contract_payload.get("policy_package", []) if _as_dict(item)]
    actions = [_enrich_action(item, topic_catalog=topic_catalog, index=index) for index, item in enumerate(actions, start=1)]

    constraints = [
        _normalize_constraint(item)
        for item in contract_payload.get("constraints", [])
        if _as_dict(item)
    ]
    evaluation_goals = [
        _normalize_goal(item)
        for item in contract_payload.get("evaluation_goals", [])
        if _as_dict(item)
    ]
    validation = _normalize_validation(contract_payload.get("validation"))
    intent = _normalize_intent(contract_payload.get("intent"))
    if not any(intent.values()):
        intent = _build_generated_intent(actions)
    else:
        generated = _build_generated_intent(actions)
        for key, value in generated.items():
            if not intent.get(key):
                intent[key] = value

    scenario_name = str(contract_payload.get("scenario_name") or contract_payload.get("scenarioName") or "").strip()
    if not scenario_name:
        scenario_name = _build_generated_scenario_name(actions)

    return {
        "scenario_id": str(contract_payload.get("scenario_id") or contract_payload.get("scenarioId") or result.scenario_id if result else ""),
        "scenario_name": scenario_name or "未命名政策方案",
        "forecast_window": str(
            contract_payload.get("forecast_window")
            or contract_payload.get("forecastWindow")
            or result.forecast_window
            if result
            else ""
        ),
        "baseline_id": str(
            baseline_scope.get("baseline_id")
            or baseline_scope.get("baselineId")
            or (baseline.baseline_id if baseline else "")
        ),
        "intent": intent,
        "baseline_scope": baseline_scope,
        "basis_documents": [
            _normalize_basis_document(item)
            for item in contract_payload.get("basis_documents", [])
            if _as_dict(item)
        ],
        "actions": actions,
        "constraints": constraints,
        "evaluation_goals": evaluation_goals,
        "assumptions": _string_list(contract_payload.get("assumptions")),
        "validation": validation,
        "tags": _string_list(contract_payload.get("tags")),
        "metadata": contract_metadata,
    }


def _build_compiled_section(
    *,
    compiled: CompiledScenario | Mapping[str, Any] | None,
    scenario_contract: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(compiled, CompiledScenario):
        compiled_payload = compiled.model_dump(mode="json")
    elif isinstance(compiled, Mapping):
        compiled_payload = dict(compiled)
    else:
        actions = scenario_contract.get("actions", [])
        contract_source = _as_dict(scenario_contract.get("metadata")).get("contract_source")
        support_level = "legacy_compatible" if contract_source == "legacy_scenario_definition" else "unknown"
        disclosures = []
        if support_level == "legacy_compatible":
            disclosures.append(
                {
                    "code": "scenario_definition_only",
                    "severity": "info",
                    "label": _DISCLOSURE_SEVERITY_LABELS["info"],
                    "message": "当前输入只有场景设定和推演结果，没有正式方案全文。",
                    "field_path": "compiled",
                }
            )
        return {
            "support_level": support_level,
            "support_label": _support_label(support_level),
            "basis_document_ids": [],
            "baseline_topic_ids": [],
            "action_resolution": [
                {
                    "action_id": item.get("action_id"),
                    "action_type": item.get("action_type"),
                    "stage": item.get("stage"),
                    "stage_label": item.get("stage_label"),
                    "action_label": item.get("action_label"),
                    "target_summary": item.get("target_summary"),
                    "support_level": item.get("support_level") or support_level,
                    "support_label": _support_label(item.get("support_level") or support_level),
                    "resolved_topic_ids": list(item.get("target_scope", {}).get("topic_ids", [])),
                    "target_labels": list(item.get("target_scope", {}).get("topic_labels", [])),
                    "resolved_topic_labels": list(item.get("target_scope", {}).get("topic_labels", [])),
                    "basis_document_ids": list(item.get("basis_document_ids", [])),
                    "compiled_guardrails": {},
                    "rule_summary": "",
                    "evidence_requirement": list(item.get("evidence_requirement", [])),
                    "notes": list(item.get("notes", [])),
                }
                for item in actions
            ],
            "disclosures": disclosures,
            "compiler_summary": {
                "action_count": len(actions),
                "resolved_action_count": len(actions),
                "basis_document_count": 0,
                "warning_count": 0,
                "error_count": 0,
            },
        }

    disclosures = [_normalize_disclosure(item) for item in compiled_payload.get("disclosures", []) if _as_dict(item)]
    support_level = str(compiled_payload.get("support_level") or "unknown")
    action_target_topic_ids = _as_dict(compiled_payload.get("action_target_topic_ids"))
    compiled_action_map = {
        str(_as_dict(item).get("action_id") or ""): _as_dict(item)
        for item in compiled_payload.get("compiled_actions", [])
        if _as_dict(item)
    }
    action_resolution = []
    raw_contract = _as_dict(compiled_payload.get("contract"))
    contract_actions = scenario_contract.get("actions", []) or raw_contract.get("actions", [])
    for item in contract_actions:
        normalized_action = _normalize_action(item)
        action = {
            **normalized_action,
            **_as_dict(item),
            "action_id": normalized_action["action_id"],
            "action_type": normalized_action["action_type"],
            "target_scope": _as_dict(item.get("target_scope")) or normalized_action["target_scope"],
        }
        compiled_action = compiled_action_map.get(action["action_id"], {})
        resolved_ids = [
            str(topic_id)
            for topic_id in action_target_topic_ids.get(action["action_id"], [])
            if str(topic_id).strip()
        ]
        resolved_labels = _string_list(compiled_action.get("resolved_topic_labels"))
        if not resolved_labels:
            resolved_labels = list(action["target_scope"]["topic_labels"])
        action_resolution.append(
            {
                "action_id": action["action_id"],
                "action_type": action["action_type"],
                "stage": str(compiled_action.get("stage") or action["stage"]),
                "stage_label": action.get("stage_label") or _stage_label(str(compiled_action.get("stage") or action["stage"])),
                "action_label": action.get("action_label"),
                "display_title": action.get("display_title"),
                "target_summary": action.get("target_summary"),
                "support_level": str(compiled_action.get("support_level") or action.get("support_level") or support_level),
                "support_label": _support_label(str(compiled_action.get("support_level") or action.get("support_level") or support_level)),
                "resolved_topic_ids": resolved_ids,
                "target_labels": _string_list(_as_dict(action["target_scope"]).get("topic_labels")),
                "resolved_topic_labels": resolved_labels,
                "basis_document_ids": _string_list(compiled_action.get("basis_document_ids") or action.get("basis_document_ids")),
                "compiled_guardrails": _normalize_compiled_guardrails(compiled_action.get("compiled_guardrails")),
                "rule_summary": _rule_summary(compiled_action.get("rule")),
                "evidence_requirement": _string_list(compiled_action.get("evidence_requirement") or action.get("evidence_requirement")),
                "notes": _string_list(compiled_action.get("notes") or action["notes"]),
            }
        )

    return {
        "support_level": support_level,
        "support_label": _support_label(support_level),
        "basis_document_ids": list(compiled_payload.get("basis_document_ids", [])),
        "baseline_topic_ids": list(compiled_payload.get("baseline_topic_ids", [])),
        "action_resolution": action_resolution,
        "disclosures": disclosures,
        "compiler_summary": {
            "action_count": len(action_resolution),
            "resolved_action_count": sum(1 for item in action_resolution if item["resolved_topic_ids"] or item["target_labels"]),
            "basis_document_count": len(list(compiled_payload.get("basis_document_ids", []))),
            "warning_count": sum(1 for item in disclosures if item["severity"] == "warning"),
            "error_count": sum(1 for item in disclosures if item["severity"] == "error"),
        },
    }


def _build_stage_impacts(
    result: SimulationResult | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if result is None:
        return [], []

    if result.stage_results:
        return _normalize_native_stage_results(result.stage_results), []

    stage_impacts = [
        _synthesize_governance_stage(result, spec)
        for spec in _GOVERNANCE_STAGE_SPECS
    ]
    return stage_impacts, [
        {
            "code": "governance_stage_synthesized",
            "severity": "info",
            "label": _DISCLOSURE_SEVERITY_LABELS["info"],
            "message": "当前页面的治理流程四段由正式结果指标整理成阶段视图；后续如果引擎直接产出完整阶段结果，可以直接替换成原始阶段结果。",
            "field_path": "stage_impacts",
        }
    ]


def _build_counterfactual_comparison(
    result: SimulationResult | None,
    comparison: SimulationComparison | None,
) -> dict[str, Any]:
    if result and result.counterfactual_comparison is not None:
        payload = result.counterfactual_comparison.model_dump(mode="json")
    else:
        impacts = list(result.impacts) if result else []
        payload = {
            "total_topics": len(impacts),
            "material_topic_count": sum(1 for item in impacts if _impact_magnitude(item) > 0.0),
            "net_delta_application_count": round(sum(item.delta_application_count for item in impacts), 3),
            "net_delta_funded_count": round(sum(item.delta_funded_count for item in impacts), 3),
            "net_delta_funding_amount": round(sum(item.delta_funding_amount for item in impacts), 3),
            "avg_delta_proxy_risk": round(sum(item.delta_proxy_risk for item in impacts) / len(impacts), 6) if impacts else 0.0,
            "goal_attainment": [],
            "summary": [],
        }

    metric_cards = [
        {
            "key": "application_count",
            "label": "申报项目数净变化",
            "value": payload.get("net_delta_application_count", 0.0),
            "format": "int",
        },
        {
            "key": "funded_count",
            "label": "立项数净变化",
            "value": payload.get("net_delta_funded_count", 0.0),
            "format": "int",
        },
        {
            "key": "funding_amount",
            "label": "合同专项经费净变化",
            "value": payload.get("net_delta_funding_amount", 0.0),
            "format": "currency",
        },
        {
            "key": "proxy_risk",
            "label": "平均风险代理变化",
            "value": payload.get("avg_delta_proxy_risk", 0.0),
            "format": "decimal",
        },
    ]

    summary = list(payload.get("summary") or [])
    if not summary and comparison is not None:
        management = _management_summary(comparison)
        summary = list(management.get("executiveSummary") or [])

    payload["metric_cards"] = metric_cards
    payload["summary"] = summary
    payload["goal_attainment"] = [
        _normalize_goal_attainment(item)
        for item in payload.get("goal_attainment", [])
        if _as_dict(item)
    ]
    return payload


def _build_portfolio_assessment(
    result: SimulationResult | None,
    comparison: SimulationComparison | None,
    explanation: SimulationExplanation | None,
) -> dict[str, Any]:
    management = _management_summary(comparison, explanation)
    return {
        "executive_summary": list(management.get("executiveSummary") or []),
        "recommended_add_topics": _normalize_management_topics(management.get("recommendedAddTopics")),
        "recommended_stop_loss_topics": _normalize_management_topics(management.get("recommendedStopLossTopics")),
        "side_effect_topics": _normalize_management_topics(management.get("sideEffectTopics")),
        "observe_topic_count": int(management.get("observeTopicCount", 0) or 0),
        "impact_origin_summary": list(management.get("impactOriginSummary") or []),
        "winners_and_losers": _normalize_outcome_topics(result),
        "crowding_out": _normalize_crowding_out(result),
        "risk_shift": _normalize_risk_shift(result),
        "recommendations": list(result.evidence_backed_recommendations if result else []) or list(management.get("executiveSummary") or [])[:3],
    }


def _build_evidence_chain(
    *,
    scenario_contract: dict[str, Any],
    compiled_section: dict[str, Any],
    explanation: SimulationExplanation | None,
    result: SimulationResult | None,
    disclosures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    if scenario_contract.get("actions"):
        chain.append(
            {
                "title": "这次设定",
                "detail": f"本次共设置 {len(scenario_contract['actions'])} 条推演设定。",
                "support_level": compiled_section.get("support_level", "unknown"),
            }
        )
    if scenario_contract.get("basis_documents"):
        chain.append(
            {
                "title": "正式依据",
                "detail": f"其中 {len(scenario_contract['basis_documents'])} 份正式文本用于约束执行范围和执行边界。",
                "support_level": "observed-grounded",
            }
        )
    if compiled_section.get("disclosures"):
        chain.append(
            {
                "title": "执行边界",
                "detail": f"本次共形成 {len(compiled_section['disclosures'])} 条边界说明，用来区分哪些部分能按正式依据执行，哪些只能做趋势试算。",
                "support_level": compiled_section.get("support_level", "unknown"),
            }
        )
    if explanation and explanation.summary:
        chain.append(
            {
                "title": "结果解释",
                "detail": explanation.summary[0],
                "support_level": "proxy-grounded",
            }
        )
    if result and result.limitations:
        chain.append(
            {
                "title": "结果限制",
                "detail": result.limitations[0],
                "support_level": "assumption-heavy",
            }
        )
    if disclosures:
        chain.append(
            {
                "title": "注意事项",
                "detail": f"本页共保留 {len(disclosures)} 条关键限制，结论需要结合这些边界一起看。",
                "support_level": "unknown",
            }
        )
    return chain


def _build_disclosures(
    *,
    scenario_contract: dict[str, Any],
    compiled_section: dict[str, Any],
    result: SimulationResult | None,
    comparison: SimulationComparison | None,
    stage_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    disclosures: list[dict[str, Any]] = list(compiled_section.get("disclosures", []))
    validation = _as_dict(scenario_contract.get("validation"))
    for metric_name in validation.get("proxy_metrics", []):
        disclosures.append(
            {
                "code": "proxy_metric",
                "severity": "info",
                "label": _DISCLOSURE_SEVERITY_LABELS["info"],
                "message": f"{metric_name} 仅能作为代理结果解读，不应外推成真实业务结果。",
                "field_path": "scenario_contract.validation.proxy_metrics",
            }
        )
    for claim in validation.get("unsupported_claims", []):
        disclosures.append(
            {
                "code": "unsupported_claim",
                "severity": "warning",
                "label": _DISCLOSURE_SEVERITY_LABELS["warning"],
                "message": claim,
                "field_path": "scenario_contract.validation.unsupported_claims",
            }
        )
    if result:
        for item in result.limitations:
            disclosures.append(
                {
                    "code": "result_limitation",
                    "severity": "warning",
                    "label": _DISCLOSURE_SEVERITY_LABELS["warning"],
                    "message": item,
                    "field_path": "result.limitations",
                }
            )
    if comparison is None and result is not None:
        disclosures.append(
            {
                "code": "comparison_missing",
                "severity": "warning",
                "label": _DISCLOSURE_SEVERITY_LABELS["warning"],
                "message": "当前报告缺少独立 comparison 结果，组合级建议将回退为基于 impacts 的汇总判断。",
                "field_path": "comparison",
            }
        )
    disclosures.extend(stage_notes)
    return _dedupe_disclosures(disclosures)


def _build_executive_summary(
    *,
    baseline: BaselineSnapshot | None,
    scenario_contract: dict[str, Any],
    compiled_section: dict[str, Any],
    counterfactual: dict[str, Any],
    portfolio_assessment: dict[str, Any],
    disclosures: list[dict[str, Any]],
    stage_impacts: list[dict[str, Any]],
) -> dict[str, Any]:
    support_level = compiled_section.get("support_level", "unknown")
    positive = len(portfolio_assessment.get("recommended_add_topics", []))
    negative = len(portfolio_assessment.get("recommended_stop_loss_topics", []))
    side_effects = len(portfolio_assessment.get("side_effect_topics", []))
    actions = scenario_contract.get("actions", [])
    contract_source = _as_dict(scenario_contract.get("metadata")).get("contract_source")
    fallback_bullets = _build_fallback_headline_bullets(
        actions=actions,
        counterfactual=counterfactual,
        stage_impacts=stage_impacts,
    )
    if contract_source == "legacy_scenario_definition":
        decision_call = "以下展示这条设定下的结果变化。"
    elif positive == 0 and negative == 0 and side_effects == 0:
        decision_call = ""
    else:
        decision_call = (
            f"当前方案可执行支持度为“{_support_label(support_level)}”。"
            f"建议加码 {positive} 个主题，止损 {negative} 个主题，需重点防副作用 {side_effects} 个主题。"
        )
    return {
        "title": scenario_contract.get("scenario_name") or "政策沙盘领导页",
        "question": _normalize_intent(scenario_contract.get("intent")).get("question") or "未提供明确决策问题",
        "support_level": support_level,
        "support_label": _support_label(support_level),
        "hero_metrics": [
            {
                "label": "覆盖主题",
                "value": counterfactual.get("total_topics") or (len(baseline.topics) if baseline else 0),
                "detail": "纳入本次推演的主题总数。",
            },
            {
                "label": "方案设定",
                "value": len(scenario_contract.get("actions", [])),
                "detail": "本次真正进入推演的设定数。",
            },
            {
                "label": "正式依据",
                "value": len(scenario_contract.get("basis_documents", [])),
                "detail": "本次挂接的正式指南/政策数。",
            },
            {
                "label": "阅读边界",
                "value": len(disclosures),
                "detail": "阅读结论时需要同时考虑的关键限制数。",
            },
        ],
        "decision_call": decision_call,
        "headline_bullets": (
            list(portfolio_assessment.get("executive_summary") or [])
            or list(counterfactual.get("summary") or [])
            or fallback_bullets
        )[:4],
    }


def _build_reading_frame(
    *,
    scenario_contract: Mapping[str, Any],
    compiled_section: Mapping[str, Any],
) -> dict[str, Any]:
    actions = [_as_dict(item) for item in scenario_contract.get("actions", []) or [] if _as_dict(item)]
    intent = _normalize_intent(scenario_contract.get("intent"))
    contract_source = _as_dict(scenario_contract.get("metadata")).get("contract_source")
    first_action = actions[0] if actions else {}
    target_scope = _as_dict(first_action.get("target_scope"))
    target_count = int(_as_number(target_scope.get("target_count") or len(target_scope.get("topic_ids") or [])))
    target_summary = str(first_action.get("target_summary") or "全体主题")
    raw_field = str(first_action.get("action_type") or "未提供").strip()
    raw_intensity = first_action.get("intensity")
    display_title = str(first_action.get("display_title") or "当前未显式配置方案设定").strip()
    scenario_window = str(scenario_contract.get("forecast_window") or "").strip()
    baseline_window = str(_as_dict(scenario_contract.get("metadata")).get("baseline_window") or "").strip()

    if contract_source == "legacy_scenario_definition":
        intro = "目前拿到的不是正式方案文本，只能看到一条推演设定。"
        known_facts = [
            (
                f"这次模拟只设置了 {len(actions)} 条条件：{display_title}"
                f"{_raw_intensity_suffix(raw_intensity)}。"
            )
            if actions
            else "当前没有拿到可直接展示的推演条件。"
        ]
        interpretation = [
            (
                f"原始结果里这批对象都沿用了“{target_summary}”这类统称，"
                "页面只能按当前申报、立项、经费规模把同名主题拆开显示。"
            )
            if actions
            else "当前页面缺少足够的设定信息，只能展示已有结果。"
        ]
        boundary = "如果后续补到正式方案文本和更细主题名称，应直接替换为正式口径。"
    elif intent.get("question"):
        intro = intent.get("question")
        known_facts = [
            f"本次共设置 {len(actions)} 条推演设定。"
        ]
        interpretation = []
        boundary = ""
    else:
        intro = "原始数据没有单独写明这次方案要解决什么问题。"
        known_facts = [
            f"当前能确认的是：本次共设置 {len(actions)} 条推演设定。"
        ]
        interpretation = []
        boundary = ""

    return {
        "intro": intro,
        "known_facts": known_facts,
        "interpretation": interpretation,
        "boundary": boundary,
        "display_title": display_title,
        "raw_field": raw_field,
        "target_summary": target_summary,
        "setting_count": len(actions),
        "support_label": _support_label(str(compiled_section.get("support_level") or "unknown")),
        "scenario_window": scenario_window,
        "baseline_window": baseline_window,
    }


def _leadership_adjustment_summary(targets: Sequence[Mapping[str, Any]]) -> str:
    total_funding = round(sum(_as_number(_as_dict(item).get("funding")) for item in targets), 3)
    total_projects = round(sum(_as_number(_as_dict(item).get("projects")) for item in targets), 3)
    parts = []
    if targets:
        parts.append(f"对 {len(targets)} 个研究方向增加支持")
    if total_funding:
        parts.append(f"新增经费 {total_funding:.1f} 万元")
    if total_projects:
        parts.append(f"新增项目 {int(round(total_projects))} 个")
    return "，".join(parts) if parts else "当前没有解析出可展示的调整。"


def _leadership_stage_chart(
    stage_impacts: Sequence[Mapping[str, Any]],
    stage_id: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    stage = next(
        (_as_dict(item) for item in stage_impacts if str(_as_dict(item).get("stage_id") or "").strip() == stage_id),
        {},
    )
    aggregated: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw_item in stage.get("top_topics", []) or []:
        item = _as_dict(raw_item)
        if not item:
            continue
        label = _leadership_topic_label(item)
        current = aggregated.get(label)
        if current is None:
            current = {
                "topic_id": item.get("topic_id"),
                "label": label,
                "delta": 0.0,
                "metric": item.get("metric"),
                "metric_label": item.get("metric_label"),
                "impact_origin_label": item.get("impact_origin_label"),
                "baseline_application_count": 0.0,
                "baseline_funded_count": 0.0,
                "baseline_funding_amount": 0.0,
                "children": [],
                "years": [],
                "topic_ids": [],
            }
            aggregated[label] = current
            order.append(label)
        current["delta"] = _as_number(current.get("delta")) + _as_number(item.get("delta"))
        current["baseline_application_count"] = _as_number(current.get("baseline_application_count")) + _as_number(item.get("baseline_application_count"))
        current["baseline_funded_count"] = _as_number(current.get("baseline_funded_count")) + _as_number(item.get("baseline_funded_count"))
        current["baseline_funding_amount"] = _as_number(current.get("baseline_funding_amount")) + _as_number(item.get("baseline_funding_amount"))
        child = _leadership_topic_child(item)
        current["children"].append(child)
        if child.get("year") and child["year"] not in current["years"]:
            current["years"].append(child["year"])
        if child.get("topic_id") and child["topic_id"] not in current["topic_ids"]:
            current["topic_ids"].append(child["topic_id"])
        if current.get("impact_origin_label") != item.get("impact_origin_label"):
            current["impact_origin_label"] = "直接与传导共同作用"
    output = [aggregated[key] for key in order]
    output.sort(key=lambda row: abs(_as_number(row.get("delta"))), reverse=True)
    return output[:limit]


def _leadership_impact_table(stage_impacts: Sequence[Mapping[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    aggregated: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str, str]] = []
    for raw_stage in stage_impacts:
        stage = _as_dict(raw_stage)
        stage_label = str(stage.get("stage_label") or "").strip()
        for raw_item in stage.get("top_topics", []) or []:
            item = _as_dict(raw_item)
            if not item:
                continue
            key = (
                str(item.get("impact_origin_label") or "").strip(),
                _leadership_topic_label(item),
                str(item.get("metric_label") or "").strip(),
                stage_label,
            )
            current = aggregated.get(key)
            if current is None:
                current = {
                    "impact_type": key[0],
                    "object_label": key[1],
                    "metric_label": key[2],
                    "delta": 0.0,
                    "stage_label": key[3],
                    "support_level": stage.get("support_level"),
                    "children": [],
                }
                aggregated[key] = current
                order.append(key)
            current["delta"] = _as_number(current.get("delta")) + _as_number(item.get("delta"))
            current["children"].append(_leadership_topic_child(item))
    rows = [aggregated[key] for key in order]
    rows.sort(key=lambda item: abs(_as_number(item.get("delta"))), reverse=True)
    return rows[:limit]


def _leadership_topic_child(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "topic_id": item.get("topic_id"),
        "display_label": item.get("display_label") or item.get("topic_label"),
        "year": item.get("topic_identity_year"),
        "scope": item.get("topic_identity_scope"),
        "broad_scope": item.get("topic_identity_broad_scope"),
        "guide_label": item.get("topic_identity_guide_label"),
        "guide_code": item.get("topic_identity_guide_code"),
        "metric": item.get("metric"),
        "metric_label": item.get("metric_label"),
        "delta": item.get("delta"),
        "delta_sentence": item.get("delta_sentence"),
        "impact_origin": item.get("impact_origin"),
        "impact_origin_label": item.get("impact_origin_label"),
        "display_context": item.get("display_context"),
        "stage_story": item.get("stage_story"),
        "baseline_application_count": item.get("baseline_application_count"),
        "baseline_funded_count": item.get("baseline_funded_count"),
        "baseline_funding_amount": item.get("baseline_funding_amount"),
    }


def _leadership_narrative(
    *,
    selected_targets: Sequence[Mapping[str, Any]],
    application_top10: Sequence[Mapping[str, Any]],
    funded_top10: Sequence[Mapping[str, Any]],
    funding_top10: Sequence[Mapping[str, Any]],
    evidence_chain: Sequence[Mapping[str, Any]],
) -> list[str]:
    output: list[str] = []
    if selected_targets:
        output.append(_leadership_adjustment_summary(selected_targets))
    if application_top10:
        first = _as_dict(application_top10[0])
        output.append(
            f"申报端变化最大的是 {first.get('label') or '未标注对象'}，变化 { _format_delta_text(first.get('delta'), 'int') }。"
        )
    if funded_top10:
        first = _as_dict(funded_top10[0])
        output.append(
            f"立项端变化最大的是 {first.get('label') or '未标注对象'}，变化 { _format_delta_text(first.get('delta'), 'int') }。"
        )
    if funding_top10:
        first = _as_dict(funding_top10[0])
        output.append(
            f"经费端变化最大的是 {first.get('label') or '未标注对象'}，变化 { _format_delta_text(first.get('delta'), 'currency') } 万元。"
        )
    for item in evidence_chain:
        detail = str(_as_dict(item).get("detail") or "").strip()
        if detail:
            output.append(detail)
        if len(output) >= 4:
            break
    return output[:4]


def _leadership_confidence(disclosures: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in disclosures:
        payload = _as_dict(item)
        if not payload:
            continue
        severity = str(payload.get("severity") or "info").strip() or "info"
        label = _DISCLOSURE_SEVERITY_LABELS.get(severity, "说明")
        message = str(payload.get("message") or "").strip()
        if not message:
            continue
        output.append(
            {
                "severity": severity,
                "label": label,
                "message": message,
            }
        )
    return output[:5]


def _format_delta_text(value: Any, fmt: str) -> str:
    numeric = _as_number(value)
    if fmt == "currency":
        return f"{numeric:+.1f}"
    return f"{int(round(numeric)):+d}"


def _leadership_skip_summary_card(item: Mapping[str, Any]) -> bool:
    fmt = str(item.get("format") or "").strip()
    value = _as_number(item.get("value"))
    if fmt == "decimal" and abs(value) < 1e-3:
        return True
    return False


def _build_visual_scene(
    *,
    scenario_contract: Mapping[str, Any],
    leadership_page: Mapping[str, Any],
    stage_impacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    active_year = _visual_active_year(_as_dict(leadership_page.get("control_panel")).get("scenario_window"))
    nodes_by_year: dict[str, dict[str, dict[str, Any]]] = {}
    order_by_year: dict[str, list[str]] = {}
    for raw_stage in stage_impacts:
        stage = _as_dict(raw_stage)
        stage_id = str(stage.get("stage_id") or "").strip()
        stage_label = str(stage.get("stage_label") or "").strip()
        support_level = str(stage.get("support_level") or "").strip()
        for raw_item in stage.get("top_topics", []) or []:
            item = _as_dict(raw_item)
            if not item:
                continue
            year = _visual_item_year(item) or active_year or "current"
            nodes_by_key = nodes_by_year.setdefault(year, {})
            order = order_by_year.setdefault(year, [])
            key = _visual_identity_key(item)
            node = nodes_by_key.get(key)
            if node is None:
                node = {
                    "id": key,
                    "label": _leadership_topic_label(item),
                    "scope": item.get("topic_identity_scope"),
                    "broadScope": item.get("topic_identity_broad_scope"),
                    "guideLabel": item.get("topic_identity_guide_label") or item.get("topic_label"),
                    "guideCode": item.get("topic_identity_guide_code"),
                    "years": [],
                    "topicIds": [],
                    "metrics": {
                        "deltaApplication": 0.0,
                        "deltaFunded": 0.0,
                        "deltaFunding": 0.0,
                        "deltaCentrality": 0.0,
                    },
                    "baseline": {
                        "application": 0.0,
                        "funded": 0.0,
                        "funding": 0.0,
                    },
                    "directCount": 0,
                    "spillCount": 0,
                    "children": [],
                    "_children_by_topic": {},
                }
                nodes_by_key[key] = node
                order.append(key)

            metric = str(item.get("metric") or "").strip()
            delta = _as_number(item.get("delta"))
            if metric == "delta_application_count":
                node["metrics"]["deltaApplication"] += delta
            elif metric == "delta_funded_count":
                node["metrics"]["deltaFunded"] += delta
            elif metric == "delta_funding_amount":
                node["metrics"]["deltaFunding"] += delta
            elif metric == "delta_topic_centrality":
                node["metrics"]["deltaCentrality"] += delta

            origin = str(item.get("impact_origin") or "").strip()
            if origin == "spillover":
                node["spillCount"] += 1
            else:
                node["directCount"] += 1

            topic_id = str(item.get("topic_id") or item.get("display_label") or key).strip()
            children_by_topic = node["_children_by_topic"]
            child = children_by_topic.get(topic_id)
            if child is None:
                child = {
                    "topicId": topic_id,
                    "displayLabel": item.get("display_label") or item.get("topic_label"),
                    "year": item.get("topic_identity_year"),
                    "scope": item.get("topic_identity_scope"),
                    "guideLabel": item.get("topic_identity_guide_label"),
                    "guideCode": item.get("topic_identity_guide_code"),
                    "baselineApplication": item.get("baseline_application_count"),
                    "baselineFunded": item.get("baseline_funded_count"),
                    "baselineFunding": item.get("baseline_funding_amount"),
                    "metrics": [],
                    "impactOrigins": [],
                    "displayContext": item.get("display_context"),
                }
                children_by_topic[topic_id] = child
                node["children"].append(child)
                if child.get("year") and child["year"] not in node["years"]:
                    node["years"].append(child["year"])
                if topic_id and topic_id not in node["topicIds"]:
                    node["topicIds"].append(topic_id)
                node["baseline"]["application"] += _as_number(item.get("baseline_application_count"))
                node["baseline"]["funded"] += _as_number(item.get("baseline_funded_count"))
                node["baseline"]["funding"] += _as_number(item.get("baseline_funding_amount"))
            if origin and origin not in child["impactOrigins"]:
                child["impactOrigins"].append(origin)
            child["metrics"].append(
                {
                    "stageId": stage_id,
                    "stageLabel": stage_label,
                    "metric": metric,
                    "metricLabel": item.get("metric_label"),
                    "delta": delta,
                    "deltaSentence": item.get("delta_sentence"),
                    "impactOrigin": item.get("impact_origin"),
                    "impactOriginLabel": item.get("impact_origin_label"),
                    "supportLevel": support_level,
                    "story": item.get("stage_story"),
                }
            )

    year_runs: dict[str, dict[str, Any]] = {}
    for year in sorted(nodes_by_year, key=_visual_year_sort_key, reverse=True):
        nodes = _finalize_visual_nodes(nodes_by_year[year], order_by_year.get(year, []))
        data_year = _visual_baseline_year_for_run(year=year, active_year=active_year)
        year_runs[year] = {
            "year": year,
            "dataYear": data_year,
            "role": _visual_year_role(year, active_year),
            "label": _visual_year_label(year, active_year, data_year=data_year),
            "topics": nodes,
            "edges": _build_visual_edges(nodes),
            "focusTopicId": str((nodes[0] if nodes else {}).get("id") or ""),
            "validation": _visual_year_validation(year, active_year),
        }

    _attach_backtest_year_runs(year_runs, active_year)

    active_run = year_runs.get(active_year) or next(iter(year_runs.values()), {"topics": [], "edges": [], "focusTopicId": ""})
    return {
        "version": 1,
        "activeYear": active_year,
        "runOrder": _visual_year_order(year_runs, active_year),
        "scenario": {
            "id": scenario_contract.get("scenario_id"),
            "name": scenario_contract.get("scenario_name") or "当前方案",
            "summary": _as_dict(leadership_page.get("control_panel")).get("summary"),
            "window": _as_dict(leadership_page.get("control_panel")).get("scenario_window"),
        },
        "yearRuns": year_runs,
        "focusTopicId": active_run.get("focusTopicId"),
        "topics": active_run.get("topics", []),
        "edges": active_run.get("edges", []),
        "filters": [
            {"id": "all", "label": "全部影响"},
            {"id": "direct", "label": "只看本次打到"},
            {"id": "spill", "label": "显示外溢"},
        ],
    }


def _attach_backtest_year_runs(year_runs: dict[str, dict[str, Any]], active_year: str) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if not active_year.isdigit() or active_year not in year_runs:
        return
    active_run = _as_dict(year_runs.get(active_year))
    active_topics = [_as_dict(item) for item in active_run.get("topics", []) or [] if _as_dict(item)]
    if not active_topics:
        return

    backtest_years = list(range(int(active_year) - 1, _BACKTEST_EARLIEST_VALIDATION_YEAR - 1, -1))
    if not backtest_years:
        return

    topic_ids = _dedupe_strings(
        topic_id
        for topic in active_topics
        for topic_id in _string_list(topic.get("topicIds"))
    )
    if not topic_ids:
        return

    try:
        facts = load_project_facts(start_year=_BACKTEST_TRAINING_START_YEAR, end_year=max(backtest_years))
    except Exception as exc:
        raise RuntimeError(
            f"failed to load real project facts for backtest years {backtest_years[0]}-{backtest_years[-1]}"
        ) from exc

    stats_by_topic_year = _build_topic_year_stats(facts, topic_ids)

    for year in sorted(backtest_years, reverse=True):
        if str(year) in year_runs:
            continue
        nodes = _build_backtest_nodes(
            year=year,
            active_topics=active_topics,
            stats_by_topic_year=stats_by_topic_year,
        )
        if not nodes:
            continue
        data_year = year - 1
        year_runs[str(year)] = {
            "year": str(year),
            "dataYear": data_year,
            "role": "backtest",
            "label": f"{data_year} → {year} 回测",
            "trainWindow": f"{_BACKTEST_TRAINING_START_YEAR}-{year - 1}",
            "validationYear": year,
            "topics": nodes,
            "edges": _build_visual_edges(nodes),
            "focusTopicId": str((nodes[0] if nodes else {}).get("id") or ""),
            "validation": _visual_year_validation(str(year), active_year),
            "backtestSummary": _summarize_backtest_nodes(nodes),
        }


def _enrich_visual_scene_with_project_data(visual_scene: dict[str, Any]) -> None:
    """Attach real project database context to the graph without changing graph topology."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    years = _visual_scene_years(visual_scene)
    active_year = str(visual_scene.get("activeYear") or "").strip()
    active_year_int = int(active_year) if active_year.isdigit() else None
    if not years and active_year_int:
        years = [active_year_int]
    if not years:
        return

    start_year = min(2020, min(years))
    end_year = max(max(years), datetime.now().year)
    try:
        facts = load_project_facts(start_year=start_year, end_year=end_year)
    except Exception:
        return

    facts_by_year: dict[int, list[Any]] = {}
    facts_by_year_topic: dict[int, dict[str, list[Any]]] = {}
    for fact in facts:
        year = int(getattr(fact, "application_year", 0) or 0)
        if year <= 0:
            continue
        facts_by_year.setdefault(year, []).append(fact)
        topic_id = str(getattr(fact, "topic_id", "") or "").strip().lower()
        if topic_id:
            facts_by_year_topic.setdefault(year, {}).setdefault(topic_id, []).append(fact)

    year_runs = _as_dict(visual_scene.get("yearRuns"))
    for year_text, raw_run in list(year_runs.items()):
        run = _as_dict(raw_run)
        if not run:
            continue
        run_year = int(year_text) if str(year_text).isdigit() else active_year_int
        if not run_year:
            continue
        data_year = _visual_run_data_year(run, active_year_int=active_year_int, run_year=run_year)
        year_facts = facts_by_year.get(data_year, [])
        run["baselineContext"] = _build_year_baseline_context(
            year=data_year,
            facts=year_facts,
            shown_topics=len(run.get("topics", []) or []),
        )
        run["availableTopicCount"] = run["baselineContext"].get("topicCount")
        topics = list(run.get("topics", []) or [])
        for index, topic in enumerate(topics):
            topic_payload = _as_dict(topic)
            topic_ids = [item.lower() for item in _string_list(topic_payload.get("topicIds"))]
            topic_facts: list[Any] = []
            for topic_id in topic_ids:
                topic_facts.extend(facts_by_year_topic.get(data_year, {}).get(topic_id, []))
            topic_payload["detailProfile"] = _build_topic_detail_profile(
                topic=topic_payload,
                year=data_year,
                facts=topic_facts,
                all_facts=facts,
            )
            topics[index] = topic_payload
        run["topics"] = topics
        year_runs[str(year_text)] = run

    active_run = _as_dict(year_runs.get(active_year)) if active_year else {}
    visual_scene["yearRuns"] = year_runs
    visual_scene["baselineContext"] = _as_dict(active_run.get("baselineContext"))
    if active_run:
        visual_scene["topics"] = active_run.get("topics", [])
        visual_scene["edges"] = active_run.get("edges", [])


def _visual_scene_years(visual_scene: Mapping[str, Any]) -> list[int]:
    years: set[int] = set()
    active_year = str(visual_scene.get("activeYear") or "").strip()
    if active_year.isdigit():
        years.add(int(active_year))
    for year in _as_dict(visual_scene.get("yearRuns")).keys():
        year_text = str(year or "").strip()
        if year_text.isdigit():
            years.add(int(year_text))
    for run in _as_dict(visual_scene.get("yearRuns")).values():
        data_year = int(_as_number(_as_dict(run).get("dataYear")))
        if data_year > 0:
            years.add(data_year)
    return sorted(years)


def _visual_run_data_year(run: Mapping[str, Any], *, active_year_int: int | None, run_year: int) -> int:
    explicit = _as_number(run.get("dataYear"))
    if explicit > 0:
        return int(explicit)
    role = str(run.get("role") or "").strip()
    if role == "current" and active_year_int and run_year == active_year_int:
        return max(active_year_int - 1, _BACKTEST_EARLIEST_VALIDATION_YEAR)
    return run_year


def _build_year_baseline_context(*, year: int, facts: Sequence[Any], shown_topics: int) -> dict[str, Any]:
    topic_ids = {str(getattr(fact, "topic_id", "") or "").strip().lower() for fact in facts if getattr(fact, "topic_id", "")}
    guide_ids = {str(getattr(fact, "guide_id", "") or getattr(fact, "guide_code", "") or "").strip() for fact in facts}
    program_ids = {str(getattr(fact, "program_id", "") or getattr(fact, "program_name", "") or "").strip() for fact in facts}
    institution_ids = {
        str(getattr(getattr(fact, "institution", None), "institution_name", "") or getattr(getattr(fact, "institution", None), "institution_id", "") or "").strip()
        for fact in facts
    }
    principal_ids = {
        str(getattr(getattr(fact, "principal", None), "person_name", "") or getattr(getattr(fact, "principal", None), "person_id", "") or "").strip()
        for fact in facts
    }
    tech_fields = {str(getattr(fact, "tech_field_name", "") or "").strip() for fact in facts}
    industries = {str(getattr(fact, "industry_name", "") or "").strip() for fact in facts}
    return {
        "year": year,
        "projectCount": len(facts),
        "topicCount": len({item for item in topic_ids if item}),
        "guideCount": len({item for item in guide_ids if item}),
        "programCount": len({item for item in program_ids if item}),
        "institutionCount": len({item for item in institution_ids if item}),
        "principalCount": len({item for item in principal_ids if item}),
        "techFieldCount": len({item for item in tech_fields if item}),
        "industryCount": len({item for item in industries if item}),
        "fundedCount": sum(1 for fact in facts if bool(getattr(fact, "funded_flag", False))),
        "fundingAmount": round(sum(_as_number(getattr(fact, "final_funding_amount", 0.0)) for fact in facts), 3),
        "shownTopicCount": shown_topics,
    }


def _build_topic_detail_profile(
    *,
    topic: Mapping[str, Any],
    year: int,
    facts: Sequence[Any],
    all_facts: Sequence[Any],
) -> dict[str, Any]:
    topic_ids = {item.lower() for item in _string_list(topic.get("topicIds"))}
    history_facts = [
        fact
        for fact in all_facts
        if str(getattr(fact, "topic_id", "") or "").strip().lower() in topic_ids
    ]
    return {
        "year": year,
        "projectCount": len(facts),
        "fundedCount": sum(1 for fact in facts if bool(getattr(fact, "funded_flag", False))),
        "fundingAmount": round(sum(_as_number(getattr(fact, "final_funding_amount", 0.0)) for fact in facts), 3),
        "requestedFundingAmount": round(sum(_as_number(getattr(getattr(fact, "funding", None), "requested_special_funding", 0.0)) for fact in facts), 3),
        "history": _topic_year_history(history_facts),
        "guides": _top_fact_buckets(facts, _fact_guide_label, limit=8),
        "programs": _top_fact_buckets(facts, lambda fact: getattr(fact, "program_name", None), limit=6),
        "industries": _top_fact_buckets(facts, lambda fact: getattr(fact, "industry_name", None), limit=8),
        "institutions": _top_fact_buckets(
            facts,
            lambda fact: getattr(getattr(fact, "institution", None), "institution_name", None),
            limit=8,
        ),
        "keywords": _top_keywords(facts, limit=10),
        "sampleProjects": _sample_project_cards(facts, limit=6),
    }


def _topic_year_history(facts: Sequence[Any]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for fact in facts:
        year = int(getattr(fact, "application_year", 0) or 0)
        if year <= 0:
            continue
        state = grouped.setdefault(year, {"year": year, "projects": 0, "funded": 0, "funding": 0.0})
        state["projects"] += 1
        state["funded"] += 1 if bool(getattr(fact, "funded_flag", False)) else 0
        state["funding"] += _as_number(getattr(fact, "final_funding_amount", 0.0))
    return [
        {
            "year": year,
            "projects": item["projects"],
            "funded": item["funded"],
            "funding": round(item["funding"], 3),
        }
        for year, item in sorted(grouped.items())
    ]


def _top_fact_buckets(facts: Sequence[Any], label_fn, *, limit: int) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for fact in facts:
        label = " ".join(str(label_fn(fact) or "").strip().split())
        if not label:
            continue
        state = buckets.setdefault(label, {"label": label, "count": 0, "funded": 0, "funding": 0.0})
        state["count"] += 1
        state["funded"] += 1 if bool(getattr(fact, "funded_flag", False)) else 0
        state["funding"] += _as_number(getattr(fact, "final_funding_amount", 0.0))
    rows = list(buckets.values())
    rows.sort(key=lambda item: (-int(item["count"]), -_as_number(item["funding"]), item["label"]))
    return [
        {
            "label": item["label"],
            "count": item["count"],
            "funded": item["funded"],
            "funding": round(item["funding"], 3),
        }
        for item in rows[:limit]
    ]


def _fact_guide_label(fact: Any) -> str:
    code = str(getattr(fact, "guide_code", "") or "").strip()
    name = " ".join(str(getattr(fact, "guide_name", "") or "").strip().split())
    if code and name and code not in name:
        return f"{code}-{name}"
    return name or code


def _top_keywords(facts: Sequence[Any], *, limit: int) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for fact in facts:
        for keyword in getattr(fact, "keywords", ()) or ():
            text = " ".join(str(keyword or "").strip().split())
            if text:
                counter[text] += 1
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def _sample_project_cards(facts: Sequence[Any], *, limit: int) -> list[dict[str, Any]]:
    rows = sorted(
        facts,
        key=lambda fact: (
            not bool(getattr(fact, "funded_flag", False)),
            -_as_number(getattr(fact, "final_funding_amount", 0.0)),
            str(getattr(fact, "project_name", "") or ""),
        ),
    )
    output = []
    for fact in rows[:limit]:
        output.append(
            {
                "projectName": getattr(fact, "project_name", "") or "未命名项目",
                "institution": getattr(getattr(fact, "institution", None), "institution_name", None),
                "guide": _fact_guide_label(fact),
                "program": getattr(fact, "program_name", None),
                "keywords": list(getattr(fact, "keywords", ()) or ())[:5],
                "funded": bool(getattr(fact, "funded_flag", False)),
                "funding": round(_as_number(getattr(fact, "final_funding_amount", 0.0)), 3),
            }
        )
    return output


def _build_topic_year_stats(facts: Sequence[Any], topic_ids: Sequence[str]) -> dict[str, dict[int, dict[str, Any]]]:
    wanted = {str(item or "").strip().lower() for item in topic_ids if str(item or "").strip()}
    stats: dict[str, dict[int, dict[str, Any]]] = {}
    for fact in facts:
        topic_id = str(getattr(fact, "topic_id", "") or "").strip().lower()
        year = int(getattr(fact, "application_year", 0) or 0)
        if not topic_id or topic_id not in wanted or year <= 0:
            continue
        state = stats.setdefault(topic_id, {}).setdefault(
            year,
            {
                "topic_id": topic_id,
                "topic_label": str(getattr(fact, "topic_name", "") or topic_id),
                "application": 0.0,
                "funded": 0.0,
                "funding": 0.0,
            },
        )
        state["application"] = _as_number(state.get("application")) + 1.0
        state["funded"] = _as_number(state.get("funded")) + (1.0 if bool(getattr(fact, "funded_flag", False)) else 0.0)
        state["funding"] = _as_number(state.get("funding")) + _as_number(getattr(fact, "final_funding_amount", 0.0))
    return stats


def _build_backtest_nodes(
    *,
    year: int,
    active_topics: Sequence[Mapping[str, Any]],
    stats_by_topic_year: Mapping[str, Mapping[int, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw_topic in active_topics:
        topic = _as_dict(raw_topic)
        topic_ids = _string_list(topic.get("topicIds"))
        training_by_year = _merge_topic_training_years(
            stats_by_topic_year=stats_by_topic_year,
            topic_ids=topic_ids,
            train_end_year=year - 1,
        )
        actual = _merge_topic_actual_year(
            stats_by_topic_year=stats_by_topic_year,
            topic_ids=topic_ids,
            validation_year=year,
        )
        if not training_by_year or not actual:
            continue

        predicted = _predict_validation_year(training_by_year)
        error = _backtest_error(predicted, actual)

        node = dict(topic)
        node["id"] = f"{topic.get('id')}|backtest:{year}"
        node["years"] = [str(year)]
        node["role"] = "backtest"
        node["baseline"] = {
            "application": actual["application"],
            "funded": actual["funded"],
            "funding": actual["funding"],
        }
        node["metrics"] = {
            "deltaApplication": error["application"],
            "deltaFunded": error["funded"],
            "deltaFunding": error["funding"],
            "deltaCentrality": 0.0,
        }
        node["backtest"] = {
            "trainWindow": f"{_BACKTEST_TRAINING_START_YEAR}-{year - 1}",
            "validationYear": year,
            "predicted": predicted,
            "actual": actual,
            "error": error,
        }
        node["children"] = [
            {
                "topicId": topic_id,
                "displayLabel": actual.get("topic_label") or topic.get("label"),
                "year": str(year),
                "baselineApplication": actual.get("application"),
                "baselineFunded": actual.get("funded"),
                "baselineFunding": actual.get("funding"),
                "metrics": [
                    {
                        "stageLabel": "回测",
                        "metric": "backtest_prediction",
                        "metricLabel": "预测与真实偏差",
                        "delta": error["application"],
                        "deltaSentence": _backtest_sentence(predicted, actual, error),
                    }
                ],
                "impactOrigins": ["backtest"],
            }
            for topic_id in topic_ids[:8]
        ]
        node["maxAbs"] = max(
            abs(_as_number(predicted.get("application"))),
            abs(_as_number(predicted.get("funded"))) * 4.0,
            abs(_as_number(predicted.get("funding"))) / 20.0,
        )
        node["primaryMetric"] = {
            "key": "predictedApplication",
            "label": "申报项目数",
            "value": predicted["application"],
            "unit": "项",
            "format": "int",
        }
        output.append(node)
    output.sort(key=lambda item: -_as_number(_as_dict(item.get("backtest")).get("predicted", {}).get("application")))
    return output


def _merge_topic_training_years(
    *,
    stats_by_topic_year: Mapping[str, Mapping[int, Mapping[str, Any]]],
    topic_ids: Sequence[str],
    train_end_year: int,
) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for raw_topic_id in topic_ids:
        topic_id = str(raw_topic_id or "").strip().lower()
        for year, raw_state in _as_dict(stats_by_topic_year.get(topic_id)).items():
            year_int = int(year)
            if year_int > train_end_year:
                continue
            state = _as_dict(raw_state)
            current = merged.setdefault(
                year_int,
                {"application": 0.0, "funded": 0.0, "funding": 0.0},
            )
            current["application"] += _as_number(state.get("application"))
            current["funded"] += _as_number(state.get("funded"))
            current["funding"] += _as_number(state.get("funding"))
    return dict(sorted(merged.items()))


def _merge_topic_actual_year(
    *,
    stats_by_topic_year: Mapping[str, Mapping[int, Mapping[str, Any]]],
    topic_ids: Sequence[str],
    validation_year: int,
) -> dict[str, Any]:
    actual = {"application": 0.0, "funded": 0.0, "funding": 0.0, "topic_label": ""}
    found = False
    for raw_topic_id in topic_ids:
        topic_id = str(raw_topic_id or "").strip().lower()
        state = _as_dict(_as_dict(stats_by_topic_year.get(topic_id)).get(str(validation_year)))
        if not state:
            continue
        found = True
        actual["application"] += _as_number(state.get("application"))
        actual["funded"] += _as_number(state.get("funded"))
        actual["funding"] += _as_number(state.get("funding"))
        if not actual["topic_label"]:
            actual["topic_label"] = str(state.get("topic_label") or "")
    if not found:
        return {}
    actual["application"] = float(int(round(actual["application"])))
    actual["funded"] = float(int(round(actual["funded"])))
    actual["funding"] = round(_as_number(actual["funding"]), 3)
    return actual


def _predict_validation_year(training_by_year: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    recent_years = sorted(training_by_year)[-4:]
    recent_states = [_as_dict(training_by_year[year]) for year in recent_years]
    application = _forecast_series([_as_number(item.get("application")) for item in recent_states], integer=True)
    funded_rate = _weighted_ratio(
        numerators=[_as_number(item.get("funded")) for item in recent_states],
        denominators=[_as_number(item.get("application")) for item in recent_states],
    )
    funded = float(int(round(application * funded_rate)))
    funding_per_project = _weighted_ratio(
        numerators=[_as_number(item.get("funding")) for item in recent_states],
        denominators=[_as_number(item.get("funded")) for item in recent_states],
    )
    if funded > 0 and funding_per_project > 0:
        funding = round(funded * funding_per_project, 3)
    else:
        funding = _forecast_series([_as_number(item.get("funding")) for item in recent_states], integer=False)
    return {
        "application": application,
        "funded": funded,
        "funding": funding,
    }


def _forecast_series(values: Sequence[float], *, integer: bool) -> float:
    cleaned = [_as_number(value) for value in values]
    if not cleaned:
        return 0.0
    if len(cleaned) == 1:
        value = cleaned[-1]
    else:
        deltas = [cleaned[index] - cleaned[index - 1] for index in range(1, len(cleaned))]
        weights = list(range(1, len(deltas) + 1))
        avg_delta = sum(delta * weight for delta, weight in zip(deltas, weights)) / max(sum(weights), 1)
        value = cleaned[-1] + avg_delta
    value = max(value, 0.0)
    return float(int(round(value))) if integer else round(value, 3)


def _weighted_ratio(*, numerators: Sequence[float], denominators: Sequence[float]) -> float:
    weighted_num = 0.0
    weighted_den = 0.0
    for index, (num, den) in enumerate(zip(numerators, denominators), start=1):
        if _as_number(den) <= 0:
            continue
        weight = float(index)
        weighted_num += _as_number(num) * weight
        weighted_den += _as_number(den) * weight
    if weighted_den <= 0:
        return 0.0
    return max(weighted_num / weighted_den, 0.0)


def _backtest_error(predicted: Mapping[str, Any], actual: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "application": float(int(round(_as_number(predicted.get("application")) - _as_number(actual.get("application"))))),
        "funded": float(int(round(_as_number(predicted.get("funded")) - _as_number(actual.get("funded"))))),
        "funding": round(_as_number(predicted.get("funding")) - _as_number(actual.get("funding")), 3),
        "applicationPct": _relative_error(predicted.get("application"), actual.get("application")),
        "fundedPct": _relative_error(predicted.get("funded"), actual.get("funded")),
        "fundingPct": _relative_error(predicted.get("funding"), actual.get("funding")),
    }


def _relative_error(predicted: Any, actual: Any) -> float:
    actual_value = _as_number(actual)
    if actual_value <= 0:
        return 0.0
    return round((_as_number(predicted) - actual_value) / actual_value * 100.0, 3)


def _backtest_sentence(predicted: Mapping[str, Any], actual: Mapping[str, Any], error: Mapping[str, Any]) -> str:
    return (
        f"申报 {int(round(_as_number(predicted.get('application'))))}，"
        f"与真实值偏差 {int(round(_as_number(error.get('application')))):+d}"
    )


def _summarize_backtest_nodes(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary = {
        "predicted": {"application": 0.0, "funded": 0.0, "funding": 0.0},
        "actual": {"application": 0.0, "funded": 0.0, "funding": 0.0},
        "error": {"application": 0.0, "funded": 0.0, "funding": 0.0},
    }
    for raw_node in nodes:
        backtest = _as_dict(_as_dict(raw_node).get("backtest"))
        for section in ("predicted", "actual", "error"):
            payload = _as_dict(backtest.get(section))
            summary[section]["application"] += _as_number(payload.get("application"))
            summary[section]["funded"] += _as_number(payload.get("funded"))
            summary[section]["funding"] += _as_number(payload.get("funding"))
    for section in ("predicted", "actual", "error"):
        summary[section]["application"] = float(int(round(summary[section]["application"])))
        summary[section]["funded"] = float(int(round(summary[section]["funded"])))
        summary[section]["funding"] = round(summary[section]["funding"], 3)
    return summary


def _finalize_visual_nodes(nodes_by_key: Mapping[str, dict[str, Any]], order: Sequence[str]) -> list[dict[str, Any]]:
    nodes = []
    for key in order:
        node = nodes_by_key[key]
        node.pop("_children_by_topic", None)
        node["years"] = sorted(str(year) for year in node.get("years", []) if year)
        node["direct"] = bool(node.get("directCount"))
        node["maxAbs"] = max(
            abs(_as_number(node["metrics"].get("deltaFunding"))),
            abs(_as_number(node["metrics"].get("deltaApplication"))),
            abs(_as_number(node["metrics"].get("deltaFunded"))),
            abs(_as_number(node["metrics"].get("deltaCentrality"))),
        )
        node["primaryMetric"] = _visual_primary_metric(node)
        nodes.append(node)
    nodes.sort(key=lambda item: (not bool(item.get("direct")), -_as_number(item.get("maxAbs"))))
    return nodes


def _visual_active_year(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return str(datetime.now().year)
    start_year = text.split("-", 1)[0].strip() or text
    if start_year.isdigit():
        return str(int(start_year) + 1)
    return start_year


def _visual_baseline_year_for_run(*, year: str, active_year: str) -> int | None:
    if not str(year).isdigit():
        return None
    year_int = int(year)
    if str(active_year).isdigit() and year == active_year:
        return year_int - 1
    if _visual_year_role(year, active_year) == "backtest":
        return year_int - 1
    return year_int


def _visual_item_year(item: Mapping[str, Any]) -> str:
    year = str(item.get("topic_identity_year") or "").strip()
    if year:
        return year
    display_label = str(item.get("display_label") or "").strip()
    if len(display_label) >= 4 and display_label[:4].isdigit():
        return display_label[:4]
    return ""


def _visual_year_sort_key(value: str) -> tuple[int, str]:
    return (int(value), value) if str(value).isdigit() else (-1, str(value))


def _visual_year_order(year_runs: Mapping[str, Any], active_year: str) -> list[str]:
    years = [str(year) for year in year_runs if str(year)]
    current = [year for year in years if year == active_year]
    backtests = sorted(
        [year for year in years if _visual_year_role(year, active_year) == "backtest"],
        key=_visual_year_sort_key,
        reverse=True,
    )
    comparisons = sorted(
        [year for year in years if _visual_year_role(year, active_year) == "comparison"],
        key=_visual_year_sort_key,
        reverse=True,
    )
    futures = sorted(
        [year for year in years if _visual_year_role(year, active_year) == "future"],
        key=_visual_year_sort_key,
    )
    return current + backtests + comparisons + futures


def _visual_year_role(year: str, active_year: str) -> str:
    if year == active_year:
        return "current"
    if year.isdigit() and active_year.isdigit() and int(year) < int(active_year):
        return "backtest"
    if year.isdigit() and active_year.isdigit() and int(year) > int(active_year):
        return "future"
    return "comparison"


def _visual_year_label(year: str, active_year: str, *, data_year: int | None = None) -> str:
    role = _visual_year_role(year, active_year)
    window = f"{data_year} → {year}" if data_year and str(year).isdigit() and int(year) != data_year else year
    if role == "current":
        return f"{window} 当前推演"
    if role == "backtest":
        return f"{window} 回测"
    if role == "future":
        return f"{window} 未来延伸"
    return f"{window} 对照"


def _visual_year_validation(year: str, active_year: str) -> dict[str, Any]:
    role = _visual_year_role(year, active_year)
    if role == "backtest" and year.isdigit():
        train_start = _BACKTEST_TRAINING_START_YEAR
        train_end = int(year) - 1
        return {
            "title": "回测验证",
            "trainWindow": f"{train_start}-{train_end}",
            "validationYear": year,
            "summary": f"用截至 {train_end} 年的数据推演 {year} 年，并标注与真实值的偏差。",
        }
    if role == "future":
        return {
            "title": "未来延伸",
            "summary": f"{year} 年是未来延伸批次，不和当前推演混在一起看。",
        }
    return {
        "title": "当前推演",
        "summary": f"用 {int(year) - 1} 年现状推演 {year} 年结果。" if str(year).isdigit() else f"{year} 是当前默认推演批次。",
    }


def _visual_identity_key(item: Mapping[str, Any]) -> str:
    scope = str(item.get("topic_identity_scope") or "").strip()
    guide_code = str(item.get("topic_identity_guide_code") or "").strip()
    guide_label = str(item.get("topic_identity_guide_label") or item.get("topic_label") or "").strip()
    parts = [scope, guide_code, guide_label]
    if any(parts):
        return "identity|" + "|".join(parts)
    return str(item.get("topic_id") or item.get("display_label") or item.get("topic_label") or "unknown").strip()


def _visual_primary_metric(node: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _as_dict(node.get("metrics"))
    candidates = [
        ("deltaFunding", "新增经费", "万元", "currency"),
        ("deltaFunded", "新增立项", "项", "int"),
        ("deltaApplication", "新增申报", "项", "int"),
        ("deltaCentrality", "中心性变化", "", "decimal"),
    ]
    for key, label, unit, fmt in candidates:
        value = _as_number(metrics.get(key))
        if abs(value) > 1e-9:
            return {"key": key, "label": label, "value": value, "unit": unit, "format": fmt}
    return {"key": "deltaApplication", "label": "变化", "value": 0.0, "unit": "", "format": "int"}


def _build_visual_edges(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    direct_nodes = [item for item in nodes if item.get("direct")]
    spill_nodes = [item for item in nodes if not item.get("direct")]
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(source: Mapping[str, Any], target: Mapping[str, Any], kind: str, label: str) -> None:
        source_id = str(source.get("id") or "")
        target_id = str(target.get("id") or "")
        if not source_id or not target_id or source_id == target_id:
            return
        edge_id = f"{source_id}|{target_id}|{kind}"
        if edge_id in seen:
            return
        seen.add(edge_id)
        edges.append({"edgeId": edge_id, "sourceId": source_id, "targetId": target_id, "kind": kind, "label": label})

    if direct_nodes:
        hub = direct_nodes[0]
        for node in direct_nodes[1:]:
            add(hub, node, "direct", "同属本次直接调整")
    for index, node in enumerate(spill_nodes):
        anchor = _find_visual_anchor(node, direct_nodes, index)
        if anchor:
            add(anchor, node, "spill", "推演外溢关联")
    for index in range(len(direct_nodes) - 1):
        add(direct_nodes[index], direct_nodes[index + 1], "ghost", "同批调整背景联系")
    return edges


def _find_visual_anchor(node: Mapping[str, Any], direct_nodes: Sequence[Mapping[str, Any]], index: int) -> Mapping[str, Any] | None:
    if not direct_nodes:
        return None
    scope = str(node.get("scope") or "")
    guide_code = str(node.get("guideCode") or "")
    for candidate in direct_nodes:
        if scope and str(candidate.get("scope") or "") == scope:
            return candidate
    for candidate in direct_nodes:
        if guide_code and str(candidate.get("guideCode") or "") == guide_code:
            return candidate
    return direct_nodes[index % len(direct_nodes)]


def _leadership_topic_delta_index(graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    label_index: dict[str, dict[str, Any]] = {}
    for raw_item in graph.get("nodes", []) or []:
        item = _as_dict(raw_item)
        if item.get("node_type") != "topic":
            continue
        node_id = str(item.get("node_id") or "").strip()
        topic_id = node_id.split("topic:", 1)[1] if node_id.startswith("topic:") else node_id
        label = str(item.get("label") or item.get("short_label") or topic_id or "未标注主题").strip() or "未标注主题"
        funding = 0.0
        projects = 0.0
        for metric in _as_dict(item.get("stage_metrics")).values():
            metric_payload = _as_dict(metric)
            metric_key = str(metric_payload.get("metric_key") or "").strip()
            if metric_key == "delta_funding_amount":
                funding += _as_number(metric_payload.get("delta_value"))
            elif metric_key == "delta_funded_count":
                projects += _as_number(metric_payload.get("delta_value"))
        topic_payload = {
            "topic_id": topic_id,
            "label": label,
            "identity_scope": item.get("identity_scope"),
            "identity_broad_scope": item.get("identity_broad_scope"),
            "identity_guide_label": item.get("identity_guide_label"),
            "identity_guide_code": item.get("identity_guide_code"),
            "identity_year": item.get("identity_year"),
            "funding": funding,
            "projects": projects,
        }
        output[topic_id] = topic_payload
        label_index.setdefault(_normalize_text_key(label), topic_payload)
    output["__label_index__"] = label_index  # type: ignore[assignment]
    return output


def _leadership_collect_targets(
    action_resolution: Sequence[Mapping[str, Any]],
    topic_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for action in action_resolution:
        topic_ids = _string_list(
            _as_dict(action).get("resolved_topic_ids")
            or _as_dict(action).get("target_labels")
        )
        topic_labels = _string_list(
            _as_dict(action).get("resolved_topic_labels")
            or _as_dict(action).get("target_labels")
        )
        resolved = _leadership_resolve_topics(topic_ids, topic_labels, topic_metrics)
        aggregated = _leadership_aggregate_topics_by_identity(resolved)
        for item in aggregated:
            key = str(item.get("topic_id") or item.get("label") or "").strip()
            if not key:
                continue
            current = output.get(key)
            if current is None:
                current = dict(item)
                current["funding"] = _as_number(current.get("funding"))
                current["projects"] = _as_number(current.get("projects"))
                output[key] = current
                order.append(key)
                continue
            current["funding"] = _as_number(current.get("funding")) + _as_number(item.get("funding"))
            current["projects"] = _as_number(current.get("projects")) + _as_number(item.get("projects"))
    material = []
    for key in order:
        item = output[key]
        material.append(item)
    return material


def _leadership_resolve_topics(
    topic_ids: Sequence[str],
    topic_labels: Sequence[str],
    topic_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    label_index = _as_dict(topic_metrics.get("__label_index__"))
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered_keys = list(topic_ids) or list(topic_labels)
    for raw_value in ordered_keys:
        normalized = _normalize_text_key(raw_value)
        topic_payload = _as_dict(topic_metrics.get(raw_value)) or _as_dict(label_index.get(normalized))
        label = str(topic_payload.get("label") or raw_value or "未标注主题").strip() or "未标注主题"
        unique_key = str(topic_payload.get("topic_id") or normalized or label)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        output.append(
            {
                "topic_id": topic_payload.get("topic_id") or raw_value,
                "label": label,
                "identity_scope": topic_payload.get("identity_scope"),
                "identity_broad_scope": topic_payload.get("identity_broad_scope"),
                "identity_guide_label": topic_payload.get("identity_guide_label"),
                "identity_guide_code": topic_payload.get("identity_guide_code"),
                "identity_year": topic_payload.get("identity_year"),
                "funding": _as_number(topic_payload.get("funding")),
                "projects": _as_number(topic_payload.get("projects")),
            }
        )
    return output


def _leadership_aggregate_topics_by_identity(topics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw_item in topics:
        item = _as_dict(raw_item)
        if not item:
            continue
        scope = str(item.get("identity_scope") or "").strip()
        guide_label = str(item.get("identity_guide_label") or item.get("label") or "").strip()
        guide_code = str(item.get("identity_guide_code") or "").strip()
        key_parts = [scope, guide_code, guide_label]
        key = "identity|" + "|".join(key_parts) if any(key_parts) else str(item.get("topic_id") or "").strip()
        current = aggregated.get(key)
        if current is None:
            current = {
                "topic_id": key,
                "label": _leadership_identity_label(item),
                "funding": 0.0,
                "projects": 0.0,
                "identity_scope": item.get("identity_scope"),
                "identity_broad_scope": item.get("identity_broad_scope"),
                "identity_guide_label": item.get("identity_guide_label"),
                "identity_guide_code": item.get("identity_guide_code"),
                "children": [],
                "years": [],
                "topic_ids": [],
            }
            aggregated[key] = current
            order.append(key)
        current["funding"] = _as_number(current.get("funding")) + _as_number(item.get("funding"))
        current["projects"] = _as_number(current.get("projects")) + _as_number(item.get("projects"))
        child = {
            "topic_id": item.get("topic_id"),
            "label": item.get("label"),
            "year": item.get("identity_year"),
            "scope": item.get("identity_scope"),
            "broad_scope": item.get("identity_broad_scope"),
            "guide_label": item.get("identity_guide_label"),
            "guide_code": item.get("identity_guide_code"),
            "funding": item.get("funding"),
            "projects": item.get("projects"),
        }
        current["children"].append(child)
        if child.get("year") and child["year"] not in current["years"]:
            current["years"].append(child["year"])
        if child.get("topic_id") and child["topic_id"] not in current["topic_ids"]:
            current["topic_ids"].append(child["topic_id"])
    return [aggregated[key] for key in order]


def _leadership_identity_label(item: Mapping[str, Any]) -> str:
    scope = str(item.get("identity_scope") or "").strip()
    guide_label = str(item.get("identity_guide_label") or item.get("label") or "未标注方向").strip()
    guide_code = str(item.get("identity_guide_code") or "").strip()
    if guide_code and guide_code not in guide_label:
        guide_label = f"{guide_code}-{guide_label}"
    if scope and scope not in guide_label:
        return f"{scope} / {guide_label}"
    return guide_label or "未标注方向"


def _leadership_topic_label(item: Mapping[str, Any]) -> str:
    scope = str(item.get("topic_identity_scope") or "").strip()
    guide_label = str(item.get("topic_identity_guide_label") or item.get("topic_label") or item.get("display_label") or "").strip()
    guide_code = str(item.get("topic_identity_guide_code") or "").strip()
    if guide_code and guide_code not in guide_label:
        guide_label = f"{guide_code}-{guide_label}"
    if scope and scope not in guide_label:
        return f"{scope} / {guide_label}"
    return guide_label or str(item.get("display_label") or item.get("topic_label") or item.get("topic_id") or "未标注主题").strip() or "未标注主题"


def _build_graph_section(
    *,
    baseline: BaselineSnapshot | None,
    scenario_contract: Mapping[str, Any],
    compiled_section: Mapping[str, Any],
    stage_impacts: Sequence[Mapping[str, Any]],
    counterfactual: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_section = _build_baseline_section(baseline) or {}
    baseline_portfolio = _as_dict(baseline_section.get("portfolio"))
    action_resolution = {
        str(_as_dict(item).get("action_id") or ""): _as_dict(item)
        for item in compiled_section.get("action_resolution", []) or []
        if _as_dict(item)
    }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    clusters: list[dict[str, Any]] = []
    topic_nodes: dict[str, dict[str, Any]] = {}
    document_nodes: dict[str, dict[str, Any]] = {}
    action_nodes: dict[str, dict[str, Any]] = {}
    stage_visible_nodes: dict[str, list[str]] = {}
    stage_visible_edges: dict[str, list[str]] = {}
    stage_topics_map: dict[str, list[dict[str, Any]]] = {}

    def add_node(node: Mapping[str, Any]) -> None:
        node_id = str(node.get("node_id") or "").strip()
        if not node_id:
            return
        if any(str(item.get("node_id")) == node_id for item in nodes):
            return
        nodes.append(dict(node))

    def add_edge(edge: Mapping[str, Any]) -> None:
        edge_id = str(edge.get("edge_id") or "").strip()
        if not edge_id:
            return
        if any(str(item.get("edge_id")) == edge_id for item in edges):
            return
        edges.append(dict(edge))

    def stage_node_id(stage_id: str) -> str:
        return f"stage:{stage_id}"

    add_node(
        {
            "node_id": "portfolio",
            "node_type": "portfolio",
            "label": "科研投资组合",
            "short_label": "组合",
            "support_level": compiled_section.get("support_level", "unknown"),
            "status": "materialized",
            "expandable": False,
            "badges": ["领导主对象"],
            "metrics": [
                {
                    "metric_key": "baseline_application_count",
                    "label": "当前申报项目数",
                    "baseline_value": baseline_portfolio.get("application_count"),
                    "scenario_value": baseline_portfolio.get("application_count"),
                    "delta_value": 0,
                    "unit": "项",
                    "evidence_level": "observed-grounded",
                },
                {
                    "metric_key": "net_delta_funding_amount",
                    "label": "合同专项经费净变化",
                    "baseline_value": 0,
                    "scenario_value": counterfactual.get("net_delta_funding_amount"),
                    "delta_value": counterfactual.get("net_delta_funding_amount"),
                    "unit": "万元",
                    "evidence_level": "proxy-grounded",
                },
            ],
            "narrative": "领导最终看的不是单项目，而是整体科研投资组合在这次设定下如何变化。",
        }
    )
    add_node(
        {
            "node_id": f"scenario:{scenario_contract.get('scenario_id') or 'current'}",
            "node_type": "scenario",
            "label": scenario_contract.get("scenario_name") or "当前方案",
            "short_label": "方案",
            "support_level": compiled_section.get("support_level", "unknown"),
            "status": "materialized",
            "expandable": False,
            "badges": ["政策包"],
            "metrics": [],
            "narrative": _normalize_intent(scenario_contract.get("intent")).get("question") or "当前方案",
        }
    )
    add_edge(
        {
            "edge_id": "edge:portfolio:scenario",
            "edge_type": "compares",
            "source_id": "portfolio",
            "target_id": f"scenario:{scenario_contract.get('scenario_id') or 'current'}",
            "status": "materialized",
            "support_level": compiled_section.get("support_level", "unknown"),
            "polarity": "neutral",
            "weight": 1.0,
            "metric_deltas": [],
            "explanation": "在同一 baseline 上比较这次场景和不干预结果。",
        }
    )

    for item in scenario_contract.get("basis_documents", []) or []:
        payload = _as_dict(item)
        document_id = str(payload.get("document_id") or "").strip()
        if not document_id:
            continue
        node = {
            "node_id": f"document:{document_id}",
            "node_type": "document",
            "label": payload.get("title") or document_id,
            "short_label": _document_type_label(payload.get("document_type")) or "依据",
            "support_level": "observed-grounded",
            "status": "materialized",
            "expandable": False,
            "badges": ["正式依据"],
            "metrics": [],
            "narrative": payload.get("support_scope_label") or "用于约束本次场景的正式文本。",
            "refs": {
                "document_ids": [document_id],
            },
        }
        add_node(node)
        document_nodes[document_id] = node

    for stage in stage_impacts:
        payload = _as_dict(stage)
        stage_id = str(payload.get("stage_id") or "").strip()
        if not stage_id:
            continue
        stage_node = {
            "node_id": stage_node_id(stage_id),
            "node_type": "stage",
            "label": payload.get("stage_label") or stage_id,
            "short_label": "阶段",
            "stage_id": stage_id,
            "support_level": payload.get("support_level") or "unknown",
            "status": "materialized",
            "expandable": True,
            "badges": [payload.get("support_label") or ""],
            "metrics": [
                {
                    "metric_key": item.get("key"),
                    "label": item.get("label"),
                    "baseline_value": 0,
                    "scenario_value": item.get("value"),
                    "delta_value": item.get("value"),
                    "unit": item.get("format"),
                    "evidence_level": payload.get("support_level") or "unknown",
                }
                for item in payload.get("metric_cards", []) or []
                if _as_dict(item)
            ],
            "narrative": payload.get("narrative"),
        }
        add_node(stage_node)
        stage_visible_nodes[stage_id] = [stage_node["node_id"]]
        stage_visible_edges[stage_id] = []
        stage_topics_map[stage_id] = []
        clusters.append(
            {
                "cluster_id": f"cluster:stage:{stage_id}",
                "cluster_type": "stage",
                "label": payload.get("stage_label") or stage_id,
                "stage_id": stage_id,
                "order": payload.get("stage_order", 0),
                "collapsed_by_default": False,
                "member_node_ids": [stage_node["node_id"]],
                "member_count": 1,
                "has_more": False,
                "support_level": payload.get("support_level") or "unknown",
                "summary_metrics": list(payload.get("metric_cards") or []),
                "load_state": "seeded",
            }
        )

    stage_specs = [str(_as_dict(item).get("stage_id") or "") for item in stage_impacts if _as_dict(item)]
    for index in range(len(stage_specs) - 1):
        edge_id = f"edge:stage:{stage_specs[index]}:{stage_specs[index + 1]}"
        add_edge(
            {
                "edge_id": edge_id,
                "edge_type": "propagates",
                "source_id": stage_node_id(stage_specs[index]),
                "target_id": stage_node_id(stage_specs[index + 1]),
                "stage_from": stage_specs[index],
                "stage_to": stage_specs[index + 1],
                "status": "materialized",
                "support_level": "proxy-grounded",
                "polarity": "neutral",
                "weight": 1.0,
                "metric_deltas": [],
                "explanation": "治理流程按固定顺序传导。",
            }
        )

    for action in scenario_contract.get("actions", []) or []:
        payload = _as_dict(action)
        action_id = str(payload.get("action_id") or "").strip()
        if not action_id:
            continue
        compiled_action = action_resolution.get(action_id, {})
        stage_id = str(compiled_action.get("stage") or payload.get("stage") or "").strip()
        target_scope = _as_dict(payload.get("target_scope"))
        resolved_topic_ids = _string_list(compiled_action.get("resolved_topic_ids") or target_scope.get("topic_ids"))
        node = {
            "node_id": f"action:{action_id}",
            "node_type": "action",
            "label": payload.get("display_title") or payload.get("action_label") or action_id,
            "short_label": "动作",
            "stage_id": stage_id,
            "support_level": compiled_action.get("support_level") or payload.get("support_level") or compiled_section.get("support_level", "unknown"),
            "status": "materialized",
            "expandable": bool(resolved_topic_ids),
            "badges": [_action_type_label(str(payload.get("action_type") or ""))],
            "metrics": [],
            "narrative": payload.get("target_summary") or target_scope.get("summary") or "当前动作作用于全体主题。",
            "refs": {
                "action_ids": [action_id],
                "document_ids": _string_list(compiled_action.get("basis_document_ids") or payload.get("basis_document_ids")),
                "topic_ids": resolved_topic_ids,
            },
        }
        add_node(node)
        action_nodes[action_id] = node
        if stage_id and stage_id in stage_visible_nodes:
            stage_visible_nodes[stage_id].append(node["node_id"])
            stage_cluster = next((item for item in clusters if item["cluster_id"] == f"cluster:stage:{stage_id}"), None)
            if stage_cluster is not None:
                stage_cluster["member_node_ids"].append(node["node_id"])
                stage_cluster["member_count"] = len(stage_cluster["member_node_ids"])
        if stage_id:
            edge_id = f"edge:action:{action_id}:stage:{stage_id}"
            add_edge(
                {
                    "edge_id": edge_id,
                    "edge_type": "activates",
                    "source_id": f"action:{action_id}",
                    "target_id": stage_node_id(stage_id),
                    "stage_to": stage_id,
                    "status": "materialized",
                    "support_level": node["support_level"],
                    "polarity": "positive",
                    "weight": 1.0,
                    "metric_deltas": [],
                    "explanation": "该动作在这一治理阶段起作用。",
                    "document_refs": node["refs"]["document_ids"],
                }
            )
            stage_visible_edges.setdefault(stage_id, []).append(edge_id)

        for document_id in node["refs"]["document_ids"]:
            if document_id not in document_nodes:
                continue
            edge_id = f"edge:document:{document_id}:action:{action_id}"
            add_edge(
                {
                    "edge_id": edge_id,
                    "edge_type": "evidences",
                    "source_id": f"document:{document_id}",
                    "target_id": f"action:{action_id}",
                    "status": "materialized",
                    "support_level": "observed-grounded",
                    "polarity": "neutral",
                    "weight": 1.0,
                    "metric_deltas": [],
                    "explanation": "正式文本为这条动作提供执行依据。",
                }
            )
            if stage_id:
                stage_visible_nodes.setdefault(stage_id, []).append(f"document:{document_id}")
                stage_visible_edges.setdefault(stage_id, []).append(edge_id)

    for stage in stage_impacts:
        payload = _as_dict(stage)
        stage_id = str(payload.get("stage_id") or "").strip()
        if not stage_id:
            continue
        direct_cluster_id = f"cluster:{stage_id}:direct"
        spill_cluster_id = f"cluster:{stage_id}:spillover"
        direct_members: list[str] = []
        spill_members: list[str] = []
        for topic in payload.get("top_topics", []) or []:
            topic_payload = _as_dict(topic)
            topic_id = str(topic_payload.get("topic_id") or "").strip()
            if not topic_id:
                continue
            topic_node = topic_nodes.get(topic_id)
            if topic_node is None:
                topic_node = {
                    "node_id": f"topic:{topic_id}",
                    "node_type": "topic",
                    "label": topic_payload.get("display_label") or topic_payload.get("topic_label") or topic_id,
                    "short_label": "主题",
                    "identity_scope": topic_payload.get("topic_identity_scope"),
                    "identity_broad_scope": topic_payload.get("topic_identity_broad_scope"),
                    "identity_guide_label": topic_payload.get("topic_identity_guide_label"),
                    "identity_guide_code": topic_payload.get("topic_identity_guide_code"),
                    "identity_year": topic_payload.get("topic_identity_year"),
                    "support_level": payload.get("support_level") or "unknown",
                    "status": "materialized",
                    "expandable": False,
                    "badges": [],
                    "metrics": [],
                    "refs": {
                        "topic_ids": [topic_id],
                        "action_ids": [],
                    },
                    "narrative": topic_payload.get("display_context") or "当前主题的基线与变化规模。",
                    "stage_metrics": {},
                }
                add_node(topic_node)
                topic_nodes[topic_id] = topic_node
            else:
                topic_node["identity_scope"] = topic_node.get("identity_scope") or topic_payload.get("topic_identity_scope")
                topic_node["identity_broad_scope"] = topic_node.get("identity_broad_scope") or topic_payload.get("topic_identity_broad_scope")
                topic_node["identity_guide_label"] = topic_node.get("identity_guide_label") or topic_payload.get("topic_identity_guide_label")
                topic_node["identity_guide_code"] = topic_node.get("identity_guide_code") or topic_payload.get("topic_identity_guide_code")
                topic_node["identity_year"] = topic_node.get("identity_year") or topic_payload.get("topic_identity_year")
            stage_metric = {
                "stage_id": stage_id,
                "metric_key": topic_payload.get("metric"),
                "label": topic_payload.get("metric_label"),
                "baseline_value": topic_payload.get("baseline_funding_amount"),
                "scenario_value": topic_payload.get("delta"),
                "delta_value": topic_payload.get("delta"),
                "unit": topic_payload.get("metric"),
                "evidence_level": payload.get("support_level") or "unknown",
                "delta_sentence": topic_payload.get("delta_sentence"),
                "display_context": topic_payload.get("display_context"),
                "impact_origin": topic_payload.get("impact_origin"),
                "impact_origin_label": topic_payload.get("impact_origin_label"),
                "stage_story": topic_payload.get("stage_story"),
            }
            topic_node["stage_metrics"][stage_id] = stage_metric
            topic_node["support_level"] = topic_node.get("support_level") or payload.get("support_level") or "unknown"
            topic_node["impact_origin"] = topic_payload.get("impact_origin")
            if topic_payload.get("metric_label") and topic_payload.get("metric_label") not in topic_node["badges"]:
                topic_node["badges"].append(topic_payload.get("metric_label"))
            if topic_payload.get("impact_origin_label") and topic_payload.get("impact_origin_label") not in topic_node["badges"]:
                topic_node["badges"].append(topic_payload.get("impact_origin_label"))
            for action_label in topic_payload.get("applied_action_labels", []) or []:
                if action_label not in topic_node["refs"]["action_ids"]:
                    topic_node["refs"]["action_ids"].append(action_label)
            topic_payload["graph_node_id"] = topic_node["node_id"]
            stage_topics_map[stage_id].append(dict(topic_payload))
            stage_visible_nodes[stage_id].append(topic_node["node_id"])
            cluster_members = spill_members if topic_payload.get("impact_origin") == "spillover" else direct_members
            cluster_members.append(topic_node["node_id"])

            stage_edge_id = f"edge:stage:{stage_id}:topic:{topic_id}"
            add_edge(
                {
                    "edge_id": stage_edge_id,
                    "edge_type": "spills_over" if topic_payload.get("impact_origin") == "spillover" else "propagates",
                    "source_id": stage_node_id(stage_id),
                    "target_id": topic_node["node_id"],
                    "stage_from": stage_id,
                    "stage_to": stage_id,
                    "status": "materialized",
                    "support_level": payload.get("support_level") or "unknown",
                    "polarity": "negative" if _as_number(topic_payload.get("delta")) < 0 else "positive",
                    "weight": abs(_as_number(topic_payload.get("delta"))),
                    "metric_deltas": [
                        {
                            "metric_key": topic_payload.get("metric"),
                            "delta_value": topic_payload.get("delta"),
                        }
                    ],
                    "explanation": topic_payload.get("stage_story") or "",
                }
            )
            stage_visible_edges[stage_id].append(stage_edge_id)

        clusters.append(
            {
                "cluster_id": direct_cluster_id,
                "cluster_type": "topic_group",
                "label": "直接命中主题",
                "parent_cluster_id": f"cluster:stage:{stage_id}",
                "stage_id": stage_id,
                "order": 10,
                "collapsed_by_default": False,
                "member_node_ids": direct_members,
                "member_count": len(direct_members),
                "has_more": False,
                "support_level": payload.get("support_level") or "unknown",
                "summary_metrics": [],
                "load_state": "seeded",
            }
        )
        clusters.append(
            {
                "cluster_id": spill_cluster_id,
                "cluster_type": "topic_group",
                "label": "外溢传导主题",
                "parent_cluster_id": f"cluster:stage:{stage_id}",
                "stage_id": stage_id,
                "order": 20,
                "collapsed_by_default": True,
                "member_node_ids": spill_members,
                "member_count": len(spill_members),
                "has_more": False,
                "support_level": payload.get("support_level") or "unknown",
                "summary_metrics": [],
                "load_state": "seeded",
            }
        )

    for action_id, action_node in action_nodes.items():
        stage_id = str(action_node.get("stage_id") or "")
        target_topic_ids = _string_list(_as_dict(action_node.get("refs")).get("topic_ids"))
        if not target_topic_ids:
            continue
        for topic_id in target_topic_ids:
            topic_node_id = f"topic:{topic_id}"
            if topic_node_id not in {item.get("node_id") for item in nodes}:
                continue
            edge_id = f"edge:action:{action_id}:topic:{topic_id}"
            add_edge(
                {
                    "edge_id": edge_id,
                    "edge_type": "targets",
                    "source_id": f"action:{action_id}",
                    "target_id": topic_node_id,
                    "stage_to": stage_id,
                    "status": "materialized",
                    "support_level": action_node.get("support_level") or "unknown",
                    "polarity": "positive",
                    "weight": 1.0,
                    "metric_deltas": [],
                    "explanation": "该动作直接命中这一主题。",
                    "document_refs": _string_list(_as_dict(action_node.get("refs")).get("document_ids")),
                }
            )
            if stage_id:
                stage_visible_edges.setdefault(stage_id, []).append(edge_id)

    stage_topic_ids_by_stage = {
        stage_id: [str(_as_dict(item).get("topic_id") or "") for item in topics if _as_dict(item)]
        for stage_id, topics in stage_topics_map.items()
    }
    for index in range(len(stage_specs) - 1):
        current_stage = stage_specs[index]
        next_stage = stage_specs[index + 1]
        current_ids = set(stage_topic_ids_by_stage.get(current_stage, []))
        next_ids = set(stage_topic_ids_by_stage.get(next_stage, []))
        for topic_id in sorted(current_ids & next_ids):
            edge_id = f"edge:topic:{topic_id}:{current_stage}:{next_stage}"
            add_edge(
                {
                    "edge_id": edge_id,
                    "edge_type": "propagates",
                    "source_id": f"topic:{topic_id}",
                    "target_id": f"topic:{topic_id}",
                    "stage_from": current_stage,
                    "stage_to": next_stage,
                    "status": "materialized",
                    "support_level": "proxy-grounded",
                    "polarity": "neutral",
                    "weight": 1.0,
                    "metric_deltas": [],
                    "explanation": "同一主题跨阶段继续传导。",
                }
            )
            stage_visible_edges.setdefault(next_stage, []).append(edge_id)

    bookmarks = []
    for stage in stage_impacts:
        payload = _as_dict(stage)
        stage_id = str(payload.get("stage_id") or "").strip()
        if not stage_id:
            continue
        visible_nodes = _dedupe_strings(stage_visible_nodes.get(stage_id, []))
        visible_edges = _dedupe_strings(stage_visible_edges.get(stage_id, []))
        bookmarks.append(
            {
                "stage_id": stage_id,
                "stage_label": payload.get("stage_label"),
                "stage_order": payload.get("stage_order", 0),
                "narrative": payload.get("narrative"),
                "support_level": payload.get("support_level"),
                "support_label": payload.get("support_label"),
                "source_label": payload.get("source_label"),
                "metric_cards": list(payload.get("metric_cards") or []),
                "top_topic_total_count": payload.get("top_topic_total_count"),
                "drivers": list(payload.get("drivers") or []),
                "top_topics": stage_topics_map.get(stage_id, []),
                "visible_node_ids": _dedupe_strings(
                    [
                        "portfolio",
                        f"scenario:{scenario_contract.get('scenario_id') or 'current'}",
                        *visible_nodes,
                    ]
                ),
                "visible_edge_ids": _dedupe_strings(["edge:portfolio:scenario", *visible_edges]),
                "focus_path": _dedupe_strings(
                    [stage_node_id(stage_id)]
                    + [
                        f"action:{str(_as_dict(item).get('action_id') or '')}"
                        for item in scenario_contract.get("actions", []) or []
                        if str(_as_dict(item).get("stage") or "") == stage_id
                    ]
                ),
            }
        )

    return {
        "graph_id": f"graph:{scenario_contract.get('scenario_id') or 'current'}",
        "root_cluster_id": "portfolio",
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "playhead": {
            "mode": "stage",
            "status": "idle",
            "current_stage_id": bookmarks[0]["stage_id"] if bookmarks else None,
            "current_event_seq": 0,
            "materialized_through_seq": 0,
            "progress": 0.0,
            "bookmarks": bookmarks,
            "can_seek": True,
        },
        "indexes": {
            "stage_order": [item.get("stage_id") for item in bookmarks],
            "node_ids": [item.get("node_id") for item in nodes],
            "edge_ids": [item.get("edge_id") for item in edges],
        },
        "load_hints": {
            "default_visible_node_limit": 12,
            "default_cluster_expand_depth": 1,
        },
    }


def _build_graph_events(
    *,
    graph: Mapping[str, Any],
    scenario_contract: Mapping[str, Any],
    stage_impacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seq = 1

    def push(
        event_type: str,
        *,
        entity_type: str,
        entity_id: str,
        op: str = "lifecycle",
        stage_id: str | None = None,
        cluster_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        support_level: str = "unknown",
        is_terminal: bool = False,
    ) -> None:
        nonlocal seq
        events.append(
            {
                "event_id": f"event:{seq}",
                "seq": seq,
                "ts": seq,
                "run_id": None,
                "baseline_id": scenario_contract.get("baseline_id"),
                "scenario_id": scenario_contract.get("scenario_id"),
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "op": op,
                "stage_id": stage_id,
                "cluster_id": cluster_id,
                "causal_parent_ids": [],
                "support_level": support_level,
                "payload": dict(payload or {}),
                "patch": {},
                "disclosure_codes": [],
                "is_terminal": is_terminal,
            }
        )
        seq += 1

    push(
        "run.started",
        entity_type="graph",
        entity_id=str(graph.get("graph_id") or "graph"),
        support_level="observed-grounded",
    )
    push(
        "compile.completed",
        entity_type="scenario",
        entity_id=str(scenario_contract.get("scenario_id") or "scenario"),
        support_level="proxy-grounded",
    )
    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()
    for stage in graph.get("playhead", {}).get("bookmarks", []) or []:
        stage_payload = _as_dict(stage)
        stage_id = str(stage_payload.get("stage_id") or "").strip()
        if not stage_id:
            continue
        push(
            "stage.started",
            entity_type="stage",
            entity_id=stage_id,
            stage_id=stage_id,
            support_level=str(stage_payload.get("support_level") or "unknown"),
        )
        for node_id in stage_payload.get("visible_node_ids", []) or []:
            node_key = str(node_id).strip()
            if not node_key or node_key in seen_nodes:
                continue
            seen_nodes.add(node_key)
            push(
                "node.upsert",
                entity_type="node",
                entity_id=node_key,
                op="upsert",
                stage_id=stage_id,
                support_level=str(stage_payload.get("support_level") or "unknown"),
            )
        for edge_id in stage_payload.get("visible_edge_ids", []) or []:
            edge_key = str(edge_id).strip()
            if not edge_key or edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            push(
                "edge.upsert",
                entity_type="edge",
                entity_id=edge_key,
                op="upsert",
                stage_id=stage_id,
                support_level=str(stage_payload.get("support_level") or "unknown"),
            )
        push(
            "playhead.moved",
            entity_type="playhead",
            entity_id=str(graph.get("graph_id") or "graph"),
            stage_id=stage_id,
            support_level=str(stage_payload.get("support_level") or "unknown"),
            payload={"current_stage_id": stage_id},
        )
        push(
            "stage.completed",
            entity_type="stage",
            entity_id=stage_id,
            stage_id=stage_id,
            support_level=str(stage_payload.get("support_level") or "unknown"),
        )
    push(
        "run.completed",
        entity_type="graph",
        entity_id=str(graph.get("graph_id") or "graph"),
        support_level="proxy-grounded",
        is_terminal=True,
    )
    return events


def _normalize_native_stage_results(stage_results: Sequence[Any]) -> list[dict[str, Any]]:
    normalized = []
    for item in stage_results:
        payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        normalized.append(
            {
                "stage_id": payload.get("stage_id"),
                "stage_label": payload.get("stage_label"),
                "stage_order": payload.get("stage_order", len(normalized)),
                "narrative": payload.get("narrative", ""),
                "support_level": "proxy-grounded",
                "support_label": _support_label("proxy-grounded"),
                "metric_cards": [
                    {
                        "key": key,
                        "label": _metric_label(key),
                        "value": value,
                        "format": "decimal",
                    }
                    for key, value in _as_dict(payload.get("metrics")).items()
                ],
                "top_topics": [_normalize_stage_topic(topic) for topic in payload.get("topics", [])[:10]],
                "top_topic_total_count": len(payload.get("topics", []) or []),
                "drivers": [],
                "source": "native_stage_results",
                "source_label": "阶段直接结果",
            }
        )
    return normalized


def _synthesize_governance_stage(result: SimulationResult, spec: dict[str, str]) -> dict[str, Any]:
    impacts = list(result.impacts)
    stage_id = spec["stage_id"]
    stage_total_count = 0
    if stage_id == "application_response":
        metric_cards = [
            _metric_card("application_count", "申报项目数净变化", sum(item.delta_application_count for item in impacts), "int"),
            _metric_card("coverage", "发生申报变化的主题", sum(1 for item in impacts if item.delta_application_count != 0), "int"),
        ]
        stage_total_count = sum(1 for item in impacts if abs(item.delta_application_count) > 0.0)
        top_topics = _rank_stage_topics(impacts, key_fn=lambda item: abs(item.delta_application_count), metric="delta_application_count")
    elif stage_id == "review_selection":
        metric_cards = [
            _metric_card("funded_count", "立项数净变化", sum(item.delta_funded_count for item in impacts), "int"),
            _metric_card("score_proxy", "评审强度代理均值变化", _avg(item.delta_score_proxy or 0.0 for item in impacts), "decimal"),
        ]
        stage_total_count = sum(
            1 for item in impacts if abs(item.delta_funded_count) + abs(item.delta_score_proxy or 0.0) > 0.0
        )
        top_topics = _rank_stage_topics(
            impacts,
            key_fn=lambda item: abs(item.delta_funded_count) + abs(item.delta_score_proxy or 0.0),
            metric="delta_funded_count",
        )
    elif stage_id == "award_contract":
        metric_cards = [
            _metric_card("funding_amount", "合同专项经费净变化", sum(item.delta_funding_amount for item in impacts), "currency"),
            _metric_card("avg_award_shift", "受约束冲击数", result.metadata.get("budgetConstrainedShockCount", 0), "int"),
        ]
        stage_total_count = sum(
            1 for item in impacts if abs(item.delta_funding_amount) + 10.0 * abs(item.delta_funded_count) > 0.0
        )
        top_topics = _rank_stage_topics(
            impacts,
            key_fn=lambda item: abs(item.delta_funding_amount) + 10.0 * abs(item.delta_funded_count),
            metric="delta_funding_amount",
        )
    else:
        metric_cards = [
            _metric_card("collaboration_density", "协作密度均值变化", _avg(item.delta_collaboration_density for item in impacts), "decimal"),
            _metric_card("proxy_risk", "风险代理均值变化", _avg(item.delta_proxy_risk for item in impacts), "decimal"),
        ]
        stage_total_count = sum(
            1
            for item in impacts
            if abs(item.delta_collaboration_density) + abs(item.delta_topic_centrality) + abs(item.delta_migration_strength) + abs(item.delta_proxy_risk) > 0.0
        )
        top_topics = _rank_stage_topics(
            impacts,
            key_fn=lambda item: abs(item.delta_collaboration_density) + abs(item.delta_topic_centrality) + abs(item.delta_migration_strength) + abs(item.delta_proxy_risk),
            metric="delta_topic_centrality",
        )

    return {
        "stage_id": stage_id,
        "stage_label": spec["stage_label"],
        "stage_order": next(index for index, item in enumerate(_GOVERNANCE_STAGE_SPECS) if item["stage_id"] == stage_id),
        "narrative": spec["narrative"],
        "support_level": spec["support_level"],
        "support_label": _support_label(spec["support_level"]),
        "metric_cards": metric_cards,
        "top_topics": top_topics,
        "top_topic_total_count": stage_total_count,
        "drivers": _stage_drivers(stage_id, impacts),
        "source": "synthesized_from_impacts",
        "source_label": "阶段推演视图",
    }


def _rank_stage_topics(
    impacts: Sequence[SimulationTopicImpact],
    *,
    key_fn,
    metric: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    ranked = sorted(impacts, key=key_fn, reverse=True)[:limit]
    return [
        {
            "topic_id": item.topic_id,
            "topic_label": item.topic_label or item.topic_id,
            "metric": metric,
            "metric_label": _metric_label(metric),
            "delta": getattr(item, metric),
            "baseline_application_count": item.baseline_application_count,
            "baseline_funded_count": item.baseline_funded_count,
            "baseline_funding_amount": item.baseline_funding_amount,
            "impact_origin": item.impact_origin,
            "applied_actions": list(item.applied_shocks),
            "support_level": "proxy-grounded",
        }
        for item in ranked
        if key_fn(item) > 0.0
    ]


def _stage_drivers(stage_id: str, impacts: Sequence[SimulationTopicImpact]) -> list[str]:
    counter: Counter[str] = Counter()
    for item in impacts:
        shocks = item.applied_shocks
        if stage_id == "application_response":
            shocks = item.direct_shocks or item.applied_shocks
        elif stage_id == "structural_spillover":
            shocks = item.spillover_shocks or item.applied_shocks
        for shock in shocks:
            counter[str(shock)] += 1
    return [name for name, _count in counter.most_common(4)]


def _humanize_stage_impacts(
    stage_impacts: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]],
    *,
    topic_identity_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    action_labels = _build_action_display_lookup(actions)
    topic_identity_profiles = topic_identity_profiles or {}
    output: list[dict[str, Any]] = []
    for stage in stage_impacts:
        stage_payload = dict(stage)
        stage_payload["drivers"] = _dedupe_strings(
            action_labels.get(str(driver), str(driver))
            for driver in stage_payload.get("drivers", [])
        )
        stage_payload["source_label"] = stage_payload.get("source_label") or _stage_source_label(stage_payload.get("source"))
        stage_topics = [
            _humanize_stage_topic(
                topic,
                action_labels,
                topic_identity_profiles=topic_identity_profiles,
            )
            for topic in stage_payload.get("top_topics", [])
            if _as_dict(topic)
        ]
        stage_payload["top_topics"] = _disambiguate_stage_topics(stage_topics)
        output.append(stage_payload)
    return output


def _humanize_stage_topic(
    topic: Mapping[str, Any],
    action_labels: Mapping[str, str],
    *,
    topic_identity_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = dict(topic)
    metric = str(payload.get("metric") or "")
    profile = _as_dict((topic_identity_profiles or {}).get(str(payload.get("topic_id") or "")))
    payload["metric_label"] = payload.get("metric_label") or _metric_label(metric)
    payload["applied_action_labels"] = _dedupe_strings(
        action_labels.get(str(action), str(action))
        for action in payload.get("applied_actions", [])
    )
    if profile:
        payload["topic_identity_title"] = profile.get("identity_title")
        payload["topic_identity_context"] = profile.get("identity_context")
        payload["topic_identity_note"] = profile.get("identity_note")
        payload["topic_identity_scope"] = profile.get("identity_scope")
        payload["topic_identity_broad_scope"] = profile.get("identity_broad_scope")
        payload["topic_identity_guide_label"] = profile.get("identity_guide_label")
        payload["topic_identity_guide_code"] = profile.get("identity_guide_code")
        payload["topic_identity_year"] = profile.get("identity_year")
    payload["impact_origin_label"] = _impact_origin_label(payload.get("impact_origin"))
    payload["delta_sentence"] = _stage_delta_sentence(metric, payload.get("delta"))
    payload["stage_story"] = _stage_topic_story(payload)
    return payload


def _disambiguate_stage_topics(items: Sequence[Mapping[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    output = [dict(item) for item in items]
    counts: Counter[str] = Counter(
        _normalize_text_key(item.get("topic_label") or item.get("topic_id") or "")
        for item in output
    )
    for item in output:
        label = str(item.get("topic_label") or item.get("topic_id") or "未命名主题").strip()
        normalized = _normalize_text_key(label)
        item["display_label"] = str(item.get("topic_identity_title") or label)
        if counts.get(normalized, 0) > 1:
            item["display_context"] = _compose_topic_identity_context(
                item,
                include_applications=True,
            )
        else:
            item["display_context"] = _compose_topic_identity_context(
                item,
                include_applications=False,
            )
    return output[:limit]


def _build_action_display_lookup(actions: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for action in actions:
        payload = _as_dict(action)
        action_id = str(payload.get("action_id") or "").strip()
        label = str(payload.get("display_title") or payload.get("action_label") or action_id).strip()
        if action_id and label:
            output[action_id] = label
    return output


def _stage_source_label(value: Any) -> str:
    text = str(value or "").strip()
    if text == "synthesized_from_impacts":
        return "阶段推演视图"
    if text == "native_stage_results":
        return "阶段直接结果"
    return text


def _metric_label(metric: Any) -> str:
    text = str(metric or "").strip()
    return _TOPIC_METRIC_LABELS.get(text, text)


def _impact_origin_label(value: Any) -> str:
    text = str(value or "").strip()
    if text == "direct":
        return "直接影响"
    if text == "spillover":
        return "外溢影响"
    if text == "mixed":
        return "直接与外溢共同作用"
    return "综合影响"


def _stage_delta_sentence(metric: str, value: Any) -> str:
    delta = _as_number(value)
    abs_delta = abs(delta)
    if metric == "delta_application_count":
        return f"本次{'新增' if delta >= 0 else '减少'}申报 {_format_payload_number(abs_delta, 'int')} 项"
    if metric == "delta_funded_count":
        return f"本次{'新增' if delta >= 0 else '减少'}立项 {_format_payload_number(abs_delta, 'int')} 项"
    if metric == "delta_funding_amount":
        return f"本次{'新增' if delta >= 0 else '减少'}经费 {_format_payload_number(abs_delta, 'currency')}"
    if metric == "delta_collaboration_density":
        return f"本次协作密度{'上升' if delta >= 0 else '下降'} {_format_payload_number(abs_delta, 'decimal')}"
    if metric == "delta_topic_centrality":
        return f"本次中心性{'上升' if delta >= 0 else '下降'} {_format_payload_number(abs_delta, 'decimal')}"
    if metric == "delta_migration_strength":
        return f"本次迁移强度{'上升' if delta >= 0 else '下降'} {_format_payload_number(abs_delta, 'decimal')}"
    if metric == "delta_proxy_risk":
        return f"本次风险代理{'上升' if delta >= 0 else '下降'} {_format_payload_number(abs_delta, 'decimal')}"
    return f"本次变化幅度 {_format_payload_number(abs_delta, 'decimal')}"


def _stage_topic_context(item: Mapping[str, Any], *, include_applications: bool) -> str:
    parts: list[str] = []
    if include_applications:
        parts.append(f"当前申报 {_format_payload_number(item.get('baseline_application_count'), 'int')}")
    parts.append(f"当前立项 {_format_payload_number(item.get('baseline_funded_count'), 'int')}")
    parts.append(f"当前经费 {_format_payload_number(item.get('baseline_funding_amount'), 'currency')}")
    return "｜".join(parts)


def _compose_topic_identity_context(item: Mapping[str, Any], *, include_applications: bool) -> str:
    identity_context = str(item.get("topic_identity_context") or "").strip()
    stage_context = _stage_topic_context(item, include_applications=include_applications)
    if identity_context and stage_context:
        return f"{identity_context}｜{stage_context}"
    return identity_context or stage_context


def _stage_topic_story(item: Mapping[str, Any]) -> str:
    origin = _impact_origin_story(item.get("impact_origin"))
    baseline = _stage_baseline_story(item)
    parts = [part for part in (origin, baseline) if part]
    return "；".join(parts)


def _impact_origin_story(value: Any) -> str:
    text = str(value or "").strip()
    if text == "direct":
        return "这条变化来自本次设定的直接作用"
    if text == "spillover":
        return "这条变化来自相邻主题的外溢传导"
    if text == "mixed":
        return "这条变化同时受到直接作用和外溢传导"
    return "这条变化来自多种因素共同作用"


def _stage_baseline_story(item: Mapping[str, Any]) -> str:
    funded_count = _as_number(item.get("baseline_funded_count"))
    funding_amount = _as_number(item.get("baseline_funding_amount"))
    if funded_count <= 0 and funding_amount <= 0:
        return "当前主要停留在申报端，还没有形成立项和合同经费"
    if funded_count > 0 and funding_amount <= 0:
        return "当前已经形成立项，但合同经费尚未拉开"
    if funded_count > 0 and funding_amount > 0:
        return "当前已经形成申报、立项和合同投入"
    return "当前基线规模见上方数据"


def _load_topic_identity_profiles(stage_impacts: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {}
    candidate_topic_ids: list[str] = []
    for stage in stage_impacts:
        for item in stage.get("top_topics", []) or []:
            payload = _as_dict(item)
            topic_id = str(payload.get("topic_id") or "").strip()
            topic_label = str(payload.get("topic_label") or "").strip()
            if topic_id and _needs_topic_identity(topic_label):
                candidate_topic_ids.append(topic_id)

    deduped_ids = _dedupe_strings(candidate_topic_ids)
    if not deduped_ids:
        return {}

    try:
        guide_rows = _load_guide_identity_rows(deduped_ids)
    except Exception:
        return {}

    return {
        topic_id: _build_guide_identity_profile(guide_rows.get(topic_id, {}), guide_rows)
        for topic_id in deduped_ids
        if _as_dict(guide_rows.get(topic_id))
    }


def _needs_topic_identity(label: str) -> bool:
    normalized = _normalize_text_key(label)
    return any(
        marker in normalized
        for marker in (
            "面上项目",
            "青年科学基金项目",
            "青年科学基金项目（a类）",
        )
    )


def _load_guide_identity_rows(topic_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    cleaned_ids = [str(item).strip() for item in topic_ids if str(item).strip()]
    if not cleaned_ids:
        return {}
    placeholders = ",".join("?" for _ in cleaned_ids)
    rows = project_execute(
        f"SELECT id, parent_ids, name, code, nd FROM sys_guide WHERE id IN ({placeholders})",
        cleaned_ids,
    )
    guides: dict[str, dict[str, Any]] = {}
    parent_ids: set[str] = set()
    for row in rows:
        cols = [meta[0] for meta in row.cursor_description]
        payload = {col: row[idx] for idx, col in enumerate(cols)}
        guide_id = str(payload.get("id") or "").strip()
        if not guide_id:
            continue
        guides[guide_id] = payload
        parent_ids.update(
            part
            for part in str(payload.get("parent_ids") or "").split(",")
            if part and part != "0"
        )
    if parent_ids:
        parent_placeholders = ",".join("?" for _ in parent_ids)
        parent_rows = project_execute(
            f"SELECT id, name, code, nd FROM sys_guide WHERE id IN ({parent_placeholders})",
            list(parent_ids),
        )
        for row in parent_rows:
            cols = [meta[0] for meta in row.cursor_description]
            payload = {col: row[idx] for idx, col in enumerate(cols)}
            guide_id = str(payload.get("id") or "").strip()
            if guide_id:
                guides.setdefault(guide_id, payload)
    return guides


def _build_guide_identity_profile(
    row: Mapping[str, Any],
    guide_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    guide_label = " ".join(str(row.get("name") or "").strip().split())
    guide_code = " ".join(str(row.get("code") or "").strip().split())
    guide_year = str(row.get("nd") or "").strip()
    parent_names = [
        " ".join(str(_as_dict(guide_rows.get(parent_id)).get("name") or "").strip().split())
        for parent_id in str(row.get("parent_ids") or "").split(",")
        if parent_id and parent_id != "0"
    ]
    parent_names = [name for name in parent_names if name and name not in {"指南代码", guide_year}]
    scope_name = parent_names[-1] if parent_names else ""
    broad_name = parent_names[-2] if len(parent_names) >= 2 else ""
    title_parts = [part for part in (guide_year, scope_name, guide_label) if part]
    context_parts = [part for part in (broad_name, f"指南代码 {guide_code}" if guide_code else "") if part]
    return {
        "identity_title": "｜".join(title_parts) if title_parts else guide_label,
        "identity_context": "｜".join(context_parts),
        "identity_note": "｜".join(parent_names),
        "identity_scope": scope_name or broad_name,
        "identity_broad_scope": broad_name,
        "identity_guide_label": guide_label,
        "identity_guide_code": guide_code,
        "identity_year": guide_year,
    }


def _normalize_outcome_topics(result: SimulationResult | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    output = []
    for item in result.winners_and_losers:
        payload = item.model_dump(mode="json")
        payload["topic_label"] = payload.get("topic_label") or payload.get("topic_id")
        output.append(payload)
    return output


def _normalize_crowding_out(result: SimulationResult | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    return [item.model_dump(mode="json") for item in result.crowding_out]


def _normalize_risk_shift(result: SimulationResult | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    return [item.model_dump(mode="json") for item in result.risk_shift]


def _normalize_management_topics(items: Any) -> list[dict[str, Any]]:
    output = []
    for item in items or []:
        payload = _as_dict(item)
        if not payload:
            continue
        output.append(
            {
                "topic_id": payload.get("topic_id"),
                "topic_label": payload.get("topic_label") or payload.get("topic_id"),
                "management_action_label": payload.get("management_action_label"),
                "dominant_label": payload.get("dominant_label"),
                "impact_origin_label": payload.get("impact_origin_label"),
                "applied_shocks": list(payload.get("applied_shocks", [])),
                "direct_score": payload.get("direct_score", 0.0),
                "spillover_score": payload.get("spillover_score", 0.0),
                "structural_score": payload.get("structural_score", 0.0),
            }
        )
    return output


def _management_summary(
    comparison: SimulationComparison | None,
    explanation: SimulationExplanation | None = None,
) -> dict[str, Any]:
    if comparison is not None and isinstance(comparison.metadata, dict):
        summary = comparison.metadata.get("managementSummary")
        if isinstance(summary, dict):
            return summary
    if explanation is not None and isinstance(explanation.metadata, dict):
        summary = explanation.metadata.get("managementSummary")
        if isinstance(summary, dict):
            return summary
    return {}


def _normalize_action(item: Mapping[str, Any]) -> dict[str, Any]:
    target_scope = _as_dict(item.get("target_scope"))
    if not target_scope:
        target_scope = _as_dict(item.get("targetScope"))
    return {
        "action_id": str(item.get("action_id") or item.get("actionId") or item.get("shock_id") or item.get("shockId") or ""),
        "action_type": str(item.get("action_type") or item.get("actionType") or item.get("shock_type") or item.get("shockType") or ""),
        "stage": str(item.get("stage") or _infer_action_stage(str(item.get("action_type") or item.get("shock_type") or ""))),
        "support_level": str(item.get("support_level") or item.get("supportLevel") or "unknown"),
        "basis_document_ids": _string_list(item.get("basis_document_ids") or item.get("basisDocumentIds")),
        "target_scope": {
            "topic_ids": _string_list(target_scope.get("topic_ids") or target_scope.get("topicIds") or item.get("target_topics")),
            "topic_labels": _string_list(target_scope.get("topic_labels") or target_scope.get("topicLabels")),
        },
        "intensity": _as_number(item.get("intensity")),
        "coverage": _as_number(item.get("coverage")),
        "lag": int(_as_number(item.get("lag"))),
        "notes": _string_list(item.get("notes")),
        "parameters": _as_dict(item.get("parameters")),
    }


def _normalize_basis_document(item: Mapping[str, Any]) -> dict[str, Any]:
    support_scope = _string_list(item.get("support_scope") or item.get("supportScope"))
    return {
        "document_id": str(item.get("document_id") or item.get("documentId") or ""),
        "document_type": str(item.get("document_type") or item.get("documentType") or ""),
        "title": str(item.get("title") or ""),
        "publish_date": str(item.get("publish_date") or item.get("publishDate") or ""),
        "source_system": str(item.get("source_system") or item.get("sourceSystem") or ""),
        "support_scope": support_scope,
        "support_scope_label": "、".join(_basis_support_scope_label(value) for value in support_scope if value) or "未标注",
        "link_keys": _as_dict(item.get("link_keys") or item.get("linkKeys")),
        "notes": _string_list(item.get("notes")),
    }


def _basis_support_scope_label(value: Any) -> str:
    text = str(value or "").strip()
    if text == "policy_package":
        return "支撑整套设定"
    if text == "actions":
        return "支撑本次设定"
    if text.startswith("action:"):
        return "支撑本次正式挂接部分"
    return text


def _normalize_constraint(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "constraint_type": str(item.get("constraint_type") or item.get("constraintType") or ""),
        "operator": str(item.get("operator") or "hold"),
        "value": item.get("value"),
        "hard_limit": bool(item.get("hard_limit") or item.get("hardLimit") or False),
        "description": str(item.get("description") or ""),
    }


def _normalize_goal(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric": str(item.get("metric") or ""),
        "direction": str(item.get("direction") or ""),
        "target_value": item.get("target_value") or item.get("targetValue"),
        "weight": item.get("weight", 1.0),
        "description": str(item.get("description") or ""),
    }


def _normalize_goal_attainment(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric": item.get("metric"),
        "direction": item.get("direction"),
        "baseline_value": item.get("baseline_value", 0.0),
        "scenario_value": item.get("scenario_value", 0.0),
        "delta_value": item.get("delta_value", 0.0),
        "status": item.get("status", "hold"),
        "summary": item.get("summary", ""),
    }


def _normalize_validation(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    return {
        "observed_metrics": _string_list(payload.get("observed_metrics") or payload.get("observedMetrics")),
        "proxy_metrics": _string_list(payload.get("proxy_metrics") or payload.get("proxyMetrics")),
        "structural_assumptions": _string_list(payload.get("structural_assumptions") or payload.get("structuralAssumptions")),
        "unsupported_claims": _string_list(payload.get("unsupported_claims") or payload.get("unsupportedClaims")),
    }


def _normalize_intent(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    return {
        "question": str(payload.get("question") or ""),
        "decision_context": str(payload.get("decision_context") or payload.get("decisionContext") or ""),
        "policy_problem": str(payload.get("policy_problem") or payload.get("policyProblem") or ""),
        "desired_outcome": str(payload.get("desired_outcome") or payload.get("desiredOutcome") or ""),
        "narrative": str(payload.get("narrative") or ""),
    }


def _normalize_disclosure(value: Mapping[str, Any]) -> dict[str, Any]:
    severity = str(value.get("severity") or "info")
    return {
        "code": str(value.get("code") or ""),
        "severity": severity,
        "label": _DISCLOSURE_SEVERITY_LABELS.get(severity, _DISCLOSURE_SEVERITY_LABELS["info"]),
        "message": str(value.get("message") or ""),
        "field_path": str(value.get("field_path") or value.get("fieldPath") or ""),
    }


def _normalize_compiled_guardrails(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    return {
        "basis_document_ids": _string_list(payload.get("basis_document_ids") or payload.get("basisDocumentIds")),
        "constraint_types": _string_list(payload.get("constraint_types") or payload.get("constraintTypes")),
        "stage_scope": _string_list(payload.get("stage_scope") or payload.get("stageScope")),
        "topic_ids": _string_list(payload.get("topic_ids") or payload.get("topicIds")),
        "program_ids": _string_list(payload.get("program_ids") or payload.get("programIds")),
        "budget_cap": payload.get("budget_cap") if payload.get("budget_cap") is not None else payload.get("budgetCap"),
        "budget_floor": payload.get("budget_floor") if payload.get("budget_floor") is not None else payload.get("budgetFloor"),
        "quota_limit": payload.get("quota_limit") if payload.get("quota_limit") is not None else payload.get("quotaLimit"),
        "quota_limit_scope_type": str(payload.get("quota_limit_scope_type") or payload.get("quotaLimitScopeType") or ""),
        "quota_limit_source_mode": str(payload.get("quota_limit_source_mode") or payload.get("quotaLimitSourceMode") or ""),
        "quota_limit_executable": bool(payload.get("quota_limit_executable") or payload.get("quotaLimitExecutable") or False),
        "eligibility_gate": bool(payload.get("eligibility_gate") or payload.get("eligibilityGate") or False),
    }


def _rule_summary(value: Any) -> str:
    payload = _as_dict(value)
    if not payload:
        return ""
    operation = str(payload.get("operation") or payload.get("operator") or "").strip()
    metric = str(payload.get("metric") or "").strip()
    rule_value = payload.get("value")
    parts = [part for part in (metric, operation, "" if rule_value in (None, "") else str(rule_value)) if part]
    return " / ".join(parts)


def _normalize_stage_topic(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "topic_id": item.get("topic_id"),
        "topic_label": item.get("topic_label") or item.get("topic_id"),
        "metric": "",
        "metric_label": "",
        "delta": 0.0,
        "impact_origin": "none",
        "applied_actions": list(item.get("applied_actions", [])),
        "support_level": item.get("evidence_level", "proxy-grounded"),
    }


def _synthesize_contract_from_scenario(
    scenario: Any,
    *,
    result: SimulationResult | None,
    baseline: BaselineSnapshot | None,
) -> dict[str, Any]:
    if scenario is None:
        return {
            "scenario_id": result.scenario_id if result else "",
            "scenario_name": "",
            "forecast_window": result.forecast_window if result else "",
            "baseline": {"baseline_id": baseline.baseline_id if baseline else result.baseline_id if result else ""},
            "actions": [],
            "constraints": [],
            "evaluation_goals": [],
            "assumptions": list(result.assumptions) if result else [],
            "validation": {},
            "tags": [],
            "metadata": {"contract_source": "result_only"},
        }

    payload = _model_dump_if_needed(scenario)
    policy_shocks = payload.get("policy_shocks") or payload.get("policyShocks") or []
    return {
        "scenario_id": payload.get("scenario_id") or payload.get("scenarioId") or (result.scenario_id if result else ""),
        "scenario_name": payload.get("scenario_name") or payload.get("scenarioName") or "",
        "forecast_window": payload.get("forecast_window") or payload.get("forecastWindow") or (result.forecast_window if result else ""),
        "baseline": {
            "baseline_id": payload.get("baseline_id") or payload.get("baselineId") or (baseline.baseline_id if baseline else ""),
        },
        "intent": _as_dict(payload.get("intent")),
        "actions": [
            {
                "action_id": item.get("shock_id") or item.get("shockId"),
                "action_type": item.get("shock_type") or item.get("shockType"),
                "stage": _infer_action_stage(str(item.get("shock_type") or item.get("shockType") or "")),
                "support_level": "legacy_compatible",
                "target_scope": {
                    "topic_ids": list(item.get("target_topics") or item.get("targetTopics") or []),
                    "topic_labels": [],
                },
                "intensity": item.get("intensity"),
                "coverage": item.get("coverage"),
                "lag": item.get("lag", 0),
                "notes": [],
                "parameters": _as_dict(item.get("parameters")),
            }
            for item in policy_shocks
            if _as_dict(item)
        ],
        "constraints": [],
        "evaluation_goals": [],
        "assumptions": _string_list(payload.get("assumptions") or (result.assumptions if result else [])),
        "validation": {},
        "tags": _string_list(payload.get("tags")),
        "metadata": {
            **_as_dict(payload.get("metadata")),
            "contract_source": "legacy_scenario_definition",
        },
    }


def _build_topic_catalog(
    *,
    baseline: BaselineSnapshot | None,
    result: SimulationResult | None,
) -> dict[str, Any]:
    by_id: dict[str, str] = {}
    label_by_norm: dict[str, str] = {}
    label_to_ids: dict[str, list[str]] = {}

    def register(topic_id: Any, topic_label: Any) -> None:
        topic_id_text = str(topic_id or "").strip()
        label_text = _human_topic_label(topic_id_text, topic_label)
        if topic_id_text:
            by_id[topic_id_text] = label_text
        label_norm = _normalize_text_key(label_text)
        if not label_norm:
            return
        label_by_norm.setdefault(label_norm, label_text)
        if topic_id_text and topic_id_text not in label_to_ids.setdefault(label_norm, []):
            label_to_ids[label_norm].append(topic_id_text)

    if baseline is not None:
        for item in baseline.topics:
            register(item.topic_id, item.topic_label)
    if result is not None:
        for item in result.impacts:
            register(item.topic_id, item.topic_label)

    return {
        "by_id": by_id,
        "label_by_norm": label_by_norm,
        "label_to_ids": label_to_ids,
    }


def _enrich_action(
    action: dict[str, Any],
    *,
    topic_catalog: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    target_scope = _humanize_target_scope(_as_dict(action.get("target_scope")), topic_catalog)
    stage = str(action.get("stage") or "")
    action_type = str(action.get("action_type") or "")
    action_label = _action_type_label(action_type)
    stage_label = _stage_label(stage)
    summary_title = _action_summary_title(action_type, target_scope.get("summary") or "全体主题")
    return {
        **action,
        "ordinal": index,
        "stage_label": stage_label,
        "action_label": action_label,
        "target_scope": target_scope,
        "target_summary": target_scope.get("summary"),
        "display_title": summary_title,
    }


def _humanize_target_scope(target_scope: Mapping[str, Any], topic_catalog: Mapping[str, Any]) -> dict[str, Any]:
    raw_topic_ids = _string_list(target_scope.get("topic_ids") or target_scope.get("topicIds"))
    raw_topic_labels = _string_list(target_scope.get("topic_labels") or target_scope.get("topicLabels"))
    by_id = _as_dict(topic_catalog.get("by_id"))
    label_by_norm = _as_dict(topic_catalog.get("label_by_norm"))

    resolved_labels: list[str] = []
    resolved_ids: list[str] = []

    for label in raw_topic_labels:
        canonical = label_by_norm.get(_normalize_text_key(label)) or _human_topic_label("", label)
        if canonical not in resolved_labels:
            resolved_labels.append(canonical)

    for raw_value in raw_topic_ids:
        if raw_value in by_id:
            resolved_ids.append(raw_value)
            canonical = by_id[raw_value]
        else:
            canonical = label_by_norm.get(_normalize_text_key(raw_value)) or _human_topic_label("", raw_value)
        if canonical and canonical not in resolved_labels:
            resolved_labels.append(canonical)

    target_count = len(raw_topic_ids) or len(resolved_labels)

    return {
        "topic_ids": raw_topic_ids,
        "resolved_topic_ids": resolved_ids,
        "topic_labels": resolved_labels,
        "target_count": target_count,
        "summary": _summarize_targets(resolved_labels, target_count),
    }


def _build_generated_intent(actions: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    if not actions:
        return {
            "question": "原始数据未提供明确问题定义。",
            "decision_context": "当前只能根据已有设定查看可能出现的结果变化。",
            "policy_problem": "原始数据没有给出明确的政策目标。",
            "desired_outcome": "先看清哪些主题会发生变化、变化落在哪个环节。",
            "narrative": "页面按申报、评审、立项和后续外溢四段展示变化。",
        }

    first_action = _as_dict(actions[0])
    first_title = str(first_action.get("display_title") or "调整资助组合").strip()
    return {
        "question": "原始数据未提供明确问题定义。",
        "decision_context": f"当前能确认的主线是“{first_title}”。",
        "policy_problem": "原始数据只给出了推演设定，没有额外写明政策目标。",
        "desired_outcome": "先看清受影响主题、变化方向和影响环节。",
        "narrative": "领导页按设定、依据、推演过程和结果边界展开。",
    }


def _build_generated_scenario_name(actions: Sequence[Mapping[str, Any]]) -> str:
    if not actions:
        return "结果预演"
    first_action = _as_dict(actions[0])
    first_title = str(first_action.get("display_title") or "政策动作").strip()
    if len(actions) == 1:
        return f"结果预演：{first_title}"
    return f"结果预演：{first_title}等 {len(actions)} 条设定"


def _build_fallback_headline_bullets(
    *,
    actions: Sequence[Mapping[str, Any]],
    counterfactual: Mapping[str, Any],
    stage_impacts: Sequence[Mapping[str, Any]],
) -> list[str]:
    output: list[str] = []
    if actions:
        first_action = _as_dict(actions[0])
        output.append(f"原始数据共给出 {len(actions)} 条方案设定，页面主线按“{first_action.get('display_title') or '调整资助组合'}”展开。")
    if counterfactual:
        funding_delta = _as_number(counterfactual.get("net_delta_funding_amount"))
        funded_delta = _as_number(counterfactual.get("net_delta_funded_count"))
        output.append(
            f"回放结果显示，合同专项经费净变化 {_format_payload_number(funding_delta, 'currency')}，立项数净变化 {_format_payload_number(funded_delta, 'int')}。"
        )
    if stage_impacts:
        output.append(f"页面按 {len(stage_impacts)} 个治理阶段展开推演，便于区分直接影响与结构外溢。")
    return output


def _summarize_targets(labels: Sequence[str], target_count: int) -> str:
    unique_labels = [str(item).strip() for item in labels if str(item).strip()]
    if not unique_labels:
        return "全体主题"
    if len(unique_labels) == 1:
        if target_count > 1:
            return f"{unique_labels[0]}（{target_count} 个细分主题）"
        return unique_labels[0]
    if len(unique_labels) <= 3:
        joined = "、".join(unique_labels)
        if target_count > len(unique_labels):
            return f"{joined}，共 {target_count} 个主题"
        return joined
    return f"{unique_labels[0]}、{unique_labels[1]}等 {len(unique_labels)} 类主题，共 {target_count} 个主题"


def _format_payload_number(value: Any, value_format: str) -> str:
    number = _as_number(value)
    if value_format == "int":
        return f"{number:,.0f}"
    if value_format == "currency":
        return f"{number:,.2f}"
    return f"{number:,.3f}"


def _action_summary_title(action_type: str, target_summary: str) -> str:
    target_text = str(target_summary or "全体主题")
    verb = _action_verb(action_type)
    if target_text == "全体主题":
        return f"整体{verb}"
    return f"对{target_text}{verb}"


def _action_type_label(action_type: str) -> str:
    lowered = str(action_type or "").strip().lower()
    if "fund" in lowered or "budget" in lowered or "award" in lowered:
        return "经费支持"
    if "quota" in lowered:
        return "配额调整"
    if "review" in lowered or "threshold" in lowered:
        return "评审门槛调整"
    if "collaboration" in lowered or "spillover" in lowered:
        return "协作牵引"
    if "priority" in lowered or "guide" in lowered:
        return "申报导向调整"
    return "政策动作"


def _document_type_label(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    if lowered == "guide":
        return "申报指南"
    if lowered in {"policy", "management_rule"}:
        return "政策/办法"
    if lowered == "notice":
        return "通知"
    if lowered == "interpretation":
        return "解读"
    return lowered or "正式文本"


def _action_verb(action_type: str) -> str:
    lowered = str(action_type or "").strip().lower()
    if "fund" in lowered or "budget" in lowered or "award" in lowered:
        return "加大经费支持"
    if "quota" in lowered:
        return "调整配额结构"
    if "review" in lowered or "threshold" in lowered:
        return "调整评审门槛"
    if "collaboration" in lowered or "spillover" in lowered:
        return "加强协作牵引"
    if "priority" in lowered or "guide" in lowered:
        return "强化申报导向"
    return "进行政策调整"


def _stage_label(stage: str) -> str:
    stage_value = str(stage or "")
    for spec in _GOVERNANCE_STAGE_SPECS:
        if spec["stage_id"] == stage_value:
            return str(spec["stage_label"])
    return stage_value or "未分阶段"


def _human_topic_label(topic_id: str, topic_label: Any) -> str:
    label = " ".join(str(topic_label or "").strip().split())
    if label:
        return label
    text = " ".join(str(topic_id or "").strip().split())
    if "-" not in text:
        return text
    prefix, remainder = text.split("-", 1)
    prefix = prefix.replace("_", "")
    remainder = " ".join(remainder.strip().split())
    if prefix and remainder and len(prefix) >= 6 and prefix.isascii() and prefix.isalnum():
        return remainder
    return text


def _normalize_text_key(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _raw_intensity_suffix(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"，强度 {float(_as_number(value)):.2f}"


def _dedupe_strings(values) -> list[str]:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in output:
            continue
        output.append(text)
    return output


def _infer_action_stage(action_type: str) -> str:
    lowered = action_type.lower()
    if "quota" in lowered or "priority" in lowered or "guide" in lowered:
        return "application_response"
    if "review" in lowered or "threshold" in lowered:
        return "review_selection"
    if "fund" in lowered or "budget" in lowered or "award" in lowered:
        return "award_contract"
    if "collaboration" in lowered or "spillover" in lowered or "migration" in lowered:
        return "structural_spillover"
    return "application_response"


def _baseline_source(baseline: BaselineSnapshot | None) -> str:
    if baseline is None:
        return ""
    provenance = baseline.metadata.get("baselineProvenance")
    if isinstance(provenance, dict):
        kind = str(provenance.get("kind") or "").strip()
        if kind == "shared_layer":
            return "共享业务数据基线"
        return str(provenance.get("source") or kind)
    return str(baseline.metadata.get("source") or "")


def _metric_card(key: str, label: str, value: Any, value_format: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": round(float(value), 6) if isinstance(value, (int, float)) else value,
        "format": value_format,
    }


def _impact_magnitude(item: SimulationTopicImpact) -> float:
    return (
        abs(item.delta_application_count)
        + abs(item.delta_funded_count)
        + abs(item.delta_funding_amount)
        + abs(item.delta_collaboration_density)
        + abs(item.delta_topic_centrality)
        + abs(item.delta_migration_strength)
        + abs(item.delta_proxy_risk)
    )


def _avg(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _dedupe_disclosures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.get("code", ""), item.get("severity", ""), item.get("message", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _support_label(value: str) -> str:
    return _SUPPORT_LABELS.get(value, value or _SUPPORT_LABELS["unknown"])


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, Sequence):
        return []
    output = []
    for item in value:
        text = str(item).strip()
        if text:
            output.append(text)
    return output


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _as_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _pick_first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _model_dump_if_needed(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _model_dump_if_needed(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_model_dump_if_needed(item) for item in value]
    return value
