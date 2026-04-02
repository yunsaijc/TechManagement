"""项目级形式审查 Agent"""
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from src.common.models import (
    CheckResult,
    CheckStatus,
    ManualReviewItem,
    MissingAttachment,
    PolicyRuleCheck,
    ProjectAttachment,
    ProjectReviewContext,
    ProjectReviewRequest,
    ProjectReviewResult,
    ReviewResult,
)
from src.common.review_runtime import ReviewRuntime
from src.services.review.agent import ReviewAgent
from src.services.review.project_config import (
    get_attachment_review_doc_kinds,
    get_effective_policy_review_points,
    get_project_config,
    resolve_document_type,
)
from src.services.review.project_rules import ProjectRuleRegistry


class ProjectReviewAgent:
    """项目级形式审查 Agent"""

    def __init__(self, review_agent: ReviewAgent | None = None):
        self.review_agent = review_agent or ReviewAgent()
        self.attachment_review_concurrency = max(1, int(ReviewRuntime.ATTACHMENT_REVIEW_CONCURRENCY))
        self.reviewable_doc_kinds = set(get_attachment_review_doc_kinds())

    async def process(self, request: ProjectReviewRequest) -> ProjectReviewResult:
        """执行项目级形式审查"""
        context = ProjectReviewContext(
            project_info=request.project_info,
            cooperation_info=request.cooperation_info,
            attachments=request.attachments,
            external_checks=request.external_checks,
        )
        return await self.process_context(context)

    async def process_context(self, context: ProjectReviewContext) -> ProjectReviewResult:
        """基于上下文执行项目级形式审查"""
        start_time = time.time()
        project_type = context.project_info.project_type
        config = get_project_config(project_type) or {}

        attachment_results = await self._review_attachments(context.attachments)
        context.attachment_results = {attachment_id: result for attachment_id, result in attachment_results}

        project_rule_results = await self._run_project_rules(context)
        missing_attachments = self._collect_missing_attachments(project_rule_results)
        manual_review_items = self._collect_manual_review_items(context, project_rule_results)
        policy_rule_checks = self._build_policy_rule_checks(context, project_rule_results, manual_review_items)
        if not config:
            project_rule_results.append(
                CheckResult(
                    item="project_type_resolution",
                    status=CheckStatus.WARNING,
                    message=f"无法识别项目类型: {project_type}",
                    evidence={"project_type": project_type, "guide_name": context.project_info.guide_name},
                )
            )

        result = ProjectReviewResult(
            id=f"project_review_{context.project_info.project_id}_{uuid4().hex[:8]}",
            project_id=context.project_info.project_id,
            project_type=project_type,
            results=project_rule_results,
            policy_rule_checks=policy_rule_checks,
            missing_attachments=missing_attachments,
            attachment_results=[result for _, result in attachment_results],
            manual_review_items=manual_review_items,
            summary=self._generate_summary(project_rule_results, missing_attachments, manual_review_items),
            suggestions=self._generate_suggestions(project_rule_results, missing_attachments, manual_review_items),
            processing_time=time.time() - start_time,
        )
        return result

    async def _review_attachments(self, attachments: List[ProjectAttachment]) -> List[tuple[str, ReviewResult]]:
        """调用附件级审查能力"""
        semaphore = asyncio.Semaphore(self.attachment_review_concurrency)
        candidates = [
            attachment
            for attachment in attachments
            if attachment.document_type and attachment.doc_kind in self.reviewable_doc_kinds
        ]

        async def _review(attachment: ProjectAttachment) -> tuple[str, ReviewResult]:
            async with semaphore:
                file_data = self._load_file_data(attachment.file_ref)
                document_type = resolve_document_type(attachment.doc_kind, attachment.document_type)
                review_result = await self.review_agent.process(
                    file_data=file_data,
                    file_type=self._detect_file_type(attachment.file_name),
                    document_type=document_type,
                    metadata={"doc_kind": attachment.doc_kind},
                )
                return attachment.attachment_id, review_result

        if not candidates:
            return []
        return list(await asyncio.gather(*[_review(attachment) for attachment in candidates]))

    async def _run_project_rules(self, context: ProjectReviewContext) -> List[CheckResult]:
        """执行项目级规则"""
        config = get_project_config(context.project_info.project_type) or {}
        rule_names = config.get("project_rules", [])
        rules = ProjectRuleRegistry.create_chain(rule_names)

        results: List[CheckResult] = []
        for rule in rules:
            if await rule.should_run(context):
                results.append(await rule.check(context))

        attachment_failures = self._collect_attachment_failures(context)
        if attachment_failures:
            results.append(attachment_failures)

        return results

    def _collect_attachment_failures(self, context: ProjectReviewContext) -> CheckResult | None:
        """汇总附件级失败结果"""
        failures = []
        for attachment_id, result in context.attachment_results.items():
            failed_items = [item for item in result.results if item.status == CheckStatus.FAILED]
            if failed_items:
                failures.append(
                    {
                        "attachment_id": attachment_id,
                        "document_type": result.document_type,
                        "failed_items": [item.item for item in failed_items],
                    }
                )

        if not failures:
            return None

        return CheckResult(
            item="attachment_review",
            status=CheckStatus.FAILED,
            message="存在未通过的附件级审查结果",
            evidence={"failures": failures},
        )

    def _collect_missing_attachments(self, results: List[CheckResult]) -> List[MissingAttachment]:
        """从规则结果中提取缺失附件"""
        missing: List[MissingAttachment] = []
        for result in results:
            if result.item == "required_attachments" and result.status == CheckStatus.FAILED:
                for doc_kind in result.evidence.get("missing_doc_kinds", []):
                    missing.append(MissingAttachment(doc_kind=doc_kind, reason="缺少必需附件"))
            elif result.item == "conditional_attachments" and result.status == CheckStatus.FAILED:
                for item in result.evidence.get("missing_conditional_attachments", []):
                    missing.append(
                        MissingAttachment(
                            doc_kind=item.get("doc_kind", ""),
                            reason=item.get("reason", "缺少条件性附件"),
                        )
                    )
        return missing

    def _collect_manual_review_items(
        self,
        context: ProjectReviewContext,
        results: List[CheckResult],
    ) -> List[ManualReviewItem]:
        """生成待人工复核项"""
        items: List[ManualReviewItem] = []
        existing_items: set[str] = set()
        unknown_attachments = [
            attachment
            for attachment in context.attachments
            if attachment.doc_kind == "unknown_attachment"
        ]
        if unknown_attachments:
            existing_items.add("attachment_classification_uncertain")
            items.append(
                ManualReviewItem(
                    item="attachment_classification_uncertain",
                    message="存在无法可靠识别类型的附件，建议人工确认材料类别",
                    evidence={
                        "count": len(unknown_attachments),
                        "files": [attachment.file_name for attachment in unknown_attachments[:20]],
                    },
                )
            )

        for result in results:
            if result.item in {"required_attachments", "conditional_attachments"} and result.status == CheckStatus.WARNING:
                if result.item in existing_items:
                    continue
                existing_items.add(result.item)
                items.append(
                    ManualReviewItem(
                        item=result.item,
                        message=result.message,
                        evidence=result.evidence,
                    )
                )
            elif result.item == "policy_review_points_check" and result.status == CheckStatus.WARNING:
                for point in result.evidence.get("pending_review_points", []):
                    item_code = point.get("code", "policy_review_point")
                    if item_code in existing_items:
                        continue
                    existing_items.add(item_code)
                    items.append(
                        ManualReviewItem(
                            item=item_code,
                            message=point.get("requirement", "存在未自动核验的政策审查要点"),
                            evidence={
                                "automation": point.get("automation", ""),
                                "reason": point.get("reason", ""),
                            },
                        )
                    )
        return items

    def _build_policy_rule_checks(
        self,
        context: ProjectReviewContext,
        results: List[CheckResult],
        manual_review_items: List[ManualReviewItem],
    ) -> List[PolicyRuleCheck]:
        """组装 docx 逐条规则对照结果"""
        policy_points = get_effective_policy_review_points(
            context.project_info.project_type,
            context.notice_context,
        )
        if not policy_points:
            return []

        result_by_item = {result.item: result for result in results}
        manual_by_item = {item.item: item for item in manual_review_items}
        checks: List[PolicyRuleCheck] = []

        for point in policy_points:
            checks.append(
                self._build_single_policy_rule_check(
                    point=point,
                    context=context,
                    result_by_item=result_by_item,
                    manual_by_item=manual_by_item,
                )
            )

        return checks

    def _build_single_policy_rule_check(
        self,
        point: Dict[str, Any],
        context: ProjectReviewContext,
        result_by_item: Dict[str, CheckResult],
        manual_by_item: Dict[str, ManualReviewItem],
    ) -> PolicyRuleCheck:
        """构造单条政策规则对照结果"""
        code = point.get("code", "")
        requirement = point.get("requirement", "")
        automation = point.get("automation", "")
        reason = point.get("reason", "")
        metadata = self._resolve_policy_point_mapping(code)
        source_rule = metadata["source_rule"]
        doc_kind = metadata.get("doc_kind", "")
        condition_field = metadata.get("condition_field", "")

        if condition_field and not getattr(context.project_info, condition_field, False):
            return PolicyRuleCheck(
                code=code,
                requirement=requirement,
                status="not_applicable",
                source_rule=source_rule,
                matched_result_item=source_rule or None,
                evidence={"condition_field": condition_field, "condition_value": False},
                reason="当前项目未触发该条规则",
            )

        source_result = result_by_item.get(source_rule) if source_rule else None
        if source_result:
            status, evidence, resolved_reason = self._resolve_status_from_result(
                code=code,
                source_result=source_result,
                doc_kind=doc_kind,
            )
            if status:
                return PolicyRuleCheck(
                    code=code,
                    requirement=requirement,
                    status=status,
                    source_rule=source_rule,
                    matched_result_item=source_result.item,
                    evidence=evidence,
                    reason=resolved_reason,
                )

        manual_item = manual_by_item.get(code)
        if manual_item:
            manual_status = manual_item.evidence.get("automation") or automation or "manual"
            return PolicyRuleCheck(
                code=code,
                requirement=requirement,
                status=manual_status,
                source_rule=source_rule,
                matched_result_item=source_rule or None,
                evidence=manual_item.evidence,
                reason=manual_item.evidence.get("reason", manual_item.message),
            )

        if automation == "manual":
            return PolicyRuleCheck(
                code=code,
                requirement=requirement,
                status="manual",
                source_rule=source_rule,
                matched_result_item=source_rule or None,
                evidence={},
                reason=reason or "当前阶段保留人工复核",
            )

        if automation == "system_managed":
            return PolicyRuleCheck(
                code=code,
                requirement=requirement,
                status="system_managed",
                source_rule=source_rule,
                matched_result_item=source_rule or None,
                evidence={},
                reason=reason or "该限制由上游申报系统前置控制，不纳入本服务重复审查",
            )

        if automation == "requires_data":
            return PolicyRuleCheck(
                code=code,
                requirement=requirement,
                status="requires_data",
                source_rule=source_rule,
                matched_result_item=source_rule or None,
                evidence={},
                reason=reason or "当前缺少自动核验所需数据",
            )

        return PolicyRuleCheck(
            code=code,
            requirement=requirement,
            status="not_applicable",
            source_rule=source_rule,
            matched_result_item=source_rule or None,
            evidence={},
            reason="当前项目未触发该条规则或暂无可用证据",
        )

    def _resolve_status_from_result(
        self,
        code: str,
        source_result: CheckResult,
        doc_kind: str = "",
    ) -> tuple[str, Dict[str, Any], str]:
        """从项目级规则结果推导 docx 单条规则状态"""
        if source_result.item == "required_attachments":
            missing = set(source_result.evidence.get("missing_doc_kinds", []))
            if doc_kind in missing:
                return source_result.status.value, source_result.evidence, source_result.message
            if source_result.status == CheckStatus.PASSED:
                return "passed", source_result.evidence, source_result.message
            if source_result.status == CheckStatus.WARNING:
                return "warning", source_result.evidence, "附件识别不稳定，暂无法确认该条附件规则"
            return "passed", {"doc_kind": doc_kind}, "该附件规则已满足"

        if source_result.item == "conditional_attachments":
            missing_items = source_result.evidence.get("missing_conditional_attachments", [])
            missing_doc_kinds = {item.get("doc_kind", "") for item in missing_items}
            if doc_kind in missing_doc_kinds:
                evidence = next((item for item in missing_items if item.get("doc_kind") == doc_kind), source_result.evidence)
                return source_result.status.value, evidence, source_result.message
            if source_result.status == CheckStatus.PASSED:
                return "passed", source_result.evidence, source_result.message
            if source_result.status == CheckStatus.WARNING:
                return "warning", source_result.evidence, "附件识别不稳定，暂无法确认该条条件性附件规则"
            return "passed", {"doc_kind": doc_kind}, "该条件性附件规则已满足"

        if source_result.item == "external_status_check":
            if code == "duplicate_submission_check":
                duplicate_status = source_result.evidence.get("duplicate_submission_status", "")
                evidence = {
                    "duplicate_submission_status": duplicate_status,
                    **source_result.evidence,
                }
                if source_result.status == CheckStatus.WARNING:
                    return "warning", evidence, source_result.message
                return source_result.status.value, evidence, source_result.message
            return source_result.status.value, source_result.evidence, source_result.message

        if source_result.status == CheckStatus.SKIPPED:
            if code == "registered_date_limit":
                return "requires_data", source_result.evidence, source_result.message
            return "not_applicable", source_result.evidence, source_result.message

        if source_result.status == CheckStatus.WARNING and code == "registered_date_limit":
            return "requires_data", source_result.evidence, source_result.message

        return source_result.status.value, source_result.evidence, source_result.message

    def _resolve_policy_point_mapping(self, code: str) -> Dict[str, str]:
        """推导政策规则与项目级规则的映射关系"""
        mapping: Dict[str, Dict[str, str]] = {
            "registered_date_limit": {"source_rule": "registered_date_limit"},
            "funding_ratio_check": {"source_rule": "funding_ratio_check"},
            "external_status_check": {"source_rule": "external_status_check"},
            "integrity_and_credit_check": {"source_rule": "external_status_check"},
            "duplicate_submission_check": {"source_rule": "external_status_check"},
            "execution_period_limit": {"source_rule": "execution_period_limit"},
            "applicant_unit_type_check": {"source_rule": "applicant_unit_type_check"},
            "commitment_letter_required": {
                "source_rule": "required_attachments",
                "doc_kind": "commitment_letter",
            },
            "base_staff_proof_required": {
                "source_rule": "required_attachments",
                "doc_kind": "base_staff_proof",
            },
            "ethics_approval_required": {
                "source_rule": "conditional_attachments",
                "doc_kind": "ethics_approval",
                "condition_field": "has_clinical_research",
            },
            "industry_permit_required": {
                "source_rule": "conditional_attachments",
                "doc_kind": "industry_permit",
                "condition_field": "has_special_industry_requirement",
            },
            "biosafety_commitment_required": {
                "source_rule": "conditional_attachments",
                "doc_kind": "biosafety_commitment",
                "condition_field": "has_biosafety_activity",
            },
            "cooperation_agreement_required": {
                "source_rule": "conditional_attachments",
                "doc_kind": "cooperation_agreement",
                "condition_field": "has_cooperation_unit",
            },
            "recommendation_letter_required": {
                "source_rule": "conditional_attachments",
                "doc_kind": "recommendation_letter",
                "condition_field": "has_cooperation_unit",
            },
            "cooperation_region_check": {
                "source_rule": "",
                "condition_field": "has_cooperation_unit",
            },
            "platform_scope_check": {"source_rule": ""},
            "joint_application_check": {"source_rule": ""},
            "unfinished_guidance_project_check": {"source_rule": ""},
            "joint_updownstream_application_check": {"source_rule": ""},
            "shared_mechanism_check": {"source_rule": ""},
            "provincial_nsf_conflict_check": {"source_rule": ""},
            "unfinished_basic_project_check": {"source_rule": ""},
            "applicant_qualification_check": {"source_rule": ""},
            "project_leader_age_check": {"source_rule": "project_leader_age_check"},
            "active_guidance_project_leader_check": {"source_rule": ""},
            "project_count_limit_check": {"source_rule": ""},
            "enterprise_batch_limit_check": {"source_rule": ""},
            "enterprise_active_guidance_project_check": {"source_rule": ""},
            "performance_metric_count_check": {"source_rule": "performance_metric_count_check"},
            "budget_forbidden_expense_check": {"source_rule": "budget_forbidden_expense_check"},
            "leader_achievement_attachment_check": {"source_rule": ""},
            "beijing_tianjin_partner_check": {"source_rule": ""},
            "cluster_region_check": {"source_rule": ""},
            "other_policy_compliance": {"source_rule": ""},
        }
        return mapping.get(code, {"source_rule": code})

    def _generate_summary(
        self,
        results: List[CheckResult],
        missing_attachments: List[MissingAttachment],
        manual_review_items: List[ManualReviewItem],
    ) -> str:
        """生成摘要"""
        failed = sum(1 for result in results if result.status == CheckStatus.FAILED)
        warnings = sum(1 for result in results if result.status == CheckStatus.WARNING)
        if failed == 0 and warnings == 0 and not missing_attachments and not manual_review_items:
            return "项目形式审查通过"
        return (
            f"项目形式审查完成：失败 {failed} 项，警告 {warnings} 项，"
            f"缺失附件 {len(missing_attachments)} 个，人工复核 {len(manual_review_items)} 项"
        )

    def _generate_suggestions(
        self,
        results: List[CheckResult],
        missing_attachments: List[MissingAttachment],
        manual_review_items: List[ManualReviewItem],
    ) -> List[str]:
        """生成建议"""
        suggestions: List[str] = []
        if missing_attachments:
            suggestions.append("补齐缺失附件后重新提交项目级形式审查")
        if any(result.item == "attachment_review" and result.status == CheckStatus.FAILED for result in results):
            suggestions.append("修复未通过的附件级审查问题后重新提交")
        if any(result.item == "external_status_check" and result.status == CheckStatus.WARNING for result in results):
            suggestions.append("补充外部校验结果后重新提交")
        if manual_review_items:
            suggestions.append("存在无法自动判断的材料项，建议人工复核")
        return suggestions

    def _load_file_data(self, file_ref: str) -> bytes:
        """读取附件内容

        第一阶段仅支持本地路径。
        """
        path = Path(file_ref)
        if not path.exists() or not path.is_file():
            raise ValueError(f"附件不存在或不可读取: {file_ref}")
        return path.read_bytes()

    def _detect_file_type(self, file_name: str) -> str:
        """根据文件名推断文件类型"""
        suffix = Path(file_name).suffix.lower().lstrip(".")
        return suffix or "pdf"
