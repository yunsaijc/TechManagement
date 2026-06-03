"""技术摸底分析器"""
import asyncio
from datetime import datetime
import re
from typing import Dict, List, Tuple

from src.common.models.evaluation import BenchmarkResult, EvidenceItem, StructuredHighlights

from .retrievers import BenchmarkRetriever


class BenchmarkAnalyzer:
    """结合检索结果生成技术水平分析"""

    PROJECT_NAME_PATTERNS = (
        r"项\s*目\s*名\s*称\s*[：:]\s*(.+?)(?:申\s*报\s*单\s*位|承\s*担\s*单\s*位|合\s*作\s*单\s*位|项目负责人|$)",
        r"项目名称\s*\|\s*(.+?)\s*\|\s*所属专项",
        r"项目名称\s+(.+?)\s+所属专项",
    )

    QUERY_SECTION_HINTS = (
        ("目标", ("研究目标", "项目目标", "建设目标", "总体目标", "目标")),
        ("创新", ("创新点", "创新", "特色", "亮点")),
        ("路线", ("技术路线", "实施内容", "研究内容", "技术方案", "研究方案", "实施方案", "方案")),
        ("效益", ("应用", "效益", "绩效", "产业化")),
    )
    QUERY_SECTION_SKIP_HINTS = (
        "附件",
        "预算",
        "成员",
        "合作单位",
        "政策支撑",
        "组织支撑",
        "资源支撑",
        "风险",
    )

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
        references = await self._retrieve_references(query, sections)

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

    async def _retrieve_references(self, query: str, sections: Dict[str, str]) -> List:
        """主查询与项目名查询并发检索后统一合并"""
        project_title = self._extract_project_title(sections)
        query_candidates: List[tuple[str, int]] = []

        normalized_query = query.strip()
        if normalized_query:
            query_candidates.append((normalized_query, 8))

        normalized_title = project_title.strip()
        if normalized_title and normalized_title != normalized_query:
            query_candidates.append((normalized_title, 6))

        if not query_candidates:
            return []

        raw_groups = await asyncio.gather(
            *[self.retriever.retrieve(item_query, top_k=top_k) for item_query, top_k in query_candidates]
        )

        merged: List = []
        seen_keys: set[str] = set()
        for group in raw_groups:
            for item in group:
                key = self._reference_key(item)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(item)

        merged.sort(key=lambda item: float(getattr(item, "score", 0.0) or 0.0), reverse=True)
        return merged[:10]

    def _build_query(self, sections: Dict[str, str], highlights: StructuredHighlights | None) -> str:
        """构建检索查询"""
        query_parts: List[str] = []
        if highlights:
            query_parts.extend(highlights.research_goals[:2])
            query_parts.extend(highlights.innovations[:3])
            query_parts.extend(highlights.technical_route[:2])
        if not self._has_enough_query_signal(query_parts):
            query_parts.append(sections.get("研究目标", ""))
            query_parts.append(sections.get("创新点", ""))
            query_parts.append(sections.get("技术路线", ""))
        if not self._has_enough_query_signal(query_parts):
            query_parts.extend(self._collect_fuzzy_section_parts(sections))
        joined = " ".join([item for item in query_parts if item]).strip()
        return joined[:1200]

    def _has_enough_query_signal(self, query_parts: List[str]) -> bool:
        """判断当前查询片段是否足够形成有效检索词"""
        merged = " ".join(part for part in query_parts if part).strip()
        return len(merged) >= 20

    def _collect_fuzzy_section_parts(self, sections: Dict[str, str]) -> List[str]:
        """按章节关键词兜底抽取检索片段"""
        parts: List[str] = []
        used_titles: set[str] = set()

        for _, keywords in self.QUERY_SECTION_HINTS:
            for title, text in sections.items():
                normalized_title = str(title or "").strip()
                if not normalized_title or normalized_title in used_titles:
                    continue
                if any(skip in normalized_title for skip in self.QUERY_SECTION_SKIP_HINTS):
                    continue
                if not any(keyword in normalized_title for keyword in keywords):
                    continue
                snippet = self._compact_query_text(text)
                if not snippet:
                    continue
                parts.append(snippet)
                used_titles.add(normalized_title)
                break

        if parts:
            return parts

        for fallback_title in ("概述", "项目简介", "项目概况"):
            snippet = self._compact_query_text(sections.get(fallback_title, ""))
            if snippet:
                return [snippet]

        return []

    def _compact_query_text(self, text: str) -> str:
        """压缩章节文本，避免把整段原文直接塞进检索词"""
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return ""
        return normalized[:240]

    def _extract_project_title(self, sections: Dict[str, str]) -> str:
        """提取项目名称，供辅助检索使用"""
        direct_name = str(sections.get("项目名称") or "").strip()
        if direct_name:
            return direct_name[:120]

        for key in ("概述", "项目简介", "项目概况"):
            text = str(sections.get(key) or "").strip()
            if not text:
                continue
            for pattern in self.PROJECT_NAME_PATTERNS:
                match = re.search(pattern, text, re.DOTALL)
                if not match:
                    continue
                name = re.sub(r"\s+", " ", str(match.group(1) or "")).strip(" :：|\t")
                if name:
                    return name[:120]
        return ""

    def _reference_key(self, reference) -> str:
        """生成参考条目去重键"""
        title = str(getattr(reference, "title", "") or "").strip().lower()
        url = str(getattr(reference, "url", "") or "").strip().lower()
        return f"{title}|{url}"

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
