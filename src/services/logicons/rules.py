"""逻辑自洽规则引擎"""
from typing import List

from src.common.models.logicons import (
    ConflictCategory,
    ConflictItem,
    ConflictSeverity,
    DocSpan,
    DocumentGraph,
)


class LogiConsRuleEngine:
    """执行时间、预算、指标一致性校验"""

    def __init__(self, budget_tolerance: float = 0.01, timeline_grace_years: int = 0):
        self.budget_tolerance = budget_tolerance
        self.timeline_grace_years = timeline_grace_years

    def run(self, graph: DocumentGraph) -> List[ConflictItem]:
        conflicts: List[ConflictItem] = []
        conflicts.extend(self._check_timeline(graph))
        conflicts.extend(self._check_budget(graph))
        conflicts.extend(self._check_indicator(graph))

        for idx, item in enumerate(conflicts, start=1):
            item.conflict_id = f"C{idx:03d}"

        return conflicts

    def _check_timeline(self, graph: DocumentGraph) -> List[ConflictItem]:
        items: List[ConflictItem] = []
        durations = [e for e in graph.entities if e.entity_type == "duration" and e.value]
        starts = [e for e in graph.entities if e.name == "year_start" and e.value]
        ends = [e for e in graph.entities if e.name == "year_end" and e.value]
        milestone_years = [e for e in graph.entities if e.entity_type == "milestone_year" and e.value]

        if starts and ends and milestone_years:
            start_year = min(int(e.value) for e in starts)
            end_year = max(int(e.value) for e in ends)
            outliers = [m for m in milestone_years if int(m.value) < start_year - self.timeline_grace_years or int(m.value) > end_year + self.timeline_grace_years]
            if outliers:
                bad = outliers[0]
                items.append(
                    ConflictItem(
                        conflict_id="",
                        rule_code="T001",
                        category=ConflictCategory.TIMELINE,
                        severity=ConflictSeverity.HIGH,
                        message=f"项目执行期为 {start_year}-{end_year}，但进度节点出现 {int(bad.value)} 年",
                        suggestion="将进度节点调整到执行期范围内，或同步修正执行期。",
                        evidences=[
                            DocSpan(section=starts[0].section, location=starts[0].location, quote=starts[0].raw_text),
                            DocSpan(section=bad.section, location=bad.location, quote=bad.raw_text),
                        ],
                    )
                )

        if durations and milestone_years:
            declared_duration = max(e.value for e in durations)
            span_years = max(e.value for e in milestone_years) - min(e.value for e in milestone_years) + 1
            if declared_duration > 0 and span_years - declared_duration > self.timeline_grace_years:
                items.append(
                    ConflictItem(
                        conflict_id="",
                        rule_code="T002",
                        category=ConflictCategory.TIMELINE,
                        severity=ConflictSeverity.HIGH,
                        message=(
                            f"执行期声明为 {declared_duration:.0f} 年，但里程碑跨度约 {span_years:.0f} 年"
                        ),
                        suggestion="核对执行期描述与详细任务进度，保持跨度一致。",
                        evidences=[
                            DocSpan(section=durations[0].section, location=durations[0].location, quote=durations[0].raw_text),
                            DocSpan(section=milestone_years[0].section, location=milestone_years[0].location, quote=milestone_years[0].raw_text),
                        ],
                    )
                )

        return items

    def _check_budget(self, graph: DocumentGraph) -> List[ConflictItem]:
        items: List[ConflictItem] = []
        totals = [e for e in graph.entities if e.name == "budget_total" and e.value]
        details = [e for e in graph.entities if e.name == "budget_detail" and e.value]

        if not totals or not details:
            return items

        total = max(e.value for e in totals)
        detail_sum = sum(e.value for e in details)
        if total <= 0:
            return items

        diff_ratio = abs(detail_sum - total) / total
        if diff_ratio > self.budget_tolerance:
            items.append(
                ConflictItem(
                    conflict_id="",
                    rule_code="B001",
                    category=ConflictCategory.BUDGET,
                    severity=ConflictSeverity.HIGH,
                    message=f"资金总额与明细合计不一致: 总额={total:.2f}元, 明细合计={detail_sum:.2f}元",
                    suggestion="核对资金总额与各分项金额，统一预算口径并修正金额。",
                    evidences=[
                        DocSpan(section=totals[0].section, location=totals[0].location, quote=totals[0].raw_text),
                        DocSpan(section=details[0].section, location=details[0].location, quote=details[0].raw_text),
                    ],
                )
            )

        return items

    def _check_indicator(self, graph: DocumentGraph) -> List[ConflictItem]:
        items: List[ConflictItem] = []
        indicators = [e for e in graph.entities if e.entity_type == "indicator" and e.value is not None]
        if len(indicators) < 2:
            return items

        # 简单启发：相同单位且语义均含“论文”时，若数值差异过大则提示
        paper_indicators = [e for e in indicators if "论文" in e.raw_text]
        if len(paper_indicators) >= 2:
            values = [e.value for e in paper_indicators]
            if max(values) > 0 and (max(values) - min(values)) / max(values) > 0.5:
                items.append(
                    ConflictItem(
                        conflict_id="",
                        rule_code="I001",
                        category=ConflictCategory.INDICATOR,
                        severity=ConflictSeverity.MEDIUM,
                        message="同类论文指标在不同章节存在明显差异，可能存在前后不一致。",
                        suggestion="核查总体指标与分阶段指标定义，确保口径一致。",
                        evidences=[
                            DocSpan(section=paper_indicators[0].section, location=paper_indicators[0].location, quote=paper_indicators[0].raw_text),
                            DocSpan(section=paper_indicators[-1].section, location=paper_indicators[-1].location, quote=paper_indicators[-1].raw_text),
                        ],
                    )
                )

        # I002: 总体指标与分阶段指标总和冲突（示例：总体论文6篇，分阶段4+5篇）
        metric_keywords = {
            "paper_indicator": "论文",
            "patent_indicator": "专利",
            "revenue_indicator": "收入",
        }
        for metric_name, metric_label in metric_keywords.items():
            metric_items = [e for e in indicators if e.name == metric_name]
            if len(metric_items) < 2:
                continue

            total_candidates = [
                e for e in metric_items if ("不少于" in e.raw_text or "不低于" in e.raw_text or "达到" in e.raw_text)
                and ("20" not in e.raw_text)
            ]
            stage_candidates = [e for e in metric_items if "20" in e.raw_text]

            if not total_candidates or not stage_candidates:
                continue

            total_value = max(e.value for e in total_candidates)
            stage_sum = sum(e.value for e in stage_candidates)

            if stage_sum > total_value and total_value > 0:
                items.append(
                    ConflictItem(
                        conflict_id="",
                        rule_code="I002",
                        category=ConflictCategory.INDICATOR,
                        severity=ConflictSeverity.HIGH,
                        message=(
                            f"{metric_label}指标前后不一致：总体指标约 {total_value:.2f}，"
                            f"分阶段合计约 {stage_sum:.2f}"
                        ),
                        suggestion="统一总体指标与分阶段口径，确保总量与分解关系一致。",
                        evidences=[
                            DocSpan(
                                section=total_candidates[0].section,
                                location=total_candidates[0].location,
                                quote=total_candidates[0].raw_text,
                            ),
                            DocSpan(
                                section=stage_candidates[0].section,
                                location=stage_candidates[0].location,
                                quote=stage_candidates[0].raw_text,
                            ),
                        ],
                    )
                )

        return items
