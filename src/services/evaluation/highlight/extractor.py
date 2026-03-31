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
    INNOVATION_KEYWORDS = [
        "创新",
        "突破",
        "首创",
        "首次",
        "新范式",
        "新模式",
        "智能化",
        "数字化",
        "高精度",
        "多模态",
        "3D 打印",
        "3D打印",
        "虚拟现实",
        "增强现实",
        "机器人",
        "个性化",
        "自主可控",
        "医疗+科普",
        "多学科协作",
        "智能问答平台",
        "智能化科普平台",
    ]
    ROUTE_ACTION_KEYWORDS = [
        "构建",
        "建立",
        "搭建",
        "开发",
        "设计",
        "整合",
        "开展",
        "形成",
        "利用",
        "采用",
        "实现",
        "推进",
        "优化",
        "组建",
        "改造",
    ]
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
        "目前取得的代表性科研创新成果",
    ]
    GOAL_MARKERS = ["总体目标", "研究目标", "项目目标", "建设目标", "目的"]
    INNOVATION_MARKERS = ["创新点", "创新亮点", "技术融合", "模式可推广", "新范式", "新模式"]
    ROUTE_MARKERS = ["技术路线", "实施内容", "主要研究内容", "研究内容", "活动策划", "资源开发", "协同推广"]
    SEGMENT_STOP_MARKERS = [
        "背景与意义",
        "意义",
        "创新亮点",
        "预期效益",
        "实施内容",
        "建设目标",
        "指标名称",
        "绩效指标",
        "总体目标",
    ]
    GOAL_STOP_MARKERS = [
        "实施内容",
        "意义",
        "社会价值",
        "行业引领",
        "政策支撑",
        "健康扶贫",
        "实施期目标",
        "第一年度目标",
        "第二年度目标",
        "第三年度目标",
        "第四年度目标",
        "指标名称",
        "绩效指标",
        "预期效益",
    ]
    GOAL_REJECT_MARKERS = [
        "实施期目标",
        "第一年度目标",
        "第二年度目标",
        "第三年度目标",
        "第四年度目标",
        "绩效指标",
        "指标名称",
        "社会价值",
        "行业引领",
        "政策支撑",
        "健康扶贫",
        "协同推广",
    ]
    STRUCTURED_TITLE_PATTERNS = [
        r"^方向[一二三四五六七八九十\d]+[:：]",
        r"^创新点\s*\d+",
        r"^[①②③④⑤⑥⑦⑧⑨⑩]",
        r"^(?:一是|二是|三是|四是|五是)[、:：]?",
        r"^\d+[、\.．]",
    ]
    ROUTE_METRIC_PATTERNS = [
        r"[，,](?:覆盖(?:全部)?[^\n，。；;]{0,40}(?:人次|项|册|场|%)).*$",
        r"[，,](?:年覆盖[^\n，。；;]{0,30}).*$",
        r"[，,](?:参与人数[^\n，。；;]{0,30}).*$",
        r"[，,](?:用户活跃度达[^\n，。；;]{0,30}).*$",
        r"[，,](?:发放至[^\n，。；;]{0,40}).*$",
        r"[，,](?:阅读和浏览量[^\n，。；;]{0,30}).*$",
        r"[，,](?:浏览量[^\n，。；;]{0,30}).*$",
    ]
    INNOVATION_WEAK_KEYWORDS = [
        "新媒体矩阵",
        "跨界合作",
        "形式多样化",
        "短视频",
        "直播",
        "讲座",
        "义诊",
        "科普剧",
    ]
    ROUTE_WEAK_KEYWORDS = [
        "整合现有",
        "视频/图文素材",
        "图册",
        "手册",
        "原创科普作品",
        "短视频",
        "直播",
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

        evidence = self._build_evidence(
            page_chunks=page_chunks,
            file_name=file_name,
            grouped_points={
                "goal": highlights.research_goals,
                "innovation": highlights.innovations,
                "route": highlights.technical_route,
            },
        )
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
            candidates.extend(self._extract_candidates(section_name, section_text, category))

        if not candidates and allow_hint_fallback:
            for section_name, section_text in sections.items():
                if self._contains_hint(section_text, hints):
                    candidates.extend(self._extract_candidates(section_name, section_text, category))

        if not candidates and allow_hint_fallback:
            for chunk in page_chunks:
                text = str(chunk.get("text", ""))
                section_name = str(chunk.get("section", ""))
                if self._section_matches(section_name, section_keys) or self._contains_hint(text, hints):
                    candidates.extend(self._extract_candidates(section_name, text, category))

        deduplicated: List[str] = []
        dedupe_keys: set[str] = set()
        for line in candidates:
            normalized = self._normalize_point(line, category)
            if not self._is_valid_point(normalized, category):
                continue
            dedupe_key = re.sub(r"\s+", "", normalized)
            if category == "innovation":
                replaced = False
                for index, existing in enumerate(deduplicated):
                    existing_key = re.sub(r"\s+", "", existing)
                    if dedupe_key in existing_key or existing_key in dedupe_key:
                        if len(normalized) < len(existing):
                            deduplicated[index] = normalized
                            dedupe_keys.discard(existing_key)
                            dedupe_keys.add(dedupe_key)
                        replaced = True
                        break
                if replaced:
                    continue
            if dedupe_key in dedupe_keys:
                continue
            dedupe_keys.add(dedupe_key)
            deduplicated.append(normalized)

        if category == "goal":
            return deduplicated

        return sorted(
            deduplicated,
            key=lambda item: self._score_point(item, category),
            reverse=True,
        )

    def _extract_candidates(self, section_name: str, text: str, category: str) -> List[str]:
        """按类别提取候选句"""
        if category == "goal":
            return self._extract_goal_candidates(section_name, text)
        return self._extract_structured_candidates(section_name, text, category)

    def _extract_goal_candidates(self, section_name: str, text: str) -> List[str]:
        """提取更可信的目标候选，避免把背景、绩效表和实施内容当成目标"""
        compact = re.sub(r"\s+", " ", text or "").strip()
        if not compact:
            return []

        candidates: List[str] = []
        has_overall_goal = self._contains_hint(compact, ["总体目标"])
        patterns = [
            (
                self._build_loose_marker_pattern("总体目标"),
                ["在建设期内实现以下核心目标"] + self.GOAL_STOP_MARKERS,
            ),
        ]

        if not has_overall_goal:
            patterns.extend(
                [
                    (
                        self._build_loose_marker_pattern("项目目标"),
                        self.GOAL_STOP_MARKERS,
                    ),
                    (
                        self._build_loose_marker_pattern("研究目标"),
                        ["总体目标"] + self.GOAL_STOP_MARKERS,
                    ),
                ]
            )

        if section_name in {"项目简介", "项目目的和意义"}:
            patterns.append(
                (
                    self._build_loose_marker_pattern("建设目标"),
                    ["实施内容", "预期效益", "协同推广", "意义"] + self.GOAL_STOP_MARKERS,
                )
            )

        if section_name == "项目目的和意义":
            patterns.append(
                (
                    r"(?:^|[。；;\s])目的\s*[:：]",
                    ["意义", "社会价值", "行业引领", "政策支撑", "健康扶贫"],
                )
            )

        for marker_pattern, stop_markers in patterns:
            candidates.extend(self._extract_goal_segments(compact, marker_pattern, stop_markers))

        if candidates:
            return candidates

        if (
            section_name in {"研究目标", "项目目标", "项目目的和意义"}
            and not any(marker in compact for marker in self.GOAL_REJECT_MARKERS)
        ):
            return self._split_goal_items(compact)

        return []

    def _extract_goal_segments(
        self,
        text: str,
        marker_pattern: str,
        stop_markers: List[str],
    ) -> List[str]:
        """提取目标片段并拆分为独立条目"""
        extracted: List[str] = []
        stop_regex = "|".join(re.escape(marker) for marker in stop_markers)
        pattern = re.compile(
            rf"{marker_pattern}\s*(?:是|为|包括|如下|为：|如下：)?\s*(?P<body>.+?)(?={stop_regex}|$)"
        )
        for match in pattern.finditer(text):
            body = match.group("body").strip(" ：:；;。")
            if not body:
                continue
            if any(marker in body for marker in self.GOAL_REJECT_MARKERS):
                continue
            extracted.extend(self._split_goal_items(body))
        return extracted

    def _build_loose_marker_pattern(self, marker: str) -> str:
        """构建允许字符间夹杂空白的标记匹配"""
        return "".join(f"{re.escape(char)}\\s*" for char in marker)

    def _contains_hint(self, text: str, hints: List[str]) -> bool:
        """判断文本中是否包含关键词，兼容字符间空白"""
        compact = re.sub(r"\s+", "", text or "")
        return any(re.sub(r"\s+", "", hint) in compact for hint in hints)

    def _split_goal_items(self, text: str) -> List[str]:
        """拆分目标条目，优先保留结构化列表项"""
        compact = re.sub(r"\s+", " ", text or "").strip(" ：:；;。")
        if not compact:
            return []

        numbered = re.split(r"(?:^|\s+)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[、.．]|\(?[一二三四五六七八九十]+\)?[、.．])\s*", compact)
        items = [item.strip(" ：:；;。") for item in numbered if item.strip()]
        if len(items) > 1:
            return items

        segments = re.split(r"[；;。]", compact)
        return [segment.strip(" ：:；;。") for segment in segments if segment.strip()]

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
        min_length = 6 if category == "innovation" else 12
        if len(text) < min_length:
            return False
        if len(text) > 320:
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
        if re.match(r"(实施地点|项目效益|主要指标|核心建设内容)[:：]?", text):
            return False
        if category == "route" and re.search(r"(背景与意义|建设目标|社会价值|行业引领|政策支撑)", text):
            return False
        if category == "route" and re.search(r"(主任委员|专业委员会|硕士研究生导师|副院长|发表核心论文|主持完成|实用新型专利|荣获.+奖)", text):
            return False
        if category == "route" and re.search(r"(硬件配置方面|设备配置|门急诊量|床位|病源基础|设备近\d+台|学科建设方面|核心重点学科|院区共设)", text):
            return False
        if category == "route" and re.search(r"(用户活跃度|参与人数|发放至社区|阅读和浏览量|大型科普活动\d+场)", text):
            return False
        if category == "route" and re.search(r"(整合现有\d+\+?部视频/图文素材|出版.+图册\d+册)", text):
            return False
        if category == "route" and re.match(r"(主要研究内容涉及|聚焦于|围绕开发应用先进的)", text):
            return False
        if category == "goal" and re.search(r"(背景与意义|社会价值|行业引领|政策支撑|健康扶贫)", text):
            return False
        if category == "goal" and re.search(r"(活动创新|技术赋能|资源共享|实施期目标|绩效指标|指标名称|协同推广|预期效益)", text):
            return False
        if category == "innovation" and re.search(r"(覆盖\d+|参与人数|用户活跃度|阅读和浏览量)", text):
            return False
        return True

    def _normalize_point(self, text: str, category: str) -> str:
        """清洗摘要候选句"""
        normalized = self._extract_marked_segment(text, category).strip(" -•*；;。")
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = self._collapse_broken_cjk_spacing(normalized)
        normalized = re.sub(r"^\|\s*", "", normalized)
        if category == "innovation":
            normalized = re.sub(r"^.*?创新点的描述限\s*\d+\s*字以内[）)]\s*", "", normalized)
            normalized = re.sub(r"^项目预期的主要创新点[:：]?\s*", "", normalized)
        normalized = re.sub(r"^[（(]?[一二三四五六七八九十\d]+[）).、\s]*", "", normalized)
        normalized = re.sub(r"^创新点\s*\d+\s*", "", normalized)
        normalized = re.sub(r"^方向[一二三四五六七八九十\d]+[:：]\s*", "", normalized)
        normalized = re.sub(r"^该(?:研究)?方向(?:主要)?(?:研究内容)?(?:聚焦于|聚焦|围绕|致力于|主要研究内容涉及)\s*", "", normalized)
        normalized = re.sub(r"^项目名称[:：]\s*", "", normalized)
        normalized = re.sub(r"^项目简介[:：]\s*", "", normalized)
        normalized = re.sub(r"^主要研究内容[:：]\s*", "", normalized)
        normalized = re.sub(r"^实施内容[:：]\s*", "", normalized)
        normalized = re.sub(r"^建设目标[:：]\s*", "", normalized)
        normalized = re.sub(r"^总体目标[:：]?\s*", "", normalized)
        normalized = re.sub(r"^研究目标[:：]?\s*", "", normalized)
        normalized = re.sub(r"^目的[:：]?\s*", "", normalized)
        normalized = re.sub(r"^是(?=通过|建立|形成|建设|解决|突破)", "", normalized)
        if category == "innovation":
            normalized = self._compress_innovation_point(normalized)
        if category == "route":
            normalized = self._strip_route_metric_tail(normalized)
        return normalized.strip()

    def _collapse_broken_cjk_spacing(self, text: str) -> str:
        """清理 PDF 解析后中文词内部的断裂空格"""
        normalized = text
        while True:
            updated = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", normalized)
            if updated == normalized:
                return updated
            normalized = updated

    def _extract_structured_candidates(self, section_name: str, text: str, category: str) -> List[str]:
        """按结构化条目提取创新点与技术路线候选"""
        if category == "innovation" and "项目预期的主要创新点" in section_name:
            numbered_candidates = self._extract_numbered_innovation_titles(text)
            if numbered_candidates:
                return numbered_candidates

        blocks = self._split_structured_blocks(text)
        if not blocks:
            return self._split_sentences(text)

        candidates: List[str] = []
        for block in blocks:
            candidates.extend(self._expand_block_candidates(section_name, block, category))

        return candidates or self._split_sentences(text)

    def _split_structured_blocks(self, text: str) -> List[str]:
        """按方向、创新点、项目符号等结构切块"""
        compact = re.sub(r"\r\n?", "\n", text or "")
        compact = re.sub(r"[ \t]+", " ", compact)
        compact = re.sub(r"(?<!\n)(方向[一二三四五六七八九十\d]+[:：])", r"\n\1", compact)
        compact = re.sub(r"(?<!\n)(创新点\s*\d+)", r"\n\1", compact)
        compact = re.sub(r"(?<!\n)([①②③④⑤⑥⑦⑧⑨⑩])", r"\n\1", compact)
        lines = [line.strip(" -•*\t") for line in compact.split("\n") if line.strip()]

        blocks: List[str] = []
        current: List[str] = []
        for line in lines:
            if self._is_structured_title(line) and current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(line)

        if current:
            blocks.append("\n".join(current).strip())

        return blocks

    def _expand_block_candidates(self, section_name: str, block: str, category: str) -> List[str]:
        """将结构块扩展为候选句"""
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            return []

        title = lines[0]
        body = " ".join(lines[1:]).strip()
        merged = " ".join(lines).strip()
        candidates: List[str] = []

        is_structured_title = self._is_structured_title(title)
        if title.startswith("方向") and is_structured_title and category == "route":
            candidates.append(title)
            sentence_source = body or title
        elif title.startswith("创新点") and is_structured_title:
            candidates.append(title)
            sentence_source = merged
        else:
            sentence_source = merged

        sentences = self._split_sentences(sentence_source)

        if category == "innovation":
            preferred = [
                sentence for sentence in sentences
                if any(keyword in sentence for keyword in self.INNOVATION_KEYWORDS)
            ]
            if preferred:
                candidates.extend(preferred[:3])
            elif title.startswith("方向") and body:
                route_like = [
                    sentence for sentence in self._split_sentences(body)
                    if any(keyword in sentence for keyword in self.ROUTE_ACTION_KEYWORDS + self.INNOVATION_KEYWORDS)
                ]
                candidates.extend(route_like[:2] or self._split_sentences(body)[:1])
            elif sentences:
                candidates.append(sentences[0])
        else:
            preferred = [
                sentence for sentence in sentences
                if any(keyword in sentence for keyword in self.ROUTE_ACTION_KEYWORDS)
            ]
            if preferred:
                candidates.extend(preferred[:3])
            elif sentences and section_name not in {"主要内容及实施地点"}:
                candidates.append(sentences[0])

        return candidates

    def _extract_numbered_innovation_titles(self, text: str) -> List[str]:
        """提取创新点编号标题，优先保留结构化主句"""
        compact = re.sub(r"\r\n?", "\n", text or "")
        compact = re.sub(r"(?<!\n)(创新点\s*\d+)", r"\n\1", compact)
        lines = [line.strip() for line in compact.split("\n") if line.strip()]
        results: List[str] = []
        for line in lines:
            match = re.match(r"创新点\s*\d+\s*(.+)", line)
            if not match:
                continue
            normalized = match.group(1).strip(" ：:；;。")
            normalized = re.sub(r"\s+", " ", normalized)
            if normalized:
                results.append(normalized)
        return results

    def _is_structured_title(self, text: str) -> bool:
        """判断是否为结构化条目标题"""
        compact = text.strip()
        return any(re.match(pattern, compact) for pattern in self.STRUCTURED_TITLE_PATTERNS)

    def _compress_innovation_point(self, text: str) -> str:
        """将冗长创新描述压缩为更适合专家扫读的技术短语"""
        normalized = text.strip()
        phrase_patterns = [
            r"(智能化\s*影像处理算法)",
            r"(多模态\s*影像融合技术)",
            r"(智能化的?康复机器人系统)",
            r"(康复及术中导航机器人(?:临床)?应用研究)",
            r"(3D\s*打印及导板制作研发应用研究)",
            r"(高精度的?手术导板)",
            r"(自主可控无人机载快照式衍射编码高光谱相机)",
            r"(低空巡检测一体化技术体系)",
            r"(智能化科普平台)",
            r"(智能问答平台)",
            r"(多学科协作机制)",
            r"(“?医疗\+科普”?深度融合)",
        ]
        for pattern in phrase_patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(1).replace("智能化的康复机器人系统", "智能化康复机器人系统")

        action_patterns = [
            r"(?:开发|研发|设计|构建|建立|形成|打造|推出)([^，。；;]{6,36}?(?:系统|平台|技术|算法|模型|体系|机器人|导板))",
            r"(?:研究|强调)([^，。；;]{6,30}?(?:技术|算法|系统|模型))",
        ]
        for pattern in action_patterns:
            match = re.search(pattern, normalized)
            if match:
                compressed = re.sub(r"\s+", " ", match.group(1)).strip(" ，,；;。")
                compressed = re.sub(r"^(?:强调|研究)\s*", "", compressed)
                return compressed

        if "：" in normalized:
            title, _, _ = normalized.partition("：")
            title = title.strip("“”\" ")
            if 4 <= len(title) <= 24:
                return title
        return normalized

    def _strip_route_metric_tail(self, text: str) -> str:
        """移除技术路线中偏绩效指标的尾部描述"""
        normalized = text.strip()
        for pattern in self.ROUTE_METRIC_PATTERNS:
            normalized = re.sub(pattern, "", normalized)
        return normalized.strip(" ，,；;。")

    def _extract_marked_segment(self, text: str, category: str) -> str:
        """按类别提取更聚焦的片段"""
        markers = self._get_markers(category)
        compact = re.sub(r"\s+", " ", text or "").strip()
        for marker in markers:
            if marker not in compact:
                continue
            start = compact.index(marker)
            segment = compact[start:]
            stop = self._find_segment_stop(segment, marker)
            return segment[:stop].strip() if stop is not None else segment.strip()
        return compact

    def _get_markers(self, category: str) -> List[str]:
        """返回类别对应的标记词"""
        if category == "goal":
            return self.GOAL_MARKERS
        if category == "innovation":
            return self.INNOVATION_MARKERS
        return self.ROUTE_MARKERS

    def _find_segment_stop(self, segment: str, current_marker: str) -> int | None:
        """查找片段结束位置"""
        stop_positions: List[int] = []
        for marker in self.SEGMENT_STOP_MARKERS:
            if marker == current_marker:
                continue
            pos = segment.find(marker, len(current_marker))
            if pos > 0:
                stop_positions.append(pos)
        if not stop_positions:
            return None
        return min(stop_positions)

    def _score_point(self, text: str, category: str) -> int:
        """对候选句进行排序"""
        score = 0
        if category == "goal":
            if "总体目标" in text:
                score += 5
            if "建设目标" in text:
                score += 4
            if "项目目标" in text or "研究目标" in text:
                score += 4
            if "目的" in text:
                score += 2
            if "实施内容" in text:
                score -= 2
        if category == "innovation":
            if any(keyword in text for keyword in ("创新点", "创新亮点", "技术融合", "新模式", "新范式", "突破")):
                score += 4
            if any(keyword in text for keyword in ("研究", "系统", "平台", "机器人", "3D 打印", "3D打印", "个性化", "医疗+科普", "多学科协作")):
                score += 2
            if re.fullmatch(r".{8,40}(研究|系统|平台|技术|算法|模型)$", text):
                score += 4
            if any(keyword in text for keyword in ("智能化科普平台", "智能问答平台", "医疗+科普", "多学科协作")):
                score += 5
            if any(keyword in text for keyword in ("智能化影像处理算法", "多模态影像融合技术", "智能化康复机器人系统")):
                score += 4
            if re.fullmatch(r".{6,30}(应用研究|临床应用研究)$", text):
                score -= 4
            if any(keyword in text for keyword in ("骨骼和关节 模型", "骨骼和关节模型", "生物力学模型")):
                score -= 4
            if any(keyword in text for keyword in ("形式多样化", "活动", "讲座", "义诊")):
                score -= 1
            if any(keyword in text for keyword in self.INNOVATION_WEAK_KEYWORDS):
                score -= 4
            if "：" not in text and len(text) <= 28:
                score += 2
            if len(text) > 120:
                score -= 3
        if category == "route":
            if any(keyword in text for keyword in ("实施内容", "主要研究内容", "技术路线", "活动策划", "资源开发", "协同推广")):
                score += 4
            if any(text.startswith(keyword) for keyword in self.ROUTE_ACTION_KEYWORDS):
                score += 3
            if any(keyword in text for keyword in ("AI", "智能问答平台", "线上科普平台", "专家团队", "技术培训")):
                score += 3
            if any(keyword in text for keyword in ("背景与意义", "建设目标", "目的")):
                score -= 2
            if any(keyword in text for keyword in ("覆盖", "人次", "活跃度", "浏览量")):
                score -= 3
            if any(keyword in text for keyword in self.ROUTE_WEAK_KEYWORDS):
                score -= 4
        score += min(len(text) // 40, 4)
        return score

    def _build_evidence(
        self,
        page_chunks: List[Dict[str, Any]],
        file_name: str,
        grouped_points: Dict[str, List[str]],
    ) -> List[EvidenceItem]:
        """为每条摘要匹配最接近的页码证据"""
        evidence: List[EvidenceItem] = []
        for category, points in grouped_points.items():
            for point in points:
                match = self._find_best_evidence(page_chunks, point, category)
                if not match:
                    continue
                evidence.append(
                    EvidenceItem(
                        source="document",
                        file=str(match.get("file") or file_name),
                        page=int(match.get("page", 0) or 0),
                        snippet=self._build_evidence_snippet(str(match.get("text", "")), point),
                        category=category,
                        target=point,
                    )
                )
        return evidence

    def _find_best_evidence(
        self,
        page_chunks: List[Dict[str, Any]],
        point: str,
        category: str,
    ) -> Dict[str, Any] | None:
        """按关键词重叠寻找最接近的证据切片"""
        query_tokens = self._extract_match_tokens(point)
        if not query_tokens:
            return None

        preferred_markers = self._get_preferred_section_markers(category)
        preferred_text_markers = self._get_preferred_text_markers(category)
        penalty_markers = self._get_penalty_text_markers(category)
        best_chunk: Dict[str, Any] | None = None
        best_score = 0
        for chunk in page_chunks:
            text = str(chunk.get("text", ""))
            if not text:
                continue
            score = 0
            signal_score = 0
            compact_text = re.sub(r"\s+", "", text)
            compact_section = re.sub(r"\s+", "", str(chunk.get("section", "")))

            if any(marker in compact_section for marker in preferred_markers):
                score += 20
            if any(marker in compact_text for marker in preferred_markers):
                score += 12
            if any(marker in compact_text for marker in preferred_text_markers):
                score += 24
            if any(marker in compact_text for marker in penalty_markers):
                score -= 12

            for clause in self._extract_match_clauses(point):
                if clause in compact_text:
                    matched = min(len(clause), 24)
                    score += matched
                    signal_score += matched

            for token in query_tokens:
                if token in compact_text:
                    matched = min(len(token), 8)
                    score += matched
                    signal_score += matched
            if signal_score <= 0:
                continue
            if score > best_score:
                best_score = score
                best_chunk = chunk

        return best_chunk if best_score > 0 else None

    def _get_preferred_section_markers(self, category: str) -> List[str]:
        """返回证据匹配时优先考虑的章节标记"""
        if category == "goal":
            return [re.sub(r"\s+", "", item) for item in self.GOAL_SECTION_KEYS + self.GOAL_HINTS]
        if category == "innovation":
            return [re.sub(r"\s+", "", item) for item in self.INNOVATION_SECTION_KEYS + self.INNOVATION_HINTS]
        return [re.sub(r"\s+", "", item) for item in self.ROUTE_SECTION_KEYS + self.ROUTE_HINTS]

    def _get_preferred_text_markers(self, category: str) -> List[str]:
        """返回证据正文中更强的优先标记"""
        if category == "goal":
            return ["总体目标", "实施期目标", "第一年度目标", "第二年度目标", "在建设期内实现以下核心目标"]
        if category == "innovation":
            return ["创新点", "本研究强调", "研究开发出", "智能化的康复机器人系统", "多模态影像融合技术"]
        return ["技术路线", "研究方案", "实施方案", "方向一", "方向二", "方向三", "方向四"]

    def _get_penalty_text_markers(self, category: str) -> List[str]:
        """返回应降低分数的正文标记"""
        if category == "goal":
            return ["方向一", "方向二", "方向三", "方向四", "技术路线及创新点"]
        if category == "innovation":
            return ["总体目标", "实施期目标", "绩效指标"]
        return ["总体目标", "实施期目标", "绩效指标"]

    def _extract_match_clauses(self, text: str) -> List[str]:
        """提取用于证据匹配的关键短句"""
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            return []

        clauses = [
            item.strip()
            for item in re.split(r"[，,。；;：:]", compact)
            if len(item.strip()) >= 8
        ]
        clauses.sort(key=len, reverse=True)
        return clauses[:3]

    def _extract_match_tokens(self, text: str) -> List[str]:
        """提取用于证据匹配的关键词"""
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            return []

        tokens: List[str] = []
        for pattern in (
            r"[\u4e00-\u9fff]{4,12}",
            r"[A-Za-z]{2,}(?:[+-][A-Za-z]+)?",
            r"\d+D",
        ):
            tokens.extend(re.findall(pattern, compact))

        deduped: List[str] = []
        seen: set[str] = set()
        for token in sorted(tokens, key=len, reverse=True):
            variants = [token]
            if "的" in token:
                variants.append(token.replace("的", ""))
            else:
                if len(token) >= 6 and token.startswith("智能化"):
                    variants.append(token.replace("智能化", "智能化的", 1))
            for variant in variants:
                if variant in seen:
                    continue
                seen.add(variant)
                deduped.append(variant)
        return deduped[:8]

    def _build_evidence_snippet(self, text: str, point: str) -> str:
        """围绕命中的关键短句截取证据片段"""
        normalized_text = re.sub(r"\s+", "", text or "")
        if not normalized_text:
            return ""

        anchors = self._extract_match_clauses(point) + self._extract_match_tokens(point)
        for anchor in anchors:
            idx = normalized_text.find(anchor)
            if idx < 0:
                continue
            start = max(0, idx - 40)
            end = min(len(normalized_text), idx + len(anchor) + 80)
            snippet = normalized_text[start:end]
            if start > 0:
                snippet = f"...{snippet}"
            if end < len(normalized_text):
                snippet = f"{snippet}..."
            return snippet

        fallback = normalized_text[:180]
        return f"{fallback}..." if len(normalized_text) > 180 else fallback

    def _split_sentences(self, text: str) -> List[str]:
        """按句切分文本"""
        compact = re.sub(r"\s+", " ", text or "").strip()
        if not compact:
            return []
        sentences = re.split(r"[。！？；;]", compact)
        return [sentence.strip() for sentence in sentences if sentence.strip()]
