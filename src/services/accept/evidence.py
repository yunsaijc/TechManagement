"""附件证据抽取与归类。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.accept.advisors import AcceptanceAdvisoryEngine, EvidenceAdvisory
from src.services.accept.kpi import (
    DISJUNCTIVE_SCIENCE_REPORT_PATTERN,
    METRIC_SPECS,
    SCIENCE_POPULARIZATION_METRIC_NAMES,
    SCIENCE_REPORT_DISJUNCTIVE_VARIANT,
    MetricSpec,
)
from src.services.accept.models import AttachmentEvidence, ParsedAcceptanceBlock, ParsedAcceptanceDocument


DOC_KIND_RULES = (
    ("验收申请", ("验收申请表", "科技计划项目验收申请表", "项目验收申请表", "验收申请书", "项目验收申请", "验收申请")),
    ("任务书", ("项目任务书", "科技计划项目任务书", "重点研发计划项目任务书", "项目合同书")),
    ("专利证书", ("专利证书", "专利授权", "专利申请受理", "专利申请受理通知书", "国家知识产权局")),
    ("科技报告", ("验收自评价报告", "自评价报告", "研究报告", "工作总结", "试验总结", "应用证明", "报告名称", "科技报告")),
    ("学位论文", ("硕士研究生毕业证书", "博士研究生毕业证书", "毕业证书", "学位证书", "硕士学位论文", "博士学位论文", "学位论文", "MASTER'S DISSERTATION", "MASTER’S DISSERTATION")),
    ("论文", ("论文", "期刊", "录用通知", "学报")),
    ("软件著作权", ("软件著作权", "计算机软件著作权", "登记号")),
    ("审计报告", ("审计报告", "专项审计", "会计师事务所")),
    ("技术合同", ("合同", "协议")),
    ("发票", ("发票", "增值税专用发票", "税额")),
    ("检测报告", ("检测报告", "检验报告")),
)

PATENT_TYPE_PATTERNS = (
    ("发明专利", ("发明专利",)),
    ("实用新型专利", ("实用新型",)),
)

FINANCE_METRIC_PATTERNS = (
    ("新增销售收入", ("新增销售收入", "新增销售额", "营业收入", "销售收入", "主营业务收入")),
    ("新增利税", ("新增利税", "新增利润", "利润总额", "净利润", "税收")),
)

FINANCE_FIELD_PATTERNS = {
    "新增销售收入": (
        re.compile(r"(?:实际)?新增销售(?:收入|额)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(亿元|万元|元)"),
        re.compile(r"(?:营业收入|销售收入|主营业务收入)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(亿元|万元|元)"),
        re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|万元|元)[^。\n；;]{0,12}(?:新增销售(?:收入|额)|营业收入|销售收入|主营业务收入)"),
    ),
    "新增利税": (
        re.compile(r"(?:实际)?新增利税[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(亿元|万元|元)"),
        re.compile(r"(?:新增利润|利润总额|净利润|税收)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(亿元|万元|元)"),
        re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|万元|元)[^。\n；;]{0,12}(?:新增利税|新增利润|利润总额|净利润|税收)"),
    ),
}

TITLE_CLEAN_PATTERN = re.compile(r"\s+")
YEAR_PATTERN = re.compile(r"(20\d{2})\s*年")
PATENT_NO_PATTERN = re.compile(r"(?:申请号|专利号|授权公告号|公开号)[:：]?\s*([A-Z0-9.\-]+)")
PATENT_PRIMARY_NO_PATTERN = re.compile(r"(?:申请号|专利号)[:：]?\s*([A-Z0-9.\-]+)")
PATENT_SECONDARY_NO_PATTERN = re.compile(r"(?:授权公告号|公开号)[:：]?\s*([A-Z0-9.\-]+)")
PATENT_FALLBACK_NO_PATTERN = re.compile(r"\b(?:CN\s*\d{6,}(?:\.\d+)?\s*[A-Z]?|ZL\s*20\d{2}\s*\d[\d\s.]*)\b", re.IGNORECASE)
SOFT_REG_PATTERN = re.compile(r"(?:登记号|证书号)[:：]?\s*([A-Z0-9.\-]+)")
PAGE_LEADER_PATTERN = re.compile(r"\.{3,}|…{2,}")
TITLE_PREFIX_PATTERN = re.compile(r"^(?:项目名称|题目|名称)[:：]\s*(.+)$")
GENERIC_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
DOI_PATTERN = re.compile(r"\bdoi\b[:\s]", re.IGNORECASE)
PATENT_TITLE_PATTERN = re.compile(r"(?:发明名称|实用新型名称|专利名称)[:：]\s*([^\n\r]{4,120})")
CHINESE_NUMBER_PATTERN = re.compile(r"([一二三四五六七八九十两]+)\s*(项|件|个|篇|份|名|人|次|场|株|种|套|册|部|座)")

JOURNAL_ISSUE_HEADER_PATTERN = re.compile(
    r"(?:第[\d０-９\s,，]+卷[\d０-９\s,，]*期|"
    r"第[\d０-９\s,，]+卷[^。\n]{0,24}?(?:第[\d０-９\s,，]+期|No\.?\s*[\d０-９]+)|"
    r"Vol\.?\s*[\d０-９]+[^。\n]{0,40}?No\.?\s*[\d０-９]+)",
    re.IGNORECASE,
)
JOURNAL_NAME_PATTERN = re.compile(r"(?:学报|期刊|光谱|光学|Journal|Acta|Spectroscopy)", re.IGNORECASE)
DISSERTATION_HEADER_PATTERN = re.compile(
    r"硕\s*士\s*学\s*位\s*论\s*文|学术学位硕士论文|专业学位硕士论文|硕士论文|MASTER['\u2019\s]*S?\s*DISSERTATION",
    re.IGNORECASE,
)
DISSERTATION_TITLE_PATTERN = re.compile(
    r"论文题目\s*([\s\S]{6,220}?)(?=\s*作者姓名|\s*学科专业|\s*指导教师|\s*硕\s*士\s*学\s*位\s*论\s*文|\s*MASTER)",
)
DISSERTATION_TITLE_LINE_PATTERN = re.compile(r"论文题目\s*([^\n]{6,200})")
APPENDIX_PAPER_LINE_PATTERN = re.compile(
    r"^\d+\s+.+?(?:学报|期刊|Journal|Acta|EI|SCI|核心)",
    re.IGNORECASE,
)
APPENDIX_ENTRY_START_PATTERN = re.compile(r"^\[\d+\]")
REFERENCE_CITATION_PATTERN = re.compile(
    r"^\[\d+\]\s*.+(?:\[J\]|\[P\]|\[D\]|(?:学报|期刊|Journal|Acta|Spectroscopy|Applied\s+Spectroscopy))",
    re.IGNORECASE,
)
APPENDIX_PAGE_FOOTER_PATTERN = re.compile(r"^-\s*\d+\s*-$")
PERSON_ROSTER_LINE_PATTERN = re.compile(
    r"^\d+\s+\S{1,8}\s+[男女]\s+\d{6,8}",
)
CHINESE_PAPER_TITLE_PREFIXES = (
    "基于",
    "一种",
    "面向",
    "关于",
    "用于",
    "研究",
    "改进",
    "开发",
    "设计",
    "建立",
    "构建",
    "多",
    "复杂",
    "代理",
)
CHINESE_PAPER_TITLE_SUFFIX_PATTERN = re.compile(r"[\u4e00-\u9fff]{6,}的研究\s*[*＊]?$")
ELSEVIER_COVER_PATTERN = re.compile(
    r"Spectrochimica\s+Acta\s+Part\s+A:\s*Molecular",
    re.IGNORECASE,
)

CHINESE_NUMERAL_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class ExtractedEvidence:
    metric_name: str
    metric_category: str
    value: float | None
    unit: str
    implicit_count: float
    action: str = ""
    subject_scope: str = ""
    time_label: str = ""
    caliber_label: str = ""
    metric_variant: str = ""
    evidence_mode: str = "summary"
    evidence_role: str = "supporting"
    evidence_nature: str = "unknown"
    artifact_key: str = ""
    artifact_title: str = ""
    confidence: float = 0.5
    excerpt: str = ""
    block_id: str = ""
    page: int = 0


class AttachmentEvidenceExtractor:
    """从验收附件中提取可核验的证据项。"""

    OCR_CLASSIFY_CHAR_LIMIT = 4000

    def __init__(self, *, advisory_engine: AcceptanceAdvisoryEngine | None = None) -> None:
        self.advisory_engine = advisory_engine or AcceptanceAdvisoryEngine()

    def _group_blocks_by_page(self, document: ParsedAcceptanceDocument) -> dict[int, list[ParsedAcceptanceBlock]]:
        grouped: dict[int, list[ParsedAcceptanceBlock]] = {}
        for block in document.blocks:
            grouped.setdefault(block.page, []).append(block)
        return grouped

    def _extract_patent_title_from_page(self, page_text: str) -> str:
        for pattern in (
            re.compile(r"(?:发明名称|专利名称|实用新型名称)[:：]\s*([^\n\r]{4,120})"),
            re.compile(r"发明创造名称[:：]\s*([^\n\r]{4,120})"),
        ):
            match = pattern.search(page_text)
            if match:
                return self._clean_title(match.group(1))
        return ""

    def extract(self, document: ParsedAcceptanceDocument) -> list[AttachmentEvidence]:
        doc_kind = self._classify_doc_kind(document)
        if doc_kind == "任务书":
            return []
        evidence_items: list[AttachmentEvidence] = []
        display_title = self.document_display_title(document)
        title = display_title or (document.lines[0] if document.lines else document.file_name)
        extracted = self._extract_by_doc_kind(document, doc_kind)
        if not extracted:
            if doc_kind == "验收申请":
                extracted = self._extract_acceptance_application_evidence(document)
            elif doc_kind == "论文":
                extracted = self._extract_generic(document, doc_kind) if document.file_type == "text" else []
            else:
                extracted = self._extract_generic(document, doc_kind)
        if not extracted:
            merged_kind, merged_items = self._extract_merged_bundle(document)
            if merged_items:
                doc_kind = merged_kind
                extracted = merged_items

        for item in extracted:
            spec = self._lookup_spec(item.metric_name)
            evidence_nature, evidence_judge_source, evidence_judge_reason = self._infer_evidence_nature(doc_kind, item)
            evidence_items.append(
                AttachmentEvidence(
                    evidence_id=f"evidence_{len(evidence_items) + 1}",
                    file_name=document.file_name,
                    doc_kind=doc_kind,
                    metric_name=item.metric_name,
                    metric_category=item.metric_category,
                    value=item.value,
                    unit=item.unit,
                    implicit_count=item.implicit_count,
                    action=item.action,
                    subject_scope=item.subject_scope,
                    time_label=item.time_label,
                    caliber_label=item.caliber_label,
                    metric_variant=item.metric_variant,
                    evidence_mode=item.evidence_mode,  # type: ignore[arg-type]
                    evidence_role=item.evidence_role,  # type: ignore[arg-type]
                    evidence_nature=evidence_nature,
                    evidence_judge_source=evidence_judge_source,  # type: ignore[arg-type]
                    evidence_judge_reason=evidence_judge_reason,
                    artifact_key=item.artifact_key,
                    artifact_title=item.artifact_title or title,
                    confidence=item.confidence,
                    title=item.artifact_title or title,
                    excerpt=item.excerpt[:240],
                    keywords=list(spec.aliases) if spec else [],
                    source_block_id=item.block_id,
                    source_page=item.page,
                )
            )
        return evidence_items

    def _infer_evidence_nature(self, doc_kind: str, item: ExtractedEvidence) -> tuple[str, str, str]:
        advisory = self.advisory_engine.advise_document_role(
            doc_kind=doc_kind,
            title=item.artifact_title,
            excerpt=item.excerpt,
            metric_name=item.metric_name,
        )
        advisory_source = self._advisory_source(advisory)
        if item.evidence_role == "catalog":
            return "catalog", "rule", "目录型子文档"
        blob = f"{item.artifact_title or ''} {item.excerpt or ''}"
        if item.evidence_role == "derived":
            if self._is_reference_citation_line(blob):
                return "reference", "rule", "派生证据且命中引文模式"
            return "summary", "rule", "派生证据默认视为摘要材料"
        if item.evidence_mode == "itemized" and item.evidence_role == "primary":
            if doc_kind in {"专利证书", "论文", "学位论文", "软件著作权"}:
                return "artifact", "rule", "主证据且文档类型为成果本体"
            if doc_kind in {"科技报告", "其他材料"} and item.metric_name in {"研究报告", "决策咨询报告", "科技报告", "技术标准"}:
                return "artifact", "rule", "主证据且命中报告类成果"
        if advisory.is_artifact_like:
            reason = advisory.rationale or "LLM/规则建议为成果本体"
            return "artifact", advisory_source, reason
        if advisory.is_summary_like:
            reason = advisory.rationale or "LLM/规则建议为摘要材料"
            return "summary", advisory_source, reason
        if item.evidence_mode == "summary":
            if doc_kind in {"审计报告", "检测报告", "技术合同", "发票"}:
                return "proof", "rule", "摘要型证明材料"
            return "summary", "rule", "摘要型描述材料"
        if item.evidence_role == "primary":
            if doc_kind in {"专利证书", "论文", "学位论文", "软件著作权"}:
                return "artifact", "rule", "主证据且文档类型为成果本体"
            if doc_kind in {"科技报告", "其他材料"} and item.metric_name in {"研究报告", "决策咨询报告", "科技报告", "技术标准"}:
                return "artifact", "rule", "主证据且命中报告类成果"
            if doc_kind in {"审计报告", "检测报告", "技术合同", "发票"}:
                return "proof", "rule", "主证据且文档类型为证明材料"
        if item.evidence_role == "supporting":
            if doc_kind in {"审计报告", "检测报告", "技术合同", "发票"}:
                return "proof", "rule", "辅证据且文档类型为证明材料"
            return "summary", "rule", "辅证据默认视为摘要材料"
        return "unknown", "unknown", ""

    def _advisory_source(self, advisory: EvidenceAdvisory) -> str:
        rationale = (advisory.rationale or "").strip()
        if not rationale:
            return "unknown"
        has_llm = "LLM:" in rationale
        has_rule = "LLM:" not in rationale or "命中" in rationale or "目录" in rationale or "主证据" in rationale
        if has_llm and has_rule and not rationale.startswith("LLM:"):
            return "hybrid"
        if rationale.startswith("LLM:") or has_llm:
            return "llm"
        return "rule"

    def should_skip_attachment(self, document: ParsedAcceptanceDocument) -> bool:
        return self._classify_doc_kind(document) == "任务书"

    def document_display_title(self, document: ParsedAcceptanceDocument) -> str:
        lines = [self._clean_title(line) for line in document.lines[:160] if self._clean_title(line)]
        metadata_title = self._clean_title(str(document.metadata.get("title") or ""))
        if metadata_title and self._is_good_title_line(metadata_title):
            return metadata_title
        if not lines:
            return self._clean_title(document.file_name)

        if self._classify_doc_kind(document) == "专利证书":
            patent_title = self._patent_document_title(document)
            if patent_title:
                return patent_title

        if self._classify_doc_kind(document) == "学位论文":
            dissertation_title = self._dissertation_display_title(document)
            if dissertation_title:
                return dissertation_title

        if self._classify_doc_kind(document) == "论文":
            paper_title = self._paper_title(document)
            if paper_title:
                return paper_title

        project_name = self._project_name_from_lines(lines)
        report_type = self._report_type_from_lines(lines)
        if project_name and report_type:
            return f"{project_name} {report_type}".strip()

        paired = self._paired_title(lines)
        if paired:
            return paired

        candidate = self._best_title_candidate(lines)
        if candidate:
            return candidate

        if metadata_title:
            return metadata_title

        return self._clean_title(document.file_name)

    def _extract_by_doc_kind(self, document: ParsedAcceptanceDocument, doc_kind: str) -> list[ExtractedEvidence]:
        if doc_kind == "专利证书":
            return self._extract_patent_evidence(document)
        if doc_kind == "学位论文":
            return self._merge_graduate_evidence_items(
                [
                    *self._extract_merged_dissertation_evidence(document),
                    *self._extract_graduate_certificate_evidence(document),
                ]
            )
        if doc_kind == "论文":
            return self._extract_paper_evidence(document)
        if doc_kind == "软件著作权":
            return self._extract_soft_evidence(document)
        if doc_kind in {"审计报告", "技术合同", "发票"}:
            return self._extract_finance_evidence(document, doc_kind)
        if doc_kind == "科技报告":
            return self._extract_report_evidence(document)
        if doc_kind == "检测报告":
            return self._extract_inspection_report_evidence(document)
        if doc_kind == "其他材料":
            return self._extract_other_material_deliverables(document)
        return []

    def _extract_acceptance_application_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        finance_items = self._extract_finance_evidence(document, "验收申请")
        table_items = self._extract_acceptance_kpi_table_evidence(document)
        sample_items = self._extract_acceptance_sample_machine_evidence(document)
        summary_items = self._extract_acceptance_summary_evidence(document)
        catalog_items = self._extract_acceptance_attachment_catalog_evidence(document)
        found_metrics = {
            item.metric_name
            for item in [*finance_items, *table_items, *sample_items, *summary_items, *catalog_items]
        }
        generic_items = self._extract_generic(
            document,
            "验收申请",
            exclude_metric_names=found_metrics,
        )
        merged = [*finance_items, *table_items, *sample_items, *summary_items, *catalog_items, *generic_items]
        return self._dedupe_acceptance_summary_by_metric(self._dedupe_extracted(merged))

    def _extract_acceptance_summary_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        summary_markers = (
            "项目完成情况",
            "主要成果及效益",
            "取得的重要成果及效益",
            "项目完成任务目标",
            "项目任务书约定的考核指标完成情况",
            "考核指标完成情况",
            "完成情况",
        )
        metric_aliases = (
            ("科技报告", ("科技报告",)),
            ("研究报告", ("研究报告", "项目研究报告")),
            ("决策咨询报告", ("决策参考报告", "决策咨询报告")),
            ("科技论文", ("理论文章", "科技论文", "论文")),
            ("发明专利", ("发明专利",)),
            ("实用新型专利", ("实用新型专利",)),
            ("培养研究生", ("培养研究生", "硕士研究生", "博士研究生")),
            ("软件著作权", ("软件著作权", "软著")),
            ("技术标准", ("技术标准", "标准")),
            ("示范基地", ("示范基地",)),
            ("实验系统", ("实验系统",)),
            ("工程样机", ("工程样机", "样机")),
            ("技术方案", ("技术方案",)),
            ("新增销售收入", ("新增销售收入", "销售收入", "营业收入")),
            ("新增利税", ("新增利税", "利润", "税收")),
            ("田间应用防效", ("田间应用防效", "防效")),
            ("化学农药减施率", ("化学农药减施率", "减施率")),
            ("高效杀虫功能微生物", ("高效杀虫功能微生物",)),
            ("杀蚜虫新型生物制剂", ("杀蚜虫新型生物制剂",)),
            ("科普动画部数", ("视频动画", "科普动画", "科普动漫微视频", "科普影视作品", "原创科普影视作品")),
            ("公益推广科普作品", ("公益推广", "科普动画作品", "影视动画作品", "科普作品", "原创科普动画影视作品")),
            ("提供资助方科普作品", ("提供给资助方", "提供给甲方", "直接提供给资助方")),
            ("科普推广点击量", ("累计网络点击量", "推广总量", "累计总流量", "网络点击量")),
            ("开展科普活动", ("科普活动", "科学普及场次", "科普推广会议")),
        )
        items: list[ExtractedEvidence] = []
        seen: set[tuple[str, str, int]] = set()
        for block in document.blocks:
            line = block.text
            if not any(marker in line for marker in summary_markers):
                continue
            if "实际完成情况" not in line and "项目完成情况" not in line and "主要成果及效益" not in line and "完成情况" not in line and "取得的重要成果及效益" not in line:
                continue
            segment = self._actual_segment(line)
            if not segment:
                segment = line
            for metric_name, aliases in metric_aliases:
                if metric_name in {item.metric_name for item in items}:
                    continue
                if not any(alias in segment for alias in aliases):
                    continue
                spec = self._lookup_spec(metric_name)
                if spec is None:
                    continue
                key = (metric_name, block.block_id, block.page)
                if key in seen:
                    continue
                seen.add(key)
                value_unit = self._extract_value_and_unit(segment, spec)
                value = value_unit[0] if value_unit else None
                unit = value_unit[1] if value_unit else ""
                if value is None:
                    value = self._summary_metric_count_from_text(segment, metric_name, aliases)
                if value is None and metric_name in {"发明专利", "实用新型专利", "科技论文", "培养研究生", "软件著作权", "技术标准", "示范基地", "实验系统", "工程样机", "技术方案"}:
                    value = 1.0
                    unit = unit or (spec.units[0] if spec.units else "项")
                if value is None:
                    continue
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category=spec.category,
                        value=value,
                        unit=unit or (spec.units[0] if spec.units else ""),
                        implicit_count=0.0,
                        action=self._infer_generic_action(segment, metric_name),
                        time_label=self._first_match(YEAR_PATTERN, segment) or self._first_match(YEAR_PATTERN, line),
                        caliber_label=self._infer_generic_caliber(segment),
                        metric_variant=metric_name,
                        evidence_mode="summary",
                        evidence_role="supporting",
                        artifact_key=self._fallback_artifact_key(document, metric_name),
                        artifact_title=self.document_display_title(document),
                        confidence=0.7,
                        excerpt=segment[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
        return self._dedupe_extracted(items)

    def _extract_acceptance_attachment_catalog_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        metric_map = {
            "专利授权证书": "发明专利",
            "专利受理通知书": "发明专利",
            "发明专利": "发明专利",
            "专利": "发明专利",
            "科技报告": "科技报告",
            "研究报告": "研究报告",
            "决策参考报告": "决策咨询报告",
            "决策咨询报告": "决策咨询报告",
            "理论文章": "科技论文",
            "科技论文": "科技论文",
            "论文": "科技论文",
        }
        items: list[ExtractedEvidence] = []
        seen: set[tuple[str, str, int]] = set()
        for block in document.blocks:
            text = str(block.text or "")
            fields = self._parse_labeled_table_fields(text)
            attachment_name = (fields.get("附件名称") or "").strip()
            if not attachment_name:
                # 兼容 OCR/表格抽取后的三列表达：
                # [表格行7] 6 | 其他 | 专利授权证书
                plain = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
                if "|" in plain:
                    cols = [col.strip() for col in plain.split("|") if col.strip()]
                    if len(cols) >= 3 and re.fullmatch(r"\d+", cols[0]):
                        category = cols[1]
                        attachment_name = cols[2] if category in {"其他", "其它", "other", "OTHER"} else category
                if not attachment_name:
                    # 兼容无分隔符行：
                    # 6 其他 专利授权证书
                    m = re.match(r"^\d+\s+(\S+)\s+(.+)$", plain)
                    if m:
                        category = m.group(1).strip()
                        tail = m.group(2).strip()
                        attachment_name = tail if category in {"其他", "其它", "other", "OTHER"} else category
            if not attachment_name:
                continue
            metric_name = ""
            for token, candidate_metric in metric_map.items():
                if token in attachment_name:
                    metric_name = candidate_metric
                    break
            if not metric_name:
                continue
            key = (metric_name, attachment_name, block.page)
            if key in seen:
                continue
            seen.add(key)
            spec = self._lookup_spec(metric_name)
            items.append(
                ExtractedEvidence(
                    metric_name=metric_name,
                    metric_category=spec.category if spec else "成果产出",
                    value=1.0,
                    unit=(spec.units[0] if spec and spec.units else "份"),
                    implicit_count=0.0,
                    action=self._infer_generic_action(attachment_name, metric_name),
                    metric_variant=metric_name,
                    evidence_mode="itemized",
                    evidence_role="supporting",
                    artifact_key=self._fallback_artifact_key(document, f"{metric_name}:{attachment_name}"),
                    artifact_title=self.document_display_title(document),
                    confidence=0.68,
                    excerpt=block.text[:240],
                    block_id=block.block_id,
                    page=block.page,
                )
            )
        return self._dedupe_extracted(items)

    def _extract_patent_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        block = document.blocks[0] if document.blocks else None
        corpus = document.text[:12000]
        metric_name = "发明专利"
        metric_variant = "申请发明专利"
        for label, phrases in PATENT_TYPE_PATTERNS:
            if any(phrase in corpus for phrase in phrases):
                metric_name = label
                metric_variant = label
                break
        items: list[ExtractedEvidence] = []
        seen_keys: set[str] = set()
        page_groups = self._group_blocks_by_page(document)
        document_has_primary_no = bool(PATENT_PRIMARY_NO_PATTERN.search(corpus))
        for page_index, page_blocks in page_groups.items():
            page_text = "\n".join(block_item.text for block_item in page_blocks)
            numbers = [self._compact_patent_no(match.group(1)) for match in PATENT_PRIMARY_NO_PATTERN.finditer(page_text)]
            if not numbers and document_has_primary_no:
                continue
            if not numbers:
                numbers = [self._compact_patent_no(match.group(1)) for match in PATENT_SECONDARY_NO_PATTERN.finditer(page_text)]
            if not numbers:
                fallback = self._first_match(PATENT_FALLBACK_NO_PATTERN, page_text)
                if fallback:
                    numbers = [self._compact_patent_no(fallback)]
            if not numbers:
                continue
            page_title = self._extract_patent_title_from_page(page_text) or self._patent_title_from_text(document)
            year = self._first_match(YEAR_PATTERN, page_text) or self._first_match(YEAR_PATTERN, corpus)
            action = "授权" if any(word in page_text for word in ("授权", "专利证书", "公告")) else "申请"
            title_chunks = self._split_patent_title_chunks(page_text)
            for idx, patent_no_compact in enumerate(numbers):
                local_variant = metric_variant
                local_action = action
                if local_action != "授权" and patent_no_compact.startswith("ZL20"):
                    local_action = "授权"
                if metric_name == "发明专利" and local_action == "授权":
                    local_variant = "授权发明专利"
                artifact_key = patent_no_compact or self._fallback_artifact_key(document, local_variant)
                if artifact_key in seen_keys:
                    continue
                seen_keys.add(artifact_key)
                anchor_block = page_blocks[min(idx, len(page_blocks) - 1)]
                title = title_chunks[idx] if idx < len(title_chunks) else page_title
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category="知识产权",
                        value=None,
                        unit="项",
                        implicit_count=1.0,
                        action=local_action,
                        time_label=year,
                        caliber_label=local_variant,
                        metric_variant=local_variant,
                        evidence_mode="itemized",
                        evidence_role="primary",
                        artifact_key=artifact_key,
                        artifact_title=title or page_title or self.document_display_title(document),
                        confidence=0.9,
                        excerpt=self._patent_excerpt_for_index(
                            page_text,
                            idx,
                            patent_no=patent_no_compact,
                            invention_title=title or page_title,
                        ),
                        block_id=anchor_block.block_id,
                        page=anchor_block.page,
                    )
                )
        if items:
            return items
        patent_no = self._first_match(PATENT_NO_PATTERN, corpus) or self._first_match(PATENT_FALLBACK_NO_PATTERN, corpus)
        patent_no_compact = self._compact_patent_no(patent_no)
        action = "授权" if any(word in corpus for word in ("授权", "专利证书", "公告")) else "申请"
        if action != "授权" and patent_no_compact.startswith("ZL20"):
            action = "授权"
        if metric_name == "发明专利" and action == "授权":
            metric_variant = "授权发明专利"
        year = self._first_match(YEAR_PATTERN, corpus)
        patent_title = self._patent_title_from_text(document)
        return [
            ExtractedEvidence(
                metric_name=metric_name,
                metric_category="知识产权",
                value=None,
                unit="项",
                implicit_count=1.0,
                action=action,
                time_label=year,
                caliber_label=metric_variant,
                metric_variant=metric_variant,
                evidence_mode="itemized",
                evidence_role="primary",
                artifact_key=patent_no_compact or self._fallback_artifact_key(document, metric_variant),
                artifact_title=patent_title or self.document_display_title(document),
                confidence=0.9,
                excerpt=self._patent_excerpt_for_index(block.text if block else document.text, 0),
                block_id=block.block_id if block else "",
                page=block.page if block else 0,
            )
        ]

    def _extract_paper_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        if self._looks_like_dissertation_document(document):
            return []
        journal_items = self._extract_merged_journal_papers(document)
        if len(journal_items) >= 2:
            return journal_items

        if not self._looks_like_paper_evidence(document):
            return []

        block = document.blocks[0] if document.blocks else None
        title = self._paper_title(document)
        if not title:
            page_groups = self._group_blocks_by_page(document)
            for _, page_blocks in sorted(page_groups.items()):
                page_text = "\n".join(block_item.text for block_item in page_blocks)
                candidate = self._extract_paper_title_from_page(page_text)
                candidate = self._clean_title(candidate)
                if candidate and self._is_plausible_paper_title(candidate):
                    title = candidate
                    block = self._find_title_anchor_block(page_blocks, candidate)
                    break
        if not title:
            return []
        year = self._first_match(YEAR_PATTERN, document.text[:2000])
        return [
            ExtractedEvidence(
                metric_name="科技论文",
                metric_category="成果产出",
                value=None,
                unit="篇",
                implicit_count=1.0,
                action="发表",
                time_label=year,
                metric_variant="科技论文",
                evidence_mode="itemized",
                evidence_role="primary",
                artifact_key=title or self._fallback_artifact_key(document, "科技论文"),
                artifact_title=title,
                confidence=0.85,
                excerpt=self._paper_excerpt_for_title(block.text if block else document.text, title),
                block_id=block.block_id if block else "",
                page=block.page if block else 0,
            )
        ]

    def build_subdoc_candidates(
        self,
        document: ParsedAcceptanceDocument,
        evidence_items: list[AttachmentEvidence] | None = None,
    ) -> list[dict[str, object]]:
        """仅为「多专利 / 多论文 / 多学位论文」合并 PDF 生成子附件列表。"""
        _ = evidence_items
        subdocs: list[dict[str, object]] = []

        if self._looks_like_merged_patent_bundle(document):
            patent_items = self._extract_patent_evidence(document)
            for item in patent_items:
                subdocs.append(
                    {
                        "title": item.artifact_title or item.metric_name,
                        "metric_name": item.metric_name,
                        "metric_variant": item.metric_variant,
                        "artifact_key": item.artifact_key,
                        "source_page": item.page,
                        "source_block_id": item.block_id,
                        "viewer_page": item.page + 1,
                        "doc_kind": "专利证书",
                    }
                )

        if self._looks_like_merged_journal_bundle(document):
            journal_items = self._extract_merged_journal_papers(document)
            if len(journal_items) >= 2:
                for item in journal_items:
                    subdocs.append(
                        {
                            "title": item.artifact_title or item.metric_name,
                            "metric_name": item.metric_name,
                            "metric_variant": item.metric_variant,
                            "artifact_key": item.artifact_key,
                            "source_page": item.page,
                            "source_block_id": item.block_id,
                            "viewer_page": item.page + 1,
                            "doc_kind": "论文",
                        }
                    )

        if self._looks_like_dissertation_document(document):
            dissertation_segments = self._split_dissertation_segments(document)
            if len(dissertation_segments) >= 2:
                subdocs.extend(dissertation_segments)

        graduate_items = self._extract_graduate_certificate_evidence(document)
        if len(graduate_items) >= 2:
            for item in graduate_items:
                subdocs.append(
                    {
                        "title": item.artifact_title or item.metric_name,
                        "metric_name": item.metric_name,
                        "metric_variant": item.metric_variant,
                        "artifact_key": item.artifact_key,
                        "source_page": item.page,
                        "source_block_id": item.block_id,
                        "viewer_page": item.page + 1,
                        "doc_kind": "毕业证书",
                    }
                )

        return subdocs

    def _extract_merged_bundle(
        self, document: ParsedAcceptanceDocument
    ) -> tuple[str, list[ExtractedEvidence]]:
        patent_items = self._extract_patent_evidence(document)
        if len(patent_items) >= 2:
            return "专利证书", patent_items
        journal_items = self._extract_merged_journal_papers(document)
        if journal_items:
            return "论文", journal_items
        dissertation_items = self._extract_merged_dissertation_evidence(document)
        if dissertation_items:
            return "学位论文", dissertation_items
        return "", []

    def _infer_merged_segments(self, document: ParsedAcceptanceDocument) -> list[dict[str, object]]:
        segments: list[dict[str, object]] = []
        for item in self._extract_patent_evidence(document):
            segments.append(
                {
                    "title": item.artifact_title or item.metric_name,
                    "metric_name": item.metric_name,
                    "metric_variant": item.metric_variant,
                    "artifact_key": item.artifact_key,
                    "source_page": item.page,
                    "source_block_id": item.block_id,
                    "viewer_page": item.page + 1,
                    "doc_kind": "专利证书",
                }
            )
        if len(segments) >= 2:
            return segments
        segments = []
        for item in self._extract_merged_journal_papers(document):
            segments.append(
                {
                    "title": item.artifact_title or item.metric_name,
                    "metric_name": item.metric_name,
                    "metric_variant": item.metric_variant,
                    "artifact_key": item.artifact_key,
                    "source_page": item.page,
                    "source_block_id": item.block_id,
                    "viewer_page": item.page + 1,
                    "doc_kind": "论文",
                }
            )
        for segment in self._split_dissertation_segments(document):
            segments.append(segment)
        for item in self._extract_graduate_certificate_evidence(document):
            segments.append(
                {
                    "title": item.artifact_title or item.metric_name,
                    "metric_name": item.metric_name,
                    "metric_variant": item.metric_variant,
                    "artifact_key": item.artifact_key,
                    "source_page": item.page,
                    "source_block_id": item.block_id,
                    "viewer_page": item.page + 1,
                    "doc_kind": "毕业证书",
                }
            )
        return segments

    def _dissertation_display_title(self, document: ParsedAcceptanceDocument) -> str:
        segments = self._split_dissertation_segments(document)
        if not segments:
            return ""
        unique_titles = {
            self._normalize_dissertation_title_key(str(segment.get("paper_title") or ""))
            for segment in segments
            if str(segment.get("paper_title") or "").strip()
        }
        unique_titles.discard("")
        if len(segments) == 1:
            return str(segments[0].get("title") or "硕士学位论文")
        return f"硕士学位论文合集（{len(unique_titles)}篇，共{len(segments)}份扫描页）"

    def _looks_like_dissertation_block(self, text: str) -> bool:
        compact = (text or "").strip()
        if not compact:
            return False
        if DISSERTATION_HEADER_PATTERN.search(compact):
            return True
        if "论文题目" in compact and any(token in compact for token in ("作者姓名", "学科专业", "指导教师", "硕士学位")):
            return True
        return "学位论文" in compact

    def _looks_like_dissertation_document(self, document: ParsedAcceptanceDocument) -> bool:
        if self._looks_like_merged_dissertation_bundle(document):
            return True
        corpus = document.text[:12000]
        has_header = bool(DISSERTATION_HEADER_PATTERN.search(corpus))
        has_title = bool(DISSERTATION_TITLE_PATTERN.search(corpus) or DISSERTATION_TITLE_LINE_PATTERN.search(corpus))
        if has_header and has_title:
            return True
        if has_header and any(token in corpus for token in ("作者姓名", "培养院系", "专业代码名称", "指导教师")):
            return True
        if has_title and any(token in corpus for token in ("作者姓名", "学科专业", "指导教师")):
            return True
        return False

    def _is_dissertation_cover_page(self, page_text: str) -> bool:
        head = (page_text or "")[:800]
        if DISSERTATION_HEADER_PATTERN.search(head):
            return True
        return "论文题目" in head and any(token in head for token in ("作者姓名", "作者", "学科专业", "指导教师", "学位类别"))

    def _extract_dissertation_author_from_segment(self, page_text: str) -> str:
        text = page_text or ""
        for pattern in (
            re.compile(r"作者姓名\s*[:：]?\s*([^\n\r]{2,24}?)(?:\s*学科专业|\s*专业代码名称|\s*学位类别|\s*指导教师|\s*学号)"),
            re.compile(r"学生姓名\s*[:：]?\s*([^\n\r]{2,24}?)(?:\s*校内导师|\s*校外导师|\s*专业领域|\s*培养单位)"),
            re.compile(r"研究生\s*[:：]?\s*([^\n\r]{2,24}?)(?:\s*指导教师|\s*专业|\s*培养单位)"),
            re.compile(r"([^\s\n\r，,：:]{2,12})\s*作者姓名"),
        ):
            match = pattern.search(text)
            if match:
                return self._clean_person_name(match.group(1))
        return ""

    def _extract_dissertation_title_from_segment(self, page_text: str, blocks: list[ParsedAcceptanceBlock]) -> str:
        match = DISSERTATION_TITLE_PATTERN.search(page_text or "")
        if match:
            return self._clean_title(match.group(1).replace("\n", ""))
        lines = [self._clean_title(block.text) for block in blocks if self._clean_title(block.text)]
        header_seen = False
        title_parts: list[str] = []
        parts: list[str] = []
        collecting = False
        for line in lines[:24]:
            if DISSERTATION_HEADER_PATTERN.search(line):
                header_seen = True
                continue
            if header_seen:
                if any(token in line for token in ("作者姓名", "作者", "学科专业", "指导教师", "培养单位")):
                    break
                if re.search(r"^[A-Z][A-Za-z\s]{8,}$", line) or re.search(r"University|College|Institute", line, re.IGNORECASE):
                    break
                if self._is_plausible_paper_title(line):
                    title_parts.append(line)
                    continue
            if "论文题目" in line:
                remainder = line.split("论文题目", 1)[-1].strip()
                if remainder:
                    parts.append(remainder)
                collecting = True
                continue
            if collecting:
                if any(token in line for token in ("作者姓名", "作者", "学科专业", "指导教师", "学位类别", "硕士学位论文")):
                    break
                if DISSERTATION_HEADER_PATTERN.search(line) or line in {"MASTER", "S DISSERTATION", "' S DISSERTATION"}:
                    continue
                if line:
                    parts.append(line)
                continue
            if not collecting and line.startswith(("基于", "一种", "面向", "关于")):
                parts.append(line)
                collecting = True
        if title_parts:
            return self._clean_title("".join(title_parts))
        return self._clean_title("".join(parts))

    def _normalize_dissertation_title_key(self, title: str) -> str:
        compact = re.sub(r"\s+", "", self._clean_title(title))
        return compact[:80]

    def _is_reference_citation_line(self, text: str) -> bool:
        compact = self._clean_title(text)
        if not compact:
            return False
        if REFERENCE_CITATION_PATTERN.match(compact):
            return True
        if APPENDIX_ENTRY_START_PATTERN.match(compact) and re.search(
            r"\[J\]|\[P\]|\[D\]|(?:学报|期刊|Journal|Acta|Spectroscopy|Applied\s+Spectroscopy|\d{4}\s*[,，]\s*\d+)",
            compact,
            re.IGNORECASE,
        ):
            return True
        return False

    def _is_reference_bibliography_page(self, page_text: str) -> bool:
        head = (page_text or "")[:1000]
        if "参考文献" in head:
            return True
        citation_hits = len(
            re.findall(
                r"\[\d+\][^\n]{8,}(?:\[J\]|\[D\]|\[P\]|学报|期刊|Journal|Spectroscopy)",
                page_text or "",
                re.IGNORECASE,
            )
        )
        return citation_hits >= 3

    def _page_has_publishable_paper_content(self, page_text: str) -> bool:
        if self._is_reference_bibliography_page(page_text):
            return False
        lines = [self._clean_title(line) for line in (page_text or "").splitlines() if self._clean_title(line)]
        if not lines:
            return False
        if self._looks_like_paper_document(lines):
            return True
        head = (page_text or "")[:1500]
        if self._is_new_journal_paper_page(head):
            return True
        if re.search(r"research\s+article|RESEARCH\s+ARTICLE", head, re.IGNORECASE):
            return True
        if ("摘" in head and "要" in head) and JOURNAL_NAME_PATTERN.search(head):
            return True
        return False

    def _extract_paper_start_title(self, page_blocks: list[ParsedAcceptanceBlock], page_text: str) -> str:
        cover_title = self._extract_journal_cover_title(page_blocks, page_text)
        if cover_title:
            return cover_title
        lines = [self._clean_title(block.text) for block in page_blocks if self._clean_title(block.text)]
        for idx, line in enumerate(lines[:20]):
            if self._is_chinese_paper_title_line(line, lines, idx):
                return line
        titled = self._extract_paper_title_from_page(page_text)
        if titled and self._is_plausible_paper_title(titled):
            return titled
        for idx, line in enumerate(lines[:28]):
            score = self._paper_title_score(lines, idx, line)
            if score >= 5 and self._is_plausible_paper_title(line):
                return line
        return ""

    def _extract_journal_cover_title(
        self, page_blocks: list[ParsedAcceptanceBlock], page_text: str
    ) -> str:
        lines = [self._clean_title(block.text) for block in page_blocks if self._clean_title(block.text)]
        head = "\n".join(lines[:18])
        if ELSEVIER_COVER_PATTERN.search(head):
            for line in lines[:30]:
                lower = line.lower()
                if len(line) < 28:
                    continue
                if re.match(r"^[A-Z][a-z]", line) and any(
                    token in lower
                    for token in ("brown tide", "fluorescence", "algae", "spectromet", "prediction", "using ")
                ):
                    return line
        if self._is_applied_spectroscopy_cover(head[:1200]):
            for line in lines[:22]:
                if re.search(r"Based on|Prediction", line, re.IGNORECASE) and len(line) >= 30:
                    return line
        merged = self._extract_chinese_journal_cover_title(page_blocks)
        if merged:
            return merged
        for idx, line in enumerate(lines[:16]):
            if self._is_chinese_journal_title_candidate(line, lines, idx):
                return line
        for idx, line in enumerate(lines[:18]):
            score = self._paper_title_score(lines, idx, line)
            if score >= 6 and self._is_plausible_paper_title(line):
                return line
        return ""

    def _extract_chinese_journal_cover_title(self, page_blocks: list[ParsedAcceptanceBlock]) -> str:
        lines = [self._clean_title(block.text) for block in page_blocks if self._clean_title(block.text)]
        parts: list[str] = []
        collecting = False
        for idx, line in enumerate(lines[:16]):
            if JOURNAL_ISSUE_HEADER_PATTERN.search(line) or (
                len(line) < 36 and re.search(r"研究论文|光学学报|光谱分析", line)
            ):
                continue
            if not collecting and self._is_chinese_journal_title_candidate(line, lines, idx):
                parts = [line]
                collecting = True
                continue
            if collecting:
                if any(token in line for token in ("摘要", "关键词", "中图分类号", "燕山大学", "摘 要")):
                    break
                if self._looks_like_chinese_author_line(line) or "大学" in line or "学院" in line:
                    break
                if len(line) <= 42 and len(re.findall(r"[\u4e00-\u9fff]", line)) >= 4:
                    parts.append(line)
                    continue
                break
        return self._clean_title("".join(parts))

    def _split_dissertation_segments(self, document: ParsedAcceptanceDocument) -> list[dict[str, object]]:
        if not self._looks_like_dissertation_document(document):
            return []
        segments: list[dict[str, object]] = []
        page_groups = self._group_blocks_by_page(document)
        for page_index in sorted(page_groups):
            page_blocks = page_groups[page_index]
            page_text = "\n".join(block.text for block in page_blocks)
            if not self._is_dissertation_cover_page(page_text):
                continue
            title = self._extract_dissertation_title_from_segment(page_text, page_blocks)
            if not title or len(title) < 8:
                continue
            if any(token in title for token in ("作者姓名", "学科专业", "指导教师")):
                continue
            author = self._extract_dissertation_author_from_segment(page_text)
            anchor_block = page_blocks[0]
            display_title = f"硕士学位论文 - {title}"
            if author:
                display_title = f"{display_title}（{author}）"
            segments.append(
                {
                    "title": display_title,
                    "metric_name": "培养研究生",
                    "metric_variant": "",
                    "artifact_key": f"{self._normalize_dissertation_title_key(title)}:{author}:{page_index}",
                    "source_page": page_index,
                    "source_block_id": anchor_block.block_id,
                    "viewer_page": page_index + 1,
                    "doc_kind": "学位论文",
                    "author": author,
                    "paper_title": title,
                }
            )
        return segments

    def _extract_merged_dissertation_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        if not self._looks_like_dissertation_document(document):
            return []
        items: list[ExtractedEvidence] = []
        seen_keys: set[str] = set()
        for segment in self._split_dissertation_segments(document):
            title = str(segment.get("paper_title") or "")
            title_key = self._normalize_dissertation_title_key(title)
            author = str(segment.get("author") or "")
            page_index = int(segment.get("source_page") or 0)
            artifact_key = f"page:{page_index}:{author or title_key}"
            if not title_key or artifact_key in seen_keys:
                continue
            seen_keys.add(artifact_key)
            page_blocks = self._group_blocks_by_page(document).get(page_index, [])
            page_text = "\n".join(block.text for block in page_blocks)
            anchor_block = page_blocks[0] if page_blocks else None
            year = self._first_match(YEAR_PATTERN, page_text) or self._first_match(YEAR_PATTERN, document.text[:4000])
            items.append(
                ExtractedEvidence(
                    metric_name="培养研究生",
                    metric_category="人才培养",
                    value=None,
                    unit="名",
                    implicit_count=1.0,
                    action="培养",
                    time_label=year,
                    metric_variant="培养研究生",
                    evidence_mode="itemized",
                    evidence_role="primary",
                    artifact_key=artifact_key,
                    artifact_title=str(segment.get("title") or title),
                    confidence=0.9,
                    excerpt=self._paper_excerpt_for_title(page_text, title),
                    block_id=anchor_block.block_id if anchor_block else "",
                    page=page_index,
                )
            )
        return items

    def _extract_graduate_certificate_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        if not self._looks_like_graduate_certificate_document(document):
            return []
        items: list[ExtractedEvidence] = []
        seen_keys: set[str] = set()
        page_groups = self._group_blocks_by_page(document)
        for page_index, page_blocks in sorted(page_groups.items()):
            page_text = "\n".join(block.text for block in page_blocks)
            if not self._is_graduate_certificate_page(page_text):
                continue
            student = self._extract_graduate_student_name(page_text)
            major = self._extract_graduate_major(page_text)
            year = self._first_match(YEAR_PATTERN, page_text)
            artifact_key = f"graduate:{student or major}:{year}:{page_index}"
            if artifact_key in seen_keys:
                continue
            seen_keys.add(artifact_key)
            title = "硕士研究生毕业证书"
            if student:
                title = f"{title} - {student}"
            if major:
                title = f"{title}（{major}）"
            anchor_block = page_blocks[0] if page_blocks else None
            items.append(
                ExtractedEvidence(
                    metric_name="培养研究生",
                    metric_category="人才培养",
                    value=None,
                    unit="名",
                    implicit_count=1.0,
                    action="培养",
                    time_label=year,
                    metric_variant="培养研究生",
                    evidence_mode="itemized",
                    evidence_role="primary",
                    artifact_key=artifact_key,
                    artifact_title=title,
                    confidence=0.88,
                    excerpt=page_text[:240],
                    block_id=anchor_block.block_id if anchor_block else "",
                    page=page_index,
                )
            )
        items.extend(self._extract_graduate_certificate_scan_fallback(document, page_groups, seen_keys))
        return items

    def _merge_graduate_evidence_items(self, items: list[ExtractedEvidence]) -> list[ExtractedEvidence]:
        merged: list[ExtractedEvidence] = []
        seen_people: list[str] = []
        for item in sorted(items, key=lambda entry: (0 if "毕业证书" in entry.artifact_title else 1, entry.page)):
            person = self._graduate_person_key(item.artifact_title)
            if person and any(self._is_similar_chinese_name(person, seen) for seen in seen_people):
                continue
            if person:
                seen_people.append(person)
            merged.append(item)
        return self._dedupe_extracted(sorted(merged, key=lambda entry: entry.page))

    def _graduate_person_key(self, title: str) -> str:
        match = re.search(r"[（(]([\u4e00-\u9fff]{2,6})[）)]", title or "")
        if match:
            return match.group(1)
        match = re.search(r"(?:证书|扫描页)\s*-\s*([\u4e00-\u9fff]{2,6})", title or "")
        if match:
            return match.group(1)
        return ""

    def _is_similar_chinese_name(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        if abs(len(left) - len(right)) > 1:
            return False
        common = sum(1 for char in left if char in right)
        return common >= min(len(left), len(right)) - 1

    def _looks_like_graduate_certificate_document(self, document: ParsedAcceptanceDocument) -> bool:
        head = document.text[:3000]
        return "毕业证书" in head and any(token in head for token in ("硕士研究生", "博士研究生", "研究生"))

    def _is_graduate_certificate_page(self, page_text: str) -> bool:
        text = page_text or ""
        return "毕业证书" in text and any(token in text for token in ("硕士研究生", "博士研究生", "研究生")) and any(token in text for token in ("准予毕业", "修完", "培养计划"))

    def _extract_graduate_student_name(self, page_text: str) -> str:
        for pattern in (
            re.compile(r"毕业证书\s*([^\s，,]{2,12})性别"),
            re.compile(r"([^\s，,]{2,12})性别[男女]"),
            re.compile(r"研究生\s*([^\s，,。；;]{2,8})\s*性别[男女]"),
        ):
            match = pattern.search(page_text or "")
            if match:
                return self._clean_person_name(match.group(1))
        return ""

    def _clean_person_name(self, value: str) -> str:
        name = self._clean_title(value)
        name = re.sub(r"[^一-龥·]", "", name)
        if name.startswith("研究生") and len(name) > 3:
            name = name[3:]
        return name[:8]

    def _extract_graduate_major(self, page_text: str) -> str:
        match = re.search(r"\d{4}年\d{2}月至\s*\d{4}年\d{2}月在([^\n\r]{2,40}?)(?:专业|学科)", page_text or "")
        if match:
            return self._clean_title(match.group(1))
        match = re.search(r"在([^\n\r]{2,40}?)(?:专业|学科).*?(?:学习|培养)", page_text or "")
        if match:
            return self._clean_title(match.group(1))
        return ""

    def _extract_graduate_certificate_scan_fallback(
        self,
        document: ParsedAcceptanceDocument,
        page_groups: dict[int, list[ParsedAcceptanceBlock]],
        seen_keys: set[str],
    ) -> list[ExtractedEvidence]:
        """合并扫描 PDF 中，部分证书页可能只解析出页码；已确认是证书包时按页拆分兜底。"""
        if not page_groups:
            return []
        total_pages = int(document.metadata.get("pages") or 0) or max(page_groups) + 1
        if total_pages < 2:
            return []
        confirmed_pages = {
            page_index
            for page_index, page_blocks in page_groups.items()
            if self._is_graduate_certificate_page("\n".join(block.text for block in page_blocks))
        }
        if not confirmed_pages:
            return []
        if self._split_dissertation_segments(document):
            return []
        sparse_pages: list[int] = []
        for page_index, page_blocks in sorted(page_groups.items()):
            if page_index in confirmed_pages:
                continue
            page_text = "\n".join(block.text for block in page_blocks)
            if self._is_sparse_scan_page_text(page_text):
                sparse_pages.append(page_index)
        if not sparse_pages:
            return []
        items: list[ExtractedEvidence] = []
        for page_index in sparse_pages:
            artifact_key = f"graduate-scan-page:{document.file_name}:{page_index}"
            if artifact_key in seen_keys:
                continue
            seen_keys.add(artifact_key)
            page_blocks = page_groups.get(page_index, [])
            anchor_block = page_blocks[0] if page_blocks else None
            items.append(
                ExtractedEvidence(
                    metric_name="培养研究生",
                    metric_category="人才培养",
                    value=None,
                    unit="名",
                    implicit_count=1.0,
                    action="培养",
                    metric_variant="培养研究生",
                    evidence_mode="itemized",
                    evidence_role="primary",
                    artifact_key=artifact_key,
                    artifact_title=f"硕士研究生毕业证书扫描页 - 第{page_index + 1}页",
                    confidence=0.62,
                    excerpt="合并PDF已确认包含研究生毕业证书；该页仅解析出页码/极少文本，按独立扫描证明页兜底拆分，建议人工复核。",
                    block_id=anchor_block.block_id if anchor_block else "",
                    page=page_index,
                )
            )
        return items

    def _is_sparse_scan_page_text(self, page_text: str) -> bool:
        compact = re.sub(r"\s+", "", page_text or "")
        if not compact:
            return True
        if re.fullmatch(r"[\-—_]*\d{1,3}[\-—_]*", compact):
            return True
        return len(compact) <= 6 and not re.search(r"[\u4e00-\u9fffA-Za-z]{3,}", compact)

    def _extract_merged_journal_papers(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        if not self._looks_like_merged_journal_bundle(document):
            return []
        items: list[ExtractedEvidence] = []
        seen_titles: set[str] = set()
        page_groups = self._group_blocks_by_page(document)
        last_cover_page = -1
        for page_index in sorted(page_groups):
            page_blocks = page_groups[page_index]
            page_text = "\n".join(block.text for block in page_blocks)
            if not self._is_journal_article_start_page(page_blocks, page_text, last_cover_page):
                continue
            title = self._trim_merged_author_suffix(self._extract_paper_start_title(page_blocks, page_text))
            if not title or self._is_reference_citation_line(title):
                continue
            normalized_title = self._clean_title(title)
            if not normalized_title or not self._is_plausible_paper_title(normalized_title):
                continue
            dedupe_key = self._normalize_dissertation_title_key(normalized_title) or normalized_title[:100]
            if dedupe_key in seen_titles:
                continue
            seen_titles.add(dedupe_key)
            last_cover_page = page_index
            anchor_block = self._find_title_anchor_block(page_blocks, normalized_title)
            year = self._first_match(YEAR_PATTERN, page_text) or self._first_match(YEAR_PATTERN, document.text[:4000])
            items.append(
                ExtractedEvidence(
                    metric_name="科技论文",
                    metric_category="成果产出",
                    value=None,
                    unit="篇",
                    implicit_count=1.0,
                    action="发表",
                    time_label=year,
                    metric_variant="科技论文",
                    evidence_mode="itemized",
                    evidence_role="primary",
                    artifact_key=dedupe_key,
                    artifact_title=normalized_title,
                    confidence=0.9,
                    excerpt=self._paper_excerpt_for_title(page_text, normalized_title),
                    block_id=anchor_block.block_id,
                    page=anchor_block.page,
                )
            )
        return items

    def _looks_like_merged_dissertation_bundle(self, document: ParsedAcceptanceDocument) -> bool:
        corpus = document.text[:12000]
        title_hits = len(DISSERTATION_TITLE_PATTERN.findall(corpus)) + len(
            DISSERTATION_TITLE_LINE_PATTERN.findall(corpus)
        )
        header_hits = len(DISSERTATION_HEADER_PATTERN.findall(corpus))
        return title_hits >= 2 or header_hits >= 2

    def _looks_like_merged_journal_bundle(self, document: ParsedAcceptanceDocument) -> bool:
        page_groups = self._group_blocks_by_page(document)
        pages = int(document.metadata.get("pages") or 0) or len(page_groups)
        corpus = document.text[:20000] if document.text else self._classification_corpus(document)
        if any(token in corpus for token in ("验收申请表", "项目任务书", "验收自评价报告", "科技计划项目")):
            return False
        candidate_start_pages = sum(
            1
            for page_blocks in page_groups.values()
            if self._is_journal_article_start_page(
                page_blocks,
                "\n".join(block.text for block in page_blocks),
            )
        )
        if candidate_start_pages >= 2:
            return True
        if pages < 4 and len(page_groups) < 4:
            return False
        issue_hits = len(JOURNAL_ISSUE_HEADER_PATTERN.findall(corpus))
        has_journal_name = bool(JOURNAL_NAME_PATTERN.search(corpus))
        has_abstract = "摘要" in corpus or "摘 要" in corpus or bool(re.search(r"摘\s*要", corpus))
        paper_start_pages = sum(
            1
            for page_blocks in page_groups.values()
            if self._is_new_journal_paper_page("\n".join(block.text for block in page_blocks))
        )
        if paper_start_pages >= 2:
            return True
        if issue_hits >= 2 and has_journal_name:
            return True
        if issue_hits >= 1 and has_journal_name and has_abstract and pages >= 8:
            return True
        return False

    def _looks_like_merged_patent_bundle(self, document: ParsedAcceptanceDocument) -> bool:
        corpus = document.text[:20000] if document.text else self._classification_corpus(document)
        if any(
            token in corpus
            for token in (
                "验收自评价报告",
                "科技报告",
                "科技计划项目验收申请表",
                "项目任务书",
            )
        ):
            return False
        if self._count_patent_segments(document) < 2:
            return False
        return any(
            token in corpus
            for token in (
                "专利证书",
                "发明专利证书",
                "实用新型专利证书",
                "专利申请受理通知书",
            )
        )

    def _count_patent_segments(self, document: ParsedAcceptanceDocument) -> int:
        seen: set[str] = set()
        for page_blocks in self._group_blocks_by_page(document).values():
            page_text = "\n".join(block.text for block in page_blocks)
            if not any(token in page_text for token in ("专利证书", "发明专利证书", "实用新型专利证书", "专利申请受理通知书")):
                numbers = [self._compact_patent_no(match.group(1)) for match in PATENT_NO_PATTERN.finditer(page_text)]
                if not numbers:
                    fallback = self._first_match(PATENT_FALLBACK_NO_PATTERN, page_text)
                    if fallback:
                        numbers = [self._compact_patent_no(fallback)]
                for number in numbers:
                    if number:
                        seen.add(number)
                continue
            numbers = [self._compact_patent_no(match.group(1)) for match in PATENT_NO_PATTERN.finditer(page_text)]
            if not numbers:
                fallback = self._first_match(PATENT_FALLBACK_NO_PATTERN, page_text)
                if fallback:
                    numbers = [self._compact_patent_no(fallback)]
            for number in numbers:
                if number:
                    seen.add(number)
        return len(seen)

    def _is_new_journal_paper_page(self, page_text: str) -> bool:
        head = (page_text or "")[:1200]
        if not JOURNAL_NAME_PATTERN.search(head):
            return False
        if JOURNAL_ISSUE_HEADER_PATTERN.search(head):
            return True
        if re.search(r"第[\d０-９\s,，]+卷", head) and re.search(r"(?:期|No\.?\s*[\d０-９]+|pp\s*[\d０-９])", head, re.IGNORECASE):
            return True
        if re.search(r"研究论文|Research\s+Article", head, re.IGNORECASE) and re.search(r"第[\d０-９\s,，]+卷", head):
            return True
        return False

    def _extract_chinese_journal_title(self, page_blocks: list[ParsedAcceptanceBlock]) -> str:
        lines = [self._clean_title(block.text) for block in page_blocks if self._clean_title(block.text)]
        for idx, line in enumerate(lines[:12]):
            if self._is_chinese_paper_title_line(line, lines, idx):
                return line
        titled = self._extract_paper_title_from_page("\n".join(lines))
        return titled or ""

    def _is_applied_spectroscopy_cover(self, head: str) -> bool:
        compact = head or ""
        return "Applied Spectroscopy" in compact and (
            "Submitted Manuscript" in compact or "Date received" in compact
        )

    def _looks_like_chinese_author_line(self, line: str) -> bool:
        if not line or len(line) > 160:
            return False
        if re.search(r"[，,]\s*[\d０-９\*＊]", line):
            return True
        if re.search(r"[\u4e00-\u9fff]{1,4}\s*[\d０-９\*＊]{1,2}", line) and ("，" in line or "," in line):
            return True
        if re.search(r"^[\u4e00-\u9fff]{2,4}\s*[\d０-９\*＊]", line) and re.search(
            r"[\u4e00-\u9fff]{2,4}\s*[\d０-９\*＊]", line[3:]
        ):
            return True
        return False

    def _trim_merged_author_suffix(self, title: str) -> str:
        cleaned = self._clean_title(title)
        if not cleaned:
            return ""
        for marker in ("陈 颖", "陈颖", "刘喆", "Ying Chen", "CHEN Ying"):
            pos = cleaned.find(marker)
            if pos >= 12:
                return self._clean_title(cleaned[:pos])
        author_match = re.search(r"[\u4e00-\u9fff]{2,4}\s*[\d０-９]", cleaned)
        if author_match and author_match.start() >= 12:
            prefix = cleaned[: author_match.start()]
            if len(re.findall(r"[\u4e00-\u9fff]", prefix)) >= 8:
                return self._clean_title(prefix)
        cleaned = re.sub(r"\s*[*＊]\s*$", "", cleaned)
        return cleaned

    def _is_chinese_journal_title_candidate(
        self, line: str, lines: list[str], idx: int
    ) -> bool:
        if JOURNAL_ISSUE_HEADER_PATTERN.search(line) or JOURNAL_NAME_PATTERN.search(line):
            return False
        if self._looks_like_chinese_author_line(line):
            return False
        if line.startswith(("（", "(", "1.", "2.", "3.")) or any(token in line for token in ("大学", "学院", "研究院", "实验室", "重点实验室")):
            return False
        if self._is_chinese_paper_title_line(line, lines, idx):
            return True
        if len(line) < 12 or len(line) > 120:
            return False
        if any(
            token in line
            for token in (
                "摘要",
                "关键词",
                "引言",
                "参考文献",
                "收稿",
                "基金",
                "中图分类",
                "本文",
                "为了",
            )
        ):
            return False
        if CHINESE_PAPER_TITLE_SUFFIX_PATTERN.search(line):
            if idx + 1 < len(lines) and (
                re.search(r"[，,]\s*[\d０-９\*＊]", lines[idx + 1])
                or "大学" in lines[idx + 1]
                or "学院" in lines[idx + 1]
            ):
                return True
            if any("摘" in ln and "要" in ln for ln in lines[idx : idx + 8]):
                return True
        return False

    def _is_journal_article_start_page(
        self,
        page_blocks: list[ParsedAcceptanceBlock],
        page_text: str,
        last_cover_page: int = -1,
    ) -> bool:
        if self._is_reference_bibliography_page(page_text):
            return False
        lines = [self._clean_title(block.text) for block in page_blocks if self._clean_title(block.text)]
        if not lines:
            return False
        page_index = page_blocks[0].page if page_blocks else 0
        head = "\n".join(lines[:14])
        head_window = head[:1800]

        _ = last_cover_page

        if ELSEVIER_COVER_PATTERN.search(head_window[:900]):
            return any(
                len(line) >= 28
                and re.match(r"^[A-Z][a-z]", line)
                and re.search(r"brown tide|fluorescence|algae|spectromet", line, re.IGNORECASE)
                for line in lines[:30]
            )

        if self._is_applied_spectroscopy_cover(head_window[:1200]):
            return any(
                re.search(r"Based on|Prediction", line, re.IGNORECASE) and len(line) >= 30
                for line in lines[:22]
            )

        extracted_title = self._trim_merged_author_suffix(self._extract_paper_start_title(page_blocks, page_text))
        if extracted_title and self._is_plausible_paper_title(extracted_title):
            if self._looks_like_english_journal_article_start(head_window, lines):
                return True

        cover_head = "\n".join(lines[:6])
        has_issue_header = bool(JOURNAL_ISSUE_HEADER_PATTERN.search(cover_head)) or bool(
            re.search(
                r"研究论文.{0,40}第[\d０-９]+卷|第[\d０-９]+卷.{0,60}研究论文",
                cover_head,
            )
        )
        if not has_issue_header:
            has_issue_header = "文章编号" in cover_head and bool(JOURNAL_NAME_PATTERN.search(cover_head))
        if not has_issue_header:
            has_issue_header = bool(
                re.search(
                    r"Chinese Journal of Scientific Instrument|ACTA METROLOGICA SINICA|仪器仪表学报|计量学报",
                    cover_head,
                    re.IGNORECASE,
                )
            )
        if not has_issue_header:
            return False

        has_abstract = any("摘" in ln and "要" in ln for ln in lines[:20]) or bool(
            re.search(r"\bAbstract\b", head_window[:1600], re.IGNORECASE)
        )
        if not has_abstract:
            return False

        for idx, line in enumerate(lines[:12]):
            if self._is_chinese_journal_title_candidate(line, lines, idx):
                return True

        if re.search(r"research\s+article|RESEARCH\s+ARTICLE", page_text[:1500], re.IGNORECASE):
            for idx, line in enumerate(lines[:30]):
                if self._paper_title_score(lines, idx, line) >= 6:
                    return True
        return False

    def _looks_like_english_journal_article_start(self, head: str, lines: list[str]) -> bool:
        blob = head or "\n".join(lines[:18])
        lower = blob.lower()
        if "contents lists available at sciencedirect" in lower and "journal homepage" in lower:
            return True
        if "research article" in lower and ("doi" in lower or "article id" in lower or "wiley" in lower):
            return True
        if "article in press" in lower and ("journal homepage" in lower or "sciencedirect" in lower):
            return True
        if any("abstract" == line.strip().lower() or line.strip().lower().startswith("abstract ") for line in lines[:30]):
            return any(
                token in lower
                for token in (
                    "journal homepage",
                    "research article",
                    "article in press",
                    "contents lists available",
                )
            )
        return False

    def _is_plausible_paper_title(self, title: str) -> bool:
        if len(title) < 10 or len(title) > 200:
            return False
        lower = title.lower()
        if re.match(
            r"^(?:fig\.?|figure|表\s*\d|y\.\s*[a-z]|vol\.?\s*\d|the\s|in\s+this|fig\.\s*\d)",
            lower,
        ):
            return False
        if re.search(r"\bmodel prediction results\b|\bpurchased from\b", lower):
            return False
        if "spectrochimica acta part" in lower and len(title) < 50:
            return False
        if re.search(r"vol\.?\s*\d|no\.?\s*\d|journal of|spectroscopy and spectral", lower):
            return False
        if re.search(r"[=∑∫′]|f[m-z]\(|xi'\)", title):
            return False
        if re.search(r"[（(]\s*x\d|=\s*\{|损失函|样本数量", title, re.IGNORECASE):
            return False
        if title.lower().startswith("study on detection") and len(re.findall(r"[\u4e00-\u9fff]", title)) < 6:
            return False
        if re.search(r"\d+[,，]\s*[A-Z][a-z]|University|College|Institute", title):
            return False
        if title.count("，") >= 3 or title.count(",") >= 4:
            return False
        if re.fullmatch(r"[A-Za-z0-9 .,&;:\-()]+", title):
            return len(title.split()) >= 6
        chinese = len(re.findall(r"[\u4e00-\u9fff]", title))
        if chinese >= 6:
            return True
        return len(title) >= 24 and bool(re.search(r"[A-Za-z]{4,}", title))

    def _is_chinese_paper_title_line(self, line: str, lines: list[str], idx: int) -> bool:
        if len(line) < 12 or len(line) > 120:
            return False
        if any(token in line for token in ("摘要", "关键词", "引言", "参考文献", "收稿", "基金")):
            return False
        if re.search(
            r"(?:光谱学\s*与\s*光谱分析|光学学报|Chinese Journal of Scientific|ACTA METROLOGICA|仪器仪表学报|计量学报|Spectroscopy\s+and\s+Spectral)",
            line,
            re.IGNORECASE,
        ):
            return False
        if ("学报" in line or "期刊" in line) and len(line) < 48:
            return False
        if any(token in line for token in ("本文", "为了", "采用上", "损失函", "样本数量", "上接", "下转", "见图", "如表")):
            return False
        if re.search(r"[（(]\s*x\d|y\d|N\s*为样本", line, re.IGNORECASE):
            return False
        starts_like_title = line.startswith(CHINESE_PAPER_TITLE_PREFIXES)
        has_title_context = False
        if idx + 1 < len(lines):
            nxt = lines[idx + 1]
            has_title_context = bool(
                re.search(r"[，,]\s*[\d０-９]", nxt)
                or re.search(r"[\u4e00-\u9fff]{2,4}\s*[\d０-９]", nxt)
                or "大学" in nxt
                or "学院" in nxt
                or "研究所" in nxt
            ) and any("摘" in ln and "要" in ln for ln in lines[idx + 1 : idx + 9])
        if not starts_like_title and not has_title_context:
            return False
        if re.match(r"^\d", line):
            return False
        if idx + 1 < len(lines):
            nxt = lines[idx + 1]
            if re.search(r"[，,]\s*[\d０-９]", nxt) or "大学" in nxt or "学院" in nxt or "研究所" in nxt:
                return True
        return len(re.findall(r"[\u4e00-\u9fff]", line)) >= 8

    def _block_for_text_offset(
        self,
        document: ParsedAcceptanceDocument,
        offset: int,
        block_map: dict[str, ParsedAcceptanceBlock],
    ) -> ParsedAcceptanceBlock | None:
        cursor = 0
        for block in document.blocks:
            block_text = block.text
            end = cursor + len(block_text)
            if cursor <= offset < end + 1:
                return block
            cursor = end + 1
        return document.blocks[0] if document.blocks else None

    def _page_text_for_block(
        self,
        document: ParsedAcceptanceDocument,
        block: ParsedAcceptanceBlock | None,
    ) -> str:
        if block is None:
            return document.text[:2000]
        page_blocks = self._group_blocks_by_page(document).get(block.page, [])
        return "\n".join(item.text for item in page_blocks)

    def _split_patent_title_chunks(self, text: str) -> list[str]:
        chunks: list[str] = []
        for pattern in (
            re.compile(r"(?:发明名称|专利名称|实用新型名称)[:：]\s*([^\n\r]{4,120})"),
            re.compile(r"(?:名称|项目名称)[:：]\s*([^\n\r]{4,120})"),
        ):
            for match in pattern.finditer(text or ""):
                title = self._clean_title(match.group(1))
                if title and title not in chunks:
                    chunks.append(title)
        return chunks

    def _patent_excerpt_for_index(self, text: str, index: int, *, patent_no: str = "", invention_title: str = "") -> str:
        parts: list[str] = []
        if patent_no:
            parts.append(f"专利号：{patent_no}")
        if invention_title:
            parts.append(f"发明名称：{invention_title}")
        lines = [self._clean_title(line) for line in (text or "").splitlines() if self._clean_title(line)]
        for pos, line in enumerate(lines):
            if any(token in line for token in ("申请号", "专利号", "发明名称", "专利名称", "受理通知书")):
                parts.append(line)
                if len(parts) >= 3:
                    break
        if parts:
            return "；".join(parts)[:240]
        return "；".join(lines[:4])[:240] if lines else (text or "")[:240]

    def _find_title_anchor_block(
        self, page_blocks: list[ParsedAcceptanceBlock], title: str
    ) -> ParsedAcceptanceBlock | None:
        if not page_blocks:
            return None
        compact_title = re.sub(r"\s+", "", self._clean_title(title))
        if not compact_title:
            return page_blocks[0]
        best_block: ParsedAcceptanceBlock | None = None
        best_len = 10**9
        for block in page_blocks[:30]:
            compact_block = re.sub(r"\s+", "", self._clean_title(block.text))
            if not compact_block:
                continue
            if compact_title in compact_block or compact_title[:20] in compact_block:
                if len(compact_block) < best_len:
                    best_block = block
                    best_len = len(compact_block)
        return best_block or page_blocks[0]

    def _paper_excerpt_for_title(self, text: str, title: str) -> str:
        lines = [self._clean_title(line) for line in (text or "").splitlines() if self._clean_title(line)]
        if title:
            for idx, line in enumerate(lines):
                if title in line:
                    return "；".join(lines[idx: min(idx + 4, len(lines))])[:240]
        return (text or "")[:240]

    def _extract_paper_title_from_block(self, text: str) -> str:
        for pattern in (
            re.compile(r"论文题目[:：]\s*([^\n\r]{6,120})"),
            re.compile(r"题目[:：]\s*([^\n\r]{6,120})"),
        ):
            match = pattern.search(text)
            if match:
                return self._clean_title(match.group(1))
        return ""

    def _extract_paper_title_from_page(self, text: str) -> str:
        lines = [self._clean_title(line) for line in (text or "").splitlines() if self._clean_title(line)]
        if not lines:
            return ""
        for idx, line in enumerate(lines[:20]):
            score = self._paper_title_score(lines, idx, line)
            if score >= 4:
                return line
        for pattern in (
            re.compile(r"论文题目[:：]\s*([^\n\r]{6,200})"),
            re.compile(r"题目[:：]\s*([^\n\r]{6,200})"),
        ):
            match = pattern.search(text or "")
            if match:
                title = self._clean_title(match.group(1))
                if title:
                    return title
        return ""

    def _extract_soft_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        block = document.blocks[0] if document.blocks else None
        corpus = document.text[:2000]
        reg_no = self._first_match(SOFT_REG_PATTERN, corpus)
        year = self._first_match(YEAR_PATTERN, corpus)
        return [
            ExtractedEvidence(
                metric_name="软件著作权",
                metric_category="知识产权",
                value=None,
                unit="项",
                implicit_count=1.0,
                action="登记",
                time_label=year,
                metric_variant="软件著作权",
                evidence_mode="itemized",
                evidence_role="primary",
                artifact_key=reg_no or self._fallback_artifact_key(document, "软件著作权"),
                artifact_title=self.document_display_title(document),
                confidence=0.9,
                excerpt=(block.text if block else document.text)[:240],
                block_id=block.block_id if block else "",
                page=block.page if block else 0,
            )
        ]

    def _is_self_evaluation_report(self, document: ParsedAcceptanceDocument) -> bool:
        corpus = f"{self.document_display_title(document)}\n{self._classification_corpus(document)}"
        return any(
            token in corpus
            for token in ("验收自评价报告", "项目验收自评价", "验收自评", "自评价报告")
        )

    def _extract_inspection_report_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        """从第三方检测报告抽取实测指标（示值误差、精密度等）。"""
        items: list[ExtractedEvidence] = []
        corpus = document.text or ""
        block = self._find_first_nonempty_block(document)
        anchor_block_id = block.block_id if block else ""
        anchor_page = block.page if block else 0

        def add_metric(
            metric_name: str,
            *,
            value: float,
            unit: str,
            excerpt: str,
            confidence: float,
            page: int = anchor_page,
            block_id: str = anchor_block_id,
        ) -> None:
            spec = self._lookup_spec(metric_name)
            if spec is None or value <= 0:
                return
            items.append(
                ExtractedEvidence(
                    metric_name=metric_name,
                    metric_category=spec.category,
                    value=value,
                    unit=unit,
                    implicit_count=0.0,
                    action="达到",
                    time_label=self._first_match(YEAR_PATTERN, excerpt) or self._first_match(YEAR_PATTERN, corpus),
                    caliber_label="检测报告实测",
                    metric_variant=metric_name,
                    evidence_mode="summary",
                    evidence_role="primary",
                    artifact_key=f"{metric_name}:{value}:{unit}",
                    artifact_title=self.document_display_title(document),
                    confidence=confidence,
                    excerpt=excerpt[:240],
                    block_id=block_id,
                    page=page,
                )
            )

        error_match = re.search(r"示值误差[\s\S]{0,120}?(\d+(?:\.\d+)?)\s*%", corpus)
        if error_match:
            add_metric(
                "最大测量误差",
                value=float(error_match.group(1)),
                unit="%",
                excerpt=error_match.group(0),
                confidence=0.92,
            )

        precision_match = re.search(
            r"精密度[\s\S]{0,160}?(\d+(?:\.\d+)?)\s*%[\s\S]{0,40}?(\d+(?:\.\d+)?)\s*%\s*符合",
            corpus,
        )
        if precision_match:
            measured = min(float(precision_match.group(1)), float(precision_match.group(2)))
            add_metric(
                "检测标准偏差",
                value=measured,
                unit="%",
                excerpt=precision_match.group(0),
                confidence=0.92,
            )
        else:
            precision_single = re.search(r"精密度[\s\S]{0,80}?(\d+(?:\.\d+)?)\s*%", corpus)
            if precision_single:
                add_metric(
                    "检测标准偏差",
                    value=float(precision_single.group(1)),
                    unit="%",
                    excerpt=precision_single.group(0),
                    confidence=0.88,
                )

        freq_match = re.search(r"(\d+(?:\.\d+)?)\s*次\s*/\s*时", corpus)
        if freq_match and "检测结果" in corpus:
            add_metric(
                "检测频率",
                value=float(freq_match.group(1)),
                unit="次/时",
                excerpt=freq_match.group(0),
                confidence=0.9,
            )

        return self._dedupe_extracted(items)

    def _extract_report_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        block = self._find_first_nonempty_block(document)
        corpus = document.text[:6000]
        is_self_eval = self._is_self_evaluation_report(document)
        title = self.document_display_title(document)
        items: list[ExtractedEvidence] = []
        if not is_self_eval:
            items.append(
                ExtractedEvidence(
                    metric_name="科技报告",
                    metric_category="成果产出",
                    value=None,
                    unit="份",
                    implicit_count=1.0,
                    action="形成",
                    metric_variant="科技报告",
                    evidence_mode="itemized",
                    evidence_role="primary",
                    artifact_key=title,
                    artifact_title=title,
                    confidence=0.75,
                    excerpt=(block.text if block else document.text)[:240],
                    block_id=block.block_id if block else "",
                    page=block.page if block else 0,
                )
            )
        items.extend(self._extract_report_appendix_items(document))
        items.extend(self._extract_report_table_items(document))
        if is_self_eval:
            items.extend(self._extract_self_eval_deliverables(document))
        if not is_self_eval and self._is_formal_science_report_deliverable(document):
            items.extend(self._extract_formal_science_report_deliverables(document, block))
        if not is_self_eval:
            items.extend(self._extract_policy_report_deliverables(document, block, title))
        items.extend(self._extract_report_technical_metrics(document))
        for metric_name, aliases in (
            ("高效杀虫功能微生物", ("高效杀虫功能微生物", "杀虫微生物", "杀虫菌株", "菌株BVZ-6")),
            ("杀蚜虫新型生物制剂", ("杀蚜虫新型生物制剂", "微生物制剂", "新型微生物杀虫剂", "水分散粒剂")),
            ("田间应用防效", ("田间应用防效", "田间防效", "防治效果", "防效")),
            ("化学农药减施率", ("化学农药减施率", "化学农药减施", "农药减施率", "减施率")),
            ("培养研究生", ("培养硕士研究生", "培养研究生", "硕士研究生", "研究生")),
            ("科普动画部数", ("视频动画", "科普动画", "科普动漫微视频", "科普影视作品", "原创科普影视作品")),
            ("公益推广科普作品", ("公益推广", "科普动画作品", "影视动画作品", "科普作品", "原创科普动画影视作品")),
            ("提供资助方科普作品", ("提供给资助方", "提供给甲方", "直接提供给资助方")),
            ("科普推广点击量", ("累计网络点击量", "推广总量", "累计总流量", "网络点击量")),
            ("开展科普活动", ("科普活动", "科学普及场次", "科普推广会议")),
        ):
            if not any(alias in corpus for alias in aliases):
                continue
            excerpt_line = self._best_report_metric_line(document, metric_name, aliases)
            if not self._report_line_supports_metric(excerpt_line, metric_name):
                continue
            spec = self._lookup_spec(metric_name)
            value, unit = (self._extract_value_and_unit(excerpt_line or corpus, spec) if spec else (None, ""))
            implicit_count = 0.0
            if value is None:
                if metric_name == "高效杀虫功能微生物":
                    count = self._extract_list_count_from_text(excerpt_line or corpus, metric_name)
                    value = count
                    unit = unit or "株"
                elif metric_name == "培养研究生":
                    count = self._extract_list_count_from_text(excerpt_line or corpus, metric_name)
                    value = count
                    unit = unit or "名"
                elif metric_name == "杀蚜虫新型生物制剂":
                    implicit_count = 1.0
            items.append(
                ExtractedEvidence(
                    metric_name=metric_name,
                    metric_category=spec.category if spec else "成果产出",
                    value=value,
                    unit=unit,
                    implicit_count=implicit_count,
                    action=self._infer_generic_action(excerpt_line or corpus, metric_name),
                    time_label=self._first_match(YEAR_PATTERN, corpus),
                    caliber_label=self._infer_generic_caliber(excerpt_line or corpus),
                    metric_variant=metric_name,
                    evidence_mode="summary" if value is not None else "itemized",
                    evidence_role="supporting",
                    artifact_key=self.document_display_title(document),
                    artifact_title=self.document_display_title(document),
                    confidence=0.7,
                    excerpt=(excerpt_line or corpus)[:240],
                    block_id=block.block_id if block else "",
                    page=block.page if block else 0,
                )
            )
        return self._dedupe_extracted(items)

    def _extract_policy_report_deliverables(
        self,
        document: ParsedAcceptanceDocument,
        block: ParsedAcceptanceBlock | None,
        title: str,
    ) -> list[ExtractedEvidence]:
        clean_title = self._clean_title(title)
        corpus = document.text[:8000]
        blob = f"{clean_title} {corpus[:2000]}"
        if any(token in blob for token in ("知网个人查重服务报告单", "检测文献", "留存证明", "咨询专刊综合采用")):
            return []
        metric_name = ""
        if self._looks_like_decision_report_body(clean_title, corpus):
            metric_name = "决策咨询报告"
        elif self._looks_like_research_report_body(clean_title, corpus):
            metric_name = "研究报告"
        if not metric_name:
            return []
        first_line = next((line for line in document.lines[:40] if self._clean_title(line)), clean_title)
        spec = self._lookup_spec(metric_name)
        return [
            ExtractedEvidence(
                metric_name=metric_name,
                metric_category=spec.category if spec else "成果产出",
                value=None,
                unit="篇",
                implicit_count=1.0,
                action="形成",
                metric_variant=metric_name,
                evidence_mode="itemized",
                evidence_role="primary",
                artifact_key=f"{metric_name}:{clean_title or document.file_name}",
                artifact_title=clean_title or document.file_name,
                confidence=0.82,
                excerpt=(first_line or corpus)[:240],
                block_id=block.block_id if block else "",
                page=block.page if block else 0,
            )
        ]

    def _best_report_metric_line(
        self,
        document: ParsedAcceptanceDocument,
        metric_name: str,
        aliases: tuple[str, ...],
    ) -> str:
        spec = self._lookup_spec(metric_name)
        candidates: list[tuple[int, str]] = []
        for line in document.lines:
            if not any(alias in line for alias in aliases):
                continue
            if not self._report_line_supports_metric(line, metric_name):
                continue
            score = 0
            if spec is not None and self._extract_value_and_unit(line, spec)[0] is not None:
                score += 4
            if self._extract_list_count_from_text(line, metric_name) is not None:
                score += 3
            if any(token in line for token in ("完成", "达到", "实现", "研制", "筛选", "培养", "防效", "减施")):
                score += 2
            if any(char.isdigit() for char in line):
                score += 1
            candidates.append((score, line))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        return candidates[0][1]

    def _is_formal_science_report_deliverable(self, document: ParsedAcceptanceDocument) -> bool:
        if self._is_self_evaluation_report(document):
            return False
        head = document.text[:4000]
        return bool(re.search(r"报告编号|MB1E\d+", head)) or ("科技报告" in head and "报告名称" in head)

    def _extract_formal_science_report_deliverables(
        self,
        document: ParsedAcceptanceDocument,
        block: ParsedAcceptanceBlock | None,
    ) -> list[ExtractedEvidence]:
        title = self.document_display_title(document)
        report_line = next(
            (line for line in document.lines if "报告名称" in line or "河北省科技成果" in line),
            block.text if block else title,
        )
        return [
            ExtractedEvidence(
                metric_name="研究报告",
                metric_category="成果产出",
                value=None,
                unit="篇",
                implicit_count=1.0,
                action="形成",
                metric_variant="研究报告",
                evidence_mode="itemized",
                evidence_role="primary",
                artifact_key=f"研究报告:{document.file_name}",
                artifact_title=title,
                confidence=0.88,
                excerpt=report_line[:240],
                block_id=block.block_id if block else "",
                page=block.page if block else 0,
            )
        ]

    def _extract_self_eval_deliverables(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        """从验收自评价报告正文抽取研究报告/决策咨询报告完成条目。"""
        items: list[ExtractedEvidence] = []
        seen: set[str] = set()
        count_patterns = (
            (re.compile(r"(?:形成|撰写|提交).*?科技报告\s*(\d+(?:\.\d+)?)\s*篇"), "科技报告"),
            (re.compile(r"(?:形成|撰写|提交).*?综合研究报告\s*(\d+(?:\.\d+)?)\s*篇"), "研究报告"),
            (re.compile(r"(?:形成|撰写|提交).*?研究报告\s*(\d+(?:\.\d+)?)\s*篇"), "研究报告"),
            (re.compile(r"(?:形成|撰写|提交).*?决策(?:参考|咨询)?报告\s*(\d+(?:\.\d+)?)\s*篇"), "决策咨询报告"),
            (re.compile(r"(?:发表|刊发|刊登).*?(?:理论文章|论文)\s*(\d+(?:\.\d+)?)\s*篇"), "科技论文"),
        )
        title_patterns = (
            (re.compile(r"《[^》]*研究报告[^》]*》"), "研究报告"),
            (re.compile(r"《[^》]*(?:决策|参考决策)[^》]*报告[^》]*》"), "决策咨询报告"),
        )
        for block in document.blocks:
            line = block.text.replace("一一", "").replace("—", "").strip()
            if not line:
                continue
            for pattern, metric_name in count_patterns:
                match = pattern.search(line)
                if not match:
                    continue
                key = f"{metric_name}:{line[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                count = float(match.group(1))
                spec = self._lookup_spec(metric_name)
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category=spec.category if spec else "成果产出",
                        value=count,
                        unit="篇",
                        implicit_count=0.0,
                        action=self._infer_generic_action(line, metric_name),
                        metric_variant=metric_name,
                        evidence_mode="summary",
                        evidence_role="primary",
                        artifact_key=f"{metric_name}:{document.file_name}:{key}",
                        artifact_title=self.document_display_title(document),
                        confidence=0.86,
                        excerpt=line[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
            for pattern, metric_name in title_patterns:
                if not pattern.search(line):
                    continue
                key = f"{metric_name}:title:{line[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                spec = self._lookup_spec(metric_name)
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category=spec.category if spec else "成果产出",
                        value=None,
                        unit="篇",
                        implicit_count=1.0,
                        action="形成",
                        metric_variant=metric_name,
                        evidence_mode="itemized",
                        evidence_role="primary",
                        artifact_key=f"{metric_name}:{document.file_name}:{key}",
                        artifact_title=self.document_display_title(document),
                        confidence=0.84,
                        excerpt=line[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
        return items

    def _extract_other_material_deliverables(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        """从查重单、说明类其他材料抽取可核验的成果条目。"""
        items: list[ExtractedEvidence] = []
        seen: set[str] = set()
        title = self.document_display_title(document)
        doc_lines = [self._clean_title(line) for line in document.lines[:120] if self._clean_title(line)]
        title_blob = " ".join(doc_lines[:12])
        normalized_title = self._clean_title(title)
        if any(token in title_blob for token in ("河北日报", "理论版", "发表")) or (
            "理论文章" in title_blob and any(token in title_blob for token in ("推进科技创新", "产业创新", "融合"))
        ):
            key = f"科技论文:{self._clean_title(title) or document.file_name}"
            items.append(
                ExtractedEvidence(
                    metric_name="科技论文",
                    metric_category="成果产出",
                    value=None,
                    unit="篇",
                    implicit_count=1.0,
                    action="发表",
                    metric_variant="科技论文",
                    evidence_mode="itemized",
                    evidence_role="primary",
                    artifact_key=key,
                    artifact_title=self._clean_title(title) or document.file_name,
                    confidence=0.86,
                    excerpt=title_blob[:240],
                    block_id=document.blocks[0].block_id if document.blocks else "",
                    page=document.blocks[0].page if document.blocks else 0,
                )
            )
        decision_report_title = self._clean_title(title)
        proof_material = self._looks_like_report_proof_material(decision_report_title, title_blob)
        looks_like_decision_body = self._looks_like_decision_report_body(normalized_title, title_blob)
        if any(token in decision_report_title for token in ("总体思路", "深度融合", "新优势")) or any(
            token in title_blob for token in ("决策参考报告", "决策咨询报告", "研究报告")
        ) or looks_like_decision_body:
            metric_name = "决策咨询报告"
            if any(token in decision_report_title for token in ("研究报告",)) and "决策" not in decision_report_title:
                metric_name = "研究报告"
            key = f"{metric_name}:{decision_report_title or document.file_name}"
            if key not in seen:
                seen.add(key)
                spec = self._lookup_spec(metric_name)
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category=spec.category if spec else "成果产出",
                        value=None,
                        unit="篇",
                        implicit_count=1.0,
                        action="形成",
                        metric_variant=metric_name,
                        evidence_mode="itemized",
                        evidence_role="supporting" if proof_material else "primary",
                        artifact_key=key,
                        artifact_title=decision_report_title or document.file_name,
                        confidence=0.7 if proof_material else 0.84,
                        excerpt=title_blob[:240],
                        block_id=document.blocks[0].block_id if document.blocks else "",
                        page=document.blocks[0].page if document.blocks else 0,
                    )
                )
        for block in document.blocks:
            line = block.text.strip()
            if "篇名" not in line:
                continue
            metric_name = ""
            if any(token in line for token in ("决策参考报告", "决策咨询报告", "参考决策报告", "决策报告")):
                metric_name = "决策咨询报告"
            elif "研究报告" in line:
                metric_name = "研究报告"
            if not metric_name:
                continue
            key = f"{metric_name}:{line[:100]}"
            if key in seen:
                continue
            seen.add(key)
            title_match = re.search(r"篇名[:：]?\s*(.+)", line)
            title = title_match.group(1).strip() if title_match else line
            spec = self._lookup_spec(metric_name)
            items.append(
                ExtractedEvidence(
                    metric_name=metric_name,
                    metric_category=spec.category if spec else "成果产出",
                    value=None,
                    unit="篇",
                    implicit_count=1.0,
                    action="形成",
                    metric_variant=metric_name,
                    evidence_mode="itemized",
                    evidence_role="supporting" if self._looks_like_report_proof_material(title, line) else "primary",
                    artifact_key=f"{metric_name}:{document.file_name}",
                    artifact_title=title[:120],
                    confidence=0.68 if self._looks_like_report_proof_material(title, line) else 0.8,
                    excerpt=line[:240],
                    block_id=block.block_id,
                    page=block.page,
                )
            )
        return self._dedupe_extracted(items)

    def _looks_like_decision_report_body(self, title: str, text: str) -> bool:
        blob = f"{title} {text}"
        if any(token in blob for token in ("知网个人查重服务报告单", "检测文献", "留存证明", "咨询专刊综合采用")):
            return False
        suggestion_markers = ("有关建议", "对策建议", "总体思路", "赋能", "发展建议")
        body_markers = ("一、", "（一）", "研究背景", "对策", "建议", "发展情况")
        if any(token in title for token in suggestion_markers) and any(token in text for token in body_markers):
            return True
        if (
            "研究" in title
            and any(token in text for token in ("发展的问题", "对策建议", "现实基础", "研究背景"))
            and any(token in text for token in ("五、", "六、", "建议"))
        ):
            return True
        if "研究" in title and any(token in text for token in ("对策建议", "发展的问题", "现实基础", "研究背景")):
            return True
        if "建议" in title and any(token in text for token in ("一、", "（一）", "情况", "建议")):
            return True
        return False

    def _looks_like_research_report_body(self, title: str, text: str) -> bool:
        blob = f"{title} {text}"
        if any(token in blob for token in ("知网个人查重服务报告单", "检测文献", "留存证明")):
            return False
        if "研究" not in title:
            return False
        if any(token in text for token in ("研究背景", "研究现状", "理论阐释", "现实基础", "对策建议")):
            return True
        return False

    def _looks_like_report_proof_material(self, title: str, text: str) -> bool:
        blob = f"{title} {text}"
        proof_tokens = ("证明", "采纳", "批示", "肯定性批示", "教育专报", "情况说明", "采用", "上报")
        report_body_tokens = ("研究报告", "决策参考报告", "决策咨询报告", "报告名称", "总报告", "阶段报告")
        if any(token in blob for token in proof_tokens) and not any(token in title for token in report_body_tokens):
            return True
        if title in {"九三学社河北省委员会", "河北省社会科学院："}:
            return True
        return False

    def _summary_metric_count_from_text(
        self,
        text: str,
        metric_name: str,
        aliases: tuple[str, ...],
    ) -> float | None:
        compact = " ".join((text or "").split())
        if not compact:
            return None
        spec = self._lookup_spec(metric_name)
        if spec is not None:
            value, _ = self._extract_value_and_unit(compact, spec)
            if value is not None:
                return value
        if metric_name == "科技论文" and "理论文章" in compact and any(
            token in compact for token in ("河北日报", "理论版", "发表", "刊发")
        ):
            return 1.0
        explicit_patterns = {
            "科技报告": (
                r"(?:科技报告)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(?:篇|份)",
                r"(\d+(?:\.\d+)?)\s*(?:篇|份)[^。；;\n]{0,12}(?:科技报告)",
            ),
            "研究报告": (
                r"(?:研究报告|总报告)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(?:篇|份)",
                r"(\d+(?:\.\d+)?)\s*(?:篇|份)[^。；;\n]{0,12}(?:研究报告|总报告)",
            ),
            "决策咨询报告": (
                r"(?:决策(?:参考|咨询)?报告)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(?:篇|份)",
                r"(\d+(?:\.\d+)?)\s*(?:篇|份)[^。；;\n]{0,12}(?:决策(?:参考|咨询)?报告)",
            ),
            "科技论文": (
                r"(?:理论文章|科技论文|论文)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*篇",
                r"(\d+(?:\.\d+)?)\s*篇[^。；;\n]{0,12}(?:理论文章|科技论文|论文)",
            ),
        }
        for pattern in explicit_patterns.get(metric_name, ()):
            match = re.search(pattern, compact)
            if match:
                return float(match.group(1))
        title_hits = {
            "科技报告": len(re.findall(r"《[^》]*科技报告[^》]*》", compact)),
            "研究报告": len(re.findall(r"《[^》]*研究报告[^》]*》", compact)),
            "决策咨询报告": len(re.findall(r"(?:决策(?:参考|咨询)?报告)", compact)),
            "科技论文": 0,
        }
        if metric_name == "科技论文":
            paper_titles = [
                title
                for title in re.findall(r"《[^》]{2,80}》", compact)
                if all(token not in title for token in ("日报", "报告", "专报", "批示"))
            ]
            if paper_titles and any(token in compact for token in ("理论文章", "科技论文", "发表", "刊发", "理论版")):
                return float(len(paper_titles))
            if any(token in compact for token in ("理论文章", "科技论文")) and any(
                token in compact for token in ("河北日报", "理论版", "发表", "刊发")
            ):
                return 1.0
        count = title_hits.get(metric_name, 0)
        if count > 0:
            return float(count)
        alias_count = sum(compact.count(alias) for alias in aliases)
        return float(alias_count) if alias_count > 0 else None

    def _extract_report_technical_metrics(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        """从研究型科技报告抽取技术指标，过滤章节标题/研究描述等弱证据。"""
        items: list[ExtractedEvidence] = []
        metric_aliases = (
            ("实验系统", ("实验系统", "检测实验系统", "信息处理实验系统")),
            ("技术方案", ("技术方案", "整体方案", "实验方案", "研究方案", "方案及资料", "解决方案", "实验解决方案", "完整的实验解决方案", "监测模型的构建")),
            ("工程样机", ("工程样机", "在线监测工程样机", "原理性样机")),
            ("示范基地", ("示范基地", "生产示范基地", "监测示范基地")),
            ("检测范围", ("检测范围", "样机检测范围", "样检测范围", "测量范围")),
            ("检测频率", ("检测工作频率", "工作频率")),
            ("检测标准偏差", ("检测标准偏差", "标准偏差")),
            ("最大测量误差", ("最大测量误差", "示值误差")),
        )
        seen_excerpts: set[str] = set()
        for metric_name, aliases in metric_aliases:
            spec = self._lookup_spec(metric_name)
            if spec is None:
                continue
            for block in document.blocks:
                line = block.text
                if not any(alias in line for alias in aliases):
                    continue
                if not self._report_line_supports_metric(line, metric_name):
                    continue
                excerpt_key = re.sub(r"\s+", "", line)[:120]
                if excerpt_key in seen_excerpts:
                    continue
                seen_excerpts.add(excerpt_key)
                value, unit = self._extract_value_and_unit(line, spec)
                implicit_count = 0.0
                if value is None and metric_name in {"实验系统", "技术方案", "工程样机", "示范基地"}:
                    if re.search(r"\d+\s*套", line) or re.search(r"\d+\s*个", line):
                        implicit_count = float(self._extract_list_count_from_text(line, metric_name) or 1.0)
                    elif any(token in line for token in ("完成", "建成", "形成", "研制", "搭建", "调试")):
                        implicit_count = 1.0
                if value is None and implicit_count <= 0:
                    continue
                role = "supporting" if value is not None else "primary"
                if metric_name in {"检测范围", "检测标准偏差", "最大测量误差"} and value is not None:
                    if any(token in line for token in ("表15", "实测", "测量", "检测结果", "可知")):
                        role = "primary"
                        confidence = 0.9
                    else:
                        confidence = 0.78
                else:
                    confidence = 0.82 if implicit_count > 0 else 0.75
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category=spec.category,
                        value=value,
                        unit=unit,
                        implicit_count=implicit_count,
                        action=self._infer_generic_action(line, metric_name),
                        time_label=self._first_match(YEAR_PATTERN, line) or self._first_match(YEAR_PATTERN, document.text[:2000]),
                        caliber_label=self._infer_generic_caliber(line),
                        metric_variant=metric_name,
                        evidence_mode="summary" if value is not None else "itemized",
                        evidence_role=role,
                        artifact_key=f"{metric_name}:{excerpt_key}",
                        artifact_title=self.document_display_title(document),
                        confidence=confidence,
                        excerpt=line[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
        return items

    def _report_line_supports_metric(self, line: str, metric_name: str) -> bool:
        text = (line or "").strip()
        if not text or len(text) < 6:
            return False
        spec = self._lookup_spec(metric_name)
        if spec is None:
            return False
        aliases = list(spec.aliases)
        if metric_name == "技术方案":
            aliases.extend(["整体方案", "实验方案", "研究方案"])
        if metric_name == "检测范围":
            aliases.extend(["测量范围", "样机检测范围"])
        if not any(alias in text for alias in aliases):
            return False
        if PAGE_LEADER_PATTERN.search(text) or re.search(r"\.{4,}|…{2,}", text):
            return False
        weak_context = ("实验研究", "光谱获取", "光谱图", "如图", "摘要", "目录", "章节", "光谱处理")
        completion_markers = ("完成", "建成", "形成", "研制", "搭建", "调试", "交付", "实现", "达到")
        if metric_name == "科技论文":
            return bool(APPENDIX_PAPER_LINE_PATTERN.match(text)) or bool(JOURNAL_NAME_PATTERN.search(text))
        if metric_name == "技术方案":
            if PAGE_LEADER_PATTERN.search(text) or "摘要" in text:
                return False
            if not any(token in text for token in ("技术方案", "整体方案", "实验方案", "研究方案", "方案及资料", "技术路线")):
                return False
            if any(token in text for token in ("方案细化", "总体研究方案", "技术路线", "整体方案", "实验方案")):
                return True
            if any(token in text for token in completion_markers + ("设计", "构建")):
                return True
            return False
        if metric_name in {"实验系统", "工程样机", "示范基地"}:
            if any(token in text for token in weak_context) and not any(token in text for token in completion_markers):
                return False
            if "采用窄带" in text or ("光源" in text and "实验系统" not in text):
                return False
            if "[表格行" in text and not any(token in text for token in completion_markers + ("套", "个", "座")):
                return False
            return any(token in text for token in completion_markers) or bool(re.search(r"\d+\s*(?:套|个|座)", text))
        if metric_name in {"检测范围", "检测标准偏差", "最大测量误差", "检测频率"}:
            if "小于" in text and "参数指标" in text:
                return False
            if any(token in text for token in ("表15", "实测", "测量", "检测结果", "可知", "样机检测")):
                return True
            if re.search(r"\d+(?:\.\d+)?\s*%", text) or re.search(r"cells/mL|mg/L", text, re.IGNORECASE):
                return True
            return False
        return True

    def _extract_report_table_items(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        items: list[ExtractedEvidence] = []
        row_patterns = {
            "科技论文": ("发表相关期刊及会议学术论文", "发表论文", "论文"),
            "发明专利": ("申请相关发明专利", "申请发明专利", "专利"),
            "培养研究生": ("培养硕士研究生", "研究生"),
            "技术方案": ("技术方案", "方案"),
        }
        for metric_name, hints in row_patterns.items():
            spec = self._lookup_spec(metric_name)
            if spec is None:
                continue
            for block in document.blocks:
                text = block.text
                if not any(hint in text for hint in hints):
                    continue
                if "完成情况" not in text and "具体任务" not in text and "考核指标" not in text:
                    continue
                value, unit = self._extract_value_and_unit(text, spec)
                if value is None:
                    if metric_name in {"科技论文", "发明专利", "培养研究生"}:
                        value = self._extract_list_count_from_text(text, metric_name)
                        unit = spec.units[0] if spec.units else unit
                if value is None:
                    continue
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category=spec.category,
                        value=value,
                        unit=unit,
                        implicit_count=0.0,
                        action=self._infer_generic_action(text, metric_name),
                        time_label=self._first_match(YEAR_PATTERN, text),
                        caliber_label=self._infer_generic_caliber(text),
                        metric_variant=metric_name,
                        evidence_mode="summary",
                        evidence_role="supporting",
                        artifact_key=self.document_display_title(document),
                        artifact_title=self.document_display_title(document),
                        confidence=0.78,
                        excerpt=text[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
        return items

    def _extract_report_appendix_items(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        items: list[ExtractedEvidence] = []
        appendix_section = False
        references_section = False
        appendix_kind = ""
        current_parts: list[str] = []
        current_block: ParsedAcceptanceBlock | None = None

        def flush_current() -> None:
            nonlocal current_parts, current_block
            if not appendix_kind or not current_parts or current_block is None:
                current_parts = []
                current_block = None
                return
            entry_text = " ".join(part.strip() for part in current_parts if part.strip())
            parsed = self._parse_report_appendix_entry(
                document=document,
                appendix_kind=appendix_kind,
                entry_text=entry_text,
                block=current_block,
            )
            if parsed is not None:
                items.append(parsed)
            current_parts = []
            current_block = None

        for block in document.blocks:
            text = block.text
            if "参考文献" in text:
                flush_current()
                references_section = True
                appendix_kind = ""
                continue
            if references_section:
                continue
            if "附录A" in text or "附件1" in text or "已发表论文" in text or "已申请专利" in text:
                appendix_section = True
                references_section = False
            if not appendix_section:
                continue
            clean_text = self._clean_title(text)
            if not clean_text or APPENDIX_PAGE_FOOTER_PATTERN.match(clean_text):
                continue
            section_kind = self._appendix_section_kind(clean_text)
            if section_kind:
                flush_current()
                appendix_kind = section_kind
                continue
            if appendix_kind and APPENDIX_ENTRY_START_PATTERN.match(clean_text):
                if self._is_reference_citation_line(clean_text):
                    continue
                flush_current()
                current_parts = [clean_text]
                current_block = block
                continue
            if current_parts:
                current_parts.append(clean_text)
                continue
            if "论文题目" in text or text.startswith("[") or "发表论文" in text:
                continue
            if PERSON_ROSTER_LINE_PATTERN.match(text):
                continue
            if APPENDIX_PAPER_LINE_PATTERN.match(text) and not self._is_reference_citation_line(text):
                title = self._clean_title(re.sub(r"^\d+\s*", "", text))
                items.append(
                    ExtractedEvidence(
                        metric_name="科技论文",
                        metric_category="成果产出",
                        value=None,
                        unit="篇",
                        implicit_count=1.0,
                        action="发表",
                        time_label=self._first_match(YEAR_PATTERN, text),
                        metric_variant="科技论文",
                        evidence_mode="summary",
                        evidence_role="catalog",
                        artifact_key=title[:80] or text[:80],
                        artifact_title=title[:120] or text[:120],
                        confidence=0.55,
                        excerpt=text[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
            elif re.search(r"^\d+\s", text) and ("申请号" in text or "专利号" in text or "专利" in text):
                patent_no = self._first_match(PATENT_NO_PATTERN, text) or self._first_match(PATENT_FALLBACK_NO_PATTERN, text)
                items.append(
                    ExtractedEvidence(
                        metric_name="发明专利",
                        metric_category="知识产权",
                        value=None,
                        unit="项",
                        implicit_count=1.0,
                        action="申请",
                        time_label=self._first_match(YEAR_PATTERN, text),
                        caliber_label="申请发明专利",
                        metric_variant="申请发明专利",
                        evidence_mode="itemized",
                        evidence_role="primary",
                        artifact_key=self._compact_patent_no(patent_no) or text[:80],
                        artifact_title=text[:80],
                        confidence=0.8,
                        excerpt=text[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
        flush_current()
        return self._dedupe_extracted(items)

    def _appendix_section_kind(self, text: str) -> str:
        compact = self._clean_title(text)
        if "已发表论文" in compact:
            return "paper"
        if "已申请专利" in compact:
            return "patent"
        if "硕士研究生培养" in compact or "研究生培养" in compact:
            return "dissertation"
        return ""

    def _parse_report_appendix_entry(
        self,
        *,
        document: ParsedAcceptanceDocument,
        appendix_kind: str,
        entry_text: str,
        block: ParsedAcceptanceBlock,
    ) -> ExtractedEvidence | None:
        if appendix_kind == "paper":
            return self._build_report_appendix_paper_entry(document, entry_text, block)
        if appendix_kind == "patent":
            return self._build_report_appendix_patent_entry(document, entry_text, block)
        if appendix_kind == "dissertation":
            return self._build_report_appendix_dissertation_entry(document, entry_text, block)
        return None

    def _build_report_appendix_paper_entry(
        self,
        document: ParsedAcceptanceDocument,
        entry_text: str,
        block: ParsedAcceptanceBlock,
    ) -> ExtractedEvidence | None:
        if self._is_reference_citation_line(entry_text):
            return None
        title = self._appendix_entry_title(entry_text)
        if not title:
            return None
        return ExtractedEvidence(
            metric_name="科技论文",
            metric_category="成果产出",
            value=None,
            unit="篇",
            implicit_count=1.0,
            action="发表",
            time_label=self._first_match(YEAR_PATTERN, entry_text),
            metric_variant="科技论文",
            evidence_mode="itemized",
            evidence_role="primary",
            artifact_key=title,
            artifact_title=title,
            confidence=0.88,
            excerpt=entry_text[:240],
            block_id=block.block_id,
            page=block.page,
        )

    def _build_report_appendix_patent_entry(
        self,
        document: ParsedAcceptanceDocument,
        entry_text: str,
        block: ParsedAcceptanceBlock,
    ) -> ExtractedEvidence | None:
        patent_no = self._compact_patent_no(
            self._first_match(PATENT_NO_PATTERN, entry_text) or self._first_match(PATENT_FALLBACK_NO_PATTERN, entry_text)
        )
        title = self._appendix_entry_title(entry_text)
        if not patent_no and not title:
            return None
        local_action = "授权" if any(word in entry_text for word in ("授权", "授权公告")) else "申请"
        metric_variant = "授权发明专利" if local_action == "授权" else "申请发明专利"
        return ExtractedEvidence(
            metric_name="发明专利",
            metric_category="知识产权",
            value=None,
            unit="项",
            implicit_count=1.0,
            action=local_action,
            time_label=self._first_match(YEAR_PATTERN, entry_text),
            caliber_label=metric_variant,
            metric_variant=metric_variant,
            evidence_mode="itemized",
            evidence_role="primary",
            artifact_key=patent_no or title,
            artifact_title=title or patent_no or self.document_display_title(document),
            confidence=0.88,
            excerpt=entry_text[:240],
            block_id=block.block_id,
            page=block.page,
        )

    def _build_report_appendix_dissertation_entry(
        self,
        document: ParsedAcceptanceDocument,
        entry_text: str,
        block: ParsedAcceptanceBlock,
    ) -> ExtractedEvidence | None:
        if self._is_reference_citation_line(entry_text) or re.search(r"\[D\]", entry_text):
            return None
        title = self._appendix_entry_title(entry_text)
        if not title:
            return None
        author = self._appendix_entry_author(entry_text)
        display_title = f"硕士学位论文 - {title}"
        if author:
            display_title = f"{display_title}（{author}）"
        artifact_key = f"{self._normalize_dissertation_title_key(title)}:{author}" if author else self._normalize_dissertation_title_key(title)
        return ExtractedEvidence(
            metric_name="培养研究生",
            metric_category="人才培养",
            value=None,
            unit="名",
            implicit_count=1.0,
            action="培养",
            time_label=self._first_match(YEAR_PATTERN, entry_text),
            metric_variant="培养研究生",
            evidence_mode="itemized",
            evidence_role="primary",
            artifact_key=artifact_key,
            artifact_title=display_title,
            confidence=0.88,
            excerpt=entry_text[:240],
            block_id=block.block_id,
            page=block.page,
        )

    def _appendix_entry_author(self, entry_text: str) -> str:
        match = re.match(r"^\[\d+\]\s*([^\.。]{1,30})[\.。]", entry_text)
        if not match:
            return ""
        return self._clean_title(match.group(1))

    def _appendix_entry_title(self, entry_text: str) -> str:
        compact = self._clean_title(entry_text)
        if not compact:
            return ""
        body = re.sub(r"^\[\d+\]\s*", "", compact)
        body = re.split(r"\[(?:J|P|D)\]", body, maxsplit=1)[0]
        body = re.split(r"(?:\(|（)\s*(?:SCI|EI|CSCD|核心).*$", body, maxsplit=1)[0]
        body = re.sub(r"\s+", " ", body).strip(" .。;；,，")
        if not body:
            return ""
        author_split = re.match(r"^[^\.。]{1,120}[\.。]\s*(.+)$", body)
        if author_split:
            body = author_split.group(1).strip()
        body = re.sub(r"\s+", " ", body).strip(" .。;；,，")
        return self._clean_title(body)

    def _extract_list_count_from_text(self, text: str, metric_name: str) -> float | None:
        patterns = {
            "科技论文": [r"(?:论文|篇)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*篇"],
            "发明专利": [r"(?:专利|件|项)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(?:件|项)"],
            "培养研究生": [r"(?:研究生|名|人)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(?:名|人)"],
        }
        for pattern in patterns.get(metric_name, []):
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    def _extract_finance_evidence(self, document: ParsedAcceptanceDocument, doc_kind: str) -> list[ExtractedEvidence]:
        items: list[ExtractedEvidence] = []
        role = "primary" if doc_kind == "审计报告" else "supporting"
        for block in document.blocks:
            text = block.text
            for metric_name, value, unit, excerpt in self._extract_finance_metric_hits(text, doc_kind):
                year_label = self._infer_finance_time_label(text, document)
                caliber = self._infer_finance_caliber(excerpt)
                if doc_kind == "审计报告" and "审计" not in caliber:
                    caliber = f"{caliber} / 审计".strip(" /")
                items.append(
                    ExtractedEvidence(
                        metric_name=metric_name,
                        metric_category="产业效益",
                        value=value,
                        unit=unit,
                        implicit_count=0.0,
                        action="实现",
                        time_label=year_label,
                        caliber_label=caliber,
                        metric_variant=self._infer_finance_variant(text, metric_name),
                        evidence_mode="summary",
                        evidence_role=role,
                        evidence_nature="proof",
                        artifact_key=f"{metric_name}:{value}:{unit}:{self._first_match(YEAR_PATTERN, excerpt) or self._first_match(YEAR_PATTERN, text) or ''}",
                        artifact_title=self.document_display_title(document),
                        confidence=0.86 if doc_kind == "审计报告" else 0.65,
                        excerpt=excerpt[:240],
                        block_id=block.block_id,
                        page=block.page,
                    )
                )
        return self._dedupe_extracted(items)

    def _infer_finance_time_label(self, text: str, document: ParsedAcceptanceDocument) -> str:
        year = self._first_match(YEAR_PATTERN, text) or self._first_match(YEAR_PATTERN, document.text[:4000])
        if "累计" in text:
            return f"{year}年/累计" if year else "累计"
        if "当年" in text or "本年" in text:
            return f"{year}年/当年" if year else "当年"
        if "截至" in text:
            return f"{year}年/截至验收前" if year else "截至验收前"
        return f"{year}年" if year else ""

    def _extract_generic(
        self,
        document: ParsedAcceptanceDocument,
        doc_kind: str,
        *,
        exclude_metric_names: set[str] | None = None,
    ) -> list[ExtractedEvidence]:
        items: list[ExtractedEvidence] = []
        qualitative_metric_names = {"实验系统", "技术方案", "工程样机", "示范基地"}
        for spec in METRIC_SPECS:
            if exclude_metric_names and spec.canonical_name in exclude_metric_names:
                continue
            matched_block = self._find_best_block(document, spec)
            if not matched_block:
                continue
            matched_line = matched_block.text
            if doc_kind == "科技报告" and not self._report_line_supports_metric(matched_line, spec.canonical_name):
                continue
            if doc_kind == "验收申请" and not re.search(r"实际完成情况[:：]", matched_line):
                continue
            evidence_text = self._actual_segment(matched_line) if doc_kind == "验收申请" else matched_line
            value, unit = self._extract_value_and_unit(matched_line, spec)
            implicit_count = 0.0 if value is not None else self._implicit_count_from_doc_kind(doc_kind, spec)
            if value is None and implicit_count <= 0 and spec.canonical_name in qualitative_metric_names:
                if any(token in evidence_text for token in ("形成", "完成", "建成", "实现", "搭建", "研发")):
                    implicit_count = 1.0
            if value is None and implicit_count <= 0:
                continue
            items.append(
                ExtractedEvidence(
                    metric_name=spec.canonical_name,
                    metric_category=spec.category,
                    value=value,
                    unit=unit,
                    implicit_count=implicit_count,
                    action=self._infer_generic_action(evidence_text, spec.canonical_name),
                    time_label=self._first_match(YEAR_PATTERN, evidence_text) or self._first_match(YEAR_PATTERN, matched_line) or self._first_match(YEAR_PATTERN, document.text[:2000]),
                    caliber_label=self._infer_generic_caliber(evidence_text),
                    metric_variant=self._infer_generic_variant(evidence_text, spec.canonical_name),
                    evidence_mode="summary" if value is not None else "itemized",
                    evidence_role="derived" if implicit_count > 0 and value is None else "supporting",
                    artifact_key=self._fallback_artifact_key(document, spec.canonical_name),
                    artifact_title=self.document_display_title(document),
                    confidence=0.55 if value is not None else 0.45,
                    excerpt=evidence_text[:240],
                    block_id=matched_block.block_id,
                    page=matched_block.page,
                )
            )
        return self._dedupe_extracted(items)

    def _classify_doc_kind(self, document: ParsedAcceptanceDocument) -> str:
        head = self._classification_corpus(document)
        corpus = f"{document.file_name}\n{head}"
        lower_name = document.file_name.lower()
        if lower_name.endswith((".jpg", ".jpeg", ".png")):
            return "图片扫描件"
        strong_report_clues = (
            "验收自评价报告",
            "验收总结报告",
            "自评价报告",
            "结题报告",
            "项目总结报告",
        )
        if any(clue in corpus for clue in strong_report_clues):
            return "科技报告"
        strong_acceptance_clues = (
            "验收申请表",
            "科技计划项目验收申请表",
            "项目验收申请表",
            "项目验收申请书",
            "验收申请书",
        )
        if any(clue in corpus for clue in strong_acceptance_clues):
            return "验收申请"
        if self._looks_like_dissertation_document(document):
            return "学位论文"
        for label, clues in DOC_KIND_RULES:
            if label == "论文" and self._looks_like_dissertation_document(document):
                continue
            if any(clue in corpus for clue in clues):
                return label
        if PATENT_FALLBACK_NO_PATTERN.search(corpus):
            return "专利证书"
        if self._count_patent_segments(document) >= 2:
            return "专利证书"
        if self._looks_like_merged_journal_bundle(document):
            return "论文"
        if self._looks_like_paper_document(document.lines[:20]):
            return "论文"
        if not head.strip():
            return "空白或扫描件"
        return "其他材料"

    def _classification_corpus(self, document: ParsedAcceptanceDocument) -> str:
        text = (document.text or "").strip()
        if text:
            return text[: self.OCR_CLASSIFY_CHAR_LIMIT]
        return "\n".join(document.lines[:160])

    def _compact_patent_no(self, value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", "", value).strip().upper()

    def _patent_document_title(self, document: ParsedAcceptanceDocument) -> str:
        corpus = document.text[:4000]
        title = self._patent_title_from_text(document)
        title = self._clean_title(title)
        if title:
            head = "实用新型专利证书" if "实用新型" in corpus else "发明专利证书"
            return f"{head} - {title}"

        lines = [self._clean_title(line) for line in document.lines[:30] if self._clean_title(line)]
        for idx, line in enumerate(lines):
            if line in {"专利证书", "发明专利证书", "实用新型专利证书"}:
                for candidate in lines[idx + 1: idx + 8]:
                    if any(token in candidate for token in ("发明名称", "实用新型名称", "专利名称")):
                        match = PATENT_TITLE_PATTERN.search(candidate)
                        if match:
                            doc_head = line if line != "专利证书" else ("实用新型专利证书" if "实用新型" in candidate else "发明专利证书")
                            return f"{doc_head} - {self._clean_title(match.group(1))}"
        return ""

    def _patent_title_from_text(self, document: ParsedAcceptanceDocument) -> str:
        corpus = document.text[:4000]
        candidates: list[str] = []
        for pattern in (
            re.compile(r"(?:发明名称|专利名称|实用新型名称)[:：]\s*([^\n\r]{4,120})"),
            re.compile(r"(?:名称|项目名称)[:：]\s*([^\n\r]{4,120})"),
        ):
            match = pattern.search(corpus)
            if match:
                candidates.append(self._clean_title(match.group(1)))
        for line in document.lines[:40]:
            clean = self._clean_title(line)
            if not clean:
                continue
            if any(token in clean for token in ("发明名称", "专利名称", "实用新型名称")):
                match = PATENT_TITLE_PATTERN.search(clean)
                if match:
                    candidates.append(self._clean_title(match.group(1)))
            elif self._is_good_title_line(clean) and not any(token in clean for token in ("专利证书", "国家知识产权局")):
                candidates.append(clean)
        for candidate in candidates:
            if self._is_good_title_line(candidate) and not self._looks_like_address(candidate):
                return candidate
        return ""

    def _lookup_spec(self, metric_name: str) -> MetricSpec | None:
        for spec in METRIC_SPECS:
            if spec.canonical_name == metric_name:
                return spec
        return None

    def _find_best_block(self, document: ParsedAcceptanceDocument, spec: MetricSpec):
        doc_kind = self._classify_doc_kind(document)
        candidates: list[tuple[int, ParsedAcceptanceBlock]] = []
        for idx, block in enumerate(document.blocks):
            line = block.text
            if not any(alias in line for alias in spec.aliases):
                continue
            if doc_kind == "科技报告" and not self._report_line_supports_metric(line, spec.canonical_name):
                continue
            actual_segment = self._actual_segment(line)
            if not any(alias in actual_segment for alias in spec.aliases) and not any(
                alias in line for alias in spec.aliases
            ):
                continue
            score = 0
            if re.search(r"实际完成情况[:：]", line):
                score += 30
            elif "实际完成情况" in line:
                score += 12
            if "任务书约定目标" in line and not re.search(r"实际完成情况[:：]", line):
                score -= 6
            if "样机参数" in line and not re.search(r"实际完成情况[:：]", line):
                score -= 4
            value, _ = self._extract_value_and_unit(line, spec)
            if value is not None:
                score += 8
            if self._line_has_value_for_spec(actual_segment, spec):
                score += 6
            if any(marker in actual_segment for marker in ("已完成", "完成", "建成", "形成", "实现", "达到", "不小于", "小于")):
                score += 3
            if any(alias in actual_segment for alias in spec.aliases):
                score += 5
            score += max(0, 3 - min(idx, 3))
            candidates.append((score, block))
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
        for idx, line in enumerate(document.lines):
            if any(alias in line for alias in spec.aliases):
                if idx < len(document.blocks):
                    return document.blocks[idx]
        return None

    def _line_has_value_for_spec(self, line: str, spec: MetricSpec) -> bool:
        for unit in spec.units:
            if re.search(rf"\d+(?:\.\d+)?(?:\s*[-~～至到]\s*\d+(?:\.\d+)?)?\s*{re.escape(unit)}", line):
                return True
        for match in CHINESE_NUMBER_PATTERN.finditer(line):
            if match.group(2) in spec.units:
                return True
        return False

    def _find_first_nonempty_block(self, document: ParsedAcceptanceDocument) -> ParsedAcceptanceBlock | None:
        return document.blocks[0] if document.blocks else None

    def _extract_value_and_unit(self, line: str, spec: MetricSpec) -> tuple[float | None, str]:
        segment = self._actual_segment(line)
        unit = self._unit_from_table_line(line, spec)
        chinese_value = self._extract_chinese_number_value(segment, spec)
        if chinese_value:
            return chinese_value
        if spec.canonical_name == "检测范围":
            range_match = re.search(r"(?:检测范围|样检测范围)[^0-9]{0,16}(\d+(?:\.\d+)?)\s*[-~～至到]\s*(\d+(?:\.\d+)?)\s*(mg/L|cells/mL)", segment)
            if range_match:
                return float(range_match.group(2)), range_match.group(3)
        if spec.canonical_name == "检测频率":
            freq_match = re.search(r"(?:工作频率|检测工作频率)[^0-9]{0,16}(\d+(?:\.\d+)?)\s*(次/时|次)", segment)
            if freq_match:
                return float(freq_match.group(1)), freq_match.group(2)
        if spec.canonical_name == "培养研究生":
            total_match = re.search(r"(?:共培养研究生|培养研究生(?:数)?|研究生共)\s*(\d+(?:\.\d+)?)\s*(名|人)", segment)
            if total_match:
                return float(total_match.group(1)), total_match.group(2)
            people_matches = list(
                re.finditer(
                    r"(?:培养)?(?:硕士研究生|博士研究生|研究生|专业技术人员|专业技术人才|培养专业技术人才|相关技术人才)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(名|人)",
                    segment,
                )
            )
            if people_matches:
                total = sum(float(match.group(1)) for match in people_matches)
                return total, people_matches[0].group(2)
        if spec.canonical_name == "科普动画部数":
            for pattern in (
                re.compile(r"(?:完成)?(?:视频动画|科普动画|科普动漫微视频|科普影视作品|原创科普影视作品)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*部"),
                re.compile(r"(\d+(?:\.\d+)?)\s*部[^。；;\n]{0,32}(?:视频动画|科普动画|科普动漫微视频|科普影视作品|原创科普影视作品)"),
            ):
                match = pattern.search(segment)
                if match:
                    return float(match.group(1)), "部"
        if spec.canonical_name == "公益推广科普作品":
            matches: list[tuple[float, str]] = []
            for pattern in (
                re.compile(r"(?:用于)?公益推广[^。；;\n]{0,48}?(?:科普动画|影视动画作品|科普作品|科普影视作品)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*(套|册)"),
                re.compile(r"(?:共计|制作(?:了)?|完成|确保至少)?\s*(\d+(?:\.\d+)?)\s*(套|册)[^。；;\n]{0,56}(?:科普动画|科普作品|影视动画作品|公益推广)"),
            ):
                for match in pattern.finditer(segment):
                    matches.append((float(match.group(1)), match.group(2)))
            if matches:
                value, found_unit = max(matches, key=lambda item: item[0])
                return value, found_unit
        if spec.canonical_name == "提供资助方科普作品":
            provided_match = re.search(
                r"(?:提供给(?:资助方|甲方)部分|(?:直接)?提供给(?:资助方|甲方))[^0-9]{0,24}(?:共|共计|为)?\s*(\d+(?:\.\d+)?)(?:\s*(套|册))?",
                segment,
            )
            if provided_match:
                return float(provided_match.group(1)), provided_match.group(2) or "套"
            for pattern in (
                re.compile(r"(?:提供给(?:资助方|甲方)部分|(?:直接)?提供给(?:资助方|甲方))[^0-9]{0,24}(?:共|共计|为)?\s*(\d+(?:\.\d+)?)\s*(套|册)"),
                re.compile(r"(?:直接)?提供给(?:资助方|甲方)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*(套|册)"),
                re.compile(r"(?:其中|其中至少|其中不少于|至少|不少于)\s*(\d+(?:\.\d+)?)\s*(套|册)[^。；;\n]{0,32}(?:直接)?提供给(?:资助方|甲方)"),
                re.compile(r"向(?:甲方|资助方)提供[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(套|册)"),
            ):
                match = pattern.search(segment)
                if match:
                    return float(match.group(1)), match.group(2)
        if spec.canonical_name == "科普推广点击量":
            for pattern in (
                re.compile(r"(?:累计网络点击量|推广总量|累计总流量|网络点击量)[^0-9]{0,20}(\d+(?:\.\d+)?)\s*(万人次|人次|人)"),
                re.compile(r"(\d+(?:\.\d+)?)\s*(万人次|人次|人)[^。；;\n]{0,32}(?:累计网络点击量|推广总量|累计总流量|网络点击量|公众参与)"),
            ):
                match = pattern.search(segment)
                if match:
                    return float(match.group(1)), match.group(2)
        candidates: list[tuple[int, float, str]] = []
        for found_unit in spec.units:
            pattern = re.compile(rf"(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*({re.escape(found_unit)})")
            for match in pattern.finditer(segment):
                candidates.append((match.start(), float(match.group(2) or match.group(1)), match.group(3)))
        if not candidates and unit:
            for match in re.finditer(r"(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?", segment):
                candidates.append((match.start(), float(match.group(2) or match.group(1)), unit))
        if candidates:
            alias_positions = [segment.index(alias) for alias in spec.aliases if alias in segment]
            if alias_positions:
                alias_pos = min(alias_positions)
                after_alias = [item for item in candidates if item[0] >= alias_pos]
                ranked = after_alias or candidates
                ranked.sort(key=lambda item: abs(item[0] - alias_pos))
                return ranked[0][1], ranked[0][2]
            return candidates[0][1], candidates[0][2]
        return None, unit or (spec.units[0] if spec.units else "")

    def _extract_chinese_number_value(self, text: str, spec: MetricSpec) -> tuple[float, str] | None:
        for match in CHINESE_NUMBER_PATTERN.finditer(text):
            unit = match.group(2)
            if unit not in spec.units:
                continue
            value = self._parse_chinese_numeral(match.group(1))
            if value is None:
                continue
            return float(value), unit
        return None

    def _parse_chinese_numeral(self, text: str) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        if text == "十":
            return 10
        if "十" in text:
            parts = text.split("十", 1)
            tens = CHINESE_NUMERAL_MAP.get(parts[0], 1 if parts[0] == "" else -1)
            ones = CHINESE_NUMERAL_MAP.get(parts[1], 0 if parts[1] == "" else -1)
            if tens < 0 or ones < 0:
                return None
            return tens * 10 + ones
        return CHINESE_NUMERAL_MAP.get(text)

    def _parse_labeled_table_fields(self, line: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for part in re.split(r"[;；]", str(line or "")):
            chunk = re.sub(r"^\[[^\]]+\]\s*", "", part.strip())
            if not chunk:
                continue
            match = re.match(r"^([^:：]+)[:：](.*)$", chunk)
            if not match:
                continue
            key = " ".join(match.group(1).split())
            value = match.group(2).strip()
            if key and value:
                fields[key] = value
        return fields

    def _actual_completion_column_from_pipe(self, line: str) -> str:
        if "人才培养" in line or "指标:人才培养" in line:
            match = re.search(r"[:：]\s*(培养(?:硕士研究生|研究生)[^;；|]{0,48})", line)
            if match:
                return match.group(1).strip()
        if "|" not in line:
            return ""
        parts = [re.sub(r"^\[[^\]]+\]\s*", "", part.strip()) for part in line.split("|")]
        parts = [part for part in parts if part]
        if not parts:
            return ""
        for part in parts:
            if part.startswith("其") or part.startswith("已完成"):
                return part
        if "样机参数" in parts[0] or any("0-200mg" in part for part in parts[:3]):
            for part in reversed(parts):
                if part in {"有限公司"} or part.startswith("有限公司"):
                    continue
                if "0-200mg" in part and "cells/mL" not in part:
                    continue
                if len(part) >= 8:
                    return part
        if len(parts) >= 2:
            return parts[-1]
        return ""

    def _metric_snippet_from_actual(self, actual_text: str, spec: MetricSpec) -> str:
        text = " ".join((actual_text or "").split())
        if not text:
            return ""
        if spec.canonical_name in {"实验系统", "技术方案", "工程样机", "示范基地", "科技论文", "发明专利", "培养研究生"}:
            return text[:160]
        if spec.canonical_name in SCIENCE_POPULARIZATION_METRIC_NAMES:
            aliases = tuple(dict.fromkeys((spec.canonical_name, *spec.aliases)))
            alias_pattern = "|".join(re.escape(alias) for alias in aliases if alias)
            match = re.search(rf"[^。；;\n]{{0,80}}(?:{alias_pattern})[^。；;\n]{{0,120}}", text)
            if match:
                return match.group(0).strip()
            return text[:240]
        if spec.canonical_name == "检测范围":
            match = re.search(r"其?检测范围为?\s*[^;；|]{0,48}", text)
            if match:
                return match.group(0).strip()
        if spec.canonical_name == "检测频率":
            match = re.search(r"(?:其)?(?:检测)?工作频率[^;；|]{0,32}", text)
            if match:
                return match.group(0).strip()
        if spec.canonical_name == "检测标准偏差":
            match = re.search(r"(?:标准\s*[偏误]差|准\s*误差)[^;；|]{0,40}", text)
            if match:
                return match.group(0).strip()
        if spec.canonical_name == "最大测量误差":
            match = re.search(r"最大测量误差[^;；|]{0,32}", text)
            if match:
                return match.group(0).strip()
        return text[:120]

    def _actual_segment(self, line: str) -> str:
        fields = self._parse_labeled_table_fields(line)
        if "实际完成情况" in fields:
            return fields["实际完成情况"].strip()
        pipe_actual = self._actual_completion_column_from_pipe(line)
        if pipe_actual:
            return pipe_actual
        compact = " ".join((line or "").split())
        match = re.search(r"实际完成情况[:：]\s*([^;；|]+)", compact)
        if match:
            return match.group(1).strip(" :：;；|，,")
        for marker in ("实际完成情况", "已完成"):
            if marker in compact:
                actual = compact.split(marker, 1)[1]
                for tail_marker in (
                    "备注",
                    "备注说明",
                    "支撑材料",
                    "附件",
                    "证明材料",
                    "考核方式",
                    "完成形式",
                    "任务书约定目标",
                ):
                    if tail_marker in actual:
                        actual = actual.split(tail_marker, 1)[0]
                return actual.strip(" :：;；|，,")
        return compact

    def _build_acceptance_table_item(
        self,
        *,
        document: ParsedAcceptanceDocument,
        block: ParsedAcceptanceBlock,
        spec: MetricSpec,
        line: str,
    ) -> ExtractedEvidence | None:
        actual_text = self._actual_segment(line)
        if not actual_text:
            return None
        metric_text = self._metric_snippet_from_actual(actual_text, spec) or actual_text
        if spec.canonical_name in {"检测范围", "检测频率", "检测标准偏差", "最大测量误差"}:
            metric_text = self._metric_snippet_from_actual(actual_text, spec) or metric_text
        value, unit = self._extract_value_and_unit(metric_text, spec)
        implicit_count = 0.0
        if value is None and spec.canonical_name in {"实验系统", "技术方案", "工程样机", "示范基地"}:
            if any(token in actual_text for token in ("形成", "完成", "建成", "实现", "搭建", "研发", "已在", "累计")):
                implicit_count = 1.0
        if value is None and implicit_count <= 0:
            return None
        return ExtractedEvidence(
            metric_name=spec.canonical_name,
            metric_category=spec.category,
            value=value,
            unit=unit,
            implicit_count=implicit_count,
            action=self._infer_generic_action(metric_text, spec.canonical_name),
            time_label=self._first_match(YEAR_PATTERN, metric_text) or self._first_match(YEAR_PATTERN, line),
            caliber_label=self._infer_generic_caliber(metric_text),
            metric_variant=spec.canonical_name,
            evidence_mode="summary" if value is not None else "itemized",
            evidence_role="derived" if implicit_count > 0 and value is None else "supporting",
            artifact_key=self._fallback_artifact_key(document, spec.canonical_name),
            artifact_title=self.document_display_title(document),
            confidence=0.88,
            excerpt=metric_text[:240],
            block_id=block.block_id,
            page=block.page,
        )

    def _extract_acceptance_kpi_table_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        row_hints: list[tuple[str, tuple[str, ...]]] = [
            ("实验系统", ("荧光检测及信息处理实验系统", "信息处理实验系统", "实验系统")),
            ("技术方案", ("技术方案", "实验解决方案", "完整的实验解决方案", "监测模型的构建")),
            ("工程样机", ("在线监测工程样机", "工程样机", "原理性样机")),
            ("示范基地", ("监测示范基地", "示范基地", "生产示范基地", "示范基地")),
            ("科技论文", ("发表论文", "公开发表学术论文", "期刊及会议学术论文", "学术论文")),
            ("科技报告", ("撰写科技报告", "科技报告")),
            ("决策咨询报告", ("撰写决策参考报告", "决策参考报告", "决策咨询报告")),
            ("研究报告", ("撰写研究报告", "项目研究报告", "研究报告")),
            ("发明专利", ("申请发明专利", "申请相关发明专利", "发明专利")),
            ("培养研究生", ("培养硕士研究生", "培养研究生", "硕士研究生", "研究生")),
            ("科普动画部数", ("视频动画", "科普动画", "科普动漫微视频", "科普影视作品", "原创科普影视作品")),
            ("公益推广科普作品", ("公益推广", "科普动画作品", "影视动画作品", "科普作品", "原创科普动画影视作品")),
            ("提供资助方科普作品", ("提供给资助方", "提供给甲方", "直接提供给资助方")),
            ("科普推广点击量", ("累计网络点击量", "推广总量", "累计总流量", "网络点击量")),
            ("开展科普活动", ("科普活动", "科学普及场次", "科普推广会议")),
        ]
        items: list[ExtractedEvidence] = []
        for block in document.blocks:
            line = block.text
            if not re.search(r"实际完成情况[:：]", line):
                continue
            fields = self._parse_labeled_table_fields(line)
            actual_text = fields.get("实际完成情况", self._actual_segment(line))
            if not actual_text:
                continue
            searchable = f"{line} {actual_text}"
            if DISJUNCTIVE_SCIENCE_REPORT_PATTERN.search(re.sub(r"\s+", "", searchable)):
                spec = self._lookup_spec("科技报告")
                if spec is not None and any(token in searchable for token in ("科技报告", "研究报告")):
                    item = self._build_acceptance_table_item(
                        document=document,
                        block=block,
                        spec=spec,
                        line=line,
                    )
                    if item is not None:
                        items.append(
                            ExtractedEvidence(
                                metric_name=item.metric_name,
                                metric_category=item.metric_category,
                                value=item.value,
                                unit=item.unit,
                                implicit_count=item.implicit_count,
                                action=item.action,
                                subject_scope=item.subject_scope,
                                time_label=item.time_label,
                                caliber_label=item.caliber_label,
                                metric_variant=SCIENCE_REPORT_DISJUNCTIVE_VARIANT,
                                evidence_mode=item.evidence_mode,
                                evidence_role=item.evidence_role,
                                evidence_nature=item.evidence_nature,
                                artifact_key=item.artifact_key,
                                artifact_title=item.artifact_title,
                                confidence=item.confidence,
                                excerpt=item.excerpt,
                                block_id=item.block_id,
                                page=item.page,
                            )
                        )
                continue
            for metric_name, hints in row_hints:
                spec = self._lookup_spec(metric_name)
                if spec is None:
                    continue
                if not any(hint in searchable for hint in hints):
                    continue
                item = self._build_acceptance_table_item(
                    document=document,
                    block=block,
                    spec=spec,
                    line=line,
                )
                if item is not None:
                    items.append(item)
        return self._dedupe_extracted(items)

    def _extract_acceptance_sample_machine_evidence(self, document: ParsedAcceptanceDocument) -> list[ExtractedEvidence]:
        metric_aliases = (
            ("检测范围", ("检测范围", "样检测范围")),
            ("检测频率", ("检测工作频率", "工作频率")),
            ("检测标准偏差", ("检测标准偏差", "标准偏差", "标准误差")),
            ("最大测量误差", ("最大测量误差", "测量误差")),
            ("培养研究生", ("人才培养", "培养硕士研究生", "培养研究生", "硕士研究生")),
        )
        items: list[ExtractedEvidence] = []
        for block in document.blocks:
            line = block.text
            if "样机参数" not in line:
                continue
            actual_text = self._actual_segment(line)
            if not actual_text:
                continue
            for metric_name, aliases in metric_aliases:
                spec = self._lookup_spec(metric_name)
                if spec is None:
                    continue
                searchable = f"{line} {actual_text}"
                if not any(alias in searchable for alias in aliases):
                    continue
                item = self._build_acceptance_table_item(
                    document=document,
                    block=block,
                    spec=spec,
                    line=line,
                )
                if item is not None:
                    items.append(item)
        return self._dedupe_extracted(items)

    def _unit_from_table_line(self, line: str, spec: MetricSpec) -> str:
        for unit in spec.units:
            if re.search(rf"指标单位[:：][^；;。]*{re.escape(unit)}", line) or re.search(rf"单位[:：][^；;。]*{re.escape(unit)}", line):
                return unit
        return ""

    def _extract_finance_value(self, line: str) -> tuple[float, str] | None:
        for unit in ("亿元", "万元", "元"):
            match = re.search(rf"(\d+(?:\.\d+)?)\s*({re.escape(unit)})", line)
            if match:
                return float(match.group(1)), match.group(2)
        return None

    def _extract_finance_metric_hits(self, text: str, doc_kind: str) -> list[tuple[str, float, str, str]]:
        items: list[tuple[str, float, str, str]] = []
        actual_segments = self._finance_segments(text)
        seen: set[tuple[str, float, str]] = set()
        for segment in actual_segments:
            if doc_kind != "审计报告" and not self._looks_like_actual_finance_segment(segment):
                continue
            for metric_name, aliases in FINANCE_METRIC_PATTERNS:
                if not any(alias in segment for alias in aliases):
                    continue
                value_unit = self._extract_finance_value_for_metric(segment, metric_name)
                if not value_unit:
                    continue
                value, unit = value_unit
                key = (metric_name, value, unit)
                if key in seen:
                    continue
                seen.add(key)
                items.append((metric_name, value, unit, segment))
        return items

    def _looks_like_actual_finance_segment(self, text: str) -> bool:
        actual_markers = ("实际", "已完成", "完成情况", "项目新增", "新增收入合计", "占预算", "任务完成情况")
        target_markers = ("任务书约定目标", "预期目标", "考核目标", "预算目标")
        if any(marker in text for marker in actual_markers):
            return True
        if any(marker in text for marker in target_markers):
            return False
        return False

    def _extract_finance_value_for_metric(self, text: str, metric_name: str) -> tuple[float, str] | None:
        for pattern in FINANCE_FIELD_PATTERNS.get(metric_name, ()):
            match = pattern.search(text)
            if match:
                return float(match.group(1)), match.group(2)
        return None

    def _finance_segments(self, text: str) -> list[str]:
        compact = " ".join((text or "").split())
        if not compact:
            return []
        segments: list[str] = []
        if "实际完成情况" in compact:
            segments.append(compact.split("实际完成情况", 1)[1])
        if "已完成" in compact:
            segments.append(compact.split("已完成", 1)[1])
        if "任务完成情况" in compact:
            segments.append(compact.split("任务完成情况", 1)[1])
        if not segments:
            segments.append(compact)
        deduped: list[str] = []
        seen = set()
        for segment in segments:
            normalized = segment.strip(" :：;；|")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _infer_generic_action(self, text: str, metric_name: str) -> str:
        if metric_name in {"发明专利", "实用新型专利"}:
            return "申请" if "申请" in text else "授权" if "授权" in text else "申请/授权"
        if metric_name == "科技论文":
            return "发表"
        if metric_name == "培养研究生":
            return "培养"
        if metric_name in {"实验系统", "技术方案"}:
            return "形成"
        if metric_name == "工程样机":
            return "完成"
        if metric_name == "示范基地":
            return "建成"
        if metric_name in {"检测范围", "检测频率", "检测标准偏差", "最大测量误差"}:
            return "达到"
        if metric_name == "高效杀虫功能微生物":
            return "筛选"
        if metric_name in {"杀蚜虫新型生物制剂", "水分散粒剂制备技术"}:
            return "研制"
        if metric_name in {"田间应用防效", "化学农药减施率", "新增销售收入", "新增利税"}:
            return "实现"
        if "申请" in text:
            return "申请"
        if "授权" in text:
            return "授权"
        if "发表" in text:
            return "发表"
        if "培养" in text:
            return "培养"
        if "制定" in text or "建立" in text or "形成" in text:
            return "制定"
        if "新增" in text or "达到" in text or "完成" in text:
            return "实现"
        return ""

    def _infer_generic_caliber(self, text: str) -> str:
        hits = [token for token in ("新增", "累计", "当年", "含税", "不含税", "发明", "授权", "企业标准", "田间", "减施") if token in text]
        if "申请" in text and not any(token in text for token in ("验收申请", "申请表", "项目验收申请")):
            hits.append("申请")
        return " / ".join(dict.fromkeys(hits))

    def _infer_generic_variant(self, text: str, metric_name: str) -> str:
        actual = self._actual_segment(text)
        if metric_name == "发明专利":
            if "申请" in actual:
                return "申请发明专利"
            if "授权" in actual:
                return "授权发明专利"
        if metric_name == "技术标准" and "企业标准" in text:
            return "企业标准"
        if metric_name in {"实验系统", "技术方案", "工程样机", "示范基地", "检测范围", "检测频率", "检测标准偏差", "最大测量误差"}:
            return metric_name
        return metric_name

    def _infer_finance_variant(self, text: str, metric_name: str) -> str:
        if metric_name == "新增销售收入":
            if "主营业务收入" in text:
                return "主营业务收入"
            if "营业收入" in text:
                return "营业收入"
            if "销售收入" in text:
                return "销售收入"
        if metric_name == "新增利税":
            if "净利润" in text:
                return "净利润"
            if "利润总额" in text:
                return "利润总额"
            if "税收" in text:
                return "税收"
        return metric_name

    def _infer_finance_caliber(self, text: str) -> str:
        hits = [token for token in ("新增", "累计", "当年", "含税", "不含税", "审计", "实际", "预算") if token in text]
        if not hits:
            return "财务口径待核"
        caliber = list(dict.fromkeys(hits))
        if "含税" in caliber and "不含税" in caliber:
            caliber.append("税口径冲突")
        if "当年" in caliber and "累计" in caliber:
            caliber.append("期间口径冲突")
        return " / ".join(dict.fromkeys(caliber))

    def _paper_title(self, document: ParsedAcceptanceDocument) -> str:
        lines = [self._clean_title(line) for line in document.lines[:20] if self._clean_title(line)]
        candidates: list[tuple[int, int, str]] = []
        for idx, line in enumerate(lines[:12]):
            score = self._paper_title_score(lines, idx, line)
            if score > 0:
                candidates.append((score, -idx, line))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]
        candidate = self._best_title_candidate(lines)
        if candidate:
            return candidate
        return self._clean_title(document.file_name)

    def _clean_title(self, text: str) -> str:
        return TITLE_CLEAN_PATTERN.sub(" ", text or "").strip()

    def _fallback_artifact_key(self, document: ParsedAcceptanceDocument, prefix: str) -> str:
        return f"{prefix}:{document.file_name}"

    def _project_name_from_lines(self, lines: list[str]) -> str:
        for idx, line in enumerate(lines[:40]):
            match = TITLE_PREFIX_PATTERN.match(line)
            if match:
                return match.group(1).strip()
            if line == "项目名称" and idx + 1 < len(lines):
                return lines[idx + 1]
        return ""

    def _report_type_from_lines(self, lines: list[str]) -> str:
        report_tokens = (
            "验收自评价报告",
            "自评价报告",
            "应用证明",
            "试验总结",
            "研究报告",
            "工作总结",
            "检测报告",
            "审计报告",
            "情况说明",
        )
        for line in lines[:40]:
            for token in report_tokens:
                if token in line:
                    return token
        return ""

    def _paired_title(self, lines: list[str]) -> str:
        if not lines:
            return ""
        lead = lines[0]
        if lead in {"应用证明", "情况说明", "试验总结", "研究报告", "检测报告", "审计报告"}:
            for line in lines[1:10]:
                if self._is_good_title_line(line):
                    return f"{lead} - {line}"
        return ""

    def _best_title_candidate(self, lines: list[str]) -> str:
        cover = self._cover_title(lines)
        if cover:
            return cover
        for line in lines[:40]:
            if self._is_good_title_line(line):
                return line
        toc_topics = [title for title in (self._toc_topic_title(line) for line in lines[:120]) if title]
        for title in toc_topics:
            if any(token in title for token in ("应用效果", "应用试验", "试验总结", "应用证明", "研究报告")):
                return title
        if toc_topics:
            return toc_topics[0]
        for line in lines[:120]:
            if self._is_fallback_topic_line(line):
                return line
        return ""

    def _cover_title(self, lines: list[str]) -> str:
        for idx, line in enumerate(lines[:16]):
            if line in {"专利证书", "发明专利证书", "实用新型专利证书", "计算机软件著作权登记证书"}:
                next_line = next((candidate for candidate in lines[idx + 1: idx + 6] if self._is_good_title_line(candidate)), "")
                return f"{line} - {next_line}".strip(" -") if next_line else line
            if line in {"应用证明", "情况说明", "研究报告", "试验总结"}:
                next_line = next((candidate for candidate in lines[idx + 1: idx + 6] if self._is_good_title_line(candidate)), "")
                if next_line:
                    return f"{line} - {next_line}"
        return ""

    def _is_good_title_line(self, line: str) -> bool:
        if len(line) < 6 or len(line) > 80:
            return False
        if line in {"目录", "编报要求"}:
            return False
        if line.startswith("V") and re.fullmatch(r"V\d+", line):
            return False
        if re.fullmatch(r"附件\s*\d+", line):
            return False
        if GENERIC_FILE_NAME_PATTERN.fullmatch(line):
            return False
        if PAGE_LEADER_PATTERN.search(line):
            return False
        if re.match(r"^\d+(\.\d+)*\s+", line):
            return False
        if re.match(r"^[（(]?[一二三四五六七八九十0-9]+[)）]\s*", line):
            return False
        if any(token in line for token in ("项目编号", "负责人", "承担单位", "河北省科学技术厅 制")):
            return False
        return True

    def _looks_like_address(self, line: str) -> bool:
        return bool(
            re.search(r"(省|市|区|县|镇|乡|街|路|号楼|楼|层|室|园|小区)", line)
            and re.search(r"\d", line)
        )

    def _is_fallback_topic_line(self, line: str) -> bool:
        if PAGE_LEADER_PATTERN.search(line):
            return False
        if len(line) < 8 or len(line) > 90:
            return False
        topic_tokens = ("应用效果", "应用试验", "试验总结", "研究报告", "自评价报告", "应用证明", "防治", "杀虫剂", "蚜虫")
        return any(token in line for token in topic_tokens)

    def _looks_like_paper_document(self, lines: list[str]) -> bool:
        joined = "\n".join(lines)
        lower = joined.lower()
        reject_tokens = (
            "河北省科技计划项目",
            "科技计划项目",
            "项目任务书",
            "验收申请表",
            "验收申请书",
            "项目编号",
            "承担单位",
            "项目负责人",
            "河北省科学技术厅",
        )
        if any(token in joined for token in reject_tokens):
            return False
        signals = 0
        if "research article" in lower:
            signals += 1
        if "abstract" in lower:
            signals += 1
        if "keywords" in lower:
            signals += 1
        if DOI_PATTERN.search(joined):
            signals += 1
        if "received" in lower and "accepted" in lower:
            signals += 1
        if "journal homepage" in lower or "vol." in lower:
            signals += 1
        if "corresponding author" in lower or "corresponding authors" in lower:
            signals += 1
        if "materials and methods" in lower or "introduction" in lower:
            signals += 1
        if ("摘要" in joined or "摘 要" in joined) and JOURNAL_NAME_PATTERN.search(joined):
            signals += 2
        if JOURNAL_ISSUE_HEADER_PATTERN.search(joined):
            signals += 1
        if DISSERTATION_HEADER_PATTERN.search(joined) and ("论文题目" in joined or "作者姓名" in joined):
            return False
        return signals >= 3

    def _looks_like_paper_evidence(self, document: ParsedAcceptanceDocument) -> bool:
        lines = [self._clean_title(line) for line in document.lines[:40] if self._clean_title(line)]
        if not lines:
            return False
        joined = "\n".join(lines)
        hard_reject_tokens = (
            "河北省科技计划项目",
            "科技计划项目",
            "项目任务书",
            "验收申请表",
            "验收申请书",
            "项目编号",
            "承担单位",
            "项目负责人",
            "河北省科学技术厅",
            "用于后期论文发表、专利申请",
        )
        if any(token in joined for token in hard_reject_tokens):
            return False
        if self._looks_like_dissertation_document(document):
            return False
        if self._looks_like_paper_document(lines):
            return True
        title = self._paper_title(document)
        lower_title = title.lower()
        if not title or len(title) < 16:
            return False
        reject_tokens = (
            "防治蚜虫新型微生物杀虫剂创制与应用关键技术",
            "科技计划项目",
            "项目任务书",
            "验收申请",
            "自评价报告",
            "研究报告",
            "工作总结",
            "应用证明",
            "试验总结",
            "情况说明",
        )
        if any(token in title for token in reject_tokens):
            return False
        head = "\n".join(lines[:20]).lower()
        positive_tokens = (
            "research article",
            "abstract",
            "keywords",
            "doi",
            "received",
            "accepted",
            "corresponding author",
            "journal",
            "vol.",
            "introduction",
            "materials and methods",
            "results",
            "discussion",
        )
        return any(token in head or token in lower_title for token in positive_tokens)

    def _paper_title_score(self, lines: list[str], idx: int, line: str) -> int:
        lower = line.lower()
        if len(line) < 16 or len(line) > 220:
            return 0
        if line.startswith(("(", "（", "Fig", "Figure", "表")):
            return 0
        if lower.startswith("study on detection") or "loss function" in lower or "sample number" in lower:
            return 0
        if any(
            token in lower
            for token in (
                "http",
                "doi",
                "journal homepage",
                "to cite this article",
                "to link to this article",
                "article views",
                "view supplementary material",
                "view crossmark data",
                "full terms & conditions",
                "published online",
                "received ",
                "accepted ",
                "keywords",
                "abstract",
                "introduction",
                "materials and methods",
                "results",
                "discussion",
                "contact ",
                "corresponding author",
                "corresponding authors",
            )
        ):
            return 0
        if re.fullmatch(r"[A-Z][A-Z .&:()\-0-9]{8,}", line):
            return 0
        if re.match(r"^\d+\s+[A-Z][a-z].*Genes Genet", line):
            return 0
        if lower.startswith("issn:") or lower.startswith("www."):
            return 0
        score = 1
        if idx + 1 < len(lines) and self._looks_like_author_line(lines[idx + 1]):
            score += 5
        if idx + 2 < len(lines) and self._looks_like_affiliation_line(lines[idx + 2]):
            score += 2
        if idx > 0:
            prev = lines[idx - 1].lower()
            if any(token in prev for token in ("doi", "research article", "journal homepage", "vol.", "article")):
                score += 2
        if " of " in lower or " and " in lower:
            score += 1
        if re.search(r"[a-z]{4,}", line) and not re.fullmatch(r"[A-Za-z .&:-]+", line):
            score += 1
        if line[0].isupper() and not line.endswith("."):
            score += 1
        return score

    def _looks_like_author_line(self, line: str) -> bool:
        lower = line.lower()
        if len(line) < 12 or len(line) > 260:
            return False
        if any(token in lower for token in ("abstract", "keywords", "received", "accepted", "introduction", "doi", "@")):
            return False
        if "&" in line or " and " in lower:
            return True
        commas = line.count(",")
        if commas >= 2 and re.search(r"[A-Z][a-z]+", line):
            return True
        return False

    def _looks_like_affiliation_line(self, line: str) -> bool:
        lower = line.lower()
        affiliation_tokens = ("university", "institute", "laboratory", "academy", "department", "college", "school", "china")
        return any(token in lower for token in affiliation_tokens)

    def _toc_topic_title(self, line: str) -> str:
        if not PAGE_LEADER_PATTERN.search(line):
            return ""
        topic = PAGE_LEADER_PATTERN.split(line, 1)[0].strip()
        topic = re.sub(r"^\d+(?:\.\d+)*\s*", "", topic).strip()
        topic = re.sub(r"^[（(]?[一二三四五六七八九十]+[)）]?\s*", "", topic).strip()
        if len(topic) < 8 or len(topic) > 80:
            return ""
        if topic in {"目录", "引言", "小结"}:
            return ""
        if not any(token in topic for token in ("应用效果", "应用试验", "试验总结", "研究报告", "应用证明", "防治", "杀虫剂", "蚜虫", "微生物")):
            return ""
        return topic

    def _first_match(self, pattern: re.Pattern[str], text: str) -> str:
        match = pattern.search(text)
        if not match:
            return ""
        if match.lastindex:
            return match.group(1)
        return match.group(0)

    def _dedupe_extracted(self, items: list[ExtractedEvidence]) -> list[ExtractedEvidence]:
        seen: set[tuple[str, str, float | None, str]] = set()
        deduped: list[ExtractedEvidence] = []
        for item in items:
            key = (
                item.metric_name,
                item.artifact_key,
                item.value,
                item.unit,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _dedupe_acceptance_summary_by_metric(self, items: list[ExtractedEvidence]) -> list[ExtractedEvidence]:
        """验收申请表同一指标只保留置信度最高的一条摘要证据。"""
        itemized: list[ExtractedEvidence] = []
        best_summary: dict[str, ExtractedEvidence] = {}

        def is_better(candidate: ExtractedEvidence, previous: ExtractedEvidence) -> bool:
            if candidate.value is not None and previous.value is None:
                return True
            if candidate.value is None and previous.value is not None:
                return False
            if len(candidate.excerpt) > len(previous.excerpt) + 12:
                return True
            return candidate.confidence > previous.confidence

        for item in items:
            if item.evidence_mode == "itemized":
                itemized.append(item)
                continue
            previous = best_summary.get(item.metric_name)
            if previous is None or is_better(item, previous):
                best_summary[item.metric_name] = item
        return [*itemized, *best_summary.values()]

    def _implicit_count_from_doc_kind(self, doc_kind: str, spec: MetricSpec) -> float:
        if doc_kind == "专利证书" and spec.canonical_name in {"发明专利", "实用新型专利"}:
            return 1.0
        if doc_kind == "论文" and spec.canonical_name == "科技论文":
            return 1.0
        if doc_kind == "软件著作权" and spec.canonical_name == "软件著作权":
            return 1.0
        if doc_kind == "科技报告" and spec.canonical_name in {"科技报告", "研究报告"}:
            return 1.0
        if doc_kind in {"验收申请", "科技报告", "其他材料"} and spec.canonical_name in {"实验系统", "技术方案", "工程样机", "示范基地"}:
            return 1.0
        if doc_kind == "审计报告" and spec.canonical_name in {"新增销售收入", "新增利税"}:
            return 0.0
        return 0.0
