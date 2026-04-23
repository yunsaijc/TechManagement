"""技术摸底分析器"""
from datetime import datetime
from typing import Dict, List, Tuple

from src.common.models.evaluation import BenchmarkResult, EvidenceItem, StructuredHighlights

from .retrievers import BenchmarkRetriever


class BenchmarkAnalyzer:
    """结合检索结果生成技术水平分析"""

    def __init__(self, retriever: BenchmarkRetriever, patent_search_enabled: bool = False):
        self.retriever = retriever
        self.patent_search_enabled = patent_search_enabled

    async def analyze(
        self,
        sections: Dict[str, str],
        highlights: StructuredHighlights | None,
    ) -> Tuple[BenchmarkResult, List[EvidenceItem]]:
        """执行技术摸底分析"""
        query = self._build_query(sections, highlights)
        references = await self.retriever.retrieve(query, top_k=10)

        if not references:
            return (
                BenchmarkResult(
                    novelty_level="unknown",
                    literature_position="未获取到可用文献结果",
                    patent_overlap="未获取到可用专利结果",
                    conclusion="当前无法形成可靠对比结论，请补充外部检索结果后复核",
                    references=[],
                ),
                [],
            )

        novelty_level = self._estimate_novelty(sections, references)
        literature_position = self._describe_literature(references)
        patent_overlap = self._describe_patent_overlap(references)
        conclusion = self._build_conclusion(novelty_level, literature_position, patent_overlap)

        evidence: List[EvidenceItem] = []
        for ref in references[:5]:
            evidence.append(
                EvidenceItem(
                    source="tech_search",
                    file=ref.source,
                    page=ref.year or 0,
                    snippet=f"{ref.title} {ref.snippet}"[:180],
                )
            )

        result = BenchmarkResult(
            novelty_level=novelty_level,
            literature_position=literature_position,
            patent_overlap=patent_overlap,
            conclusion=conclusion,
            references=references,
        )
        return result, evidence

    def _build_query(self, sections: Dict[str, str], highlights: StructuredHighlights | None) -> str:
        """构建检索查询"""
        query_parts: List[str] = []
        if highlights:
            query_parts.extend(highlights.research_goals[:2])
            query_parts.extend(highlights.innovations[:3])
        if not query_parts:
            query_parts.append(sections.get("研究目标", ""))
            query_parts.append(sections.get("创新点", ""))
            query_parts.append(sections.get("技术路线", ""))
        joined = " ".join([item for item in query_parts if item]).strip()
        return joined[:1200]

    def _estimate_novelty(self, sections: Dict[str, str], references: List) -> str:
        """估算新颖性等级"""
        merged = "\n".join(sections.values())
        novelty_signals = ["首次", "原创", "突破", "首创", "独创"]
        signal_hits = sum(1 for item in novelty_signals if item in merged)

        current_year = datetime.now().year
        recent_count = sum(1 for ref in references if ref.year and ref.year >= current_year - 3)

        if signal_hits >= 3 and recent_count >= 3:
            return "high"
        if signal_hits >= 1 and recent_count >= 2:
            return "medium_high"
        if recent_count >= 1:
            return "medium"
        return "medium_low"

    def _describe_literature(self, references: List) -> str:
        """描述文献位置"""
        literature = [ref for ref in references if "patent" not in ref.source.lower()]
        if not literature:
            return "暂无可比文献结论"
        return f"已检索到 {len(literature)} 条相关文献，项目与近年同类研究存在可比较改进空间"

    def _describe_patent_overlap(self, references: List) -> str:
        """描述专利重叠风险"""
        if not self.patent_search_enabled:
            return "专利对比待接入"
        patents = [ref for ref in references if "patent" in ref.source.lower() or "专利" in ref.source]
        if not patents:
            return "未检索到直接专利重叠证据"
        if len(patents) >= 4:
            return "存在较多潜在专利交叉，建议开展FTO分析"
        return "存在部分专利交叉，建议补充规避设计"

    def _build_conclusion(self, novelty: str, literature_position: str, patent_overlap: str) -> str:
        """生成综合结论"""
        novelty_map = {
            "high": "技术新颖性较高",
            "medium_high": "技术新颖性中高",
            "medium": "技术新颖性中等",
            "medium_low": "技术新颖性偏保守",
            "unknown": "技术新颖性待核验",
        }
        return (
            f"{novelty_map.get(novelty, '技术新颖性待核验')}；"
            f"{literature_position}；{patent_overlap}。"
        )
