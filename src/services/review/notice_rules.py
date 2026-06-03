"""申报通知规则解析与合并"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List


_NOTICE_2026_TITLE = "关于申报2026年度中央引导地方 科技发展资金项目的通知"


def build_notice_context(notice_url: str = "", notice_html: str = "") -> Dict[str, Any]:
    """构造通知上下文"""
    title = ""
    text = ""
    recognized_notice_id = ""
    if notice_html.strip():
        title = _extract_notice_title(notice_html)
        text = _html_to_text(notice_html)
    if notice_url.strip() and "2026021118105729745" in notice_url:
        recognized_notice_id = "2026_central_guidance_local_fund"
        if not title:
            title = _NOTICE_2026_TITLE
    if title == _NOTICE_2026_TITLE:
        recognized_notice_id = "2026_central_guidance_local_fund"
    return {
        "notice_url": notice_url.strip(),
        "notice_title": title.strip(),
        "notice_text": text.strip(),
        "recognized_notice_id": recognized_notice_id,
    }


def get_merged_policy_review_points(project_type: str, base_points: List[Dict[str, Any]], notice_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """合并基础规则与通知规则，通知同 code 覆盖基础规则"""
    merged: Dict[str, Dict[str, Any]] = {}
    for item in base_points:
        code = str(item.get("code", "")).strip()
        if code:
            merged[code] = dict(item)
    for item in _get_notice_policy_points(project_type, notice_context):
        code = str(item.get("code", "")).strip()
        if code:
            merged[code] = dict(item)
    return list(merged.values())


def _get_notice_policy_points(project_type: str, notice_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按已识别通知返回项目类型对应规则"""
    if notice_context.get("recognized_notice_id") != "2026_central_guidance_local_fund":
        return []
    project_rules = _NOTICE_2026_RULES.get(project_type, [])
    common_rules = _NOTICE_2026_COMMON_RULES
    return [dict(item) for item in [*project_rules, *common_rules]]


def _extract_notice_title(notice_html: str) -> str:
    """提取通知标题"""
    match = re.search(r"<title>(.*?)</title>", notice_html, re.I | re.S)
    if match:
        return html.unescape(match.group(1)).strip()
    text = _html_to_text(notice_html)
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean[:120]
    return ""


