import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.models.logicon import (
    ConflictCategory,
    ConflictItem,
    ConflictSeverity,
    DocSpan,
    ExtractedEntity,
)
from src.common.tools.json import safe_json_loads
from src.services.logicon.parser import LogicOnParser


def _parse_number(text: str) -> Optional[float]:
    s = (text or "").strip()
    if not s:
        return None
    s = s.replace(",", "").replace("，", "")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _amount_to_wan(amount: float, unit: str) -> float:
    u = (unit or "").strip()
    if u in {"万", "万元"}:
        return float(amount)
    if u in {"元"}:
        return float(amount) / 10000.0
    return float(amount)


def _extract_amount_candidates(text: str) -> list[tuple[float, str, str]]:
    out: list[tuple[float, str, str]] = []
    for m in re.finditer(r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>万元|万|元)", text or ""):
        num = _parse_number(m.group("num"))
        if num is None:
            continue
        unit = m.group("unit")
        out.append((_amount_to_wan(num, unit), unit, m.group(0)))
    return out


def _infer_budget_unit(raw_text: str) -> str:
    raw = raw_text or ""
    if re.search(r"单位\s*[:：]\s*元\b", raw):
        return "元"
    if re.search(r"单位\s*[:：]\s*万\s*元|单位\s*[:：]\s*万元\b", raw):
        return "万元"
    if "万元" in raw:
        return "万元"
    return "万元"


def _extract_bare_number_amount(text: str, default_unit: str) -> Optional[float]:
    s = (text or "").strip()
    if not s:
        return None
    if re.search(r"\d\s*年|\d\s*月|20\d{2}[./\-]\d{1,2}", s):
        return None
    m = re.search(r"(?<![A-Za-z])(?P<num>\d+(?:[.,]\d+)?)(?!\d)", s)
    if not m:
        return None
    num = _parse_number(m.group("num"))
    if num is None:
        return None
    if 1900 <= int(num) <= 2100 and len(m.group("num").split(".")[0]) == 4:
        return None
    if float(num) > 1000000:
        return None
    unit = default_unit
    return _amount_to_wan(float(num), unit)


def _extract_budget_items_from_table_rows(raw_text: str) -> Dict[str, float]:
    default_unit = _infer_budget_unit(raw_text)
    out: dict[str, float] = {}
    row_re = re.compile(r"^\[表格行\d+\]\s*(?P<line>.+)$", re.MULTILINE)
    for m in row_re.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        if "预算科目名称:" not in line or "金额:" not in line:
            continue
        name_m = re.search(r"预算科目名称:(?P<name>[^;|]+)", line)
        amt_m = re.search(r"金额:(?P<num>\d+(?:\.\d+)?)", line)
        if not name_m or not amt_m:
            continue
        name = (name_m.group("name") or "").strip()
        num = _parse_number(amt_m.group("num"))
        if num is None:
            continue
        amount = _amount_to_wan(float(num), default_unit)
        if "设备费" in name:
            if re.search(r"其中|购置|试制|升级|改造|租赁", name):
                continue
            out["设备费"] = amount
        elif "业务费" in name:
            out["业务费"] = amount
        elif "劳务费" in name:
            out["劳务费"] = amount
        elif "材料费" in name:
            out["材料费"] = amount
    return out


def _extract_budget_total_from_table_rows(raw_text: str) -> Optional[float]:
    default_unit = _infer_budget_unit(raw_text)
    totals: list[float] = []
    row_re = re.compile(r"^\[表格行\d+\]\s*(?P<line>.+)$", re.MULTILINE)
    for m in row_re.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        if "/合计:" in line:
            amt_m = re.search(r"/合计:(?P<num>\d+(?:\.\d+)?)", line)
            if not amt_m:
                continue
            num = _parse_number(amt_m.group("num"))
            if num is None:
                continue
            totals.append(_amount_to_wan(float(num), default_unit))
            continue
        if "预算总额" in line or "资金申请总额" in line or "资金下达总额" in line:
            candidates = _extract_amount_candidates(line)
            if candidates:
                totals.append(candidates[0][0])
    if totals:
        s = float(sum(totals))
        if s > 0:
            return s
    return None


