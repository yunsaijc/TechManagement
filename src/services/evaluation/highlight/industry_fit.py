"""产业指南贴合分析"""
from typing import Any, Dict, List, Tuple

from src.common.models.evaluation import EvidenceItem, IndustryFitResult
from src.services.evaluation.tools.gateway import ToolGateway


class IndustryFitAnalyzer:
    """产业指南贴合分析器"""

    GUIDE_HINTS: List[Dict[str, Any]] = [
        {"name": "新一代信息技术", "keywords": ["芯片", "算法", "人工智能", "算力", "大数据"]},
        {"name": "高端装备制造", "keywords": ["装备", "产线", "工业", "控制", "自动化"]},
        {"name": "新材料", "keywords": ["材料", "复合", "涂层", "高分子", "合金"]},
        {"name": "生物医药", "keywords": ["药物", "生物", "医疗", "临床", "诊疗"]},
        {"name": "新能源与储能", "keywords": ["新能源", "电池", "储能", "光伏", "氢能"]},
    ]

    def __init__(self, gateway: ToolGateway):
        self.gateway = gateway

    async def analyze(
        self,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
        query_text: str,
    ) -> Tuple[IndustryFitResult, List[EvidenceItem]]:
        """分析与产业指南的贴合度"""
        guide_results = await self.gateway.guide_search(query_text, top_k=6)
        matched = self._collect_matches(query_text, guide_results)

        gaps = self._infer_gaps(sections)
        suggestions = self._build_suggestions(gaps, matched)
        fit_score = self._calc_fit_score(matched, gaps)

        evidence = self._build_evidence(page_chunks, guide_results)
        result = IndustryFitResult(
            fit_score=fit_score,
            matched=matched,
            gaps=gaps,
            suggestions=suggestions,
        )
        return result, evidence

    def _collect_matches(self, query_text: str, guide_results: List[Dict[str, Any]]) -> List[str]:
        """收集匹配条目"""
        matched: List[str] = []

        for item in guide_results:
            title = str(item.get("title", "")).strip()
            if title and title not in matched:
                matched.append(title)

        for hint in self.GUIDE_HINTS:
            if any(keyword in query_text for keyword in hint["keywords"]):
                if hint["name"] not in matched:
                    matched.append(hint["name"])

        return matched[:5]

    def _infer_gaps(self, sections: Dict[str, str]) -> List[str]:
        """推断产业化缺口"""
        gaps: List[str] = []
        merged = "\n".join(sections.values())

        if "量产" not in merged and "产线" not in merged:
            gaps.append("缺少量产路径与产线改造说明")
        if "成本" not in merged and "经济" not in merged:
            gaps.append("缺少成本收益与经济性测算")
        if "标准" not in merged and "认证" not in merged:
            gaps.append("缺少标准符合性与认证路径说明")

        return gaps[:3]

    def _build_suggestions(self, gaps: List[str], matched: List[str]) -> List[str]:
        """生成建议"""
        suggestions: List[str] = []

        if not matched:
            suggestions.append("补充与省级产业指南条目的逐条对照，明确对应关系")
        for gap in gaps:
            if "量产" in gap:
                suggestions.append("补充中试/量产计划、产线条件与时间节点")
            if "成本" in gap:
                suggestions.append("补充成本结构与经济效益测算表")
            if "标准" in gap:
                suggestions.append("补充标准/认证路径及关键里程碑")

        if not suggestions:
            suggestions.append("保持与产业指南条目的一一映射，并补充量化指标")

        return suggestions[:4]

    def _calc_fit_score(self, matched: List[str], gaps: List[str]) -> float:
        """计算贴合度得分"""
        match_score = min(len(matched) * 0.2, 0.8)
        gap_penalty = min(len(gaps) * 0.1, 0.4)
        return round(max(0.0, min(1.0, match_score + 0.2 - gap_penalty)), 2)

    def _build_evidence(
        self,
        page_chunks: List[Dict[str, Any]],
        guide_results: List[Dict[str, Any]],
    ) -> List[EvidenceItem]:
        """构建证据"""
        evidence: List[EvidenceItem] = []

        for item in guide_results[:3]:
            title = str(item.get("title", ""))
            if not title:
                continue
            evidence.append(
                EvidenceItem(
                    source="guide_search",
                    file=str(item.get("source", "industry_guide")),
                    page=int(item.get("page", 0) or 0),
                    snippet=title,
                )
            )

        for chunk in page_chunks:
            text = str(chunk.get("text", ""))
            if "产业" in text or "应用" in text:
                evidence.append(
                    EvidenceItem(
                        source="document",
                        file=chunk.get("file", ""),
                        page=int(chunk.get("page", 0) or 0),
                        snippet=text[:160],
                    )
                )
            if len(evidence) >= 5:
                break

        return evidence
