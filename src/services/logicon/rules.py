import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.models.logicon import (
    ConflictCategory,
    ConflictItem,
    ConflictSeverity,
    DocSpan,
    ExtractedEntity,
)
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


# 广东省等模板常见：「预算科目名称:科目名 ; 预算科目名称:金额」，无单独「金额:」列
_BUDGET_DUAL_SUBJECT_RE = re.compile(
    r"预算科目名称:(?P<name>[^;|]+?)\s*;\s*预算科目名称:(?P<num>\d+(?:\.\d+)?)\s*(?:万元)?"
)


def _normalize_budget_table_key(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip())


def _extract_budget_named_amount_wan(raw_text: str, labels: list[str]) -> Optional[float]:
    """在正文/表格拼接文本中按标签近邻抓取金额（万元口径）。"""
    text = raw_text or ""
    if not text:
        return None
    default_unit = _infer_budget_unit(text)
    for lb in labels:
        if not lb:
            continue
        pat = re.compile(rf"{re.escape(lb)}[^\n。；;:：]{{0,26}}(?P<num>\d+(?:\.\d+)?)\s*(?P<u>万元|万)?")
        for m in pat.finditer(text):
            num = _parse_number(m.group("num"))
            if num is None or float(num) <= 0:
                continue
            # 避免把“序号:6”等非金额字段误判为金额（尤其是配套/自筹等兜底标签）
            around = text[max(0, m.start() - 18) : min(len(text), m.end() + 18)]
            if re.search(r"序号\s*[:：]?\s*\d", around):
                continue
            # 若缺少单位，要求近邻出现“金额”提示，否则大概率是序号/编号/条目数字
            has_unit = bool((m.group("u") or "").strip())
            if not has_unit:
                around2 = text[m.start() : min(len(text), m.end() + 40)]
                if "金额" not in around and "金额" not in around2:
                    continue
            unit = (m.group("u") or "").strip() or default_unit
            val = _amount_to_wan(float(num), unit)
            # 避免把年份误判为金额
            if 1900 <= int(float(num)) <= 2100 and unit in {"", "万元"}:
                continue
            return float(val)
    return None


def _budget_fiscal_tier_from_table_summary(ts: Dict[str, float]) -> Dict[str, Any]:
    """从表格科目字典抽取「省级财政总盘 /（一）直接费用 /（二）间接费用」，用于与 直接+间接 交叉核对。"""
    prov: Optional[float] = None
    ind: Optional[float] = None
    dr: Optional[float] = None
    for key_raw, v in (ts or {}).items():
        k = str(key_raw or "").strip()
        nk = _normalize_budget_table_key(k)
        if not nk or re.match(r"^[0-9]", nk) or "万元" in nk:
            continue
        if "自筹" in nk or "配套" in nk:
            continue
        if "设备费" in nk or "业务费" in nk or "劳务费" in nk or "材料费" in nk:
            continue
        if "其中" in nk and ("购置" in nk or "绩效" in nk or "试制" in nk):
            continue
        if nk in {"合计", "总计"} or (nk.endswith("合计") and len(nk) <= 8):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if ("省级财政" in nk or (nk.startswith("一、") and "财政" in nk)) and "间接" not in nk:
            prov = fv if prov is None else max(prov, fv)
        elif "间接费用" in nk or nk.startswith("（二）间接"):
            ind = fv if ind is None else max(ind, fv)
        elif "直接费用" in nk and "间接" not in nk:
            dr = fv if dr is None else max(dr, fv)
    out: Dict[str, Any] = {
        "provincial_fiscal_wan": prov,
        "direct_block_wan": dr,
        "indirect_block_wan": ind,
    }
    if prov is not None and dr is not None and ind is not None:
        out["direct_plus_indirect_wan"] = float(dr) + float(ind)
        out["provincial_vs_components_delta_wan"] = float(dr) + float(ind) - float(prov)
    return out


def _budget_source_components_from_table_summary(ts: Dict[str, float]) -> Dict[str, Any]:
    """抽取资金来源口径：省级财政/自筹/配套与表内合计，便于来源分项对账。"""
    prov: Optional[float] = None
    self_raised: Optional[float] = None
    matching: Optional[float] = None
    grand_total: Optional[float] = None
    for key_raw, v in (ts or {}).items():
        k = str(key_raw or "").strip()
        nk = _normalize_budget_table_key(k)
        if not nk:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if nk in {"合计", "总计"} or (nk.endswith("合计") and len(nk) <= 8):
            grand_total = fv if grand_total is None else max(grand_total, fv)
            continue
        if ("省级财政" in nk or (nk.startswith("一、") and "财政" in nk)) and "间接" not in nk:
            prov = fv if prov is None else max(prov, fv)
            continue
        if "自筹" in nk:
            self_raised = fv if self_raised is None else max(self_raised, fv)
            continue
        if "配套" in nk:
            matching = fv if matching is None else max(matching, fv)
            continue
    out: Dict[str, Any] = {
        "source_provincial_wan": prov,
        "source_self_raised_wan": self_raised,
        "source_matching_wan": matching,
        "source_grand_total_wan": grand_total,
    }
    if prov is not None and self_raised is not None and matching is not None:
        out["source_components_sum_wan"] = float(prov) + float(self_raised) + float(matching)
        if grand_total is not None:
            out["source_vs_grand_delta_wan"] = float(out["source_components_sum_wan"]) - float(grand_total)
    return out


def _append_fiscal_tier_conflict_if_needed(
    *,
    conflicts: list[ConflictItem],
    doc_id: str,
    fiscal_tier: Dict[str, Any],
    amount_tolerance_wan: float,
    page_texts: Dict[int, str],
    raw_text: str,
    parser: LogicOnParser,
) -> None:
    """若同时存在省级财政总盘与（一）直接+（二）间接，则核对 直接+间接 是否等于总盘。"""
    d = fiscal_tier.get("provincial_vs_components_delta_wan")
    if d is None:
        return
    if abs(float(d)) <= float(amount_tolerance_wan):
        return
    prov = fiscal_tier.get("provincial_fiscal_wan")
    dr = fiscal_tier.get("direct_block_wan")
    ind = fiscal_tier.get("indirect_block_wan")
    sumdi = fiscal_tier.get("direct_plus_indirect_wan")
    pt_ev, ev_sliced = _evidence_page_texts_for_project_body(page_texts, raw_text)
    p1, s1 = parser.pick_evidence_snippet(
        page_texts=pt_ev,
        patterns=[
            r"预算科目名称:.*省级财政",
            r"预算科目名称:.*一、.*省级财政",
        ],
    )
    p2, s2 = parser.pick_evidence_snippet(
        page_texts=pt_ev,
        patterns=[
            r"预算科目名称:.*间接费用",
            r"预算科目名称:.*（二）间接",
        ],
    )
    if ev_sliced:
        if s1:
            p1 = _remap_evidence_page(page_texts, s1)
        if s2:
            p2 = _remap_evidence_page(page_texts, s2)
    s1 = s1 or ""
    s2 = s2 or ""
    conflicts.append(
        ConflictItem(
            conflict_id=f"C_budget_fiscal_tier_{doc_id}",
            severity=ConflictSeverity.RED,
            category=ConflictCategory.BUDGET_SUM,
            title="省级财政资金与「直接+间接」之和不一致",
            description=(
                f"表格中省级财政总盘约 **{float(prov):.2f}** 万元，"
                f"（一）直接费用 **{float(dr):.2f}** 万元与（二）间接费用 **{float(ind):.2f}** 万元之和为 **{float(sumdi):.2f}** 万元，"
                f"差额 **{float(d):+.2f}** 万元；请核对是否漏行、串行或单位不一致。"
            ),
            evidence=[
                DocSpan(
                    page=(p1 + 1) if p1 is not None else None,
                    section_title="预算·省级财政",
                    snippet=s1,
                ),
                DocSpan(
                    page=(p2 + 1) if p2 is not None else None,
                    section_title="预算·间接费用",
                    snippet=s2,
                ),
            ],
            related_entities=[f"E_budget_items_{doc_id}"],
            rule_id="R-BUDGET-01",
        )
    )


def _append_budget_source_conflict_if_needed(
    *,
    conflicts: list[ConflictItem],
    doc_id: str,
    source_norm: Dict[str, Any],
    amount_tolerance_wan: float,
    page_texts: Dict[int, str],
    raw_text: str,
    parser: LogicOnParser,
) -> None:
    """若可解析到 省级+自筹+配套 与 合计，则核对来源分项是否与总额一致。"""
    d = source_norm.get("source_vs_grand_delta_wan")
    if d is None:
        return
    if abs(float(d)) <= float(amount_tolerance_wan):
        return
    prov = source_norm.get("source_provincial_wan")
    self_raised = source_norm.get("source_self_raised_wan")
    matching = source_norm.get("source_matching_wan")
    grand = source_norm.get("source_grand_total_wan")
    ssum = source_norm.get("source_components_sum_wan")
    pt_ev, ev_sliced = _evidence_page_texts_for_project_body(page_texts, raw_text)
    p1, s1 = parser.pick_evidence_snippet(
        page_texts=pt_ev,
        patterns=[
            r"预算科目名称:.*合\s*计",
            r"预算科目名称:.*省级财政",
        ],
    )
    p2, s2 = parser.pick_evidence_snippet(
        page_texts=pt_ev,
        patterns=[
            r"预算科目名称:.*自筹",
            r"预算科目名称:.*配套",
        ],
    )
    if ev_sliced:
        if s1:
            p1 = _remap_evidence_page(page_texts, s1)
        if s2:
            p2 = _remap_evidence_page(page_texts, s2)
    s1 = s1 or ""
    s2 = s2 or ""
    conflicts.append(
        ConflictItem(
            conflict_id=f"C_budget_source_sum_{doc_id}",
            severity=ConflictSeverity.RED,
            category=ConflictCategory.BUDGET_SUM,
            title="预算合计与资金来源分项不一致",
            description=(
                f"来源分项中省级财政 **{float(prov):.2f}** 万元 + 自筹 **{float(self_raised):.2f}** 万元 + 配套 **{float(matching):.2f}** 万元"
                f" = **{float(ssum):.2f}** 万元，但表内合计为 **{float(grand):.2f}** 万元，差额 **{float(d):+.2f}** 万元。"
            ),
            evidence=[
                DocSpan(
                    page=(p1 + 1) if p1 is not None else None,
                    section_title="预算·来源合计",
                    snippet=s1,
                ),
                DocSpan(
                    page=(p2 + 1) if p2 is not None else None,
                    section_title="预算·来源分项",
                    snippet=s2,
                ),
            ],
            related_entities=[f"E_budget_items_{doc_id}"],
            rule_id="R-BUDGET-01",
        )
    )


def _parse_dual_budget_subject_line(line: str) -> Optional[Tuple[str, float]]:
    m = _BUDGET_DUAL_SUBJECT_RE.search(line or "")
    if not m:
        return None
    name = (m.group("name") or "").strip()
    num = _parse_number(m.group("num"))
    if num is None:
        return None
    return name, float(num)


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

    row_re2 = re.compile(r"^\[表格行\d+\]\s*(?P<line>.+)$", re.MULTILINE)
    for m in row_re2.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        parsed = _parse_dual_budget_subject_line(line)
        if not parsed:
            continue
        name, num = parsed
        amount = _amount_to_wan(float(num), default_unit)
        if re.search(r"其中|购置|试制|升级|改造|租赁", name):
            continue
        if "设备费" in name:
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
        dual = _parse_dual_budget_subject_line(line)
        if dual:
            nk = _normalize_budget_table_key(dual[0])
            if nk in {"合计", "总计"} or nk.endswith("合计"):
                num = _parse_number(str(dual[1]))
                if num is not None:
                    totals.append(_amount_to_wan(float(num), default_unit))
            if "省级财政" in dual[0] and "配套" not in dual[0] and "自筹" not in dual[0]:
                num = _parse_number(str(dual[1]))
                if num is not None:
                    totals.append(_amount_to_wan(float(num), default_unit))
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
    for m in row_re.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        dual = _parse_dual_budget_subject_line(line)
        if not dual:
            continue
        name_raw, num = dual
        key = _normalize_budget_table_key(name_raw)
        out[key] = _amount_to_wan(float(num), default_unit)
    return out