def _extract_budget_table_summary(raw_text: str) -> Dict[str, float]:
    default_unit = _infer_budget_unit(raw_text)
    out: dict[str, float] = {}
    row_re = re.compile(r"^\[表格行\d+\]\s*(?P<line>.+)$", re.MULTILINE)
    for m in row_re.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        if "预算科目名称:" not in line or "金额:" not in line:
            continue
        name_m = re.search(r"预算科目名称:(?P<name>[^;|]+)", line)
        amt_m = re.search(r"金额:(?P<num>\d+(?:\.\d+)?)", line)
        if not name_m or not amt_m:
            continue
        name = re.sub(r"\s+", "", (name_m.group("name") or "").strip())
        num = _parse_number(amt_m.group("num"))
        if num is None:
            continue
        out[name] = _amount_to_wan(float(num), default_unit)
    return out


def _extract_budget_total(raw_text: str) -> Optional[float]:
    default_unit = _infer_budget_unit(raw_text)
    keywords = [
        "资金申请总额",
        "资金下达总额",
        "总预算",
        "预算总额",
    ]
    for kw in keywords:
        for m in re.finditer(re.escape(kw), raw_text or ""):
            start = m.start()
            seg = raw_text[start : min(len(raw_text), start + 90)]
            candidates = _extract_amount_candidates(seg)
            if candidates:
                return candidates[0][0]
            bare = _extract_bare_number_amount(seg, default_unit)
            if bare is not None:
                return bare
    return None


def _extract_budget_items(raw_text: str) -> Dict[str, float]:
    default_unit = _infer_budget_unit(raw_text)
    item_types = [
        "设备费",
        "材料费",
        "劳务费",
        "业务费",
        "差旅费",
        "会议费",
        "专家咨询费",
        "测试化验加工费",
        "燃料动力费",
        "其他费用",
        "间接费用",
        "管理费",
    ]

    table_items = _extract_budget_items_from_table_rows(raw_text)
    if table_items and any(k in table_items for k in ("设备费", "业务费", "劳务费")):
        return {k: v for k, v in table_items.items() if k in {"设备费", "业务费", "劳务费"}}

    found: dict[str, float] = {}

    for t in item_types:
        for m in re.finditer(re.escape(t), raw_text or ""):
            seg = raw_text[m.start() : min(len(raw_text), m.start() + 60)]
            candidates = _extract_amount_candidates(seg)
            if candidates:
                val = candidates[0][0]
            else:
                if not re.search(rf"{re.escape(t)}[^0-9]{{0,8}}\d", seg):
                    continue
                val = _extract_bare_number_amount(seg, default_unit)
                if val is None:
                    continue
            if t in found:
                found[t] = max(found[t], val)
            else:
                found[t] = val

    table_row_re = re.compile(r"^\[表格行\d+\]\s*(?P<line>.+)$", re.MULTILINE)
    for m in table_row_re.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        for t in item_types:
            if t not in line:
                continue
            candidates = _extract_amount_candidates(line)
            if candidates:
                val = candidates[0][0]
            else:
                continue
            if t in found:
                found[t] = max(found[t], val)
            else:
                found[t] = val

    return found


def _parse_year_month(year: int, month: Optional[int]) -> int:
    m = int(month or 1)
    m = max(1, min(m, 12))
    return int(year) * 12 + (m - 1)


def _ym_to_year_month(ym: int) -> tuple[int, int]:
    year = int(ym) // 12
    month = int(ym) % 12 + 1
    return year, month


def _build_year_month_patterns(year: int, month: int) -> list[str]:
    mm = str(int(month))
    mm2 = mm.zfill(2)
    yy = str(int(year))
    return [
        rf"{yy}\s*年\s*0?{mm}\s*月",
        rf"{yy}[./\-]0?{mm2}",
        rf"{yy}[./\-]0?{mm}",
    ]


