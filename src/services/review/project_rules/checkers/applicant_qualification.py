"""申报单位资格检查"""
from __future__ import annotations

import re
from typing import List

from src.common.models import CheckResult, CheckStatus
from src.services.review.project_rules.checkers._attachment_kinds import collect_specific_doc_kinds
from src.services.review.project_rules.base import BaseProjectRule
from src.services.review.project_rules.registry import ProjectRuleRegistry


@ProjectRuleRegistry.register
class ApplicantQualificationCheckRule(BaseProjectRule):
    """检查申报单位主体资格和行政机关限制"""

    name = "applicant_qualification_check"
    description = "检查申报单位是否具备法人主体资格，且申报/合作单位不属于行政机关"
    priority = 93

    async def check(self, context):
        project = context.project_info
        cooperation = context.cooperation_info
        doc_kinds = collect_specific_doc_kinds(context.attachments)
        applicant_name = str(project.applicant_unit or "").strip()
        applicant_region = str(project.applicant_region or "").strip()
        credit_code = str(project.applicant_credit_code or "").strip()
        independent_legal_person = project.applicant_is_independent_legal_person

        government_units: List[str] = []
        if project.applicant_is_government_agency or self._is_government_agency(applicant_name):
            government_units.append(applicant_name or "申报单位")
        for unit in (cooperation.cooperation_units if cooperation else []):
            if self._is_government_agency(unit):
                government_units.append(unit)

        if government_units:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="申报单位或合作单位存在行政机关主体，不符合申报资格要求",
                evidence={
                    "government_units": government_units,
                    "applicant_unit": applicant_name,
                    "cooperation_units": (cooperation.cooperation_units if cooperation else []),
                },
            )

        if independent_legal_person is False:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="申报单位未满足独立法人资格要求",
                evidence={
                    "applicant_unit": applicant_name,
                    "applicant_is_independent_legal_person": False,
                },
            )

        explicit_non_hebei = self._is_explicit_non_hebei(applicant_region)
        if explicit_non_hebei:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="申报单位注册地区不在河北省行政区域内",
                evidence={
                    "applicant_unit": applicant_name,
                    "applicant_region": applicant_region,
                },
            )

        legal_person_evidence = {
            "credit_code": credit_code,
            "has_business_license_attachment": "business_license" in doc_kinds,
            "applicant_is_independent_legal_person": independent_legal_person,
        }
        if not credit_code and independent_legal_person is None and "business_license" not in doc_kinds:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="未发现申报资格红线问题（未识别到行政机关主体）",
                evidence={
                    "applicant_unit": applicant_name,
                    "applicant_region": applicant_region,
                    "legal_person_evidence": legal_person_evidence,
                },
            )

        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="申报单位资格符合要求",
            evidence={
                "applicant_unit": applicant_name,
                "applicant_region": applicant_region,
                "legal_person_evidence": legal_person_evidence,
                "cooperation_units": (cooperation.cooperation_units if cooperation else []),
            },
        )

    def _is_government_agency(self, name: str) -> bool:
        """粗判单位是否行政机关"""
        normalized = re.sub(r"\s+", "", str(name or ""))
        if not normalized:
            return False
        tokens = [
            "人民政府",
            "党委",
            "人民法院",
            "人民检察院",
            "政协",
            "人大常委会",
            "发展和改革委员会",
            "科学技术局",
            "科技局",
            "财政局",
            "税务局",
            "教育局",
            "公安局",
            "应急管理局",
            "行政审批局",
            "管理委员会",
            "委员会",
            "机关事务",
        ]
        if any(token in normalized for token in tokens):
            if any(white in normalized for white in ["大学", "学院", "医院", "研究院", "研究所", "实验室", "中心"]):
                return False
            return True
        return False

    def _is_explicit_non_hebei(self, region: str) -> bool:
        """明确识别为非河北地区"""
        normalized = re.sub(r"\s+", "", str(region or ""))
        if not normalized:
            return False
        if "河北" in normalized:
            return False
        non_hebei_tokens = [
            "北京",
            "天津",
            "上海",
            "重庆",
            "新疆",
            "西藏",
            "广东",
            "江苏",
            "浙江",
            "山东",
            "河南",
            "湖北",
            "湖南",
            "四川",
            "云南",
            "陕西",
        ]
        return any(token in normalized for token in non_hebei_tokens)
