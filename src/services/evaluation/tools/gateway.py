"""工具网关

统一管理正文评审服务中的检索能力调用。
"""
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional


DocSearchHandler = Callable[[str, int], Awaitable[List[Dict[str, Any]]]]
GuideSearchHandler = Callable[[str, int], Awaitable[List[Dict[str, Any]]]]
TechSearchHandler = Callable[[str, int], Awaitable[List[Dict[str, Any]]]]


class ToolUnavailableError(RuntimeError):
    """工具不可用异常"""


class ToolGateway:
    """正文评审工具网关"""

    def __init__(
        self,
        doc_search_handler: Optional[DocSearchHandler] = None,
        guide_search_handler: Optional[GuideSearchHandler] = None,
        tech_search_handler: Optional[TechSearchHandler] = None,
    ):
        self.doc_search_handler = doc_search_handler
        self.guide_search_handler = guide_search_handler
        self.tech_search_handler = tech_search_handler

    async def doc_search(
        self,
        query: str,
        page_chunks: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """文档检索

        优先使用外部处理器，未配置时走内置关键词匹配。
        """
        if self.doc_search_handler:
            return await self.doc_search_handler(query, top_k)

        keywords = self._split_keywords(query)
        if not keywords:
            return []

        results: List[Dict[str, Any]] = []
        for chunk in page_chunks:
            text = str(chunk.get("text", ""))
            if not text:
                continue
            score = sum(1 for keyword in keywords if keyword in text)
            if score <= 0:
                continue
            results.append(
                {
                    "source": "document",
                    "file": chunk.get("file", ""),
                    "page": int(chunk.get("page", 0) or 0),
                    "section": chunk.get("section", ""),
                    "snippet": text[:220],
                    "score": float(score),
                }
            )

        results.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return results[:top_k]

    async def guide_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """产业指南检索"""
        if not self.guide_search_handler:
            raise ToolUnavailableError("guide_search 未配置")
        return await self.guide_search_handler(query, top_k)

    async def tech_search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """文献/专利检索"""
        if not self.tech_search_handler:
            raise ToolUnavailableError("tech_search 未配置")
        return await self.tech_search_handler(query, top_k)

    def _split_keywords(self, text: str) -> List[str]:
        """切分检索关键词"""
        parts = [p.strip() for p in re.split(r"[，,。；;\s]+", text) if p.strip()]
        return [p for p in parts if len(p) >= 2][:12]
