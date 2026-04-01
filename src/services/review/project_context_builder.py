"""项目上下文构造器"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List

from src.common.models import ProjectAttachment, ProjectIndexRow, ProjectInfo, ProjectReviewContext
from src.services.review.project_config import resolve_document_type, resolve_project_type


class ProjectContextBuilder:
    """根据数据库记录和文件目录构造项目上下文"""

    CORPUS_ROOT = Path(os.getenv("REVIEW_CORPUS_ROOT", "/mnt/remote_corpus"))
    UNKNOWN_DOC_KIND = "unknown_attachment"
    KEYWORD_RULES = [
        ("承诺书", "commitment_letter"),
        ("伦理", "ethics_approval"),
        ("合作协议", "cooperation_agreement"),
        ("协议", "cooperation_agreement"),
        ("推荐函", "recommendation_letter"),
        ("检索", "retrieval_report"),
        ("专利", "patent_certificate"),
        ("主要完成人", "contributor_form"),
        ("完成人情况", "contributor_form"),
        ("证书", "award_certificate"),
        ("许可", "industry_permit"),
        ("生物安全", "biosafety_commitment"),
        ("固定人员", "base_staff_proof"),
    ]

    def build(self, project_row: ProjectIndexRow) -> ProjectReviewContext:
        """构造项目上下文"""
        project_type = resolve_project_type(project_row.guide_name)
        attachments, scan_info = self._scan_attachments(project_row)
        classification_reliable = bool(attachments) and all(
            attachment.doc_kind != self.UNKNOWN_DOC_KIND for attachment in attachments
        )

        project_info = ProjectInfo(
            project_id=project_row.project_id,
            project_type=project_type,
            project_name=project_row.project_name,
            year=project_row.year,
            guide_name=project_row.guide_name,
            applicant_unit=project_row.applicant_unit or project_row.unit_name,
            execution_period_years=self._calculate_execution_period(project_row.start_date, project_row.end_date),
        )

        return ProjectReviewContext(
            project_index_row=project_row,
            project_info=project_info,
            attachments=attachments,
            attachment_classification_reliable=classification_reliable,
            scan_info=scan_info,
        )

    def _scan_attachments(self, project_row: ProjectIndexRow) -> tuple[List[ProjectAttachment], dict]:
        """扫描附件目录并生成附件列表"""
        proposal_dir = self.CORPUS_ROOT / str(project_row.year) / "sbs" / project_row.project_id
        attachments_dir = self.CORPUS_ROOT / str(project_row.year) / "sbsfj" / project_row.project_id
        proposal_files = [str(path) for path in self._iter_files(proposal_dir)] if proposal_dir.exists() and proposal_dir.is_dir() else []
        if not attachments_dir.exists() or not attachments_dir.is_dir():
            return [], {
                "proposal_dir": str(proposal_dir),
                "proposal_files": proposal_files,
                "attachments_dir": str(attachments_dir),
                "attachments_dir_exists": False,
                "attachment_files": [],
                "unknown_attachment_count": 0,
            }

        attachments: List[ProjectAttachment] = []
        attachment_files = list(self._iter_files(attachments_dir))
        unknown_attachment_count = 0
        for index, path in enumerate(attachment_files, start=1):
            doc_kind, confidence = self._classify_attachment(path.name)
            if doc_kind == self.UNKNOWN_DOC_KIND:
                unknown_attachment_count += 1
            attachments.append(
                ProjectAttachment(
                    attachment_id=f"{project_row.project_id}-att-{index}",
                    doc_kind=doc_kind,
                    file_name=path.name,
                    file_ref=str(path),
                    document_type=resolve_document_type(doc_kind) if doc_kind != self.UNKNOWN_DOC_KIND else None,
                    recognition_confidence=confidence,
                )
            )
        return attachments, {
            "proposal_dir": str(proposal_dir),
            "proposal_files": proposal_files,
            "attachments_dir": str(attachments_dir),
            "attachments_dir_exists": True,
            "attachment_files": [str(path) for path in attachment_files],
            "unknown_attachment_count": unknown_attachment_count,
        }

    def _iter_files(self, root: Path) -> Iterable[Path]:
        """遍历目录中的文件"""
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path

    def _classify_attachment(self, file_name: str) -> tuple[str, float]:
        """根据文件名进行保守归类"""
        normalized = self._normalize_name(file_name)
        if not normalized:
            return self.UNKNOWN_DOC_KIND, 0.0
        for keyword, doc_kind in self.KEYWORD_RULES:
            if keyword in normalized:
                return doc_kind, 0.95
        return self.UNKNOWN_DOC_KIND, 0.0

    def _normalize_name(self, file_name: str) -> str:
        """归一化文件名，过滤明显无意义字符"""
        stem = Path(file_name).stem
        text = re.sub(r"[\s_\-.()]+", "", stem)
        if not text:
            return ""
        # 仅当文件名包含可读中文或字母数字时才尝试匹配
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
            return ""
        return text

    def _calculate_execution_period(self, start_date: str, end_date: str) -> float:
        """根据起止时间估算执行期（年）"""
        start = self._parse_date(start_date)
        end = self._parse_date(end_date)
        if not start or not end or end <= start:
            return 0.0
        return round((end - start).days / 365.0, 2)

    def _parse_date(self, value: str) -> date | None:
        """解析日期"""
        if not value:
            return None
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None
