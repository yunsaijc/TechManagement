"""逻辑自洽报告中的「项目名称」展示：与 debug 列表同一套抽取 + 清洗。"""
from __future__ import annotations

import re

from src.services.logicon.parser import PerfCheckParser

_DISPLAY_NAME_CUT = re.compile(
    r"\[表格|\[表头|专项名称\s*[:：]|项目类别\s*[:：]|所属学科\d*\s*[:：]?|"
    r"申报人\s*[:：]|承担单位\s*[:：]|填报日期|起止年月|项目编号\s*[:：]|归口管理部门",
    re.I,
)

_GRANT_PROGRAM_PREFIX = re.compile(r"^基础研究专项（自然科学基金）\s*[:：]?\s*")


def _strip_grant_program_prefixes(s: str) -> str:
    t = str(s or "").strip()
    for _ in range(4):
        n = _GRANT_PROGRAM_PREFIX.sub("", t, count=1)
        if n == t:
            break
        t = n.strip("：: \t")
    return t


def sanitize_logicon_display_name(raw: str) -> str:
    """把 _extract_project_name 的原始串压成仅适合作列表主标题的短名称。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    s = _strip_grant_program_prefixes(s)
    m = _DISPLAY_NAME_CUT.search(s)
    if m and m.start() >= 4:
        s = s[: m.start()].strip()
    s = s.strip("；，,。:：;、 ")
    if "：" in s:
        tail = s.rsplit("：", 1)[-1].strip()
        bad_head = ("专项", "项目类别", "学科", "申报人", "表格", "承担单位")
        if len(tail) >= 4 and not any(tail.startswith(x) for x in bad_head) and "专项名称" not in tail[:16]:
            s = tail
    s = _strip_grant_program_prefixes(s)
    s = re.sub(r"\s+", "", s)
    if len(s) > 72:
        s = s[:72].rstrip("…，,。;；:：、 ") + "…"
    return s if len(s) >= 4 else ""


def extract_logicon_project_display_name(raw_text: str) -> str:
    """从全文前部抽取项目名称并清洗；失败返回空串。"""
    perf = PerfCheckParser()
    raw = perf._extract_project_name((raw_text or "")[:24000]) or ""
    return sanitize_logicon_display_name(raw)
