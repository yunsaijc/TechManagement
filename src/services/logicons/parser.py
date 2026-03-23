"""逻辑自洽服务文档解析器"""
import re
from dataclasses import dataclass
from typing import List


@dataclass
class SectionChunk:
    """章节切片"""

    section: str
    line_no: int
    text: str


class LogiConsParser:
    """对长文档文本做章节化切分"""

    _SECTION_HEADING = re.compile(
        r"^(第[一二三四五六七八九十百0-9]+[章节]|[一二三四五六七八九十]+[、.]|\d+[、.])"
    )

    def parse_text(self, text: str) -> List[SectionChunk]:
        """将原文按行切分并推断章节

        Args:
            text: 文档全文文本

        Returns:
            章节切片列表
        """
        chunks: List[SectionChunk] = []
        current_section = "未命名章节"

        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue

            if self._looks_like_heading(line):
                current_section = line[:60]

            chunks.append(SectionChunk(section=current_section, line_no=line_no, text=line))

        return chunks

    def _looks_like_heading(self, line: str) -> bool:
        if len(line) > 80:
            return False
        if self._SECTION_HEADING.search(line):
            return True
        if any(k in line for k in ["项目基本信息", "进度安排", "资金预算", "经费预算", "考核指标"]):
            return True
        return False