def _html_to_text(notice_html: str) -> str:
    """HTML 转文本"""
    text = re.sub(r"<script.*?</script>", " ", notice_html, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>|</div>|</li>|</tr>|</h\\d>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


_NOTICE_2026_RULES: Dict[str, List[Dict[str, Any]]] = {
    "regional_innovation": [
        {
            "code": "registered_date_limit",
            "requirement": "项目申报单位应在2025年1月1日（含）前注册。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "cooperation_region_check",
            "requirement": "合作单位应在新疆维吾尔自治区巴音郭楞蒙古自治州、新疆生产建设兵团第二师铁门关市或西藏自治区阿里地区注册。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "cooperation_agreement_required",
            "requirement": "承担单位与合作单位应签订正式合作协议（合同）。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "funding_ratio_check",
            "requirement": "申请财政资金与自筹资金比例不得低于1:1；申报单位与合作单位均为事业单位的，对自筹资金不做要求。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "recommendation_letter_required",
            "requirement": "援疆援藏项目需由合作方地市级科技管理部门出具推荐函并作为附件上传。",
            "automation": "requires_data",
            "reason": "当前未区分援疆援藏项目场景与推荐函触发条件",
        },
        {
            "code": "execution_period_limit",
            "requirement": "项目执行期不超过2年。",
            "automation": "auto",
            "reason": "",
        },
    ],
    "innovation_base": [
        {
            "code": "registered_date_limit",
            "requirement": "项目申报单位应在2025年1月1日（含）前注册。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "joint_application_check",
            "requirement": "创新基地主办单位为高校、科研院所等事业单位的，须与企业联合申报。",
            "automation": "requires_data",
            "reason": "当前未接入联合申报主体结构与合作单位类型",
        },
        {
            "code": "base_staff_proof_required",
            "requirement": "项目申报人须为基地固定人员，并上传单位出具的基地固定人员证明。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "funding_ratio_check",
            "requirement": "企业申请财政资金与自筹资金比例不得低于1:2，事业单位不得低于1:1。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "unfinished_guidance_project_check",
            "requirement": "截至2026年1月1日，有未结题中央引导地方项目的省级重点实验室、省级技术创新中心不得申报。",
            "automation": "requires_data",
            "reason": "当前未接入基地历史项目结题状态",
        },
        {
            "code": "execution_period_limit",
            "requirement": "项目执行期不超过2年。",
            "automation": "auto",
            "reason": "",
        },
    ],
    "achievement_transformation": [
        {
            "code": "registered_date_limit",
            "requirement": "项目申报单位应在2025年1月1日（含）前注册。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "applicant_unit_type_check",
            "requirement": "项目应由企业牵头承担。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "funding_ratio_check",
            "requirement": "申请财政资金与自筹资金比例不得低于1:3。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "joint_updownstream_application_check",
            "requirement": "特色产业集群成果转化与技术攻关项目申报单位应与产业链上下游企业联合申报。",
            "automation": "requires_data",
            "reason": "当前未接入集群项目标识和合作单位产业链关系",
        },
        {
            "code": "shared_mechanism_check",
            "requirement": "特色产业集群项目实施期间应建立完善的“共投、共研、共享”机制。",
            "automation": "manual",
            "reason": "需结合协议与实施方案人工复核机制设计",
        },
        {
            "code": "execution_period_limit",
            "requirement": "项目执行期不超过2年。",
            "automation": "auto",
            "reason": "",
        },
    ],
    "basic_research": [
        {
            "code": "registered_date_limit",
            "requirement": "项目申报单位应在2025年1月1日（含）前注册。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "execution_period_limit",
            "requirement": "项目执行期不超过3年。",
            "automation": "auto",
            "reason": "",
        },
        {
            "code": "provincial_nsf_conflict_check",
            "requirement": "申报本年度省自然基金项目的负责人，不得申报本批次基础研究项目。",
            "automation": "system_managed",
            "reason": "该限制由申报系统前置控制，不纳入本服务重复审查",
        },
        {
            "code": "unfinished_basic_project_check",
            "requirement": "截至2026年1月1日，未完成验收的省自然基金和中央引导地方科技发展资金基础研究项目负责人，不得申报本批次基础研究项目。",
            "automation": "system_managed",
            "reason": "该限制由申报系统前置控制，不纳入本服务重复审查",
        },
    ],
}


_NOTICE_2026_COMMON_RULES: List[Dict[str, Any]] = [
    {
        "code": "applicant_qualification_check",
        "requirement": "项目申报单位应为河北省所属的或者在河北省行政区域内登记、注册、具有独立法人资格的企事业单位；行政机关不得作为申报单位或合作单位。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "project_leader_age_check",
        "requirement": "项目负责人应为1967年1月1日（含）以后出生。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "active_guidance_project_leader_check",
        "requirement": "有在研中央引导地方科技发展资金项目负责人（基础研究项目除外），不得申报本批次区域科技创新体系建设、科技创新基地建设、科技成果转移转化项目。",
        "automation": "system_managed",
        "reason": "该限制由申报系统前置控制，不纳入本服务重复审查",
    },
    {
        "code": "integrity_and_credit_check",
        "requirement": "申报单位、合作单位和项目组成员诚信状况良好，无科研失信记录和相关社会领域信用黑名单记录。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "project_count_limit_check",
        "requirement": "申报本批次区域科技创新体系、科技创新基地、科技成果转化与技术攻关项目的申报人，在研与本年度申报总数不超过2项，其中作为负责人最多1项。",
        "automation": "system_managed",
        "reason": "该限制由申报系统前置控制，不纳入本服务重复审查",
    },
    {
        "code": "enterprise_batch_limit_check",
        "requirement": "本批次中央引导地方科技发展资金项目（不含基础研究项目），每个企业最多申报1项。",
        "automation": "system_managed",
        "reason": "该限制由申报系统前置控制，不纳入本服务重复审查",
    },
    {
        "code": "enterprise_active_guidance_project_check",
        "requirement": "截至2026年1月1日，有在研中央引导地方科技发展资金项目（不含基础研究方向）的企业，不得申报本批次相关项目。",
        "automation": "system_managed",
        "reason": "该限制由申报系统前置控制，不纳入本服务重复审查",
    },
    {
        "code": "performance_metric_count_check",
        "requirement": "项目应分年度确定绩效指标，第一年度绩效目标应达到总绩效目标50%以上，绩效指标总数不得低于5项。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "budget_forbidden_expense_check",
        "requirement": "中央引导地方科技发展资金项目不得列支间接经费和绩效支出，不得用于罚款、捐款、赞助、投资、偿还债务等支出。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "biosafety_commitment_required",
        "requirement": "项目内容涉及生物技术研究、开发、应用的，必须填写生物安全承诺书。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "ethics_approval_required",
        "requirement": "涉及人的医学研究及人类遗传资源相关活动的项目，正式实施前应按规定通过伦理审查。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "industry_permit_required",
        "requirement": "涉及安全生产等特种行业的，需提供相关行业准入资格或许可佐证材料。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "cooperation_agreement_required",
        "requirement": "项目有合作单位的，申报单位应与合作单位签订合作协议，格式规范、分工明确、权属清晰，使用法人单位印章。",
        "automation": "requires_data",
        "reason": "当前只能校验协议存在性，尚未核验协议规范性与权属条款",
    },
    {
        "code": "leader_achievement_attachment_check",
        "requirement": "项目负责人及骨干人员科研水平及主要研究成果证明材料应作为附件上传。",
        "automation": "auto",
        "reason": "",
    },
    {
        "code": "other_policy_compliance",
        "requirement": "其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题。",
        "automation": "manual",
        "reason": "需人工综合复核通知正文、管理办法及申报指南",
    },
]
