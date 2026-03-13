"""审查 Agent"""
import time
from typing import Any, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models import CheckResult, CheckStatus, ReviewResult
from src.common.vision import MultimodalLLM
from src.services.review.extractor import DocumentExtractor
from src.services.review.rules import ReviewContext, RuleRegistry
from src.services.review.rules.config import load_rules


class ReviewAgent:
    """形式审查 Agent

    协调规则引擎和多模态 LLM，实现文档的智能审查。
    """

    def __init__(
        self,
        llm: Any = None,
        document_parser: Any = None,
        rule_registry: type[RuleRegistry] = RuleRegistry,
    ):
        """初始化

        Args:
            llm: LangChain ChatModel 实例
            document_parser: 文档解析器
            rule_registry: 规则注册表
        """
        self.llm = llm or get_default_llm_client()
        self.parser = document_parser
        self.rule_registry = rule_registry
        self.extractor = DocumentExtractor(self.llm)

    async def process(
        self,
        file_data: bytes,
        file_type: str,
        document_type: str = None,
        check_items: Optional[List[str]] = None,
        **kwargs,
    ) -> ReviewResult:
        """执行审查

        Args:
            file_data: 文件数据
            file_type: 文件类型
            document_type: 文档类型（可选，自动识别）
            check_items: 检查项列表（可选）

        Returns:
            ReviewResult: 审查结果
        """
        start_time = time.time()

        # 1. 文档分类
        if not document_type:
            document_type = await self._classify_document(file_data)

        # 2. 预提取内容（一次性提取，供规则复用）
        extracted = await self.extractor.extract(file_data, document_type)

        # 3. 构建审查上下文
        context = ReviewContext(
            file_data=file_data,
            file_type=file_type,
            document_type=document_type,
            extracted=extracted,
            metadata=kwargs.get("metadata", {}),
        )

        # 4. 加载并运行规则
        rule_results = await self._run_rules(context, check_items)

        # 5. LLM 补充（可选）
        llm_results = await self._llm_check(context, check_items)

        # 6. 结果聚合
        all_results = rule_results + llm_results
        summary = self._generate_summary(all_results)
        suggestions = self._generate_suggestions(all_results)

        return ReviewResult(
            id=f"review_{int(time.time() * 1000)}",
            document_type=document_type,
            results=all_results,
            summary=summary,
            suggestions=suggestions,
            processing_time=time.time() - start_time,
        )

    async def _classify_document(self, file_data: bytes) -> str:
        """文档分类"""
        multi_llm = MultimodalLLM(self.llm)

        prompt = """请识别这个文档的类型（直接返回类型，不要其他内容）：
- patent_certificate（专利证书）
- patent_application（专利申请）
- acceptance_report（验收报告）
- license（行政许可）
- retrieval_report（检索报告）
- award_certificate（奖励证书）
- contract（合同）
- paper（论文）

直接返回类型名称。"""

        try:
            result = await multi_llm.analyze_image(file_data, prompt)
            # 简单解析
            type_mapping = {
                "专利证书": "patent_certificate",
                "专利申请": "patent_application",
                "验收报告": "acceptance_report",
                "行政许可": "license",
                "检索报告": "retrieval_report",
                "奖励证书": "award_certificate",
                "合同": "contract",
                "论文": "paper",
            }
            for key, value in type_mapping.items():
                if key in result:
                    return value
        except Exception:
            pass

        return "other"

    async def _run_rules(
        self,
        context: ReviewContext,
        check_items: Optional[List[str]] = None,
    ) -> List[CheckResult]:
        """运行规则"""
        # 从配置加载规则
        rule_names = load_rules(context.document_type)
        
        # 创建规则实例
        rules = []
        for name in rule_names:
            rule_class = self.rule_registry.get_rule(name)
            if rule_class:
                rules.append(rule_class())
        
        # 如果没有配置规则，使用 registry 的默认链
        if not rules:
            rules = self.rule_registry.create_chain(context.document_type)

        # 过滤检查项
        if check_items:
            rules = [r for r in rules if r.name in check_items]

        results = []
        for rule in rules:
            if await rule.should_run(context):
                result = await rule.check(context)
                results.append(result)

        return results

    async def _llm_check(
        self,
        context: ReviewContext,
        check_items: Optional[List[str]] = None,
    ) -> List[CheckResult]:
        """LLM 补充检查"""
        # 需要 LLM 检查的项目
        llm_items = ["consistency", "completeness"]
        if check_items:
            llm_items = [i for i in llm_items if i in check_items]

        results = []

        if "consistency" in llm_items:
            result = await self._check_consistency(context)
            if result:
                results.append(result)

        return results

    async def _check_consistency(self, context: ReviewContext) -> Optional[CheckResult]:
        """一致性检查"""
        form_data = context.metadata.get("form_data", {})
        if not form_data:
            return None

        multi_llm = MultimodalLLM(self.llm)

        prompt = f"""请检查文档中的信息与以下表单数据是否一致：

表单数据：
{form_data}

请分析并给出结果（一致/不一致）。"""

        try:
            result = await multi_llm.analyze_image(context.file_data, prompt)

            return CheckResult(
                item="consistency",
                status=CheckStatus.PASSED if "一致" in result else CheckStatus.FAILED,
                message="一致性检查完成",
                evidence={"llm_analysis": result},
            )
        except Exception:
            return CheckResult(
                item="consistency",
                status=CheckStatus.WARNING,
                message="一致性检查暂时不可用",
                evidence={},
            )

    def _generate_summary(self, results: List[CheckResult]) -> str:
        """生成总结"""
        passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
        failed = sum(1 for r in results if r.status == CheckStatus.FAILED)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARNING)

        return f"审查完成：通过 {passed} 项，失败 {failed} 项，警告 {warnings} 项"

    def _generate_suggestions(self, results: List[CheckResult]) -> List[str]:
        """生成建议"""
        suggestions = []

        for result in results:
            if result.status == CheckStatus.FAILED:
                suggestions.append(f"请检查：{result.item} - {result.message}")
            elif result.status == CheckStatus.WARNING:
                suggestions.append(f"注意：{result.item} - {result.message}")

        return suggestions
