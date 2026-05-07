"""正文评审检索适配层"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import requests


class EvaluationSearchClient:
    """统一封装正文评审使用的外部检索能力"""

    COMPACT_QUERY_HINT_TERMS = (
        "骨科",
        "临床",
        "机器人",
        "手术",
        "诊疗",
        "医学",
        "医疗",
        "数字化",
        "导航",
        "图像",
        "算法",
        "模型",
        "平台",
        "系统",
        "人工智能",
        "智能",
        "芯片",
        "材料",
        "电池",
        "传感",
        "检测",
        "控制",
        "制造",
        "工艺",
        "药物",
        "蛋白",
        "基因",
        "细胞",
        "储能",
        "光伏",
        "网络",
        "通信",
        "分析",
        "优化",
    )

    COMPACT_QUERY_SKIP_TERMS = {
        "本项目",
        "项目",
        "研究",
        "应用",
        "技术",
        "建设",
        "内容",
        "目标",
        "总体目标",
        "方向",
        "主要",
        "核心",
        "能力",
        "水平",
        "条件",
        "基础",
        "成果",
        "效益",
        "工作",
        "计划",
        "形成",
        "开展",
        "实现",
        "提升",
    }
    RESULT_SKIP_PATTERNS = (
        "espnet",
        "pretrained model",
        "python api",
        "文献检索工具",
        "药物发现",
        "drug discovery",
        "model zoo",
        "recipe in espnet",
    )
    OPENALEX_SELECT_FIELDS = (
        "id",
        "doi",
        "display_name",
        "publication_year",
        "relevance_score",
        "primary_location",
        "concepts",
    )

    def __init__(self) -> None:
        self.openalex_enabled = self._is_enabled(os.getenv("EVALUATION_OPENALEX_ENABLED", "0"))
        self.openalex_base_url = os.getenv("EVALUATION_OPENALEX_BASE_URL", "https://api.openalex.org").rstrip("/")
        self.openalex_mailto = os.getenv("EVALUATION_OPENALEX_MAILTO", "").strip()
        self.openalex_api_key = os.getenv("EVALUATION_OPENALEX_API_KEY", "").strip()
        self.openalex_timeout = float(os.getenv("EVALUATION_OPENALEX_TIMEOUT_SECONDS", "12"))
        self._tech_search_cache: Dict[tuple[str, int], List[Dict[str, Any]]] = {}

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
        cache_key = (" ".join(str(query or "").split()), max(1, min(int(top_k or 10), 25)))
        cached = self._tech_search_cache.get(cache_key)
        if cached is not None:
            return cached

        results = await asyncio.to_thread(self._search_openalex, cache_key[0], cache_key[1])
        self._tech_search_cache[cache_key] = results
        return results

    def _search_openalex(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        cleaned_query = " ".join(str(query or "").split())
        if not cleaned_query:
            return []

        compact_query = self._build_compact_query(cleaned_query)
        query_candidates: List[str] = []
        for candidate in (cleaned_query, compact_query):
            normalized_candidate = " ".join(str(candidate or "").split()).strip()
            if normalized_candidate and normalized_candidate not in query_candidates:
                query_candidates.append(normalized_candidate)

        limit = max(1, min(int(top_k or 10), 25))
        last_timeout: requests.Timeout | None = None
        for candidate_query in query_candidates:
            try:
                raw_results = self._request_openalex(candidate_query, top_k)
            except requests.Timeout as exc:
                last_timeout = exc
                continue
            mapped_results = self._map_openalex_results(raw_results)
            reranked_results = self._rerank_and_filter_results(mapped_results, candidate_query, top_k)
            if reranked_results:
                return reranked_results[:limit]

        if last_timeout is not None:
            raise last_timeout
        return []

    def _request_openalex(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """请求 OpenAlex 原始结果"""
        params: Dict[str, Any] = {
            "search": query[:300],
            "per-page": max(10, min(max(int(top_k or 10), int(top_k or 10) * 3), 25)),
            "sort": "relevance_score:desc",
            "select": ",".join(self.OPENALEX_SELECT_FIELDS),
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
        return results if isinstance(results, list) else []

    def _map_openalex_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """映射 OpenAlex 结果为统一结构"""
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

    def _rerank_and_filter_results(
        self,
        items: List[Dict[str, Any]],
        query: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """基于查询词做本地重排和低相关过滤"""
        query_terms = self._extract_query_terms(query)
        ranked: List[tuple[float, Dict[str, Any]]] = []
        fallback_ranked: List[tuple[float, Dict[str, Any]]] = []
        seen_titles: set[str] = set()

        for item in items:
            title_key = str(item.get("title") or "").strip().lower()
            if not title_key or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            if self._is_obvious_noise(item):
                continue
            if self._is_cjk_topic_mismatch(item, query_terms):
                continue

            original_score = float(item.get("score") or 0.0)
            fallback_ranked.append((original_score, dict(item)))
            local_score = self._score_item(item, query_terms)
            if local_score < 1.0:
                continue

            merged_score = original_score + local_score
            ranked_item = dict(item)
            ranked_item["score"] = round(merged_score, 4)
            ranked.append((merged_score, ranked_item))

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        limit = max(1, min(int(top_k or 10), 25))
        if ranked:
            return [item for _, item in ranked[:limit]]

        fallback_ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in fallback_ranked[:limit]]

    def _extract_query_terms(self, query: str) -> List[str]:
        """提取检索重排使用的关键词"""
        compact_query = self._build_compact_query(query)
        terms = self._tokenize_query_terms(compact_query)
        if terms:
            return terms[:8]
        return self._tokenize_query_terms(query)[:8]

    def _score_item(self, item: Dict[str, Any], query_terms: List[str]) -> float:
        """计算本地相关度分数"""
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")
        merged = f"{title} {snippet}"
        lower_merged = merged.lower()
        lower_title = title.lower()

        score = 0.0
        title_hits = 0
        snippet_hits = 0
        for term in query_terms:
            if term in title:
                score += 3.5
                title_hits += 1
            elif term in snippet:
                score += 1.2
                snippet_hits += 1

        if title_hits >= 2:
            score += 3.0
        if title_hits >= 1 and snippet_hits >= 1:
            score += 1.5
        if title_hits == 0 and snippet_hits < 3:
            score -= 6.0

        for pattern in self.RESULT_SKIP_PATTERNS:
            if pattern in lower_title:
                score -= 8.0
            if pattern in lower_merged:
                score -= 4.0

        return score

    def _is_obvious_noise(self, item: Dict[str, Any]) -> bool:
        """拦截明显与项目主题无关的噪声结果"""
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")
        merged = f"{title} {snippet}".lower()
        return any(pattern in merged for pattern in self.RESULT_SKIP_PATTERNS)

    def _is_cjk_topic_mismatch(self, item: Dict[str, Any], query_terms: List[str]) -> bool:
        """中文结果若与中文查询词完全不重合，视作主题明显不符"""
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")
        merged = f"{title} {snippet}"
        if not self._contains_cjk(merged):
            return False

        cjk_terms = [term for term in query_terms if self._contains_cjk(term)]
        if not cjk_terms:
            return False
        return not any(term in merged for term in cjk_terms)

    def _build_compact_query(self, query: str) -> str:
        """把长段落压缩成更适合 OpenAlex 的关键词查询"""
        normalized = re.sub(r"\s+", " ", str(query or "")).strip()
        if not normalized:
            return ""

        compact_terms = self._tokenize_query_terms(normalized)
        if compact_terms:
            return " ".join(compact_terms[:6])
        return normalized[:80]

    def _tokenize_query_terms(self, query: str) -> List[str]:
        """把长句稳定压缩成关键词，而不是整句中文"""
        normalized = re.sub(r"\s+", " ", str(query or "")).strip()
        if not normalized:
            return []

        compact_terms: List[str] = []
        for term in self.COMPACT_QUERY_HINT_TERMS:
            if term in normalized and term not in compact_terms:
                compact_terms.append(term)
            if len(compact_terms) >= 6:
                return compact_terms

        parts = re.split(
            r"[，,。；;、：:\s]+|以及|及其|通过|实现|开展|形成|围绕|包括|建立|构建|基于|面向|用于|结合|及|与|和|的|在|对|将",
            normalized,
        )
        for part in parts:
            token = str(part).strip("()[]{}<>《》“”\"' ")
            if not token or token in self.COMPACT_QUERY_SKIP_TERMS or token.isdigit():
                continue
            if re.fullmatch(r"[A-Za-z0-9._+-]+", token):
                if len(token) >= 2 and token not in compact_terms:
                    compact_terms.append(token)
                continue
            if len(token) < 2 or len(token) > 12:
                continue
            if token not in compact_terms:
                compact_terms.append(token)
            if len(compact_terms) >= 6:
                break

        return compact_terms

    def _contains_cjk(self, value: str) -> bool:
        return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(value or "")))

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
