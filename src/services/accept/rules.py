"""验收核验规则模板。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.services.accept.models import EvidenceAggregation, KPICommitment, MetricEvaluationLayer


SummaryFallback = Literal["none", "max", "sum", "count"]


class MetricRuleTemplate(BaseModel):
    metric_name: str
    metric_category: str = ""
    metric_layer: MetricEvaluationLayer = "generic"
    itemized: bool = False
    aggregation: EvidenceAggregation = "sum"
    require_primary: bool = False
    primary_doc_kinds: list[str] = Field(default_factory=list)
    allowed_doc_kinds: list[str] = Field(default_factory=list)
    summary_fallback: SummaryFallback = "none"
    allowed_actions: list[str] = Field(default_factory=list)
    variant_alias_groups: dict[str, list[str]] = Field(default_factory=dict)


class RuleRegistry:
    def __init__(self, templates: list[MetricRuleTemplate]) -> None:
        self.templates = templates
        self.by_metric = {(item.metric_name, item.metric_category): item for item in templates}

    def resolve(self, commitment: KPICommitment) -> MetricRuleTemplate:
        rule = self.by_metric.get((commitment.metric_name, commitment.metric_category))
        if rule:
            return rule
        return MetricRuleTemplate(
            metric_name=commitment.metric_name,
            metric_category=commitment.metric_category,
            itemized=commitment.aggregation == "count",
            aggregation=commitment.aggregation,
            summary_fallback="max" if commitment.aggregation == "max" else "sum",
        )


@lru_cache(maxsize=1)
def load_default_rule_registry() -> RuleRegistry:
    path = Path(__file__).with_name("rule_templates.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RuleRegistry([MetricRuleTemplate.model_validate(item) for item in payload])