def _extract_budget_total(raw_text: str) -> Optional[float]:
    default_unit = _infer_budget_unit(raw_text)
    keywords = [
        "资金申请总额",
        "资金下达总额",
        "总预算",
        "预算总额",
        "省级财政资金",
        "专项经费",
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
    return patterns


def _build_progress_patterns(latest_ym: Optional[int], milestone_years: list[int]) -> list[str]:
    patterns: list[str] = []
    if latest_ym is not None:
        y, m = _ym_to_year_month(latest_ym)
        patterns.extend(_build_year_month_patterns(y, m))
    if milestone_years:
        y = max(milestone_years)
        patterns.append(rf"{int(y)}\s*年")
    return patterns


def _extract_exec_period(raw_text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """在多处「yyyy-mm 至 yyyy-mm」并存时，优先带起止年月/实施期限等本项目字段的命中，避免误取他人课题行。"""
    s = raw_text or ""

    def _score_date_range_match(m: re.Match) -> int:
        lo = max(0, m.start() - 260)
        hi = min(len(s), m.end() + 80)
        zone = s[lo:hi]
        sc = 0
        if re.search(
            r"起止年月|起\s*止\s*年\s*月|起止时间|起\s*止\s*时\s*间|实施期限|项目期限|执行期|专项.{0,20}起止",
            zone,
            re.I,
        ):
            sc += 85
        # 噪声仅在紧贴日期的小窗内扣分，避免封面「填报说明」里「国内外现状及趋势…」等
        # 与起止年月同页但相隔较远时误伤，导致执行期误取为进度甘特首段（如 2025年7月-2026年1月）。
        nlo = max(0, m.start() - 52)
        nhi = min(len(s), m.end() + 36)
        noise_zone = s[nlo:nhi]
        if _MILESTONE_YEAR_CONTEXT_NOISE.search(noise_zone):
            sc -= 130
        return sc

    cands: list[tuple[int, int, tuple[Optional[int], Optional[int], Optional[int]]]] = []
    for m in re.finditer(
        r"(?P<sy>20\d{2})[./\-](?P<sm>\d{1,2})\s*[-—~至到]\s*(?P<ey>20\d{2})[./\-](?P<em>\d{1,2})",
        s,
    ):
        sy = int(m.group("sy"))
        sm = int(m.group("sm"))
        ey = int(m.group("ey"))
        em = int(m.group("em"))
        tup = (_parse_year_month(sy, sm), _parse_year_month(ey, em), None)
        cands.append((_score_date_range_match(m), m.start(), tup))

    for m in re.finditer(
        r"(?P<sy>20\d{2})\s*年\s*(?P<sm>\d{1,2})?\s*月?\s*[-—~至到]\s*(?P<ey>20\d{2})\s*年\s*(?P<em>\d{1,2})?\s*月?",
        s,
    ):
        sy = int(m.group("sy"))
        sm = int(m.group("sm")) if m.group("sm") else 1
        ey = int(m.group("ey"))
        em = int(m.group("em")) if m.group("em") else 12
        tup = (_parse_year_month(sy, sm), _parse_year_month(ey, em), None)
        cands.append((_score_date_range_match(m), m.start(), tup))

    if cands:
        cands.sort(key=lambda x: (-x[0], x[1]))
        best_sc = cands[0][0]
        if best_sc < -40:
            pos = [c for c in cands if c[0] >= 0]
            pick = pos[0] if pos else cands[0]
        else:
            pick = cands[0]
        return pick[2]

    duration_year = None
    duration_month = None
    for m in re.finditer(r"(?:(?:执行期|实施期|周期|年限)[^。\n]{0,20})?(?P<num>\d{1,2})\s*(?P<unit>年|个月)", s):
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


def _merged_page_text(page_texts: Dict[int, str]) -> str:
    return "\n\n".join((page_texts.get(i) or "") for i in sorted(page_texts))


# 从该位置起多为参考文献、附件、简历、单位意见等，与「本项目」时间/预算/指标无关
_PROJECT_BODY_TAIL_END = re.compile(
    r"(?:^|[\r\n])\s*(?:"
    r"参考文献\s*[\r\n:：]|"
    r"附录\s*[\r\n:：]|"
    r"附件\s*[\d一二三四五六七八九十第]*\s*[、，,：:\s]*[\r\n]|"
    r"个人简历|项目负责人简介|申请人简介|主要研究人员简介|"
    r"攻读博士学位期间|在站期间|在学期间发表的论文|在学期间|"
    r"以往承担的主要项目|合作单位意见|申报单位意见|审核意见|推荐意见"
    r")\s*",
    re.I | re.MULTILINE,
)


_PROJECT_LATE_STRUCTURED_ANCHOR = re.compile(
    r"预算科目名称|预算科目|预算明细|一、省级财政资金|"
    r"项目绩效评价考核目标及指标|绩效\s*指标|实施期目标|第一年度目标|第二年度目标|第三年度目标",
    re.I,
)


def _project_relevant_text(raw_text: str, *, min_cut_pos: int = 1800) -> str:
    """保留本项目申报/任务正文：文首至参考文献、附录、简历等之前，供时间/预算/指标规则统一扫描。"""
    s = raw_text or ""
    if len(s) <= min_cut_pos:
        return s.strip()
    # 参考文献/附件等标记可能出现在中段；若后文仍有预算/绩效结构化锚点，不应在该点截断。
    for m in _PROJECT_BODY_TAIL_END.finditer(s):
        if m.start() < min_cut_pos:
            continue
        tail = s[m.start() : min(len(s), m.start() + 26000)]
        if _PROJECT_LATE_STRUCTURED_ANCHOR.search(tail):
            continue
        return s[: m.start()].strip()
    return s.strip()


def _evidence_page_texts_for_project_body(
    page_texts: Dict[int, str], raw_text: str
) -> tuple[Dict[int, str], bool]:
    """证据定位用：将全文截为「本项目正文」后再匹配，避免尾部噪声；单键 dict 便于与截断 raw 一致。"""
    body = _project_relevant_text(raw_text)
    if not body.strip():
        return page_texts, False
    return {0: body}, True


def _remap_evidence_page(full_page_texts: Dict[int, str], snippet: str) -> Optional[int]:
    """将基于正文截片的匹配结果映射回原始分页中的页码。"""
    sn = (snippet or "").strip()
    if not sn:
        return None
    key = sn[:100] if len(sn) > 100 else sn
    return _find_page_for_snippet(full_page_texts, key)


# 进度年份抽取时排除：参考文献、团队履历、历史课题、著录引用日期等中的 20xx 年
_MILESTONE_YEAR_CONTEXT_NOISE = re.compile(
    r"参考文献|引用文献|文献综述|国内外现状|个人简介|主要业绩|工作经历|教育经历|"
    r"主编|专著|获奖|科技进步|自然科学奖|承担.{0,8}(国家|省部级).{0,6}(课题|项目)|"
    r"九五|十五|十一五|十二五|十三五|近\s*5\s*年|近\s*十\s*年|"
    r"国家自然科学基金委员会|国家自然基金委|国家重大科研仪器研制|重大科研仪器研制|"
    r"基金委[,，].{0,40}(?:重大|仪器|项目)|"
    r"(?:万元|万\s*元)[^，。;；\n]{0,12}主研|主研\s*[（(，,]|"
    r"完成.{0,30}(?:省|市)?自然科学基金项目情况|对申请人负责的前一个已结题|"
    r"以往承担的主要项目|在研课题|申请人负责|"
    r"(?:课题|项目)编号\s*[:：]?\s*[A-Z0-9]{5,}|"
    r"\[EB/OL\]|\[J/OL\]|\[M/OL\]|\[DB/OL\]|https?://|www\.(?:who|ncbi)\.|doi[:：]\s*10\.|"
    r"ICD-\d+|Revision\s*\(|WHO\.int|"
    r"\[20\d{2}[-/]\d{1,2}[-/]\d{1,2}\]|"  # [2024-10-01] 等引用日期
    r"\)\s*\[20\d{2}|"  # (2023-01-01)[2024-10-01] 中访问日期
    r"引用日期|出版年|获取地址|Available from|accessed on|Retrieved",
    re.I,
)


def _strip_time_snippet_admin_tail(t: str) -> str:
    """去掉封面/表格拼接中的填报说明、机关模板尾等。"""
    x = (t or "").strip()
    if not x:
        return ""
    x = re.sub(r"\s*填\s*报\s*日\s*期\s*[:：].{0,36}$", "", x, flags=re.I).strip()
    x = re.sub(r"\s*填\s*报\s*说\s*明\s*\d?.*$", "", x, flags=re.I).strip()
    x = re.sub(r"\s*.{0,20}管理局制.*$", "", x).strip()
    x = re.sub(r"\s*申\s*报\s*预\s*算\s*年\s*度\s*[:：].{0,16}$", "", x, flags=re.I).strip()
    return x


def _tighten_time_evidence_snippet(snippet: str) -> str:
    """时间证据：从宽上下文中尽量只保留起止年月或日期区间附近，避免整表拼接噪声。"""
    s = (snippet or "").strip()
    if not s:
        return ""
    s = re.sub(r"[\r\n]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # 去掉封面表头里「局中药处…申报预算年度」等挤在起止日期前的拼接噪声
    s2 = re.sub(r"^.{0,80}?(?=起\s*止\s*年\s*月|起止年月)", "", s)
    if s2.strip():
        s = s2.strip()
    # 机关表单常见「起 止 年 月」拆字排版
    m0 = re.search(
        r"起\s*止\s*年\s*月\s*[:：]?\s*("
        r"20\d{2}[./\-]\d{1,2}\s*[-—~至到]\s*20\d{2}[./\-]\d{1,2}|"
        r"20\d{2}\s*年\s*\d{1,2}\s*月?\s*[-—~至到]\s*20\d{2}\s*年\s*\d{1,2}\s*月?"
        r")",
        s,
    )
    if m0:
        seg = (m0.group(0) or "").strip()
        return _strip_time_snippet_admin_tail(seg) + ("…" if len(s) > m0.end() + 5 else "")
    for key in ("起止年月", "起止时间", "实施期限", "项目期限", "执行期"):
        i = s.find(key)
        if i >= 0:
            rest = s[i : i + 220]
            m2 = re.search(
                r"20\d{2}[./\-]\d{1,2}\s*[-—~至到]\s*20\d{2}[./\-]\d{1,2}|"
                r"20\d{2}\s*年\s*\d{1,2}\s*月?\s*[-—~至到]\s*20\d{2}\s*年\s*\d{1,2}\s*月?",
                rest,
            )
            if m2:
                seg = rest[: m2.end()].strip()
                seg = re.split(r"\s*\[表格行", seg, 1)[0].strip()
                seg = _strip_time_snippet_admin_tail(seg)
                return seg + ("…" if len(rest) > m2.end() + 2 else "")
            seg = rest[:130].strip()
            return _strip_time_snippet_admin_tail(seg) + ("…" if len(s[i:]) > 130 else "")
    m = re.search(
        r"20\d{2}\s*[年./-]\s*\d{1,2}\s*月?\s*[-—~至到]\s*20\d{2}\s*[年./-]\s*\d{1,2}\s*月?",
        s,
    )
    if not m:
        m = re.search(r"20\d{2}[./\-]\d{1,2}\s*[-—~至到]\s*20\d{2}[./\-]\d{1,2}", s)
    if m:
        a = max(0, m.start() - 28)
        b = min(len(s), m.end() + 40)
        out = _strip_time_snippet_admin_tail(s[a:b].strip())
        return out + ("…" if len(out) > 200 else "")
    if len(s) > 220:
        return _strip_time_snippet_admin_tail(s[:220].strip()) + "…"
    return _strip_time_snippet_admin_tail(s)


def _pick_time_evidence_snippet(
    *,
    page_texts: Dict[int, str],
    patterns: list[str],
    skip_grant_cv_noise: bool,
) -> tuple[Optional[int], Optional[str]]:
    """时间维度证据：跳过承担课题/主研经费行等噪声命中，并收紧摘录。"""
    if not page_texts or not patterns:
        return None, None
    flags = re.IGNORECASE | re.MULTILINE
    cb, ca = 44, 72
    for page_idx in sorted(page_texts.keys()):
        text = page_texts.get(page_idx) or ""
        if not text.strip():
            continue
        for pat in patterns:
            try:
                m = re.search(pat, text, flags)
            except re.error:
                continue
            if not m:
                continue
            if skip_grant_cv_noise:
                lo = max(0, m.start() - 200)
                hi = min(len(text), m.end() + 140)
                ctx = text[lo:hi]
                if _MILESTONE_YEAR_CONTEXT_NOISE.search(ctx):
                    continue
            start = max(0, m.start() - cb)
            end = min(len(text), m.end() + ca)
            raw_snip = text[start:end].strip()
            snippet = _tighten_time_evidence_snippet(raw_snip)
            if len(snippet) > 520:
                snippet = snippet[:520] + "…"
            return page_idx, snippet
    return None, None


def _is_annual_performance_cell_context(
    raw_text: str, match_start: int, match_end: Optional[int] = None
) -> bool:
    """分年度/阶段目标（含「第二年（20xx」类进度体例）中的篇数、专利件数，不与绩效表「实施期」总量混比。"""
    me = int(match_end) if match_end is not None else int(match_start) + 1
    prev = raw_text[max(0, match_start - 200) : match_start]
    nxt = raw_text[me : min(len(raw_text), me + 200)]
    pat = (
        r"第[一二三]年度目标\s*（当前年度）|第[一二三]年度目标|中期目标\s*（当前年度）|"
        r"第一年度目标|第二年度目标|第三年度目标|年度目标\s*（当前年度）|"
        r"第一年度|第二年度|第三年度|第四年度|"
        r"年度预期研究成果|年度预期成果|本年度预期|"
        r"年度\s*[:：]\s*20\d{2}|"
        r"第[一二三四五六七八九十]+\s*年\s*[（(]|"
        r"第一年[（(]|第二年[（(]|第三年[（(]|第四年[（(]|"
        r"分年度|年度计划|年度安排|年度实施|阶段目标|阶段性目标|中期目标|"
        r"第一阶段|第二阶段|第三阶段|阶段总结|阶段性总结|阶段实施|阶段安排|"
        # 进度安排常见区间体例：2026.4-2027.3 / 2026-04~2027-03 等
        r"\b20\d{2}[./-]\d{1,2}\s*[-—~～]\s*20\d{2}[./-]\d{1,2}\b|"
        r"\b20\d{2}[./-]\d{1,2}\s*[-—~～]\s*20\d{2}[./-]\d{1,2}\b"
    )
    return bool(re.search(pat, prev) or re.search(pat, nxt))


def _is_cv_or_aggregate_paper_context(snippet: str) -> bool:
    """团队/个人累计论文、近 N 篇、简历已发表论文等，不是本项目实施期绩效口径。"""
    s = snippet or ""
    return bool(
        re.search(
            r"近\s*\d+\s*篇|发表论文.{0,30}近\s*\d+|累计.{0,20}论文|累计.{0,12}篇|"
            r"发表学术论文.{0,12}\d{2,4}\s*篇|余篇|主编.{0,8}著作|获国家.{0,8}奖|"
            r"承担.{0,10}国家.{0,8}(基金|项目|课题)|"
            r"已发表论文|既往发表|以副主编|副主编|"
            r"主任医师|副主任医师|主治医师|教授|副教授|研究员|副研究员|博士生导师|"
            r"第一作者或唯一通讯作者|通讯作者发表|他引次数|h-index|h指数|"
            r"researchgate|ResearchGate|个人成果链接|"
            r"在投\s*SCI|在投.{0,14}(?:SCI|E[I])?论文|"
            r"\d{2,}\s*多篇|40多篇|50余篇|"
            r"项目迄今|迄今在学术刊物|不存在任何重复性|本次申请项目.{0,36}研究内容|"
            r"Elsevier|Springer|中国建筑工业出版社|出版专著|参编专著|"
            r"国内学术会议做学术报告|授权软件著作权|"
            r"参与发表|共同发表|合作发表|国内外期刊论文|"
            r"其中(?:SCI|EI)(?:检索|收录)|中文核心|"
            r"具体成果如下|主要代表作|论文目录|参研多项|"
            r"博士课题|硕士课题|工学博士|工学硕士|理学博士|理学硕士|"
            r"毕业于.{0,16}(?:大学|学院)|现任教(?:于)?|辅导员|教务处|教师教学发展|"
            r"员、奖励名称等级|授奖年等）|"
            r"其中国家一级学报\d+篇|中文核心期刊\d+余?篇|发表论文\d+余?篇|"
            r"(?:SCI|EI)收录\d+篇|科技项目\d+项|主持或主研.{0,20}\d+项|"
            r"\[\s*\d+\s*\]\s*[A-Za-z]",  # 文献列表 [1]Author
            s,
            re.I,
        )
    )


def _is_grant_unrelated_trainee_context(snippet: str) -> bool:
    """既往/在读培养人数、查重说明段中的「培养…名」等，非本项目绩效表实施期口径。"""
    s = snippet or ""
    return bool(
        re.search(
            r"项目迄今|迄今.{0,24}(?:培养|毕业|获)|已培养|培养毕业|"
            r"在读.{0,10}(?:硕士|博士)?研究生|硕士学位研究生|"
            r"不存在任何重复性|本次申请项目.{0,40}研究内容|"
            r"第一作者或唯一通讯作者|他引次数|researchgate|个人成果链接",
            s,
            re.I,
        )
    )


def _is_stage_task_metric_noise(snippet: str) -> bool:
    """年度任务/关键节点里的阶段性数量，不等同于实施期总目标。"""
    s = snippet or ""
    return bool(
        re.search(
            r"第一年度任务|第二年度任务|第三年度任务|第[一二三四五六七八九十]+\s*年度任务|"
            r"关键节点|具体任务|年度计划|分年度任务|阶段目标|阶段性目标|"
            r"第一阶段|第二阶段|第三阶段|阶段总结|阶段性总结|阶段实施|阶段安排|"
            r"阶段[一二三四五六七八九十\d]+\s*[:：]|"
            r"年度考核|阶段考核|年度预期研究成果|年度预期成果|本年度预期|"
            r"年度\s*[:：]\s*20\d{2}|"
            r"\b20\d{2}[./-]\d{1,2}\s*[-—~～]\s*20\d{2}[./-]\d{1,2}\b|"
            r"\b20\d{2}\s*年\s*\d{1,2}\s*月\s*[-—~～]\s*20\d{2}\s*年\s*\d{1,2}\s*月\b",
            s,
            re.I,
        )
    )


def _is_metric_background_noise(snippet: str) -> bool:
    """过滤背景/履历/文献/团队介绍等与本项目目标无关语境。"""
    s = snippet or ""
    return bool(
        re.search(
            r"国内外现状|文献综述|参考文献|附件目录|工作简历|教育经历|主要学术业绩|"
            r"近五年|曾荣获|先后主持|已发表|参与发表|SCI收录|EI收录|他引|h-index|"
            r"项目组主要成员|项目负责人简介|申请人简介|团队建设|在读研究生|"
            r"以往承担的主要项目|既往|历史项目|前期研究基础|"
            r"项目基本信息|拥有专利数量|注册时间|附件目录|前期实验研究工作|"
            r"研究基础|以上研究工作|奠定坚实的基础|顺利进行奠定|"
            r"申报项目与所属指南|与所属指南或申报通知方向的关联关系",
            s,
            re.I,
        )
    )


def _has_project_metric_anchor(snippet: str) -> bool:
    """需在本项目目标/计划/任务语境中才纳入正文指标提及。"""
    s = snippet or ""
    return bool(
        re.search(
            r"本项目|项目拟|拟解决|项目目标|研究目标|预期成果|关键节点|具体任务|"
            r"年度任务|实施方案|技术路线|通过本项目|项目实施|完成项目|计划|"
            r"拟解决的科学问题|可量化|考核指标|项目成果的呈现形式|预期研究成果",
            s,
            re.I,
        )
    )


def _has_project_goal_tense(snippet: str) -> bool:
    """仅保留项目目标/计划/验收等“要实现”的语气，排除既往成绩叙述。"""
    s = snippet or ""
    has_future = bool(
        re.search(
            r"计划|拟|将|预期|目标|任务|关键节点|验收|完成|实现|形成|构建|建立|开展|推进|达到|不少于|不低于|"
            r"本项目研究拟|通过本项目|以上|至少|年均",
            s,
            re.I,
        )
    )
    has_past = bool(
        re.search(
            r"已|曾|先后|既往|前期|已发表|已授权|已完成|以上研究工作|研究基础|"
            r"主持.*项目|参与.*项目|获奖|发表论文\d+篇",
            s,
            re.I,
        )
    )
    return has_future and not has_past


def _metric_focus_snippet(raw_text: str, start: int, end: int, pad: int = 130) -> str:
    """证据摘录以命中数字+单位为中心，避免大段无关文字导致「数值与摘录对不上」。"""
    s = raw_text or ""
    a = max(0, int(start) - pad)
    b = min(len(s), int(end) + pad)
    out = s[a:b].replace("\n", " ").strip()
    out = re.sub(r"\s+", " ", out)
    if len(out) > 400:
        out = out[:400] + "…"
    return out


def _metric_snippet_dedupe_key(snippet: str) -> str:
    """用于指标 mention 去重：压缩空白并去掉表格行标记。"""
    s = (snippet or "").strip()
    if not s:
        return ""
    s = re.sub(r"\[表格行\d+\]\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:220]


def _metric_narrative_dedupe_key(metric_name: str, unit: str, snippet: str) -> str:
    """正文提及去重键：尽量抽取同一句核心表达，避免同段多次命中重复计数。"""
    s = (snippet or "").strip()
    if not s:
        return ""
    s = re.sub(r"\[表格行\d+\]\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    clauses = [x.strip() for x in re.split(r"[。；;!?！？]", s) if x.strip()]
    if not clauses:
        clauses = [s]
    name = (metric_name or "").strip()
    u = (unit or "").strip()
    key_clause = ""
    for c in clauses:
        if name and name in c:
            key_clause = c
            break
    if not key_clause:
        if "研究生" in name:
            for c in clauses:
                if re.search(r"研究生|培养", c):
                    key_clause = c
                    break
        elif "论文" in name:
            for c in clauses:
                if re.search(r"论文|发表|刊发", c):
                    key_clause = c
                    break
        elif "专利" in name:
            for c in clauses:
                if re.search(r"专利|申请|授权|申报", c):
                    key_clause = c
                    break
    if not key_clause:
        key_clause = clauses[0]
    key_clause = re.sub(r"\s+", "", key_clause)
    if u:
        unit_pat = re.escape(u)
        m = re.search(
            rf"(\d+(?:\.\d+)?(?:[~～\-至到]\d+(?:\.\d+)?)?\s*(?:{unit_pat}|名|人|项|个|件|篇|次))",
            key_clause,
        )
        if m:
            key_clause = f"{name}|{m.group(1)}|{key_clause}"
    return key_clause[:220]


def _is_range_style_paper_mention(raw_text: str, start: int, end: int) -> bool:
    """「年均发表2至3篇」「高水平论文2-3篇」等区间表述，不按单端点 3 篇计入指标。"""
    s = raw_text or ""
    lo = max(0, start - 40)
    hi = min(len(s), end + 30)
    span = s[lo:hi]
    if re.search(r"\d+\s*[至到~-～]\s*\d+\s*篇", span):
        return True
    if re.search(r"年均.{0,20}发表", s[max(0, start - 50) : end + 10]):
        return True
    return False


def _extract_metric_range_bounds_from_snippet(
    metric_name: str, snippet: str, unit: str
) -> tuple[float, float] | None:
    """按指标名在摘录中解析区间（如研究生 3-4 名），避免误命中同句其它范围数字。"""
    s = (snippet or "").strip()
    if not s:
        return None
    name = (metric_name or "").strip()
    u = (unit or "").strip()
    key_pat = re.escape(name) if name else ""
    patterns: list[str] = []
    if name == "培养研究生":
        patterns.extend(
            [
                r"培养(?:硕士|博士)?研究生[^\n。；;：:]{0,24}?(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)\s*(?:名|人)",
                r"研究生培养[^\n。；;：:]{0,24}?(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)\s*(?:名|人)",
            ]
        )
    elif name == "科技论文":
        patterns.extend(
            [
                r"(?:发表|刊发)[^\n。；;：:]{0,24}?论文[^\n。；;：:]{0,12}?(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)\s*篇",
                r"论文[^\n。；;：:]{0,12}?(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)\s*篇",
            ]
        )
    elif name == "发明专利":
        patterns.extend(
            [
                r"发明专利[^\n。；;：:]{0,12}?(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)\s*(?:件|项)",
            ]
        )
    if key_pat:
        patterns.append(
            rf"{key_pat}[^\n。；;：:]{{0,30}}?(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)"
        )
    unit_pat = re.escape(u) if u else r"篇|件|项|个|次|名|人"
    patterns.append(
        rf"(?P<a>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<b>\d+(?:\.\d+)?)\s*(?:{unit_pat})"
    )
    m = None
    for p in patterns:
        m = re.search(p, s)
        if m:
            break
    if not m:
        return None
    a = _parse_number(m.group("a"))
    b = _parse_number(m.group("b"))
    if a is None or b is None:
        return None
    lo = float(min(a, b))
    hi = float(max(a, b))
    return (lo, hi)


def _exec_duration_months_from_period(
    start_ym: Optional[int], end_ym: Optional[int], duration_month: Optional[int]
) -> Optional[int]:
    if duration_month is not None and int(duration_month) > 0:
        return int(duration_month)
    if start_ym is not None and end_ym is not None and int(end_ym) >= int(start_ym):
        return int(end_ym) - int(start_ym) + 1
    return None


def _apply_annualized_range_if_needed(
    metric_name: str,
    snippet: str,
    rng: tuple[float, float],
    exec_duration_months: Optional[int],
) -> tuple[tuple[float, float], Optional[str]]:
    """将“年均 x-y”口径换算为执行期总量区间，避免与实施期总值直接比较误判。"""
    if metric_name != "科技论文":
        return rng, None
    s = snippet or ""
    if not re.search(r"年均|每年", s):
        return rng, None
    if exec_duration_months is None or exec_duration_months <= 0:
        return rng, None
    years = max(1.0, float(exec_duration_months) / 12.0)
    lo, hi = rng
    adj = (float(lo) * years, float(hi) * years)
    note = (
        f"按执行期约{years:.1f}年将“年均{lo:g}-{hi:g}篇”折算为“{adj[0]:g}-{adj[1]:g}篇”后比对。"
    )
    return adj, note


def _ym_year(ym: int) -> int:
    return int(ym) // 12


def _extract_milestone_year_months(
    raw_text: str,
    *,
    start_ym: Optional[int] = None,
    end_ym: Optional[int] = None,
) -> tuple[list[int], list[int]]:
    yms: list[int] = []
    years: list[int] = []
    raw = raw_text or ""

    def _noise_at(pos: int, end_pos: int) -> bool:
        ctx = raw[max(0, pos - 200) : min(len(raw), end_pos + 120)]
        return bool(_MILESTONE_YEAR_CONTEXT_NOISE.search(ctx))

    for m in re.finditer(r"(?P<y>20\d{2})\s*[年./-]\s*(?P<m>\d{1,2})\s*月", raw):
        if _noise_at(m.start(), m.end()):
            continue
        y = int(m.group("y"))
        mm = int(m.group("m"))
        yms.append(_parse_year_month(y, mm))

    for m in re.finditer(r"(?P<y>20\d{2})[./\-](?P<m>\d{1,2})", raw):
        if _noise_at(m.start(), m.end()):
            continue
        y = int(m.group("y"))
        mm = int(m.group("m"))
        yms.append(_parse_year_month(y, mm))

    for m in re.finditer(r"(?P<y>20\d{2})\s*年", raw):
        if _noise_at(m.start(), m.end()):
            continue
        years.append(int(m.group("y")))

    years = sorted(set(years))
    yms = sorted(set(yms))

    if start_ym is not None and end_ym is not None:
        sy = _ym_year(int(start_ym))
        ey = _ym_year(int(end_ym))
        lo, hi = sy - 1, ey + 2
        years = [y for y in years if lo <= y <= hi]
        yms = [x for x in yms if lo <= _ym_year(x) <= hi]

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

    scoped = _project_relevant_text(raw_text)
    table_summary = _extract_budget_table_summary(scoped)
    unit_total = _extract_budget_total_from_table_rows(scoped)

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

    items = _extract_budget_items(scoped)
    items_sum = float(sum(items.values()))

    fiscal_tier = _budget_fiscal_tier_from_table_summary(table_summary)
    source_norm = _budget_source_components_from_table_summary(table_summary)
    # 文本兜底：不少模板不会完整落成「预算科目名称:...;金额:...」结构，补抓关键字段。
    if fiscal_tier.get("provincial_fiscal_wan") is None:
        fiscal_tier["provincial_fiscal_wan"] = _extract_budget_named_amount_wan(
            scoped, ["一、省级财政资金", "省级财政资金", "省级财政"]
        )
    if fiscal_tier.get("direct_block_wan") is None:
        fiscal_tier["direct_block_wan"] = _extract_budget_named_amount_wan(
            scoped, ["（一）直接费用", "直接费用"]
        )
    if fiscal_tier.get("indirect_block_wan") is None:
        fiscal_tier["indirect_block_wan"] = _extract_budget_named_amount_wan(
            scoped, ["（二）间接费用", "间接费用"]
        )
    prov_fb = fiscal_tier.get("provincial_fiscal_wan")
    dr_fb = fiscal_tier.get("direct_block_wan")
    ind_fb = fiscal_tier.get("indirect_block_wan")
    if (
        fiscal_tier.get("direct_plus_indirect_wan") is None
        and dr_fb is not None
        and ind_fb is not None
    ):
        fiscal_tier["direct_plus_indirect_wan"] = float(dr_fb) + float(ind_fb)
    if (
        fiscal_tier.get("provincial_vs_components_delta_wan") is None
        and prov_fb is not None
        and fiscal_tier.get("direct_plus_indirect_wan") is not None
    ):
        fiscal_tier["provincial_vs_components_delta_wan"] = (
            float(fiscal_tier["direct_plus_indirect_wan"]) - float(prov_fb)
        )

    if source_norm.get("source_provincial_wan") is None:
        source_norm["source_provincial_wan"] = _extract_budget_named_amount_wan(
            scoped, ["省级财政资金", "省级财政"]
        )
    if source_norm.get("source_self_raised_wan") is None:
        source_norm["source_self_raised_wan"] = _extract_budget_named_amount_wan(scoped, ["自筹资金", "自筹"])
    if source_norm.get("source_matching_wan") is None:
        source_norm["source_matching_wan"] = _extract_budget_named_amount_wan(scoped, ["配套资金", "配套"])
    if source_norm.get("source_grand_total_wan") is None:
        source_norm["source_grand_total_wan"] = _extract_budget_named_amount_wan(scoped, ["合计", "总计"])
    sp = source_norm.get("source_provincial_wan")
    ss = source_norm.get("source_self_raised_wan")
    sm = source_norm.get("source_matching_wan")
    if source_norm.get("source_components_sum_wan") is None and None not in (sp, ss, sm):
        source_norm["source_components_sum_wan"] = float(sp) + float(ss) + float(sm)
    if (
        source_norm.get("source_vs_grand_delta_wan") is None
        and source_norm.get("source_components_sum_wan") is not None
        and source_norm.get("source_grand_total_wan") is not None
    ):
        source_norm["source_vs_grand_delta_wan"] = (
            float(source_norm["source_components_sum_wan"]) - float(source_norm["source_grand_total_wan"])
        )

    total = None
    compare_sum: Optional[float] = None
    compare_label = ""
    # 优先按“预算总额/合计”口径核对，再选最可靠的分项加总口径。
    if grand_total is not None:
        total = float(grand_total)
    elif source_norm.get("source_grand_total_wan") is not None:
        total = float(source_norm.get("source_grand_total_wan"))
    elif unit_total is not None:
        total = float(unit_total)
    else:
        total = _extract_budget_total(scoped)

    if source_norm.get("source_components_sum_wan") is not None:
        compare_sum = float(source_norm.get("source_components_sum_wan"))
        compare_label = "来源分项"
    elif source_total is not None:
        compare_sum = float(source_total)
        compare_label = "来源分项"
    elif (
        direct_total is not None
        and items
        and total is not None
        and abs(float(total) - float(direct_total)) <= max(float(amount_tolerance_wan), 0.5)
    ):
        compare_sum = float(items_sum)
        compare_label = "直接费用分项"
    elif direct_total is not None and items and total is None:
        total = float(direct_total)
        compare_sum = float(items_sum)
        compare_label = "直接费用分项"

    total_patterns: list[str] = []
    detail_patterns: list[str] = []
    if compare_label == "直接费用分项":
        total_patterns = [
            r"预算科目名称:.*直接费用.*金额:\s*\d",
            r"预算科目名称:.*合\s*计.*金额:\s*\d",
            r"预算科目名称:.*（一）直接费用.*预算科目名称:\s*\d",
            r"预算科目名称:.*合\s*计.*预算科目名称:\s*\d",
        ]
        detail_patterns = [
            r"预算科目名称:.*设备费.*金额:\s*\d",
            r"预算科目名称:.*业务费.*金额:\s*\d",
            r"预算科目名称:.*劳务费.*金额:\s*\d",
            r"预算科目名称:.*设备费.*预算科目名称:\s*\d",
            r"预算科目名称:.*业务费.*预算科目名称:\s*\d",
            r"预算科目名称:.*劳务费.*预算科目名称:\s*\d",
        ]
    elif compare_label == "来源分项":
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
        total_patterns = [
            r"资金申请总额",
            r"资金下达总额",
            r"预算总额",
            r"总预算",
            r"预算科目名称:.*合\s*计.*金额:\s*\d",
            r"预算科目名称:.*合\s*计.*预算科目名称:\s*\d",
            r"预算科目名称:.*省级财政.*预算科目名称:\s*\d",
        ]
        detail_patterns = [
            r"\[表格行\d+\].*预算科目名称:.*金额:\s*\d",
            r"\[表格行\d+\].*预算科目名称:.*预算科目名称:\s*\d",
        ]

    pt_ev, ev_sliced = _evidence_page_texts_for_project_body(page_texts, raw_text)
    total_page, total_snippet = parser.pick_evidence_snippet(
        page_texts=pt_ev,
        patterns=total_patterns,
    )
    detail_page, detail_snippet = parser.pick_evidence_snippet(
        page_texts=pt_ev,
        patterns=detail_patterns,
    )
    if ev_sliced:
        if total_snippet:
            total_page = _remap_evidence_page(page_texts, total_snippet)
        if detail_snippet:
            detail_page = _remap_evidence_page(page_texts, detail_snippet)
    total_snippet = total_snippet or ""
    detail_snippet = detail_snippet or ""

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

    # 明细展示口径：必须与 compare_label 对齐，避免“核对用来源分项，但展示用科目拆分”导致用户误判。
    display_items: Dict[str, float] = dict(items or {})
    if compare_label == "来源分项":
        disp: Dict[str, float] = {}
        if sp is not None:
            disp["省级财政资金"] = float(sp)
        if ss is not None:
            disp["自筹资金"] = float(ss)
        if sm is not None:
            disp["配套资金"] = float(sm)
        if disp:
            display_items = disp

    items_normalized: Dict[str, Any] = {
        "items_wan": display_items,
        "sum_wan": float(compare_sum) if compare_sum is not None else float(items_sum),
        "sum_label": compare_label or "预算分项",
        # 额外保留科目拆分（设备/业务/劳务…），供前端需要时展示为“节选/参考”，但不参与口径核对。
        "subject_items_wan": dict(items or {}),
        "subject_sum_wan": float(items_sum),
        **fiscal_tier,
        **source_norm,
    }

    entities.append(
        ExtractedEntity(
            entity_id=ent_items_id,
            entity_type="budget_items",
            name="预算明细",
            value="",
            normalized=items_normalized,
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

    # 预算维度仅保留「总额 vs 分项加总」单一核验口径。
    if total is None or compare_sum is None or float(compare_sum) == 0:
        return conflicts, entities

    delta = float(compare_sum) - float(total)
    if abs(delta) > float(amount_tolerance_wan):
        conflicts.append(
            ConflictItem(
                conflict_id=f"C_budget_sum_{doc_id}",
                severity=ConflictSeverity.RED,
                category=ConflictCategory.BUDGET_SUM,
                title="预算总额与明细求和不一致",
                description=f"预算总额为 {float(total):.2f} 万元，但{compare_label or '预算分项'}加总为 {float(compare_sum):.2f} 万元，差额 {delta:.2f} 万元。",
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
    _ = parser  # 与预算等检测接口对齐；时间证据使用 _pick_time_evidence_snippet

    scoped = _project_relevant_text(raw_text)
    start_ym, end_ym, duration_months = _extract_exec_period(scoped)
    milestone_yms, milestone_years = _extract_milestone_year_months(
        scoped, start_ym=start_ym, end_ym=end_ym
    )

    latest_ym = max(milestone_yms) if milestone_yms else None
    exec_patterns = _build_exec_period_patterns(start_ym, end_ym, duration_months)
    prog_patterns = _build_progress_patterns(latest_ym, milestone_years)
    pt_ev, ev_sliced = _evidence_page_texts_for_project_body(page_texts, raw_text)
    exec_page, exec_snippet = _pick_time_evidence_snippet(
        page_texts=pt_ev,
        patterns=exec_patterns,
        skip_grant_cv_noise=False,
    )
    prog_page, prog_snippet = _pick_time_evidence_snippet(
        page_texts=pt_ev,
        patterns=prog_patterns,
        skip_grant_cv_noise=True,
    )
    if ev_sliced:
        if exec_snippet:
            exec_page = _remap_evidence_page(page_texts, exec_snippet)
        if prog_snippet:
            prog_page = _remap_evidence_page(page_texts, prog_snippet)
    exec_snippet = exec_snippet or ""
    prog_snippet = prog_snippet or ""
    if exec_patterns and (not exec_snippet or not re.search(r"20\d{2}", exec_snippet)):
        merged = scoped or _merged_page_text(page_texts)
        if merged.strip():
            ep2, es2 = _pick_time_evidence_snippet(
                page_texts={0: merged},
                patterns=exec_patterns,
                skip_grant_cv_noise=False,
            )
            if es2:
                exec_snippet = es2
                exec_page = _remap_evidence_page(page_texts, (es2[:100] if len(es2) > 100 else es2))
    if prog_patterns and (not prog_snippet or not re.search(r"20\d{2}", prog_snippet)):
        merged = scoped or _merged_page_text(page_texts)
        if merged.strip():
            pp2, ps2 = _pick_time_evidence_snippet(
                page_texts={0: merged},
                patterns=prog_patterns,
                skip_grant_cv_noise=True,
            )
            if ps2:
                prog_snippet = ps2
                prog_page = _remap_evidence_page(page_texts, (ps2[:100] if len(ps2) > 100 else ps2))

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
            sy, sm = _ym_to_year_month(start_ym)
            ey, em = _ym_to_year_month(end_ym)
            ly, lm = _ym_to_year_month(latest)
            start_s = f"{sy}年{sm}月"
            end_s = f"{ey}年{em}月"
            latest_s = f"{ly}年{lm}月"
            conflicts.append(
                ConflictItem(
                    conflict_id=f"C_time_span_{doc_id}",
                    severity=ConflictSeverity.RED,
                    category=ConflictCategory.TIME_SPAN,
                    title="执行期与进度跨度不一致",
                    description=(
                        f"执行期为 {start_s} 至 {end_s}，但进度安排最晚节点为 {latest_s}，"
                        f"超出执行期约 {int(latest - end_ym)} 个月（容忍 {int(date_tolerance_months)} 个月）。"
                        "建议核查详细任务进度安排是否跨期。"
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


# --- 绩效/指标：河北等模板「项目绩效评价考核目标及指标」表格（双列 实施期目标）与正文多处复述 ---

# R-METRIC-01 仅对以下口径做多出处数值核对，避免「劳务费人数」等误入指标实体。
# 注意：「申请发明专利」与「授权发明专利」是两类不同口径，不能归并为同一“发明专利”指标；
# 同时仍保留“发明专利”兜底（部分模板只写“发明专利”不区分申请/授权）。
_METRIC_CONFLICT_KEYS = frozenset(
    {"科技论文", "发明专利", "申请发明专利", "授权发明专利", "培养研究生"}
)

_PERF_METRIC_ROW_RE = re.compile(
    r"绩效\s*指标\s*;\s*实施期目标:(?P<mname>[^;|]+?)\s*;\s*实施期目标:(?P<mval>\d+(?:\.\d+)?)"
)
# 广东等模板：「实施期目标/长叙述:申请发明专利（件） ; 实施期目标/…:3」首段数值为实施期总目标
_PERF_METRIC_ROW_RE_SLASH = re.compile(
    r"实施期目标/.+?:(?P<mname>[^;|]+?)"
    r"\s*;\s*"
    r"实施期目标/.+?:(?P<mval>\d+(?:\.\d+)?)",
)


def _is_budget_or_labor_metric_noise(s: str) -> bool:
    """劳务费/人次/乘法核算等与「培养研究生」绩效指标无关的片段，不参与指标归一。"""
    if not s:
        return False
    return bool(
        re.search(
            r"(?:研究生|博士)劳务费|劳务费[:：].{0,40}(?:研究生|博士|硕士)|"
            r"每人次|人次[,，、]?每人|国际合作与交流费|"
            r"\d+\s*人\s*×\s*\d+\s*(?:个?\s*月|月)|×\s*\d+\s*个月\s*×",
            s,
            re.I,
        )
    )


def _is_team_composition_noise(prefix: str) -> bool:
    """研究团队职称/人数表与绩效「培养研究生」易混，跳过。"""
    p = prefix or ""
    return bool(
        re.search(
            r"总人数|高级职称|中级职称|初级职称|博士后[:：]|博士生[:：]|硕士生[:：]|"
            r"职称结构|学历结构|学位",
            p,
        )
    )


def _is_cv_or_aggregate_patent_context(snippet: str) -> bool:
    """团队简介、限字成果栏、历史专利统计等，不是本项目实施期「申请发明专利」绩效口径。"""
    s = snippet or ""
    return bool(
        re.search(
            r"首席设计师|第一发明人|实用新型专利|重点成果取得情况|限\s*\d+\s*字|"
            r"科技计划项目情况|曾荣获|先后主持|"
            r"项目组主要成员|主要研究人员|公司首席|荣获发明|"
            r"(?:省|市|部|国家).{0,8}科技进步.{0,6}奖|中铁建|轨交协|"
            r"正在公开的发明专利|授权发明专利|工作简历|访问学者|主编出版教材论著|"
            r"主持或主研|厅局级及横向课题|近五年主持的与申请项目相关的科技计划项目情况|"
            # 存量/履历：已有专利件数、已建成装置能力等，不是本课题实施期「申请」目标
            r"拥有\s*\d+\s*项\s*(?:发明\s*)?专利|"
            r"(?:本申报项目|本项目|课题组|申请人).{0,24}已经\s*完成|"
            r"已经\s*建成|已建成|吨\s*/\s*年|制备装置|产业化|"
            r"申报项目与所属指南|与所属指南或申报通知|关联关系\s*[（(]?限\s*\d+\s*字",
            s,
            re.I,
        )
    )


def _is_personnel_resume_or_history_context(snippet: str) -> bool:
    """人员履历/历史业绩段落，不应作为本项目实施期指标来源。"""
    s = snippet or ""
    return bool(
        re.search(
            r"工作简历|访问学者|主要学术业绩|主编出版教材|第一发明人|授权发明专利|正在公开的发明专利|"
            r"主持或主研|近五年主持的与申请项目相关的科技计划项目情况|项目组主要成员|主要骨干人员|"
            r"自\d{4}年\d{2}月至\d{4}年\d{2}月|自\d{4}年\d{2}月至今|在.+单位工作|曾荣获|先后主持|"
            r"发表论文\d+余?篇|其中国家一级学报\d+篇|(?:SCI|EI)收录\d+篇|中文核心期刊\d+余?篇|"
            r"(?:科技项目|课题)\d+项|厅局级及横向课题\d+余?项",
            s,
            re.I,
        )
    )


def _coerce_canonical_metric_name(prefix_or_context: str, fallback: str) -> str:
    """将正文/碎片归并为绩效口径；实用新型与发明专利分列；避免单独「专利」泛化到发明。"""
    s = prefix_or_context or ""
    # 并列口径（如“青年骨干及研究生”）不应被归并为单独“培养研究生”
    if re.search(r"(?:骨干|青年|人才|专业技术人员|技术骨干).{0,10}研究生|研究生.{0,10}(?:骨干|青年|人才)", s):
        return fallback
    if re.search(r"(?:及|与|和|、|/).{0,8}研究生|研究生.{0,8}(?:及|与|和|、|/)", s):
        return fallback
    if re.search(
        r"培养\s*(?:硕士|博士)?研究生|(?:硕士|博士)研究生\s*(?:\d+|[一二三四五六七八九十两])",
        s,
    ):
        return "培养研究生"
    # 实用新型/外观设计与「发明专利」分列，不归入同一比对键
    if re.search(r"实用新型|外观设计", s):
        return fallback
    # 发明专利：区分“申请”与“授权”两类口径
    if re.search(r"授权[^\n。;]{0,24}发明(?:专利)?", s):
        return "授权发明专利"
    if re.search(r"(?:申请|申报|撰写申报)[^\n。;]{0,24}发明(?:专利)?", s):
        return "申请发明专利"
    if re.search(r"发明专利|发明\s*专利", s):
        return "发明专利"
    if re.search(r"论文|篇", s) and not re.search(r"(?:发明|实用)专利", s):
        return "科技论文"
    return fallback


def _metric_key_and_unit_from_perf_label(label: str) -> Tuple[str, str]:
    raw = (label or "").strip()
    lb = re.sub(r"\s+", "", raw)
    if not lb:
        return "", ""
    # 绩效表中常见分组/表头词，不是可比对的具体指标项；若参与比对会出现
    # 「效益指标 2 vs 400」这类跨行数字被误并的假冲突。
    if re.fullmatch(
        r"(?:一级指标|二级指标|三级指标|绩效指标|数量指标|质量指标|效益指标|经济效益|社会效益|满意度指标|总体目标|实施期目标|年度目标)",
        lb,
    ):
        return "", ""
    if "研究生" in lb:
        # 绩效表常见“培养青年骨干及研究生（人）/培养骨干、研究生（人）”等并列口径；
        # 这类不应强行归并为单独“培养研究生”，否则会把“青年骨干”人数混入研究生指标。
        if re.search(r"(?:骨干|青年|人才|专业技术人员|技术骨干).{0,10}研究生|研究生.{0,10}(?:骨干|青年|人才)", lb):
            pass
        elif re.search(r"(?:及|与|和|、|/).{0,8}研究生|研究生.{0,8}(?:及|与|和|、|/)", lb):
            pass
        else:
            return "培养研究生", "人"
    # 发明专利：绩效表里常见区分“申请/授权”，不能归并
    if re.search(r"授权发明专利", lb):
        return "授权发明专利", "件"
    if re.search(r"(?:申请|申报|撰写申报)发明专利", lb):
        return "申请发明专利", "件"
    if "发明专利" in lb or re.search(r"发明\s*专利", lb):
        return "发明专利", "件"
    if "论文" in lb:
        return "科技论文", "篇"
    # 对非三类核心指标也保留：用于「绩效指标表内部」一致性核验与完整展示。
    m = re.search(r"^(?P<name>.+?)[（(](?P<unit>[^）)]+)[）)]$", raw)
    if m:
        name = re.sub(r"^(?:实施期目标[:：/]?)", "", (m.group("name") or "").strip())
        unit = (m.group("unit") or "").strip()
        if unit in {"名"}:
            unit = "人"
        if not unit:
            unit = "项"
        return (name[:36] or "指标项"), unit
    name = re.sub(r"^(?:实施期目标[:：/]?)", "", raw).strip()
    return (name[:36] or "指标项"), "项"


def _looks_like_metric_label_token(s: str) -> bool:
    x = (s or "").strip()
    if not x:
        return False
    if re.fullmatch(
        r"(?:一级指标|二级指标|三级指标|绩效指标|数量指标|质量指标|效益指标|经济效益|社会效益|满意度指标|总体目标|实施期目标|年度目标)",
        re.sub(r"\s+", "", x),
    ):
        return False
    return bool(
        re.search(
            r"论文|专利|研究生|技术咨询|技术服务|转化科技成果|培训.*人员|"
            r"满意度|示范区|新技术|成果数量|服务数量|种质资源|创新服务人员|技术创新服务人员",
            x,
        )
    )


def _extract_perf_metrics_from_dense_row(line: str) -> list[tuple[str, float, str, str]]:
    """解析 `实施期目标/...:指标A ; 实施期目标/...:值 ; 第一年度目标/...:值` 的密集行。"""
    out: list[tuple[str, float, str, str]] = []
    chunks = [c.strip() for c in re.split(r"[;；]", line or "") if c.strip()]
    vals: list[str] = []
    for c in chunks:
        # 取最后一个冒号后的值，兼容 `前缀:后缀:值`。
        if ":" in c:
            vals.append(c.rsplit(":", 1)[-1].strip())
        elif "：" in c:
            vals.append(c.rsplit("：", 1)[-1].strip())
        else:
            vals.append(c.strip())
    n = len(vals)

    def _strict_numeric_token(tok: str) -> Optional[float]:
        t = (tok or "").strip()
        if not t:
            return None
        # 仅接受“纯数值单元格”（可带 >=/≤/%），避免把“(2) 发表论文1-2篇”中的序号误当目标值。
        if not re.fullmatch(r"(?:>=|<=|≥|≤)?\s*\d+(?:\.\d+)?\s*(?:%|％)?", t):
            return None
        num_m = re.search(r"\d+(?:\.\d+)?", t)
        if not num_m:
            return None
        return float(num_m.group(0))

    for i, tok in enumerate(vals):
        if not _looks_like_metric_label_token(tok):
            continue
        key, unit = _metric_key_and_unit_from_perf_label(tok)
        if not key:
            continue
        # 在后续少量单元格中找最邻近数字，优先作为实施期目标。
        pick_val: Optional[float] = None
        for j in range(i + 1, min(n, i + 5)):
            num = _strict_numeric_token(vals[j])
            if num is None:
                continue
            pick_val = float(num)
            break
        if pick_val is None:
            continue
        out.append((key, pick_val, unit or "项", tok))
    return out


def _extract_planning_performance_table_metrics(raw_text: str) -> list[dict[str, Any]]:
    """解析 `[表格行…] … 绩效 指标 ; 实施期目标:指标名 ; 实施期目标:数值`（samples_2025_docx 任务书/申报书常见）。"""
    out: list[dict[str, Any]] = []
    row_re = re.compile(r"^\[表格行\d+\]\s*(?P<line>.+)$", re.MULTILINE)
    for m in row_re.finditer(raw_text or ""):
        line = (m.group("line") or "").strip()
        for mm in _PERF_METRIC_ROW_RE.finditer(line):
            mname = (mm.group("mname") or "").strip()
            num = _parse_number(mm.group("mval"))
            if num is None:
                continue
            key, unit = _metric_key_and_unit_from_perf_label(mname)
            if not key:
                continue
            row_tag_m = re.match(r"^(\[表格行\d+\])\s*", line)
            row_tag = f"{row_tag_m.group(1)} " if row_tag_m else ""
            sn = row_tag + _metric_focus_snippet(line, mm.start(), mm.end(), pad=100)
            out.append(
                {
                    "key": key,
                    "value": float(num),
                    "unit": unit,
                    "snippet": sn,
                    "source": "绩效指标表",
                }
            )
        if "绩效" in line and "指标" in line and "实施期目标/" in line:
            for mm in _PERF_METRIC_ROW_RE_SLASH.finditer(line):
                mname = (mm.group("mname") or "").strip()
                num = _parse_number(mm.group("mval"))
                if num is None:
                    continue
                key, unit = _metric_key_and_unit_from_perf_label(mname)
                if not key:
                    continue
                row_tag_m = re.match(r"^(\[表格行\d+\])\s*", line)
                row_tag = f"{row_tag_m.group(1)} " if row_tag_m else ""
                sn = row_tag + _metric_focus_snippet(line, mm.start(), mm.end(), pad=100)
                out.append(
                    {
                        "key": key,
                        "value": float(num),
                        "unit": unit,
                        "snippet": sn,
                        "source": "绩效指标表",
                    }
                )
        # fallback：密集拼接格式（某些任务书/申报书模板）
        if "绩效" in line and "指标" in line and "实施期目标/" in line:
            row_tag_m = re.match(r"^(\[表格行\d+\])\s*", line)
            row_tag = f"{row_tag_m.group(1)} " if row_tag_m else ""
            for key, num, unit, tok in _extract_perf_metrics_from_dense_row(line):
                pos = line.find(tok)
                if pos < 0:
                    pos = 0
                sn = row_tag + _metric_focus_snippet(line, pos, pos + len(tok), pad=120)
                out.append(
                    {
                        "key": key,
                        "value": float(num),
                        "unit": unit,
                        "snippet": sn,
                        "source": "绩效指标表(密集行)",
                    }
                )
        # 另一类常见模板：同一行连续出现多个「实施期目标:...」单元，
        # 如「效益指标 ; 数量指标 ; 发表论文（篇） ; 2 ; 第一年度目标:1」。
        # 该格式在申报书中较多，若不做密集回退会漏掉除个别核心词外的大部分指标。
        if (
            ("实施期目标:" in line or "实施期目标：" in line)
            and ("绩效" in line and "指标" in line)
            and line.count("实施期目标:") + line.count("实施期目标：") >= 3
        ):
            row_tag_m = re.match(r"^(\[表格行\d+\])\s*", line)
            row_tag = f"{row_tag_m.group(1)} " if row_tag_m else ""
            for key, num, unit, tok in _extract_perf_metrics_from_dense_row(line):
                pos = line.find(tok)
                if pos < 0:
                    pos = 0
                sn = row_tag + _metric_focus_snippet(line, pos, pos + len(tok), pad=120)
                out.append(
                    {
                        "key": key,
                        "value": float(num),
                        "unit": unit,
                        "snippet": sn,
                        "source": "绩效指标表(密集行)",
                    }
                )
    return out


_PERF_PLAIN_CTX = re.compile(
    r"项目绩效评价考核目标及指标|绩效\s*指标|指标名称\s*指标值|总体\s*目标\s*实施期目标",
    re.I,
)
_PERF_PLAIN_ROW = re.compile(
    r"(?P<mname>[^;\n]{2,40}?[（(][^）)]{1,6}[）)])\s+"
    r"(?P<m0>\d+)(?:\s+(?P<m1>\d+))?(?:\s+(?P<m2>\d+))?(?:\s+(?P<m3>\d+))?",
)


def _extract_perf_plain_numeric_block_metrics(raw_text: str) -> list[dict[str, Any]]:
    """解析无分号、空格分列的绩效块：如「培养研究生（人） 3 1 1 1」「发表科技论文（篇） 6 2 2 2」；取首列为实施期目标。"""
    out: list[dict[str, Any]] = []
    raw = raw_text or ""
    for m in _PERF_PLAIN_ROW.finditer(raw):
        pos = m.start()
        ctx = raw[max(0, pos - 400) : pos + 1]
        if not _PERF_PLAIN_CTX.search(ctx):
            continue
        mname = (m.group("mname") or "").strip()
        m0 = _parse_number(m.group("m0"))
        if m0 is None:
            continue
        key, unit = _metric_key_and_unit_from_perf_label(mname)
        if not key:
            continue
        sn = _metric_focus_snippet(raw, m.start(), m.end(), pad=110)
        out.append(
            {
                "key": key,
                "value": float(m0),
                "unit": unit,
                "snippet": sn,
                "source": "绩效指标表(plain)",
            }
        )
    return out


_PERF_SECTION_START_RE = re.compile(
    r"(?:^|\n)\s*(?:七[、.．]\s*)?(?:项目实施的)?绩效目标(?:及指标|表)?\s*(?:\n|$)|"
    r"项目实施的(?:预期)?绩效目标(?:表)?",
    re.I,
)
_PERF_SECTION_END_RE = re.compile(
    r"(?:^|\n)\s*(?:八|九|十)[、.．]\s*|项目预算表|项目验收的考核指标|承担单位、合作单位经费预算明细表",
    re.I,
)


def _extract_perf_target_sentence_metrics(raw_text: str) -> list[dict[str, Any]]:
    """解析「实施期目标: … 论文10篇；专利2件；服务30人次」这类非表格规范句式。"""
    out: list[dict[str, Any]] = []
    text = raw_text or ""
    if not text:
        return out
    windows: list[str] = []
    for m in _PERF_SECTION_START_RE.finditer(text):
        a = m.start()
        tail = text[a : min(len(text), a + 14000)]
        em = _PERF_SECTION_END_RE.search(tail[120:])
        if em:
            b = a + 120 + em.start()
            windows.append(text[a:b])
        else:
            windows.append(tail)
    if not windows:
        return out

    metric_re = re.compile(
        r"(?P<name>[^\d；;。:\n]{2,60}?)"
        r"(?P<val>\d+(?:\.\d+)?(?:\s*[~～至到\-]\s*\d+(?:\.\d+)?)?)\s*"
        r"(?P<unit>篇|件|项|个|次|人次|名|人|万元|万|%)"
    )
    for win in windows:
        for mm in metric_re.finditer(win):
            name_raw = (mm.group("name") or "").strip()
            if not name_raw:
                continue
            # 去掉常见前缀与连接词，保留指标核心词。
            name_raw = re.sub(
                r"^(?:实施期目标[:：/]?|第一年度目标[:：/]?|第二年度目标[:：/]?|第三年度目标[:：/]?|第四年度目标[:：/]?|中期目标[:：/]?|总体目标[:：/]?|完成|实现|达到|新增|转化|促进|提供|培训|申请|发表|建立)",
                "",
                name_raw,
            ).strip(" ：:；;，,。")
            if not name_raw:
                continue
            if re.search(r"(单位名称|证件号码|注册资本|单位拥有专利数量|联系人|手机号|地址)", name_raw):
                continue
            key, unit = _metric_key_and_unit_from_perf_label(name_raw)
            if not key:
                key = (name_raw[:36] or "指标项")
            raw_unit = (mm.group("unit") or "").strip()
            unit = unit or raw_unit
            if unit in {"名"}:
                unit = "人"
            if key in {"科技论文"}:
                unit = "篇"
            elif key in {"发明专利"}:
                unit = "件"
            elif key in {"培养研究生"}:
                unit = "人"
            near = win[max(0, mm.start() - 260) : min(len(win), mm.end() + 180)]
            if not re.search(r"实施期目标|绩效|指标|预期技术指标|预期经济社会效益|项目实施", near):
                continue
            if _is_metric_background_noise(near):
                continue
            if _is_personnel_resume_or_history_context(near):
                continue
            if key == "发明专利" and _is_cv_or_aggregate_patent_context(near):
                continue
            if key == "科技论文" and _is_cv_or_aggregate_paper_context(near):
                continue
            if _is_annual_performance_cell_context(win, mm.start(), mm.end()):
                continue
            snippet = _metric_focus_snippet(win, mm.start(), mm.end(), pad=120)
            val_token = (mm.group("val") or "").strip()
            num = _parse_number(val_token)
            if num is None:
                continue
            out.append(
                {
                    "key": key,
                    "value": float(num),
                    "unit": unit,
                    "snippet": snippet,
                    "source": "绩效目标正文",
                }
            )
    return out


_STRONG_METRIC_SOURCES = frozenset(
    {"绩效指标表", "绩效指标表(plain)", "绩效指标表(密集行)", "表格-培养研究生", "绩效目标正文"}
)


def _filter_metric_pairs_to_authoritative(
    grouped: dict[tuple[str, str], list[tuple[float, str, str]]],
) -> dict[tuple[str, str], list[tuple[float, str, str]]]:
    """若某指标已能从绩效表/表格行抽取，则仅用「结构化出处」参与比对与实体汇总，避免正文/关键词噪声。"""
    out: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    for key, pairs in grouped.items():
        strong = [p for p in pairs if p[2] in _STRONG_METRIC_SOURCES]
        out[key] = strong if len(strong) >= 1 else pairs
    return out


def _match_structured_metric_from_context(
    ctx: str,
    structured_key_units: dict[str, str],
) -> tuple[str, str]:
    """从上下文中回指绩效表里的指标名（支持非三类核心指标）。"""
    raw = ctx or ""
    if not raw or not structured_key_units:
        return "", ""
    raw_n = re.sub(r"[\s\u3000:：,，;；()（）\[\]【】<>《》\-_/\\]+", "", raw)
    # 长名称优先，避免「项目」先命中「国家科研项目」子串。
    keys = sorted(structured_key_units.keys(), key=lambda x: len(x), reverse=True)
    for k in keys:
        kn = re.sub(r"[\s\u3000:：,，;；()（）\[\]【】<>《》\-_/\\]+", "", str(k or ""))
        if not kn:
            continue
        if kn in raw_n:
            return k, (structured_key_units.get(k) or "")
    return "", ""


def _extract_narrative_cross_metric_mentions(raw_text: str) -> list[dict[str, Any]]:
    """正文/研究目标/预期成果中与绩效表可对照的量化表述（多出处互证）。"""
    out: list[dict[str, Any]] = []
    text = raw_text or ""

    def _is_technical_subtask_context(s: str) -> bool:
        """技术路线/子任务描述中的阶段性产出，不作为实施期总目标对比口径。"""
        x = s or ""
        return bool(
            re.search(
                r"优化制备|理化性质|缓释|体外|生物膜|共培养|通路|机制|"
                r"初步探究|深入研究|建立.{0,10}模型|动物模|在动物模|验证|"
                r"表征|评价.{0,10}效果|抑制效果|分子机制|ESP|icaADBC",
                x,
                re.I,
            )
        )

    def _push(key: str, unit: str, val: float, start: int, end: int, source: str) -> None:
        if key not in _METRIC_CONFLICT_KEYS:
            return
        if key == "科技论文" and _is_range_style_paper_mention(text, start, end):
            return
        sn = _metric_focus_snippet(text, start, end, pad=120)
        ext = text[max(0, start - 220) : min(len(text), end + 100)]
        if _is_metric_background_noise(ext) or _is_metric_background_noise(sn):
            return
        if _is_personnel_resume_or_history_context(ext) or _is_personnel_resume_or_history_context(sn):
            return
        if _is_stage_task_metric_noise(ext):
            return
        if _is_budget_or_labor_metric_noise(sn):
            return
        if key == "科技论文" and (val > 35 or _is_cv_or_aggregate_paper_context(ext)):
            return
        if "发明专利" in key and (
            _is_cv_or_aggregate_patent_context(sn) or _is_cv_or_aggregate_patent_context(ext)
        ):
            return
        if key == "培养研究生" and _is_grant_unrelated_trainee_context(ext):
            return
        if _is_annual_performance_cell_context(text, start, end):
            return
        # 技术路线/子任务语境：抽取但降级为“阶段目标”展示，不参与实施期一致性核验
        stage_label = ""
        if _is_technical_subtask_context(f"{ext} {sn}"):
            stage_label = "子任务产出"
        out.append(
            {
                "key": key,
                "value": float(val),
                "unit": unit,
                "snippet": sn,
                "source": f"{source}(阶段)" if stage_label else source,
                "stage_label": stage_label,
            }
        )

    for m in re.finditer(
        r"(?:发表|刊发)[^\n。;]{0,35}(\d+)\s*篇[^\n。;]{0,20}?(?:论文|研究性论文|学术论文|SCI)",
        text,
    ):
        span = text[max(0, m.start() - 30) : min(len(text), m.end() + 20)]
        if re.search(r"\d+\s*[至到~-～]\s*\d+\s*篇", span):
            continue
        _push("科技论文", "篇", float(m.group(1)), m.start(), m.end(), "正文-论文")
    # 「申报」勿匹配「申报项目/申报书」节标题，否则会误把后文「拥有9项发明专利」中的 9 抽成申报指标
    for m in re.finditer(
        r"(?:撰写申报|申请(?!\s*书)|申报(?!\s*(?:项目|书)))[^\n。;]{0,40}(\d+)\s*项[^\n。;]{0,24}?(?:发明专利|发明\s*专利)",
        text,
    ):
        span = text[max(0, m.start() - 48) : min(len(text), m.end() + 32)]
        if re.search(r"实用新型", span):
            continue
        _push("申请发明专利", "件", float(m.group(1)), m.start(), m.end(), "正文-专利")
    for m in re.finditer(
        r"授权[^\n。;]{0,40}(\d+)\s*(?:项|件)[^\n。;]{0,24}?(?:发明专利|发明\s*专利)",
        text,
    ):
        span = text[max(0, m.start() - 48) : min(len(text), m.end() + 32)]
        if re.search(r"实用新型", span):
            continue
        _push("授权发明专利", "件", float(m.group(1)), m.start(), m.end(), "正文-专利")
    for m in re.finditer(
        r"培养(?:硕士|博士)?研究生\s*(\d+)\s*(?:名|人|个)\b",
        text,
    ):
        _push("培养研究生", "人", float(m.group(1)), m.start(), m.end(), "正文-研究生")
    return out


def _extract_structured_metric_narrative_mentions(
    raw_text: str,
    structured_key_units: dict[str, str],
) -> list[dict[str, Any]]:
    """按绩效表已识别指标名，从正文补充抽取同名指标提及（用于交叉核验与展示）。"""
    out: list[dict[str, Any]] = []
    text = raw_text or ""
    if not text or not structured_key_units:
        return out

    def _norm_unit(unit_text: str) -> str:
        uu = (unit_text or "").strip()
        if uu in {"名", "人"}:
            return "人"
        return uu

    for key, unit in structured_key_units.items():
        k = str(key or "").strip()
        u = str(unit or "").strip() or "项"
        if not k:
            continue
        key_pat = re.escape(k)
        unit_pat = re.escape(u)
        # 常见正文句式：承担国家科研项目1项 / 培养专业技术人员5人 / 新产品3项
        pat = re.compile(
            rf"{key_pat}[^\n。；;：:]{0,42}?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{unit_pat}|名|人|项|个|件|篇|次)?"
        )
        for m in pat.finditer(text):
            num = _parse_number(m.group("num"))
            if num is None:
                continue
            mu = _norm_unit((m.group("unit") or u).strip())
            if u in {"人", "名"}:
                mu = "人"
            elif u:
                mu = u
            if "发明专利" in k:
                mu = "件"
            if "论文" in k:
                mu = "篇"
            if mu in {"名"}:
                mu = "人"

            # 过滤表格模板串与分年度子目标，避免把年度拆分值当实施期总值
            near = text[max(0, m.start() - 320) : min(len(text), m.end() + 160)]
            # OCR 噪声：如“发表SCI论文111篇”被拆成“1 1 1”后误抽为 1
            if "论文" in k:
                # 用更大的 near 窗口兜底（OCR 可能插入空格/换行/符号）
                big = re.search(r"(?:论文|SCI\\D{0,10}论文)\\D{0,24}(\\d{2,4})\\D{0,6}篇", near)
                if big:
                    try:
                        if int(big.group(1)) > 35 and float(num) <= 2.0:
                            continue
                    except Exception:
                        pass
            if re.search(r"绩效\s*指标|实施期目标|第一年度目标|第二年度目标|第三年度目标", near):
                continue
            if _is_annual_performance_cell_context(text, m.start(), m.end()):
                continue
            if _is_metric_background_noise(near):
                continue
            if _is_personnel_resume_or_history_context(near):
                continue
            stage_label = ""
            if _is_stage_task_metric_noise(near):
                stage_label = "阶段目标"
            if not _has_project_metric_anchor(near):
                continue
            if not _has_project_goal_tense(near):
                continue

            sn = _metric_focus_snippet(text, m.start(), m.end(), pad=120)
            # OCR 噪声兜底：snippet 内出现明显大数（如 111篇），但当前抽取值很小（1/2）
            if "论文" in k and float(num) <= 2.0:
                big2 = re.search(r"\D(\d{2,4})\D{0,6}篇", sn or "")
                if big2:
                    try:
                        if int(big2.group(1)) > 35:
                            continue
                    except Exception:
                        pass
            if _is_budget_or_labor_metric_noise(sn):
                continue
            if _is_metric_background_noise(sn):
                continue
            if _is_personnel_resume_or_history_context(sn):
                continue
            if _is_stage_task_metric_noise(sn):
                stage_label = stage_label or "阶段目标"
            if "发明专利" in k and (
                _is_cv_or_aggregate_patent_context(near) or _is_cv_or_aggregate_patent_context(sn)
            ):
                continue
            out.append(
                {
                    "key": k,
                    "value": float(num),
                    "unit": mu or u or "项",
                    "snippet": sn,
                    "source": "正文-指标提及(阶段)" if stage_label else "正文-指标提及",
                    "stage_label": stage_label,
                }
            )
    return out


def _extract_structured_metric_narrative_mentions_loose(
    raw_text: str,
    structured_key_units: dict[str, str],
) -> list[dict[str, Any]]:
    """宽松正文提及：补充区间/阶段句式（用于展示，不直接触发冲突）。"""
    out: list[dict[str, Any]] = []
    text = raw_text or ""
    if not text or not structured_key_units:
        return out

    def _norm_unit(unit_text: str) -> str:
        uu = (unit_text or "").strip()
        if uu in {"名", "人"}:
            return "人"
        return uu

    def _patterns_for_key(k: str, u: str) -> list[re.Pattern]:
        ps: list[str] = []
        if "研究生" in k:
            ps.extend(
                [
                    r"培养(?:硕士|博士|博硕士|博硕)?研究生[^\n。；;：:]{0,24}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>名|人)",
                    r"培养(?:硕士|博士|博硕士|博硕)?研究生[^\n。；;：:]{0,24}(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>名|人)",
                    r"培养(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>名|人)[^\n。；;：:]{0,12}(?:硕士|博士|博硕士|博硕)?研究生",
                    r"培养(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>名|人)[^\n。；;：:]{0,12}(?:硕士|博士|博硕士|博硕)?研究生",
                    r"(?:硕士|博士|博硕士|博硕)?研究生[^\n。；;：:]{0,12}培养[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>名|人)",
                ]
            )
        if "论文" in k:
            ps.extend(
                [
                    r"(?:发表|刊发|形成|完成)[^\n。；;：:]{0,28}论文[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>篇)",
                    r"(?:发表|刊发)[^\n。；;：:]{0,28}论文[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>篇)",
                    r"(?:发表|刊发|形成|完成)[^\n。；;：:]{0,20}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>篇)[^\n。；;：:]{0,16}(?:科技|学术|核心|SCI|EI)?论文",
                    r"(?:发表|刊发|形成|完成)[^\n。；;：:]{0,20}(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>篇)[^\n。；;：:]{0,16}(?:科技|学术|核心|SCI|EI)?论文",
                ]
            )
        if "发明专利" in k:
            ps.extend(
                [
                    r"(?:申请|申报|授权)[^\n。；;：:]{0,16}发明专利[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|件)",
                    r"(?:申请|申报|授权)[^\n。；;：:]{0,16}发明专利[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>项|件)",
                ]
            )
        if "实用新型专利" in k:
            ps.append(
                r"(?:申请|申报|授权)[^\n。；;：:]{0,16}实用新型专利[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|件)"
            )
        if "软件著作权" in k:
            ps.append(r"软件著作权[^\n。；;：:]{0,12}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|件)")
        if "标准" in k:
            ps.append(r"(?:制定|形成|发布)[^\n。；;：:]{0,18}(?:企业)?标准[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|个)")
        if "新产品" in k:
            ps.append(r"新产品[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|个)")
        if "专业技术人员" in k or "青年人才" in k:
            ps.append(r"培养[^\n。；;：:]{0,20}(?:专业技术人员|技术骨干|青年人才)[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>名|人)")
        if "外籍专家" in k:
            ps.append(r"引进[^\n。；;：:]{0,10}外籍专家[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>名|人)")
        if "学术奖励" in k:
            ps.append(r"(?:获得|荣获)[^\n。；;：:]{0,14}学术奖励[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|次)")
        if "国家科研项目" in k:
            ps.append(r"承担[^\n。；;：:]{0,16}国家[^\n。；;：:]{0,12}项目[^\n。；;：:]{0,10}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|个)")
        if not ps:
            key_pat = re.escape(k)
            unit_pat = re.escape(u)
            ps.extend(
                [
                    rf"{key_pat}[^\n。；;：:]{{0,36}}?(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>{unit_pat}|名|人|项|个|件|篇|次)?",
                    rf"{key_pat}[^\n。；;：:]{{0,36}}?(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>{unit_pat}|名|人|项|个|件|篇|次)?",
                ]
            )
        return [re.compile(p) for p in ps]

    for key, unit in structured_key_units.items():
        k = str(key or "").strip()
        u = str(unit or "").strip() or "项"
        if not k:
            continue
        for pat in _patterns_for_key(k, u):
            for m in pat.finditer(text):
                n1 = _parse_number(m.group("n1"))
                n2 = _parse_number(m.groupdict().get("n2", ""))
                if n1 is None:
                    continue
                mu = _norm_unit((m.groupdict().get("u", "") or u).strip())
                if u in {"人", "名"}:
                    mu = "人"
                elif u:
                    mu = u
                if "发明专利" in k:
                    mu = "件"
                if "论文" in k:
                    mu = "篇"
                val = float(max(n1, n2)) if n2 is not None else float(n1)
                if val <= 0:
                    continue
                # OCR/表格噪声：常见 “论文1 1 1篇” 这种分裂数字，实际不是 1 篇。
                # 若检测到拆分后的多位数字且过大（>35），直接跳过该命中，避免把首位“1”误当目标值。
                if "论文" in k:
                    around = text[max(0, m.start() - 12) : min(len(text), m.end() + 18)]
                    # 允许 OCR 把数字拆成 "1 1 1" / "1|1|1" / "1\n1\n1" 等
                    mm = re.search(r"论文\s*(?P<d>\d(?:\D+\d){1,8})\s*篇", around)
                    if mm:
                        joined = re.sub(r"\D+", "", mm.group("d") or "")
                        try:
                            if joined.isdigit() and int(joined) > 35:
                                continue
                        except Exception:
                            pass
                near = text[max(0, m.start() - 320) : min(len(text), m.end() + 160)]
                if re.search(r"绩效\s*指标|实施期目标|第一年度目标|第二年度目标|第三年度目标", near):
                    continue
                if _is_budget_or_labor_metric_noise(near):
                    continue
                if _is_metric_background_noise(near):
                    continue
                if _is_personnel_resume_or_history_context(near):
                    continue
                if _is_stage_task_metric_noise(near):
                    continue
                if not _has_project_metric_anchor(near):
                    continue
                if not _has_project_goal_tense(near):
                    continue
                sn = _metric_focus_snippet(text, m.start(), m.end(), pad=120)
                if _is_metric_background_noise(sn):
                    continue
                if _is_personnel_resume_or_history_context(sn):
                    continue
                if _is_stage_task_metric_noise(sn):
                    continue
                if "发明专利" in k and (
                    _is_cv_or_aggregate_patent_context(near) or _is_cv_or_aggregate_patent_context(sn)
                ):
                    continue
                hit_txt = m.group(0) or ""
                is_range_hit = (n2 is not None) or bool(
                    re.search(r"\d+\s*[~～\-至到]\s*\d+", hit_txt)
                )
                out.append(
                    {
                        "key": k,
                        "value": val,  # 仅用于展示/宽松对照
                        "unit": mu or u or "项",
                        "snippet": sn,
                        "source": "正文-指标提及(区间/宽松)" if is_range_hit else "正文-指标提及",
                    }
                )
    return out


def _extract_structured_metric_narrative_mentions_fallback(
    raw_text: str,
    structured_key_units: dict[str, str],
) -> list[dict[str, Any]]:
    """正文补充抽取：覆盖少见句式，召回后再由噪声规则过滤。"""
    out: list[dict[str, Any]] = []
    text = raw_text or ""
    if not text or not structured_key_units:
        return out

    def _norm_unit(unit_text: str) -> str:
        uu = (unit_text or "").strip()
        if uu in {"名", "人"}:
            return "人"
        return uu

    for key, unit in structured_key_units.items():
        k = str(key or "").strip()
        u = str(unit or "").strip() or "项"
        if not k:
            continue
        key_pat = re.escape(k)
        unit_pat = re.escape(u) if u else r"名|人|项|个|件|篇|次"
        pats = [
            re.compile(
                rf"{key_pat}[^\n。；;：:]{{0,48}}?(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>{unit_pat}|名|人|项|个|件|篇|次)?"
            ),
            re.compile(
                rf"{key_pat}[^\n。；;：:]{{0,42}}?(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>{unit_pat}|名|人|项|个|件|篇|次)?"
            ),
        ]
        if "研究生" in k:
            pats.extend(
                [
                    re.compile(
                        r"培养(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>名|人)[^\n。；;：:]{0,16}(?:硕士|博士|博硕士|博硕)?研究生"
                    ),
                    re.compile(
                        r"培养(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>名|人)[^\n。；;：:]{0,16}(?:硕士|博士|博硕士|博硕)?研究生"
                    ),
                ]
            )
        if "论文" in k:
            pats.extend(
                [
                    re.compile(
                        r"(?:发表|刊发|形成|完成)[^\n。；;：:]{0,24}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>篇)[^\n。；;：:]{0,20}(?:科技|学术|核心|SCI|EI)?论文"
                    ),
                    re.compile(
                        r"(?:发表|刊发|形成|完成)[^\n。；;：:]{0,24}(?P<n1>\d+(?:\.\d+)?)\s*[~～\-至到]\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<u>篇)[^\n。；;：:]{0,20}(?:科技|学术|核心|SCI|EI)?论文"
                    ),
                ]
            )
        if "发明专利" in k:
            pats.extend(
                [
                    re.compile(
                        r"(?:申请|申报|授权|撰写申报)[^\n。；;：:]{0,20}发明专利[^\n。；;：:]{0,16}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|件)"
                    ),
                    re.compile(
                        r"发明专利[^\n。；;：:]{0,16}(?P<n1>\d+(?:\.\d+)?)\s*(?P<u>项|件)(?:以上|不少于)?"
                    ),
                ]
            )

        for pat in pats:
            for m in pat.finditer(text):
                n1 = _parse_number(m.groupdict().get("n1", ""))
                n2 = _parse_number(m.groupdict().get("n2", ""))
                if n1 is None:
                    continue
                val = float(max(n1, n2)) if n2 is not None else float(n1)
                if val <= 0:
                    continue
                mu = _norm_unit((m.groupdict().get("u", "") or u).strip())
                if u in {"人", "名"}:
                    mu = "人"
                elif u:
                    mu = u
                if "发明专利" in k:
                    mu = "件"
                if "论文" in k:
                    mu = "篇"
                if "研究生" in k:
                    mu = "人"

                near = text[max(0, m.start() - 320) : min(len(text), m.end() + 180)]
                if re.search(r"绩效\s*指标|实施期目标|第一年度目标|第二年度目标|第三年度目标", near):
                    continue
                if _is_annual_performance_cell_context(text, m.start(), m.end()):
                    continue
                if _is_budget_or_labor_metric_noise(near):
                    continue
                if _is_metric_background_noise(near):
                    continue
                if _is_personnel_resume_or_history_context(near):
                    continue
                if _is_stage_task_metric_noise(near):
                    continue
                if not _has_project_metric_anchor(near):
                    continue
                if not _has_project_goal_tense(near):
                    continue
                sn = _metric_focus_snippet(text, m.start(), m.end(), pad=140)
                if _is_metric_background_noise(sn):
                    continue
                if _is_personnel_resume_or_history_context(sn):
                    continue
                if _is_stage_task_metric_noise(sn):
                    continue
                if "发明专利" in k and (
                    _is_cv_or_aggregate_patent_context(near) or _is_cv_or_aggregate_patent_context(sn)
                ):
                    continue
                hit_txt = m.group(0) or ""
                is_range_hit = (n2 is not None) or bool(
                    re.search(r"\d+\s*[~～\-至到]\s*\d+", hit_txt)
                )
                out.append(
                    {
                        "key": k,
                        "value": val,
                        "unit": mu or u or "项",
                        "snippet": sn,
                        "source": "正文-指标提及(区间/宽松)" if is_range_hit else "正文-指标提及",
                    }
                )
    return out


def _find_page_for_metric_evidence(
    page_texts: Optional[Dict[int, str]], snippet: str
) -> Optional[int]:
    """表格行过长时，除前缀匹配外，用章节锚点回退定位页码。"""
    if not page_texts:
        return None
    s = (snippet or "").strip()
    if not s:
        return None
    p = _find_page_for_snippet(page_texts, s)
    if p is not None:
        return p
    for n in (100, 80, 50, 40):
        key = s[:n] if len(s) > n else s
        if len(key) < 12:
            continue
        for page, txt in sorted(page_texts.items(), key=lambda x: x[0]):
            if key in (txt or ""):
                return page
    for needle in ("项目绩效评价考核目标及指标", "绩效 指标", "实施期目标:", "项目绩效"):
        if needle in s:
            for page, txt in sorted(page_texts.items(), key=lambda x: x[0]):
                if needle in (txt or ""):
                    return page
            break
    return None


def _pick_metric_conflict_evidence(
    pairs: list[tuple[float, str, str]],
    page_texts: Optional[Dict[int, str]],
    *,
    max_spans: int = 4,
) -> list[DocSpan]:
    """按不同数值各选一条摘录，并标注出处标签，避免三条证据实为同一数值的重复段落。"""
    if not pairs:
        return []
    by_val: dict[float, list[tuple[float, str, str]]] = {}
    for t in pairs:
        by_val.setdefault(float(t[0]), []).append(t)
    uvals = sorted(by_val.keys())
    want_vals: list[float] = []
    if len(uvals) <= 2:
        want_vals = uvals[:]
    else:
        want_vals = [uvals[0], uvals[-1]]
        mid = uvals[len(uvals) // 2]
        if mid not in want_vals:
            want_vals.append(mid)
    out: list[DocSpan] = []
    for val in want_vals:
        cands = by_val.get(val) or []
        cands.sort(
            key=lambda c: (
                0
                if (
                    "绩效" in (c[2] or "")
                    or "表格" in (c[2] or "")
                    or (c[2] or "").startswith("绩效指标表")
                )
                else 1,
                len((c[1] or "").strip()),
            )
        )
        _, snip, src = cands[0]
        sec = f"指标·{src}"
        excerpt = (snip or "").strip()
        pg = _find_page_for_metric_evidence(page_texts, excerpt) if page_texts else None
        out.append(
            DocSpan(
                page=(pg + 1) if pg is not None else None,
                section_title=sec,
                snippet=f"摘录对应数值≈{val:g}（{src}）：{excerpt}",
            )
        )
        if len(out) >= max_spans:
            break
    return out


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

    scoped = _project_relevant_text(raw_text)
    if not scoped:
        scoped = (raw_text or "").strip()
    exec_start_ym, exec_end_ym, exec_dur_month = _extract_exec_period(scoped)
    exec_duration_months = _exec_duration_months_from_period(exec_start_ym, exec_end_ym, exec_dur_month)

    def normalize_name(name: str) -> str:
        n = re.sub(r"[\s\u3000:：,，;；()（）\[\]【】<>《》\-_/\\]+", "", (name or "")).strip()
        if not n:
            return ""
        n = re.sub(r"[xX×]", "", n)
        if re.search(r"培养\s*(?:硕士|博士)?研究生|(?:硕士|博士)研究生", n):
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
                r"培养|研究生|博士|硕士|论文|专利|软著|标准|获奖|推广|示范|服务对象满意度|满意度|人才|"
                r"绩效|指标|考核|目标值|预期|中期|验收|技术|成果",
                prefix or "",
            )
        )

    def has_metric_anchor_context(text: str) -> bool:
        return bool(
            re.search(
                r"绩效|指标|考核|实施期目标|目标值|预期目标|验收指标|年度目标|项目目标|里程碑",
                text or "",
            )
        )

    mentions: list[Tuple[str, float, str, str, str]] = []
    # 分年度/阶段目标：允许抽取用于展示，但不参与“实施期目标”一致性对比
    stage_mentions: list[Tuple[str, float, str, str, str, str]] = []  # (name,val,unit,snippet,source,stage_label)
    perf_rows = _extract_planning_performance_table_metrics(scoped)
    perf_plain_rows = _extract_perf_plain_numeric_block_metrics(scoped)
    perf_sentence_rows = _extract_perf_target_sentence_metrics(scoped)
    structured_key_units: dict[str, str] = {}
    # 结构化“基准键”仅来自表格/plain 块，避免把正文宽松句式噪声反向放大到全局键空间。
    for r in [*perf_rows, *perf_plain_rows]:
        k = str(r.get("key") or "").strip()
        if not k:
            continue
        u = str(r.get("unit") or "").strip()
        if k not in structured_key_units:
            structured_key_units[k] = u
    structured_metric_keys: set[str] = set(structured_key_units.keys())

    def _stage_label_from_context(ctx: str) -> str:
        s = ctx or ""
        for k in ("第一年度", "第二年度", "第三年度", "第四年度", "年度目标", "中期目标"):
            if k in s:
                return k
        for k in ("第一阶段", "第二阶段", "第三阶段", "阶段目标", "阶段性目标"):
            if k in s:
                return k
        m = re.search(r"\b20\d{2}[./-]\d{1,2}\s*[-—~～]\s*20\d{2}[./-]\d{1,2}\b", s)
        if m:
            return m.group(0)
        return "阶段目标"

    with_constraint_re = re.compile(
        r"(?P<prefix>[^。\n]{0,50}?)(?P<constraint>不少于|不低于|达到|≥|<=|≤|>=|=)\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>篇|件|项|个|次|名|人|%|％)"
    )
    for m in with_constraint_re.finditer(scoped):
        pfx = m.group("prefix") or ""
        ctx = f"{pfx}{m.group(0) or ''}"
        name = normalize_name(pfx)
        name = _coerce_canonical_metric_name(ctx, name)
        if not name:
            continue
        if name not in _METRIC_CONFLICT_KEYS and name not in structured_metric_keys:
            mk, mu = _match_structured_metric_from_context(ctx, structured_key_units)
            if not mk:
                continue
            name = mk
            if mu:
                unit = normalize_unit(mu)
            else:
                unit = normalize_unit((m.group("unit") or "").strip())
        else:
            unit = normalize_unit((m.group("unit") or "").strip())
        if not name:
            continue
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        if name == "科技论文":
            unit = "篇"
        elif name == "发明专利":
            unit = "件"
        elif name == "培养研究生":
            unit = "人"
        snippet = _metric_focus_snippet(scoped, m.start(), m.end(), pad=120)
        wide = scoped[max(0, m.start() - 220) : min(len(scoped), m.end() + 100)]
        if structured_metric_keys and name in _METRIC_CONFLICT_KEYS:
            # 三类核心指标的正文对照由 _extract_narrative_cross_metric_mentions 统一处理；
            # 这里的弱句式会混入“既往项目/背景目标”数字，故跳过。
            continue
        if structured_metric_keys and name not in _METRIC_CONFLICT_KEYS:
            if not has_metric_anchor_context(f"{ctx} {wide}"):
                continue
        if _is_budget_or_labor_metric_noise(snippet):
            continue
        if _is_annual_performance_cell_context(scoped, m.start(), m.end()) or _is_stage_task_metric_noise(wide) or _is_stage_task_metric_noise(snippet):
            stage_mentions.append(
                (name, float(val), unit, snippet, "阶段目标-约束句式", _stage_label_from_context(f"{ctx} {wide}"))
            )
            continue
        if name == "科技论文" and (
            val > 35
            or _is_cv_or_aggregate_paper_context(wide)
            or _is_range_style_paper_mention(scoped, m.start(), m.end())
        ):
            continue
        if name and "发明专利" in name and (
            _is_cv_or_aggregate_patent_context(snippet) or _is_cv_or_aggregate_patent_context(wide)
        ):
            continue
        if name == "培养研究生" and _is_grant_unrelated_trainee_context(wide):
            continue
        mentions.append((name, float(val), unit, snippet, "约束句式"))

    without_constraint_re = re.compile(
        r"(?P<prefix>[^。\n]{0,50}?)(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>名|人|篇|件|项|个|次)"
    )
    for m in without_constraint_re.finditer(scoped):
        prefix_raw = (m.group("prefix") or "").strip()
        if not has_metric_keywords(prefix_raw):
            continue
        win = scoped[max(0, m.start() - 32) : min(len(scoped), m.end() + 16)]
        if re.search(r"\d\s*[-～至~]\s*\d", win):
            continue
        if _is_annual_performance_cell_context(scoped, m.start(), m.end()):
            continue
        ctx = f"{prefix_raw}{m.group(0) or ''}"
        name = normalize_name(prefix_raw)
        name = _coerce_canonical_metric_name(ctx, name)
        if not name:
            continue
        if name not in _METRIC_CONFLICT_KEYS and name not in structured_metric_keys:
            mk, mu = _match_structured_metric_from_context(ctx, structured_key_units)
            if not mk:
                continue
            name = mk
            unit = normalize_unit(mu or (m.group("unit") or "").strip())
        else:
            unit = normalize_unit((m.group("unit") or "").strip())
        if not name:
            continue
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        if name == "科技论文":
            unit = "篇"
        elif name == "发明专利":
            unit = "件"
        elif name == "培养研究生":
            unit = "人"
        snippet = _metric_focus_snippet(scoped, m.start(), m.end(), pad=120)
        if len((prefix_raw or "").strip()) > 45:
            continue
        ctx = f"{prefix_raw}{snippet}"
        wide = scoped[max(0, m.start() - 220) : min(len(scoped), m.end() + 100)]
        # 年度/阶段口径不入库：有些“第一年度目标:2”紧贴数值，可能落在窗口边界，
        # 这里对 snippet/wide 再做一次兜底扫描，避免把年度拆分值当实施期总值。
        if _is_annual_performance_cell_context(wide, 0, min(len(wide), 1)) or re.search(
            r"第一年度|第二年度|第三年度|第四年度|年度目标|分年度|阶段目标|阶段性目标|中期目标",
            snippet,
        ):
            continue
        # 合作单位/任务分工口径：常见“合作单位主要负责内容…完成绩效指标…新技术 2 项”，
        # 这是局部子任务指标，不与项目实施期总目标混比。
        if re.search(r"合作单位|承担单位|任务分工|主要负责|负责内容|完成绩效指标", wide or ""):
            continue
        if structured_metric_keys and name in _METRIC_CONFLICT_KEYS:
            continue
        if structured_metric_keys and name not in _METRIC_CONFLICT_KEYS:
            if not has_metric_anchor_context(f"{ctx} {wide}"):
                continue
        if _is_budget_or_labor_metric_noise(ctx) or _is_team_composition_noise(prefix_raw):
            continue
        if _is_stage_task_metric_noise(wide) or _is_stage_task_metric_noise(snippet):
            stage_mentions.append(
                (name, float(val), unit, snippet, "阶段目标-关键词+数值", _stage_label_from_context(f"{ctx} {wide}"))
            )
            continue
        if name == "科技论文" and (
            val > 35
            or _is_cv_or_aggregate_paper_context(wide)
            or _is_range_style_paper_mention(scoped, m.start(), m.end())
        ):
            continue
        if name == "培养研究生" and (
            _is_grant_unrelated_trainee_context(wide) or _is_team_composition_noise(prefix_raw)
        ):
            continue
        if name and "发明专利" in name and (
            _is_cv_or_aggregate_patent_context(ctx) or _is_cv_or_aggregate_patent_context(wide)
        ):
            continue
        mentions.append((name, float(val), unit, snippet, "关键词+数值"))

    table_metric_re = re.compile(r"培养研究生（人）[^。\n]{0,200}?实施期目标[:：]\s*(?P<num>\d+(?:\.\d+)?)")
    for m in table_metric_re.finditer(scoped):
        val = _parse_number(m.group("num"))
        if val is None:
            continue
        snippet = _metric_focus_snippet(scoped, m.start(), m.end(), pad=100)
        mentions.append(("培养研究生", float(val), "人", snippet, "绩效指标表"))

    for row in perf_rows:
        mentions.append(
            (
                row["key"],
                row["value"],
                row["unit"],
                row["snippet"],
                str(row.get("source", "绩效指标表")),
            )
        )
        sn = str(row.get("snippet") or "")
        if sn:
            for mm in re.finditer(
                r"(第一年度目标|第二年度目标|第三年度目标|第四年度目标|中期目标)\s*[:：]\s*(\d+(?:\.\d+)?)",
                sn,
            ):
                vv = _parse_number(mm.group(2))
                if vv is None:
                    continue
                stage_mentions.append(
                    (
                        str(row["key"]),
                        float(vv),
                        str(row["unit"]),
                        _metric_focus_snippet(sn, mm.start(), mm.end(), pad=80),
                        "阶段目标-绩效指标表",
                        str(mm.group(1)),
                    )
                )

    for row in perf_plain_rows:
        mentions.append(
            (
                row["key"],
                row["value"],
                row["unit"],
                row["snippet"],
                str(row.get("source", "绩效指标表(plain)")),
            )
        )
        sn = str(row.get("snippet") or "")
        if sn:
            for mm in re.finditer(
                r"(第一年度目标|第二年度目标|第三年度目标|第四年度目标|中期目标)\s*[:：]\s*(\d+(?:\.\d+)?)",
                sn,
            ):
                vv = _parse_number(mm.group(2))
                if vv is None:
                    continue
                stage_mentions.append(
                    (
                        str(row["key"]),
                        float(vv),
                        str(row["unit"]),
                        _metric_focus_snippet(sn, mm.start(), mm.end(), pad=80),
                        "阶段目标-绩效指标表",
                        str(mm.group(1)),
                    )
                )
    for row in perf_sentence_rows:
        k = str(row.get("key") or "").strip()
        if structured_metric_keys:
            if k not in structured_metric_keys and k not in _METRIC_CONFLICT_KEYS:
                continue
        # 绩效目标正文更像“任务拆解/子任务段”，默认只做阶段目标展示，不参与实施期一致性对比
        stage_mentions.append(
            (
                k,
                float(row["value"]),
                str(row["unit"]),
                str(row.get("snippet") or ""),
                "阶段目标-绩效目标正文",
                "子目标",
            )
        )

    for row in _extract_narrative_cross_metric_mentions(scoped):
        src = str(row.get("source", "正文"))
        if "(阶段)" in src:
            stage_mentions.append(
                (
                    str(row["key"]),
                    float(row["value"]),
                    str(row["unit"]),
                    str(row.get("snippet") or ""),
                    src,
                    str(row.get("stage_label") or _stage_label_from_context(str(row.get("snippet") or ""))),
                )
            )
        else:
            mentions.append(
                (
                    row["key"],
                    row["value"],
                    row["unit"],
                    row["snippet"],
                    src,
                )
            )
    for row in _extract_structured_metric_narrative_mentions(scoped, structured_key_units):
        src = str(row.get("source", "正文-指标提及"))
        if "(阶段)" in src:
            stage_mentions.append(
                (
                    str(row["key"]),
                    float(row["value"]),
                    str(row["unit"]),
                    str(row.get("snippet") or ""),
                    src,
                    str(row.get("stage_label") or _stage_label_from_context(str(row.get("snippet") or ""))),
                )
            )
        else:
            mentions.append(
                (
                    row["key"],
                    row["value"],
                    row["unit"],
                    row["snippet"],
                    src,
                )
            )
    for row in _extract_structured_metric_narrative_mentions_loose(scoped, structured_key_units):
        mentions.append(
            (
                row["key"],
                row["value"],
                row["unit"],
                row["snippet"],
                str(row.get("source", "正文-指标提及(区间)")),
            )
        )
    for row in _extract_structured_metric_narrative_mentions_fallback(scoped, structured_key_units):
        mentions.append(
            (
                row["key"],
                row["value"],
                row["unit"],
                row["snippet"],
                str(row.get("source", "正文-指标提及(区间)")),
            )
        )

    mentions = [
        (n, v, u, s, src)
        for n, v, u, s, src in mentions
        if n and float(v) > 0 and (n in _METRIC_CONFLICT_KEYS or n in structured_metric_keys)
    ]
    def _narrative_src_priority(src: str) -> int:
        ssrc = str(src or "")
        if ssrc.startswith("正文-论文"):
            return 0
        if ssrc.startswith("正文-专利") or ssrc.startswith("正文-研究生"):
            return 1
        if ssrc.startswith("正文-指标提及(区间/宽松)"):
            return 3
        if ssrc.startswith("正文-指标提及"):
            return 2
        if "正文" in ssrc:
            return 4
        return 9

    dedup_non_narr: list[Tuple[str, float, str, str, str]] = []
    seen_non_narr: set[tuple[str, str, float, str, str]] = set()
    dedup_narr_best: dict[tuple[str, str, float, str], Tuple[str, float, str, str, str]] = {}

    for n, v, u, s, src in mentions:
        try:
            vv = round(float(v), 6)
        except Exception:
            vv = float(v)
        src_s = str(src or "")
        if "正文" in src_s:
            # 非区间命中统一归到「正文-指标提及」，避免标签误导
            if src_s.startswith("正文-指标提及(区间/宽松)") and not re.search(
                r"\d+\s*[~～\-至到]\s*\d+", str(s or "")
            ):
                src_s = "正文-指标提及"
            narr_fp = _metric_narrative_dedupe_key(str(n), str(u), s)
            nk = (str(n), str(u), vv, narr_fp)
            prev = dedup_narr_best.get(nk)
            cur = (n, v, u, s, src_s)
            if prev is None or _narrative_src_priority(src_s) < _narrative_src_priority(str(prev[4])):
                dedup_narr_best[nk] = cur
            continue

        dedupe_sn = _metric_snippet_dedupe_key(s)
        k = (str(n), str(u), vv, src_s, dedupe_sn)
        if k in seen_non_narr:
            continue
        seen_non_narr.add(k)
        dedup_non_narr.append((n, v, u, s, src_s))

    mentions = dedup_non_narr + list(dedup_narr_best.values())

    grouped: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    for name, val, unit, snippet, src in mentions:
        key = (name, unit)
        grouped.setdefault(key, []).append((val, snippet, src))

    # 每个 (指标名, 单位) 组至少生成一条 metric 实体，便于报告展示「已抽取」；
    # 仅当同组出现 2 处及以上数值且差异超容忍度时才追加冲突。
    ent_idx = 1
    for (name, unit), pairs in grouped.items():
        # 同一表格源（绩效指标表）在不同抽取器命中到同一数值时，只保留一条，避免“来源单一但处数=2+”。
        compact_pairs: list[tuple[float, str, str]] = []
        seen_perf: set[tuple[str, float]] = set()
        seen_narr: set[tuple[str, float, str]] = set()
        for val, sn, src in pairs:
            src_norm = "绩效指标表" if str(src or "").startswith("绩效指标表") else str(src or "")
            vv = round(float(val), 6)
            if src_norm == "绩效指标表":
                k = (src_norm, vv)
                if k in seen_perf:
                    continue
                seen_perf.add(k)
            elif "正文" in src_norm:
                nk = (src_norm, vv, _metric_narrative_dedupe_key(name, unit, sn))
                if nk in seen_narr:
                    continue
                seen_narr.add(nk)
            compact_pairs.append((val, sn, src_norm))
        pairs = compact_pairs

        # 正文“区间/宽松”若给出范围且覆盖绩效表基准值，按基准值对齐，避免把区间上界误报成差异值。
        perf_baseline_vals = [float(v) for v, _, src in pairs if "绩效指标表" in str(src or "")]
        baseline_val = perf_baseline_vals[0] if perf_baseline_vals else None
        source_notes: dict[str, str] = {}
        if baseline_val is not None:
            aligned_pairs: list[tuple[float, str, str]] = []
            for val, sn, src in pairs:
                src_s = str(src or "")
                out_v = float(val)
                if ("区间" in src_s or "宽松" in src_s):
                    rng = _extract_metric_range_bounds_from_snippet(name, sn, unit)
                    if rng is not None:
                        rng, annual_note = _apply_annualized_range_if_needed(
                            name, sn, rng, exec_duration_months
                        )
                        lo, hi = rng
                        if lo <= float(baseline_val) <= hi:
                            out_v = float(baseline_val)
                            if annual_note:
                                source_notes[src_s] = annual_note
                aligned_pairs.append((out_v, sn, src_s))
            pairs = aligned_pairs

        # 对齐后再做一次正文跨来源去重：同一句同数值只保留一个最优来源标签，避免重复展示。
        merged_non_narr: list[tuple[float, str, str]] = []
        narr_best: dict[tuple[float, str], tuple[float, str, str]] = {}
        for val, sn, src in pairs:
            src_s = str(src or "")
            if "正文" not in src_s:
                merged_non_narr.append((val, sn, src_s))
                continue
            nk = (round(float(val), 6), _metric_narrative_dedupe_key(name, unit, sn))
            prev = narr_best.get(nk)
            cur = (val, sn, src_s)
            if prev is None or _narrative_src_priority(src_s) < _narrative_src_priority(prev[2]):
                narr_best[nk] = cur
        pairs = merged_non_narr + list(narr_best.values())

        vals = [v for v, _, _ in pairs]
        snippets = [s for _, s, _ in pairs]
        src_tags = [src for _, _, src in pairs]
        distinct_sources = []
        for t in src_tags:
            if t and t not in distinct_sources:
                distinct_sources.append(t)
        by_source_vals: dict[str, list[float]] = {}
        by_source_counts: dict[str, int] = {}
        by_source_snips: dict[str, list[str]] = {}
        for v, _s, src in pairs:
            sk = str(src or "")
            by_source_vals.setdefault(sk, [])
            by_source_counts[sk] = int(by_source_counts.get(sk, 0)) + 1
            vv = round(float(v), 6)
            if vv not in by_source_vals[sk]:
                by_source_vals[sk].append(vv)
            ss = (_s or "").strip()
            if ss:
                bucket = by_source_snips.setdefault(sk, [])
                fpk = _metric_snippet_dedupe_key(ss)
                if fpk and all(_metric_snippet_dedupe_key(x) != fpk for x in bucket):
                    bucket.append(ss)
                if len(bucket) > 3:
                    del bucket[3:]
        first_snip = snippets[0] if snippets else ""
        ent_id = f"E_metric_{doc_id}_{ent_idx}"

        # 阶段目标：同名同单位的分年度/阶段提及，按阶段分组（仅展示，不参与冲突判定）
        stage_values_by_stage: dict[str, list[float]] = {}
        for n, v, u, _sn, _src, st in stage_mentions:
            if str(n) != str(name) or str(u) != str(unit):
                continue
            st_key = str(st or "阶段目标")
            stage_values_by_stage.setdefault(st_key, [])
            vv = round(float(v), 6)
            if vv not in stage_values_by_stage[st_key]:
                stage_values_by_stage[st_key].append(vv)

        span_for_ent: list[DocSpan] = []
        seen_snip: set[str] = set()
        for snip in snippets:
            s = (snip or "").strip()[:800]
            if not s or s in seen_snip:
                continue
            seen_snip.add(s)
            pg = _find_page_for_metric_evidence(page_texts, s) if page_texts else None
            span_for_ent.append(
                DocSpan(
                    page=(pg + 1) if pg is not None else None,
                    section_title="指标",
                    snippet=s,
                )
            )
            if len(span_for_ent) >= 4:
                break

        entities.append(
            ExtractedEntity(
                entity_id=ent_id,
                entity_type="metric",
                name=name,
                value="",
                normalized={
                    "values": vals,
                    "unit": unit,
                    "mention_count": len(pairs),
                    "evidence_sources": distinct_sources[:8],
                    "values_by_source": by_source_vals,
                    "mention_count_by_source": by_source_counts,
                    "source_snippets": by_source_snips,
                    "source_notes": source_notes,
                    # 分年度/阶段目标：按阶段分组展示，不参与一致性核验
                    "stage_values_by_stage": stage_values_by_stage,
                },
                spans=span_for_ent,
            )
        )

        compare_base = list(pairs)
        if name in _METRIC_CONFLICT_KEYS:
            has_perf_struct = any("绩效指标表" in str(src or "") for _, _, src in pairs)
            if has_perf_struct:
                # 某些模板中“绩效目标正文”会混入阶段性/分列叙述（如第一年度目标），
                # 与绩效指标表中的实施期目标口径不同，易造成误报。
                # 但若正文并非年度/阶段口径，则应参与比对，否则会漏报真实不一致。
                annual_hint = False
                for _v, sn, src in pairs:
                    if str(src or "") != "绩效目标正文":
                        continue
                    s = str(sn or "")
                    if re.search(r"第一年度|第二年度|第三年度|第四年度|年度目标|分年度|阶段性|阶段目标|中期目标", s):
                        annual_hint = True
                        break
                if annual_hint:
                    keep = [p for p in pairs if str(p[2] or "") != "绩效目标正文"]
                    if keep:
                        compare_base = keep

        # 若存在绩效表基准值，则把「绩效目标正文」中与基准不一致的“子目标值”降级为阶段目标展示，
        # 避免把任务拆解/子段落口径误判为实施期总目标冲突。
        perf_baseline_vals2 = [float(v) for v, _, src in compare_base if "绩效指标表" in str(src or "")]
        baseline2 = perf_baseline_vals2[0] if perf_baseline_vals2 else None
        if baseline2 is not None:
            filtered: list[tuple[float, str, str]] = []
            for v, sn, src in compare_base:
                if str(src or "") == "绩效目标正文":
                    try:
                        vv = float(v)
                    except Exception:
                        vv = float(v)
                    # 超出容忍比例则视为阶段/子目标
                    if baseline2 > 0 and abs(vv - baseline2) / baseline2 > float(metric_tolerance_ratio):
                        stage_mentions.append(
                            (
                                str(name),
                                float(vv),
                                str(unit),
                                str(sn or ""),
                                "阶段目标-绩效目标正文",
                                "子目标",
                            )
                        )
                        continue
                filtered.append((v, sn, src))
            compare_base = filtered
        else:
            # 没有绩效指标表基准时，绩效目标正文更像“任务拆解段”，默认不参与总目标一致性对比
            filtered2: list[tuple[float, str, str]] = []
            for v, sn, src in compare_base:
                if str(src or "") == "绩效目标正文":
                    stage_mentions.append(
                        (
                            str(name),
                            float(v),
                            str(unit),
                            str(sn or ""),
                            "阶段目标-绩效目标正文",
                            "子目标",
                        )
                    )
                    continue
                filtered2.append((v, sn, src))
            compare_base = filtered2

        compare_pairs = [
            p
            for p in compare_base
            if ("区间" not in str(p[2] or "")) and ("宽松" not in str(p[2] or ""))
        ]
        reliable_noncore = any(
            str(src or "").startswith("绩效指标表") or str(src or "").startswith("表格-")
            for _, _, src in compare_pairs
        )
        if name not in _METRIC_CONFLICT_KEYS and not reliable_noncore:
            # 非三类核心指标若仅来自自由句式抽取，先只作为实体展示，不直接给冲突结论。
            ent_idx += 1
            continue
        if len(compare_pairs) < 2:
            ent_idx += 1
            continue

        cmp_vals = [v for v, _, _ in compare_pairs]
        vmin = min(cmp_vals)
        vmax = max(cmp_vals)
        if vmin <= 0:
            ent_idx += 1
            continue
        if (vmax - vmin) / vmin <= float(metric_tolerance_ratio):
            ent_idx += 1
            continue

        cmp_src_tags = [src for _, _, src in compare_pairs]
        cmp_snippets = [sn for _, sn, _ in compare_pairs]
        srcs = {t for t in cmp_src_tags if t}
        blob = "\n".join(cmp_snippets)
        # 无绩效表时，正文仅差 1 篇多为分阶段/多段落表述，不作「不一致」
        if (
            name == "科技论文"
            and not any("绩效指标表" in (s or "") for s in srcs)
            and vmax - vmin <= 1
            and 1 <= vmax <= 15
            and srcs <= {"正文-论文", "关键词+数值"}
        ):
            ent_idx += 1
            continue
        # 「培养 1～2 名」与绩效表「1 人」等属同一量级口径
        if name == "培养研究生" and vmax - vmin <= 1 and re.search(
            r"1\s*[~～至-]\s*2\s*名|一至二\s*名|1至2\s*名", blob
        ):
            ent_idx += 1
            continue

        rel = (float(vmax) - float(vmin)) / float(vmin) if vmin > 0 else 0.0
        evidence = _pick_metric_conflict_evidence(compare_pairs, page_texts, max_spans=4)
        if not evidence:
            for _, snip, _src in compare_pairs[:3]:
                evidence.append(DocSpan(section_title="指标", snippet=(snip or "")[:900]))

        conflicts.append(
            ConflictItem(
                conflict_id=f"C_metric_{doc_id}_{ent_idx}",
                severity=ConflictSeverity.YELLOW,
                category=ConflictCategory.METRIC_VALUE,
                title="同一指标多处目标值可能不一致",
                description=(
                    f"指标「{name}」在不同出处给出的目标值不一致（单位：{unit}）："
                    f"最小约 {vmin:g}、最大约 {vmax:g}（相对偏差约 {rel * 100:.1f}%）。"
                    f"请重点核对绩效表「实施期目标」与研究目标/正文表述是否同一口径。"
                ),
                evidence=evidence,
                related_entities=[ent_id],
                rule_id="R-METRIC-01",
            )
        )
        ent_idx += 1

    return conflicts, entities


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
    """指标冲突以规则抽取为准（与绩效表/正文口径一致）；不再走 LLM 聚类，避免预算、专利与论文混群。"""
    del llm
    return detect_metric_conflicts(
        doc_id=doc_id,
        raw_text=raw_text,
        page_texts=page_texts,
        metric_tolerance_ratio=metric_tolerance_ratio,
    )
