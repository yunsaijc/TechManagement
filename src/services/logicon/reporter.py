import json

from src.common.models.logicon import ConflictItem, LogicOnDimensionSummary, LogicOnResult, RuleInfo

# 与 LogicOnAgent 中启用的规则保持一致；当 result.rule_snapshot 缺失时用于报告兜底
DEFAULT_ENABLED_RULES: tuple[RuleInfo, ...] = (
    RuleInfo(rule_id="R-TIME-01", name="执行期与进度安排跨度冲突"),
    RuleInfo(rule_id="R-BUDGET-01", name="预算总额与明细求和不一致"),
    RuleInfo(rule_id="R-METRIC-01", name="同一指标多处目标值不一致"),
)

_OUTCOME_ZH = {
    "consistent": "一致（本维度未检出矛盾）",
    "inconsistent": "不一致（已列出矛盾说明）",
    "insufficient": "数据不足（无法完成本维度核对）",
}


class LogicOnReporter:
    def _effective_enabled_rules(self, result: LogicOnResult) -> list[RuleInfo]:
        rs = result.rule_snapshot
        if rs and rs.enabled_rules:
            return list(rs.enabled_rules)
        return list(DEFAULT_ENABLED_RULES)

    def _append_rule_snapshot_section(
        self, lines: list[str], result: LogicOnResult, *, enabled_rules: list[RuleInfo]
    ) -> None:
        rs = result.rule_snapshot
        version = rs.version if rs and rs.version else "v1"
        lines.append("## 规则与阈值快照")
        lines.append("")
        lines.append(f"- **版本**: {version}")
        lines.append("- **启用规则**:")
        for r in enabled_rules:
            lines.append(f"  - `{r.rule_id}` {r.name}")
        thresholds: dict = {}
        if rs and rs.thresholds:
            thresholds = dict(rs.thresholds)
        if thresholds:
            lines.append("- **阈值 / 开关**:")
            for k, v in thresholds.items():
                lines.append(f"  - `{k}`: {v}")
        lines.append("")

    def _append_dimension_section(self, lines: list[str], result: LogicOnResult) -> None:
        if not result.dimension_summaries:
            return
        lines.append("## 三维度核对（执行期 / 预算 / 指标）")
        lines.append("")
        lines.append(
            "以下按 **R-TIME-01**、**R-BUDGET-01**、**R-METRIC-01** 分别说明："
            "无冲突时给出与申报书/任务书抽取结果**一致**的要点；有冲突时列出该维度下的**不一致**说明与证据。"
        )
        lines.append("")
        for i, block in enumerate(result.dimension_summaries):
            if i:
                lines.append("---")
                lines.append("")
            lines.extend(self._format_dimension_block(block))
        lines.append("")

    def _format_dimension_block(self, block: LogicOnDimensionSummary) -> list[str]:
        lines: list[str] = []
        oc = (block.outcome or "insufficient").lower()
        zh = _OUTCOME_ZH.get(oc, oc)
        lines.append(f"### `{block.rule_id}` {block.name}")
        lines.append("")
        lines.append(f"- **结论**: {zh}")
        lines.append("")
        lines.append("**说明**")
        lines.append("")
        lines.append(
            "> 阅读顺序：**抽取结果 → 规则结论 → 原文摘录**。"
            "摘录中长表格串已换行并去掉 `[表格行n]` 标记，便于对照。"
        )
        lines.append("")
        if block.detail_lines:
            lines.extend(block.detail_lines)
        else:
            lines.append("_（无正文）_")
        lines.append("")
        return lines

    def build_markdown(self, result: LogicOnResult) -> str:
        lines: list[str] = []
        enabled_rules = self._effective_enabled_rules(result)

        lines.append("# 文档逻辑一致性核验报告")
        lines.append("")
        lines.append(f"- **doc_id**: `{result.doc_id}`")
        lines.append(f"- **doc_kind**: {result.doc_kind}")
        lines.append(f"- **partial（降级/抽取不全）**: {'是' if result.partial else '否'}")
        lines.append(f"- **冲突条数**: {len(result.conflicts)}")
        lines.append("")

        self._append_rule_snapshot_section(lines, result, enabled_rules=enabled_rules)
        self._append_dimension_section(lines, result)
        if result.agent_analysis:
            lines.append("## Agent 复核说明（工具调用）")
            lines.append("")
            lines.append(
                "以下为在规则检出结果之上，由模型通过**工具调用**检索原文与摘要后生成的可读说明；"
                "数值与冲突条目仍以规则引擎输出为准。"
            )
            lines.append("")
            lines.append(result.agent_analysis.strip())
            lines.append("")
            if result.agent_tool_trace:
                lines.append("### 工具调用轨迹（节选）")
                lines.append("")
                for i, step in enumerate(result.agent_tool_trace[:40], start=1):
                    tool = step.get("tool", "")
                    lines.append(f"{i}. `{tool}`")
                    prev = step.get("result_preview") or ""
                    if prev:
                        lines.append("")
                        lines.append("```")
                        for ln in prev.split("\n")[:24]:
                            lines.append(ln[:400])
                        lines.append("```")
                    lines.append("")

        if result.warnings:
            lines.append("## 警告与提示")
            lines.append("")
            for w in result.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if not result.conflicts:
            lines.append("## 冲突明细")
            lines.append("")
            lines.append("未发现明显逻辑冲突。")
            lines.append("")
            lines.append(
                "三维度逐项结论见上文「三维度核对」；若某维度为「数据不足」，表示当前抽取结果不足以自动核对，不代表该部分无风险。"
            )
            return "\n".join(lines).strip()

        lines.append("## 冲突明细")
        lines.append("")
        for idx, c in enumerate(result.conflicts, start=1):
            lines.extend(self._format_conflict_block(idx, c))

        return "\n".join(lines).strip()

    def _format_conflict_block(self, idx: int, c: ConflictItem) -> list[str]:
        lines: list[str] = []
        lines.append(f"### {idx}. {c.title}")
        lines.append("")
        lines.append(f"| 字段 | 内容 |")
        lines.append(f"| --- | --- |")
        lines.append(f"| conflict_id | `{c.conflict_id}` |")
        lines.append(f"| rule_id | `{c.rule_id}` |")
        lines.append(f"| severity | **{c.severity.value}** |")
        lines.append(f"| category | `{c.category.value}` |")
        lines.append("")
        lines.append("**说明**")
        lines.append("")
        lines.append(c.description.strip() or "—")
        lines.append("")
        if c.related_entities:
            lines.append("**关联实体 ID**")
            lines.append("")
            lines.append(", ".join(f"`{x}`" for x in c.related_entities))
            lines.append("")
        if c.evidence:
            lines.append("**证据与定位**")
            lines.append("")
            for i, e in enumerate(c.evidence, start=1):
                page_s = f"第 {e.page} 页" if e.page is not None else "页码未知"
                sec = e.section_title or ""
                head = f"{i}. {page_s}"
                if sec:
                    head += f" · {sec}"
                lines.append(head)
                if e.start_char is not None or e.end_char is not None:
                    lines.append(
                        f"   - 字符范围: [{e.start_char}, {e.end_char}]"
                    )
                snip = (e.snippet or "").strip()
                if snip:
                    lines.append("")
                    lines.append("   ```")
                    for part in snip.split("\n"):
                        lines.append(f"   {part}")
                    lines.append("   ```")
                lines.append("")
        lines.append("---")
        lines.append("")
        return lines

    def build_json(self, result: LogicOnResult) -> str:
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
