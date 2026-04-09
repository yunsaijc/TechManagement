"""合作单位注册地区检查"""
from __future__ import annotations

import re

from src.common.models import CheckResult, CheckStatus
from src.services.review.project_config import get_project_config
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class CooperationRegionCheckRule(BaseProjectRule):
    """检查合作单位是否位于政策允许地区"""

    name = "cooperation_region_check"
    description = "检查合作单位注册地区是否符合申报通知要求"
    priority = 83

    async def should_run(self, context) -> bool:
        return bool(context.project_info.has_cooperation_unit)

    async def check(self, context):
        config = get_project_config(context.project_info.project_type) or {}
        constraints = config.get("constraints", {})
        allowed_regions = constraints.get("allowed_cooperation_regions", [])
        if not allowed_regions:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="当前项目类型未配置合作单位地区限制",
                evidence={},
            )

        cooperation = context.cooperation_info
        units = list((cooperation.cooperation_units if cooperation else []) or [])
        region_details = list((cooperation.cooperation_unit_region_details if cooperation else []) or [])
        if not units:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="申报书标记存在合作单位，但未提取到合作单位信息",
                evidence={"allowed_regions": allowed_regions},
            )

        allowed_tokens = self._build_allowed_tokens(allowed_regions)
        detail_map = {
            re.sub(r"\s+", "", str(item.get("unit", ""))): str(item.get("region", "")).strip()
            for item in region_details
            if isinstance(item, dict) and str(item.get("unit", "")).strip()
        }
        hits = []
        unmatched = []

        for unit in units:
            normalized_unit = re.sub(r"\s+", "", unit)
            region_text = detail_map.get(normalized_unit, "")
            merged_text = f"{region_text} {unit}".strip()
            matched = next((token for token in allowed_tokens if token and token in merged_text), "")
            if matched:
                hits.append(
                    {
                        "unit": unit,
                        "region_text": region_text,
                        "matched_region_token": matched,
                    }
                )
            else:
                unmatched.append(
                    {
                        "unit": unit,
                        "region_text": region_text,
                    }
                )

        evidence = {
            "allowed_regions": allowed_regions,
            "cooperation_units": units,
            "cooperation_region_details": region_details,
            "matched_units": hits,
            "unmatched_units": unmatched,
        }
        if unmatched:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="存在合作单位未命中允许注册地区",
                evidence=evidence,
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="合作单位注册地区符合要求",
            evidence=evidence,
        )

    def _build_allowed_tokens(self, allowed_regions: list[str]) -> list[str]:
        """把全称地区拆成可匹配的关键词"""
        tokens = set()
        for region in allowed_regions:
            normalized = re.sub(r"\s+", "", str(region or ""))
            if not normalized:
                continue
            tokens.add(normalized)
            for token in ["巴音郭楞", "铁门关", "阿里", "新疆", "西藏"]:
                if token in normalized:
                    tokens.add(token)
        return sorted(tokens, key=len, reverse=True)
