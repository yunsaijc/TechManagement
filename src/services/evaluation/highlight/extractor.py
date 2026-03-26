"""划重点提取器"""
import re
from typing import Any, Dict, List, Tuple

from src.common.models.evaluation import EvidenceItem, StructuredHighlights


class HighlightExtractor:
    """提取研究目标、创新点和技术路线"""

    PROJECT_PROFILE_TECHNICAL = "technical"
    PROJECT_PROFILE_PLATFORM = "platform"
    PROJECT_PROFILE_MEDICAL = "medical"

    GOAL_SECTION_KEYS = ["研究目标", "项目目标", "总体目标", "项目目的和意义", "项目简介"]
    GOAL_HINTS = ["总体目标", "研究目标", "目标是", "拟实现", "拟建成", "目标值"]
    INNOVATION_SECTION_KEYS = ["创新点", "创新性", "技术创新", "方法创新", "内容创新", "模式创新", "传播创新"]
    INNOVATION_HINTS = ["创新点", "首创", "首次", "突破", "新范式", "新模式"]
    ROUTE_SECTION_KEYS = [
        "技术路线",
        "研究方案",
        "实施方案",
        "技术方案",
        "研究内容",
        "主要研究内容",
        "主要内容及实施地点",
        "项目简介",
    ]
    PLATFORM_ROUTE_SECTION_KEYS = [
        "主要内容及实施地点",
        "数字化资源库建设",
        "科普基础设施建设",
        "科普内容产出",
        "科普活动开展",
        "基层能力辐射工程",
        "资源开发",
        "协同推广",
    ]
    MEDICAL_ROUTE_SECTION_KEYS = [
        "技术路线",
        "研究方案",
        "实施方案",
        "研究目标",
        "创新点",
        "预期成果",
    ]
    ROUTE_HINTS = ["技术路线", "研究方案", "实施方案", "技术方案", "主要研究内容", "实施内容"]
    REJECT_PHRASES = [
        "填报说明",
        "项目申报书分为",
        "申报书的内容将作为",
        "每项创新点的描述限",
        "围绕基础前沿",
        "具体内容 应包括",
        "具体内容包括",
        "指标名称",
        "当前年度",
        "实施期目标",
        "绩效指标",
        "申报单位可根据",
        "请申报单位认真阅读",
        "项目名称应清晰",
        "在线填写项目申报书",
        "主要指标：",
    ]

    async def extract(
        self,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
        file_name: str,
    ) -> Tuple[StructuredHighlights, List[EvidenceItem]]:
        """提取结构化摘要与证据"""
        project_profile = self._infer_project_profile(sections)
        goals = self._collect_points(
            sections,
            page_chunks,
            self.GOAL_SECTION_KEYS,
            self.GOAL_HINTS,
            allow_hint_fallback=True,
            category="goal",
        )
        innovations = self._collect_points(
            sections,
            page_chunks,
            self.INNOVATION_SECTION_KEYS,
            self.INNOVATION_HINTS,
            allow_hint_fallback=True,
            category="innovation",
        )
        routes = self._collect_points(
            sections,
            page_chunks,
            self._get_route_section_keys(project_profile),
            self.ROUTE_HINTS,
            allow_hint_fallback=False,
            category="route",
        )

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
        section_keys: List[str],
        hints: List[str],
        allow_hint_fallback: bool,
        category: str,
    ) -> List[str]:
        """优先按章节提取，缺失时回退到切片"""
        candidates: List[str] = []

        for section_name, section_text in self._select_sections(sections, section_keys):
            candidates.extend(self._split_sentences(section_text))

        if not candidates and allow_hint_fallback:
            for chunk in page_chunks:
                text = str(chunk.get("text", ""))
                section_name = str(chunk.get("section", ""))
                if self._section_matches(section_name, section_keys) or any(hint in text for hint in hints):
                    candidates.extend(self._split_sentences(text))

        deduplicated: List[str] = []
        for line in candidates:
            normalized = self._normalize_point(line)
            if not self._is_valid_point(normalized, category):
                continue
            if normalized in deduplicated:
                continue
            deduplicated.append(normalized)

        return deduplicated

    def _infer_project_profile(self, sections: Dict[str, str]) -> str:
        """根据章节和正文特征推断项目类型"""
        section_names = " ".join(sections.keys())
        merged = f"{section_names}\n" + "\n".join(sections.values())

        platform_hits = sum(
            1 for keyword in ("科普", "宣教", "公众号", "义诊", "活动", "资源库", "直播", "展览")
            if keyword in merged
        )
        medical_hits = sum(
            1 for keyword in ("骨科", "诊疗", "临床", "患者", "手术", "医学影像", "医院")
            if keyword in merged
        )

        if platform_hits >= 4:
            return self.PROJECT_PROFILE_PLATFORM
        if medical_hits >= 4:
            return self.PROJECT_PROFILE_MEDICAL
        return self.PROJECT_PROFILE_TECHNICAL

    def _get_route_section_keys(self, project_profile: str) -> List[str]:
        """按项目类型返回技术路线候选章节"""
        if project_profile == self.PROJECT_PROFILE_PLATFORM:
            return self.PLATFORM_ROUTE_SECTION_KEYS
        if project_profile == self.PROJECT_PROFILE_MEDICAL:
            return self.MEDICAL_ROUTE_SECTION_KEYS
        return self.ROUTE_SECTION_KEYS

    def _select_sections(
        self,
        sections: Dict[str, str],
        section_keys: List[str],
    ) -> List[Tuple[str, str]]:
        """筛选更可信的候选章节"""
        selected: List[Tuple[str, str]] = []
        for section_name, section_text in sections.items():
            if self._section_matches(section_name, section_keys):
                selected.append((section_name, section_text))
        return selected

    def _section_matches(self, section_name: str, section_keys: List[str]) -> bool:
        """判断章节名是否匹配目标类型"""
        normalized = section_name.strip()
        if not normalized:
            return False
        return any(key in normalized or normalized in key for key in section_keys)

    def _is_valid_point(self, text: str, category: str) -> bool:
        """过滤模板句、表单句和噪声句"""
        if len(text) < 12:
            return False
        if len(text) > 260:
            return False
        if any(phrase in text for phrase in self.REJECT_PHRASES):
            return False
        if re.search(r"V\d{8,}", text):
            return False
        if re.search(r"(青少年|育龄夫妇|肿瘤患者|医护人员)[:：]", text):
            return False
        if text.count("：") >= 3 or text.count(":") >= 3:
            return False
        if re.search(r"(第一年度目标|第二年度目标|第三年度目标|第四年度目标)", text):
            return False
        if re.search(r"(项目编号|申报单位|吸引发动公众参与|开展科学普及活动)", text):
            return False
        if category == "route" and re.search(r"(背景与意义|建设目标|社会价值|行业引领|政策支撑)", text):
            return False
        if category == "goal" and re.search(r"(活动创新|技术赋能|资源共享)", text):
            return False
        return True

    def _normalize_point(self, text: str) -> str:
        """清洗摘要候选句"""
        normalized = text.strip(" -•*；;。")
        normalized = re.sub(r"^[（(]?[一二三四五六七八九十\d]+[）).、\s]*", "", normalized)
        normalized = re.sub(r"^创新点\d+\s*", "", normalized)
        normalized = re.sub(r"^方向[一二三四五六七八九十\d]+[:：]\s*", "", normalized)
        normalized = re.sub(r"^项目名称[:：]\s*", "", normalized)
        normalized = re.sub(r"^项目简介[:：]\s*", "", normalized)
        normalized = re.sub(r"^主要研究内容[:：]\s*", "", normalized)
        normalized = re.sub(r"^实施内容[:：]\s*", "", normalized)
        normalized = re.sub(r"^建设目标[:：]\s*", "", normalized)
        return normalized.strip()

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
