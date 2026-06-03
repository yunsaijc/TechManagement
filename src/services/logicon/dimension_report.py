"""按 R-TIME-01 / R-BUDGET-01 / R-METRIC-01 生成「一致 / 不一致 / 数据不足」说明行。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.models.logicon import ConflictCategory, ConflictItem, ExtractedEntity, LogicOnDimensionSummary
from src.services.logicon.rules import _ym_to_year_month


def _fmt_ym(ym: Optional[int]) -> str:
    if ym is None:
        return "—"
    y, m = _ym_to_year_month(int(ym))
    return f"{y}年{m}月"


def _time_conflicts(conflicts: List[ConflictItem]) -> List[ConflictItem]:
    return [c for c in conflicts if c.rule_id == "R-TIME-01" or c.category == ConflictCategory.TIME_SPAN]


def _budget_conflicts(conflicts: List[ConflictItem]) -> List[ConflictItem]:
    return [c for c in conflicts if c.rule_id == "R-BUDGET-01" or c.category == ConflictCategory.BUDGET_SUM]


def _metric_conflicts(conflicts: List[ConflictItem]) -> List[ConflictItem]:
    return [
        c
        for c in conflicts
        if c.rule_id == "R-METRIC-01"
        or c.category in (ConflictCategory.METRIC_VALUE, ConflictCategory.METRIC_UNIT)
    ]


def _snippet_preview(
    text: str,
    limit: int = 160,
    *,
    strip_table_row_tags: bool = False,
) -> str:
    s = (text or "").strip().replace("\n", " ")
    if strip_table_row_tags:
        s = re.sub(r"\s*\[表格行\d+\]\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _snippet_fingerprint(text: str, *, strip_table_row_tags: bool = False) -> str:
    """用于去重：忽略空白与表格行标记的短指纹。"""
    s = _snippet_preview(text, 240, strip_table_row_tags=strip_table_row_tags)
    return s[:140]


def _fmt_display_num(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return str(round(x, 4))


def _metric_span_sort_key(snippet: str) -> Tuple[int, int]:
    """摘录排序：优先绩效表/实施期目标，其次更短片段。"""
    s = snippet or ""
    sc = 0
    if "实施期目标" in s:
        sc += 40
    if "绩效" in s and "指标" in s:
        sc += 25
    if "总体" in s and "目标" in s:
        sc += 10
    return (sc, -len(s))


def _metric_snippet_matches_entity(metric_name: str, snippet: str) -> bool:
    """表格拼接时易把相邻绩效列粘进同一段，按指标名过滤无关摘录。"""
    s = snippet or ""
    if not s.strip():
        return False
    if metric_name == "培养研究生":
        s_compact = re.sub(r"\s+", "", s)
        if (
            not re.search(r"培养(?:硕士|博士)?研究生", s)
            and "研究生（人）" not in s_compact
            and not re.search(
                r"研究生\d+(?:\.\d+)?(?:[~～\-至到]\d+(?:\.\d+)?)?\s*(?:名|人)",
                s_compact,
            )
            and not re.search(r"培养[^\n。;；]{0,20}研究生", s)
        ):
            return False
        if "发表科技论文（篇）" in s and "培养研究生（人）" in s and "实施期目标" in s:
            return False
        if re.search(r"高水平论文|2[-～~]3\s*篇|国际知名学术期刊", s):
            return False
    if metric_name == "科技论文":
        if "科技论文" not in s and "论文（篇）" not in s:
            # 正文常见写法：发表/刊发 ... 3篇论文（不含“科技论文（篇）”字样）
            if not re.search(r"(?:发表|刊发)[^\n。;；]{0,40}\d+(?:\.\d+)?\s*篇[^\n。;；]{0,16}论文", s):
                return False
        if re.search(r"高水平论文\s*2[-～~]3\s*篇|国际知名学术期刊", s):
            return False
        if "培养研究生（人）" in s and "发表科技论文（篇）" in s and len(s) > 72:
            return False
    if metric_name == "发明专利":
        if "专利" not in s:
            return False
        if "实用新型" in s and "发明专利" not in s:
            return False
    return True


def _snippet_soft_breaks(text: str, *, strip_table_row_tags: bool, limit: int, chunk: int = 76) -> str:
    """在分号分隔处插入 Markdown 硬换行（行尾两空格），避免单行过长。"""
    s = _snippet_preview(text, min(limit, 420), strip_table_row_tags=strip_table_row_tags)
    if ";" not in s or len(s) <= chunk:
        return s
    parts = [p.strip() for p in s.split(";") if p.strip()]
    if len(parts) <= 1:
        return s
    rows: List[str] = []
    buf: List[str] = []
    cur_len = 0
    for p in parts:
        add = len(p) + (2 if buf else 0)
        if buf and cur_len + add > chunk:
            rows.append("; ".join(buf))
            buf = [p]
            cur_len = len(p)
        else:
            buf.append(p)
            cur_len += add
    if buf:
        rows.append("; ".join(buf))
    return "  \n".join(rows)


def build_dimension_summaries(
    *,
    conflicts: List[ConflictItem],
    time_entities: List[ExtractedEntity],
    budget_entities: List[ExtractedEntity],
    metric_entities: List[ExtractedEntity],
    has_exec: bool,
    has_progress: bool,
    exec_norm: Dict[str, Any],
    prog_norm: Dict[str, Any],
    has_total: bool,
    has_items: bool,
    total_norm: Dict[str, Any],
    items_norm: Dict[str, Any],
    amount_tolerance_wan: float,
    date_tolerance_months: int,
) -> List[LogicOnDimensionSummary]:
    """为三个固定规则各生成一条维度摘要。"""
    time_c = _time_conflicts(conflicts)
    budget_c = _budget_conflicts(conflicts)
    metric_c = _metric_conflicts(conflicts)

    time_block = _build_time_summary(
        conflicts=time_c,
        has_exec=has_exec,
        has_progress=has_progress,
        exec_norm=exec_norm,
        prog_norm=prog_norm,
        time_entities=time_entities,
        date_tolerance_months=date_tolerance_months,
    )
    budget_block = _build_budget_summary(
        conflicts=budget_c,
        has_total=has_total,
        has_items=has_items,
        total_norm=total_norm,
        items_norm=items_norm,
        amount_tolerance_wan=amount_tolerance_wan,
        budget_entities=budget_entities,
    )
    metric_block = _build_metric_summary(
        conflicts=metric_c,
        metric_entities=metric_entities,
    )
    return [time_block, budget_block, metric_block]


def _build_time_summary(
    *,
    conflicts: List[ConflictItem],
    has_exec: bool,
    has_progress: bool,
    exec_norm: Dict[str, Any],
    prog_norm: Dict[str, Any],
    time_entities: List[ExtractedEntity],
    date_tolerance_months: int,
) -> LogicOnDimensionSummary:
    rid, name = "R-TIME-01", "执行期与进度安排跨度冲突"
    lines: List[str] = []

    if conflicts:
        start_ym = exec_norm.get("start_ym")
        end_ym = exec_norm.get("end_ym")
        myms: List[int] = list(prog_norm.get("milestone_yms") or [])
        if start_ym is not None and end_ym is not None:
            lines.append(f"- **执行期**：{_fmt_ym(start_ym)} 至 {_fmt_ym(end_ym)}。")
        if myms:
            lines.append(f"- **进度最晚节点**：{_fmt_ym(max(myms))}。")
        for c in conflicts:
            lines.append(f"- **{c.title}**：{c.description}")
            for ev in c.evidence or []:
                pg = f"第{ev.page}页" if ev.page is not None else "页码未知"
                sec = ev.section_title or ""
                head = f"  - 证据（{pg}{(' · ' + sec) if sec else ''}）"
                lines.append(head)
                if (ev.snippet or "").strip():
                    lines.append(
                        f"    - 摘录：`{_snippet_preview(ev.snippet, 180, strip_table_row_tags=True)}`"
                    )
        return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="inconsistent", detail_lines=lines)

    if not has_exec and not has_progress:
        lines.append("- 未同时抽取到「执行期」与「进度安排」侧可用于比对的时间信息，本维度无法作出跨期一致性结论。")
        return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="insufficient", detail_lines=lines)

    start_ym = exec_norm.get("start_ym")
    end_ym = exec_norm.get("end_ym")
    duration_months = exec_norm.get("duration_months")
    myms: List[int] = list(prog_norm.get("milestone_yms") or [])
    years: List[int] = list(prog_norm.get("years") or [])

    extract_lines: List[str] = []
    if start_ym is not None and end_ym is not None:
        extract_lines.append(f"- **执行期**：{_fmt_ym(start_ym)} 至 {_fmt_ym(end_ym)}。")
    elif duration_months is not None:
        extract_lines.append(f"- **执行期**：约 {int(duration_months)} 个月（未解析到完整起止年月）。")
    elif has_exec:
        extract_lines.append("- **执行期**：已抽取部分字段，尚不足以还原完整起止年月。")

    if myms:
        latest = max(myms)
        extract_lines.append(f"- **进度最晚节点**：{_fmt_ym(latest)}。")
    if years:
        extract_lines.append(
            f"- **进度年份（已筛噪声）**：{', '.join(str(y) for y in sorted(set(years)))}。"
        )

    lines.append("#### ① 抽取结果")
    lines.append("")
    if extract_lines:
        lines.extend(extract_lines)
    else:
        lines.append("- （本段未解析到可用的执行期/进度时间字段。）")

    lines.append("")
    lines.append("#### ② 规则核验结论")
    lines.append("")
    rule_lines: List[str] = []
    if has_progress and end_ym is not None and myms:
        latest = max(myms)
        if latest <= end_ym + int(date_tolerance_months):
            rule_lines.append(
                f"- 最晚进度节点 **不晚于** 执行期结束（含约 **{date_tolerance_months}** 个月容忍），"
                f"**未发现**执行期与进度跨期矛盾。"
            )
    if has_exec and not has_progress:
        rule_lines.append(
            "- 仅有执行期信息，**未**抽取到可与执行期对照的进度时间节点；本段**未做**跨期数值核验。"
        )
    if not rule_lines:
        if not extract_lines:
            rule_lines.append("- 时间相关字段已抽取，本维度未触发跨度冲突规则。")
        else:
            rule_lines.append("- 本维度按当前规则 **未** 触发跨度冲突。")
    lines.extend(rule_lines)

    exec_snip = ""
    prog_snip = ""
    for ent in time_entities:
        for sp in ent.spans or []:
            t = (sp.snippet or "").strip()
            if not t:
                continue
            if getattr(ent, "entity_type", "") == "time_exec_period":
                exec_snip = t
            else:
                prog_snip = t
            break

    lines.append("")
    lines.append("#### ③ 原文摘录（便于人工核对）")
    lines.append("")
    if exec_snip and prog_snip and _snippet_fingerprint(exec_snip) == _snippet_fingerprint(prog_snip):
        body = _snippet_soft_breaks(exec_snip, strip_table_row_tags=False, limit=200)
        lines.append("- **执行期与进度（同源）**：")
        lines.append("  ```text")
        lines.append(f"  {body}")
        lines.append("  ```")
    else:
        if exec_snip:
            body = _snippet_soft_breaks(exec_snip, strip_table_row_tags=False, limit=200)
            lines.append("- **执行期**：")
            lines.append("  ```text")
            lines.append(f"  {body}")
            lines.append("  ```")
        if prog_snip:
            body = _snippet_soft_breaks(prog_snip, strip_table_row_tags=False, limit=200)
            lines.append("- **进度安排**：")
            lines.append("  ```text")
            lines.append(f"  {body}")
            lines.append("  ```")
    if not exec_snip and not prog_snip:
        lines.append("- _（无可用摘录。）_")

    return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="consistent", detail_lines=lines)


def _build_budget_summary(
    *,
    conflicts: List[ConflictItem],
    has_total: bool,
    has_items: bool,
    total_norm: Dict[str, Any],
    items_norm: Dict[str, Any],
    amount_tolerance_wan: float,
    budget_entities: List[ExtractedEntity],
) -> LogicOnDimensionSummary:
    rid, name = "R-BUDGET-01", "预算总额与明细求和不一致"
    lines: List[str] = []
    has_conflict = bool(conflicts)

    if has_conflict:
        for c in conflicts:
            lines.append(f"- **{c.title}**：{c.description}")
            for ev in c.evidence or []:
                pg = f"第{ev.page}页" if ev.page is not None else "页码未知"
                sec = ev.section_title or ""
                head = f"  - 证据（{pg}{(' · ' + sec) if sec else ''}）"
                lines.append(head)
                if (ev.snippet or "").strip():
                    lines.append(
                        f"    - 摘录：`{_snippet_preview(ev.snippet, 180, strip_table_row_tags=True)}`"
                    )
        lines.append("")

    total_wan = total_norm.get("amount_wan")
    items_wan = items_norm.get("items_wan")
    sum_wan = items_norm.get("sum_wan")
    sum_label = str(items_norm.get("sum_label") or "预算分项")
    subject_items_wan = items_norm.get("subject_items_wan")
    if not has_total or not has_items:
        lines.append("- 未同时抽取到「预算总额」与「预算分项加总」，本维度无法完成数学核对。")
        return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="insufficient", detail_lines=lines)

    tw = float(total_wan) if total_wan is not None else None
    sw = float(sum_wan) if sum_wan is not None else None
    if tw is None or sw is None:
        lines.append("- 未解析到可比较的总额与分项求和数值。")
        return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="insufficient", detail_lines=lines)

    delta = sw - tw
    lines.append("#### ① 总额核对（总额 vs 分项求和）")
    lines.append("")
    lines.append(f"- **预算总额**：**{tw:.2f}** 万元。")
    lines.append(f"- **{sum_label}加总**：**{sw:.2f}** 万元。")
    lines.append(f"- **差额**：**{delta:+.2f}** 万元。")
    if abs(delta) <= float(amount_tolerance_wan):
        lines.append(f"- **结论**：在容忍度 ±{amount_tolerance_wan:.2f} 万元内，分项求和与总额一致。")
    else:
        lines.append(f"- **结论**：分项求和与总额不一致（超出容忍度 ±{amount_tolerance_wan:.2f} 万元）。")

    lines.append("")
    lines.append("#### ② 分项明细（节选）")
    lines.append("")
    src_p = items_norm.get("source_provincial_wan")
    src_s = items_norm.get("source_self_raised_wan")
    src_m = items_norm.get("source_matching_wan")
    if None not in (src_p, src_s):
        seg = [f"省级财政 {float(src_p):.2f} 万元", f"自筹 {float(src_s):.2f} 万元"]
        if src_m is not None:
            seg.append(f"配套 {float(src_m):.2f} 万元")
        lines.append(f"- **来源构成**：{' + '.join(seg)}")
        lines.append(f"- **加总公式**：{' + '.join(seg)} = {sw:.2f} 万元")

    # 预算科目明细：设备费/业务费/劳务费等叶子项，便于对照“项目预算表”
    if isinstance(subject_items_wan, dict) and subject_items_wan:
        # 避免与来源项重复展示
        skip_keys = set()
        if isinstance(items_wan, dict):
            skip_keys |= set(str(k) for k in items_wan.keys())
        show: list[tuple[str, float]] = []
        for k, v in subject_items_wan.items():
            try:
                fv = float(v)
            except Exception:
                continue
            kk = str(k)
            if kk in skip_keys:
                continue
            show.append((kk, fv))
        if show:
            show.sort(key=lambda x: ("费" not in x[0], x[0]))
            lines.append("- **科目明细**：")
            subj_sum = 0.0
            for kk, fv in show[:12]:
                lines.append(f"  - **{kk}**：{float(fv):.2f} 万元")
                subj_sum += float(fv)
            if len(show) > 12:
                lines.append("  - _（其余科目略）_")
            else:
                parts = [f"{kk}{float(fv):.2f}万" for kk, fv in show]
                if parts:
                    lines.append(f"- **科目加总公式**：{' + '.join(parts)} = {subj_sum:.2f} 万元")
                    tol = float(amount_tolerance_wan)
                    gap_to_total = float(tw) - float(subj_sum)
                    ind_raw = items_norm.get("indirect_block_wan")
                    ind_f: float | None
                    if ind_raw is not None:
                        try:
                            ind_f = float(ind_raw)
                        except Exception:
                            ind_f = None
                    else:
                        ind_f = None
                    if ind_f is not None and ind_f > 1e-9:
                        sum_di = float(subj_sum) + ind_f
                        lines.append(
                            f"- **直接费用 + 间接费用**：{float(subj_sum):.2f} + {ind_f:.2f} = {sum_di:.2f} 万元"
                            f"（与预算总额 **{tw:.2f}** 万元对照）。"
                        )
                    elif gap_to_total > max(tol, 0.01):
                        lines.append(
                            f"- **口径说明**：上式为设备/业务/劳务等**直接费用科目**合计 **{float(subj_sum):.2f}** 万元；"
                            f"与预算总额 **{tw:.2f}** 万元相差 **{gap_to_total:.2f}** 万元，常见为**间接费用**等未列入「科目加总公式」。"
                        )
    # 若当前核对口径就是“来源分项”，则不再逐条重复展示“省级财政资金/自筹资金/配套资金”等；
    # 用户只需要看一次“来源构成 + 加总公式”即可。
    show_items_dict = True
    if "来源" in str(sum_label):
        show_items_dict = False
    if show_items_dict:
        if isinstance(items_wan, dict) and items_wan:
            for k, v in list(items_wan.items())[:12]:
                lines.append(f"- **{k}**：{float(v):.2f} 万元")
            if len(items_wan) > 12:
                lines.append("- _（其余分项略）_")
        else:
            lines.append("- _（未解析到分项字典。）_")

    lines.append("")
    lines.append("#### ③ 原文摘录（表格噪声已压缩）")
    lines.append("")
    shown = 0
    for ent in budget_entities:
        if shown >= 2:
            break
        for sp in ent.spans or []:
            if (sp.snippet or "").strip():
                label = "总额" if ent.entity_type == "budget_total" else "明细"
                body = _snippet_soft_breaks(
                    sp.snippet or "",
                    strip_table_row_tags=True,
                    limit=260,
                )
                lines.append(f"- **预算{label}**：")
                lines.append("  ```text")
                lines.append(f"  {body}")
                lines.append("  ```")
                shown += 1
                break

    return LogicOnDimensionSummary(
        rule_id=rid,
        name=name,
        outcome="inconsistent" if has_conflict else "consistent",
        detail_lines=lines,
    )


def _build_metric_summary(
    *,
    conflicts: List[ConflictItem],
    metric_entities: List[ExtractedEntity],
) -> LogicOnDimensionSummary:
    rid, name = "R-METRIC-01", "同一指标多处目标值不一致"
    lines: List[str] = []
    has_conflict = bool(conflicts)

    if has_conflict:
        ent_by_id = {e.entity_id: e for e in metric_entities if e.entity_type == "metric"}
        for c in conflicts:
            lines.append(f"- **{c.title}**：{c.description}")
            rel_metric = None
            for rel_id in c.related_entities or []:
                if rel_id in ent_by_id:
                    rel_metric = ent_by_id[rel_id]
                    break
            if rel_metric is not None:
                nv = rel_metric.normalized or {}
                vbs = nv.get("values_by_source")
                if isinstance(vbs, dict) and vbs:
                    segs: List[str] = []
                    for src, vv in vbs.items():
                        if not src or not isinstance(vv, list) or not vv:
                            continue
                        vals_disp = "、".join(_fmt_display_num(x) for x in vv)
                        segs.append(f"{src}={vals_disp}")
                    if segs:
                        lines.append(f"  - 各来源提及值：{'；'.join(segs)}。")
                src_snips = nv.get("source_snippets")
                if isinstance(src_snips, dict) and src_snips:
                    show_order = sorted(
                        src_snips.keys(),
                        key=lambda s: (0 if "绩效指标表" in str(s) else 1, 0 if "正文" in str(s) else 2, str(s)),
                    )
                    shown = 0
                    for src in show_order:
                        s_list = src_snips.get(src) or []
                        if not isinstance(s_list, list) or not s_list:
                            continue
                        raw = str(s_list[0] or "").strip()
                        if not raw:
                            continue
                        lines.append(
                            f"  - 来源摘录（{src}）：`{_snippet_preview(raw, 160, strip_table_row_tags=True)}`"
                        )
                        shown += 1
                        if shown >= 3:
                            break
            for ev in c.evidence or []:
                pg = f"第{ev.page}页" if ev.page is not None else "页码未知"
                sec = ev.section_title or ""
                head = f"  - 证据（{pg}{(' · ' + sec) if sec else ''}）"
                lines.append(head)
                if (ev.snippet or "").strip():
                    lines.append(
                        f"    - 摘录：`{_snippet_preview(ev.snippet, 180, strip_table_row_tags=True)}`"
                    )
        lines.append("")
        lines.append("#### 已抽取指标（含未冲突项）")
        lines.append("")

    n_metric = len([e for e in metric_entities if getattr(e, "entity_type", "") == "metric"])
    if n_metric == 0:
        if has_conflict:
            lines.append("- 当前冲突由证据片段触发，但未沉淀到可展示的指标实体，请结合上方证据人工复核。")
            return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="inconsistent", detail_lines=lines)
        lines.append("- 未抽取到可用于比对的绩效/指标类结构化条目，本维度未触发多处目标值冲突检测。")
        return LogicOnDimensionSummary(rule_id=rid, name=name, outcome="insufficient", detail_lines=lines)

    lines.append("#### ① 总览")
    lines.append("")
    if has_conflict:
        lines.append(f"- 共 **{n_metric}** 组指标（按名称+单位聚合）；其中部分指标已在上方标记为冲突，以下列出全部已抽取指标供核对。")
    else:
        lines.append(
            f"- 共 **{n_metric}** 组指标（按名称+单位聚合）；**未发现**多处目标值互斥或超出容忍比例的情况。"
        )
    lines.append("")

    for ent in metric_entities:
        if ent.entity_type != "metric":
            continue
        nv = getattr(ent, "normalized", None) or {}
        vals = nv.get("values")
        unit = nv.get("unit") or ""
        mc = nv.get("mention_count")
        uniq_vals: List[Any] = []

        lines.append(f"#### 「{ent.name}」（单位：{unit}）")
        lines.append("")

        # 以绩效指标表为准：如果存在绩效表“实施期目标”，优先作为基准展示；
        # 其它来源只展示“与基准一致/差异”，避免把不同口径混成一串“抽取到的数值”。
        vbs_preview = nv.get("values_by_source")
        perf_base: Optional[float] = None
        if isinstance(vbs_preview, dict):
            for k, vv in vbs_preview.items():
                if "绩效指标表" in str(k) and isinstance(vv, list) and vv:
                    try:
                        perf_base = float(vv[0])
                    except Exception:
                        perf_base = None
                    break

        if perf_base is not None:
            lines.append(f"- **基准（绩效指标表·实施期目标）**：**{_fmt_display_num(perf_base)}** {unit}。")
        elif vals is not None:
            fv: List[Any] = []
            for v in vals:
                if isinstance(v, (int, float)):
                    fv.append(round(float(v), 6))
                else:
                    fv.append(v)
            uniq_vals = list(dict.fromkeys(fv))
            if len(uniq_vals) == 1:
                u0 = uniq_vals[0]
                disp = _fmt_display_num(u0)
                extra = f"（共 **{mc}** 处表述，数值一致）" if isinstance(mc, int) and mc > 1 else ""
                lines.append(f"- **目标值**：各处均为 **{disp}** {unit}{extra}。")
            else:
                vtxt = "、".join(_fmt_display_num(v) for v in fv)
                extra = f"（共 **{mc}** 处）" if isinstance(mc, int) and mc > 0 else ""
                lines.append(f"- **抽取到的数值**：{vtxt} {extra}".strip() + "。")

        esrc = nv.get("evidence_sources")
        if isinstance(esrc, list) and esrc:
            esrc_u = list(dict.fromkeys(str(x) for x in esrc if x))
            lines.append(f"- **出处类型**：{'、'.join(esrc_u)}。")
        vbs = nv.get("values_by_source")
        cbs = nv.get("mention_count_by_source")
        source_notes = nv.get("source_notes")
        stage_vbs = nv.get("stage_values_by_stage")
        if isinstance(vbs, dict) and vbs:
            segs: List[str] = []
            # 若有绩效表基准，则按“与基准一致/差异”展示其它来源（并明确以绩效表为准）
            if perf_base is not None:
                diffs: List[str] = []
                for src, vv in vbs.items():
                    if not src or not isinstance(vv, list) or not vv:
                        continue
                    if "绩效指标表" in str(src):
                        continue
                    try:
                        cur = float(vv[0])
                    except Exception:
                        continue
                    same = abs(cur - float(perf_base)) <= 1e-9
                    if not same:
                        diffs.append(f"{src}={_fmt_display_num(cur)}")
                if diffs:
                    lines.append(f"- **差异来源（以绩效表为准）**：{'；'.join(diffs)}。")
            # 仍保留“各来源提及值”行，便于快速对照（但上面已明确基准）
            for src, vv in vbs.items():
                if not src:
                    continue
                if isinstance(vv, list) and vv:
                    vals_disp = "、".join(_fmt_display_num(x) for x in vv)
                    segs.append(f"{src}={vals_disp}")
            if segs:
                lines.append(f"- **各来源提及值**：{'；'.join(segs)}。")
        if isinstance(cbs, dict) and cbs:
            cnts: List[str] = []
            for src, c in cbs.items():
                if not src:
                    continue
                try:
                    ci = int(c)
                except Exception:
                    continue
                cnts.append(f"{src}={ci}处")
            if cnts:
                lines.append(f"- **各来源提及次数**：{'；'.join(cnts)}。")
        # 分年度/阶段目标：单独分组展示（不参与“实施期目标”一致性核验）
        if isinstance(stage_vbs, dict) and stage_vbs:
            segs2: List[str] = []
            for st, vv in stage_vbs.items():
                if not st:
                    continue
                if isinstance(vv, list) and vv:
                    vals_disp = "、".join(_fmt_display_num(x) for x in vv)
                    segs2.append(f"{st}={vals_disp}")
            if segs2:
                lines.append(f"- **分年度/阶段目标（不参与实施期一致性核验）**：{'；'.join(segs2)}。")
        if isinstance(source_notes, dict) and source_notes:
            notes: List[str] = []
            for src, note in source_notes.items():
                if not src or not note:
                    continue
                notes.append(f"{src}={note}")
            if notes:
                lines.append(f"- **来源口径说明**：{'；'.join(notes)}")

        lines.append("- **摘录**（与上列指标强相关，已去表格行标记并换行）：")
        source_snips = nv.get("source_snippets")
        n_show = 0
        if isinstance(source_snips, dict) and source_snips:
            cbs_map = cbs if isinstance(cbs, dict) else {}
            order = sorted(
                source_snips.keys(),
                key=lambda s: (
                    0 if "正文" in str(s) else 1,
                    0 if "绩效指标表" in str(s) else 1,
                    str(s),
                ),
            )
            for src in order:
                sn_list = source_snips.get(src) or []
                if not isinstance(sn_list, list):
                    continue
                show_local = 0
                # 每个来源只展示一次，避免“同来源多段摘录”重复占屏
                target_local = 1
                for raw_sn in sn_list:
                    if not _metric_snippet_matches_entity(ent.name, raw_sn):
                        continue
                    body = _snippet_soft_breaks(raw_sn, strip_table_row_tags=True, limit=200)
                    lines.append(f"  - 来源：{src}")
                    lines.append("  ```text")
                    lines.append(f"  {body}")
                    lines.append("  ```")
                    n_show += 1
                    show_local += 1
                    if show_local >= target_local:
                        break
                # 如果该来源计数>0但因过滤未展示，降级展示首条原文，避免“有次数无摘录”错觉。
                if show_local == 0 and sn_list and int(cbs_map.get(src, 0) or 0) > 0:
                    raw0 = str(sn_list[0] or "").strip()
                    if raw0:
                        body = _snippet_soft_breaks(raw0, strip_table_row_tags=True, limit=200)
                        lines.append(f"  - 来源：{src}")
                        lines.append("  ```text")
                        lines.append(f"  {body}")
                        lines.append("  ```")
                        n_show += 1
                if n_show >= 6:
                    break
        else:
            spans = [sp for sp in (ent.spans or []) if (sp.snippet or "").strip()]
            spans.sort(key=lambda sp: _metric_span_sort_key(sp.snippet or ""), reverse=True)
            seen_fp: set[str] = set()
            max_sp = 2 if (vals is not None and len(uniq_vals) == 1) else 3
            for sp in spans:
                raw_sn = sp.snippet or ""
                if not _metric_snippet_matches_entity(ent.name, raw_sn):
                    continue
                fp = _snippet_fingerprint(raw_sn, strip_table_row_tags=True)
                if fp in seen_fp:
                    continue
                seen_fp.add(fp)
                body = _snippet_soft_breaks(raw_sn, strip_table_row_tags=True, limit=200)
                lines.append("  ```text")
                lines.append(f"  {body}")
                lines.append("  ```")
                n_show += 1
                if n_show >= max_sp:
                    break
        if n_show == 0:
            lines.append("  ```text")
            lines.append("  （无通过过滤的摘录。）")
            lines.append("  ```")
        lines.append("")

    return LogicOnDimensionSummary(
        rule_id=rid,
        name=name,
        outcome="inconsistent" if has_conflict else "consistent",
        detail_lines=lines,
    )
