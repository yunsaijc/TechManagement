"""奖励平台单文件审查增强服务。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import PureWindowsPath
from typing import Any, Dict, List, Optional

from src.common.database.connection import reward_execute, reward_execute_write
from src.common.models import CheckResult, CheckStatus, ReviewResult
from src.services.review.doc_types import get_doc_type_label, normalize_doc_type

logger = logging.getLogger(__name__)


REWARD_PATH_DOC_TYPES = {"tjdwyj", "gzdwyj", "wcr", "wjwcr", "wcdw", "hzdw", "dywcrcns", "dywcdwcns", "qysm"}

DOC_TYPE_TO_LX = {
    "tjdwyj": "10.1",
    "gzdwyj": "10.2",
    "wcr": "10.3",
    "wjwcr": "10.3",
    "wcdw": "10.4",
    "hzdw": "10.5",
    "dywcrcns": "5.10",
    "dywcdwcns": "5.15",
    "qysm": "5.16",
}

QTFJCL_DOC_TYPES = {"dywcrcns", "dywcdwcns", "qysm"}


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/]", "", text).lower()


def _is_exact_match(left: str, right: str) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    return bool(normalized_left) and normalized_left == normalized_right


def _is_partial_match(left: str, right: str) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return False
    return normalized_left in normalized_right or normalized_right in normalized_left


def _matches(expected: str, candidates: List[str]) -> bool:
    left = _normalize_text(expected)
    if not left:
        return False
    for item in candidates:
        right = _normalize_text(item)
        if not right:
            continue
        if left == right or left in right or right in left:
            return True
    return False


def _dedup(values: List[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        key = _normalize_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _raw_field_state(expected: str, observed: str) -> str:
    expected_text = str(expected or "").strip()
    observed_text = str(observed or "").strip()
    if not expected_text or not observed_text:
        return "unknown"
    return "match" if _matches(expected_text, [observed_text]) else "mismatch"


def _raw_candidate_state(expected: str, candidates: List[str]) -> str:
    expected_text = str(expected or "").strip()
    normalized_candidates = [str(item or "").strip() for item in (candidates or []) if str(item or "").strip()]
    if not expected_text or not normalized_candidates:
        return "unknown"
    return "match" if _matches(expected_text, normalized_candidates) else "mismatch"


def _raw_db_field_state(expected: str, observed: str) -> str:
    expected_text = str(expected or "").strip()
    observed_text = str(observed or "").strip()
    if not expected_text or not observed_text:
        return "unknown"
    if _is_exact_match(expected_text, observed_text):
        return "match"
    if _is_partial_match(expected_text, observed_text):
        return "partial_match"
    return "mismatch"


def _clean_signature_text(value: Any) -> str:
    text = str(value or "").replace("\n", " ").replace("\xa0", " ").strip()
    if not text:
        return ""

    banned_exact_values = {
        "位置如下",
        "如下",
        "位置",
        "签字位置如下",
        "签名位置如下",
        "签字如下",
        "签名如下",
    }

    patterns = [
        r"(?:本人签名|签名人|签字人|签名|签字)[：:\s]*([A-Za-z\u4e00-\u9fff·• ]{2,40})$",
        r"(?:本人签名|签名人|签字人|签名|签字)[：:\s]*([A-Za-z\u4e00-\u9fff·• ]{2,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip()
            if (
                re.fullmatch(r"[A-Za-z\u4e00-\u9fff·• ]{2,40}", candidate)
                and candidate not in banned_exact_values
                and "位置" not in candidate
                and "如下" not in candidate
            ):
                return candidate

    description_markers = {
        "页面", "位于", "位置", "区域", "上方", "下方", "左侧", "右侧", "左下角", "右下角",
        "中间", "附近", "公章", "手写", "黑色", "红色", "文字", "覆盖", "具体", "如下",
        "有一个", "可见", "显示", "图中",
    }
    if any(marker in text for marker in description_markers):
        return ""
    if any(punct in text for punct in ("，", "。", "；")):
        return ""
    if len(text) > 40:
        return ""
    if not re.fullmatch(r"[A-Za-z\u4e00-\u9fff·• ]{2,40}", text):
        return ""
    return text


def _pick_case_insensitive(row: Dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


class RewardReviewService:
    """奖励平台单文件审查增强服务。"""

    def is_reward_doc_type(self, doc_type: str) -> bool:
        return normalize_doc_type(doc_type) in REWARD_PATH_DOC_TYPES

    def build_context(self, project_id: str, file_path: str, doc_type: str) -> Dict[str, Any]:
        normalized_doc_type = normalize_doc_type(doc_type)
        context: Dict[str, Any] = {
            "project_id": str(project_id or "").strip(),
            "file_path": str(file_path or "").strip(),
            "doc_type": normalized_doc_type,
            "doc_type_label": get_doc_type_label(normalized_doc_type),
            "errors": [],
            "attachment_record": None,
            "target_record": None,
            "target_values": {},
            "path_info": self._parse_path_info(file_path),
        }

        if not context["project_id"]:
            context["errors"].append("缺少 project_id，无法关联奖励库记录")
            return context

        if normalized_doc_type not in REWARD_PATH_DOC_TYPES:
            context["errors"].append(f"不支持的奖励材料类型: {doc_type}")
            return context

        try:
            attachment_record = self._find_attachment_record(
                project_id=context["project_id"],
                file_path=context["file_path"],
                doc_type=normalized_doc_type,
            )
            context["attachment_record"] = attachment_record
            if not attachment_record:
                attachment_table = "t_xm_qtfjcl" if normalized_doc_type in QTFJCL_DOC_TYPES else "t_xm_gzy"
                context["errors"].append(f"未匹配到 {attachment_table} 附件记录")
                return context
        except Exception as exc:
            logger.exception("构建奖励附件上下文失败")
            context["errors"].append(f"奖励库附件查询失败: {exc}")
            return context

        try:
            target_record, target_values = self._load_target_record(attachment_record, normalized_doc_type)
            context["target_record"] = target_record
            context["target_values"] = target_values
            if not target_values:
                context["errors"].append("未查询到奖励库目标字段")
        except Exception as exc:
            logger.exception("加载奖励库目标记录失败")
            context["errors"].append(f"奖励库目标记录查询失败: {exc}")

        return context

    def enrich_result(
        self,
        result: ReviewResult,
        context: Dict[str, Any],
        check_items: Optional[List[str]] = None,
        file_data: Optional[bytes] = None,
    ) -> ReviewResult:
        normalized_doc_type = normalize_doc_type(result.doc_type)
        effective_items = {str(item).strip() for item in (check_items or []) if str(item).strip()}

        observed_fields = self._collect_observed_fields(result, normalized_doc_type)
        signatures = self._collect_signature_texts(result)
        stamps = self._collect_stamp_texts(result)
        verification = self._collect_verification_result(
            result=result,
            file_data=file_data,
            doc_type=normalized_doc_type,
            target_values=context.get("target_values", {}) or {},
        )

        result.extracted_data["reward_project_id"] = context.get("project_id", "")
        result.extracted_data["reward_recognized_signatures"] = signatures
        result.extracted_data["reward_recognized_stamps"] = stamps
        result.extracted_data["reward_target_values"] = context.get("target_values", {})
        result.extracted_data["reward_verification"] = verification

        extras: List[CheckResult] = []
        errors = [str(item) for item in context.get("errors", []) if str(item).strip()]
        if errors:
            extras.append(
                CheckResult(
                    item="reward_db_context",
                    status=CheckStatus.WARNING,
                    message="；".join(errors),
                    evidence={
                        "project_id": context.get("project_id", ""),
                        "file_path": context.get("file_path", ""),
                        "doc_type": normalized_doc_type,
                    },
                )
            )

        target_values = context.get("target_values", {}) or {}

        if normalized_doc_type == "tjdwyj":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_candidates(
                            item="nomination_unit_stamp_consistency",
                            label="提名单位公章",
                            expected=str(target_values.get("nomination_unit_name") or ""),
                            candidates=stamps,
                            verification=verification.get("nomination_unit_stamp"),
                        )
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type == "gzdwyj":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_candidates(
                            item="candidate_work_unit_stamp_consistency",
                            label="候选人工作单位公章",
                            expected=str(target_values.get("candidate_work_unit_name") or ""),
                            candidates=stamps,
                            verification=verification.get("candidate_work_unit_stamp"),
                        )
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type in {"wcr", "wjwcr"}:
            extras.extend(
                self._filter_items(
                    [
                        self._compare_field(
                            item="contributor_db_name_consistency",
                            label="姓名",
                            observed=observed_fields.get("name", ""),
                            expected=str(target_values.get("name") or ""),
                            verification=verification.get("name"),
                        ),
                        self._compare_field(
                            item="contributor_db_work_unit_consistency",
                            label="工作单位",
                            observed=observed_fields.get("work_unit", ""),
                            expected=str(target_values.get("work_unit") or ""),
                            verification=verification.get("work_unit"),
                        ),
                        self._compare_field(
                            item="contributor_db_completion_unit_consistency",
                            label="完成单位",
                            observed=observed_fields.get("completion_unit", ""),
                            expected=str(target_values.get("completion_unit") or ""),
                            verification=verification.get("completion_unit"),
                        ),
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type == "wcdw":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_field(
                            item="completion_unit_name_consistency",
                            label="单位名称",
                            observed=observed_fields.get("unit_name", ""),
                            expected=str(target_values.get("unit_name") or ""),
                            verification=verification.get("unit_name"),
                        ),
                        self._compare_field(
                            item="completion_unit_legal_representative_consistency",
                            label="法定代表人",
                            observed=observed_fields.get("legal_representative", ""),
                            expected=str(target_values.get("legal_representative") or ""),
                            verification=verification.get("legal_representative"),
                        ),
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type == "hzdw":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_field(
                            item="cooperation_unit_name_consistency",
                            label="单位名称",
                            observed=observed_fields.get("unit_name", ""),
                            expected=str(target_values.get("unit_name") or ""),
                            verification=verification.get("unit_name"),
                        ),
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type == "dywcrcns":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_named_signature(
                            item="first_contributor_signature_consistency",
                            label="第一完成人",
                            expected_name=str(target_values.get("name") or ""),
                            signature_names=signatures,
                            verification=verification.get("signature_for_name"),
                        ),
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type == "dywcdwcns":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_role_stamp_consistency(
                            item="first_completion_unit_stamp_consistency",
                            role_label="第一完成单位",
                            expected_unit=str(target_values.get("unit_name") or ""),
                            role_units=stamps,
                            verification=None,
                        ),
                    ],
                    effective_items,
                )
            )
        elif normalized_doc_type == "qysm":
            extras.extend(
                self._filter_items(
                    [
                        self._compare_role_stamp_consistency(
                            item="enterprise_stamp_consistency",
                            role_label="企业名称",
                            expected_unit=str(target_values.get("enterprise_name") or ""),
                            role_units=stamps,
                            verification=None,
                        ),
                        self._compare_named_signature(
                            item="enterprise_legal_representative_signature_consistency",
                            label="法定代表人",
                            expected_name=str(target_values.get("legal_representative") or ""),
                            signature_names=signatures,
                            verification=verification.get("legal_representative_signature"),
                        ),
                    ],
                    effective_items,
                )
            )

        self._apply_verification_to_existing_results(
            result=result,
            doc_type=normalized_doc_type,
            target_values=target_values,
            observed_fields=observed_fields,
            signatures=signatures,
            verification=verification,
        )
        result.results.extend(extras)
        result.summary = self._generate_summary(result.results)
        result.suggestions = self._generate_suggestions(result.results)
        result.structured_result = self._build_structured_result(
            result=result,
            context=context,
            observed_fields=observed_fields,
            signatures=signatures,
            stamps=stamps,
            verification=verification,
        )
        return result

    def persist_recognition(self, context: Dict[str, Any], result: ReviewResult) -> None:
        attachment = context.get("attachment_record") or {}
        row_id = str(_pick_case_insensitive(attachment, "id") or "").strip()
        if not row_id:
            return
        doc_type = normalize_doc_type(str(context.get("doc_type") or ""))

        signature_status = self._extract_item_status(result, "signature")
        stamp_status = self._extract_item_status(result, "stamp")
        signature_info = {
            "recognized": self._collect_signature_texts(result),
            "result": self._extract_item_evidence(result, "signature"),
            "verification": (result.extracted_data or {}).get("reward_verification", {}).get("signature_for_name"),
        }
        stamp_info = {
            "recognized": self._collect_stamp_texts(result),
            "result": self._extract_item_evidence(result, "stamp"),
            "verification": {
                key: value
                for key, value in ((result.extracted_data or {}).get("reward_verification", {}) or {}).items()
                if "stamp" in str(key)
            },
        }

        try:
            if doc_type in QTFJCL_DOC_TYPES:
                payload = {
                    "doc_type": doc_type,
                    "signature_check": signature_status,
                    "signature_info": signature_info,
                    "seal_check": stamp_status,
                    "seal_info": stamp_info,
                }
                reward_execute_write(
                    "xmsbnew",
                    """
                    UPDATE t_xm_qtfjcl
                    SET ocr_result = %s
                    WHERE id = %s
                    """,
                    (
                        json.dumps(payload, ensure_ascii=False),
                        row_id,
                    ),
                )
            else:
                reward_execute_write(
                    "xmsbnew",
                    """
                    UPDATE t_xm_gzy
                    SET signature_check = %s,
                        signature_info = %s,
                        seal_check = %s,
                        seal_info = %s
                    WHERE id = %s
                    """,
                    (
                        signature_status,
                        json.dumps(signature_info, ensure_ascii=False),
                        stamp_status,
                        json.dumps(stamp_info, ensure_ascii=False),
                        row_id,
                    ),
                )
        except Exception:
            logger.exception("奖励附件识别结果写回失败: id=%s", row_id)

    def _parse_path_info(self, file_path: str) -> Dict[str, str]:
        path = PureWindowsPath(str(file_path or "").replace("/", "\\"))
        parts = [str(part).strip() for part in path.parts if str(part).strip() and str(part).strip() not in {"\\", "/"}]
        filename = parts[-1] if parts else ""
        xmtjh = ""
        nd = ""
        for index, part in enumerate(parts):
            matched = re.fullmatch(r"gzy(\d{4})", part, re.IGNORECASE)
            if matched:
                nd = matched.group(1)
                if index + 1 < len(parts):
                    xmtjh = parts[index + 1]
                break
            matched = re.fullmatch(r"zmcl(\d{4})", part, re.IGNORECASE)
            if matched:
                nd = matched.group(1)
                if index + 1 < len(parts):
                    xmtjh = parts[index + 1]
                break
        return {
            "filename": filename,
            "xmtjh": xmtjh,
            "nd": nd,
        }

    def _find_attachment_record(self, project_id: str, file_path: str, doc_type: str) -> Optional[Dict[str, Any]]:
        info = self._parse_path_info(file_path)
        filename = info.get("filename", "")
        nd = info.get("nd", "")
        xmtjh = info.get("xmtjh", "")
        lx = DOC_TYPE_TO_LX.get(doc_type, "")
        if not filename or not lx:
            return None

        attempts: List[tuple[str, tuple[Any, ...]]] = []
        if doc_type in QTFJCL_DOC_TYPES:
            base_sql = """
            SELECT q.*
            FROM t_xm_qtfjcl q
            WHERE q.XMBH = %s
              AND q.LX = %s
              AND q.FJLJ = %s
            """
            if nd:
                attempts.append((base_sql + " AND q.ND = %s LIMIT 1", (project_id, lx, filename, nd)))
            attempts.append((base_sql + " LIMIT 1", (project_id, lx, filename)))
        else:
            base_sql = """
            SELECT g.*, gg.XMTJH
            FROM t_xm_gzy g
            LEFT JOIN t_xm_ggjbxx gg ON gg.XMBH = g.XMBH
            WHERE g.XMBH = %s
              AND g.LX = %s
              AND g.FJLJ = %s
            """
            if nd and xmtjh:
                attempts.append((base_sql + " AND g.ND = %s AND gg.XMTJH = %s LIMIT 1", (project_id, lx, filename, nd, xmtjh)))
            if nd:
                attempts.append((base_sql + " AND g.ND = %s LIMIT 1", (project_id, lx, filename, nd)))
            if xmtjh:
                attempts.append((base_sql + " AND gg.XMTJH = %s LIMIT 1", (project_id, lx, filename, xmtjh)))
            attempts.append((base_sql + " LIMIT 1", (project_id, lx, filename)))

        for sql, params in attempts:
            rows = reward_execute("xmsbnew", sql, params)
            if rows:
                return rows[0]
        return None

    def _load_target_record(
        self,
        attachment_record: Dict[str, Any],
        doc_type: str,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        project_id = str(_pick_case_insensitive(attachment_record, "XMBH", "xmbh") or "").strip()
        wcr_id = str(_pick_case_insensitive(attachment_record, "wcr_id", "WCR_ID") or "").strip()

        if doc_type == "tjdwyj":
            rows = reward_execute(
                "xmsbnew",
                """
                SELECT cl.*, td.*
                FROM t_xm_cl cl
                LEFT JOIN t_xm_tjdwxx td ON td.TJDWBH = cl.TJDWBH AND td.ND = cl.ND
                WHERE cl.XMBH = %s
                LIMIT 1
                """,
                (project_id,),
            )
            row = rows[0] if rows else None
            return row, {"nomination_unit_name": str(_pick_case_insensitive(row or {}, "tjdwqc", "TJDWQC") or "").strip()}

        if doc_type == "gzdwyj":
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_xm_tcgxgrjbxx WHERE XMBH = %s",
                (project_id,),
            )
            units = _dedup([str(_pick_case_insensitive(row, "grdwmc", "GRDWMC") or "").strip() for row in rows])
            return (rows[0] if rows else None), {"candidate_work_unit_name": units[0] if units else "", "candidate_work_unit_names": units}

        if doc_type in {"wcr", "wjwcr"}:
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_xm_zywcr WHERE id = %s LIMIT 1",
                (wcr_id,),
            )
            row = rows[0] if rows else None
            return row, {
                "name": str(_pick_case_insensitive(row or {}, "xm", "XM") or "").strip(),
                "work_unit": str(_pick_case_insensitive(row or {}, "gzdw", "GZDW") or "").strip(),
                "completion_unit": str(_pick_case_insensitive(row or {}, "wcdw", "WCDW") or "").strip(),
            }

        if doc_type == "wcdw":
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_xm_xmwcdwqk WHERE id = %s LIMIT 1",
                (wcr_id,),
            )
            row = rows[0] if rows else None
            return row, {
                "unit_name": str(_pick_case_insensitive(row or {}, "dwmc", "DWMC") or "").strip(),
                "legal_representative": str(_pick_case_insensitive(row or {}, "fddbr", "FDDBR") or "").strip(),
            }

        if doc_type == "hzdw":
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_xm_gjhzhzdw WHERE ID = %s LIMIT 1",
                (wcr_id,),
            )
            row = rows[0] if rows else None
            return row, {
                "unit_name": str(_pick_case_insensitive(row or {}, "dwmc", "DWMC") or "").strip(),
            }

        if doc_type == "dywcrcns":
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_xm_zywcr WHERE XMBH = %s AND PM = 1 LIMIT 1",
                (project_id,),
            )
            row = rows[0] if rows else None
            return row, {
                "name": str(_pick_case_insensitive(row or {}, "xm", "XM") or "").strip(),
            }

        if doc_type == "dywcdwcns":
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_xm_xmwcdwqk WHERE XMBH = %s AND DWPM = 1 LIMIT 1",
                (project_id,),
            )
            row = rows[0] if rows else None
            return row, {
                "unit_name": str(_pick_case_insensitive(row or {}, "dwmc", "DWMC") or "").strip(),
            }

        if doc_type == "qysm":
            rows = reward_execute(
                "xmsbnew",
                "SELECT * FROM t_qyjscx_qyjbqk WHERE XMBH = %s LIMIT 1",
                (project_id,),
            )
            row = rows[0] if rows else None
            return row, {
                "enterprise_name": str(_pick_case_insensitive(row or {}, "qymc", "QYMC") or "").strip(),
                "legal_representative": str(_pick_case_insensitive(row or {}, "fddbr", "FDDBR") or "").strip(),
            }

        return None, {}

    def _collect_observed_fields(self, result: ReviewResult, doc_type: str) -> Dict[str, str]:
        llm_analysis = result.llm_analysis or {}
        extracted_fields = llm_analysis.get("extracted_fields") or {}
        if not isinstance(extracted_fields, dict):
            extracted_fields = {}

        if doc_type in {"wcr", "wjwcr"}:
            payload = llm_analysis.get("award_contributor_analysis") or {}
            if not isinstance(payload, dict):
                payload = {}
            return {
                "name": str(payload.get("contributor_name") or extracted_fields.get("姓名") or "").strip(),
                "work_unit": str(payload.get("work_unit") or extracted_fields.get("工作单位") or "").strip(),
                "completion_unit": str(payload.get("completion_unit") or extracted_fields.get("完成单位") or "").strip(),
            }

        if doc_type == "wcdw":
            return {
                "unit_name": str(extracted_fields.get("单位名称") or "").strip(),
                "legal_representative": str(extracted_fields.get("法定代表人") or "").strip(),
            }

        if doc_type == "hzdw":
            return {
                "unit_name": str(extracted_fields.get("单位名称") or "").strip(),
            }

        if doc_type == "dywcrcns":
            return {
                "name": str(extracted_fields.get("姓名") or "").strip(),
            }

        if doc_type == "dywcdwcns":
            return {
                "unit_name": str(extracted_fields.get("单位名称") or "").strip(),
            }

        if doc_type == "qysm":
            return {
                "enterprise_name": str(extracted_fields.get("企业名称") or "").strip(),
                "legal_representative": str(extracted_fields.get("法定代表人") or "").strip(),
            }

        return {}

    def _collect_signature_texts(self, result: ReviewResult) -> List[str]:
        values: List[str] = []
        llm_analysis = result.llm_analysis or {}
        payload = llm_analysis.get("award_contributor_analysis") or {}
        if isinstance(payload, dict):
            values.extend(
                [
                    _clean_signature_text(item)
                    for item in payload.get("signature_names", [])
                    if _clean_signature_text(item)
                ]
            )

        signatures_result = llm_analysis.get("signatures_result") or {}
        if isinstance(signatures_result, dict):
            for item in signatures_result.get("signatures", []):
                if isinstance(item, dict):
                    candidate = _clean_signature_text(item.get("text") or item.get("name") or "")
                    if candidate:
                        values.append(candidate)

        for item in result.extracted_data.get("signatures", []):
            if isinstance(item, dict):
                candidate = _clean_signature_text(item.get("text") or item.get("name") or "")
                if candidate:
                    values.append(candidate)
            else:
                candidate = _clean_signature_text(item)
                if candidate:
                    values.append(candidate)

        for check in result.results:
            if getattr(check, "item", "") != "signature":
                continue
            evidence = getattr(check, "evidence", {}) or {}
            if not isinstance(evidence, dict):
                continue
            for item in evidence.get("signatures", []):
                if isinstance(item, dict):
                    candidate = _clean_signature_text(item.get("text") or item.get("name") or "")
                    if candidate:
                        values.append(candidate)
                else:
                    candidate = _clean_signature_text(item)
                    if candidate:
                        values.append(candidate)
        return _dedup(values)

    def _collect_stamp_texts(self, result: ReviewResult) -> List[str]:
        values: List[str] = []
        llm_analysis = result.llm_analysis or {}
        payload = llm_analysis.get("award_contributor_analysis") or {}
        if isinstance(payload, dict):
            values.extend([str(item).strip() for item in payload.get("work_unit_stamp_units", []) if str(item).strip()])
            values.extend([str(item).strip() for item in payload.get("completion_unit_stamp_units", []) if str(item).strip()])
            values.extend([str(item).strip() for item in payload.get("all_stamp_units", []) if str(item).strip()])

        stamps_result = llm_analysis.get("stamps_result") or {}
        if isinstance(stamps_result, dict):
            for item in stamps_result.get("stamps", []):
                if isinstance(item, dict):
                    values.append(str(item.get("text") or item.get("unit") or "").strip())

        for item in result.extracted_data.get("stamps", []):
            if isinstance(item, dict):
                values.append(str(item.get("text") or item.get("unit") or "").strip())
            else:
                values.append(str(item).strip())

        for check in result.results:
            if getattr(check, "item", "") != "stamp":
                continue
            evidence = getattr(check, "evidence", {}) or {}
            if not isinstance(evidence, dict):
                continue
            for item in evidence.get("stamps", []):
                if isinstance(item, dict):
                    values.append(str(item.get("text") or item.get("unit") or "").strip())
                else:
                    values.append(str(item).strip())
        return _dedup(values)

    def _collect_wcr_role_stamp_texts(self, result: ReviewResult) -> Dict[str, List[str]]:
        role_values: Dict[str, List[str]] = {
            "work_unit_stamps": [],
            "completion_unit_stamps": [],
        }
        llm_analysis = result.llm_analysis or {}
        payload = llm_analysis.get("award_contributor_analysis") or {}
        if isinstance(payload, dict):
            role_values["work_unit_stamps"].extend(
                [str(item).strip() for item in payload.get("work_unit_stamp_units", []) if str(item).strip()]
            )
            role_values["completion_unit_stamps"].extend(
                [str(item).strip() for item in payload.get("completion_unit_stamp_units", []) if str(item).strip()]
            )

        for check in result.results:
            if getattr(check, "item", "") == "award_contributor_work_unit_stamp_consistency":
                evidence = getattr(check, "evidence", {}) or {}
                if isinstance(evidence, dict):
                    role_values["work_unit_stamps"].extend(
                        [str(item).strip() for item in (evidence.get("role_stamp_units") or []) if str(item).strip()]
                    )
            elif getattr(check, "item", "") == "award_contributor_completion_unit_stamp_consistency":
                evidence = getattr(check, "evidence", {}) or {}
                if isinstance(evidence, dict):
                    role_values["completion_unit_stamps"].extend(
                        [str(item).strip() for item in (evidence.get("role_stamp_units") or []) if str(item).strip()]
                    )

        return {
            "work_unit_stamps": _dedup(role_values["work_unit_stamps"]),
            "completion_unit_stamps": _dedup(role_values["completion_unit_stamps"]),
        }

    def _collect_verification_result(
        self,
        result: ReviewResult,
        file_data: Optional[bytes],
        doc_type: str,
        target_values: Dict[str, Any],
    ) -> Dict[str, Any]:
        llm_analysis = result.llm_analysis or {}
        if doc_type in {"wcr", "wjwcr"}:
            payload = llm_analysis.get("verification_result") or {}
            if isinstance(payload, dict) and payload:
                return {
                    "name": self._normalize_verification_entry(payload.get("name")),
                    "signature_for_name": self._normalize_verification_entry(payload.get("signature_for_name")),
                    "work_unit": self._normalize_verification_entry(payload.get("work_unit")),
                    "completion_unit": self._normalize_verification_entry(payload.get("completion_unit")),
                    "work_unit_stamp": self._normalize_verification_entry(payload.get("work_unit_stamp")),
                    "completion_unit_stamp": self._normalize_verification_entry(payload.get("completion_unit_stamp")),
                }
            return {}
        if doc_type == "dywcrcns":
            payload = llm_analysis.get("verification_result") or {}
            if isinstance(payload, dict) and payload:
                return {
                    "signature_for_name": self._normalize_verification_entry(payload.get("signature_for_name")),
                }
            return {}
        if doc_type == "qysm":
            payload = llm_analysis.get("verification_result") or {}
            if isinstance(payload, dict) and payload:
                return {
                    "legal_representative_signature": self._normalize_verification_entry(payload.get("legal_representative_signature")),
                }
            return {}
        return self._build_verification_result(file_data=file_data, doc_type=doc_type, target_values=target_values)

    def _build_verification_result(
        self,
        file_data: Optional[bytes],
        doc_type: str,
        target_values: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not file_data or not target_values:
            return {}
        if doc_type in QTFJCL_DOC_TYPES:
            return {}
        try:
            return self._verify_generic_reward_doc(file_data, doc_type, target_values)
        except Exception:
            logger.exception("奖励材料定向验证失败: doc_type=%s", doc_type)
            return {}

    def _verify_generic_reward_doc(self, file_data: bytes, doc_type: str, target_values: Dict[str, Any]) -> Dict[str, Any]:
        image_data = self._pdf_to_image(file_data)
        if doc_type == "tjdwyj":
            prompt = """请只根据图像判断：页面中是否存在与目标单位一致的红色公章。
