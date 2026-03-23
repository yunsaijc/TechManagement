"""逻辑自洽服务临时图谱构建"""
from typing import List

from src.common.models.logicons import DocumentGraph, ExtractedEntity, GraphEdge


class LogiConsGraphBuilder:
    """构建文档内部临时知识图谱"""

    def build(self, entities: List[ExtractedEntity]) -> DocumentGraph:
        edges: List[GraphEdge] = []

        total_indices = [i for i, e in enumerate(entities) if e.name == "budget_total"]
        detail_indices = [i for i, e in enumerate(entities) if e.name == "budget_detail"]
        for total_idx in total_indices:
            for detail_idx in detail_indices:
                edges.append(GraphEdge(source=total_idx, target=detail_idx, relation="has_detail"))

        duration_indices = [i for i, e in enumerate(entities) if e.entity_type == "duration"]
        milestone_indices = [i for i, e in enumerate(entities) if e.entity_type == "milestone_year"]
        for duration_idx in duration_indices:
            for milestone_idx in milestone_indices:
                edges.append(GraphEdge(source=duration_idx, target=milestone_idx, relation="constrains"))

        return DocumentGraph(entities=entities, edges=edges)
