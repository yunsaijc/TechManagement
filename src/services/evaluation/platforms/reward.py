"""奖励平台正文评审适配器。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.database.connection import reward_execute
from src.common.models.evaluation import DEFAULT_WEIGHTS, EvaluationRequest, PlatformEvaluationRequest
from src.services.review.smb_file_reader import SMBReviewFileReader


AWARD_TYPE_NAMES = {
    "1": "突出贡献奖",
    "2": "自然科学奖",
    "3": "技术发明奖",
    "4": "科学技术进步奖",
    "5": "科学技术合作奖",
    "6": "企业技术创新奖",
    "7": "科学技术普及奖",
}


AWARD_TYPE_PREFERENCES = {
    "1": "更关注重大贡献、行业影响、成果价值和示范带动作用。",
    "2": "更关注原创发现、学术贡献、代表性成果质量和同行认可。",
    "3": "更关注技术原创性、发明高度、技术可行性和应用前景。",
    "4": "更关注推广应用、经济社会效益、成熟度和示范效果。",
    "5": "更关注合作基础、合作贡献、国际或区域影响和协同成效。",
    "6": "更关注企业创新能力、产业化价值、经济效益和技术竞争力。",
    "7": "更关注科普传播效果、社会效益、受众覆盖和组织实施基础。",
}


AWARD_TYPE_WEIGHTS = {
    "1": {
        "outcome": 0.18,
        "social_benefit": 0.16,
        "economic_benefit": 0.14,
        "team": 0.14,
        "innovation": 0.12,
        "feasibility": 0.10,
        "compliance": 0.08,
        "schedule": 0.04,
        "risk_control": 0.04,
    },
    "2": {
        "innovation": 0.22,
        "outcome": 0.18,
        "feasibility": 0.14,
        "team": 0.10,
        "social_benefit": 0.10,
        "compliance": 0.08,
        "economic_benefit": 0.06,
        "schedule": 0.06,
        "risk_control": 0.06,
    },
    "3": {
        "innovation": 0.20,
        "feasibility": 0.18,
        "outcome": 0.15,
        "economic_benefit": 0.13,
        "team": 0.10,
        "social_benefit": 0.08,
        "compliance": 0.06,
        "schedule": 0.05,
        "risk_control": 0.05,
    },
    "4": {
        "outcome": 0.18,
        "economic_benefit": 0.16,
        "social_benefit": 0.14,
        "feasibility": 0.14,
        "innovation": 0.12,
        "team": 0.08,
        "compliance": 0.07,
        "schedule": 0.06,
        "risk_control": 0.05,
    },
    "5": {
        "social_benefit": 0.18,
        "team": 0.16,
        "outcome": 0.15,
        "innovation": 0.12,
        "feasibility": 0.12,
        "economic_benefit": 0.10,
        "compliance": 0.07,
        "schedule": 0.05,
        "risk_control": 0.05,
    },
    "6": {
        "economic_benefit": 0.20,
        "innovation": 0.17,
        "feasibility": 0.16,
        "outcome": 0.14,
        "team": 0.10,
        "social_benefit": 0.08,
        "compliance": 0.06,
        "risk_control": 0.05,
        "schedule": 0.04,
    },
    "7": {
        "social_benefit": 0.22,
        "outcome": 0.16,
        "feasibility": 0.13,
        "team": 0.12,
        "innovation": 0.10,
        "schedule": 0.09,
        "compliance": 0.08,
        "economic_benefit": 0.05,
        "risk_control": 0.05,
    },
}


REWARD_DIMENSION_SECTION_ALIASES = {
    "feasibility": {
        "技术路线": [
            "项目详细内容（不超过6页）",
            "项目简介（限1200字）",
            "项目简介",
            "重要科学发现",
            "主要技术发明",
            "主要科技创新",
            "科技创新内容",
            "科学技术合作内容",
            "企业技术创新情况",
            "科普作品情况",
        ],
        "研究方案": [
            "项目详细内容（不超过6页）",
            "项目简介（限1200字）",
            "项目简介",
            "重要科学发现",
            "主要技术发明",
            "主要科技创新",
            "科普创作和传播情况",
        ],
        "实施方案": [
            "项目详细内容（不超过6页）",
            "项目简介（限1200字）",
            "项目简介",
            "推广应用情况",
            "应用情况",
            "科普活动情况",
        ],
    },
    "innovation": {
        "创新点": [
            "重要科学发现",
            "主要科学发现",
            "主要技术发明",
            "主要科技创新",
            "科技创新内容",
            "科学技术合作内容",
            "企业技术创新情况",
            "科普作品创新性",
            "项目详细内容（不超过6页）",
            "项目简介（限1200字）",
        ],
        "技术方案": [
            "项目详细内容（不超过6页）",
            "重要科学发现",
            "主要技术发明",
            "主要科技创新",
            "科技创新内容",
        ],
        "研究内容": [
            "项目详细内容（不超过6页）",
            "重要科学发现",
            "主要科学发现",
            "主要技术发明",
            "主要科技创新",
            "科普作品情况",
        ],
    },
    "team": {
        "项目团队": ["主要完成人情况表", "主要完成单位情况表", "项目基本情况", "科学技术合作内容"],
        "人员分工": ["主要完成人情况表", "主要完成单位情况表", "完成单位合作情况"],
        "成员简介": ["主要完成人情况表", "主要完成人"],
        "团队介绍": ["主要完成人情况表", "主要完成单位情况表", "完成单位合作情况"],
    },
    "outcome": {
        "预期成果": [
            "代表性论文(专著)目录（不超过6篇）",
            "代表性论文",
            "知识产权和标准规范目录",
            "主要知识产权证明目录",
            "重要科学发现",
            "主要技术发明",
            "主要科技创新",
            "项目简介（限1200字）",
        ],
        "考核指标": [
            "重要科学发现",
            "主要技术发明",
            "主要科技创新",
            "代表性论文(专著)被他人引用情况（不超过6篇）",
            "推广应用情况",
            "应用情况",
        ],
        "技术指标": [
            "重要科学发现",
            "主要技术发明",
            "主要科技创新",
            "项目详细内容（不超过6页）",
        ],
        "成果形式": [
            "代表性论文(专著)目录（不超过6篇）",
            "知识产权和标准规范目录",
            "主要知识产权证明目录",
            "主要附件目录",
            "公示材料",
        ],
    },
    "social_benefit": {
        "预期效益": [
            "客观评价（不超过2页）",
            "客观评价",
            "推广应用情况",
            "应用情况",
            "经济效益和社会效益",
            "社会效益",
            "科普活动情况",
            "代表性论文(专著)被他人引用情况（不超过6篇）",
            "项目详细内容（不超过6页）",
        ],
        "社会效益": [
            "客观评价（不超过2页）",
            "客观评价",
            "推广应用情况",
            "应用情况",
            "经济效益和社会效益",
            "社会效益",
            "科普活动情况",
            "代表性论文(专著)被他人引用情况（不超过6篇）",
        ],
        "推广应用": ["推广应用情况", "应用情况", "客观评价（不超过2页）", "项目详细内容（不超过6页）"],
        "效益分析": ["经济效益和社会效益", "社会效益", "客观评价（不超过2页）", "客观评价"],
    },
    "economic_benefit": {
        "预期效益": [
            "经济效益和社会效益",
            "经济效益",
            "推广应用情况",
            "应用情况",
            "客观评价（不超过2页）",
            "项目详细内容（不超过6页）",
        ],
        "经济效益": [
            "经济效益和社会效益",
            "经济效益",
            "推广应用情况",
            "应用情况",
            "客观评价（不超过2页）",
            "项目详细内容（不超过6页）",
        ],
        "产业化": ["推广应用情况", "应用情况", "企业技术创新情况", "客观评价（不超过2页）", "项目详细内容（不超过6页）"],
        "效益分析": ["经济效益和社会效益", "经济效益", "客观评价（不超过2页）", "客观评价"],
    },
    "risk_control": {
        "风险分析": ["项目基本情况", "主要附件目录", "项目简介（限1200字）", "客观评价（不超过2页）"],
        "风险控制": ["项目基本情况", "主要附件目录", "项目简介（限1200字）", "客观评价（不超过2页）"],
        "风险管理": ["项目基本情况", "主要附件目录", "签字盖章类材料"],
        "风险应对": ["项目基本情况", "主要附件目录", "签字盖章类材料"],
    },
    "schedule": {
        "进度安排": ["项目详细内容（不超过6页）", "推广应用情况", "应用情况", "项目简介（限1200字）"],
        "实施计划": ["项目详细内容（不超过6页）", "推广应用情况", "应用情况", "项目简介（限1200字）"],
        "工作计划": ["项目详细内容（不超过6页）", "科普活动情况", "项目简介（限1200字）"],
        "研究计划": ["项目详细内容（不超过6页）", "重要科学发现", "主要技术发明", "主要科技创新"],
    },
    "compliance": {
        "政策依据": ["提名意见", "项目基本情况", "主要附件目录", "公示材料"],
        "经费预算": ["项目基本情况", "主要附件目录"],
        "伦理审查": ["项目基本情况", "主要附件目录", "完成人声明", "单位声明", "签字盖章类材料"],
        "预算说明": ["项目基本情况", "主要附件目录"],
    },
}


class RewardEvaluationAdapter:
    """把奖励平台项目转换为正文评审输入。"""

    def __init__(self, smb_reader: Optional[SMBReviewFileReader] = None):
        self.smb_reader = smb_reader or SMBReviewFileReader()

    async def evaluate(self, agent: Any, request: PlatformEvaluationRequest):
        """执行奖励平台评审。"""
        project = self.get_project(request.project_id)
        if not project:
            raise ValueError(f"奖励项目不存在: {request.project_id}")

        xmbh = str(project.get("XMBH") or project.get("xmbh") or request.project_id).strip()
        xmtjh = str(project.get("XMTJH") or project.get("xmtjh") or "").strip()
        nd = str(project.get("ND") or project.get("nd") or "").strip()
        if not xmtjh or not nd:
            raise ValueError(f"奖励项目缺少年度或提名号: {xmbh}")

        award_type_code = self.resolve_award_type_code(xmbh)
        award_type_name = AWARD_TYPE_NAMES.get(award_type_code)
        if not award_type_name:
            raise ValueError(f"奖励项目编号无法识别奖种: {xmbh}")

        material_groups = self.build_material_groups(xmbh=xmbh, xmtjh=xmtjh, nd=nd)
        try:
            local_paths = self.materials_to_local_files(material_groups)
        except Exception as exc:
            raise ValueError(f"未找到奖励提名书: {xmbh}: {exc}") from exc
        main_materials = local_paths.get("主材料", [])
        if not main_materials:
            raise ValueError(f"未找到奖励提名书: {xmbh}")

        attachment_paths = [
            item["local_path"]
            for group_name in ("签字盖章类材料", "相关佐证材料")
            for item in local_paths.get(group_name, [])
            if item.get("local_path")
        ]

        options = dict(request.options or {})
        options.update(
            {
                "platform": "reward",
                "award_type_code": award_type_code,
                "award_type_name": award_type_name,
                "review_preference": AWARD_TYPE_PREFERENCES.get(award_type_code, ""),
                "reward_project": project,
                "reward_material_groups": material_groups,
                "dimension_section_aliases": REWARD_DIMENSION_SECTION_ALIASES,
            }
        )
        weights = request.weights or self.get_award_weights(award_type_code)
        eval_request = EvaluationRequest(
            project_id=xmbh,
            dimensions=request.dimensions,
            weights=weights,
            include_sections=request.include_sections,
            enable_highlight=request.enable_highlight,
            enable_industry_fit=request.enable_industry_fit,
            enable_benchmark=request.enable_benchmark,
            enable_chat_index=request.enable_chat_index,
            options=options,
        )

        parsed = await agent.parser.parse(
            main_materials[0]["local_path"],
            source_name=main_materials[0]["file_name"],
        )
        sections = parsed.get("sections", {})
        if isinstance(sections, dict):
            sections.setdefault("项目名称", str(project.get("XMMC") or project.get("xmmc") or ""))
            sections.setdefault("奖励类型", award_type_name)
            sections.setdefault("评审偏好", AWARD_TYPE_PREFERENCES.get(award_type_code, ""))
        meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
        meta["attachment_files"] = attachment_paths
        meta["platform"] = "reward"
        meta["award_type_code"] = award_type_code
        meta["award_type_name"] = award_type_name
        meta["review_preference"] = AWARD_TYPE_PREFERENCES.get(award_type_code, "")
        meta["reward_project"] = project
        meta["reward_material_groups"] = material_groups
        meta["reward_local_material_groups"] = local_paths
        parsed["sections"] = sections
        parsed["meta"] = meta

        return await agent.evaluate(
            request=eval_request,
            file_path=main_materials[0]["local_path"],
            content=parsed,
            source_name=main_materials[0]["file_name"],
        )

    def get_project(self, xmbh: str) -> Optional[Dict[str, Any]]:
        rows = reward_execute(
            "xmsbnew",
            """
            SELECT XMBH, XMMC, XMTJH, ND, JZBH, XKDZMC, TJDWBH
            FROM t_xm_ggjbxx
            WHERE XMBH = %s
            LIMIT 1
            """,
            (str(xmbh or "").strip(),),
        )
        return rows[0] if rows else None

    def build_material_groups(self, *, xmbh: str, xmtjh: str, nd: str) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "主材料": [
                {
                    "title": "提名书",
                    "source": "derived",
                    "file_name": f"{xmtjh}.docx",
                    "path": f"FJCL\\static\\rpw\\tjs{nd}\\{xmtjh}.docx",
                }
            ],
            "签字盖章类材料": self._build_gzy_materials(xmbh=xmbh, xmtjh=xmtjh, nd=nd),
            "相关佐证材料": [
                *self._build_qtfjcl_materials(xmbh=xmbh, xmtjh=xmtjh, nd=nd),
                *self._build_gscl_materials(xmbh=xmbh, xmtjh=xmtjh, nd=nd),
            ],
        }

    def materials_to_local_files(self, material_groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = {}
        temp_root = Path(tempfile.mkdtemp(prefix="reward_eval_"))
        for group_name, materials in material_groups.items():
            result[group_name] = []
            for index, material in enumerate(materials, start=1):
                path = str(material.get("path") or "").strip()
                if not path:
                    continue
                file_name = Path(path.replace("\\", "/")).name
                suffix = Path(file_name).suffix or ".bin"
                local_path = temp_root / group_name / f"{index:03d}_{self._safe_filename(file_name, suffix)}"
                local_path.parent.mkdir(parents=True, exist_ok=True)
                item = dict(material)
                item["file_name"] = file_name
                try:
                    data = self.smb_reader.read_bytes(path)
                    local_path.write_bytes(data)
                    item["local_path"] = str(local_path)
                except Exception as exc:
                    item["read_error"] = str(exc)
                    if group_name == "主材料":
                        raise
                result[group_name].append(item)
        return result

    def get_award_weights(self, award_type_code: str) -> Dict[str, float]:
        return dict(AWARD_TYPE_WEIGHTS.get(award_type_code) or DEFAULT_WEIGHTS)

    def resolve_award_type_code(self, xmbh: str) -> str:
        text = str(xmbh or "").strip()
        return text[4] if len(text) >= 5 else ""

    def _build_gzy_materials(self, *, xmbh: str, xmtjh: str, nd: str) -> List[Dict[str, Any]]:
        rows = reward_execute(
            "xmsbnew",
            """
            SELECT id, LX, XH, FJMC, FJLJ, ND, wcr_id
            FROM t_xm_gzy
            WHERE XMBH = %s
            ORDER BY LX, XH, id
            """,
            (xmbh,),
        )
        return [
            {
                "id": str(row.get("id") or ""),
                "source": "t_xm_gzy",
                "type": str(row.get("LX") or ""),
                "title": str(row.get("FJMC") or row.get("FJLJ") or ""),
                "file_name": str(row.get("FJLJ") or ""),
                "path": f"FJCL\\static\\rpw\\gzy{nd}\\{xmtjh}\\{row.get('FJLJ')}",
            }
            for row in rows
            if str(row.get("FJLJ") or "").strip()
        ]

    def _build_qtfjcl_materials(self, *, xmbh: str, xmtjh: str, nd: str) -> List[Dict[str, Any]]:
        rows = reward_execute(
            "xmsbnew",
            """
            SELECT id, LX, XH, FJMC, FJLJ, ND
            FROM t_xm_qtfjcl
            WHERE XMBH = %s
            ORDER BY LX, XH, id
            """,
            (xmbh,),
        )
        return [
            {
                "id": str(row.get("id") or ""),
                "source": "t_xm_qtfjcl",
                "type": str(row.get("LX") or ""),
                "title": str(row.get("FJMC") or row.get("FJLJ") or ""),
                "file_name": str(row.get("FJLJ") or ""),
                "path": f"FJCL\\static\\rpw\\zmcl{nd}\\{xmtjh}\\{row.get('FJLJ')}",
            }
            for row in rows
            if str(row.get("FJLJ") or "").strip()
        ]

    def _build_gscl_materials(self, *, xmbh: str, xmtjh: str, nd: str) -> List[Dict[str, Any]]:
        rows = reward_execute(
            "xmsbnew",
            """
            SELECT id, code, url, filepath, nd, xh
            FROM t_xm_gscl
            WHERE XMBH = %s
            ORDER BY xh, id
            """,
            (xmbh,),
        )
        return [
            {
                "id": str(row.get("id") or ""),
                "source": "t_xm_gscl",
                "type": "公示材料",
                "title": "公示材料",
                "url": str(row.get("url") or ""),
                "file_name": str(row.get("filepath") or ""),
                "path": f"FJCL\\static\\rpw\\zmcl{nd}\\{xmtjh}\\{row.get('filepath')}",
            }
            for row in rows
            if str(row.get("filepath") or "").strip()
        ]

    def _safe_filename(self, file_name: str, fallback_suffix: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in file_name)
        cleaned = cleaned.strip("._") or f"material{fallback_suffix}"
        return cleaned
