"""任务书 KPI 承诺抽取。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.accept.models import KPICommitment, ParsedAcceptanceDocument, MetricEvaluationLayer


@dataclass(frozen=True)
class MetricSpec:
    category: str
    canonical_name: str
    aliases: tuple[str, ...]
    units: tuple[str, ...]
    aggregation: str = "sum"
    layer: MetricEvaluationLayer = "generic"


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("技术指标", "实验系统", ("实验系统", "荧光检测实验系统", "信息处理实验系统", "实验解决方案"), ("套",), "max", "technical"),
    MetricSpec("技术指标", "技术方案", ("技术方案", "整体方案", "实验方案", "研究方案", "完整的技术方案", "一套的技术方案", "方案及资料"), ("套", "份"), "max", "technical"),
    MetricSpec("技术指标", "工程样机", ("工程样机", "在线监测工程样机", "监测工程样机"), ("套",), "max", "technical"),
    MetricSpec("技术指标", "示范基地", ("示范基地", "生产示范基地", "监测示范基地"), ("个", "座"), "max", "technical"),
    MetricSpec("质量指标", "检测范围", ("检测范围", "样机检测范围", "样检测范围", "测量范围"), ("mg/L", "cells/mL"), "max", "technical"),
    MetricSpec("质量指标", "检测频率", ("检测工作频率", "工作频率"), ("次/时", "次"), "max", "technical"),
    MetricSpec("质量指标", "检测标准偏差", ("检测标准偏差",), ("%",), "max", "technical"),
    MetricSpec("质量指标", "最大测量误差", ("最大测量误差",), ("%",), "max", "technical"),
    MetricSpec("知识产权", "发明专利", ("申请发明专利", "发明专利", "专利申请", "授权发明专利"), ("项", "件"), "sum", "deliverable"),
    MetricSpec("知识产权", "实用新型专利", ("实用新型专利",), ("项", "件"), "sum", "deliverable"),
    MetricSpec("知识产权", "软件著作权", ("软件著作权", "软著"), ("项", "件"), "sum", "deliverable"),
    MetricSpec("成果产出", "科技论文", ("发表论文", "发表文章", "发表学术论文", "发表相关论文", "核心期刊以上论文", "高水平研究论文", "科技论文", "学术论文", "试验报告/论文", "相关论文", "论文"), ("篇",), "sum", "deliverable"),
    MetricSpec("成果产出", "科技报告", ("科技报告",), ("份", "篇"), "sum", "deliverable"),
    MetricSpec("成果产出", "研究报告", ("研究报告", "调研报告"), ("份", "篇"), "sum", "deliverable"),
    MetricSpec("成果产出", "决策咨询报告", ("决策咨询报告", "决策参考报告"), ("份", "篇"), "sum", "deliverable"),
    MetricSpec("成果产出", "技术标准", ("制定技术标准", "技术标准", "地方标准", "行业标准", "国家标准", "企业标准"), ("项", "件"), "sum", "deliverable"),
    MetricSpec("成果产出", "检测分析方法", ("检测分析方法", "建立检测分析方法"), ("个", "项"), "sum", "technical"),
    MetricSpec("技术指标", "高效杀虫功能微生物", ("优选出高效杀虫功能微生物", "高效杀虫功能微生物", "高效杀虫 功能微生物", "高效杀虫功能微 生物", "筛选高效杀虫功能微生物", "筛选高效 杀虫功能 微生物", "杀虫功能微生物", "杀虫功能 微生物", "功能微生物菌株", "菌株数量"), ("株",), "max", "technical"),
    MetricSpec("技术指标", "杀蚜虫新型生物制剂", ("研制出杀蚜虫新型生物制剂", "杀蚜虫新型生物制剂", "杀蚜虫新型微生物制剂", "新型生物制剂", "新型微生物制剂", "微生物制剂", "新型微生物杀虫剂", "新型微生物 杀虫剂", "微生物杀虫剂", "微生物 杀虫剂", "水分散粒剂"), ("种",), "max", "technical"),
    MetricSpec("技术指标", "水分散粒剂制备技术", ("水分散粒剂制备技术", "制备关键技术", "水分散粒剂"), ("套", "项"), "max", "technical"),
    MetricSpec("应用指标", "田间应用防效", ("田间应用防效", "田间防效", "防治效果", "防效"), ("%",), "max", "technical"),
    MetricSpec("应用指标", "化学农药减施率", ("化学农药减施率", "化学农药减施", "农药减施率", "农药减施"), ("%",), "max", "technical"),
    MetricSpec("产出指标", "成果转化数", ("成果转化数",), ("项", "个"), "max", "deliverable"),
    MetricSpec("知识产权", "新增知识产权数量", ("平均新增知识产权数量", "新增知识产权数", "新增知识产权数量"), ("项", "件", "个"), "max", "deliverable"),
    MetricSpec("人才培养", "培养研究生", ("培养研究生", "培养硕士研究生", "培养博士研究生", "硕士研究生", "博士研究生"), ("名", "人"), "sum", "talent"),
    MetricSpec("人才培养", "培育吸引人才", ("培育、吸引人才情况", "培育吸引人才情况", "高层次人才", "高级创新技术人员"), ("名", "人"), "max", "talent"),
    MetricSpec("产业效益", "新增销售收入", ("新增销售收入", "新增销售额", "营收", "营业收入", "销售收入", "预计销售"), ("亿元", "万元", "元"), "max", "financial"),
    MetricSpec("产业效益", "新增利税", ("新增利税", "税收", "利润", "净利润", "上缴税金"), ("亿元", "万元", "元"), "max", "financial"),
    MetricSpec("产业效益", "引导社会资金投入能力", ("引导社会资金投入能力", "社会资金总量与专项资金之比", "实际自筹资金/专项资金"), ("%",), "max", "financial"),
    MetricSpec("产业效益", "专项资金投入产出效益", ("专项资金投入产出效益", "新增利税/专项资金"), ("%",), "max", "financial"),
    MetricSpec("社会效益", "新增就业人数", ("新增就业人数",), ("名", "人"), "max", "numeric"),
    MetricSpec("成果产出", "核心成果获奖数", ("核心成果获奖数",), ("项", "个"), "max", "deliverable"),
    MetricSpec("社会效益", "开展科普活动", ("开展科学普及活动", "开展科学普及场次", "科学普及场次", "开展科普活动", "科普活动", "科普推广会议", "科普会议", "举办培训", "学术活动"), ("次", "场"), "sum", "numeric"),
    MetricSpec("社会效益", "服务公众人次", ("吸引发动公众参与", "服务公众", "受益人群", "影响人数"), ("人次", "人"), "max", "numeric"),
    MetricSpec("科普产出", "科普动画部数", ("科普动画", "科普动漫微视频", "科普微动漫视频", "科普影视作品", "原创科普影视作品", "视频动画"), ("部",), "max", "deliverable"),
    MetricSpec("科普产出", "公益推广科普作品", ("公益推广科普作品", "用于公益推广的科普动画", "用于公益推广的影视动画作品", "科普动画作品", "科普动漫微视频", "科普影视作品", "原创科普动画影视作品"), ("套", "册"), "max", "numeric"),
    MetricSpec("科普产出", "提供资助方科普作品", ("提供给资助方", "直接提供给资助方", "向甲方提供", "提供给甲方"), ("套", "册"), "max", "numeric"),
    MetricSpec("社会效益", "科普推广点击量", ("累计网络点击量", "推广总量", "累计总流量", "网络点击量", "总流量"), ("万人次", "人次", "人"), "max", "numeric"),
)

COMPARATOR_PATTERNS = (
    ("≥", ("不少于", "不低于", "至少", "以上", "达到", "达", "完成", "形成", "申请", "发表", "新增", "培养", "举办", "吸引", "优选", "研制", "筛选")),
    ("≤", ("不超过", "至多")),
)

ACTION_PATTERNS = (
    ("申请", ("申请", "专利申请")),
    ("授权", ("授权", "获批", "取得授权")),
    ("发表", ("发表", "刊发")),
    ("制定", ("制定", "形成", "建立")),
    ("筛选", ("优选", "筛选")),
    ("研制", ("研制" ,)),
    ("培养", ("培养", "引进")),
    ("实现", ("实现", "达到", "完成", "新增", "减施")),
    ("推广", ("推广", "示范", "培训")),
)

TIME_PATTERNS = (
    "项目执行期内",
    "截至验收前",
    "验收前",
    "项目期内",
    "当年",
    "累计",
)

CALIBER_PATTERNS = (
    "含税",
    "不含税",
    "累计",
    "当年",
    "新增",
    "申请",
    "授权",
    "发明",
    "实用新型",
    "企业标准",
    "田间",
    "减施",
)

SUBJECT_PATTERNS = (
    ("项目承担单位", ("承担单位",)),
    ("项目参与单位", ("参与单位", "协作单位")),
    ("项目组", ("项目组", "课题组")),
)

SECTION_HINT_PATTERNS = (
    r"(项目绩效评价考核目标及指标)",
    r"(项目验收的考核指标)",
    r"(项目的考核目标及指标)",
    r"(项目考核目标及指标)",
    r"(项目验收考核指标)",
    r"(考核目标及指标)",
    r"(考核指标)",
    r"(项目实施的绩效目标)",
    r"(绩效指标)",
    r"(预期目标)",
    r"(预期成果)",
    r"(主要指标如下)",
)

SECTION_END_PATTERNS = (
    r"^[一二三四五六七八九十]+、",
    r"^第[一二三四五六七八九十]+",
)

ENTRY_START_PATTERN = re.compile(r"^(?:\d+[\.、]|[①②③④⑤⑥⑦⑧⑨⑩]|（\d+）|\(\d+\))")
TABLE_ROW_PATTERN = re.compile(r"^\[表格行\d+\]")
NUMBER_UNIT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*(亿元|万元|元|项|件|个|篇|份|名|人|次|场|万人次|人次|株|种|套|册|部|%)")
CHINESE_NUMBER_PATTERN = re.compile(r"([一二三四五六七八九十两]+)\s*(项|件|个|篇|份|名|人|次|场|株|种|套|册|部|座)")
SCIENCE_POPULARIZATION_METRIC_NAMES = {
    "科普动画部数",
    "公益推广科普作品",
    "提供资助方科普作品",
    "科普推广点击量",
    "开展科普活动",
}

# “撰写科技报告、研究报告1篇”表示二选一，而非各 1 篇。
DISJUNCTIVE_SCIENCE_REPORT_PATTERN = re.compile(
    r"(?:撰写|形成|提交|完成)?\s*科技报告\s*[、,，]\s*研\s*究\s*报告"
    r"|"
    r"科技报告\s*[、,，]\s*研\s*究\s*报告\s*(?:[（(]\s*篇\s*[）)]|[（(]\s*份\s*[）)])?"
    r"|"
    r"研\s*究\s*报告\s*[、,，]\s*科技报告"
)
SCIENCE_REPORT_EQUIVALENCE_PATTERN = re.compile(
    r"(?:项目)?研究报告\s*[（(]\s*科技报告\s*[）)]|科技报告\s*[（(]\s*研究报告\s*[）)]"
)
SCIENCE_REPORT_DISJUNCTIVE_VARIANT = "科技报告/研究报告"
SCIENCE_REPORT_DISJUNCTIVE_NAMES = ("科技报告", "研究报告")

CURRENCY_UNIT_SCALE = {
    "元": 1.0,
    "万元": 10_000.0,
    "亿元": 100_000_000.0,
}

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


class KPIExtractor:
    """从任务书文本中抽取 KPI 承诺。"""

    def extract(self, document: ParsedAcceptanceDocument) -> list[KPICommitment]:
        commitments: list[KPICommitment] = []
        seen: dict[tuple[str, float, str, str], int] = {}
        for entry_text, source_block, current_section in self._iter_candidate_entries(document):
            disjunctive_item = self._try_extract_disjunctive_science_report(
                entry_text,
                source_block,
                current_section,
            )
            if disjunctive_item is not None:
                self._store_commitment(commitments, seen, disjunctive_item)
                continue
            for spec in METRIC_SPECS:
                if not self._entry_mentions_metric(entry_text, spec):
                    continue
                value_unit = self._extract_value_and_unit(entry_text, spec)
                if not value_unit:
                    continue
                target_value, unit = value_unit
                comparator = self._infer_comparator(entry_text)
                item = KPICommitment(
                    commitment_id=f"kpi_{len(commitments) + 1}",
                    metric_name=spec.canonical_name,
                    metric_category=spec.category,
                    target_value=target_value,
                    target_unit=unit,
                    comparator=comparator,
                    aggregation=spec.aggregation,  # type: ignore[arg-type]
                    action=self._infer_action(entry_text, spec),
                    subject_scope=self._infer_subject_scope(entry_text),
                    time_constraint=self._infer_time_constraint(entry_text, current_section),
                    caliber_constraint=self._infer_caliber_constraint(entry_text, spec),
                    metric_variant=self._infer_metric_variant(entry_text, spec),
                    metric_layer=spec.layer,
                    keywords=list(spec.aliases),
                    source_line=entry_text,
                    source_section=current_section,
                    source_block_id=source_block.block_id if source_block else "",
                    source_page=source_block.page if source_block else 0,
                )
                self._store_commitment(commitments, seen, item)
        for item in self._extract_science_popularization_total_commitments(document):
            self._store_commitment(commitments, seen, item)
        commitments = self._merge_science_popularization_commitments(commitments)
        return self._collapse_disjunctive_science_report_commitments(
            self._prune_near_duplicates(commitments)
        )

    def extract_declared_targets(self, document: ParsedAcceptanceDocument) -> list[KPICommitment]:
        """从验收申请表“任务书约定目标”字段补齐承诺指标。"""
        commitments: list[KPICommitment] = []
        seen: dict[tuple[str, float, str, str], int] = {}
        for block in document.blocks:
            line = block.text
            if "任务书约定目标" not in line:
                continue
            target_text = line.split("任务书约定目标", 1)[1]
            target_text = re.split(r"实际完成情况[:：]|[；;]\s*实际完成", target_text, maxsplit=1)[0]
            target_text = re.sub(r"^[：:]\s*", "", target_text).strip()
            if not target_text:
                continue
            source_text = f"验收申请表任务书约定目标：{target_text}"
            for spec in METRIC_SPECS:
                if not self._entry_mentions_metric(target_text, spec):
                    continue
                value_unit = self._extract_value_and_unit(target_text, spec)
                if not value_unit:
                    continue
                item = self._make_commitment(
                    spec=spec,
                    value=value_unit[0],
                    unit=value_unit[1],
                    source_text=source_text,
                    source_block=block,
                    section="验收申请表任务书约定目标",
                )
                self._store_commitment(commitments, seen, item)
        commitments = self._merge_science_popularization_commitments(commitments)
        return self._collapse_disjunctive_science_report_commitments(
            self._prune_near_duplicates(commitments)
        )

    def _store_commitment(
        self,
        commitments: list[KPICommitment],
        seen: dict[tuple[str, float, str, str], int],
        item: KPICommitment,
    ) -> None:
        dedup_key = (
            item.metric_name,
            self._normalize_value(item.target_value, item.target_unit),
            self._normalize_unit(item.target_unit),
            self._compact_text(item.source_line),
        )
        existing_index = seen.get(dedup_key)
        if existing_index is not None:
            if self._prefer_candidate(item, commitments[existing_index]):
                commitments[existing_index] = item
            return
        seen[dedup_key] = len(commitments)
        commitments.append(item)

    def _line_has_disjunctive_science_report(self, line: str) -> bool:
        compact = self._compact_text(line)
        if DISJUNCTIVE_SCIENCE_REPORT_PATTERN.search(compact):
            return True
        if "科技报告" in compact and "研究报告" in compact:
            if re.search(r"科技报告\s*[、,，]\s*研\s*究\s*报告", compact):
                return True
            if re.search(r"研\s*究\s*报告\s*[、,，]\s*科技报告", compact):
                return True
        return False

    def _line_treats_science_reports_as_equivalent(self, line: str) -> bool:
        return bool(SCIENCE_REPORT_EQUIVALENCE_PATTERN.search(self._compact_text(line)))

    def _try_extract_disjunctive_science_report(
        self,
        entry_text: str,
        source_block: object | None,
        current_section: str,
    ) -> KPICommitment | None:
        if not self._line_has_disjunctive_science_report(entry_text):
            return None
        spec = next(item for item in METRIC_SPECS if item.canonical_name == "科技报告")
        value_unit = self._extract_value_and_unit(entry_text, spec)
        if not value_unit:
            value_unit = self._extract_disjunctive_science_report_table_value(entry_text, spec)
        if not value_unit:
            return None
        target_value, unit = value_unit
        return KPICommitment(
            commitment_id="",
            metric_name="科技报告",
            metric_category=spec.category,
            target_value=target_value,
            target_unit=unit,
            comparator=self._infer_comparator(entry_text),
            aggregation=spec.aggregation,  # type: ignore[arg-type]
            action=self._infer_action(entry_text, spec),
            subject_scope=self._infer_subject_scope(entry_text),
            time_constraint=self._infer_time_constraint(entry_text, current_section),
            caliber_constraint=self._infer_caliber_constraint(entry_text, spec),
            metric_variant=SCIENCE_REPORT_DISJUNCTIVE_VARIANT,
            metric_layer=spec.layer,
            alternate_metric_names=list(SCIENCE_REPORT_DISJUNCTIVE_NAMES),
            keywords=["科技报告", "研究报告", "撰写科技报告", "撰写研究报告"],
            source_line=entry_text,
            source_section=current_section,
            source_block_id=source_block.block_id if source_block else "",
            source_page=source_block.page if source_block else 0,
        )

    def _make_commitment(
        self,
        *,
        spec: MetricSpec,
        value: float,
        unit: str,
        source_text: str,
        source_block: object | None,
        section: str,
    ) -> KPICommitment:
        return KPICommitment(
            commitment_id="",
            metric_name=spec.canonical_name,
            metric_category=spec.category,
            target_value=value,
            target_unit=unit,
            comparator=self._infer_comparator(source_text),
            aggregation=spec.aggregation,  # type: ignore[arg-type]
            action=self._infer_action(source_text, spec),
            subject_scope=self._infer_subject_scope(source_text),
            time_constraint=self._infer_time_constraint(source_text, section),
            caliber_constraint=self._infer_caliber_constraint(source_text, spec),
            metric_variant=self._infer_metric_variant(source_text, spec),
            metric_layer=spec.layer,
            keywords=list(spec.aliases),
            source_line=source_text,
            source_section=section,
            source_block_id=source_block.block_id if source_block else "",
            source_page=source_block.page if source_block else 0,
        )

    def _collapse_disjunctive_science_report_commitments(
        self,
        commitments: list[KPICommitment],
    ) -> list[KPICommitment]:
        if not commitments:
            return commitments
        if any(item.metric_variant == SCIENCE_REPORT_DISJUNCTIVE_VARIANT for item in commitments):
            return self._drop_redundant_science_report_commitments(commitments)

        report_items = [item for item in commitments if item.metric_name in SCIENCE_REPORT_DISJUNCTIVE_NAMES]
        if len(report_items) < 2:
            return commitments

        by_name: dict[str, KPICommitment] = {}
        for item in report_items:
            existing = by_name.get(item.metric_name)
            if existing is None or self._prefer_candidate(item, existing):
                by_name[item.metric_name] = item
        if set(by_name) != set(SCIENCE_REPORT_DISJUNCTIVE_NAMES):
            return commitments

        has_disjunctive_source = any(self._line_has_disjunctive_science_report(item.source_line) for item in report_items)
        if not has_disjunctive_source and self._science_reports_explicit_and_requirement(report_items):
            return commitments
        if any(item.target_value != 1 for item in by_name.values()):
            return commitments
        if any(self._normalize_unit(item.target_unit) not in {"篇", "份"} for item in by_name.values()):
            return commitments

        merged = self._merge_science_report_commitments(list(by_name.values()))
        remaining = [item for item in commitments if item.metric_name not in SCIENCE_REPORT_DISJUNCTIVE_NAMES]
        remaining.append(merged)
        return remaining

    def _drop_redundant_science_report_commitments(
        self,
        commitments: list[KPICommitment],
    ) -> list[KPICommitment]:
        disjunctive = [item for item in commitments if item.metric_variant == SCIENCE_REPORT_DISJUNCTIVE_VARIANT]
        if not disjunctive:
            return commitments
        primary = max(disjunctive, key=self._commitment_priority)
        remaining = [
            item
            for item in commitments
            if item.metric_name not in SCIENCE_REPORT_DISJUNCTIVE_NAMES
            or item.metric_variant == SCIENCE_REPORT_DISJUNCTIVE_VARIANT
        ]
        if primary not in remaining:
            remaining.append(primary)
        return remaining

    def _extract_disjunctive_science_report_table_value(
        self,
        entry_text: str,
        spec: MetricSpec,
    ) -> tuple[float, str] | None:
        for unit in spec.units:
            match = re.search(
                rf"(?:实施期目标|指标值|目标值)[:：]\s*(\d+(?:\.\d+)?)\s*(?:{re.escape(unit)})?(?:\s|;|；|$)",
                entry_text,
            )
            if match:
                return float(match.group(1)), unit
        generic = re.search(r"(?:实施期目标|指标值|目标值)[:：]\s*(\d+(?:\.\d+)?)", entry_text)
        if generic:
            return float(generic.group(1)), spec.units[0]
        return None

    def _science_reports_explicit_and_requirement(self, items: list[KPICommitment]) -> bool:
        for item in items:
            compact = self._compact_text(item.source_line)
            if self._line_has_disjunctive_science_report(item.source_line):
                continue
            has_science = bool(re.search(r"科技报告\s*\d+(?:\.\d+)?\s*(?:篇|份)", compact))
            has_research = bool(re.search(r"(?<!总)研究报告\s*\d+(?:\.\d+)?\s*(?:篇|份)", compact))
            if has_science and has_research:
                return True
        return False

    def _merge_science_report_commitments(self, items: list[KPICommitment]) -> KPICommitment:
        primary = max(items, key=self._commitment_priority)
        anchor_item = primary
        for item in items:
            if self._line_has_disjunctive_science_report(item.source_line):
                anchor_item = item
                break
        source_lines: list[str] = []
        seen_lines: set[str] = set()
        keywords: list[str] = []
        seen_keywords: set[str] = set()
        for item in items:
            line = (item.source_line or "").strip()
            if line and line not in seen_lines:
                seen_lines.add(line)
                source_lines.append(line)
            for keyword in [*item.keywords, *SCIENCE_REPORT_DISJUNCTIVE_NAMES]:
                if keyword not in seen_keywords:
                    seen_keywords.add(keyword)
                    keywords.append(keyword)
        return primary.model_copy(
            update={
                "metric_name": "科技报告",
                "metric_variant": SCIENCE_REPORT_DISJUNCTIVE_VARIANT,
                "alternate_metric_names": list(SCIENCE_REPORT_DISJUNCTIVE_NAMES),
                "target_value": max(item.target_value for item in items),
                "keywords": keywords,
                "source_line": "\n".join(source_lines),
                "source_block_id": anchor_item.source_block_id,
                "source_page": anchor_item.source_page,
            }
        )

    def _iter_candidate_entries(
        self,
        document: ParsedAcceptanceDocument,
    ) -> list[tuple[str, object | None, str]]:
        entries = self._iter_section_entries(document)
        entries.extend(self._iter_alias_windows(document))
        deduped: list[tuple[str, object | None, str]] = []
        seen: set[tuple[str, str, int]] = set()
        for text, block, section in entries:
            signature = (text.strip(), section, block.page if block else -1)
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append((text, block, section))
        return deduped

    def _extract_science_popularization_total_commitments(self, document: ParsedAcceptanceDocument) -> list[KPICommitment]:
        """科普专项任务书常见为 OCR 分散段落，按“总体指标/实施期目标”窗口兜底抽取。"""
        specs = {spec.canonical_name: spec for spec in METRIC_SPECS}
        commitments: list[KPICommitment] = []
        lines = document.lines
        blocks = document.blocks or []
        for idx, line in enumerate(lines):
            if "项目总体指标" not in line and "总体目标包括" not in line and "实施期目标" not in line:
                continue
            window_lines = lines[idx: min(len(lines), idx + 16)]
            window = "".join(window_lines)
            if not any(token in window for token in ("科普", "动画", "推广", "资助方", "点击量", "总流量")):
                continue
            block = blocks[idx] if idx < len(blocks) else None
            section = self._nearest_section(lines, idx) or "科普专项总体指标"
            patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
                ("公益推广科普作品", re.compile(r"(?:确保至少|不少于)?\s*(\d+(?:\.\d+)?)\s*(套|册)[^。；;\n]{0,40}(?:科普动画|科普作品|公益推广|非营利性教育活动)")),
                ("提供资助方科普作品", re.compile(r"(?:其中至少|其中不少于|其中|至少|不少于)\s*(\d+(?:\.\d+)?)\s*(套|册)\s*(?:直接)?提供给(?:资助方|甲方)")),
                ("科普推广点击量", re.compile(r"(?:累计网络点击量|推广总量|累计总流量|网络点击量)[^0-9]{0,20}(\d+(?:\.\d+)?)\s*(万人次|人次|人)")),
                ("开展科普活动", re.compile(r"(?:开展)?(?:科学普及|科普)(?:活动|场次|会议)[^0-9一二三四五六七八九十两]{0,20}(\d+(?:\.\d+)?|[一二三四五六七八九十两]+)\s*(场|次)")),
                ("科普动画部数", re.compile(r"(?:科普动画|科普动漫微视频|科普影视作品|原创科普影视作品|视频动画)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*部")),
            )
            for metric_name, pattern in patterns:
                spec = specs.get(metric_name)
                if spec is None:
                    continue
                matches = list(pattern.finditer(window))
                if not matches:
                    continue
                match = max(matches, key=lambda item: self._number_match_value(item.group(1)) or 0.0)
                value = self._number_match_value(match.group(1))
                if value is None:
                    continue
                commitments.append(
                    self._make_commitment(
                        spec=spec,
                        value=value,
                        unit=match.group(2) if match.lastindex and match.lastindex >= 2 else spec.units[0],
                        source_text="".join(window_lines)[:800],
                        source_block=block,
                        section=section,
                    )
                )
        return commitments

    def _number_match_value(self, text: str) -> float | None:
        try:
            return float(text)
        except (TypeError, ValueError):
            parsed = self._parse_chinese_numeral(text)
            return float(parsed) if parsed is not None else None

    def _range_target_value(self, first: str, second: str | None, spec: MetricSpec) -> float:
        """任务书目标出现区间时，按最低完成门槛（下限）提取目标值。"""
        start = float(first)
        if not second:
            return start
        end = float(second)
        # 检测范围类指标需要上限值作为可覆盖范围。
        if spec.canonical_name == "检测范围":
            return max(start, end)
        return min(start, end)

    def _merge_science_popularization_commitments(self, commitments: list[KPICommitment]) -> list[KPICommitment]:
        science_names = {
            "科普动画部数",
            "公益推广科普作品",
            "提供资助方科普作品",
            "科普推广点击量",
            "开展科普活动",
        }
        by_metric: dict[str, list[KPICommitment]] = {}
        others: list[KPICommitment] = []
        for item in commitments:
            if item.metric_name in science_names:
                by_metric.setdefault(item.metric_name, []).append(item)
            else:
                others.append(item)
        merged: list[KPICommitment] = []
        for metric_name, items in by_metric.items():
            total_like = [
                item for item in items
                if (
                    any(token in item.source_line[:180] for token in ("项目总体指标", "项目总体目标", "总体目标包括", "实施期目标"))
                    or (
                        any(token in item.source_line for token in ("项目总体指标", "项目总体目标", "总体目标包括", "实施期目标"))
                        and not any(token in item.source_line[:180] for token in ("第一年指标", "第二年指标", "第一年度目标", "第二年度目标"))
                    )
                )
            ]
            if total_like:
                merged.append(max(total_like, key=lambda item: self._normalize_value(item.target_value, item.target_unit)))
                continue
            if metric_name in {"科普推广点击量", "公益推广科普作品", "提供资助方科普作品", "开展科普活动"} and len(items) >= 2:
                unit = items[0].target_unit
                total = sum(self._convert_value(item.target_value, item.target_unit, unit) for item in items)
                first = max(items, key=self._commitment_priority)
                merged.append(
                    first.model_copy(
                        update={
                            "target_value": total,
                            "target_unit": unit,
                            "source_line": "\n".join(dict.fromkeys(item.source_line for item in items)),
                            "source_block_id": first.source_block_id,
                            "source_page": first.source_page,
                        }
                    )
                )
                continue
            merged.append(max(items, key=lambda item: (self._commitment_priority(item), item.target_value)))
        return [*others, *merged]

    def _iter_section_entries(
        self,
        document: ParsedAcceptanceDocument,
    ) -> list[tuple[str, object | None, str]]:
        blocks = document.blocks or []
        entries: list[tuple[str, object | None, str]] = []
        current_section = ""
        in_kpi_section = False
        buffer: list[str] = []
        buffer_block = None

        def flush() -> None:
            nonlocal buffer, buffer_block
            if not buffer:
                return
            text = "".join(buffer).strip()
            if text:
                entries.append((text, buffer_block, current_section))
            buffer = []
            buffer_block = None

        for idx, line in enumerate(document.lines):
            block = blocks[idx] if idx < len(blocks) else None
            section = self._detect_section(line)
            if section:
                flush()
                current_section = section
                in_kpi_section = True
                continue
            if in_kpi_section and self._is_section_end(line):
                flush()
                in_kpi_section = False
                current_section = ""
                continue
            if not in_kpi_section:
                continue
            if not self._is_candidate_line(line):
                continue
            if TABLE_ROW_PATTERN.match(line):
                flush()
                buffer = [line]
                buffer_block = block
                continue
            if ENTRY_START_PATTERN.match(line):
                flush()
                buffer = [line]
                buffer_block = block
                continue
            if buffer and self._line_has_metric_alias(line) and any(self._line_has_metric_alias(item) for item in buffer):
                flush()
                buffer = [line]
                buffer_block = block
                continue
            if not buffer:
                buffer = [line]
                buffer_block = block
                continue
            buffer.append(line)
        flush()
        return entries

    def _iter_alias_windows(
        self,
        document: ParsedAcceptanceDocument,
    ) -> list[tuple[str, object | None, str]]:
        entries: list[tuple[str, object | None, str]] = []
        lines = document.lines
        blocks = document.blocks or []
        for idx, line in enumerate(lines):
            if not self._is_candidate_line(line):
                continue
            if not self._line_has_metric_alias(line):
                continue
            nearest_section = self._nearest_section(lines, idx)
            if not nearest_section and "[表格行" not in line and "任务书约定目标" not in line:
                continue
            window = [line]
            if not self._has_inline_target_value(line):
                for offset in (1, 2):
                    next_idx = idx + offset
                    if next_idx >= len(lines):
                        break
                    next_line = lines[next_idx]
                    if not self._is_candidate_line(next_line):
                        break
                    if TABLE_ROW_PATTERN.match(next_line) and offset > 1:
                        break
                    if NUMBER_UNIT_PATTERN.search(next_line) or (offset == 1 and self._line_has_metric_alias(next_line)):
                        window.append(next_line)
                    else:
                        break
            block = blocks[idx] if idx < len(blocks) else None
            entries.append((" ".join(part.strip() for part in window if part.strip()), block, nearest_section))
        return entries

    def _detect_section(self, line: str) -> str:
        for pattern in SECTION_HINT_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return ""

    def _is_section_end(self, line: str) -> bool:
        if self._detect_section(line):
            return False
        for pattern in SECTION_END_PATTERNS:
            if re.search(pattern, line):
                return True
        return False

    def _is_candidate_line(self, line: str) -> bool:
        if not line:
            return False
        if any(token in line for token in ("项目进展情况", "进展情况及已拨经费", "目前进展如下", "已拨经费使用情况")):
            return False
        if any(token in line for token in ("目前成果包括", "截至目前", "已发表", "已申请", "已授权", "已培养")):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?", line):
            return False
        if "[表格行" in line and all(alias not in line for spec in METRIC_SPECS for alias in spec.aliases):
            return False
        if line.startswith("河北省科学技术厅") or line.startswith("河 北 省 科 学 技 术 厅"):
            return False
        return True

    def _line_has_metric_alias(self, line: str) -> bool:
        return any(alias in line for spec in METRIC_SPECS for alias in spec.aliases)

    def _nearest_section(self, lines: list[str], index: int) -> str:
        for cursor in range(index, max(index - 12, -1), -1):
            section = self._detect_section(lines[cursor])
            if section:
                return section
        return ""

    def _infer_comparator(self, line: str) -> str:
        for comparator, phrases in COMPARATOR_PATTERNS:
            if any(phrase in line for phrase in phrases):
                return comparator
        if any(token in line for token in ("小于", "低于", "少于", "不超过", "至多", "最大")):
            return "≤"
        if any(token in line for token in ("<", "≤", "=")):
            return "=" if "=" in line else "≤"
        return "≥"

    def _metric_context(self, line: str, spec: MetricSpec, *, window: int = 48) -> str:
        text = str(line or "")
        positions = [text.find(alias) for alias in spec.aliases if alias and alias in text]
        positions = [position for position in positions if position >= 0]
        if not positions:
            return text
        start = max(0, min(positions) - window)
        end = min(len(text), max(positions) + window)
        return text[start:end]

    def _infer_action(self, line: str, spec: MetricSpec) -> str:
        context = self._metric_context(line, spec)
        if spec.canonical_name in {"发明专利", "实用新型专利"}:
            if "授权" in context:
                return "授权"
            if "申请" in context or "申报" in context:
                return "申请"
            return "申请/授权"
        if spec.canonical_name == "培养研究生":
            return "培养"
        if spec.canonical_name in {"科普动画部数", "公益推广科普作品", "提供资助方科普作品"}:
            return "完成"
        if spec.canonical_name == "科普推广点击量":
            return "推广"
        if spec.canonical_name == "科技论文":
            return "发表"
        if spec.canonical_name == "技术标准":
            return "制定"
        if spec.canonical_name in {"实验系统", "技术方案"}:
            return "形成"
        if spec.canonical_name in {"工程样机", "示范基地"}:
            return "完成" if "完成" in line else "建成" if "建成" in line else "形成"
        if spec.canonical_name in {"检测范围", "检测频率", "检测标准偏差", "最大测量误差"}:
            return "达到"
        if spec.canonical_name == "检测分析方法":
            return "建立"
        if spec.canonical_name == "高效杀虫功能微生物":
            return "筛选"
        if spec.canonical_name in {"杀蚜虫新型生物制剂", "水分散粒剂制备技术"}:
            return "研制"
        if spec.canonical_name in {"田间应用防效", "化学农药减施率"}:
            return "实现"
        if spec.canonical_name in {"新增销售收入", "新增利税"}:
            return "实现"
        if spec.canonical_name in {"科技报告", "研究报告", "决策咨询报告"}:
            if "提交" in context:
                return "提交"
            if "发表" in context:
                return "发表"
            return "形成"
        for action, phrases in ACTION_PATTERNS:
            if any(phrase in context for phrase in phrases):
                return action
        if spec.canonical_name in {"新增销售收入", "新增利税"}:
            return "实现"
        return ""

    def _infer_subject_scope(self, line: str) -> str:
        for label, phrases in SUBJECT_PATTERNS:
            if any(phrase in line for phrase in phrases):
                return label
        return "项目承担单位"

    def _infer_time_constraint(self, line: str, section: str) -> str:
        for phrase in TIME_PATTERNS:
            if phrase in line:
                return phrase
        if "进度" in section or "阶段" in section:
            return "阶段目标"
        return "项目执行期内"

    def _infer_caliber_constraint(self, line: str, spec: MetricSpec) -> str:
        context = self._metric_context(line, spec)
        if spec.canonical_name in SCIENCE_POPULARIZATION_METRIC_NAMES:
            hits = [phrase for phrase in ("累计", "当年") if phrase in context]
            return " / ".join(dict.fromkeys(hits))
        hits = [phrase for phrase in CALIBER_PATTERNS if phrase in context]
        if hits:
            return " / ".join(dict.fromkeys(hits))
        if spec.canonical_name == "新增销售收入":
            return "新增口径"
        return ""

    def _infer_metric_variant(self, line: str, spec: MetricSpec) -> str:
        context = self._metric_context(line, spec)
        if spec.canonical_name == "发明专利":
            if "授权" in context:
                return "授权发明专利"
            if "申请" in context:
                return "申请发明专利"
        if spec.canonical_name == "科技论文":
            for phrase in (
                "核心期刊以上论文",
                "高水平研究论文",
                "发表学术论文",
                "发表相关论文",
                "学术论文",
                "相关论文",
                "发表论文",
                "发表文章",
                "科技论文",
                "论文",
            ):
                if phrase in context:
                    return phrase
        if spec.canonical_name in {"实验系统", "技术方案", "工程样机", "示范基地", "检测范围", "检测频率", "检测标准偏差", "最大测量误差"}:
            return spec.canonical_name
        if spec.canonical_name in SCIENCE_POPULARIZATION_METRIC_NAMES:
            return spec.canonical_name
        if spec.canonical_name == "新增销售收入":
            if "营业收入" in line:
                return "营业收入"
            if "销售收入" in line:
                return "销售收入"
        if spec.canonical_name == "新增利税":
            if "利润" in line:
                return "利润"
            if "税收" in line:
                return "税收"
        if spec.canonical_name == "技术标准" and "企业标准" in line:
            return "企业标准"
        return spec.canonical_name

    def _extract_value_and_unit(self, line: str, spec: MetricSpec) -> tuple[float, str] | None:
        line = self._normalize_lost_range_separators(line, spec)
        table_match = self._extract_table_row_value(line, spec)
        if table_match:
            return table_match
        direct_matches = self._collect_direct_matches(line, spec)
        if direct_matches:
            return self._reduce_matches(direct_matches, spec)
        chinese_match = self._extract_chinese_number_value(line, spec)
        if chinese_match:
            return chinese_match

        candidates = self._collect_generic_candidates(line, spec)
        if not candidates:
            return None
        alias_positions = [line.index(alias) for alias in spec.aliases if alias in line]
        if not alias_positions:
            return None
        alias_pos = min(alias_positions)
        candidates.sort(key=lambda item: abs(item[0] - alias_pos))
        _, value, unit = candidates[0]
        range_floor = re.search(rf"(\d+(?:\.\d+)?)\s*[-~～至到]\s*\d+(?:\.\d+)?\s*{re.escape(unit)}", line)
        if range_floor:
            return float(range_floor.group(1)), unit
        return value, unit

    def _entry_mentions_metric(self, line: str, spec: MetricSpec) -> bool:
        if spec.canonical_name in SCIENCE_REPORT_DISJUNCTIVE_NAMES:
            if self._line_has_disjunctive_science_report(line):
                return spec.canonical_name == "科技报告"
            if self._line_treats_science_reports_as_equivalent(line):
                return spec.canonical_name == "科技报告"
        if spec.canonical_name == "新增销售收入":
            return any(alias in line for alias in ("新增销售收入", "新增销售额", "新增销售"))
        if spec.canonical_name == "新增利税":
            return any(alias in line for alias in ("新增利税", "新增利润", "新增利"))
        return any(alias in line for alias in spec.aliases)

    def _collect_direct_matches(self, line: str, spec: MetricSpec) -> list[tuple[int, float, str]]:
        line = self._normalize_lost_range_separators(line, spec)
        if spec.canonical_name == "检测频率":
            pattern = re.compile(r"(?:工作频率|检测工作频率)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(次/时|次)")
            return [(match.start(), float(match.group(1)), match.group(2)) for match in pattern.finditer(line)]
        if spec.canonical_name == "检测范围":
            pattern = re.compile(r"(?:检测范围|样检测范围)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*[-~～至到]\s*(\d+(?:\.\d+)?)\s*(mg/L|cells/mL)")
            return [(match.start(), float(match.group(2)), match.group(3)) for match in pattern.finditer(line)]
        if spec.canonical_name == "培养研究生":
            matches: list[tuple[int, float, str]] = []
            for pattern in (
                re.compile(r"(?:培养)?博士研究生\s*(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*(名|人)"),
                re.compile(r"(?:培养)?硕士研究生\s*(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*(名|人)"),
                re.compile(r"(?:相关技术人才|专业技术人员)\s*(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*(名|人)"),
                re.compile(r"培养研究生\s*(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*(名|人)"),
            ):
                for match in pattern.finditer(line):
                    value = self._range_target_value(match.group(1), match.group(2), spec)
                    matches.append((match.start(), value, match.group(3)))
            return matches
        if spec.canonical_name == "科普动画部数":
            matches: list[tuple[int, float, str]] = []
            patterns = (
                re.compile(r"(?:完成)?(?:视频动画|科普动画|科普动漫微视频|科普影视作品|原创科普影视作品)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*部"),
                re.compile(r"(\d+(?:\.\d+)?)\s*部[^。；;\n]{0,32}(?:视频动画|科普动画|科普动漫微视频|科普影视作品|原创科普影视作品)"),
                re.compile(r"完成视频动画\s*(\d+(?:\.\d+)?)\s*部"),
            )
            for pattern in patterns:
                for match in pattern.finditer(line):
                    matches.append((match.start(), float(match.group(1)), "部"))
            return matches
        if spec.canonical_name == "公益推广科普作品":
            matches: list[tuple[int, float, str]] = []
            patterns = (
                re.compile(r"(?:用于)?公益推广[^。；;\n]{0,40}?(?:科普动画|影视动画作品|科普作品|科普影视作品)[^0-9]{0,20}(\d+(?:\.\d+)?)\s*(套|册)"),
                re.compile(r"(?:确保至少|共计|制作(?:了)?|完成)?\s*(\d+(?:\.\d+)?)\s*(套|册)[^。；;\n]{0,48}(?:科普动画|科普作品|影视动画作品|公益推广)"),
            )
            for pattern in patterns:
                for match in pattern.finditer(line):
                    matches.append((match.start(), float(match.group(1)), match.group(2)))
            return matches
        if spec.canonical_name == "提供资助方科普作品":
            matches: list[tuple[int, float, str]] = []
            patterns = (
                re.compile(r"(?:其中|其中至少|其中不少于|至少|不少于)\s*(\d+(?:\.\d+)?)\s*(套|册)[^。；;\n]{0,24}(?:直接)?提供给(?:资助方|甲方)"),
                re.compile(r"(?:直接)?提供给(?:资助方|甲方)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*(套|册)"),
                re.compile(r"向(?:甲方|资助方)提供[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(套|册)"),
            )
            for pattern in patterns:
                for match in pattern.finditer(line):
                    matches.append((match.start(), float(match.group(1)), match.group(2)))
            return matches
        if spec.canonical_name == "科普推广点击量":
            matches: list[tuple[int, float, str]] = []
            for pattern in (
                re.compile(r"(?:累计网络点击量|推广总量|累计总流量|网络点击量)[^0-9]{0,16}(\d+(?:\.\d+)?)\s*(万人次|人次|人)"),
                re.compile(r"(\d+(?:\.\d+)?)\s*(万人次|人次|人)[^。；;\n]{0,24}(?:累计网络点击量|推广总量|累计总流量|网络点击量|公众参与)"),
            ):
                for match in pattern.finditer(line):
                    matches.append((match.start(), float(match.group(1)), match.group(2)))
            return matches

        matches: list[tuple[int, float, str]] = []
        seen_spans: set[tuple[int, int, str]] = set()
        for alias in sorted({alias for alias in spec.aliases if alias in line}, key=len, reverse=True):
            for unit in spec.units:
                after_pattern = re.compile(
                    rf"{re.escape(alias)}[\s:：）)（(]*[^0-9%]{{0,20}}(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*({re.escape(unit)})"
                )
                for match in after_pattern.finditer(line):
                    value = self._range_target_value(match.group(1), match.group(2), spec)
                    key = (match.start(), match.end(), match.group(3))
                    if key in seen_spans:
                        continue
                    seen_spans.add(key)
                    matches.append((match.start(), value, match.group(3)))
        return matches

    def _collect_generic_candidates(self, line: str, spec: MetricSpec) -> list[tuple[int, float, str]]:
        line = self._normalize_lost_range_separators(line, spec)
        generic_pattern = re.compile(
            rf"(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*({'|'.join(re.escape(unit) for unit in spec.units)})"
        )
        return [
            (m.start(), self._range_target_value(m.group(1), m.group(2), spec), m.group(3))
            for m in generic_pattern.finditer(line)
        ]

    def _normalize_lost_range_separators(self, line: str, spec: MetricSpec) -> str:
        text = str(line or "")
        for unit in sorted(spec.units, key=len, reverse=True):
            pattern = re.compile(rf"(?<!\d)(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*{re.escape(unit)}")

            def repl(match: re.Match[str]) -> str:
                first = float(match.group(1))
                second = float(match.group(2))
                if first < second and second - first <= 10:
                    return f"{match.group(1)}-{match.group(2)}{unit}"
                return match.group(0)

            text = pattern.sub(repl, text)
        return text

    def _extract_chinese_number_value(self, line: str, spec: MetricSpec) -> tuple[float, str] | None:
        for match in CHINESE_NUMBER_PATTERN.finditer(line):
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
        value = CHINESE_NUMERAL_MAP.get(text)
        return value if value is not None else None

    def _reduce_matches(self, matches: list[tuple[int, float, str]], spec: MetricSpec) -> tuple[float, str]:
        matches.sort(key=lambda item: item[0])
        if spec.canonical_name == "培养研究生":
            unit = matches[0][2]
            normalized_values = {
                self._convert_value(value, found_unit, unit)
                for _, value, found_unit in matches
            }
            if len(normalized_values) == 1:
                return normalized_values.pop(), unit
            total = sum(self._convert_value(value, found_unit, unit) for _, value, found_unit in matches)
            return total, unit
        if spec.canonical_name in {"科普动画部数", "公益推广科普作品", "提供资助方科普作品", "科普推广点击量", "开展科普活动"}:
            _, value, unit = max(matches, key=lambda item: item[1])
            return value, unit
        _, value, unit = max(matches, key=lambda item: item[1])
        return value, unit

    def _normalize_unit(self, unit: str) -> str:
        if unit in {"件", "项", "个"}:
            return "项"
        if unit in {"人", "名"}:
            return "名"
        return unit

    def _normalize_value(self, value: float, unit: str) -> float:
        normalized_unit = self._normalize_unit(unit)
        if normalized_unit in CURRENCY_UNIT_SCALE:
            return value * CURRENCY_UNIT_SCALE[normalized_unit]
        return value

    def _convert_value(self, value: float, from_unit: str, to_unit: str) -> float:
        normalized_from = self._normalize_unit(from_unit)
        normalized_to = self._normalize_unit(to_unit)
        if normalized_from == normalized_to:
            return value
        if normalized_from in CURRENCY_UNIT_SCALE and normalized_to in CURRENCY_UNIT_SCALE:
            base_value = value * CURRENCY_UNIT_SCALE[normalized_from]
            return base_value / CURRENCY_UNIT_SCALE[normalized_to]
        return value

    def _prefer_candidate(self, new_item: KPICommitment, current_item: KPICommitment) -> bool:
        new_score = self._commitment_priority(new_item)
        current_score = self._commitment_priority(current_item)
        if new_score != current_score:
            return new_score > current_score
        if TABLE_ROW_PATTERN.match(new_item.source_line) and not TABLE_ROW_PATTERN.match(current_item.source_line):
            return True
        if ENTRY_START_PATTERN.match(new_item.source_line) and not ENTRY_START_PATTERN.match(current_item.source_line):
            return True
        return len(new_item.source_line) < len(current_item.source_line)

    def _compact_text(self, value: str) -> str:
        return re.sub(r"\s+", "", value or "")

    def _has_inline_target_value(self, line: str) -> bool:
        if NUMBER_UNIT_PATTERN.search(line):
            return True
        return bool(re.search(r"项目承担单位考核指标[:：]?[^\d%]*?\d+(?:\.\d+)?", line))

    def _prune_near_duplicates(self, commitments: list[KPICommitment]) -> list[KPICommitment]:
        pruned: list[KPICommitment] = []
        for item in commitments:
            replaced = False
            item_text = self._compact_text(item.source_line)
            item_parts = self._source_line_parts(item.source_line)
            for index, existing in enumerate(pruned):
                if item.metric_name != existing.metric_name:
                    continue
                if self._normalize_unit(item.target_unit) != self._normalize_unit(existing.target_unit):
                    continue
                item_value = self._normalize_value(item.target_value, item.target_unit)
                existing_value = self._normalize_value(existing.target_value, existing.target_unit)
                same_value = item_value == existing_value
                existing_text = self._compact_text(existing.source_line)
                existing_parts = self._source_line_parts(existing.source_line)
                same_goal_family = self._comparable_goal_statement(
                    item.metric_name,
                    item.source_line,
                    existing.source_line,
                )
                same_metric_family = item.metric_name in {
                    "科普动画部数",
                    "公益推广科普作品",
                    "提供资助方科普作品",
                    "科普推广点击量",
                    "开展科普活动",
                }
                if not same_value and not same_goal_family:
                    if same_metric_family:
                        item_priority = self._commitment_priority(item)
                        existing_priority = self._commitment_priority(existing)
                        if item_priority > existing_priority:
                            pruned[index] = item
                            replaced = True
                            break
                        if existing_priority > item_priority:
                            replaced = True
                            break
                    continue
                if item_parts and existing_parts:
                    if item_parts.issubset(existing_parts):
                        replaced = True
                        break
                    if existing_parts.issubset(item_parts):
                        pruned[index] = item
                        replaced = True
                        break
                if item_text in existing_text or existing_text in item_text:
                    if self._prefer_candidate(item, existing):
                        pruned[index] = item
                    replaced = True
                    break
            if not replaced:
                pruned.append(item)
        return pruned

    def _source_line_parts(self, value: str) -> set[str]:
        parts: set[str] = set()
        for line in str(value or "").split("\n"):
            compact = self._compact_text(line)
            if compact:
                parts.add(compact)
        return parts

    def _commitment_priority(self, item: KPICommitment) -> int:
        text = f"{item.source_section} {item.source_line}"
        score = 0
        if "项目总体指标" in text or "项目总体目标" in text or "总体目标包括" in text:
            score += 8
        if "项目验收的考核指标" in text:
            score += 6
        if "绩效指标" in text:
            score += 5
        if "总体目标" in text or "实施期目标" in text:
            score += 3
        if "第一年指标" in text or "第二年指标" in text or "第一年度目标" in text or "第二年度目标" in text:
            score -= 5
        if "中期拟提交" in text or "阶段研究成果" in text:
            score -= 4
        if "示例" in text:
            score -= 6
        return score

    def _comparable_goal_statement(self, metric_name: str, left: str, right: str) -> bool:
        if metric_name not in {"决策咨询报告", "研究报告", "科技论文", "科技报告"}:
            return False
        left_text = self._compact_text(left)
        right_text = self._compact_text(right)
        shared_tokens = ("决策咨询报告", "决策参考报告", "研究报告", "科技报告", "科技论文", "论文")
        if not any(token in left_text and token in right_text for token in shared_tokens):
            return False
        goal_markers = ("项目验收的考核指标", "绩效指标", "总体目标", "实施期目标", "阶段研究成果")
        return any(marker in left or marker in right for marker in goal_markers)

    def _extract_table_row_value(self, line: str, spec: MetricSpec) -> tuple[float, str] | None:
        if "[表格行" not in line:
            return None
        target_label = "项目承担单位考核指标" if "项目承担单位考核指标" in line else "任务书约定目标" if "任务书约定目标" in line else ""
        if not target_label:
            return None
        segment = line.split(target_label, 1)[1]
        segment = re.split(r"实际完成情况[:：]|[；;]实际完成", segment, maxsplit=1)[0]
        unit = ""
        for candidate in spec.units:
            if re.search(rf"指标单位[:：][^；;。]*{re.escape(candidate)}", line) or re.search(rf"单位[:：][^；;。]*{re.escape(candidate)}", line):
                unit = candidate
                break
        value_match = re.search(r"(\d+(?:\.\d+)?)(?:\s*[-~～至到]\s*(\d+(?:\.\d+)?))?\s*(亿元|万元|元|项|件|个|篇|份|名|人|次|场|人次|株|种|套|%)?", segment)
        if not value_match:
            return None
        if value_match.group(3):
            unit = value_match.group(3)
        if not unit and "%" in spec.units and "%" in segment[value_match.start():value_match.start() + 24]:
            unit = "%"
        if not unit:
            unit = spec.units[0]
        return float(value_match.group(1)), unit