目标单位：%s

返回严格 JSON：
{"nomination_unit_stamp": {"status": "yes|no|uncertain", "reason": ""}}

规则：
1. yes 仅表示可以清晰确认红章与目标单位一致。
2. no 表示未见对应红章或可清晰确认不一致。
3. uncertain 表示看不清。""" % (str(target_values.get("nomination_unit_name") or "").strip() or "空")
            payload = self._run_multimodal_json(image_data, prompt)
            return {"nomination_unit_stamp": self._normalize_verification_entry(payload.get("nomination_unit_stamp"))}

        if doc_type == "gzdwyj":
            prompt = """请只根据图像判断：页面中是否存在与目标单位一致的红色公章。
目标单位：%s

返回严格 JSON：
{"candidate_work_unit_stamp": {"status": "yes|no|uncertain", "reason": ""}}

规则同上，只判断红章，不要把打印文字当公章。""" % (
                str(target_values.get("candidate_work_unit_name") or "").strip() or "空"
            )
            payload = self._run_multimodal_json(image_data, prompt)
            return {"candidate_work_unit_stamp": self._normalize_verification_entry(payload.get("candidate_work_unit_stamp"))}

        if doc_type == "wcdw":
            prompt = """请只根据图像判断下列字段是否与目标值一致：
- 单位名称：%s
- 法定代表人：%s

