"""项目事实编排器

复用 common / review 现有抽取能力，从申报书中提取项目级规则所需事实字段。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from src.common.file_handler import PDFParser


class ProjectFactResolver:
    """从申报书主文件中抽取项目事实字段"""

    def __init__(self):
        self.pdf_parser = PDFParser()

    async def resolve(self, proposal_files: List[Path], applicant_unit: str = "", unit_name: str = "") -> Dict[str, Any]:
        """解析申报书事实"""
        main_file = self._select_main_proposal_file(proposal_files)
        if not main_file:
            return {
                "proposal_main_file": "",
                "proposal_text_excerpt": "",
                "project_info_updates": {
                    "applicant_unit_type": self._infer_applicant_unit_type(applicant_unit or unit_name),
                },
                "cooperation_info": {
                    "cooperation_units": [],
                    "cooperation_regions": [],
                    "has_formal_cooperation_agreement": False,
                    "has_management_recommendation_letter": False,
                },
            }

        text = await self._extract_text(main_file)
        cooperation_units = self._extract_cooperation_units(text)
        project_info_updates = {
            "applicant_unit_type": self._infer_applicant_unit_type(applicant_unit or unit_name),
            "registered_date": self._extract_registered_date(text),
            "fiscal_funding": self._extract_amount(text, ["申请财政资金", "申请省财政资金", "财政资金", "拟申请财政资金"]),
            "self_funding": self._extract_amount(text, ["自筹资金", "单位自筹", "配套资金"]),
            "has_clinical_research": self._contains_any(text, ["临床研究", "临床试验", "伦理审查"]),
            "has_special_industry_requirement": self._contains_any(text, ["安全生产", "特种行业", "行业准入", "生产许可", "经营许可"]),
            "has_biosafety_activity": self._contains_any(text, ["生物安全", "人类遗传资源", "病原微生物", "实验动物"]),
            "has_cooperation_unit": bool(cooperation_units) or self._contains_any(text, ["合作单位", "协作单位", "联合申报"]),
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
        pdf_files = [path for path in proposal_files if path.suffix.lower() == ".pdf"]
        candidates = pdf_files or proposal_files
        return max(candidates, key=lambda path: path.stat().st_size if path.exists() else 0)

    async def _extract_text(self, path: Path) -> str:
        """抽取申报书文本"""
        file_data = path.read_bytes()
        if path.suffix.lower() == ".pdf":
            result = await self.pdf_parser.parse(file_data)
            return "\n".join(block.text for block in result.content.text_blocks if block.text).strip()
        return ""

    def _extract_registered_date(self, text: str) -> str:
        """提取注册时间"""
        patterns = [
            r"(?:注册时间|成立时间|设立时间)[：:\s]*([12]\d{3}[年/-]\d{1,2}[月/-]\d{1,2}日?)",
            r"(?:注册时间|成立时间|设立时间)[：:\s]*([12]\d{3}[./-]\d{1,2}[./-]\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1)
                return value.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
        return ""

    def _extract_amount(self, text: str, labels: List[str]) -> float:
        """提取金额字段"""
        compact = re.sub(r"\s+", "", text)
        for label in labels:
            pattern = rf"{re.escape(label)}[：:]*([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)?"
            match = re.search(pattern, compact)
            if match:
                value = float(match.group(1))
                unit = match.group(2) or ""
                if unit == "元":
                    value = value / 10000.0
                return round(value, 2)
        return 0.0

    def _extract_cooperation_units(self, text: str) -> List[str]:
        """提取合作单位列表"""
        units: List[str] = []
        patterns = [
            r"(?:合作单位|协作单位|联合申报单位)[：:\s]*([^\n。；]{2,120})",
            r"(?:合作单位|协作单位)[\s\S]{0,12}([^\n。；]*公司[^\n。；]*)",
            r"(?:合作单位|协作单位)[\s\S]{0,12}([^\n。；]*(?:大学|学院|研究院|研究所|中心)[^\n。；]*)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                raw = match.group(1).strip()
                parts = re.split(r"[、,，；;和及/]", raw)
                for part in parts:
                    cleaned = part.strip("：:()（） \t")
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

    def _infer_applicant_unit_type(self, unit_name: str) -> str:
        """根据单位名称推断单位类型"""
        text = unit_name or ""
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

    def _looks_like_unit(self, text: str) -> bool:
        """粗判是否像单位名称"""
        if not text or len(text) < 4:
            return False
        keywords = ["公司", "大学", "学院", "研究院", "研究所", "中心", "医院", "实验室", "集团", "学校"]
        return any(keyword in text for keyword in keywords)

    def _contains_any(self, text: str, keywords: List[str]) -> bool:
        """是否包含任一关键词"""
        return any(keyword in text for keyword in keywords)
