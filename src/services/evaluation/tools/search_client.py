"""正文评审检索适配层"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import requests


class EvaluationSearchClient:
    """统一封装正文评审使用的外部检索能力"""

    def __init__(self) -> None:
        self.openalex_enabled = self._is_enabled(os.getenv("EVALUATION_OPENALEX_ENABLED", "0"))
        self.openalex_base_url = os.getenv("EVALUATION_OPENALEX_BASE_URL", "https://api.openalex.org").rstrip("/")
        self.openalex_mailto = os.getenv("EVALUATION_OPENALEX_MAILTO", "").strip()
        self.openalex_api_key = os.getenv("EVALUATION_OPENALEX_API_KEY", "").strip()
        self.openalex_timeout = float(os.getenv("EVALUATION_OPENALEX_TIMEOUT_SECONDS", "12"))

    @staticmethod
    def _is_enabled(raw: str) -> bool:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def tech_search_handler(self):
        """返回技术摸底检索处理器"""
        if not self.openalex_enabled:
            return None
        return self.tech_search

    async def tech_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """执行 OpenAlex 公开论文检索"""
        return await asyncio.to_thread(self._search_openalex, query, top_k)

    def _search_openalex(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        cleaned_query = " ".join(str(query or "").split())
        if not cleaned_query:
            return []

        params: Dict[str, Any] = {
            "search": cleaned_query[:300],
            "per-page": max(1, min(int(top_k or 10), 25)),
            "sort": "relevance_score:desc",
        }
        if self.openalex_mailto:
            params["mailto"] = self.openalex_mailto
        if self.openalex_api_key:
            params["api_key"] = self.openalex_api_key

        response = requests.get(
            f"{self.openalex_base_url}/works",
            params=params,
            timeout=self.openalex_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(results, list):
            return []

        items: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("display_name") or "").strip()
            if not title:
                continue

            snippet = self._extract_snippet(item)
            doi = str(item.get("doi") or "").strip()
            primary_location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
            url = (
                str(item.get("id") or "").strip()
                or str(primary_location.get("landing_page_url") or "").strip()
                or doi
            )
            items.append(
                {
                    "type": "literature",
                    "source": "openalex",
                    "title": title[:200],
                    "snippet": snippet[:300],
                    "year": item.get("publication_year"),
                    "url": url or None,
                    "score": self._extract_score(item),
                }
            )

        return items

    def _extract_snippet(self, item: Dict[str, Any]) -> str:
        abstract = self._decode_abstract(item.get("abstract_inverted_index"))
        if abstract:
            return abstract

        primary_location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
        source_name = str(source.get("display_name") or "").strip()
        concept_names = [
            str(concept.get("display_name") or "").strip()
            for concept in (item.get("concepts") or [])[:5]
            if isinstance(concept, dict) and str(concept.get("display_name") or "").strip()
        ]

        parts = [part for part in [source_name, " / ".join(concept_names)] if part]
        return "；".join(parts) or "OpenAlex 公开论文检索结果"

    def _decode_abstract(self, inverted_index: Any) -> str:
        if not isinstance(inverted_index, dict):
            return ""

        tokens: List[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            if not isinstance(word, str) or not isinstance(positions, list):
                continue
            for position in positions:
                if isinstance(position, int):
                    tokens.append((position, word))

        if not tokens:
            return ""

        tokens.sort(key=lambda item: item[0])
        return " ".join(word for _, word in tokens)

    def _extract_score(self, item: Dict[str, Any]) -> Optional[float]:
        raw_score = item.get("relevance_score")
        if raw_score is None:
            return None
        try:
            return float(raw_score)
        except (TypeError, ValueError):
            return None
