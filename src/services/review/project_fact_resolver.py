"""项目事实编排器

复用 common / review 现有抽取能力，从申报书中提取项目级规则所需事实字段。
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from src.common.file_handler import DOCXParser, PDFParser


class ProjectFactResolver:
    """从申报书主文件中抽取项目事实字段"""

    def __init__(self):
        self.pdf_parser = PDFParser()
        self.docx_parser = DOCXParser()

    async def resolve(
        self,
        proposal_files: List[Path],
        applicant_unit: str = "",
        unit_name: str = "",
        project_leader: str = "",
    ) -> Dict[str, Any]:
        """解析申报书事实"""
        main_file = self._select_main_proposal_file(proposal_files)
        preferred_unit_name = unit_name or applicant_unit
        if not main_file:
            return {
                "proposal_main_file": "",
                "proposal_text_excerpt": "",
                "project_info_updates": {
                    "applicant_unit_type": self._infer_applicant_unit_type(preferred_unit_name),
                },
                "cooperation_info": {
                    "cooperation_units": [],
                    "cooperation_unit_types": [],
                    "cooperation_regions": [],
                    "has_formal_cooperation_agreement": False,
                    "has_management_recommendation_letter": False,
                },
            }

        text = await self._extract_text(main_file)
        form_fields = self._extract_form_fields(text)
        cooperation_units = self._extract_cooperation_units(text, form_fields)
        applicant_unit_type = self._infer_applicant_unit_type(
            preferred_unit_name,
            form_fields.get("单位性质", ""),
        )
        project_info_updates = {
            "applicant_unit_type": applicant_unit_type,
            "registered_date": self._extract_registered_date(text, form_fields),
            "project_leader_birth_date": self._extract_project_leader_birth_date(
                main_file,
                text,
                form_fields,
                project_leader,
            ),
            "fiscal_funding": self._extract_budget_amount(text, form_fields, ["申请财政资金", "申请省财政资金", "财政资金", "拟申请财政资金"]),
            "self_funding": self._extract_budget_amount(text, form_fields, ["自筹资金", "单位自筹", "配套资金"]),
            "budget_line_items": self._extract_budget_line_items(text),
            "has_clinical_research": self._extract_boolean_fact(text, form_fields, ["临床研究", "临床试验"], negative_hints=["无", "否"]),
            "has_special_industry_requirement": self._extract_boolean_fact(text, form_fields, ["安全生产", "特种行业", "行业准入", "生产许可", "经营许可"], negative_hints=["无", "否"]),
            "has_biosafety_activity": self._extract_boolean_fact(text, form_fields, ["生物安全", "人类遗传资源", "病原微生物", "实验动物"], negative_hints=["无", "否"]),
            "has_cooperation_unit": self._extract_has_cooperation_unit(text, form_fields, cooperation_units),
        }
        project_info_updates.update(self._extract_performance_metrics(main_file))

        return {
            "proposal_main_file": str(main_file),
            "proposal_text_excerpt": text[:4000],
            "project_info_updates": project_info_updates,
            "cooperation_info": {
                "cooperation_units": cooperation_units,
                "cooperation_unit_types": [self._infer_applicant_unit_type(unit) for unit in cooperation_units],
                "cooperation_regions": self._extract_regions(cooperation_units),
                "has_formal_cooperation_agreement": self._contains_any(text, ["合作协议", "合作合同", "联合申报协议"]),
                "has_management_recommendation_letter": self._contains_any(text, ["推荐函", "推荐意见", "科技管理部门推荐"]),
            },
        }

    def _select_main_proposal_file(self, proposal_files: List[Path]) -> Path | None:
        """选择主申报书文件"""
        if not proposal_files:
            return None
        docx_files = [path for path in proposal_files if path.suffix.lower() == ".docx"]
        if docx_files:
            candidates = docx_files
        else:
            pdf_files = [path for path in proposal_files if path.suffix.lower() == ".pdf"]
            candidates = pdf_files or proposal_files
        return max(candidates, key=lambda path: path.stat().st_size if path.exists() else 0)

    async def _extract_text(self, path: Path) -> str:
        """抽取申报书文本"""
        file_data = path.read_bytes()
        if path.suffix.lower() == ".docx":
            result = await self.docx_parser.parse(file_data)
            return "\n".join(block.text for block in result.content.text_blocks if block.text).strip()
        if path.suffix.lower() == ".pdf":
            result = await self.pdf_parser.parse(file_data)
            return "\n".join(block.text for block in result.content.text_blocks if block.text).strip()
        return ""

    def _extract_form_fields(self, text: str) -> Dict[str, str]:
        """从表格行文本中抽取字段键值"""
        fields: Dict[str, str] = {}
        for line in text.splitlines():
            clean = line.strip()
            if not clean.startswith("[表格行"):
                continue
            if "]" in clean:
                clean = clean.split("]", 1)[1].strip()
            raw_parts = [part.strip() for part in clean.split("|") if part.strip()]
            parts = []
            for part in raw_parts:
                normalized = self._normalize_field_token(part)
                if normalized:
                    parts.append(normalized)
            if not parts:
                continue
            if self._looks_like_budget_row(parts):
                self._capture_budget_row_fields(fields, parts)
                continue
            for index in range(len(parts) - 1):
                key = parts[index]
                value = parts[index + 1]
                if self._looks_like_field_key(key) and value and not self._looks_like_field_key(value):
                    fields.setdefault(key, value)
        return fields

    def _extract_registered_date(self, text: str, form_fields: Dict[str, str]) -> str:
        """提取注册时间"""
        for key, value in form_fields.items():
            if "注册时间" in key:
                normalized = self._normalize_date(value)
                if normalized:
                    return normalized
        patterns = [
            r"(?:注册时间|成立时间|设立时间)(?:\||：|:|\s)*([12]\d{3}[年/-]\d{1,2}[月/-]\d{1,2}日?)",
            r"(?:注册时间|成立时间|设立时间)(?:\||：|:|\s)*([12]\d{3}[./-]\d{1,2}[./-]\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return self._normalize_date(match.group(1))
        return ""

    def _extract_budget_amount(self, text: str, form_fields: Dict[str, str], labels: List[str]) -> float:
        """提取预算金额，优先使用表格字段"""
        for key, value in form_fields.items():
            if any(label in key for label in labels):
                amount = self._parse_amount(value)
                if amount > 0:
                    return amount

        compact = re.sub(r"\s+", "", text)
        for label in labels:
            pattern = rf"{re.escape(label)}[：:]*([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)?"
            match = re.search(pattern, compact)
            if match:
                amount = self._parse_amount("".join(match.groups(default="")))
                if amount > 0:
                    return amount
        for label in labels:
            pattern = rf"(?:一|二|三|四|五|六|七|八|九|十)?[、.]?{re.escape(label)}(?:\||：|:|\s)*([0-9]+(?:\.[0-9]+)?)"
            match = re.search(pattern, compact)
            if match:
                return self._parse_amount(match.group(1))
        return 0.0

    def _extract_project_leader_birth_date(
        self,
        path: Path,
        text: str,
        form_fields: Dict[str, str],
        project_leader: str = "",
    ) -> str:
        """提取项目负责人出生日期"""
        if path.suffix.lower() == ".docx":
            from_docx = self._extract_project_leader_birth_date_from_docx(path, project_leader)
            if from_docx:
                return from_docx

        for key, value in form_fields.items():
            if any(token in key for token in ["出生日期", "出生年月", "负责人出生日期", "负责人出生年月"]):
                normalized = self._normalize_date(value)
                if normalized:
                    return normalized

        patterns = [
            r"(?:项目负责人|负责人)[^\n]{0,80}?(?:出生日期|出生年月)(?:\||：|:|\s)*([12]\d{3}[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?)",
            r"(?:出生日期|出生年月)(?:\||：|:|\s)*([12]\d{3}[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?)",
            r"(?:身份证号|身份证号码)(?:\||：|:|\s)*([1-9]\d{5}(19|20)\d{2}\d{2}\d{2}\d{3}[\dXx])",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = match.group(1)
            if len(value) == 18 and value[:6].isdigit():
                return f"{value[6:10]}-{value[10:12]}-{value[12:14]}"
            normalized = self._normalize_date(value)
            if normalized:
                return normalized
        return ""

    def _extract_project_leader_birth_date_from_docx(self, path: Path, project_leader: str = "") -> str:
        """从 docx 成员表提取项目负责人出生日期（优先取身份证）"""
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        id_pattern = re.compile(
            r"(?<!\d)([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx])(?!\d)"
        )
        try:
            with zipfile.ZipFile(path) as archive:
                xml_bytes = archive.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
        except Exception:
            return ""
        body = root.find("w:body", ns)
        if body is None:
            return ""

        normalized_leader = re.sub(r"\s+", "", project_leader or "")

        for table in body.findall("w:tbl", ns):
            rows: List[List[str]] = []
            for tr in table.findall("w:tr", ns):
                row = []
                for tc in tr.findall("w:tc", ns):
                    cell = "".join(node.text or "" for node in tc.findall(".//w:t", ns)).strip()
                    row.append(re.sub(r"\s+", "", cell))
                if row:
                    rows.append(row)
            if len(rows) < 2:
                continue

            header = rows[0]
            if "证件号码" not in "".join(header):
                continue
            name_idx = self._find_header_index(header, ["姓名"])
            id_idx = self._find_header_index(header, ["证件号码", "身份证号", "身份证号码"])
            role_idx = self._find_header_index(header, ["分工", "角色", "承担任务"])
            if id_idx < 0:
                continue

            leader_first: str = ""
            for row in rows[1:]:
                if id_idx >= len(row):
                    continue
                id_match = id_pattern.search(row[id_idx] or "")
                if not id_match:
                    continue
                candidate_birth = f"{id_match.group(1)[6:10]}-{id_match.group(1)[10:12]}-{id_match.group(1)[12:14]}"

                role_text = row[role_idx] if role_idx >= 0 and role_idx < len(row) else ""
                name_text = row[name_idx] if name_idx >= 0 and name_idx < len(row) else ""
                normalized_name = re.sub(r"\s+", "", name_text)

                if "项目负责人" in role_text:
                    return candidate_birth
                if normalized_leader and normalized_name and normalized_name == normalized_leader:
                    return candidate_birth
                if not leader_first:
                    leader_first = candidate_birth
            if leader_first:
                return leader_first
        return ""

    def _find_header_index(self, headers: List[str], candidates: List[str]) -> int:
        """查找表头索引"""
        for idx, text in enumerate(headers):
            if any(candidate in text for candidate in candidates):
                return idx
        return -1

    def _extract_budget_line_items(self, text: str) -> List[str]:
        """抽取预算相关明细行，供预算禁列项检查使用"""
        keywords = [
            "预算", "经费", "支出", "费用", "科目", "直接费用", "间接经费", "绩效支出",
            "设备费", "材料费", "测试化验加工费", "燃料动力费", "差旅费", "会议费",
            "国际合作与交流费", "出版", "文献", "信息传播", "知识产权事务费",
            "劳务费", "专家咨询费", "其他支出", "罚款", "捐款", "赞助", "投资", "偿还债务",
        ]
        lines: List[str] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            normalized = re.sub(r"\s+", "", line)
            if any(keyword in normalized for keyword in keywords):
                clean = line[:240]
                if clean not in seen:
                    seen.add(clean)
                    lines.append(clean)
        return lines[:80]

    def _extract_performance_metrics(self, path: Path) -> Dict[str, Any]:
        """抽取绩效指标信息"""
        if path.suffix.lower() != ".docx" or not path.exists():
            return {
                "performance_metric_count": 0,
                "performance_first_year_ratio": None,
                "performance_metric_rows": [],
            }
        try:
            rows = self._extract_performance_rows_from_docx(path)
        except Exception:
            rows = []
        if not rows:
            return {
                "performance_metric_count": 0,
                "performance_first_year_ratio": None,
                "performance_metric_rows": [],
            }

        comparable = [row for row in rows if row.get("total_value") is not None and row.get("first_year_value") is not None]
        total_sum = round(sum(float(row["total_value"]) for row in comparable), 4) if comparable else 0.0
        first_year_sum = round(sum(float(row["first_year_value"]) for row in comparable), 4) if comparable else 0.0
        ratio = round(first_year_sum / total_sum, 4) if total_sum > 0 else None
        return {
            "performance_metric_count": len(rows),
            "performance_first_year_ratio": ratio,
            "performance_metric_rows": rows[:20],
        }

    def _extract_performance_rows_from_docx(self, path: Path) -> List[Dict[str, Any]]:
        """从 docx 中抽取预期绩效目标表的指标行"""
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        body = root.find("w:body", ns)
        if body is None:
            return []
        children = list(body)
        table = None
        for index, child in enumerate(children):
            if not child.tag.endswith("}p"):
                continue
            text = "".join(node.text or "" for node in child.findall(".//w:t", ns)).strip()
            if "预期绩效目标" in text:
                if index + 1 < len(children) and children[index + 1].tag.endswith("}tbl"):
                    table = children[index + 1]
                    break
        if table is None:
            return []

        raw_rows: List[List[str]] = []
        for tr in table.findall("w:tr", ns):
            row = []
            for tc in tr.findall("w:tc", ns):
                cell = "".join(node.text or "" for node in tc.findall(".//w:t", ns)).strip()
                row.append(re.sub(r"\s+", "", cell))
            raw_rows.append(row)

        header_index = -1
        for index, row in enumerate(raw_rows):
            if "绩效指标" in "".join(row) and "指标值" in "".join(row):
                header_index = index
                break
        if header_index < 0:
            return []

        performance_rows: List[Dict[str, Any]] = []
        for row in raw_rows[header_index + 1:]:
            if len(row) < 6:
                continue
            total_value = self._parse_optional_number(row[4])
            first_year_value = self._parse_optional_number(row[5]) if len(row) > 5 else None
            metric_name = ""
            for candidate in [row[3], row[2], row[1], row[0]]:
                if candidate and candidate not in {"绩效指标", "一级指标", "二级指标", "三级指标", "指标值"}:
                    metric_name = candidate
                    break
            if not metric_name or total_value is None:
                continue
            performance_rows.append(
                {
                    "metric_name": metric_name,
                    "total_value": total_value,
                    "first_year_value": first_year_value,
                    "raw_row": row,
                }
            )
        return performance_rows

    def _extract_cooperation_units(self, text: str, form_fields: Dict[str, str]) -> List[str]:
        """提取合作单位列表"""
        units: List[str] = []
        explicit_unit = self._extract_cover_field(text, ["合作单位", "协作单位", "联合申报单位"])
        if explicit_unit and explicit_unit not in {"无", "否", "/"}:
            for part in re.split(r"[、,，；;和及/]", explicit_unit):
                cleaned = self._clean_unit_name(part)
                if self._looks_like_unit(cleaned) and cleaned not in units:
                    units.append(cleaned)

        for key, value in form_fields.items():
            if key in {"合作单位", "协作单位", "联合申报单位"}:
                for part in re.split(r"[、,，；;和及/]", value):
                    cleaned = self._clean_unit_name(part)
                    if self._looks_like_unit(cleaned) and cleaned not in units:
                        units.append(cleaned)

        section_match = re.search(r"合作单位概况([\s\S]{0,400})", text)
        if section_match:
            section_text = section_match.group(1)
            for match in re.finditer(r"\[表格行\d+\]\s*([^\|\n]{4,80}?)\s*\|\s*(?:中国|[^\|\n]{1,20})\s*\|", section_text):
                cleaned = self._clean_unit_name(match.group(1))
                if self._looks_like_unit(cleaned) and cleaned not in units:
                    units.append(cleaned)
        return units[:10]

    def _extract_regions(self, units: List[str]) -> List[str]:
        """从单位名称中抽取粗粒度地区"""
        region_tokens = [
            "北京", "天津", "河北", "新疆", "西藏", "巴音郭楞", "铁门关", "阿里",
            "石家庄", "唐山", "承德", "秦皇岛", "邯郸", "保定", "沧州",
        ]
        regions: List[str] = []
        for unit in units:
            for token in region_tokens:
                if token in unit and token not in regions:
                    regions.append(token)
        return regions

    def _infer_applicant_unit_type(self, unit_name: str, unit_nature: str = "") -> str:
        """根据单位名称推断单位类型"""
        text = f"{unit_name} {unit_nature}".strip()
        if not text:
            return ""
        if any(token in text for token in ["有限公司", "有限责任公司", "股份", "集团", "企业"]):
            return "enterprise"
        if any(token in text for token in ["大学", "学院", "学校"]):
            return "university"
        if any(token in text for token in ["研究院", "研究所", "科学院"]):
            return "research_institute"
        if "医院" in text:
            return "hospital"
        return "institution"

    def _extract_boolean_fact(
        self,
        text: str,
        form_fields: Dict[str, str],
        positive_hints: List[str],
        negative_hints: List[str] | None = None,
    ) -> bool:
        """提取布尔事实，优先使用明确的表单字段或勾选项"""
        negative_hints = negative_hints or []
        for key, value in form_fields.items():
            if any(hint in key for hint in positive_hints):
                normalized = re.sub(r"\s+", "", value)
                if any(token in normalized for token in ["是", "有"]):
                    return True
                if any(token in normalized for token in ["否", "无"]):
                    return False

        checkbox_value = self._extract_checkbox_value(text, positive_hints)
        if checkbox_value is not None:
            return checkbox_value

        compact_text = re.sub(r"\s+", "", text)
        for hint in positive_hints:
            explicit_negative = [
                f"不涉及{hint}",
                f"未开展{hint}",
                f"无{hint}",
            ] + [f"{token}{hint}" for token in negative_hints]
            if any(token in compact_text for token in explicit_negative):
                return False
        return False

    def _extract_has_cooperation_unit(self, text: str, form_fields: Dict[str, str], cooperation_units: List[str]) -> bool:
        """提取是否存在合作单位"""
        explicit_unit = self._extract_cover_field(text, ["合作单位", "协作单位", "联合申报单位"])
        normalized_cover = re.sub(r"\s+", "", explicit_unit)
        if normalized_cover in {"无", "否", "/", ""}:
            return False
        if normalized_cover:
            return True
        if cooperation_units:
            return True
        for key, value in form_fields.items():
            if key in {"合作单位", "协作单位", "联合申报单位"}:
                normalized = re.sub(r"\s+", "", value)
                if normalized in {"无", "否", "/", "无无"}:
                    return False
                if normalized:
                    return True
        return False

    def _looks_like_unit(self, text: str) -> bool:
        """粗判是否像单位名称"""
        if not text or len(text) < 4:
            return False
        keywords = ["公司", "大学", "学院", "研究院", "研究所", "中心", "医院", "实验室", "集团", "学校"]
        return any(keyword in text for keyword in keywords)

    def _contains_any(self, text: str, keywords: List[str]) -> bool:
        """是否包含任一关键词"""
        return any(keyword in text for keyword in keywords)

    def _extract_cover_field(self, text: str, field_names: List[str]) -> str:
        """提取封面字段"""
        for field_name in field_names:
            pattern = rf"{self._build_spaced_text_pattern(field_name)}[：:\s]*([^\n]+)"
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ""

    def _clean_unit_name(self, value: str) -> str:
        """清洗单位名称"""
        text = re.sub(r"\s+", "", value)
        text = re.sub(r"^[项目本目该合协联申报单位概况：:]+", "", text)
        text = re.sub(r"^(单位名称|联系人|所属地区|国别|单位地址|单位性质)", "", text)
        text = re.sub(r"^(作单位|合作单位|协作单位|联合申报单位)", "", text)
        text = text.strip("：:()（）[]【】,，;；")
        return text

    def _normalize_field_token(self, value: str) -> str:
        """归一化表格 token"""
        text = re.sub(r"\s+", "", value)
        return text.strip("|：:;；")

    def _looks_like_field_key(self, value: str) -> bool:
        """判断 token 是否像字段名"""
        if not value:
            return False
        compact = re.sub(r"\s+", "", value)
        if re.fullmatch(r"[12]\d{3}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", compact):
            return False
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%?", value):
            return False
        if any(token in value for token in ["万元", "亿元", "元", "%"]):
            return False
        if re.fullmatch(r"[0-9A-Za-z._/-]{6,}", compact):
            return False
        known_keys = [
            "项目名称", "所属专项", "指南代码", "科技活动类型", "应用行业", "技术领域",
            "所属学科1", "所属学科2", "关键词", "单位名称", "法定代表人", "单位地址",
            "注册（纳税）地区", "统一社会信用代码", "项目负责人", "项目联系人", "办公电话",
            "E-mail", "开户名称", "开户银行行号", "开户银行", "帐号", "职工总数", "技术人员数",
            "中高级技术人员数", "是否为省级以上高新技术企业", "是否为省级以上科技型中小企业",
            "所属园区", "上年度单位研发投入", "上年度单位销售收入", "上年度单位研发投入/销售收入",
            "注册资本", "注册时间", "拥有专利数量", "单位性质", "单位规模", "其它特征",
            "合作单位", "协作单位", "联合申报单位", "国别", "所属地区", "联系人", "手机",
            "申报单位概况", "合作单位概况",
        ]
        if value in known_keys:
            return True
        if re.search(r"[，。；;,.()（）]", value):
            return False
        digit_count = sum(1 for char in compact if char.isdigit())
        if digit_count and digit_count >= max(4, len(compact) // 2):
            return False
        return len(compact) <= 12

    def _looks_like_budget_row(self, parts: List[str]) -> bool:
        """判断是否为预算值行"""
        return len(parts) >= 2 and sum(1 for part in parts if "万元" in part or "%" in part) >= 2

    def _capture_budget_row_fields(self, fields: Dict[str, str], parts: List[str]) -> None:
        """捕获预算相关行"""
        amounts = [part for part in parts if "万元" in part or "%" in part]
        if len(amounts) >= 1:
            fields.setdefault("上年度单位研发投入", amounts[0])
        if len(amounts) >= 2:
            fields.setdefault("上年度单位销售收入", amounts[1])
        if len(amounts) >= 3:
            fields.setdefault("上年度单位研发投入/销售收入", amounts[2])

    def _normalize_date(self, value: str) -> str:
        """标准化日期文本"""
        text = str(value).strip()
        text = text.replace("年", "-").replace("月", "-").replace("日", "")
        text = text.replace("/", "-").replace(".", "-")
        return re.sub(r"-{2,}", "-", text)

    def _build_spaced_text_pattern(self, text: str) -> str:
        """构造允许字符间空白的匹配模式"""
        return r"\s*".join(re.escape(char) for char in text if char.strip())

    def _extract_checkbox_value(self, text: str, positive_hints: List[str]) -> bool | None:
        """解析“是/否”勾选项"""
        mark_tokens = "Rr√☑✔■●"
        plain_text = re.sub(r"[ \t]+", " ", text)
        for hint in positive_hints:
            pattern = rf"{self._build_spaced_text_pattern(hint)}(.{{0,40}})"
            match = re.search(pattern, plain_text)
            if not match:
                continue
            snippet = match.group(1)
            negative_match = re.search(rf"[{mark_tokens}]\s*否", snippet)
            if negative_match:
                return False
            positive_match = re.search(rf"[{mark_tokens}]\s*是", snippet)
            if positive_match:
                return True
            if "是" in snippet and "否" in snippet:
                if snippet.index("否") < snippet.index("是"):
                    return False
        return None

    def _parse_amount(self, raw: str) -> float:
        """解析金额"""
        text = str(raw).replace(",", "").replace("，", "").strip()
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return 0.0
        value = float(match.group(1))
        if "元" in text and "万元" not in text and "万" not in text:
            value = value / 10000.0
        return round(value, 2)

    def _parse_optional_number(self, raw: str) -> float | None:
        """解析可选数字"""
        text = str(raw or "").replace(",", "").replace("，", "").strip()
        match = re.search(r"(-?[0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return None
        return float(match.group(1))
