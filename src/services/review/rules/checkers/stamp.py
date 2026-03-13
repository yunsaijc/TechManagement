"""盖章检查规则"""
from src.common.models.review import CheckResult, CheckStatus
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class StampCheckRule(BaseRule):
    """盖章检查规则
    
    使用预提取的内容判断是否存在印章。
    """

    name = "stamp"
    description = "检查文档中是否存在印章"
    priority = 10

    def __init__(self):
        self.min_confidence = 0.7

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行盖章检查
        
        从预提取的内容中获取印章信息。
        """
        # 优先使用预提取的内容
        if context.extracted:
            stamps = context.extracted.get("stamps", [])
            if stamps:
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.PASSED,
                    message=f"检测到 {len(stamps)} 个印章",
                    evidence={"stamps": stamps},
                    confidence=0.9,
                )
            
            # 检查是否有错误
            if context.extracted.get("error"):
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.WARNING,
                    message="印章提取失败",
                    evidence={"error": context.extracted.get("error")},
                )
        
        # 如果没有预提取结果，尝试使用 LLM 直接检查
        return await self._llm_check(context)
    
    async def _llm_check(self, context: ReviewContext) -> CheckResult:
        """使用 LLM 检查印章"""
        from src.common.vision import MultimodalLLM
        from src.common.llm import get_default_llm_client
        
        try:
            llm = get_default_llm_client()
            multi_llm = MultimodalLLM(llm)
            
            prompt = """请仔细检查这个文档页面，判断是否存在印章/公章。
请以以下JSON格式返回结果：
{"has_stamp": true/false, "stamp_count": 数量, "stamp_units": ["盖章单位1", "盖章单位2"]}

只返回JSON，不要其他内容。"""
            
            result = await multi_llm.analyze_image(context.file_data, prompt)
            
            # 简单解析 JSON
            import json
            import re
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("has_stamp"):
                    return CheckResult(
                        item=self.name,
                        status=CheckStatus.PASSED,
                        message=f"检测到 {data.get('stamp_count', 1)} 个印章",
                        evidence={"stamp_units": data.get("stamp_units", [])},
                        confidence=0.9,
                    )
            
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未检测到印章",
                evidence={"llm_result": result},
            )
            
        except Exception as e:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message=f"印章检测暂时不可用: {str(e)}",
                evidence={},
            )