def _build_exec_period_patterns(start_ym: Optional[int], end_ym: Optional[int], duration_months: Optional[int]) -> list[str]:
    patterns: list[str] = []
    if start_ym is not None and end_ym is not None:
        sy, sm = _ym_to_year_month(start_ym)
        ey, em = _ym_to_year_month(end_ym)
        start_parts = _build_year_month_patterns(sy, sm)
        end_parts = _build_year_month_patterns(ey, em)
        for sp in start_parts:
            for ep in end_parts:
                patterns.append(rf"项目起止年月[^。\n]{{0,40}}{sp}[^。\n]{{0,40}}(?:至|到|—|-|~)[^。\n]{{0,40}}{ep}")
                patterns.append(rf"起止年月[^。\n]{{0,40}}{sp}[^。\n]{{0,40}}(?:至|到|—|-|~)[^。\n]{{0,40}}{ep}")
        patterns.append(rf"{sy}[./\-]0?{str(sm).zfill(2)}\s*(?:至|到|—|-|~)\s*{ey}[./\-]0?{str(em).zfill(2)}")
        patterns.append(rf"{sy}[./\-]0?{sm}\s*(?:至|到|—|-|~)\s*{ey}[./\-]0?{em}")
    if duration_months is not None:
        years = max(1, int(round(int(duration_months) / 12.0)))
        patterns.append(rf"(?:执行期|实施期|周期|年限)[^。\n]{{0,20}}{years}\s*年")
        patterns.append(rf"(?:执行期|实施期|周期|年限)[^。\n]{{0,20}}{int(duration_months)}\s*个月")
    patterns.extend([r"项目起止年月", r"起止年月", r"执行期", r"实施期", r"周期", r"年限"])
    return patterns


def _build_progress_patterns(latest_ym: Optional[int], milestone_years: list[int]) -> list[str]:
    patterns: list[str] = []
    if latest_ym is not None:
        y, m = _ym_to_year_month(latest_ym)
        patterns.extend(_build_year_month_patterns(y, m))
    if milestone_years:
        y = max(milestone_years)
        patterns.append(rf"{int(y)}\s*年")
    patterns.extend([r"进度安排", r"阶段目标", r"详细任务进度安排", r"里程碑", r"项目起止年月"])
    return patterns


