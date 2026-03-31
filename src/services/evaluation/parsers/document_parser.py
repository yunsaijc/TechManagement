"""
文档解析器

负责解析项目申报书，输出章节化文本与页码切片。
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List

from src.common.file_handler import detect_file_type, get_parser
from src.common.file_handler.base import ParseResult


class DocumentParser:
    """正文文档解析器"""

    INVALID_SECTION_TITLES = {
        "%",
        "html",
        "html.",
        "万元",
        "其他",
    }

    GENERIC_FRAGMENT_TITLES = {
        "总体",
        "目标",
        "指标",
        "指标名称",
        "指标值",
        "实施期目标",
        "第一年度目标",
        "第二年度目标",
        "第三年度目标",
        "第四年度目标",
        "当前年度",
        "附件目录",
        "附件类型",
        "附件名称",
        "序号",
    }

    SECTION_PATTERNS = [
        r"^第[一二三四五六七八九十]+部分",
        r"^[一二三四五六七八九十]+[、\.．\s]",
        r"^\d+[、\.．\s]",
        r"^\d+\.\d+[、\.．\s]",
        r"^[（(][一二三四五六七八九十\d]+[）)]",
        r"^(技术路线|研究方案|实施方案|创新点|研究内容|项目团队|人员分工|预期成果|考核指标|预期效益|社会效益|经济效益|风险分析|风险控制|进度安排|实施计划|政策依据|经费预算|伦理审查|预算说明|工作计划|研究计划|研究目标|项目目标)[：:\s]",
    ]

    SECTION_ALIASES: Dict[str, List[str]] = {
        "研究目标": ["研究目标", "项目目标", "总体目标", "建设目标"],
        "创新点": ["创新点", "创新性", "技术创新", "方法创新"],
        "技术路线": ["技术路线", "研究方案", "实施方案", "技术方案"],
        "项目团队": ["项目团队", "人员分工", "团队能力"],
        "预期成果": ["预期成果", "考核指标"],
        "社会效益": ["社会效益"],
        "经济效益": ["经济效益", "产业化", "应用前景"],
        "风险控制": ["风险分析", "风险控制", "风险管理"],
        "进度安排": ["进度安排", "实施计划", "工作计划"],
        "合规性": ["政策依据", "伦理审查", "经费预算"],
    }

    NOISE_LINE_PATTERNS = [
        r"^V\d{8,}$",
        r"^\d+$",
        r"^\[表格(?:行|表头)\d+\]$",
    ]

    BUDGET_SECTION_NAMES = {
        "省级财政资金",
        "直接费用",
        "间接费用",
        "自筹资金",
        "项目预算表",
        "项目预算",
    }

    BUDGET_DETAIL_TITLES = {
        "设备费",
        "业务费",
        "劳务费",
        "材料费",
        "测试化验加工费",
        "燃料动力费",
        "出版/文献/信息传播/知识产权事务费",
        "会议/差旅/国际合作与交流费",
        "其他支出",
        "学术论文发表费",
        "文献、信息调研费",
        "专家咨询",
    }

    TITLE_REJECT_PATTERNS = [
        r"^\[表格(?:行|表头)\d+\]",
        r"^\d+\s+其他$",
        r"^(?:设备费|业务费|劳务费|差旅/会议/国际合作与交流费|出版/文献/信息传播/知识产权事务费)[：:].*万元$",
        r"^(?:材料费|测试化验加工费|燃料动力费|会议/差旅/国际合作与交流费|其他支出|专家咨询)[：:].*万元$",
        r"^年?\d{0,4}\s*月?.*致谢函",
        r"^年省.+直播历史数据$",
    ]

    DOCX_PAGE_CHARS = 1800
    CHUNK_MAX_CHARS = 1200
    CONTAINER_SECTION_CHILD_PATTERNS: Dict[str, List[str]] = {
        "进度安排": [
            r"^\d{4}\s*年\s*\d{1,2}\s*月\s*[-—~至]+\s*\d{4}\s*年\s*\d{1,2}\s*月$",
            r"^第[一二三四五六七八九十]+年(?:度)?$",
            r"^[一二三四五六七八九十]+年(?:度)?(?:[（(]\d{4}年[）)])?$",
            r"^第[一二三四五六七八九十]+年(?:度)?(?:[（(]\d{4}年[）)])?$",
            r"^阶段[一二三四五六七八九十\d]+$",
        ],
        "项目组织实施机制": [
            r"^项目组织管理$",
            r"^组织管理$",
            r"^协调机制$",
            r"^实施机制$",
        ],
    }
    COVER_PAGE_MARKERS = (
        "项目申报书",
        "项目名称",
        "申报单位",
        "项目负责人",
        "河北省科学技术厅制",
    )
    INSTRUCTION_PAGE_MARKERS = (
        "填报说明",
        "项目申报书分为",
        "实事求是、准确完整",
    )

    async def parse(self, file_path: str, source_name: str = "") -> Dict[str, Any]:
        """解析文档并输出统一结构

        Args:
            file_path: 文件路径
            source_name: 展示用文件名

        Returns:
            包含 sections/page_chunks/meta 的字典
        """
        page_texts, page_estimated = await self._extract_pages(file_path)
        cleaned_pages = [self._clean_text(text) for text in page_texts if self._clean_text(text)]
        if not cleaned_pages:
            raise ValueError("PARSE_ERROR: 文档内容为空或无法提取有效文本")

        full_text = "\n".join(cleaned_pages)
        sections = self._extract_sections(full_text)
        resolved_name = source_name or os.path.basename(file_path)
        page_chunks = self._build_page_chunks(cleaned_pages, sections, resolved_name)

        return {
            "sections": sections,
            "page_chunks": page_chunks,
            "meta": {
                "file_name": resolved_name,
                "file_path": file_path,
                "parser_version": "v2",
                "parsed_at": datetime.now().isoformat(),
                "page_estimated": page_estimated,
                "page_count": len(cleaned_pages),
            },
        }

    async def _extract_pages(self, file_path: str) -> tuple[List[str], bool]:
        """按页提取文档文本"""
        lower = file_path.lower()
        if lower.endswith(".doc"):
            raise ValueError("不支持的文件类型: doc，请先转换为 docx 或 pdf")
        file_type = detect_file_type(file_path)
        if file_type not in ("pdf", "docx"):
            raise ValueError(f"不支持的文件类型: {file_path}")

        with open(file_path, "rb") as f:
            file_data = f.read()

        parser = get_parser(file_type)
        parse_result = await parser.parse(file_data)
        return self._convert_parse_result_to_pages(parse_result, file_type)

    def _convert_parse_result_to_pages(
        self,
        parse_result: ParseResult,
        file_type: str,
    ) -> tuple[List[str], bool]:
        """将通用解析结果转换为按页文本"""
        text_blocks = parse_result.content.text_blocks
        if not text_blocks:
            return [], file_type == "docx"

        if file_type == "pdf":
            return self._build_pdf_pages(text_blocks), False

        return self._build_docx_pages(text_blocks), True

    def _build_pdf_pages(self, text_blocks: List[Any]) -> List[str]:
        """根据通用 PDF 文本块还原页文本"""
        pages: Dict[int, List[tuple[float, float, str]]] = {}

        for block in text_blocks:
            text = self._clean_text(block.text)
            if not text:
                continue
            pages.setdefault(block.page, []).append((block.bbox.y, block.bbox.x, text))

        page_texts: List[str] = []
        for page_index in sorted(pages):
            ordered_blocks = sorted(pages[page_index], key=lambda item: (item[0], item[1]))
            page_texts.append("\n".join(item[2] for item in ordered_blocks))

        return page_texts

    def _build_docx_pages(self, text_blocks: List[Any]) -> List[str]:
        """根据通用 DOCX 文本块做近似分页"""
        pages: List[str] = []
        current_lines: List[str] = []
        current_chars = 0

        for block in text_blocks:
            text = self._clean_text(block.text)
            if not text:
                continue

            current_lines.append(text)
            current_chars += len(text)

            if current_chars >= self.DOCX_PAGE_CHARS:
                pages.append("\n".join(current_lines))
                current_lines = []
                current_chars = 0

        if current_lines:
            pages.append("\n".join(current_lines))

        return pages

    def _extract_sections(self, text: str) -> Dict[str, str]:
        """提取章节文本"""
        sections: Dict[str, str] = {}
        lines = text.split("\n")

        current_section = "概述"
        current_content: List[str] = []

        for line in lines:
            normalized_line = line.strip()
            if not normalized_line:
                continue
            if self._is_noise_line(normalized_line):
                continue

            if current_section != "附件" and self._is_section_title(normalized_line):
                normalized_title = self._normalize_section_name(normalized_line)
                if not self._should_start_new_section(current_section, normalized_line, normalized_title):
                    current_content.append(normalized_line)
                    continue
                if current_content:
                    merged = "\n".join(current_content).strip()
                    if merged:
                        existing = sections.get(current_section, "")
                        sections[current_section] = (
                            f"{existing}\n{merged}".strip() if existing else merged
                        )
                current_section = normalized_title
                current_content = []
                continue

            current_content.append(normalized_line)

        if current_content:
            merged = "\n".join(current_content).strip()
            if merged:
                existing = sections.get(current_section, "")
                sections[current_section] = f"{existing}\n{merged}".strip() if existing else merged

        return sections

    def _is_section_title(self, line: str) -> bool:
        """判断是否为章节标题"""
        if len(line) > 32:
            return False
        if "|" in line:
            return False
        if any(mark in line for mark in ("。", "；", ";", "？", "！", "，", ",")):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?(?:\s*[人万元%]+)?", line):
            return False
        normalized = self._normalize_section_name(line)
        if not normalized:
            return False
        if len(normalized) <= 1:
            return False
        if normalized in self.GENERIC_FRAGMENT_TITLES:
            return False
        if normalized in self.SECTION_ALIASES:
            return True
        if any(normalized == alias for aliases in self.SECTION_ALIASES.values() for alias in aliases):
            return True
        if any(re.match(pattern, line) for pattern in self.TITLE_REJECT_PATTERNS):
            return False
        if any(re.match(pattern, normalized) for pattern in self.TITLE_REJECT_PATTERNS):
            return False
        if self._is_budget_detail_title(line, normalized):
            return False
        if normalized.lower() in self.INVALID_SECTION_TITLES:
            return False
        if re.fullmatch(r"(?:附件目录|实施期目标|总体目标|绩效指标)", normalized):
            return False
        if re.fullmatch(r"[0-9A-Za-z%.\-_/]+", normalized):
            return False
        for pattern in self.SECTION_PATTERNS:
            if re.match(pattern, line):
                return True
        return False

    def _should_start_new_section(self, current_section: str, raw_title: str, normalized_title: str) -> bool:
        """判断当前标题是否应该真的切出新章节"""
        if normalized_title == "概述":
            return False
        if current_section == "附件":
            return False
        if normalized_title in self.GENERIC_FRAGMENT_TITLES:
            return False
        if self._is_budget_context(current_section) and self._is_budget_detail_title(raw_title, normalized_title):
            return False
        if self._is_container_child_section(current_section, raw_title, normalized_title):
            return False
        return True

    def _is_budget_context(self, section_name: str) -> bool:
        """判断是否已进入预算相关章节"""
        return section_name in self.BUDGET_SECTION_NAMES

    def _is_budget_detail_title(self, raw_title: str, normalized_title: str) -> bool:
        """过滤预算区明细行，避免被误切成章节"""
        compact_title = re.sub(r"\s+", "", raw_title)
        normalized = re.sub(r"^[、，]+", "", normalized_title.strip())
        if normalized in self.BUDGET_DETAIL_TITLES:
            return True
        if "万元" in compact_title and re.search(
            r"(?:费用|设备费|业务费|劳务费|材料费|测试化验加工费|燃料动力费|文献|调研费|论文发表费|差旅|会议|国际合作|交流费|知识产权事务费|其他支出|专家咨询)",
            compact_title,
        ):
            return True
        if re.fullmatch(r"(?:设备费|业务费|劳务费|材料费|测试化验加工费|燃料动力费)", normalized):
            return True
        return False

    def _normalize_section_name(self, title: str) -> str:
        """规范化章节名"""
        name = re.sub(r"^第[一二三四五六七八九十]+部分\s*", "", title)
        name = re.sub(r"^[（(][一二三四五六七八九十\d]+[）)]\s*", "", name)
        name = re.sub(r"^[一二三四五六七八九十]+[、\.．\s]*", "", name)
        name = re.sub(r"^\d+(\.\d+)*[、\.．\s]*", "", name)
        name = re.sub(r"^[\-•·]+\s*", "", name)
        name = re.sub(r"[：:\s]+$", "", name).strip()
        name = re.sub(r"^\|\s*", "", name)
        name = re.sub(r"\s+", " ", name)
        if not name:
            return "概述"

        for canonical, aliases in self.SECTION_ALIASES.items():
            for alias in aliases:
                if self._alias_matches(name, alias):
                    return canonical

        return name

    def _is_noise_line(self, line: str) -> bool:
        """判断是否为无意义噪声行"""
        return any(re.match(pattern, line) for pattern in self.NOISE_LINE_PATTERNS)

    def _alias_matches(self, name: str, alias: str) -> bool:
        """更保守的章节别名匹配，避免泛化误归类"""
        if name == alias:
            return True
        if name.endswith(alias) and len(name) <= len(alias) + 6:
            return True
        if alias in name and len(name) <= len(alias) + 4:
            return True
        return len(name) >= 4 and alias.startswith(name) and len(alias) <= len(name) + 2

    def _is_container_child_section(self, current_section: str, raw_title: str, normalized_title: str) -> bool:
        """判断当前标题是否应归入上级章节正文"""
        patterns = self.CONTAINER_SECTION_CHILD_PATTERNS.get(current_section)
        if not patterns:
            return False
        candidates = (raw_title.strip(), normalized_title.strip())
        return any(re.fullmatch(pattern, candidate) for pattern in patterns for candidate in candidates if candidate)

    def _build_page_chunks(
        self,
        page_texts: List[str],
        sections: Dict[str, str],
        file_name: str,
    ) -> List[Dict[str, Any]]:
        """按章节上下文构建页码切片"""
        chunks: List[Dict[str, Any]] = []
        chunk_id = 1
        current_section = "概述"

        for page_num, page_text in enumerate(page_texts, start=1):
            override_section = self._detect_page_override_section(page_text)
            if override_section:
                page_blocks = [(override_section, self._clean_text(page_text))]
                current_section = override_section
            else:
                page_blocks, current_section = self._split_page_into_section_blocks(
                    page_text=page_text,
                    current_section=current_section,
                )
            if not page_blocks:
                page_blocks = [(current_section, self._clean_text(page_text))]

            for section_name, block_text in page_blocks:
                for part in self._split_text(block_text, self.CHUNK_MAX_CHARS):
                    clean_part = self._clean_text(part)
                    if not clean_part:
                        continue
                    resolved_section = self._resolve_chunk_section(
                        chunk_text=clean_part,
                        preferred_section=section_name,
                        sections=sections,
                    )
                    chunks.append(
                        {
                            "id": chunk_id,
                            "file": file_name,
                            "page": page_num,
                            "section": resolved_section,
                            "text": clean_part,
                        }
                    )
                    chunk_id += 1

        return chunks

    def _detect_page_override_section(self, page_text: str) -> str:
        """识别整页级结构性页面，避免误归入业务章节"""
        normalized = self._clean_text(page_text)
        if not normalized:
            return ""

        if self._looks_like_cover_page(normalized):
            return "项目基本信息"
        if self._looks_like_instruction_page(normalized):
            return "填报说明"
        return ""

    def _split_page_into_section_blocks(
        self,
        page_text: str,
        current_section: str,
    ) -> tuple[List[tuple[str, str]], str]:
        """按页内标题切出章节块，并继承上一页章节上下文"""
        blocks: List[tuple[str, str]] = []
        active_section = current_section
        buffer: List[str] = []

        for raw_line in page_text.split("\n"):
            normalized_line = raw_line.strip()
            if not normalized_line:
                continue
            if self._is_noise_line(normalized_line):
                continue

            if self._is_section_title(normalized_line):
                normalized_title = self._normalize_section_name(normalized_line)
                if self._should_start_new_section(active_section, normalized_line, normalized_title):
                    if buffer:
                        merged = "\n".join(buffer).strip()
                        if merged:
                            blocks.append((active_section, merged))
                    active_section = normalized_title
                    buffer = [normalized_line]
                    continue

            buffer.append(normalized_line)

        if buffer:
            merged = "\n".join(buffer).strip()
            if merged:
                blocks.append((active_section, merged))

        return blocks, active_section

    def _looks_like_cover_page(self, page_text: str) -> bool:
        """判断是否为封面/基本信息页"""
        return sum(1 for marker in self.COVER_PAGE_MARKERS if marker in page_text) >= 4

    def _looks_like_instruction_page(self, page_text: str) -> bool:
        """判断是否为填报说明页"""
        return sum(1 for marker in self.INSTRUCTION_PAGE_MARKERS if marker in page_text) >= 2

    def _resolve_chunk_section(
        self,
        chunk_text: str,
        preferred_section: str,
        sections: Dict[str, str],
    ) -> str:
        """优先使用页内上下文章节，必要时再做轻量纠偏"""
        if preferred_section and preferred_section != "概述":
            return preferred_section

        return self._infer_chunk_section(chunk_text, sections)

    def _infer_chunk_section(self, chunk_text: str, sections: Dict[str, str]) -> str:
        """推断切片所属章节"""
        sample = chunk_text[:120]
        for section_name in sections:
            if section_name in sample:
                return section_name

        score_section = "概述"
        score_value = 0
        for section_name in sections:
            section_keywords = [k for k in re.split(r"[、，,\s]+", section_name) if k]
            score = sum(1 for keyword in section_keywords if keyword and keyword in chunk_text)
            if score > score_value:
                score_value = score
                score_section = section_name

        return score_section

    def _split_text(self, text: str, chunk_size: int) -> List[str]:
        """按段落优先切分文本"""
        normalized = self._clean_text(text)
        if not normalized:
            return []
        if len(normalized) <= chunk_size:
            return [normalized]

        paragraphs = [p.strip() for p in normalized.split("\n") if p.strip()]
        chunks: List[str] = []
        current = ""

        for paragraph in paragraphs:
            if len(paragraph) > chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                for i in range(0, len(paragraph), chunk_size):
                    chunks.append(paragraph[i : i + chunk_size])
                continue

            candidate = f"{current}\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                chunks.append(
                    current
                )
                current = paragraph

        if current:
            chunks.append(current)

        return chunks

    def _clean_text(self, text: str) -> str:
        """清洗文本"""
        compact = re.sub(r"\u00a0", " ", text)
        compact = re.sub(r"\r\n?", "\n", compact)
        compact = re.sub(r"\n{3,}", "\n\n", compact)
        compact = re.sub(r"[\t ]+", " ", compact)
        return compact.strip()
