"""奖励平台单文件审查增强服务。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import PureWindowsPath
from typing import Any, Dict, List, Optional

from src.common.database.connection import reward_execute, reward_execute_write
from src.common.models import CheckResult, CheckStatus, ReviewResult
from src.services.review.doc_types import get_doc_type_label, normalize_doc_type

logger = logging.getLogger(__name__)


REWARD_PATH_DOC_TYPES = {"tjdwyj", "gzdwyj", "wcr", "wjwcr", "wcdw", "hzdw"}

DOC_TYPE_TO_LX = {
    "tjdwyj": "10.1",
    "gzdwyj": "10.2",
    "wcr": "10.3",
    "wjwcr": "10.3",
    "wcdw": "10.4",
    "hzdw": "10.5",
}


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/]", "", text).lower()


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
                context["errors"].append("未匹配到 t_xm_gzy 附件记录")
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
    ) -> ReviewResult:
        normalized_doc_type = normalize_doc_type(result.doc_type)
        effective_items = {str(item).strip() for item in (check_items or []) if str(item).strip()}

        observed_fields = self._collect_observed_fields(result, normalized_doc_type)
        signatures = self._collect_signature_texts(result)
        stamps = self._collect_stamp_texts(result)

        result.extracted_data["reward_project_id"] = context.get("project_id", "")
        result.extracted_data["reward_recognized_signatures"] = signatures
        result.extracted_data["reward_recognized_stamps"] = stamps
        result.extracted_data["reward_target_values"] = context.get("target_values", {})

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
                        ),
                        self._compare_field(
                            item="contributor_db_work_unit_consistency",
                            label="工作单位",
                            observed=observed_fields.get("work_unit", ""),
                            expected=str(target_values.get("work_unit") or ""),
                        ),
                        self._compare_field(
                            item="contributor_db_completion_unit_consistency",
                            label="完成单位",
                            observed=observed_fields.get("completion_unit", ""),
                            expected=str(target_values.get("completion_unit") or ""),
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
                        ),
                        self._compare_field(
                            item="completion_unit_legal_representative_consistency",
                            label="法定代表人",
                            observed=observed_fields.get("legal_representative", ""),
                            expected=str(target_values.get("legal_representative") or ""),
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
                        ),
                    ],
                    effective_items,
                )
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
        )
        return result

    def persist_recognition(self, context: Dict[str, Any], result: ReviewResult) -> None:
        attachment = context.get("attachment_record") or {}
        row_id = str(_pick_case_insensitive(attachment, "id") or "").strip()
        if not row_id:
            return

        signature_status = self._extract_item_status(result, "signature")
        stamp_status = self._extract_item_status(result, "stamp")
        signature_info = {
            "recognized": self._collect_signature_texts(result),
            "result": self._extract_item_evidence(result, "signature"),
        }
        stamp_info = {
            "recognized": self._collect_stamp_texts(result),
            "result": self._extract_item_evidence(result, "stamp"),
        }

        sql = """
        UPDATE t_xm_gzy
        SET signature_check = %s,
            signature_info = %s,
            seal_check = %s,
            seal_info = %s
        WHERE id = %s
        """
        try:
            reward_execute_write(
                "xmsbnew",
                sql,
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

        base_sql = """
        SELECT g.*, gg.XMTJH
        FROM t_xm_gzy g
        LEFT JOIN t_xm_ggjbxx gg ON gg.XMBH = g.XMBH
        WHERE g.XMBH = %s
          AND g.LX = %s
          AND g.FJLJ = %s
        """
        attempts: List[tuple[str, tuple[Any, ...]]] = []
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
                SELECT gg.*, td.*
                FROM t_xm_ggjbxx gg
                LEFT JOIN t_xm_tjdwxx td ON td.TJDWBH = gg.TJDWBH AND td.ND = gg.ND
                WHERE gg.XMBH = %s
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

        return {}

    def _collect_signature_texts(self, result: ReviewResult) -> List[str]:
        values: List[str] = []
        llm_analysis = result.llm_analysis or {}
        payload = llm_analysis.get("award_contributor_analysis") or {}
        if isinstance(payload, dict):
            values.extend([str(item).strip() for item in payload.get("signature_names", []) if str(item).strip()])

        signatures_result = llm_analysis.get("signatures_result") or {}
        if isinstance(signatures_result, dict):
            for item in signatures_result.get("signatures", []):
                if isinstance(item, dict):
                    values.append(str(item.get("text") or "").strip())

        for item in result.extracted_data.get("signatures", []):
            if isinstance(item, dict):
                values.append(str(item.get("text") or "").strip())
            else:
                values.append(str(item).strip())
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
        return _dedup(values)

    def _compare_field(self, item: str, label: str, observed: str, expected: str) -> CheckResult:
        if not expected:
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"奖励库未提供可核验的{label}",
                evidence={"observed": observed, "expected": expected},
            )
        if not observed:
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"未识别到表单中的{label}",
                evidence={"observed": observed, "expected": expected},
            )
        if not _matches(expected, [observed]):
            return CheckResult(
                item=item,
                status=CheckStatus.FAILED,
                message=f"表单{label}与奖励库记录不一致",
                evidence={"observed": observed, "expected": expected},
            )
        return CheckResult(
            item=item,
            status=CheckStatus.PASSED,
            message=f"表单{label}与奖励库记录一致",
            evidence={"observed": observed, "expected": expected},
        )

    def _compare_candidates(self, item: str, label: str, expected: str, candidates: List[str]) -> CheckResult:
        if not expected:
            return CheckResult(
                item=item,
                status=CheckStatus.WARNING,
                message=f"奖励库未提供可核验的{label}",
                evidence={"expected": expected, "candidates": candidates},
            )
        if not candidates:
            return CheckResult(
                item=item,
                status=CheckStatus.FAILED,
                message=f"未识别到可用于核验的{label}文字",
                evidence={"expected": expected, "candidates": candidates},
            )
        if not _matches(expected, candidates):
            return CheckResult(
                item=item,
                status=CheckStatus.FAILED,
                message=f"{label}与奖励库记录不一致",
                evidence={"expected": expected, "candidates": candidates},
            )
        return CheckResult(
            item=item,
            status=CheckStatus.PASSED,
            message=f"{label}与奖励库记录一致",
            evidence={"expected": expected, "candidates": candidates},
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

        return {
            "overview": {
                "doc_type": normalized_doc_type,
                "doc_type_label": get_doc_type_label(normalized_doc_type),
                "summary": result.summary,
                "status_counts": counts,
            },
            "recognized": {
                "signatures": signatures,
                "stamps": stamps,
                "fields": observed_fields,
                "notes": list((llm_analysis.get("award_contributor_analysis") or {}).get("notes", []))
                if isinstance(llm_analysis.get("award_contributor_analysis"), dict)
                else [],
            },
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
            "reward_db_context": "奖励库关联",
        }
        return labels.get(item, item)
