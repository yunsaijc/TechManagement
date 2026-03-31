"""项目级形式审查 Agent"""
import time
from pathlib import Path
from typing import List

from src.common.models import (
    CheckResult,
    CheckStatus,
    MissingAttachment,
    ProjectAttachment,
    ProjectReviewContext,
    ProjectReviewRequest,
    ProjectReviewResult,
    ReviewResult,
)
from src.services.review.agent import ReviewAgent
from src.services.review.project_config import get_project_config, resolve_document_type
from src.services.review.project_rules import ProjectRuleRegistry


class ProjectReviewAgent:
    """项目级形式审查 Agent"""

    def __init__(self, review_agent: ReviewAgent | None = None):
        self.review_agent = review_agent or ReviewAgent()

    async def process(self, request: ProjectReviewRequest) -> ProjectReviewResult:
        """执行项目级形式审查"""
        start_time = time.time()
        project_type = request.project_info.project_type
        config = get_project_config(project_type)
        if not config:
            raise ValueError(f"不支持的 project_type: {project_type}")

        context = ProjectReviewContext(
            project_info=request.project_info,
            cooperation_info=request.cooperation_info,
            attachments=request.attachments,
            external_checks=request.external_checks,
        )

        attachment_results = await self._review_attachments(request.attachments)
        context.attachment_results = {attachment_id: result for attachment_id, result in attachment_results}

        project_rule_results = await self._run_project_rules(context)
        missing_attachments = self._collect_missing_attachments(project_rule_results)

        result = ProjectReviewResult(
            id=f"project_review_{int(time.time() * 1000)}",
            project_id=request.project_info.project_id,
            project_type=project_type,
            results=project_rule_results,
            missing_attachments=missing_attachments,
            attachment_results=[result for _, result in attachment_results],
            summary=self._generate_summary(project_rule_results, missing_attachments),
            suggestions=self._generate_suggestions(project_rule_results, missing_attachments),
            processing_time=time.time() - start_time,
        )
        return result

    async def _review_attachments(self, attachments: List[ProjectAttachment]) -> List[tuple[str, ReviewResult]]:
        """调用附件级审查能力"""
        results: List[tuple[str, ReviewResult]] = []
        for attachment in attachments:
            file_data = self._load_file_data(attachment.file_ref)
            document_type = resolve_document_type(attachment.doc_kind, attachment.document_type)
            review_result = await self.review_agent.process(
                file_data=file_data,
                file_type=self._detect_file_type(attachment.file_name),
                document_type=document_type,
                metadata={"doc_kind": attachment.doc_kind},
            )
            results.append((attachment.attachment_id, review_result))
        return results

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
            if result.item == "required_attachments":
                for doc_kind in result.evidence.get("missing_doc_kinds", []):
                    missing.append(MissingAttachment(doc_kind=doc_kind, reason="缺少必需附件"))
            elif result.item == "conditional_attachments":
                for item in result.evidence.get("missing_conditional_attachments", []):
                    missing.append(
                        MissingAttachment(
                            doc_kind=item.get("doc_kind", ""),
                            reason=item.get("reason", "缺少条件性附件"),
                        )
                    )
        return missing

    def _generate_summary(self, results: List[CheckResult], missing_attachments: List[MissingAttachment]) -> str:
        """生成摘要"""
        failed = sum(1 for result in results if result.status == CheckStatus.FAILED)
        warnings = sum(1 for result in results if result.status == CheckStatus.WARNING)
        if failed == 0 and not missing_attachments:
            return "项目形式审查通过"
        return f"项目形式审查完成：失败 {failed} 项，警告 {warnings} 项，缺失附件 {len(missing_attachments)} 个"

    def _generate_suggestions(self, results: List[CheckResult], missing_attachments: List[MissingAttachment]) -> List[str]:
        """生成建议"""
        suggestions: List[str] = []
        if missing_attachments:
            suggestions.append("补齐缺失附件后重新提交项目级形式审查")
        if any(result.item == "attachment_review" and result.status == CheckStatus.FAILED for result in results):
            suggestions.append("修复未通过的附件级审查问题后重新提交")
        if any(result.item == "external_status_check" and result.status == CheckStatus.WARNING for result in results):
            suggestions.append("补充外部校验结果后重新提交")
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
