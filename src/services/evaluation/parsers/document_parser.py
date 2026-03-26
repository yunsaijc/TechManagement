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

    SECTION_PATTERNS = [
        r"^[一二三四五六七八九十]+[、\.．\s]",
        r"^\d+[、\.．\s]",
        r"^\d+\.\d+[、\.．\s]",
        r"^(技术路线|研究方案|实施方案|创新点|研究内容|项目团队|人员分工|预期成果|考核指标|预期效益|社会效益|经济效益|风险分析|风险控制|进度安排|实施计划|政策依据|经费预算|伦理审查|预算说明|工作计划|研究计划|研究目标|项目目标)[：:\s]",
    ]

    SECTION_ALIASES: Dict[str, List[str]] = {
        "研究目标": ["研究目标", "项目目标", "总体目标", "目标"],
        "创新点": ["创新点", "创新性", "技术创新", "方法创新"],
        "技术路线": ["技术路线", "研究方案", "实施方案", "技术方案"],
        "项目团队": ["项目团队", "人员分工", "团队", "团队能力"],
        "预期成果": ["预期成果", "考核指标", "成果"],
        "社会效益": ["社会效益", "社会价值"],
        "经济效益": ["经济效益", "产业化", "应用前景"],
        "风险控制": ["风险分析", "风险控制", "风险管理"],
        "进度安排": ["进度安排", "实施计划", "工作计划"],
        "合规性": ["政策依据", "伦理审查", "经费预算"],
    }

    DOCX_PAGE_CHARS = 1800
    CHUNK_MAX_CHARS = 1200

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

            if self._is_section_title(normalized_line):
                if current_content:
                    merged = "\n".join(current_content).strip()
                    if merged:
                        existing = sections.get(current_section, "")
                        sections[current_section] = (
                            f"{existing}\n{merged}".strip() if existing else merged
                        )
                current_section = self._normalize_section_name(normalized_line)
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
        if any(mark in line for mark in ("。", "；", ";", "？", "！", "，", ",")):
            return False
        for pattern in self.SECTION_PATTERNS:
            if re.match(pattern, line):
                return True
        return False

    def _normalize_section_name(self, title: str) -> str:
        """规范化章节名"""
        name = re.sub(r"^[一二三四五六七八九十]+[、\.．\s]*", "", title)
        name = re.sub(r"^\d+(\.\d+)*[、\.．\s]*", "", name)
        name = re.sub(r"[：:\s]+$", "", name).strip()
        if not name:
            return "概述"

        for canonical, aliases in self.SECTION_ALIASES.items():
            for alias in aliases:
                if alias in name or name in alias:
                    return canonical

        return name

    def _build_page_chunks(
        self,
        page_texts: List[str],
        sections: Dict[str, str],
        file_name: str,
    ) -> List[Dict[str, Any]]:
        """构建页码切片"""
        chunks: List[Dict[str, Any]] = []
        chunk_id = 1

        for page_num, page_text in enumerate(page_texts, start=1):
            page_parts = self._split_text(page_text, self.CHUNK_MAX_CHARS)
            for part in page_parts:
                clean_part = self._clean_text(part)
                if not clean_part:
                    continue
                section_name = self._infer_chunk_section(clean_part, sections)
                chunks.append(
                    {
                        "id": chunk_id,
                        "file": file_name,
                        "page": page_num,
                        "section": section_name,
                        "text": clean_part,
                    }
                )
                chunk_id += 1

        return chunks

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
                chunks.append(current)
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
