"""KPI 与附件证据的匹配推理。"""
from __future__ import annotations

import re

from src.services.accept.normalizer import EvidenceNormalizer
from src.services.accept.models import (
    AcceptanceCheckResult,
    AcceptanceCheckRow,
    AttachmentEvidence,
    KPICommitment,
    KPIMatchDetail,
)
from src.services.accept.rules import MetricRuleTemplate, RuleRegistry, load_default_rule_registry


class AcceptanceReasoner:
    """规则化履约核验引擎。"""

    def __init__(
        self,
        *,
        rule_registry: RuleRegistry | None = None,
        normalizer: EvidenceNormalizer | None = None,
    ) -> None:
        self.rule_registry = rule_registry or load_default_rule_registry()
        self.normalizer = normalizer or EvidenceNormalizer()

    def check(
        self,
        *,
        project_id: str,
        commitments: list[KPICommitment],
        evidence_items: list[AttachmentEvidence],
    ) -> AcceptanceCheckResult:
        rows: list[AcceptanceCheckRow] = []
        for commitment in commitments:
            rule = self.rule_registry.resolve(commitment)
            matched = [item for item in evidence_items if self._is_match(commitment, item, rule)]
            application_matched = [item for item in matched if self._is_application_claim(item)]
            attachment_matched = [item for item in matched if not self._is_application_claim(item)]

            application_value, application_details, application_count, application_basis, application_risks = self._aggregate(
                commitment,
                application_matched,
                rule,
                prefer_summary=True,
            )
            attachment_value, attachment_details, attachment_count, attachment_basis, attachment_risks = self._aggregate(
                commitment,
                attachment_matched,
                rule,
                prefer_best_value=True,
            )
            if attachment_matched and rule.itemized:
                actual_value = attachment_value
            else:
                actual_value = min(application_value, attachment_value) if application_matched and attachment_matched else max(application_value, attachment_value)
            status = self._decide_three_way_status(commitment, application_value, attachment_value, bool(application_matched), bool(attachment_matched))
            application_status = self._decide_status(commitment, application_value)
            attachment_status = self._decide_status(commitment, attachment_value)
            ratio = self._compute_ratio(commitment.target_value, actual_value)
            if status == "fulfilled":
                ratio = 1.0
            elif status == "partial":
                ratio = min(
                    ratio,
                    self._compute_ratio(commitment.target_value, application_value) if application_matched else 0.0,
                    self._compute_ratio(commitment.target_value, attachment_value) if attachment_matched else 0.0,
                )
            details = self._merge_details(commitment, rule, application_details, attachment_details)
            applied_count = application_count + attachment_count
            risk_flags = [*application_risks, *attachment_risks]
            conflict_flags = self._detect_conflicts(
                commitment,
                application_value=application_value,
                attachment_value=attachment_value,
                has_application=bool(application_matched),
                has_attachment=bool(attachment_matched),
            )
            consistency_summary = self._build_consistency_summary(
                commitment,
                application_value,
                attachment_value,
                bool(application_matched),
                bool(attachment_matched),
            )
            rule_basis = f"验收申请：{application_basis or '未命中'}；附件证明：{attachment_basis or '未命中'}"
            rows.append(
                AcceptanceCheckRow(
                    commitment_id=commitment.commitment_id,
                    metric_name=commitment.metric_name,
                    metric_category=commitment.metric_category,
                    target_display=f"{commitment.comparator}{self._format_number(commitment.target_value)}{commitment.target_unit}",
                    target_value=commitment.target_value,
                    target_unit=commitment.target_unit,
                    actual_display=f"{self._format_number(actual_value)}{commitment.target_unit}",
                    actual_value=actual_value,
                    application_display=f"{self._format_number(application_value)}{commitment.target_unit}",
                    application_value=application_value,
                    application_evidence_count=application_count,
                    attachment_display=f"{self._format_number(attachment_value)}{commitment.target_unit}",
                    attachment_value=attachment_value,
                    attachment_evidence_count=attachment_count,
                    consistency_summary=consistency_summary,
                    fulfillment_ratio=ratio,
                    status=status,
                    matched_evidence_count=len(matched),
                    applied_evidence_count=applied_count,
                    rule_basis=rule_basis,
                    risk_flags=risk_flags,
                    reason=self._build_three_way_reason(
                        status,
                        commitment,
                        application_value,
                        attachment_value,
                        application_matched,
                        attachment_matched,
                        applied_count,
                        risk_flags,
                    ),
                    source_line=commitment.source_line,
                    action=commitment.action,
                    subject_scope=commitment.subject_scope,
                    time_constraint=commitment.time_constraint,
                    caliber_constraint=commitment.caliber_constraint,
                    metric_variant=commitment.metric_variant,
                    metric_layer=commitment.metric_layer,
                    application_status=application_status,
                    attachment_status=attachment_status,
                    conflict_flags=conflict_flags,
                    match_details=details,
                    source_block_id=commitment.source_block_id,
                    source_page=commitment.source_page,
                )
            )

        fulfilled = sum(1 for row in rows if row.status == "fulfilled")
        partial = sum(1 for row in rows if row.status == "partial")
        missing = sum(1 for row in rows if row.status == "missing")
        total = len(rows)
        rate = fulfilled / total if total else 0.0
        return AcceptanceCheckResult(
            project_id=project_id,
            total_commitments=total,
            fulfilled_commitments=fulfilled,
            partial_commitments=partial,
            missing_commitments=missing,
            fulfillment_rate=rate,
            rows=rows,
            extracted_commitments=commitments,
            extracted_evidence=evidence_items,
            warnings=[] if commitments else ["未从任务书中提取到可核验 KPI 指标"],
        )

    def _is_match(self, commitment: KPICommitment, evidence: AttachmentEvidence, rule: MetricRuleTemplate) -> bool:
        if commitment.metric_category != evidence.metric_category:
            return False
        if rule.allowed_doc_kinds and evidence.doc_kind not in rule.allowed_doc_kinds:
            return False
        if commitment.metric_name != evidence.metric_name and not (set(commitment.keywords) & set(evidence.keywords)):
            if evidence.metric_name not in commitment.alternate_metric_names and not self._metrics_are_compatible(commitment, evidence, rule):
                return False
        if commitment.metric_variant and evidence.metric_variant:
            skip_variant = (
                evidence.metric_name == commitment.metric_name
                and evidence.evidence_mode == "itemized"
                and evidence.doc_kind in set(rule.primary_doc_kinds or [])
            )
            if not skip_variant and not self._variant_compatible(commitment.metric_variant, evidence.metric_variant, rule):
                return False
        if commitment.action and evidence.action:
            if evidence.doc_kind == "验收申请" and commitment.metric_name in {
                "研究报告",
                "决策咨询报告",
                "科技报告",
                "技术标准",
                "科技论文",
            }:
                pass
            elif (
                commitment.metric_name in {"研究报告", "决策咨询报告"}
                and evidence.doc_kind in {"科技报告", "其他材料"}
                and evidence.evidence_role == "primary"
            ):
                pass
            elif not self._action_compatible(commitment.action, evidence.action, rule):
                return False
        if commitment.time_constraint and evidence.time_label:
            if not self._time_compatible(commitment.time_constraint, evidence.time_label):
                return False
        if commitment.caliber_constraint and evidence.caliber_label:
            if not self._caliber_compatible(commitment.caliber_constraint, evidence.caliber_label):
                return False
        if commitment.metric_name in {"检测范围", "检测频率", "检测标准偏差", "最大测量误差"}:
            # 申请表单独展示，仅作 application 侧；附件侧认科技报告/检测报告等（见 _is_application_claim 分流）
            if evidence.doc_kind not in {"验收申请", "科技报告", "检测报告", "其他材料"}:
                return False
        if commitment.metric_name in {"技术方案", "实验系统", "工程样机", "示范基地"}:
            if evidence.doc_kind not in {"验收申请", "科技报告", "检测报告", "其他材料"}:
                return False
        if commitment.metric_name == "技术方案" and evidence.doc_kind == "科技报告":
            return True
        if commitment.metric_name == "科技论文" and evidence.doc_kind in {"论文", "其他材料"}:
            return True
        if commitment.metric_name == "培养研究生" and evidence.doc_kind in {"学位论文", "其他材料"}:
            return True
        return True

    def _metrics_are_compatible(
        self,
        commitment: KPICommitment,
        evidence: AttachmentEvidence,
        rule: MetricRuleTemplate,
    ) -> bool:
        if commitment.metric_name == evidence.metric_name:
            return True
        if evidence.metric_name in commitment.alternate_metric_names:
            return True
        if commitment.metric_variant == "科技报告/研究报告" and evidence.metric_name in {"科技报告", "研究报告"}:
            return True
        blob = f"{evidence.artifact_title or ''} {evidence.title or ''} {evidence.excerpt or ''}"
        if commitment.metric_name == "研究报告":
            if evidence.metric_name == "科技报告" and evidence.evidence_role == "primary":
                if evidence.doc_kind in set(rule.primary_doc_kinds or []):
                    return True
            if evidence.metric_name == "研究报告" and "研究报告" in blob:
                return True
        if commitment.metric_name == "决策咨询报告":
            if evidence.metric_name == "决策咨询报告":
                return True
            if any(token in blob for token in ("决策参考报告", "决策咨询报告", "参考决策报告", "决策报告")):
                return True
        return False

    def _aggregate(
        self,
        commitment: KPICommitment,
        matched: list[AttachmentEvidence],
        rule: MetricRuleTemplate,
        *,
        prefer_summary: bool = False,
        prefer_best_value: bool = False,
    ) -> tuple[float, list[KPIMatchDetail], int, str, list[str]]:
        values: list[float] = []
        valued_items: list[AttachmentEvidence] = []
        details: list[KPIMatchDetail] = []
        risk_flags: list[str] = []
        filtered = self._select_evidence(commitment, matched, rule, prefer_summary=prefer_summary)
        for item in filtered:
            value = self._evidence_value_for_commitment(item, commitment)
            if value <= 0:
                continue
            values.append(value)
            valued_items.append(item)
            if item in filtered:
                details.append(
                    KPIMatchDetail(
                        evidence_id=item.evidence_id,
                        file_name=item.file_name,
                        doc_kind=item.doc_kind,
                        metric_name=commitment.metric_name,
                        contribution_value=value,
                        evidence_role=item.evidence_role,
                        evidence_mode=item.evidence_mode,
                        evidence_nature=item.evidence_nature,
                        evidence_judge_source=item.evidence_judge_source,
                        evidence_judge_reason=item.evidence_judge_reason,
                        artifact_key=item.artifact_key,
                        time_label=item.time_label,
                        caliber_label=item.caliber_label,
                        title=item.artifact_title or item.title,
                        excerpt=item.excerpt,
                        reason=self._detail_reason(item, value, commitment),
                        source_block_id=item.source_block_id,
                        source_page=item.source_page,
                    )
                )
        if not values:
            if matched and not filtered:
                risk_flags.append("存在疑似证据，但被动作/时间/口径规则过滤")
            return 0.0, details, 0, "无有效证据", risk_flags
        if commitment.metric_layer == "financial":
            if not any(item.doc_kind == "审计报告" for item in filtered):
                risk_flags.append("财务指标缺少审计报告主证据")
            if any("口径冲突" in (item.caliber_label or "") for item in filtered):
                risk_flags.append("财务证据存在口径冲突")
            if any("项目期外" in (item.time_label or "") for item in filtered):
                risk_flags.append("财务证据存在项目执行期外年份")
        if any(item.evidence_role != "primary" for item in filtered) and rule.require_primary:
            risk_flags.append("缺少主证据，当前结论依赖辅证据或派生证据")
        if rule.itemized:
            itemized = [item for item in filtered if item.evidence_mode == "itemized"]
            if itemized:
                distinct_keys = []
                seen_keys = set()
                for item in itemized:
                    key = item.normalized_artifact_key or item.artifact_key or f"{item.file_name}:{item.source_block_id}:{item.source_page}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    distinct_keys.append(item)
                actual = float(len(distinct_keys))
                basis = f"按去重后的单件成果证据核验，共 {len(distinct_keys)} 件"
                return actual, details, len(distinct_keys), basis, risk_flags
            summary_values = [value for item, value in zip(valued_items, values) if item.evidence_mode == "summary"]
            if summary_values:
                if prefer_summary:
                    best = (
                        self._best_summary_value(commitment, summary_values)
                        if prefer_best_value
                        else max(summary_values)
                    )
                    return best, details, len(summary_values), "按验收申请摘要性声明取最大值核验", risk_flags
                if rule.summary_fallback == "sum":
                    total = sum(summary_values)
                    risk_flags.append("缺少单件成果附件，当前按摘要性材料累计值核验")
                    return total, details, len(summary_values), "缺少单件成果证据，按摘要性材料累计值核验", risk_flags
                if rule.summary_fallback == "count":
                    count = float(len(summary_values))
                    risk_flags.append("缺少单件成果附件，当前按摘要性材料条数核验")
                    return count, details, len(summary_values), "缺少单件成果证据，按摘要性材料条数核验", risk_flags
                if rule.summary_fallback == "max":
                    risk_flags.append("缺少单件成果附件，当前按摘要性材料取最大声明值")
                    best = (
                        self._best_summary_value(commitment, summary_values)
                        if prefer_best_value
                        else max(summary_values)
                    )
                    return best, details, len(summary_values), "缺少单件成果证据，按摘要性材料取最大值核验", risk_flags
            return 0.0, details, 0, "无有效证据", risk_flags
        if rule.aggregation == "max":
            best = self._best_summary_value(commitment, values) if prefer_best_value else max(values)
            basis = (
                "按附件实测/主证据取最优值核验"
                if prefer_best_value and commitment.comparator in {"≤", "<"}
                else "按数值型摘要证据取最大值核验"
            )
            return best, details, len(filtered), basis, risk_flags
        if rule.aggregation == "count":
            return float(len(values)), details, len(values), "按命中证据条数核验", risk_flags
        return sum(values), details, len(filtered), "按数值型摘要证据累计核验", risk_flags


    def _is_application_claim(self, evidence: AttachmentEvidence) -> bool:
        if evidence.doc_kind != "验收申请":
            return False
        # 验收申请表中的附件目录条目（如“专利授权证书/受理通知书”）应作为附件侧证据，
        # 否则会被误并入申请侧，导致附件证明始终为 0。
        if (
            evidence.metric_name in {"发明专利", "实用新型专利"}
            and evidence.evidence_mode == "itemized"
            and any(token in (evidence.excerpt or "") for token in ("专利授权证书", "专利受理通知书"))
        ):
            return False
        return True

    def _decide_three_way_status(
        self,
        commitment: KPICommitment,
        application_value: float,
        attachment_value: float,
        has_application: bool,
        has_attachment: bool,
    ) -> str:
        application_ok = has_application and self._decide_status(commitment, application_value) == "fulfilled"
        attachment_ok = has_attachment and self._attachment_satisfies_completion(
            commitment,
            application_value,
            attachment_value,
            has_application=has_application,
        )
        if attachment_ok:
            return "fulfilled"
        if application_value <= 0 and attachment_value <= 0:
            return "missing"
        return "partial"

    def _build_consistency_summary(
        self,
        commitment: KPICommitment,
        application_value: float,
        attachment_value: float,
        has_application: bool,
        has_attachment: bool,
    ) -> str:
        target = f"{commitment.comparator}{self._format_number(commitment.target_value)}{commitment.target_unit}"
        application_text = f"验收申请声明 {self._format_number(application_value)}{commitment.target_unit}" if has_application else "验收申请未提取到完成情况"
        attachment_text = f"附件证明 {self._format_number(attachment_value)}{commitment.target_unit}" if has_attachment else "附件未提取到证明材料"
        application_ok = has_application and self._decide_status(commitment, application_value) == "fulfilled"
        attachment_ok = has_attachment and self._attachment_satisfies_completion(
            commitment,
            application_value,
            attachment_value,
            has_application=has_application,
        )
        if application_ok and attachment_ok:
            verdict = "验收申请与附件证明均达到任务书考核指标，且附件证明不低于验收申请表完成情况，满足验收"
        elif not has_application and not has_attachment:
            verdict = "缺少验收申请完成情况和附件证明，无法确认满足验收"
        elif not has_application and attachment_ok:
            verdict = "附件证明已达到任务书考核指标；验收申请表未抽到明确完成值，但不影响附件独立证明成立"
        elif not has_application:
            verdict = "缺少验收申请表完成情况，不能判定满足验收"
        elif not has_attachment:
            verdict = "缺少验收申请附件证明，不能判定满足验收"
        elif application_ok:
            verdict = "验收申请已达到任务书目标，但附件证明未同时满足任务书考核指标与验收申请表完成情况"
        elif attachment_ok:
            verdict = "附件证明已达到任务书目标，但验收申请未达到任务书目标"
        else:
            verdict = "验收申请与附件证明均未达到任务书目标"
        return f"任务书目标 {target}；{application_text}；{attachment_text}；{verdict}"

    def _attachment_satisfies_completion(
        self,
        commitment: KPICommitment,
        application_value: float,
        attachment_value: float,
        *,
        has_application: bool,
    ) -> bool:
        if self._decide_status(commitment, attachment_value) != "fulfilled":
            return False
        if not has_application:
            return True
        return self._is_not_weaker_than_application(commitment, attachment_value, application_value)

    def _is_not_weaker_than_application(self, commitment: KPICommitment, attachment_value: float, application_value: float) -> bool:
        if commitment.comparator in {"≤", "<"}:
            return attachment_value <= application_value
        if commitment.comparator in {"=",}:
            return attachment_value == application_value
        return attachment_value >= application_value

    def _build_three_way_reason(
        self,
        status: str,
        commitment: KPICommitment,
        application_value: float,
        attachment_value: float,
        application_matched: list[AttachmentEvidence],
        attachment_matched: list[AttachmentEvidence],
        applied_count: int,
        risk_flags: list[str],
    ) -> str:
        suffix = f"；风险：{'；'.join(risk_flags)}" if risk_flags else ""
        consistency = self._build_consistency_summary(
            commitment,
            application_value,
            attachment_value,
            bool(application_matched),
            bool(attachment_matched),
        )
        if status == "fulfilled":
            return f"{consistency}；采用 {applied_count} 条有效定位证据{suffix}"
        return f"{consistency}；采用 {applied_count} 条有效定位证据，需专家复核{suffix}"

    def _decide_status(self, commitment: KPICommitment, actual_value: float) -> str:
        if actual_value <= 0:
            return "missing"
        ok = False
        if commitment.comparator == "≥":
            ok = actual_value >= commitment.target_value
        elif commitment.comparator == "≤":
            ok = actual_value <= commitment.target_value
        elif commitment.comparator == "=":
            ok = actual_value == commitment.target_value
        elif commitment.comparator == ">":
            ok = actual_value > commitment.target_value
        elif commitment.comparator == "<":
            ok = actual_value < commitment.target_value
        return "fulfilled" if ok else "partial"

    def _compute_ratio(self, target_value: float, actual_value: float) -> float:
        if target_value <= 0:
            return 1.0 if actual_value > 0 else 0.0
        return max(0.0, min(actual_value / target_value, 1.0))

    def _build_reason(
        self,
        status: str,
        matched: list[AttachmentEvidence],
        actual_value: float,
        commitment: KPICommitment,
        applied_count: int,
        risk_flags: list[str],
    ) -> str:
        if not matched:
            return "未检索到可支持该指标的附件证据"
        suffix = f"；风险：{'；'.join(risk_flags)}" if risk_flags else ""
        if status == "fulfilled":
            return (
                f"命中 {len(matched)} 条候选证据，采用 {applied_count} 条有效证据，"
                f"核得 {self._format_number(actual_value)}{commitment.target_unit}，达到承诺目标{suffix}"
            )
        return (
            f"命中 {len(matched)} 条候选证据，采用 {applied_count} 条有效证据，"
            f"核得 {self._format_number(actual_value)}{commitment.target_unit}，但仍低于承诺目标{suffix}"
        )

    def _best_summary_value(self, commitment: KPICommitment, values: list[float]) -> float:
        if not values:
            return 0.0
        if commitment.comparator in {"≤", "<"}:
            return min(values)
        if commitment.comparator in {"≥", ">"}:
            return max(values)
        return max(values)

    def _looks_like_self_eval_summary(self, item: AttachmentEvidence) -> bool:
        title = item.title or item.artifact_title or ""
        return "验收自评价" in title or "自评价报告" in title

    def _requires_concrete_attachment_proof(
        self,
        commitment: KPICommitment,
        rule: MetricRuleTemplate,
    ) -> bool:
        return (
            rule.itemized
            and commitment.metric_name in {
                "发明专利",
                "实用新型专利",
                "软件著作权",
                "科技论文",
                "培养研究生",
                "科技报告",
                "研究报告",
                "决策咨询报告",
            }
        )

    def _select_evidence(
        self,
        commitment: KPICommitment,
        matched: list[AttachmentEvidence],
        rule: MetricRuleTemplate,
        *,
        prefer_summary: bool = False,
    ) -> list[AttachmentEvidence]:
        filtered = self._dedupe_matched(matched)
        if not prefer_summary:
            filtered = self._drop_weak_attachment_evidence(commitment, filtered, rule)
            filtered = self._filter_attachment_proof_evidence(commitment, filtered, rule)
        if rule.itemized and rule.primary_doc_kinds:
            primary_itemized = [
                item for item in filtered
                if item.evidence_mode == "itemized"
                and item.evidence_nature == "artifact"
                and (item.doc_kind in rule.primary_doc_kinds or item.evidence_role == "primary")
            ]
            if primary_itemized:
                return primary_itemized
        if prefer_summary:
            summary = [item for item in filtered if item.evidence_mode == "summary"]
            if summary:
                return summary
        if rule.primary_doc_kinds:
            primary = [item for item in filtered if item.doc_kind in rule.primary_doc_kinds or item.evidence_role == "primary"]
            non_derived_primary = [item for item in primary if item.evidence_role != "derived"]
            if non_derived_primary:
                return non_derived_primary
            if primary and rule.require_primary:
                return primary
            if primary and not prefer_summary:
                return primary
        if rule.require_primary:
            primary = [item for item in filtered if item.evidence_role == "primary"]
            return primary or filtered
        if rule.itemized:
            primary_itemized = [
                item
                for item in filtered
                if item.evidence_mode == "itemized"
                and item.evidence_role == "primary"
                and (commitment.metric_layer != "deliverable" or item.evidence_nature == "artifact")
            ]
            if primary_itemized:
                return primary_itemized
            itemized = [item for item in filtered if item.evidence_mode == "itemized"]
            if itemized:
                return itemized
        return filtered

    def _drop_weak_attachment_evidence(
        self,
        commitment: KPICommitment,
        matched: list[AttachmentEvidence],
        rule: MetricRuleTemplate,
    ) -> list[AttachmentEvidence]:
        if not matched:
            return matched
        strong = [
            item
            for item in matched
            if item.evidence_role != "derived"
            and (
                not self._requires_concrete_attachment_proof(commitment, rule)
                or not self._looks_like_self_eval_summary(item)
            )
        ]
        if strong:
            matched = strong
        elif rule.primary_doc_kinds:
            primary_kind = [item for item in matched if item.doc_kind in rule.primary_doc_kinds]
            if primary_kind:
                matched = primary_kind
        return [item for item in matched if item.evidence_role != "derived"] or matched

    def _looks_like_reference_excerpt(self, item: AttachmentEvidence) -> bool:
        excerpt = item.excerpt or ""
        if re.match(r"^\[\d+\]", excerpt.strip()):
            return True
        if re.search(r"\[J\]|\[D\]|\[P\]", excerpt):
            return True
        return False

    def _filter_attachment_proof_evidence(
        self,
        commitment: KPICommitment,
        matched: list[AttachmentEvidence],
        rule: MetricRuleTemplate,
    ) -> list[AttachmentEvidence]:
        if not matched:
            return matched
        filtered = [
            item
            for item in matched
            if item.evidence_role not in {"catalog", "reference", "derived"}
            and not self._looks_like_reference_excerpt(item)
        ]
        if commitment.metric_layer == "deliverable":
            artifact_items = [item for item in filtered if item.evidence_nature == "artifact"]
            if artifact_items:
                filtered = artifact_items
        if commitment.metric_name == "科技论文" and rule.itemized:
            paper_items = [item for item in filtered if item.doc_kind == "论文" and item.evidence_mode == "itemized"]
            if paper_items:
                return paper_items
        if commitment.metric_name == "培养研究生" and rule.itemized:
            thesis_items = [item for item in filtered if item.doc_kind == "学位论文" and item.evidence_mode == "itemized"]
            if thesis_items:
                return thesis_items
        if commitment.metric_name in {"发明专利", "实用新型专利"} and rule.itemized:
            patent_items = [item for item in filtered if item.doc_kind == "专利证书" and item.evidence_mode == "itemized"]
            if patent_items:
                return patent_items
            # OCR 失败时，允许验收申请附件目录中的专利条目作为附件兜底证据。
            catalog_patent_items = [
                item
                for item in matched
                if item.metric_name in {"发明专利", "实用新型专利"}
                and item.evidence_mode == "itemized"
                and item.doc_kind == "验收申请"
                and ("专利授权证书" in (item.excerpt or "") or "专利受理通知书" in (item.excerpt or ""))
            ]
            if catalog_patent_items:
                return catalog_patent_items
        if commitment.metric_name in {"研究报告", "决策咨询报告"} and rule.itemized:
            report_items = [
                item
                for item in filtered
                if item.evidence_mode == "itemized"
                and item.evidence_role == "primary"
                and item.doc_kind in set(rule.primary_doc_kinds or [])
                and (
                    item.metric_name == commitment.metric_name
                    or (
                        commitment.metric_name == "研究报告"
                        and item.metric_name == "科技报告"
                        and self._is_formal_science_report_attachment(item)
                    )
                )
            ]
            if report_items:
                return report_items
        return filtered or matched

    @staticmethod
    def _is_formal_science_report_attachment(item: AttachmentEvidence) -> bool:
        blob = f"{item.artifact_title or ''} {item.title or ''} {item.excerpt or ''}"
        return bool(re.search(r"报告编号|MB1E\d+", blob)) or ("科技报告" in blob and "报告名称" in blob)

    def _merge_details(
        self,
        commitment: KPICommitment,
        rule: MetricRuleTemplate,
        application_details: list[KPIMatchDetail],
        attachment_details: list[KPIMatchDetail],
    ) -> list[KPIMatchDetail]:
        concrete_only = self._concrete_attachment_details(commitment, rule, attachment_details)
        proof_only = self._proof_attachment_details(commitment, rule, attachment_details)
        if concrete_only:
            return self._dedupe_detail_entries([*concrete_only, *application_details])
        if proof_only:
            return self._dedupe_detail_entries([*proof_only, *application_details])
        if self._requires_concrete_attachment_display(commitment, rule):
            return self._dedupe_detail_entries(application_details)
        return self._dedupe_detail_entries([*application_details, *attachment_details])

    def _concrete_attachment_details(
        self,
        commitment: KPICommitment,
        rule: MetricRuleTemplate,
        attachment_details: list[KPIMatchDetail],
    ) -> list[KPIMatchDetail]:
        if not self._requires_concrete_attachment_display(commitment, rule):
            return []
        concrete = [
            detail for detail in attachment_details
            if detail.evidence_mode == "itemized" and detail.doc_kind in rule.primary_doc_kinds
        ]
        if not concrete and commitment.metric_name in {"发明专利", "实用新型专利"}:
            # 专利证书 OCR 失败时，允许展示验收申请附件目录中的专利单件条目，
            # 避免结果只显示摘要声明而看不到具体证据件。
            concrete = [
                detail
                for detail in attachment_details
                if detail.evidence_mode == "itemized"
                and detail.doc_kind == "验收申请"
                and any(token in (detail.excerpt or "") for token in ("专利授权证书", "专利受理通知书"))
            ]
        if not concrete:
            return []
        return sorted(
            concrete,
            key=lambda detail: (
                0 if detail.evidence_role == "primary" else 1,
                detail.source_page,
                detail.artifact_key or detail.title or detail.file_name,
                detail.source_block_id,
            ),
        )

    def _proof_attachment_details(
        self,
        commitment: KPICommitment,
        rule: MetricRuleTemplate,
        attachment_details: list[KPIMatchDetail],
    ) -> list[KPIMatchDetail]:
        if commitment.metric_name not in {
            "检测范围",
            "检测频率",
            "检测标准偏差",
            "最大测量误差",
            "实验系统",
            "技术方案",
            "工程样机",
            "示范基地",
            "培养研究生",
        }:
            return []
        primary_kinds = set(rule.primary_doc_kinds or [])
        proof = [
            detail
            for detail in attachment_details
            if detail.doc_kind in primary_kinds
            and detail.evidence_role != "derived"
            and not self._looks_like_self_eval_summary_detail(detail)
        ]
        if not proof:
            return []
        return sorted(
            proof,
            key=lambda detail: (
                0 if detail.doc_kind == "检测报告" else 1,
                0 if detail.evidence_role == "primary" else 1,
                0 if detail.evidence_mode == "itemized" else 1,
                detail.source_page,
                detail.artifact_key or detail.file_name,
            ),
        )[:8]

    def _looks_like_self_eval_summary_detail(self, detail: KPIMatchDetail) -> bool:
        title = detail.title or ""
        return "验收自评价" in title or "自评价报告" in title

    def _requires_concrete_attachment_display(
        self,
        commitment: KPICommitment,
        rule: MetricRuleTemplate,
    ) -> bool:
        return self._requires_concrete_attachment_proof(commitment, rule) and bool(rule.primary_doc_kinds)

    def _dedupe_detail_entries(self, details: list[KPIMatchDetail]) -> list[KPIMatchDetail]:
        best_by_key: dict[tuple[str, str, str], KPIMatchDetail] = {}
        ordered_keys: list[tuple[str, str, str]] = []
        for detail in details:
            detail_key = (
                detail.doc_kind,
                self._dedupe_artifact_key(detail.artifact_key or detail.title or detail.file_name or ""),
                detail.source_block_id or f"page:{detail.source_page}",
            )
            existing = best_by_key.get(detail_key)
            if existing is None:
                best_by_key[detail_key] = detail
                ordered_keys.append(detail_key)
                continue
            if self._detail_priority(detail) > self._detail_priority(existing):
                best_by_key[detail_key] = detail
        return [best_by_key[key] for key in ordered_keys]

    def _detail_priority(self, detail: KPIMatchDetail) -> tuple[int, int, float, int]:
        return (
            1 if detail.evidence_mode == "itemized" else 0,
            1 if detail.evidence_role == "primary" else 0,
            float(detail.contribution_value or 0.0),
            len(detail.excerpt or ""),
        )

    def _dedupe_matched(self, matched: list[AttachmentEvidence]) -> list[AttachmentEvidence]:
        deduped: list[AttachmentEvidence] = []
        seen_itemized: set[tuple[str, str]] = set()
        seen_summary: set[tuple[str, str, float]] = set()
        for item in matched:
            if item.evidence_mode == "itemized":
                key = (
                    item.metric_name,
                    self._dedupe_artifact_key(item.normalized_artifact_key or item.artifact_key or item.file_name),
                )
                if key in seen_itemized:
                    continue
                seen_itemized.add(key)
            else:
                summary_value = self._summary_dedupe_value(item)
                key = (
                    item.metric_name,
                    self._dedupe_artifact_key(item.normalized_artifact_key or item.artifact_key or item.file_name),
                    float(summary_value),
                )
                if key in seen_summary:
                    continue
                seen_summary.add(key)
                deduped.append(item)
                continue
            deduped.append(item)
        return deduped

    def _dedupe_artifact_key(self, value: str) -> str:
        raw = self.normalizer.normalize_artifact_key(value)
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits.startswith("20") and len(digits) >= 12:
            return digits
        return raw

    def _detail_reason(self, item: AttachmentEvidence, value: float, commitment: KPICommitment) -> str:
        parts = [item.doc_kind, f"提供 {self._format_number(value)}{commitment.target_unit}"]
        if item.evidence_role == "primary":
            parts.append("主证据")
        elif item.evidence_role == "derived":
            parts.append("派生证据")
        if item.evidence_nature == "artifact":
            parts.append("成果本体")
        elif item.evidence_nature == "proof":
            parts.append("证明材料")
        elif item.evidence_nature == "summary":
            parts.append("摘要材料")
        if item.time_label:
            parts.append(item.time_label)
        if item.caliber_label:
            parts.append(item.caliber_label)
        return "，".join(parts)

    def _detect_conflicts(
        self,
        commitment: KPICommitment,
        *,
        application_value: float,
        attachment_value: float,
        has_application: bool,
        has_attachment: bool,
    ) -> list[str]:
        flags: list[str] = []
        target = commitment.target_value
        if has_application and has_attachment:
            if commitment.comparator in {"≥", ">"} and application_value > 0 and attachment_value > 0 and attachment_value < application_value:
                flags.append("附件证明低于验收申请声明")
            if commitment.comparator in {"≤", "<"} and application_value > 0 and attachment_value > 0 and attachment_value > application_value:
                flags.append("附件证明高于验收申请声明")
        if has_application and application_value > 0 and self._decide_status(commitment, application_value) == "fulfilled" and (not has_attachment or self._decide_status(commitment, attachment_value) != "fulfilled"):
            flags.append("验收申请已报完成但附件未充分证明")
        if has_attachment and self._decide_status(commitment, attachment_value) == "fulfilled" and has_application and self._decide_status(commitment, application_value) != "fulfilled":
            flags.append("附件已达到目标但验收申请填报偏低或漏报")
        if target > 0 and has_application and has_attachment and application_value == 0 and attachment_value > 0:
            flags.append("验收申请未提取完成值但附件已有证据")
        return flags

    def _variant_compatible(self, target_variant: str, evidence_variant: str, rule: MetricRuleTemplate) -> bool:
        target_normalized = self.normalizer.normalize_metric_variant(target_variant)
        evidence_normalized = self.normalizer.normalize_metric_variant(evidence_variant)
        if target_normalized == evidence_normalized:
            return True
        if rule.metric_name == "发明专利" and "发明专利" in target_normalized and "发明专利" in evidence_normalized:
            return True
        for canonical, aliases in rule.variant_alias_groups.items():
            alias_set = {self.normalizer.normalize_metric_variant(alias) for alias in aliases + [canonical]}
            if target_normalized in alias_set and evidence_normalized in alias_set:
                return True
        if target_variant == evidence_variant:
            return True
        if target_variant in evidence_variant or evidence_variant in target_variant:
            return True
        if target_variant == "销售收入" and evidence_variant in {"营业收入", "主营业务收入"}:
            return True
        return False

    def _action_compatible(self, target_action: str, evidence_action: str, rule: MetricRuleTemplate) -> bool:
        if "/" in target_action:
            return any(self._action_compatible(part.strip(), evidence_action, rule) for part in target_action.split("/") if part.strip())
        if "/" in evidence_action:
            return any(self._action_compatible(target_action, part.strip(), rule) for part in evidence_action.split("/") if part.strip())
        if rule.allowed_actions and target_action not in rule.allowed_actions and evidence_action not in rule.allowed_actions:
            compatible_pairs = (
                ("制定", "实现"),
                ("制定", "完成"),
                ("制定", "形成"),
                ("制定", "提交"),
                ("形成", "实现"),
                ("形成", "完成"),
                ("提交", "实现"),
            )
            if (target_action, evidence_action) not in compatible_pairs:
                return False
        if rule.allowed_actions and target_action in rule.allowed_actions and evidence_action in rule.allowed_actions:
            return True
        if target_action == evidence_action:
            return True
        if target_action in evidence_action or evidence_action in target_action:
            return True
        if target_action == "申请" and evidence_action == "授权":
            return True
        if target_action == "实现" and evidence_action in {"实现", "新增"}:
            return True
        return False

    def _time_compatible(self, time_constraint: str, time_label: str) -> bool:
        if not time_label:
            return True
        if time_constraint in {"项目执行期内", "截至验收前", "验收前"}:
            return True
        if "项目期外" in time_label and time_constraint == "累计":
            # 累计类推广/社会效益证据常在验收年度形成截图或报告，年份只代表材料生成时间。
            return True
        if time_constraint == "当年":
            return "当年" in time_label
        if time_constraint == "累计":
            return "累计" in time_label
        return True

    def _caliber_compatible(self, target_caliber: str, evidence_caliber: str) -> bool:
        if not target_caliber or not evidence_caliber:
            return True
        tokens = [token.strip() for token in target_caliber.split("/") if token.strip()]
        if not tokens:
            return True
        return any(token in evidence_caliber for token in tokens)

    def _evidence_value_for_commitment(self, evidence: AttachmentEvidence, commitment: KPICommitment) -> float:
        if evidence.value is None:
            return evidence.implicit_count
        return self.normalizer.convert_value(evidence.value, evidence.unit, commitment.target_unit)

    def _summary_dedupe_value(self, item: AttachmentEvidence) -> float:
        if item.normalized_value is not None:
            return item.normalized_value
        if item.value is not None:
            normalized = self.normalizer.normalize_value(item.value, item.unit)
            return float(normalized) if normalized is not None else float(item.value)
        return float(item.implicit_count)

    @staticmethod
    def _format_number(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
