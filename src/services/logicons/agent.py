"""逻辑自洽校验 Agent"""
from src.common.models.logicons import GraphStats, LogiConsResult, LogiConsSummary
from src.services.logicons.extractor import LogiConsEntityExtractor
from src.services.logicons.graph import LogiConsGraphBuilder
from src.services.logicons.parser import LogiConsParser
from src.services.logicons.rules import LogiConsRuleEngine


class LogiConsAgent:
    """全局文档逻辑一致性校验 Agent"""

    def __init__(self, budget_tolerance: float = 0.01, timeline_grace_years: int = 0):
        self.parser = LogiConsParser()
        self.extractor = LogiConsEntityExtractor()
        self.graph_builder = LogiConsGraphBuilder()
        self.rule_engine = LogiConsRuleEngine(
            budget_tolerance=budget_tolerance,
            timeline_grace_years=timeline_grace_years,
        )

    async def run(self, *, check_id: str, project_id: str, text: str) -> LogiConsResult:
        chunks = self.parser.parse_text(text)
        entities = self.extractor.extract(chunks)
        graph = self.graph_builder.build(entities)
        conflicts = self.rule_engine.run(graph)

        summary = LogiConsSummary(
            high=sum(1 for c in conflicts if c.severity.value == "high"),
            medium=sum(1 for c in conflicts if c.severity.value == "medium"),
            low=sum(1 for c in conflicts if c.severity.value == "low"),
            total=len(conflicts),
        )

        warnings = []
        if not conflicts:
            warnings.append("未检测到显著逻辑冲突。")

        return LogiConsResult(
            check_id=check_id,
            project_id=project_id,
            summary=summary,
            conflicts=conflicts,
            graph_stats=GraphStats(entity_count=len(graph.entities), edge_count=len(graph.edges)),
            warnings=warnings,
        )