返回严格 JSON：
{
  "unit_name": {"status": "yes|no|uncertain", "reason": ""},
  "legal_representative": {"status": "yes|no|uncertain", "reason": ""}
}

规则：
1. yes 仅表示可以清晰确认字段值一致。
2. no 表示可清晰确认不一致或未见该字段值。
3. uncertain 表示看不清。""" % (
                str(target_values.get("unit_name") or "").strip() or "空",
                str(target_values.get("legal_representative") or "").strip() or "空",
            )
            payload = self._run_multimodal_json(image_data, prompt)
            return {
                "unit_name": self._normalize_verification_entry(payload.get("unit_name")),
                "legal_representative": self._normalize_verification_entry(payload.get("legal_representative")),
            }

        if doc_type == "hzdw":
            prompt = """请只根据图像判断下列字段是否与目标值一致：
目标单位名称：%s

返回严格 JSON：
{"unit_name": {"status": "yes|no|uncertain", "reason": ""}}""" % (
                str(target_values.get("unit_name") or "").strip() or "空"
            )
            payload = self._run_multimodal_json(image_data, prompt)
            return {"unit_name": self._normalize_verification_entry(payload.get("unit_name"))}

        return {}

    def _pdf_to_image(self, file_data: bytes) -> bytes:
        if not file_data.startswith(b"%PDF"):
            return file_data
        try:
            import fitz

            doc = fitz.open(stream=file_data, filetype="pdf")
            if doc.page_count <= 0:
                return file_data
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            image_data = pix.tobytes("png")
            doc.close()
            return image_data
        except Exception:
            return file_data

    def _run_multimodal_json(self, image_data: bytes, prompt: str) -> Dict[str, Any]:
        async def _run() -> str:
            from src.common.llm import get_review_llm_client
            from src.common.vision.multimodal import MultimodalLLM

            llm = MultimodalLLM(get_review_llm_client())
            return await asyncio.wait_for(llm.analyze_image(image_data, prompt), timeout=45)

        raw = asyncio.run(_run())
        return self._parse_json_object(raw)

    def _parse_json_object(self, raw_text: Any) -> Dict[str, Any]:
        text = str(raw_text or "").strip()
        if not text:
            return {}
        if text.startswith("```"):
            parts = text.split("```", 2)
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _normalize_verification_entry(self, payload: Any) -> Dict[str, str]:
        if isinstance(payload, str):
            status = str(payload or "").strip().lower()
            if status in {"yes", "no", "uncertain"}:
                return {"status": status, "reason": ""}
            return {}
        if not isinstance(payload, dict):
            return {}
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"yes", "no", "uncertain"}:
            return {}
        return {
            "status": status,
            "reason": str(payload.get("reason") or "").strip(),
        }

    def _verification_status(self, entry: Any) -> str:
        if isinstance(entry, dict):
            status = str(entry.get("status") or "").strip().lower()
            if status in {"yes", "no", "uncertain"}:
                return status
        return ""

    def _compare_field(
        self,
        item: str,
        label: str,
        observed: str,
        expected: str,
        verification: Optional[Dict[str, str]] = None,
    ) -> CheckResult:
        verification_status = self._verification_status(verification)
        raw_state = _raw_db_field_state(expected, observed)
        evidence = {
            "observed": observed,
            "expected": expected,
            "raw_state": raw_state,
            "verification_status": verification_status,
        }
        if verification:
            evidence["verification"] = verification
        if not expected:
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"奖励库未提供可核验的{label}",
                evidence=evidence,
            )
        if raw_state == "match":
            if verification_status in {"", "yes"}:
                return CheckResult(
                    item=item,
                    status=CheckStatus.PASSED,
                    message=f"表单{label}与奖励库记录一致",
                    evidence=evidence,
                )
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"表单{label}结果需复核",
                evidence=evidence,
            )
        if raw_state == "mismatch":
            if verification_status == "no":
                return CheckResult(
                    item=item,
                    status=CheckStatus.FAILED,
                    message=f"表单{label}与奖励库记录不一致",
                    evidence=evidence,
                )
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"表单{label}疑似与奖励库记录不一致，请复核",
                evidence=evidence,
            )
        if raw_state == "partial_match":
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"表单{label}仅部分匹配奖励库记录，请复核",
                evidence=evidence,
            )
        return CheckResult(
            item=item,
            status=CheckStatus.WARNING,
            message=f"表单{label}结果需复核" if verification_status == "yes" else f"表单{label}疑似与奖励库记录不一致，请复核",
            evidence=evidence,
        )

    def _compare_named_signature(
        self,
        item: str,
        label: str,
        expected_name: str,
        signature_names: List[str],
        verification: Optional[Dict[str, str]] = None,
    ) -> CheckResult:
        verification_status = self._verification_status(verification)
        raw_state = _raw_candidate_state(expected_name, signature_names)
        evidence: Dict[str, Any] = {
            "expected_name": expected_name,
            "signature_names": signature_names,
            "raw_state": raw_state,
            "verification_status": verification_status,
        }
        if verification:
            evidence["verification"] = verification
        if raw_state == "match":
            return CheckResult(
                item=item,
                status=CheckStatus.PASSED,
                message=f"{label}“{expected_name}”与签字/签章一致",
                evidence=evidence,
            )
        if verification_status == "yes":
            return CheckResult(
                item=item,
                status=CheckStatus.PASSED,
                message=f"{label}“{expected_name}”与签字/签章一致",
                evidence=evidence,
            )
        if verification_status == "no":
            return CheckResult(
                item=item,
                status=CheckStatus.FAILED,
                message=f"{label}“{expected_name}”与签字/签章不一致",
                evidence=evidence,
            )
        if raw_state == "mismatch":
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"{label}“{expected_name}”与签字/签章疑似不一致，请复核",
                evidence=evidence,
            )
        return CheckResult(
            item=item,
            status=CheckStatus.WARNING,
            message=f"{label}“{expected_name}”与签字/签章结果需复核"
            if verification_status == "yes"
            else f"{label}“{expected_name}”与签字/签章疑似不一致，请复核",
            evidence=evidence,
        )

    def _compare_candidates(
        self,
        item: str,
        label: str,
        expected: str,
        candidates: List[str],
        verification: Optional[Dict[str, str]] = None,
    ) -> CheckResult:
        verification_status = self._verification_status(verification)
        raw_state = _raw_candidate_state(expected, candidates)
        evidence = {
            "expected": expected,
            "candidates": candidates,
            "raw_state": raw_state,
            "verification_status": verification_status,
        }
        if verification:
            evidence["verification"] = verification
        if not expected:
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"奖励库未提供可核验的{label}",
                evidence=evidence,
            )
        if raw_state == "match":
            if verification_status in {"", "yes"}:
                return CheckResult(
                    item=item,
                    status=CheckStatus.PASSED,
                    message=f"{label}与奖励库记录一致",
                    evidence=evidence,
                )
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"{label}结果需复核",
                evidence=evidence,
            )
        if raw_state == "mismatch":
            if verification_status == "no":
                return CheckResult(
                    item=item,
                    status=CheckStatus.FAILED,
                    message=f"{label}与奖励库记录不一致",
                    evidence=evidence,
                )
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"{label}疑似与奖励库记录不一致，请复核",
                evidence=evidence,
            )
        return CheckResult(
            item=item,
            status=CheckStatus.WARNING,
            message=f"{label}结果需复核" if verification_status == "yes" else f"{label}疑似与奖励库记录不一致，请复核",
            evidence=evidence,
        )

    def _extract_item_status(self, result: ReviewResult, item_name: str) -> int:
        for item in result.results:
            if item.item == item_name:
                if item.status == CheckStatus.PASSED:
                    return 1
                if item.status == CheckStatus.FAILED:
                    return 0
        return -1

    def _extract_item_evidence(self, result: ReviewResult, item_name: str) -> Dict[str, Any]:
        for item in result.results:
            if item.item == item_name:
                return dict(item.evidence or {})
        return {}

    def _replace_result_item(self, result: ReviewResult, item_name: str, replacement: CheckResult) -> None:
        for index, item in enumerate(result.results):
            if item.item == item_name:
                result.results[index] = replacement
                return

    def _compare_award_contributor_signature(
        self,
        expected_name: str,
        contributor_name: str,
        signature_names: List[str],
        verification: Optional[Dict[str, str]] = None,
    ) -> CheckResult:
        verification_status = self._verification_status(verification)
        contributor_state = _raw_field_state(expected_name, contributor_name)
        signature_state = _raw_candidate_state(expected_name, signature_names)
        if contributor_state == "match" and signature_state == "match":
            raw_state = "match"
        elif contributor_state == "mismatch" or signature_state == "mismatch":
            raw_state = "mismatch"
        else:
            raw_state = "unknown"
        evidence: Dict[str, Any] = {
            "expected_name": expected_name,
            "contributor_name": contributor_name,
            "signature_names": signature_names,
            "raw_state": raw_state,
            "verification_status": verification_status,
        }
        if verification:
            evidence["verification"] = verification

        # 条件串行：
        # 1. 先用抽取结果直接和奖励库比，命中就直接通过；
        # 2. 只有抽取没过时，才使用“是否是 xxx”的定向验证兜底。
        if raw_state == "match":
            return CheckResult(
                item="award_contributor_signature_consistency",
                status=CheckStatus.PASSED,
                message=f"完成人“{expected_name}”与本人签名一致",
                evidence=evidence,
            )

        if verification_status == "yes":
            return CheckResult(
                item="award_contributor_signature_consistency",
                status=CheckStatus.PASSED,
                message=f"完成人“{expected_name}”与本人签名一致",
                evidence=evidence,
            )
        if verification_status == "no":
            return CheckResult(
                item="award_contributor_signature_consistency",
                status=CheckStatus.FAILED,
                message=f"完成人“{expected_name or contributor_name}”与本人签名不一致",
                evidence=evidence,
            )

        if raw_state == "mismatch":
            return CheckResult(
                item="award_contributor_signature_consistency",
                status=CheckStatus.WARNING,
                message=f"完成人“{expected_name}”与本人签名疑似不一致，请复核",
                evidence=evidence,
            )
        return CheckResult(
            item="award_contributor_signature_consistency",
            status=CheckStatus.WARNING,
            message=f"完成人“{expected_name or contributor_name}”与本人签名结果需复核",
            evidence=evidence,
        )

    def _compare_role_stamp_consistency(
        self,
        item: str,
        role_label: str,
        expected_unit: str,
        role_units: List[str],
        verification: Optional[Dict[str, str]] = None,
    ) -> CheckResult:
        verification_status = self._verification_status(verification)
        raw_state = _raw_candidate_state(expected_unit, role_units)
        evidence: Dict[str, Any] = {
            "expected_unit": expected_unit,
            "role_stamp_units": role_units,
            "raw_state": raw_state,
            "verification_status": verification_status,
        }
        if verification:
            evidence["verification"] = verification

        if raw_state == "match" and verification_status in {"", "yes"}:
            return CheckResult(
                item=item,
                status=CheckStatus.PASSED,
                message=f"{role_label}“{expected_unit}”与对应公章一致",
                evidence=evidence,
            )
        if raw_state == "match":
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"{role_label}“{expected_unit}”与对应公章结果需复核",
                evidence=evidence,
            )
        if raw_state == "mismatch" and verification_status == "no":
            return CheckResult(
                item=item,
                status=CheckStatus.FAILED,
                message=f"{role_label}“{expected_unit}”与对应公章不一致",
                evidence=evidence,
            )
        if raw_state == "mismatch":
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"{role_label}“{expected_unit}”与对应公章疑似不一致，请复核",
                evidence=evidence,
            )
        return CheckResult(
            item=item,
            status=CheckStatus.WARNING,
            message=f"{role_label}“{expected_unit}”与对应公章结果需复核"
            if verification_status == "yes"
            else f"{role_label}“{expected_unit}”与对应公章疑似不一致，请复核",
            evidence=evidence,
        )

    def _apply_wcr_recognition_overrides(self, result: ReviewResult, verification: Dict[str, Any]) -> None:
        signature_item = self._extract_item_evidence(result, "signature")
        signature_verification = verification.get("signature_for_name")
        signature_verification_status = self._verification_status(signature_verification)
        for check in result.results:
            if check.item != "signature":
                continue
            evidence = dict(signature_item or check.evidence or {})
            if signature_verification:
                evidence["verification"] = signature_verification
            if check.status == CheckStatus.FAILED and signature_verification_status in {"yes", "uncertain"}:
                check.status = CheckStatus.WARNING
                check.message = "签字识别结果需复核"
                check.evidence = evidence
            elif check.status == CheckStatus.PASSED and signature_verification_status == "no":
                check.status = CheckStatus.WARNING
                check.message = "签字识别结果疑似不一致，请复核"
                check.evidence = evidence
            break

        stamp_verifications = {
            key: value
            for key, value in {
                "work_unit_stamp": verification.get("work_unit_stamp"),
                "completion_unit_stamp": verification.get("completion_unit_stamp"),
            }.items()
            if value
        }
        stamp_verification_statuses = {self._verification_status(value) for value in stamp_verifications.values()}
        for check in result.results:
            if check.item != "stamp":
                continue
            evidence = dict(check.evidence or {})
            if stamp_verifications:
                evidence["verification"] = stamp_verifications
            if check.status == CheckStatus.FAILED and ("yes" in stamp_verification_statuses or "uncertain" in stamp_verification_statuses):
                check.status = CheckStatus.WARNING
                check.message = "印章识别结果需复核"
                check.evidence = evidence
            elif check.status == CheckStatus.PASSED and "no" in stamp_verification_statuses:
                check.status = CheckStatus.WARNING
                check.message = "印章识别结果疑似不一致，请复核"
                check.evidence = evidence
            break

    def _apply_verification_to_existing_results(
        self,
        result: ReviewResult,
        doc_type: str,
        target_values: Dict[str, Any],
        observed_fields: Dict[str, str],
        signatures: List[str],
        verification: Dict[str, Any],
    ) -> None:
        if doc_type not in {"wcr", "wjwcr"}:
            return

        expected_name = str(target_values.get("name") or "").strip()
        contributor_name = str(observed_fields.get("name") or "").strip()
        signature_result = self._compare_award_contributor_signature(
            expected_name=expected_name,
            contributor_name=contributor_name,
            signature_names=signatures,
            verification=verification.get("signature_for_name"),
        )
        self._replace_result_item(result, "award_contributor_signature_consistency", signature_result)

        work_item = self._extract_item_evidence(result, "award_contributor_work_unit_stamp_consistency")
        work_units = _dedup([str(item).strip() for item in (work_item.get("role_stamp_units") or []) if str(item).strip()])
        work_result = self._compare_role_stamp_consistency(
            item="award_contributor_work_unit_stamp_consistency",
            role_label="工作单位",
            expected_unit=str(target_values.get("work_unit") or "").strip(),
            role_units=work_units,
            verification=verification.get("work_unit_stamp"),
        )
        work_result.evidence.update({"same_unit": bool(work_item.get("same_unit"))})
        self._replace_result_item(result, "award_contributor_work_unit_stamp_consistency", work_result)

        completion_item = self._extract_item_evidence(result, "award_contributor_completion_unit_stamp_consistency")
        completion_units = _dedup([str(item).strip() for item in (completion_item.get("role_stamp_units") or []) if str(item).strip()])
        completion_result = self._compare_role_stamp_consistency(
            item="award_contributor_completion_unit_stamp_consistency",
            role_label="完成单位",
            expected_unit=str(target_values.get("completion_unit") or "").strip(),
            role_units=completion_units,
            verification=verification.get("completion_unit_stamp"),
        )
        completion_result.evidence.update({"same_unit": bool(completion_item.get("same_unit"))})
        self._replace_result_item(result, "award_contributor_completion_unit_stamp_consistency", completion_result)
        self._apply_wcr_recognition_overrides(result, verification)

    def _filter_items(self, results: List[CheckResult], effective_items: set[str]) -> List[CheckResult]:
        if not effective_items:
            return results
        return [item for item in results if item.item in effective_items]

    def _generate_summary(self, results: List[CheckResult]) -> str:
        passed = sum(1 for item in results if item.status == CheckStatus.PASSED)
        failed = sum(1 for item in results if item.status == CheckStatus.FAILED)
        warnings = sum(1 for item in results if item.status == CheckStatus.WARNING)
        return f"审查完成：通过 {passed} 项，失败 {failed} 项，警告 {warnings} 项"

    def _generate_suggestions(self, results: List[CheckResult]) -> List[str]:
        suggestions: List[str] = []
        for item in results:
            if item.status == CheckStatus.FAILED:
                suggestions.append(f"请检查：{item.item} - {item.message}")
            elif item.status == CheckStatus.WARNING:
                suggestions.append(f"注意：{item.item} - {item.message}")
        return suggestions

    def _build_structured_result(
        self,
        result: ReviewResult,
        context: Dict[str, Any],
        observed_fields: Dict[str, str],
        signatures: List[str],
        stamps: List[str],
        verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_doc_type = normalize_doc_type(result.doc_type)
        target_values = context.get("target_values", {}) or {}
        attachment = context.get("attachment_record") or {}
        llm_analysis = result.llm_analysis or {}

        counts = {
            "passed": sum(1 for item in result.results if item.status == CheckStatus.PASSED),
            "failed": sum(1 for item in result.results if item.status == CheckStatus.FAILED),
            "warning": sum(1 for item in result.results if item.status == CheckStatus.WARNING),
        }

        recognized: Dict[str, Any] = {
            "signatures": signatures,
            "fields": observed_fields,
            "notes": list((llm_analysis.get("award_contributor_analysis") or {}).get("notes", []))
            if isinstance(llm_analysis.get("award_contributor_analysis"), dict)
            else [],
        }
        if normalized_doc_type in {"wcr", "wjwcr"}:
            recognized.update(self._collect_wcr_role_stamp_texts(result))
        else:
            recognized["stamps"] = stamps

        return {
            "overview": {
                "doc_type": normalized_doc_type,
                "doc_type_label": get_doc_type_label(normalized_doc_type),
                "summary": result.summary,
                "status_counts": counts,
            },
            "recognized": recognized,
            "verification": verification,
            "db_binding": {
                "project_id": context.get("project_id", ""),
                "matched_attachment": bool(attachment),
                "attachment": {
                    "id": str(_pick_case_insensitive(attachment, "id") or ""),
                    "lx": str(_pick_case_insensitive(attachment, "LX", "lx") or ""),
                    "xh": _pick_case_insensitive(attachment, "XH", "xh"),
                    "file_name": str(_pick_case_insensitive(attachment, "FJLJ", "fjlj") or ""),
                    "title": str(_pick_case_insensitive(attachment, "FJMC", "fjmc") or ""),
                    "wcr_id": str(_pick_case_insensitive(attachment, "wcr_id", "WCR_ID") or ""),
                },
                "target_values": target_values,
                "errors": [str(item) for item in context.get("errors", []) if str(item).strip()],
            },
            "checks": self._build_structured_checks(result.results),
        }

    def _build_structured_checks(self, results: List[CheckResult]) -> Dict[str, Any]:
        grouped = {
            "recognition": [],
            "form_consistency": [],
            "database_consistency": [],
            "system": [],
        }
        for item in results:
            payload = {
                "code": item.item,
                "label": self._item_label(item.item),
                "status": item.status.value,
                "message": item.message,
                "evidence": dict(item.evidence or {}),
            }
            if item.item in {"signature", "stamp"}:
                grouped["recognition"].append(payload)
            elif item.item in {
                "award_contributor_signature_consistency",
                "award_contributor_work_unit_stamp_consistency",
                "award_contributor_completion_unit_stamp_consistency",
                "nomination_unit_stamp_consistency",
                "candidate_work_unit_stamp_consistency",
                "completion_unit_name_consistency",
                "completion_unit_legal_representative_consistency",
                "cooperation_unit_name_consistency",
                "first_contributor_signature_consistency",
                "first_completion_unit_stamp_consistency",
                "enterprise_stamp_consistency",
                "enterprise_legal_representative_signature_consistency",
            }:
                grouped["form_consistency"].append(payload)
            elif item.item.startswith("contributor_db_"):
                grouped["database_consistency"].append(payload)
            else:
                grouped["system"].append(payload)
        return grouped

    def _item_label(self, item: str) -> str:
        labels = {
            "signature": "签字识别",
            "stamp": "盖章识别",
            "award_contributor_signature_consistency": "姓名与签字一致性",
            "award_contributor_work_unit_stamp_consistency": "工作单位与公章一致性",
            "award_contributor_completion_unit_stamp_consistency": "完成单位与公章一致性",
            "contributor_db_name_consistency": "姓名与奖励库一致性",
            "contributor_db_work_unit_consistency": "工作单位与奖励库一致性",
            "contributor_db_completion_unit_consistency": "完成单位与奖励库一致性",
            "nomination_unit_stamp_consistency": "提名单位公章与奖励库一致性",
            "candidate_work_unit_stamp_consistency": "候选人工作单位公章与奖励库一致性",
            "completion_unit_name_consistency": "单位名称与奖励库一致性",
            "completion_unit_legal_representative_consistency": "法定代表人与奖励库一致性",
            "cooperation_unit_name_consistency": "合作单位名称与奖励库一致性",
            "first_contributor_signature_consistency": "第一完成人签字与奖励库一致性",
            "first_completion_unit_stamp_consistency": "第一完成单位公章与奖励库一致性",
            "enterprise_stamp_consistency": "企业公章与奖励库一致性",
            "enterprise_legal_representative_signature_consistency": "法定代表人签字/签章与奖励库一致性",
            "reward_db_context": "奖励库关联",
        }
        return labels.get(item, item)
