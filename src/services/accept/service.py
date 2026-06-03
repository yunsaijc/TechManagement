"""科技项目结题验收自动核验服务。"""
from __future__ import annotations

from pathlib import Path
from collections import OrderedDict
import json
import re

from pydantic import BaseModel, Field

from src.services.accept.advisors import AcceptanceAdvisoryEngine
from src.services.accept.evidence import AttachmentEvidenceExtractor
from src.services.accept.kpi import KPIExtractor
from src.services.accept.models import AcceptanceCheckResult, KPICommitment, ParsedAcceptanceDocument
from src.services.accept.normalizer import EvidenceNormalizer
from src.services.accept.parser import AcceptanceDocumentParser
from src.services.accept.reasoner import AcceptanceReasoner


class AcceptanceAttachmentInput(BaseModel):
    file_name: str
    file_type: str
    file_data: bytes


class AcceptanceAttachmentTextInput(BaseModel):
    file_name: str
    text: str
    file_type: str = "text"


class AcceptanceService:
    """结题验收 KPI 履约核验服务。"""

    EVIDENCE_CACHE_VERSION = "v10-acceptance-attachment-catalog-patent-fallback"

    def __init__(self, *, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir
        self.parser = AcceptanceDocumentParser(cache_dir=cache_dir)
        self.kpi_extractor = KPIExtractor()
        self.advisory_engine = AcceptanceAdvisoryEngine()
        self.evidence_extractor = AttachmentEvidenceExtractor(advisory_engine=self.advisory_engine)
        self.evidence_normalizer = EvidenceNormalizer()
        self.reasoner = AcceptanceReasoner(normalizer=self.evidence_normalizer)
        self._evidence_cache_dir = (cache_dir / "evidence") if cache_dir else None
        if self._evidence_cache_dir:
            self._evidence_cache_dir.mkdir(parents=True, exist_ok=True)

    async def check_from_files(
        self,
        *,
        project_id: str,
        taskbook_file: bytes,
        taskbook_file_type: str,
        attachments: list[AcceptanceAttachmentInput] | None = None,
        taskbook_file_name: str = "taskbook",
    ) -> AcceptanceCheckResult:
        taskbook = await self.parser.parse_bytes(
            file_data=taskbook_file,
            file_type=taskbook_file_type,
            file_name=taskbook_file_name,
        )
        parsed_attachments: list[ParsedAcceptanceDocument] = []
        for attachment in attachments or []:
            parsed_attachments.append(
                await self.parser.parse_bytes(
                    file_data=attachment.file_data,
                    file_type=attachment.file_type,
                    file_name=attachment.file_name,
                )
            )
        return self._check(project_id=project_id, taskbook=taskbook, attachments=parsed_attachments)

    async def check_from_text(
        self,
        *,
        project_id: str,
        taskbook_text: str,
        attachments: list[AcceptanceAttachmentTextInput] | None = None,
        taskbook_file_name: str = "taskbook.txt",
    ) -> AcceptanceCheckResult:
        taskbook = self.parser.parse_text(text=taskbook_text, file_name=taskbook_file_name)
        parsed_attachments = [
            self.parser.parse_text(text=item.text, file_name=item.file_name, file_type=item.file_type)
            for item in (attachments or [])
        ]
        return self._check(project_id=project_id, taskbook=taskbook, attachments=parsed_attachments)

    def _check(
        self,
        *,
        project_id: str,
        taskbook: ParsedAcceptanceDocument,
        attachments: list[ParsedAcceptanceDocument],
    ) -> AcceptanceCheckResult:
        commitments = self.kpi_extractor.extract(taskbook)
        for attachment in attachments:
            if self.evidence_extractor._classify_doc_kind(attachment) != "验收申请":
                continue
            supplemental = self.kpi_extractor.extract_declared_targets(attachment)
            for item in supplemental:
                existing_index = next(
                    (index for index, existing in enumerate(commitments) if existing.metric_name == item.metric_name),
                    None,
                )
                if existing_index is None:
                    commitments.append(item)
                    continue
                existing = commitments[existing_index]
                if (
                    self._normalize_unit(existing.target_unit) == self._normalize_unit(item.target_unit)
                    and item.target_value > existing.target_value
                    and "验收申请表任务书约定目标" in item.source_section
                ):
                    commitments[existing_index] = item
            break
        commitments = self._merge_commitments(commitments)
        project_period = self._extract_project_period(taskbook)
        evidence_items = []
        for attachment in attachments:
            if self.evidence_extractor.should_skip_attachment(attachment):
                continue
            evidence_items.extend(self._extract_evidence_cached(attachment))
        evidence_items = self.evidence_normalizer.normalize(evidence_items)
        evidence_items = self._apply_project_period_labels(evidence_items, project_period)
        result = self.reasoner.check(
            project_id=project_id,
            commitments=commitments,
            evidence_items=evidence_items,
        )
        if result.partial_commitments == 0 and result.missing_commitments == 0 and result.total_commitments > 0:
            result.warnings.extend(
                self._build_supplemental_metric_notes(commitments, evidence_items)
            )
        else:
            result.warnings.extend(self._build_unmatched_metric_warnings(commitments, evidence_items))
        return result

    def check_from_documents(
        self,
        *,
        project_id: str,
        taskbook: ParsedAcceptanceDocument,
        attachments: list[ParsedAcceptanceDocument],
    ) -> AcceptanceCheckResult:
        """直接基于已解析文档执行核验。"""
        return self._check(project_id=project_id, taskbook=taskbook, attachments=attachments)

    def extract_evidence(self, document: ParsedAcceptanceDocument) -> list:
        """对外暴露带缓存的证据抽取，供批处理/调试链路复用。"""
        return self._extract_evidence_cached(document)

    def _extract_evidence_cached(self, document: ParsedAcceptanceDocument) -> list:
        cache_path = self._evidence_cache_path(document)
        if cache_path and cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    from src.services.accept.models import AttachmentEvidence

                    return [AttachmentEvidence.model_validate(item) for item in payload]
            except Exception:
                pass
        items = self.evidence_extractor.extract(document)
        if cache_path:
            try:
                cache_path.write_text(
                    json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass
        return items

    def _evidence_cache_path(self, document: ParsedAcceptanceDocument) -> Path | None:
        if not self._evidence_cache_dir:
            return None
        text = document.text or "\n".join(document.lines)
        if not text:
            return None
        import hashlib

        digest = hashlib.sha1()
        digest.update(self.EVIDENCE_CACHE_VERSION.encode("utf-8"))
        digest.update(b"\0")
        digest.update((document.file_type or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update((document.file_name or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(text[:50000].encode("utf-8", errors="ignore"))
        return self._evidence_cache_dir / f"{digest.hexdigest()}.json"

    def _merge_commitments(self, commitments: list[KPICommitment]) -> list[KPICommitment]:
        grouped: OrderedDict[tuple[str, str, str, str], list[KPICommitment]] = OrderedDict()
        for item in commitments:
            key = (
                item.metric_name,
                item.metric_category,
                self._normalize_unit(item.target_unit),
                item.aggregation,
            )
            grouped.setdefault(key, []).append(item)

        merged: list[KPICommitment] = []
        for items in grouped.values():
            first = items[0]
            if len(items) == 1:
                merged.append(first.model_copy(update={"commitment_id": f"kpi_{len(merged) + 1}"}))
                continue

            if first.aggregation == "max":
                target_value = max(item.target_value for item in items)
            elif self._should_merge_by_max(first, items):
                target_value = max(item.target_value for item in items)
            else:
                target_value = sum(item.target_value for item in items)

            source_lines = []
            seen_lines = set()
            for item in items:
                line = (item.source_line or "").strip()
                if line and line not in seen_lines:
                    seen_lines.add(line)
                    source_lines.append(line)

            keywords = []
            seen_keywords = set()
            for item in items:
                for keyword in item.keywords:
                    if keyword not in seen_keywords:
                        seen_keywords.add(keyword)
                        keywords.append(keyword)

            merged.append(
                first.model_copy(
                    update={
                        "commitment_id": f"kpi_{len(merged) + 1}",
                        "target_value": target_value,
                        "keywords": keywords,
                        "source_line": "\n".join(source_lines),
                    }
                )
            )
        return merged

    def _normalize_unit(self, unit: str) -> str:
        if unit in {"件", "项", "个"}:
            return "项"
        if unit in {"人", "名"}:
            return "名"
        return unit

    def _should_merge_by_max(self, first: KPICommitment, items: list[KPICommitment]) -> bool:
        if first.metric_layer not in {"deliverable", "talent"} and first.metric_category != "知识产权":
            return False
        sections = "\n".join((item.source_section or "") + "\n" + (item.source_line or "") for item in items)
        if any(token in sections for token in ("项目验收的考核指标", "绩效指标", "总体目标", "实施期目标")):
            return True
        return False

    def _build_supplemental_metric_notes(
        self,
        commitments: list[KPICommitment],
        evidence_items: list,
    ) -> list[str]:
        """任务书指标均已满足时，仅提示额外成果，不作为未完成项。"""
        notes: list[str] = []
        for warning in self._build_unmatched_metric_warnings(commitments, evidence_items):
            notes.append(warning.replace("非任务书指标成果：", "补充成果（非任务书考核指标）："))
        return notes

    def _build_unmatched_metric_warnings(
        self,
        commitments: list[KPICommitment],
        evidence_items: list,
    ) -> list[str]:
        committed_metrics = {item.metric_name for item in commitments}
        grouped: OrderedDict[str, dict[str, object]] = OrderedDict()
        for item in evidence_items:
            if item.metric_name in committed_metrics:
                continue
            bucket = grouped.setdefault(
                item.metric_name,
                {
                    "application_values": [],
                    "attachment_count": 0,
                    "taskbook_not_set": False,
                },
            )
            if item.doc_kind == "验收申请":
                value = item.value if item.value is not None else item.implicit_count
                if value and value > 0:
                    cast_values = bucket["application_values"]
                    assert isinstance(cast_values, list)
                    cast_values.append(float(value))
                excerpt = (item.excerpt or "") + " " + (item.title or "")
                if "任务书中未设置该指标" in excerpt or "任务书未设置该指标" in excerpt:
                    bucket["taskbook_not_set"] = True
            else:
                bucket["attachment_count"] = int(bucket["attachment_count"]) + int(item.implicit_count or 1)

        warnings: list[str] = []
        for metric_name, bucket in grouped.items():
            application_values = bucket["application_values"]
            assert isinstance(application_values, list)
            application_text = ""
            if application_values:
                application_text = f"验收申请声明 {max(application_values):g}"
            attachment_count = int(bucket["attachment_count"])
            attachment_text = f"附件命中 {attachment_count} 份" if attachment_count > 0 else ""
            status_text = "任务书未设置该指标" if bucket["taskbook_not_set"] else "任务书未抽取到该指标"
            parts = [part for part in [application_text, attachment_text, status_text] if part]
            warnings.append(f"非任务书指标成果：{metric_name}（{'；'.join(parts)}）")
        return warnings

    def _extract_project_period(self, taskbook: ParsedAcceptanceDocument) -> tuple[int | None, int | None]:
        text = "\n".join(taskbook.lines[:120])
        year_matches = re.findall(r"20\d{2}", text)
        if "项目起止年月" in text and len(year_matches) >= 2:
            return int(year_matches[0]), int(year_matches[1])
        if len(year_matches) >= 2:
            return int(year_matches[0]), int(year_matches[1])
        if len(year_matches) == 1:
            year = int(year_matches[0])
            return year, year
        return None, None

    def _apply_project_period_labels(
        self,
        evidence_items: list,
        project_period: tuple[int | None, int | None],
    ) -> list:
        start_year, end_year = project_period
        if start_year is None or end_year is None:
            return evidence_items
        updated = []
        for item in evidence_items:
            time_label = str(item.time_label or "")
            match = re.search(r"(20\d{2})", time_label)
            if match:
                year = int(match.group(1))
                if year < start_year or year > end_year:
                    extra = "项目期外"
                    new_label = f"{time_label} / {extra}" if time_label else extra
                    item = item.model_copy(update={"time_label": new_label})
            updated.append(item)
        return updated
