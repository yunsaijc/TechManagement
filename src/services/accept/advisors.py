"""辅助判定器：为规则引擎提供可替换的弱监督建议。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

try:
    from openai import LengthFinishReasonError
except Exception:  # pragma: no cover - openai SDK 版本差异
    LengthFinishReasonError = None  # type: ignore[assignment]

try:
    from langchain_core.messages import HumanMessage, SystemMessage
except Exception:  # pragma: no cover - 依赖缺失时自动降级
    HumanMessage = None  # type: ignore[assignment]
    SystemMessage = None  # type: ignore[assignment]

from src.common.llm import get_default_llm_client, llm_config


logger = logging.getLogger(__name__)


class DocumentRoleProbeResult(BaseModel):
    """文档角色弱监督输出。"""

    is_artifact_like: bool | None = Field(default=None)
    is_summary_like: bool | None = Field(default=None)
    confidence: float = Field(default=0.0)
    rationale: str = Field(default="", max_length=120)


class ArtifactEquivalenceProbeResult(BaseModel):
    """成果同一性弱监督输出。"""

    same_artifact: bool | None = Field(default=None)
    confidence: float = Field(default=0.0)
    rationale: str = Field(default="", max_length=120)


@dataclass(frozen=True)
class EvidenceAdvisory:
    is_artifact_like: bool | None = None
    is_summary_like: bool | None = None
    same_artifact_as: str = ""
    rationale: str = ""


class AcceptanceAdvisoryEngine:
    """优先轻规则，模糊场景下再使用 LLM 做弱监督建议。"""

    def __init__(self, *, llm: Any | None = None) -> None:
        self._llm = llm
        self._llm_ready = llm is not None
        self._llm_disabled = os.getenv("ACCEPT_ENABLE_LLM_ADVISORY", "false").strip().lower() not in {"1", "true", "yes", "on"}
        self._doc_role_cache: dict[tuple[str, str, str, str], EvidenceAdvisory] = {}
        self._equivalence_cache: dict[tuple[str, str], EvidenceAdvisory] = {}

    def advise_document_role(
        self,
        *,
        doc_kind: str,
        title: str,
        excerpt: str,
        metric_name: str,
    ) -> EvidenceAdvisory:
        key = (
            (doc_kind or "").strip(),
            (metric_name or "").strip(),
            (title or "").strip()[:240],
            (excerpt or "").strip()[:800],
        )
        cached = self._doc_role_cache.get(key)
        if cached is not None:
            return cached

        heuristic = self._rule_based_document_role(
            doc_kind=doc_kind,
            title=title,
            excerpt=excerpt,
            metric_name=metric_name,
        )
        if not self._should_consult_llm_for_document_role(
            heuristic=heuristic,
            doc_kind=doc_kind,
            title=title,
            excerpt=excerpt,
            metric_name=metric_name,
        ):
            self._doc_role_cache[key] = heuristic
            return heuristic

        llm_advisory = self._probe_document_role_with_llm(
            doc_kind=doc_kind,
            title=title,
            excerpt=excerpt,
            metric_name=metric_name,
        )
        result = self._merge_document_role_advisory(heuristic, llm_advisory)
        self._doc_role_cache[key] = result
        return result

    def advise_artifact_equivalence(
        self,
        *,
        left_title: str,
        right_title: str,
    ) -> EvidenceAdvisory:
        key = ((left_title or "").strip(), (right_title or "").strip())
        cached = self._equivalence_cache.get(key)
        if cached is not None:
            return cached

        heuristic = self._rule_based_artifact_equivalence(
            left_title=left_title,
            right_title=right_title,
        )
        if not self._should_consult_llm_for_equivalence(left_title=left_title, right_title=right_title, heuristic=heuristic):
            self._equivalence_cache[key] = heuristic
            return heuristic

        llm_advisory = self._probe_artifact_equivalence_with_llm(
            left_title=left_title,
            right_title=right_title,
        )
        result = heuristic
        if llm_advisory.same_artifact_as:
            result = EvidenceAdvisory(
                same_artifact_as=llm_advisory.same_artifact_as,
                rationale=self._combine_rationales(heuristic.rationale, llm_advisory.rationale),
            )
        self._equivalence_cache[key] = result
        return result

    def _rule_based_document_role(
        self,
        *,
        doc_kind: str,
        title: str,
        excerpt: str,
        metric_name: str,
    ) -> EvidenceAdvisory:
        blob = f"{title} {excerpt}"
        if metric_name in {"研究报告", "决策咨询报告", "科技报告"}:
            if any(token in blob for token in ("验收自评价", "自评价报告", "完成情况")):
                return EvidenceAdvisory(is_summary_like=True, rationale="命中总结类特征")
            if len(title.strip()) >= 8 and any(token in excerpt for token in ("一、", "二、", "三、", "建议", "报告", "研究")):
                return EvidenceAdvisory(is_artifact_like=True, rationale="命中报告正文类特征")
            if "目录" in excerpt and len(title.strip()) >= 8 and any(token in title for token in ("研究", "建议", "报告", "发展")):
                return EvidenceAdvisory(is_artifact_like=True, rationale="目录页但标题像正式报告")
            if any(token in blob for token in ("目录", "摘要")):
                return EvidenceAdvisory(is_summary_like=True, rationale="命中目录/摘要类特征")
        if metric_name == "科技论文":
            if any(token in blob for token in ("学报", "Journal", "doi", "摘要", "关键词")):
                return EvidenceAdvisory(is_artifact_like=True, rationale="命中论文正文类特征")
        if metric_name in {"发明专利", "实用新型专利"}:
            if any(token in blob for token in ("专利证书", "申请号", "专利号", "授权公告号")):
                return EvidenceAdvisory(is_artifact_like=True, rationale="命中专利证据类特征")
        if doc_kind in {"审计报告", "检测报告", "技术合同", "发票"}:
            return EvidenceAdvisory(is_artifact_like=True, rationale="命中证明材料类文档")
        return EvidenceAdvisory()

    def _rule_based_artifact_equivalence(
        self,
        *,
        left_title: str,
        right_title: str,
    ) -> EvidenceAdvisory:
        left = "".join((left_title or "").split()).lower()
        right = "".join((right_title or "").split()).lower()
        if left and right and (left in right or right in left):
            return EvidenceAdvisory(same_artifact_as=right_title, rationale="标题存在包含关系")
        return EvidenceAdvisory()

    def _should_consult_llm_for_document_role(
        self,
        *,
        heuristic: EvidenceAdvisory,
        doc_kind: str,
        title: str,
        excerpt: str,
        metric_name: str,
    ) -> bool:
        if heuristic.is_artifact_like or heuristic.is_summary_like:
            if "目录" not in excerpt and "摘要" not in excerpt:
                return False
            if heuristic.is_summary_like:
                return False
            if heuristic.is_artifact_like and len(title.strip()) >= 8 and any(token in excerpt for token in ("一、", "二、", "三、", "报告", "研究", "建议")):
                return False
        if metric_name not in {"研究报告", "决策咨询报告", "科技报告", "科技论文", "发明专利", "实用新型专利"}:
            return False
        blob = f"{title} {excerpt}"
        if not blob.strip():
            return False
        ambiguous_tokens = ("目录", "摘要", "完成情况", "附件", "清单", "汇总", "概述")
        if doc_kind in {"科技报告", "其他材料", "论文"} and any(token in blob for token in ambiguous_tokens):
            if len(excerpt.strip()) < 260:
                return True
            return False
        if doc_kind not in {"科技报告", "其他材料", "论文"}:
            return False
        if len(title.strip()) < 6 and len(excerpt.strip()) < 80:
            return True
        return heuristic.is_artifact_like is None and heuristic.is_summary_like is None

    def _should_consult_llm_for_equivalence(
        self,
        *,
        left_title: str,
        right_title: str,
        heuristic: EvidenceAdvisory,
    ) -> bool:
        if heuristic.same_artifact_as:
            return False
        left = (left_title or "").strip()
        right = (right_title or "").strip()
        if not left or not right:
            return False
        if left == right:
            return False
        if min(len(left), len(right)) < 8:
            return False
        return self._overlap_ratio(left, right) >= 0.45

    def _probe_document_role_with_llm(
        self,
        *,
        doc_kind: str,
        title: str,
        excerpt: str,
        metric_name: str,
    ) -> EvidenceAdvisory:
        llm = self._get_llm()
        if llm is None or HumanMessage is None or SystemMessage is None:
            return EvidenceAdvisory()
        try:
            chain = self._bind_probe_llm(llm).with_structured_output(DocumentRoleProbeResult)
            messages = [
                SystemMessage(
                    content=(
                        "你是科技项目验收核查助手。"
                        "请判断某段文档内容更像“成果本体/正式成果正文”还是“总结汇报/目录/清单/概述”。"
                        "成果本体示例：论文正文、专利证书、研究报告正文、决策咨询报告正文、科技报告正文。"
                        "总结类示例：验收自评价、任务完成情况、成果汇总、附件目录、概述性说明。"
                        "如果无法确定，可返回 null。不要扩展事实。"
                        "请严格返回 JSON 对象，rationale 不超过 20 个汉字。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"指标类型: {metric_name[:80]}\n"
                        f"文档类别: {doc_kind[:80]}\n"
                        f"标题: {(title or '')[:240]}\n"
                        f"摘录: {(excerpt or '')[:1200]}\n\n"
                        "只输出 JSON："
                        '{"is_artifact_like": true/false/null, "is_summary_like": true/false/null, "confidence": 0-1, "rationale": "短理由"}'
                    )
                ),
            ]
            out = chain.invoke(messages)
            if out.confidence < 0.55:
                return EvidenceAdvisory()
            return EvidenceAdvisory(
                is_artifact_like=out.is_artifact_like,
                is_summary_like=out.is_summary_like,
                rationale=f"LLM: {out.rationale}".strip(),
            )
        except Exception as exc:
            self._handle_probe_error("accept_document_role_probe_failed", exc)
            return EvidenceAdvisory()

    def _probe_artifact_equivalence_with_llm(
        self,
        *,
        left_title: str,
        right_title: str,
    ) -> EvidenceAdvisory:
        llm = self._get_llm()
        if llm is None or HumanMessage is None or SystemMessage is None:
            return EvidenceAdvisory()
        try:
            chain = self._bind_probe_llm(llm).with_structured_output(ArtifactEquivalenceProbeResult)
            messages = [
                SystemMessage(
                    content=(
                        "你是科技项目验收核查助手。"
                        "请判断两个成果题名是否指向同一个具体成果本体。"
                        "只有在明显是同一成果、只是简称/别名/轻微表述差异时，才判定 same_artifact=true。"
                        "不要因为同属一个研究方向就判定为同一成果。"
                        "请严格返回 JSON 对象，rationale 不超过 20 个汉字。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"题名A: {(left_title or '')[:240]}\n"
                        f"题名B: {(right_title or '')[:240]}\n\n"
                        "只输出 JSON："
                        '{"same_artifact": true/false/null, "confidence": 0-1, "rationale": "短理由"}'
                    )
                ),
            ]
            out = chain.invoke(messages)
            if out.same_artifact and out.confidence >= 0.7:
                return EvidenceAdvisory(
                    same_artifact_as=right_title,
                    rationale=f"LLM: {out.rationale}".strip(),
                )
            return EvidenceAdvisory()
        except Exception as exc:
            self._handle_probe_error("accept_artifact_equivalence_probe_failed", exc)
            return EvidenceAdvisory()

    def _merge_document_role_advisory(
        self,
        heuristic: EvidenceAdvisory,
        llm_advisory: EvidenceAdvisory,
    ) -> EvidenceAdvisory:
        if not any(
            [
                llm_advisory.is_artifact_like is not None,
                llm_advisory.is_summary_like is not None,
                llm_advisory.rationale,
            ]
        ):
            return heuristic
        is_artifact_like = heuristic.is_artifact_like
        is_summary_like = heuristic.is_summary_like
        if is_artifact_like is None:
            is_artifact_like = llm_advisory.is_artifact_like
        if is_summary_like is None:
            is_summary_like = llm_advisory.is_summary_like
        if heuristic.is_artifact_like and llm_advisory.is_summary_like:
            is_summary_like = False
        if heuristic.is_summary_like and llm_advisory.is_artifact_like:
            is_artifact_like = False
        return EvidenceAdvisory(
            is_artifact_like=is_artifact_like,
            is_summary_like=is_summary_like,
            rationale=self._combine_rationales(heuristic.rationale, llm_advisory.rationale),
        )

    def _combine_rationales(self, left: str, right: str) -> str:
        parts = [part.strip() for part in (left, right) if part and part.strip()]
        if not parts:
            return ""
        return "；".join(dict.fromkeys(parts))

    def _overlap_ratio(self, left: str, right: str) -> float:
        left_tokens = {token for token in self._tokenize_title(left) if token}
        right_tokens = {token for token in self._tokenize_title(right) if token}
        if not left_tokens or not right_tokens:
            return 0.0
        union = left_tokens | right_tokens
        if not union:
            return 0.0
        return len(left_tokens & right_tokens) / len(union)

    def _tokenize_title(self, title: str) -> list[str]:
        compact = "".join((title or "").split()).lower()
        if not compact:
            return []
        return [compact[i : i + 2] for i in range(max(len(compact) - 1, 1))]

    def _get_llm(self) -> Any | None:
        if self._llm_disabled:
            return None
        if self._llm_ready:
            return self._llm
        self._llm_ready = True
        if not llm_config.api_key:
            return None
        try:
            self._llm = get_default_llm_client()
        except Exception:
            logger.exception("accept_advisory_llm_init_failed")
            self._llm_disabled = True
            self._llm = None
        return self._llm

    def _bind_probe_llm(self, llm: Any) -> Any:
        """LLM 只做弱监督判定，强制小输出，避免思考/补全文本撑爆结构化解析。"""
        kwargs: dict[str, Any] = {
            "temperature": 0.0,
            "max_tokens": int(os.getenv("ACCEPT_LLM_ADVISORY_MAX_TOKENS", "160") or "160"),
        }
        base_url = str(getattr(llm_config, "base_url", "") or "").lower()
        model = str(getattr(llm_config, "model", "") or "").lower()
        if "dashscope" in base_url or "qwen" in model:
            kwargs["extra_body"] = {"enable_thinking": False}
        return llm.bind(**kwargs)

    def _handle_probe_error(self, event: str, exc: Exception) -> None:
        self._llm_disabled = True
        if LengthFinishReasonError is not None and isinstance(exc, LengthFinishReasonError):
            logger.warning("%s length_limit_fallback_to_rules", event)
            return
        logger.warning("%s fallback_to_rules: %s", event, exc.__class__.__name__)
