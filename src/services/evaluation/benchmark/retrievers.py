"""技术摸底检索器"""
from typing import Any, List

from src.common.models.evaluation import BenchmarkReference
from src.services.evaluation.tools.gateway import ToolGateway


class BenchmarkRetriever:
    """通过 ToolGateway 获取文献和专利条目"""

    def __init__(self, gateway: ToolGateway):
        self.gateway = gateway

    async def retrieve(self, query: str, top_k: int = 10) -> List[BenchmarkReference]:
        """检索文献/专利"""
        raw_results = await self.gateway.tech_search(query, top_k=top_k)
        references: List[BenchmarkReference] = []

        for item in raw_results:
            references.append(
                BenchmarkReference(
                    source=str(item.get("type", item.get("source", "literature"))),
                    title=str(item.get("title", ""))[:200],
                    snippet=str(item.get("snippet", item.get("abstract", "")))[:300],
                    year=self._to_int(item.get("year")),
                    url=str(item.get("url", "")) or None,
                    score=self._to_float(item.get("score")),
                )
            )

        return [item for item in references if item.title]

    def _to_int(self, value: Any) -> int | None:
        """安全转换整数"""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_float(self, value: Any) -> float | None:
        """安全转换浮点数"""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
