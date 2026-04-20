"""奖励平台主要完成人情况表专项规则。"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from src.common.models import CheckResult, CheckStatus
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


def _normalize_text(value: str) -> str:
    text = str(value or "").strip()
    return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/]", "", text).lower()


def _name_matches(expected: str, candidates: List[str]) -> bool:
    left = _normalize_text(expected)
    if not left:
        return False
    for item in candidates:
        right = _normalize_text(item)
        if not right:
            continue
        if left == right or left in right or right in left:
            return True
    return False


def _unit_matches(expected: str, candidates: List[str]) -> bool:
    return _name_matches(expected, candidates)


def _dedup_texts(values: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        key = _normalize_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _load_award_contributor_payload(context: ReviewContext) -> Dict[str, Any]:
    extracted = context.extracted
    llm_analysis = extracted.get("llm_analysis") or {}
    payload = llm_analysis.get("award_contributor_analysis") or {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


class _BaseAwardContributorRule(BaseRule):
    """主要完成人情况表专项规则基类。"""

    def _payload(self, context: ReviewContext) -> Dict[str, Any]:
        return _load_award_contributor_payload(context)

    def _missing_analysis_result(self) -> CheckResult:
        return CheckResult(
            item=self.name,
            status=CheckStatus.WARNING,
            message="未生成主要完成人情况表结构化分析结果",
            evidence={},
        )


@RuleRegistry.register
class AwardContributorSignatureConsistencyRule(_BaseAwardContributorRule):
    """本人姓名与签名一致性检查。"""

    name = "award_contributor_signature_consistency"
    description = "完成人姓名与本人签名一致性检查"
    priority = 75

    async def check(self, context: ReviewContext) -> CheckResult:
        payload = self._payload(context)
        if not payload:
            return self._missing_analysis_result()

        contributor_name = str(payload.get("contributor_name") or "").strip()
        signature_names = _dedup_texts([str(item) for item in payload.get("signature_names", []) if str(item).strip()])

        if not contributor_name:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未识别到表单中的完成人姓名",
                evidence={"signature_names": signature_names},
            )

        if not signature_names:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"未识别到与完成人“{contributor_name}”对应的本人签名",
                evidence={
                    "contributor_name": contributor_name,
                    "signature_names": [],
                },
            )

        if not _name_matches(contributor_name, signature_names):
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"完成人“{contributor_name}”与本人签名不一致",
                evidence={
                    "contributor_name": contributor_name,
                    "signature_names": signature_names,
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message=f"完成人“{contributor_name}”与本人签名一致",
            evidence={
                "contributor_name": contributor_name,
                "signature_names": signature_names,
            },
        )


class _BaseAwardContributorStampRule(_BaseAwardContributorRule):
    """单位与对应公章一致性检查基类。"""

    role_key: str = ""
    role_label: str = ""

    def _expected_unit(self, payload: Dict[str, Any]) -> str:
        return str(payload.get(self.role_key) or "").strip()

    def _role_stamp_units(self, payload: Dict[str, Any]) -> List[str]:
        return _dedup_texts([str(item) for item in payload.get(f"{self.role_key}_stamp_units", []) if str(item).strip()])

    def _build_evidence(
        self,
        expected_unit: str,
        same_unit: bool,
        role_units: List[str],
        all_stamp_units: List[str],
    ) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {
            self.role_key: expected_unit,
            "same_unit": same_unit,
            "role_stamp_units": role_units,
        }
        if all_stamp_units:
            evidence["all_stamp_units"] = all_stamp_units
        return evidence

    async def check(self, context: ReviewContext) -> CheckResult:
        payload = self._payload(context)
        if not payload:
            return self._missing_analysis_result()

        expected_unit = self._expected_unit(payload)
        if not expected_unit:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message=f"未识别到表单中的{self.role_label}",
                evidence={},
            )

        work_unit = str(payload.get("work_unit") or "").strip()
        completion_unit = str(payload.get("completion_unit") or "").strip()
        same_unit = bool(work_unit and completion_unit and _unit_matches(work_unit, [completion_unit]))

        role_units = self._role_stamp_units(payload)
        all_stamp_units = _dedup_texts([str(item) for item in payload.get("all_stamp_units", []) if str(item).strip()])
        fallback_units = _dedup_texts(role_units + all_stamp_units)

        # 两个单位相同时，只盖一个章也可满足两个规则。
        if same_unit:
            other_role_key = "completion_unit" if self.role_key == "work_unit" else "work_unit"
            other_role_units = _dedup_texts(
                [str(item) for item in payload.get(f"{other_role_key}_stamp_units", []) if str(item).strip()]
            )
            fallback_units = _dedup_texts(fallback_units + other_role_units)

        if not fallback_units:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"未识别到“{self.role_label}”位置的公章",
                evidence=self._build_evidence(expected_unit, same_unit, role_units, all_stamp_units),
            )

        if not _unit_matches(expected_unit, fallback_units):
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"{self.role_label}“{expected_unit}”与对应公章不一致",
                evidence=self._build_evidence(expected_unit, same_unit, role_units, all_stamp_units),
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message=f"{self.role_label}“{expected_unit}”与对应公章一致",
            evidence=self._build_evidence(expected_unit, same_unit, role_units, all_stamp_units),
        )


@RuleRegistry.register
class AwardContributorWorkUnitStampConsistencyRule(_BaseAwardContributorStampRule):
    """工作单位与工作单位公章一致性检查。"""

    name = "award_contributor_work_unit_stamp_consistency"
    description = "工作单位与工作单位处公章一致性检查"
    priority = 74
    role_key = "work_unit"
    role_label = "工作单位"


@RuleRegistry.register
class AwardContributorCompletionUnitStampConsistencyRule(_BaseAwardContributorStampRule):
    """完成单位与完成单位公章一致性检查。"""

    name = "award_contributor_completion_unit_stamp_consistency"
    description = "完成单位与完成单位处公章一致性检查"
    priority = 73
    role_key = "completion_unit"
    role_label = "完成单位"
