"""负责人及骨干成果附件一致性检查"""
from __future__ import annotations

from src.common.models import CheckResult, CheckStatus
from src.services.review.project_rules.checkers._attachment_kinds import collect_specific_doc_kinds
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class LeaderAchievementAttachmentCheckRule(BaseProjectRule):
    """检查负责人/骨干成果条目与证明附件的一致性"""

    name = "leader_achievement_attachment_check"
    description = "检查负责人及骨干成果材料是否提供对应证明附件"
    priority = 67

    TARGET_DOC_KINDS = {
        "patent_certificate",
        "award_certificate",
        "research_paper",
        "retrieval_report",
    }

    async def check(self, context):
        claimed_categories = set(context.project_info.leader_achievement_categories or [])
        evidence_lines = list(context.project_info.leader_achievement_evidence_lines or [])
        existing_doc_kinds = collect_specific_doc_kinds(context.attachments)
        matched_doc_kinds = sorted(existing_doc_kinds & self.TARGET_DOC_KINDS)

        if claimed_categories:
            missing = sorted(claimed_categories - existing_doc_kinds)
            if missing:
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.FAILED,
                    message="负责人/骨干成果已有申报描述，但缺少对应证明附件",
                    evidence={
                        "claimed_doc_kinds": sorted(claimed_categories),
                        "missing_doc_kinds": missing,
                        "matched_doc_kinds": matched_doc_kinds,
                        "evidence_lines": evidence_lines[:12],
                    },
                )
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="负责人/骨干成果证明附件与申报描述一致",
                evidence={
                    "claimed_doc_kinds": sorted(claimed_categories),
                    "matched_doc_kinds": matched_doc_kinds,
                    "evidence_lines": evidence_lines[:12],
                },
            )

        if matched_doc_kinds:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="已识别到负责人/骨干成果证明附件",
                evidence={
                    "matched_doc_kinds": matched_doc_kinds,
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.FAILED,
            message="未识别到负责人/骨干成果证明附件",
            evidence={
                "target_doc_kinds": sorted(self.TARGET_DOC_KINDS),
                "recognized_doc_kinds": sorted(existing_doc_kinds),
                "evidence_lines": evidence_lines[:12],
            },
        )
