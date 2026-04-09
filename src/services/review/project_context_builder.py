"""项目上下文构造器"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List

from src.common.models import CooperationInfo, ProjectAttachment, ProjectIndexRow, ProjectInfo, ProjectReviewContext
from src.common.review_runtime import ReviewRuntime
from src.services.review.attachment_classifier import AttachmentClassifier
from src.services.review.project_config import resolve_document_type, resolve_project_type
from src.services.review.project_fact_resolver import ProjectFactResolver


class ProjectContextBuilder:
    """根据数据库记录和文件目录构造项目上下文"""

    CORPUS_ROOT = Path(os.getenv("REVIEW_CORPUS_ROOT", "/mnt/remote_corpus"))
    UNKNOWN_DOC_KIND = "unknown_attachment"

    def __init__(
        self,
        attachment_classifier: AttachmentClassifier | None = None,
        project_fact_resolver: ProjectFactResolver | None = None,
    ):
        self.attachment_classifier = attachment_classifier or AttachmentClassifier()
        self.project_fact_resolver = project_fact_resolver or ProjectFactResolver()
        self.classification_concurrency = max(1, int(ReviewRuntime.ATTACHMENT_CLASSIFY_CONCURRENCY))

    async def build(self, project_row: ProjectIndexRow) -> ProjectReviewContext:
        """构造项目上下文"""
        project_type = resolve_project_type(project_row.guide_name)
        attachments, scan_info, proposal_facts = await self._scan_attachments(project_row)
        classification_reliable = bool(attachments) and all(
            attachment.doc_kind != self.UNKNOWN_DOC_KIND for attachment in attachments
        )
        project_info_updates = proposal_facts.get("project_info_updates", {})

        project_info = ProjectInfo(
            project_id=project_row.project_id,
            project_type=project_type,
            project_name=project_row.project_name,
            year=project_row.year,
            guide_name=project_row.guide_name,
            applicant_unit=project_row.unit_name or project_row.applicant_unit,
            applicant_unit_type=project_info_updates.get("applicant_unit_type", ""),
            registered_date=project_info_updates.get("registered_date", ""),
            project_leader_birth_date=project_info_updates.get("project_leader_birth_date", ""),
            execution_period_years=self._calculate_execution_period(project_row.start_date, project_row.end_date),
            fiscal_funding=project_info_updates.get("fiscal_funding", 0.0),
            self_funding=project_info_updates.get("self_funding", 0.0),
            budget_line_items=project_info_updates.get("budget_line_items", []),
            performance_metric_count=project_info_updates.get("performance_metric_count", 0),
            performance_first_year_ratio=project_info_updates.get("performance_first_year_ratio"),
            performance_metric_rows=project_info_updates.get("performance_metric_rows", []),
            has_clinical_research=project_info_updates.get("has_clinical_research", False),
            has_special_industry_requirement=project_info_updates.get("has_special_industry_requirement", False),
            has_biosafety_activity=project_info_updates.get("has_biosafety_activity", False),
            has_cooperation_unit=project_info_updates.get("has_cooperation_unit", False),
        )
        cooperation_payload = proposal_facts.get("cooperation_info") or {}

        return ProjectReviewContext(
            project_index_row=project_row,
            project_info=project_info,
            cooperation_info=CooperationInfo(**cooperation_payload),
            attachments=attachments,
            attachment_classification_reliable=classification_reliable,
            scan_info=scan_info,
        )

    async def _scan_attachments(self, project_row: ProjectIndexRow) -> tuple[List[ProjectAttachment], dict, dict]:
        """扫描附件目录并生成附件列表"""
        scan_started = time.perf_counter()
        proposal_root = self.CORPUS_ROOT / str(project_row.year) / "sbs"
        proposal_dir = proposal_root / project_row.project_id
        attachments_dir = self.CORPUS_ROOT / str(project_row.year) / "sbsfj" / project_row.project_id
        proposal_file_paths = self._find_proposal_files(proposal_root, project_row.project_id, proposal_dir)
        proposal_files = [str(path) for path in proposal_file_paths]
        proposal_started = time.perf_counter()
        proposal_facts = await self.project_fact_resolver.resolve(
            proposal_file_paths,
            applicant_unit=project_row.applicant_unit,
            unit_name=project_row.unit_name,
            project_leader=project_row.project_leader,
        )
        proposal_elapsed = round(time.perf_counter() - proposal_started, 3)
        if not attachments_dir.exists() or not attachments_dir.is_dir():
            return [], {
                "proposal_dir": str(proposal_dir),
                "proposal_files": proposal_files,
                "proposal_main_file": proposal_facts.get("proposal_main_file", ""),
                "proposal_facts": proposal_facts,
                "attachments_dir": str(attachments_dir),
                "attachments_dir_exists": False,
                "attachment_files": [],
                "unknown_attachment_count": 0,
                "timings": {
                    "proposal_fact_seconds": proposal_elapsed,
                    "attachment_classification_seconds": 0.0,
                    "total_scan_seconds": round(time.perf_counter() - scan_started, 3),
                },
                "concurrency": {
                    "attachment_classify_concurrency": self.classification_concurrency,
                },
            }, proposal_facts

        attachments: List[ProjectAttachment] = []
        attachment_files = list(self._iter_files(attachments_dir))
        classify_started = time.perf_counter()
        classified, classify_perf = await self._classify_attachments(attachment_files)
        classify_elapsed = round(time.perf_counter() - classify_started, 3)
        unknown_attachment_count = 0
        attachment_debug_items = []
        for index, path in enumerate(attachment_files, start=1):
            classification = classified[str(path)]
            doc_kind = classification["doc_kind"]
            confidence = classification["confidence"]
            document_type = resolve_document_type(doc_kind) if doc_kind != self.UNKNOWN_DOC_KIND else "unknown"
            if doc_kind == self.UNKNOWN_DOC_KIND:
                unknown_attachment_count += 1
            attachments.append(
                ProjectAttachment(
                    attachment_id=f"{project_row.project_id}-att-{index}",
                    doc_kind=doc_kind,
                    file_name=path.name,
                    file_ref=str(path),
                    document_type=document_type if document_type != "unknown" else None,
                    recognition_confidence=confidence,
                    classification_source=classification["source"],
                    classification_reason=classification["reason"],
                    classification_details=classification["details"],
                )
            )
            attachment_debug_items.append(
                {
                    "attachment_id": f"{project_row.project_id}-att-{index}",
                    "file_name": path.name,
                    "file_ref": str(path),
                    "doc_kind": doc_kind,
                    "recognition_confidence": confidence,
                    "classification_source": classification["source"],
                    "classification_reason": classification["reason"],
                    "classification_details": classification["details"],
                }
            )
        return attachments, {
            "proposal_dir": str(proposal_dir),
            "proposal_files": proposal_files,
            "proposal_main_file": proposal_facts.get("proposal_main_file", ""),
            "proposal_facts": proposal_facts,
            "attachments_dir": str(attachments_dir),
            "attachments_dir_exists": True,
            "attachment_files": [str(path) for path in attachment_files],
            "attachments": attachment_debug_items,
            "unknown_attachment_count": unknown_attachment_count,
            "timings": {
                "proposal_fact_seconds": proposal_elapsed,
                "attachment_classification_seconds": classify_elapsed,
                "total_scan_seconds": round(time.perf_counter() - scan_started, 3),
            },
            "concurrency": {
                "attachment_classify_concurrency": self.classification_concurrency,
            },
            "classification_perf": classify_perf,
        }, proposal_facts

    async def _classify_attachments(self, attachment_files: List[Path]) -> tuple[dict[str, dict], dict]:
        """并发分类附件"""
        semaphore = asyncio.Semaphore(self.classification_concurrency)

        async def _classify(path: Path) -> tuple[str, dict, float]:
            async with semaphore:
                started = time.perf_counter()
                result = await self.attachment_classifier.classify(path)
                elapsed = round(time.perf_counter() - started, 3)
                return str(path), result, elapsed

        classified_items = await asyncio.gather(*[_classify(path) for path in attachment_files])
        classified = {path: payload for path, payload, _ in classified_items}
        elapsed_items = [{"file": path, "seconds": elapsed} for path, _, elapsed in classified_items]
        elapsed_sorted = sorted(elapsed_items, key=lambda item: item["seconds"], reverse=True)
        perf = {
            "attachment_count": len(attachment_files),
            "total_attachment_seconds_sum": round(sum(item["seconds"] for item in elapsed_items), 3),
            "slowest_files_top10": elapsed_sorted[:10],
        }
        return classified, perf

    def _iter_files(self, root: Path) -> Iterable[Path]:
        """遍历目录中的文件"""
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path

    def _find_proposal_files(self, proposal_root: Path, project_id: str, proposal_dir: Path) -> List[Path]:
        """定位申报书文件

        优先兼容真实结构：sbs/{project_id}.pdf|docx
        其次兼容旧目录结构：sbs/{project_id}/...
        """
        candidates: List[Path] = []
        for suffix in (".pdf", ".docx", ".doc", ".wps"):
            path = proposal_root / f"{project_id}{suffix}"
            if path.exists() and path.is_file():
                candidates.append(path)
        if candidates:
            return candidates
        if proposal_dir.exists() and proposal_dir.is_dir():
            return list(self._iter_files(proposal_dir))
        return []

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
