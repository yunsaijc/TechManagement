import json

from src.common.models.perfcheck import PerfCheckResult

class PerfCheckReporter:
    """绩效核验报告生成器"""

    def build_markdown(self, result: PerfCheckResult) -> str:
        """生成 Markdown 格式的核验报告"""
        def count_levels(items):
            reds = sum(1 for x in items if getattr(x, "risk_level", "") == "RED")
            yellows = sum(1 for x in items if getattr(x, "risk_level", "") == "YELLOW")
            greens = sum(1 for x in items if getattr(x, "risk_level", "") == "GREEN")
            return reds, yellows, greens

        def has_any(level, items):
            return any(getattr(x, "risk_level", "") == level for x in items)

        metrics = list(getattr(result, "metrics_risks", []) or [])
        contents = list(getattr(result, "content_risks", []) or [])
        budgets = list(getattr(result, "budget_risks", []) or [])
        others = list(getattr(result, "other_risks", []) or [])

        all_items = metrics + contents + budgets + others
        red_n, yellow_n, green_n = count_levels(all_items)

        md = []
        md.append("# 项目申报书与任务书绩效核验查异报告")
        md.append(f"本次针对**{result.project_id}**项目的申报书和任务书进行全维度精准比对，从**核心考核指标、研究内容、预算大类**三个维度核查是否存在“偷工减料、指标缩水、预算挪移”等问题。")
        md.append("")

        overall_text = "未发现显著差异"
        if red_n > 0:
            overall_text = f"发现 {red_n} 项重点差异"
        elif yellow_n > 0:
            overall_text = f"发现 {yellow_n} 项提示差异"
        md.append(f"核验总体结论：**{overall_text}**。")
        if getattr(result, "summary", ""):
            md.append(f"核验摘要：{result.summary}")
        md.append("")

        md.append("## 一、核心考核指标：对齐核验")
        if not metrics:
            md.append("未抽取到可核验的绩效指标条目。")
        else:
            if has_any("RED", metrics):
                md.append("发现绩效指标存在明显缩水/降级/缺失等高风险变动：")
            elif has_any("YELLOW", metrics):
                md.append("绩效指标总体一致，但存在表述或约束不充分等中风险提示：")
            else:
                md.append("申报书与任务书的绩效指标整体一致，未发现论文数量减少、专利类型降级、营收目标下调等缩水情况。")
            md.append("")
            md.append("| 指标类型 | 申报书 | 任务书 | 风险等级 | 说明 |")
            md.append("| --- | --- | --- | --- | --- |")
            for m in metrics:
                a = m.apply_display or f"{m.apply_value}{m.unit}"
                t = m.task_display or f"{m.task_value}{m.unit}"
                md.append(f"| {m.type} | {a} | {t} | {m.risk_level} | {m.reason} |")
        md.append("")

        md.append("## 二、研究内容：覆盖核验")
        if not contents:
            md.append("未抽取到可核验的研究内容条目。")
        else:
            covered = sum(1 for c in contents if bool(getattr(c, "is_covered", False)))
            total = len(contents)
            coverage_ratio = (covered / total) if total else 0.0
            content_level = str(getattr(contents[0], "risk_level", "")).upper() if contents else ""
            if content_level == "RED":
                md.append(f"判定：**严重缩水**。任务书未覆盖申报书核心内容；覆盖率约 **{coverage_ratio:.1%}**（{covered}/{total}）。")
            elif content_level == "YELLOW":
                md.append(f"判定：**部分缩水**。任务书仅覆盖申报书部分内容；覆盖率约 **{coverage_ratio:.1%}**（{covered}/{total}）。")
            else:
                md.append(f"判定：**内容一致或扩展**。任务书覆盖申报书全部研究内容；覆盖率约 **{coverage_ratio:.1%}**（{covered}/{total}）。")
            md.append("")
            md.append("| 内容项 | 申报书内容摘要 | 任务书内容摘要 | 覆盖情况 | 相似度 | 风险等级 | 说明 |")
            md.append("| --- | --- | --- | --- | --- | --- | --- |")
            for c in contents:
                cov = "已覆盖" if c.is_covered else "未完全覆盖"
                apply_text = (getattr(c, "apply_text", "") or "").replace("|", "\\|")
                task_text = (getattr(c, "task_text", "") or "").replace("|", "\\|")
                md.append(f"| {c.apply_id} | {apply_text} | {task_text} | {cov} | {c.coverage_score:.2%} | {c.risk_level} | {c.reason} |")
        md.append("")

        md.append("## 三、预算大类：占比变动核验")
        if not budgets:
            md.append("未抽取到可核验的预算大类条目。")
        else:
            if has_any("RED", budgets):
                md.append("预算大类存在显著比例变动或疑似挪移：")
            elif has_any("YELLOW", budgets):
                md.append("预算大类总体一致，但存在占比变动较明显的条目：")
            else:
                md.append("预算大类与占比整体匹配，未发现“乾坤大挪移”式的结构性调整。")
            md.append("")
            md.append("| 预算类别 | 申报书占比 | 任务书占比 | 变动幅度 | 风险等级 | 说明 |")
            md.append("| --- | --- | --- | --- | --- | --- |")
            for b in budgets:
                md.append(f"| {b.type} | {b.apply_ratio:.1%} | {b.task_ratio:.1%} | {b.ratio_delta:.1%} | {b.risk_level} | {b.reason} |")
        md.append("")

        md.append("## 四、单位预算：承担/合作单位经费明细核验")
        unit_risks = getattr(result, "unit_budget_risks", []) or []
        if not unit_risks:
            md.append("未发现承担单位/合作单位经费预算明细差异。")
        else:
            md.append("| 单位 | 科目 | 申报书金额 | 任务书金额 | 差额 | 风险等级 | 说明 |")
            md.append("| --- | --- | --- | --- | --- | --- | --- |")
            for u in unit_risks:
                md.append(f"| {u.unit_name} | {u.type} | {u.apply_amount:.2f} | {u.task_amount:.2f} | {u.delta:.2f} | {u.risk_level} | {u.reason} |")
        md.append("")

        md.append("## 五、项目组成员及分工")
        member_item = None
        for o in others:
            if getattr(o, "field", "") == "项目组成员及分工":
                member_item = o
                break

        def _parse_members(raw: str):
            text = str(raw or "").strip()
            if not text:
                return []
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    rows = []
                    for x in data:
                        if not isinstance(x, dict):
                            continue
                        name = str(x.get("name") or "").strip()
                        duty = str(x.get("duty") or "").strip()
                        if name:
                            rows.append({"name": name, "duty": duty})
                    return rows
            except Exception:
                return []
            return []

        if not member_item:
            md.append("未抽取到项目组成员及分工信息。")
        else:
            apply_members = _parse_members(getattr(member_item, "apply_value", ""))
            task_members = _parse_members(getattr(member_item, "task_value", ""))
            md.append(f"核验判定：**{getattr(member_item, 'risk_level', 'GREEN')}**，{getattr(member_item, 'reason', '一致')}。")
            md.append("")

            md.append("### 申报书（第六部分：项目组主要成员表）")
            if not apply_members:
                md.append("未抽取到申报书项目组成员。")
            else:
                md.append("| 序号 | 姓名 | 分工 |")
                md.append("| --- | --- | --- |")
                for i, m in enumerate(apply_members, start=1):
                    name = str(m.get("name") or "").replace("|", "\\|")
                    duty = str(m.get("duty") or "").replace("|", "\\|")
                    md.append(f"| {i} | {name} | {duty} |")

            md.append("")
            md.append("### 任务书（第六部分：参加人员及分工表）")
            if not task_members:
                md.append("未抽取到任务书项目组成员。")
            else:
                md.append("| 序号 | 姓名 | 分工 |")
                md.append("| --- | --- | --- |")
                for i, m in enumerate(task_members, start=1):
                    name = str(m.get("name") or "").replace("|", "\\|")
                    duty = str(m.get("duty") or "").replace("|", "\\|")
                    md.append(f"| {i} | {name} | {duty} |")
        md.append("")

        md.append("## 六、核验结论")
        if red_n == 0 and yellow_n == 0:
            md.append("本次核验在核心考核指标、研究内容及预算大类维度均未发现差异迹象，任务书整体继承申报书要求。")
        elif red_n == 0:
            md.append(f"本次核验存在 **{yellow_n}** 项提示差异，建议结合原文进行复核确认。")
        else:
            md.append(f"本次核验发现 **{red_n}** 项重点差异，建议对相关条款进行重点核对并要求解释/更正。")
        md.append("")

        if getattr(result, "warnings", None):
            if result.warnings:
                md.append("## 附：注意事项")
                for w in result.warnings:
                    md.append(f"- {w}")

        return "\n".join(md)
