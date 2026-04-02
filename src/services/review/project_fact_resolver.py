"""项目事实编排器

复用 common / review 现有抽取能力，从申报书中提取项目级规则所需事实字段。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from src.common.file_handler import DOCXParser, PDFParser


class ProjectFactResolver:
    """从申报书主文件中抽取项目事实字段"""

    def __init__(self):
        self.pdf_parser = PDFParser()
        self.docx_parser = DOCXParser()

    async def resolve(self, proposal_files: List[Path], applicant_unit: str = "", unit_name: str = "") -> Dict[str, Any]:
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
            "fiscal_funding": self._extract_budget_amount(text, form_fields, ["申请财政资金", "申请省财政资金", "财政资金", "拟申请财政资金"]),
            "self_funding": self._extract_budget_amount(text, form_fields, ["自筹资金", "单位自筹", "配套资金"]),
            "has_clinical_research": self._extract_boolean_fact(text, form_fields, ["临床研究", "临床试验"], negative_hints=["无", "否"]),
            "has_special_industry_requirement": self._extract_boolean_fact(text, form_fields, ["安全生产", "特种行业", "行业准入", "生产许可", "经营许可"], negative_hints=["无", "否"]),
            "has_biosafety_activity": self._extract_boolean_fact(text, form_fields, ["生物安全", "人类遗传资源", "病原微生物", "实验动物"], negative_hints=["无", "否"]),
            "has_cooperation_unit": self._extract_has_cooperation_unit(text, form_fields, cooperation_units),
        }

        return {
            "proposal_main_file": str(main_file),
            "proposal_text_excerpt": text[:4000],
            "project_info_updates": project_info_updates,
            "cooperation_info": {
                "cooperation_units": cooperation_units,
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
