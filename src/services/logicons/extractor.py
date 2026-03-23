"""逻辑自洽服务实体抽取"""
import re
from typing import List

from src.common.models.logicons import ExtractedEntity
from src.services.logicons.parser import SectionChunk


class LogiConsEntityExtractor:
    """从章节切片中抽取人、单位、金额、时间和指标实体"""

    _RANGE_YEAR_RE = re.compile(
        r"(20\d{2})\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?\s*[-~至到]\s*"
        r"(20\d{2})\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?"
    )
    _YEAR_RE = re.compile(r"(20\d{2})\s*年")
    _DURATION_RE = re.compile(r"执行期[^\n]{0,30}?(\d+(?:\.\d+)?)\s*年")
    _MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|万元|元)")
    _INDICATOR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(篇|项|件|套|人|%|万元|亿元|元)")
    _MILESTONE_SECTION_HINTS = ["进度", "里程碑", "任务安排", "实施计划", "节点"]
    _INDICATOR_KEYWORDS = ["论文", "专利", "收入", "营收", "指标", "目标", "成果", "示范"]

    def extract(self, chunks: List[SectionChunk]) -> List[ExtractedEntity]:
        entities: List[ExtractedEntity] = []

        for chunk in chunks:
            text = chunk.text
            location = f"line:{chunk.line_no}"

            entities.extend(self._extract_time_entities(text, chunk.section, location))
            entities.extend(self._extract_money_entities(text, chunk.section, location))
            entities.extend(self._extract_indicator_entities(text, chunk.section, location))
            entities.extend(self._extract_person_org_entities(text, chunk.section, location))

        return entities

    def _extract_time_entities(self, text: str, section: str, location: str) -> List[ExtractedEntity]:
        items: List[ExtractedEntity] = []

        for m in self._RANGE_YEAR_RE.finditer(text):
            start_year = float(m.group(1))
            end_year = float(m.group(2))
            items.append(
                ExtractedEntity(
                    entity_type="time_range",
                    name="year_range",
                    value=end_year - start_year + 1,
                    unit="year",
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )
            items.append(
                ExtractedEntity(
                    entity_type="time_point",
                    name="year_start",
                    value=start_year,
                    unit="year",
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )
            items.append(
                ExtractedEntity(
                    entity_type="time_point",
                    name="year_end",
                    value=end_year,
                    unit="year",
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )

        duration_match = self._DURATION_RE.search(text)
        if duration_match:
            items.append(
                ExtractedEntity(
                    entity_type="duration",
                    name="execution_duration",
                    value=float(duration_match.group(1)),
                    unit="year",
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )

        in_milestone_scope = any(k in text for k in self._MILESTONE_SECTION_HINTS) or any(
            k in section for k in self._MILESTONE_SECTION_HINTS
        )
        if in_milestone_scope:
            for m in self._YEAR_RE.finditer(text):
                items.append(
                    ExtractedEntity(
                        entity_type="milestone_year",
                        name="milestone_year",
                        value=float(m.group(1)),
                        unit="year",
                        section=section,
                        location=location,
                        raw_text=text,
                    )
                )

        return items

    def _extract_money_entities(self, text: str, section: str, location: str) -> List[ExtractedEntity]:
        items: List[ExtractedEntity] = []

        for m in self._MONEY_RE.finditer(text):
            amount = self._to_yuan(float(m.group(1)), m.group(2))
            name = "budget_item"
            if any(k in text for k in ["总额", "合计", "总计", "申请", "下达"]):
                name = "budget_total"
            if any(k in text for k in ["明细", "设备费", "材料费", "劳务费", "测试", "管理费", "间接费"]):
                name = "budget_detail"

            items.append(
                ExtractedEntity(
                    entity_type="money",
                    name=name,
                    value=amount,
                    unit="yuan",
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )

        return items

    def _extract_indicator_entities(self, text: str, section: str, location: str) -> List[ExtractedEntity]:
        items: List[ExtractedEntity] = []
        if not any(k in text for k in self._INDICATOR_KEYWORDS):
            return items

        m = self._INDICATOR_RE.search(text)
        if not m:
            return items

        value = float(m.group(1))
        unit = m.group(2)
        if unit == "%":
            value = value / 100.0

        indicator_name = self._detect_indicator_name(text)
        items.append(
            ExtractedEntity(
                entity_type="indicator",
                name=indicator_name,
                value=value,
                unit=unit,
                section=section,
                location=location,
                raw_text=text,
            )
        )
        return items

    def _detect_indicator_name(self, text: str) -> str:
        if "论文" in text:
            return "paper_indicator"
        if "专利" in text:
            return "patent_indicator"
        if "收入" in text or "营收" in text:
            return "revenue_indicator"
        if "示范" in text:
            return "demo_indicator"
        return "indicator_value"

    def _extract_person_org_entities(self, text: str, section: str, location: str) -> List[ExtractedEntity]:
        items: List[ExtractedEntity] = []

        person_match = re.search(r"(负责人|项目负责人)[:：]\s*([^，。；\s]{2,20})", text)
        if person_match:
            items.append(
                ExtractedEntity(
                    entity_type="person",
                    name="负责人",
                    value=None,
                    unit=None,
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )

        org_match = re.search(r"(承担单位|依托单位)[:：]\s*([^，。；\s]{2,40})", text)
        if org_match:
            items.append(
                ExtractedEntity(
                    entity_type="org",
                    name="承担单位",
                    value=None,
                    unit=None,
                    section=section,
                    location=location,
                    raw_text=text,
                )
            )

        return items

    def _to_yuan(self, num: float, unit: str) -> float:
        if unit == "亿元":
            return num * 100000000
        if unit == "万元":
            return num * 10000
        return num
