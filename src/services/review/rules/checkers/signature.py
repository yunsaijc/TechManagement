"""签字检查规则

使用统一的 SignatureExtractor 进行检查：
1. 先用 LLM 定位签字区域 bbox
2. 裁剪区域
3. OCR 转写签字内容
"""
from src.common.models import CheckResult, CheckStatus
from src.common.extractors import SignatureExtractor
from src.common.extractors.signature import normalize_signature_entries
from src.services.review.doc_types import normalize_doc_type
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class SignatureCheckRule(BaseRule):
    """签字检查规则

    使用 SignatureExtractor 提取签字内容。
    """

    name = "signature"
    description = "检查文档中是否存在签字"
    priority = 10

    def __init__(self):
        self.min_regions = 1  # 最少签字区域数

    def _build_pass_result(self, signatures: list[dict]) -> CheckResult:
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message=f"提取到 {len(signatures)} 个签字区域",
            evidence={
                "signatures": [
                    {
                        "text": s.get("text", ""),
                        "bbox": s.get("bbox", {}),
                        "confidence": s.get("confidence", 0),
                    }
                    for s in signatures
                ],
            },
            confidence=0.9,
        )

    async def should_run(self, context: ReviewContext) -> bool:
        """根据文档类型判断"""
        # 某些文档类型不需要签字检查
        no_signature_types = {"project_retrieval_report"}
        return normalize_doc_type(context.doc_type) not in no_signature_types

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行签字检查

        使用 SignatureExtractor 提取签字内容。
        能提取到则 PASS，否则 FAILED。
        """
        llm_analysis = context.extracted.get("llm_analysis") if context.extracted else {}
        if isinstance(llm_analysis, dict):
            if normalize_doc_type(context.doc_type) in {"wcr", "wjwcr"} and llm_analysis.get("error"):
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.WARNING,
                    message=f"专项分析已降级，跳过通用签字提取：{llm_analysis.get('error')}",
                    evidence={"stage": "llm_analysis"},
                )
            llm_signatures = llm_analysis.get("signatures_result")
            if isinstance(llm_signatures, dict):
                signatures = normalize_signature_entries(llm_signatures.get("signatures", []))
                if signatures:
                    return self._build_pass_result(signatures)
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.FAILED,
                    message="未提取到签字",
                    evidence={"signatures": []},
                )

        extractor = SignatureExtractor()
        
        try:
            result = await extractor.extract(
                context.file_data,
                min_regions=self.min_regions,
            )
        except Exception as e:
            # 如果提取失败，返回警告
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message=f"签字提取暂时不可用: {e}",
                evidence={},
            )

        signatures = normalize_signature_entries((result or {}).get("signatures", []))
        if signatures:
            return self._build_pass_result(signatures)
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未提取到签字",
                evidence={"signatures": []},
            )