def _extract_exec_period(raw_text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:

    for m in re.finditer(
        r"(?P<sy>20\d{2})[./\-](?P<sm>\d{1,2})\s*[-—~至到]\s*(?P<ey>20\d{2})[./\-](?P<em>\d{1,2})",
        raw_text or "",
    ):
        sy = int(m.group("sy"))
        sm = int(m.group("sm"))
        ey = int(m.group("ey"))
        em = int(m.group("em"))
        return _parse_year_month(sy, sm), _parse_year_month(ey, em), None

    for m in re.finditer(
        r"(?P<sy>20\d{2})\s*年\s*(?P<sm>\d{1,2})?\s*月?\s*[-—~至到]\s*(?P<ey>20\d{2})\s*年\s*(?P<em>\d{1,2})?\s*月?",
        raw_text or "",
    ):
        sy = int(m.group("sy"))
        sm = int(m.group("sm")) if m.group("sm") else 1
        ey = int(m.group("ey"))
        em = int(m.group("em")) if m.group("em") else 12
        return _parse_year_month(sy, sm), _parse_year_month(ey, em), None

    duration_year = None
    duration_month = None
    for m in re.finditer(r"(?:(?:执行期|实施期|周期|年限)[^。\n]{0,20})?(?P<num>\d{1,2})\s*(?P<unit>年|个月)", raw_text or ""):
        num = int(m.group("num"))
        unit = m.group("unit")
        if unit == "年":
            duration_year = num
            break
        if unit == "个月":
            duration_month = num
            break

    if duration_month is not None:
        return None, None, int(duration_month)
    if duration_year is not None:
        return None, None, int(duration_year) * 12
    return None, None, None


def _extract_milestone_year_months(raw_text: str) -> tuple[list[int], list[int]]:
    yms: list[int] = []
    years: list[int] = []

    for m in re.finditer(r"(?P<y>20\d{2})\s*[年./-]\s*(?P<m>\d{1,2})\s*月", raw_text or ""):
        y = int(m.group("y"))
        mm = int(m.group("m"))
        yms.append(_parse_year_month(y, mm))

    for m in re.finditer(r"(?P<y>20\d{2})[./\-](?P<m>\d{1,2})", raw_text or ""):
        y = int(m.group("y"))
        mm = int(m.group("m"))
        yms.append(_parse_year_month(y, mm))

    for m in re.finditer(r"(?P<y>20\d{2})\s*年", raw_text or ""):
        years.append(int(m.group("y")))

    years = sorted(set(years))
    yms = sorted(set(yms))
    return yms, years


def detect_budget_conflicts(
    *,
    doc_id: str,
    parser: LogicOnParser,
    raw_text: str,
    page_texts: Dict[int, str],
    amount_tolerance_wan: float,
) -> tuple[list[ConflictItem], list[ExtractedEntity]]:
    entities: list[ExtractedEntity] = []
    conflicts: list[ConflictItem] = []

    table_summary = _extract_budget_table_summary(raw_text)
    unit_total = _extract_budget_total_from_table_rows(raw_text)

    direct_total = None
    grand_total = None
    source_total = None

    for k, v in table_summary.items():
        if "直接费用" in k:
            direct_total = float(v)
        if k in {"合计", "合计"}:
            grand_total = float(v)
        if k.endswith("合计") and len(k) <= 6:
            grand_total = float(v)

    for k, v in table_summary.items():
        if re.match(r"^[一二三四五六七八九十]+、", k) or "财政资金" in k or "自筹资金" in k:
            if "合计" not in k and "直接费用" not in k:
                source_total = float(source_total or 0.0) + float(v)

    items = _extract_budget_items(raw_text)
    items_sum = float(sum(items.values()))

    total = None
    compare_label = ""
    if direct_total is not None and items:
        total = float(direct_total)
        compare_label = "直接费用"
    elif grand_total is not None and source_total is not None:
        total = float(grand_total)
        items_sum = float(source_total)
        compare_label = "资金来源合计"
    elif unit_total is not None and grand_total is not None:
        total = float(grand_total)
        items_sum = float(unit_total)
        compare_label = "单位预算合计"
    else:
        total = _extract_budget_total(raw_text)
        compare_label = "预算"

    total_patterns: list[str] = []
    detail_patterns: list[str] = []
    if compare_label == "直接费用":
        total_patterns = [
            r"预算科目名称:.*直接费用.*金额:\s*\d",
            r"预算科目名称:.*合\s*计.*金额:\s*\d",
        ]
        detail_patterns = [
            r"预算科目名称:.*设备费.*金额:\s*\d",
            r"预算科目名称:.*业务费.*金额:\s*\d",
            r"预算科目名称:.*劳务费.*金额:\s*\d",
        ]
    elif compare_label == "单位预算合计":
        total_patterns = [
            r"经费预算明细表/合计:\s*\d",
            r"/合计:\s*\d",
        ]
        detail_patterns = [
            r"预算科目名称:.*合\s*计.*金额:\s*\d",
            r"预算科目名称:.*直接费用.*金额:\s*\d",
        ]
    elif compare_label == "资金来源合计":
        total_patterns = [
            r"预算科目名称:.*合\s*计.*金额:\s*\d",
            r"预算科目名称:.*财政资金.*金额:\s*\d",
            r"预算科目名称:.*自筹资金.*金额:\s*\d",
        ]
        detail_patterns = [
            r"预算科目名称:.*财政资金.*金额:\s*\d",
            r"预算科目名称:.*自筹资金.*金额:\s*\d",
        ]
    else:
        total_patterns = [r"资金申请总额", r"资金下达总额", r"预算总额", r"总预算", r"预算科目名称:.*合\s*计.*金额:\s*\d"]
        detail_patterns = [r"\[表格行\d+\].*预算科目名称:.*金额:\s*\d"]

    total_page, total_snippet = parser.pick_evidence_snippet(
        page_texts=page_texts,
        patterns=total_patterns,
    )
    detail_page, detail_snippet = parser.pick_evidence_snippet(
        page_texts=page_texts,
        patterns=detail_patterns,
    )

    ent_total_id = f"E_budget_total_{doc_id}"
    ent_items_id = f"E_budget_items_{doc_id}"

    if total is not None:
        entities.append(
            ExtractedEntity(
                entity_id=ent_total_id,
                entity_type="budget_total",
                name="预算总额",
                value=f"{total:.4f}",
                normalized={"amount_wan": total},
                spans=[
                    DocSpan(
                        page=(total_page + 1) if total_page is not None else None,
                        section_title="预算",
                        snippet=total_snippet,
                    )
                ]
                if total_snippet
                else [],
            )
        )

    entities.append(
        ExtractedEntity(
            entity_id=ent_items_id,
            entity_type="budget_items",
            name="预算明细",
            value="",
            normalized={"items_wan": items, "sum_wan": items_sum},
            spans=[
                DocSpan(
                    page=(detail_page + 1) if detail_page is not None else None,
                    section_title="预算明细",
                    snippet=detail_snippet,
                )
            ]
            if detail_snippet
            else [],
        )
    )

    if total is None or items_sum == 0:
        return conflicts, entities

    delta = float(items_sum) - float(total)
    if abs(delta) <= float(amount_tolerance_wan):
        return conflicts, entities

    conflicts.append(
        ConflictItem(
            conflict_id=f"C_budget_sum_{doc_id}",
            severity=ConflictSeverity.RED,
            category=ConflictCategory.BUDGET_SUM,
            title="预算总额与明细求和不一致",
            description=f"{compare_label}总额为 {float(total):.2f} 万元，但明细求和为 {float(items_sum):.2f} 万元，差额 {delta:.2f} 万元。",
            evidence=[
                DocSpan(
                    page=(total_page + 1) if total_page is not None else None,
                    section_title="预算",
                    snippet=total_snippet,
                ),
                DocSpan(
                    page=(detail_page + 1) if detail_page is not None else None,
                    section_title="预算明细",
                    snippet=detail_snippet,
                ),
            ],
            related_entities=[ent_total_id, ent_items_id],
            rule_id="R-BUDGET-01",
        )
    )
    return conflicts, entities


def detect_time_conflicts(
    *,
    doc_id: str,
    parser: LogicOnParser,
    raw_text: str,
    page_texts: Dict[int, str],
    date_tolerance_months: int,
) -> tuple[list[ConflictItem], list[ExtractedEntity]]:
    entities: list[ExtractedEntity] = []
    conflicts: list[ConflictItem] = []

    start_ym, end_ym, duration_months = _extract_exec_period(raw_text)
    milestone_yms, milestone_years = _extract_milestone_year_months(raw_text)

    latest_ym = max(milestone_yms) if milestone_yms else None
    exec_page, exec_snippet = parser.pick_evidence_snippet(
        page_texts=page_texts,
        patterns=_build_exec_period_patterns(start_ym, end_ym, duration_months),
    )
    prog_page, prog_snippet = parser.pick_evidence_snippet(
        page_texts=page_texts,
        patterns=_build_progress_patterns(latest_ym, milestone_years),
    )

    ent_exec_id = f"E_exec_{doc_id}"
    ent_prog_id = f"E_progress_{doc_id}"

    entities.append(
        ExtractedEntity(
            entity_id=ent_exec_id,
            entity_type="time_exec_period",
            name="执行期",
            value="",
            normalized={
                "start_ym": start_ym,
                "end_ym": end_ym,
                "duration_months": duration_months,
            },
            spans=[
                DocSpan(
                    page=(exec_page + 1) if exec_page is not None else None,
                    section_title="基本信息",
                    snippet=exec_snippet,
                )
            ]
            if exec_snippet
            else [],
        )
    )
    entities.append(
        ExtractedEntity(
            entity_id=ent_prog_id,
            entity_type="time_progress",
            name="进度安排",
            value="",
            normalized={"milestone_yms": milestone_yms, "years": milestone_years},
            spans=[
                DocSpan(
                    page=(prog_page + 1) if prog_page is not None else None,
                    section_title="进度安排",
                    snippet=prog_snippet,
                )
            ]
            if prog_snippet
            else [],
        )
    )

    if not milestone_yms and not milestone_years:
        return conflicts, entities

    if start_ym is not None and end_ym is not None and milestone_yms:
        latest = max(milestone_yms)
        if latest > end_ym + int(date_tolerance_months):
            conflicts.append(
                ConflictItem(
                    conflict_id=f"C_time_span_{doc_id}",
                    severity=ConflictSeverity.RED,
                    category=ConflictCategory.TIME_SPAN,
                    title="执行期与进度跨度不一致",
                    description="执行期的起止时间与进度安排中的最晚时间节点不一致，建议核查详细任务进度安排是否跨期。",
                    evidence=[
                        DocSpan(
                            page=(exec_page + 1) if exec_page is not None else None,
                            section_title="基本信息",
                            snippet=exec_snippet,
                        ),
                        DocSpan(
                            page=(prog_page + 1) if prog_page is not None else None,
                            section_title="进度安排",
                            snippet=prog_snippet,
                        ),
                    ],
                    related_entities=[ent_exec_id, ent_prog_id],
                    rule_id="R-TIME-01",
                )
            )
        return conflicts, entities

    if duration_months is not None and milestone_years:
        duration_years = max(1, int(round(duration_months / 12.0)))
        if len(milestone_years) >= 2:
            span_years = int(max(milestone_years) - min(milestone_years) + 1)
            if span_years > duration_years:
                conflicts.append(
                    ConflictItem(
                        conflict_id=f"C_time_span_{doc_id}",
                        severity=ConflictSeverity.YELLOW,
                        category=ConflictCategory.TIME_SPAN,
                        title="执行期与进度跨度可能不一致",
                        description=(
                            f"执行期描述为约 {duration_years} 年，但进度安排中出现的年份跨度为 {span_years} 年，建议复核是否存在跨期节点。"
                        ),
                        evidence=[
                            DocSpan(
                                page=(exec_page + 1) if exec_page is not None else None,
                                section_title="基本信息",
                                snippet=exec_snippet,
                            ),
                            DocSpan(
                                page=(prog_page + 1) if prog_page is not None else None,
                                section_title="进度安排",
                                snippet=prog_snippet,
                            ),
                        ],
                        related_entities=[ent_exec_id, ent_prog_id],
                        rule_id="R-TIME-01",
                    )
                )
        return conflicts, entities

    return conflicts, entities


def detect_metric_conflicts(
    *,
    doc_id: str,
    raw_text: str,
    page_texts: Optional[Dict[int, str]] = None,
    metric_tolerance_ratio: float,
) -> tuple[list[ConflictItem], list[ExtractedEntity]]:
    entities: list[ExtractedEntity] = []
    conflicts: list[ConflictItem] = []

    if not raw_text:
        return conflicts, entities

    def normalize_name(name: str) -> str:
        n = re.sub(r"[\s\u3000:：,，;；()（）\[\]【】<>《》\-_/\\]+", "", (name or "")).strip()
        if not n:
            return ""
        n = re.sub(r"[xX×]", "", n)
        if "培养" in n and "研究生" in n:
            return "培养研究生"
        return n[-18:]

    def normalize_unit(unit: str) -> str:
        u = (unit or "").strip()
        if u in {"名", "人"}:
            return "人"
        return u

    def has_metric_keywords(prefix: str) -> bool:
        return bool(
            re.search(
                r"培养|研究生|博士|硕士|论文|专利|软著|标准|获奖|推广|示范|服务对象满意度|满意度|人才",
                prefix or "",
            )
        )

    mentions: list[tuple[str, float, str, str]] = []

    with_constraint_re = re.compile(
        r"(?P<prefix>[^。\n]{0,50}?)(?P<constraint>不少于|不低于|达到|≥|<=|≤|>=|=)\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>篇|件|项|个|次|名|人|%|％|万元|万|元)"
    )
    for m in with_constraint_re.finditer(raw_text):
        name = normalize_name(m.group("prefix") or "")
        if not name:
            continue
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        unit = normalize_unit((m.group("unit") or "").strip())
        if unit == "元":
            val = _amount_to_wan(val, unit)
            unit = "万元"
        if unit == "万":
            unit = "万元"
        start = max(0, m.start() - 50)
        end = min(len(raw_text), m.end() + 50)
        snippet = raw_text[start:end].strip()
        mentions.append((name, float(val), unit, snippet))

    without_constraint_re = re.compile(
        r"(?P<prefix>[^。\n]{0,50}?)(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>名|人|篇|件|项|个|次)"
    )
    for m in without_constraint_re.finditer(raw_text):
        prefix_raw = (m.group("prefix") or "").strip()
        if not has_metric_keywords(prefix_raw):
            continue
        name = normalize_name(prefix_raw)
        if not name:
            continue
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        unit = normalize_unit((m.group("unit") or "").strip())
        start = max(0, m.start() - 50)
        end = min(len(raw_text), m.end() + 50)
        snippet = raw_text[start:end].strip()
        mentions.append((name, float(val), unit, snippet))

    table_metric_re = re.compile(r"培养研究生（人）[^。\n]{0,200}?实施期目标[:：]\s*(?P<num>\d+(?:\.\d+)?)")
    for m in table_metric_re.finditer(raw_text):
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        start = max(0, m.start() - 60)
        end = min(len(raw_text), m.end() + 60)
        snippet = raw_text[start:end].strip()
        mentions.append(("培养研究生", float(val), "人", snippet))

    grouped: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for name, val, unit, snippet in mentions:
        key = (name, unit)
        grouped.setdefault(key, []).append((val, snippet))

    idx = 1
    for (name, unit), pairs in grouped.items():
        if len(pairs) < 2:
            continue
        vals = [v for v, _ in pairs]
        vmin = min(vals)
        vmax = max(vals)
        if vmin <= 0:
            continue
        if (vmax - vmin) / vmin <= float(metric_tolerance_ratio):
            continue
        ent_id = f"E_metric_{doc_id}_{idx}"
        idx += 1
        entities.append(
            ExtractedEntity(
                entity_id=ent_id,
                entity_type="metric",
                name=name,
                value="",
                normalized={"values": vals, "unit": unit},
                spans=[],
            )
        )
        evidence: list[DocSpan] = []
        if page_texts:
            for _, snip in pairs[:2]:
                page = _find_page_for_snippet(page_texts, snip)
                evidence.append(
                    DocSpan(
                        page=(page + 1) if page is not None else None,
                        section_title="指标",
                        snippet=snip,
                    )
                )
        conflicts.append(
            ConflictItem(
                conflict_id=f"C_metric_{doc_id}_{idx}",
                severity=ConflictSeverity.YELLOW,
                category=ConflictCategory.METRIC_VALUE,
                title="同一指标多处目标值可能不一致",
                description=f"指标“{name}”在文档中出现多个目标值（单位：{unit}），建议复核口径是否一致。",
                evidence=evidence,
                related_entities=[ent_id],
                rule_id="R-METRIC-01",
            )
        )

    return conflicts, entities


def _strip_code_fence(content: str) -> str:
    text = (content or "").strip()
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text


def _extract_first_json_object(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return ""
    return raw[start : end + 1].strip()


def _find_page_for_snippet(page_texts: Dict[int, str], snippet: str) -> Optional[int]:
    s = (snippet or "").strip()
    if not s:
        return None
    key = s[:60] if len(s) > 60 else s
    for page, txt in sorted(page_texts.items(), key=lambda x: x[0]):
        if key and key in (txt or ""):
            return page
    return None


async def detect_metric_conflicts_with_llm(
    *,
    doc_id: str,
    raw_text: str,
    page_texts: Dict[int, str],
    llm: Any,
    metric_tolerance_ratio: float,
) -> tuple[list[ConflictItem], list[ExtractedEntity]]:
    entities: list[ExtractedEntity] = []
    conflicts: list[ConflictItem] = []
    if not raw_text:
        return conflicts, entities

    mentions: list[dict[str, object]] = []
    idx = 1
    for m in re.finditer(
        r"(?P<prefix>[^。\n]{0,40}?)(?P<constraint>不少于|不低于|达到|≥|<=|≤|>=|=)\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>篇|件|项|个|次|%|％|万元|万|元)",
        raw_text,
    ):
        prefix = re.sub(r"[\s\u3000:：,，;；()（）\[\]【】<>《》\-_/\\]+", "", (m.group("prefix") or "")).strip()
        if not prefix:
            continue
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        unit = (m.group("unit") or "").strip()
        if unit == "元":
            val = _amount_to_wan(val, unit)
            unit = "万元"
        if unit == "万":
            unit = "万元"

        start = max(0, m.start() - 40)
        end = min(len(raw_text), m.end() + 40)
        snippet = raw_text[start:end].strip()
        mentions.append(
            {
                "id": f"M{idx}",
                "name_guess": prefix[-18:],
                "value": float(val),
                "unit": unit,
                "text": m.group(0),
                "snippet": snippet,
            }
        )
        idx += 1
        if idx > 80:
            break

    if len(mentions) < 2:
        return conflicts, entities

    prompt_lines: list[str] = []
    for it in mentions:
        mid = str(it.get("id", ""))
        name_guess = str(it.get("name_guess", ""))
        value = it.get("value", 0.0)
        unit = str(it.get("unit", ""))
        snippet = str(it.get("snippet", ""))
        prompt_lines.append(f"{mid}: name_guess={name_guess} ; value={value} ; unit={unit} ; snippet={snippet}")

    prompt = (
        "你是项目申报书/任务书的逻辑一致性核验助手。请将下列“指标条目”按同一指标聚类，并判断是否存在同一指标多处目标值不一致。\n"
        "注意：不同阶段目标/年度目标不一定等于最终目标；若无法确定是否为同一口径，请给出 YELLOW。\n"
        "输出严格 JSON（不要代码块，不要解释），格式：\n"
        "{"
        "\"clusters\":[{"
        "\"canonical_name\":str,"
        "\"unit\":str,"
        "\"mention_ids\":[str],"
        "\"values\":[number],"
        "\"has_conflict\":bool,"
        "\"severity\":\"YELLOW\"|\"RED\","
        "\"reason\":str"
        "}]}。\n"
        "条目：\n"
        + "\n".join(prompt_lines)
    )

    response = await llm.ainvoke(prompt)
    content = _strip_code_fence(getattr(response, "content", str(response)))
    payload = safe_json_loads(_extract_first_json_object(content), default={}) or {}
    clusters = payload.get("clusters")
    if not isinstance(clusters, list):
        return conflicts, entities

    mention_map = {str(m.get("id")): m for m in mentions}

    entity_idx = 1
    for c in clusters:
        if not isinstance(c, dict):
            continue
        has_conflict = bool(c.get("has_conflict", False))
        if not has_conflict:
            continue
        canonical = str(c.get("canonical_name", "") or "").strip()
        unit = str(c.get("unit", "") or "").strip()
        reason = str(c.get("reason", "") or "").strip()
        sev = str(c.get("severity", "YELLOW") or "YELLOW").strip().upper()
        severity = ConflictSeverity.RED if sev == "RED" else ConflictSeverity.YELLOW

        mids = c.get("mention_ids") if isinstance(c.get("mention_ids"), list) else []
        values = c.get("values") if isinstance(c.get("values"), list) else []
        norm_values: list[float] = []
        for v in values:
            try:
                norm_values.append(float(v))
            except Exception:
                continue

        if len(norm_values) >= 2:
            vmin = min(norm_values)
            vmax = max(norm_values)
            if vmin > 0 and (vmax - vmin) / vmin <= float(metric_tolerance_ratio):
                continue

        ent_id = f"E_metric_llm_{doc_id}_{entity_idx}"
        entity_idx += 1
        entities.append(
            ExtractedEntity(
                entity_id=ent_id,
                entity_type="metric",
                name=canonical or "未命名指标",
                value="",
                normalized={"values": norm_values or values, "unit": unit, "mention_ids": mids},
                spans=[],
            )
        )

        evidence: list[DocSpan] = []
        for mid in [str(x) for x in (mids or [])][:3]:
            info = mention_map.get(mid, {})
            snippet = str(info.get("snippet", "") or "")
            page = _find_page_for_snippet(page_texts, snippet)
            evidence.append(
                DocSpan(
                    page=(page + 1) if page is not None else None,
                    section_title="指标",
                    snippet=snippet,
                )
            )

        conflicts.append(
            ConflictItem(
                conflict_id=f"C_metric_llm_{doc_id}_{entity_idx}",
                severity=severity,
                category=ConflictCategory.METRIC_VALUE,
                title="同一指标多处目标值可能不一致",
                description=(reason or f"指标“{canonical}”在文档中出现多个目标值（单位：{unit}），建议复核口径是否一致。"),
                evidence=evidence,
                related_entities=[ent_id],
                rule_id="R-METRIC-01",
            )
        )

    return conflicts, entities
