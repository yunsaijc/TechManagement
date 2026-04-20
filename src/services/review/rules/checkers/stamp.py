"""盖章检查规则

使用统一的 StampExtractor 进行检查：
1. 先用 LLM 定位印章区域 bbox
2. 裁剪区域
3. OCR 转写印章文字
"""
from src.common.models.review import CheckResult, CheckStatus
from src.common.extractors import StampExtractor
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class StampCheckRule(BaseRule):
    """盖章检查规则
    
    使用 StampExtractor 提取印章内容。
    """

    name = "stamp"
    description = "检查文档中是否存在印章"
    priority = 10

    def __init__(self):
        self.min_regions = 1  # 最少印章区域数

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行盖章检查
        
        使用 StampExtractor 提取印章内容。
        能提取到则 PASS，否则 FAILED。
        """
        llm_analysis = context.extracted.get("llm_analysis") if context.extracted else {}
        if isinstance(llm_analysis, dict):
            llm_stamps = llm_analysis.get("stamps_result")
            if isinstance(llm_stamps, dict):
                stamps = llm_stamps.get("stamps", [])
                if stamps:
                    return CheckResult(
                        item=self.name,
                        status=CheckStatus.PASSED,
                        message=f"提取到 {len(stamps)} 个印章",
                        evidence={
                            "stamps": [
                                {
                                    "text": s.get("text") or s.get("unit", ""),
                                    "bbox": s.get("bbox", {}),
                                    "confidence": s.get("confidence", 0),
                                    "location": s.get("location", ""),
                                }
                                for s in stamps
                            ],
                        },
                        confidence=0.9,
                    )
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.FAILED,
                    message="未提取到印章",
                    evidence={"stamps": []},
                )

        extractor = StampExtractor()
        
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
                message=f"印章提取暂时不可用: {e}",
                evidence={},
            )

        if result and result.get("stamps"):
            stamps = result["stamps"]
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"提取到 {len(stamps)} 个印章",
                evidence={
                    "stamps": [
                        {
                            "text": s.get("text", ""),
                            "bbox": s.get("bbox", {}),
                            "confidence": s.get("confidence", 0),
                        }
                        for s in stamps
                    ],
                },
                confidence=0.9,
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未提取到印章",
                evidence={"stamps": []},
            )
