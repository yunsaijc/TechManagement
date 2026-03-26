"""划重点提取器"""
import re
from typing import Any, Dict, List, Tuple

from src.common.models.evaluation import EvidenceItem, StructuredHighlights


class HighlightExtractor:
    """提取研究目标、创新点和技术路线"""

    GOAL_KEYS = ["研究目标", "项目目标", "总体目标", "目标"]
    INNOVATION_KEYS = ["创新点", "创新性", "技术创新", "方法创新"]
    ROUTE_KEYS = ["技术路线", "研究方案", "实施方案", "技术方案"]

    async def extract(
        self,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
        file_name: str,
    ) -> Tuple[StructuredHighlights, List[EvidenceItem]]:
        """提取结构化摘要与证据"""
        goals = self._collect_points(sections, page_chunks, self.GOAL_KEYS)
        innovations = self._collect_points(sections, page_chunks, self.INNOVATION_KEYS)
        routes = self._collect_points(sections, page_chunks, self.ROUTE_KEYS)

        highlights = StructuredHighlights(
            research_goals=goals[:3],
            innovations=innovations[:3],
            technical_route=routes[:4],
        )

        evidence = self._build_evidence(page_chunks, file_name, goals + innovations + routes)
        return highlights, evidence

    def _collect_points(
        self,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
        keywords: List[str],
    ) -> List[str]:
        """优先按章节提取，缺失时回退到切片"""
        candidates: List[str] = []

        for section_name, section_text in sections.items():
            if any(key in section_name for key in keywords):
                candidates.extend(self._split_sentences(section_text))

        if not candidates:
            for chunk in page_chunks:
                text = str(chunk.get("text", ""))
                if any(key in text for key in keywords):
                    candidates.extend(self._split_sentences(text))

        deduplicated: List[str] = []
        for line in candidates:
            normalized = line.strip(" -•*；;。")
            if len(normalized) < 8:
                continue
            if normalized in deduplicated:
                continue
            deduplicated.append(normalized)

        return deduplicated

    def _build_evidence(
        self,
        page_chunks: List[Dict[str, Any]],
        file_name: str,
        key_phrases: List[str],
    ) -> List[EvidenceItem]:
        """构建证据链"""
        evidence: List[EvidenceItem] = []
        if not key_phrases:
            return evidence

        for chunk in page_chunks:
            text = str(chunk.get("text", ""))
            if not text:
                continue
            matched = any(phrase[:12] in text for phrase in key_phrases[:10] if phrase)
            if not matched:
                continue
            evidence.append(
                EvidenceItem(
                    source="document",
                    file=chunk.get("file") or file_name,
                    page=int(chunk.get("page", 0) or 0),
                    snippet=text[:180],
                )
            )
            if len(evidence) >= 5:
                break

        return evidence

    def _split_sentences(self, text: str) -> List[str]:
        """按句切分文本"""
        compact = re.sub(r"\s+", " ", text or "").strip()
        if not compact:
            return []
        sentences = re.split(r"[。！？；;\n]", compact)
        return [sentence.strip() for sentence in sentences if sentence.strip()]
