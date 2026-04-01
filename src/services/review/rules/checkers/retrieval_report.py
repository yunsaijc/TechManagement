"""检索报告完整性规则"""
from src.common.models.review import CheckResult, CheckStatus
from src.common.vision.multimodal import MultimodalLLM
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry


@RuleRegistry.register
class RetrievalReportCompletenessRule(BaseRule):
    """检索报告完整性检查

    检查每篇论文是否都有对应的检索报告。
    从上传的检索报告 PDF 中提取包含的论文列表，与项目论文列表对比。
    """

    name = "retrieval_report_completeness"
    description = "检查每篇论文是否都有对应的检索报告"
    priority = 5

    async def check(self, context: ReviewContext) -> CheckResult:
        """执行检索报告完整性检查

        期望的 metadata 格式:
        {
            "papers": ["论文1标题", "论文2标题", ...]  # 项目包含的所有论文列表
        }

        从 PDF 中提取检索报告包含的论文列表，然后对比找出缺失的。
        """
        papers = context.metadata.get("papers")

        # 需要客户端在提交时传入论文列表
        if papers is None:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="未提供论文列表元数据，无法执行检索报告完整性检查（请提供 papers）",
                evidence={
                    "papers": papers,
                },
            )

        if not isinstance(papers, list):
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message="元数据格式错误，papers 必须是列表",
                evidence={
                    "papers_type": type(papers).__name__,
                },
            )

        # 从 PDF 中提取检索报告包含的论文列表
        try:
            from src.common.llm import get_default_llm_client
            from src.common.extractors.stamp import StampExtractor
            llm = get_default_llm_client()
            multi_llm = MultimodalLLM(llm)

            # 使用 StampExtractor 的 PDF 转图片方法
            extractor = StampExtractor()
            image_data = extractor._pdf_to_image(context.file_data)

            prompt = f"""请从这份检索报告中提取包含的所有论文标题列表。

项目包含的论文列表（供参考）:
{chr(10).join(f"- {p}" for p in papers)}

请分析检索报告内容，提取其中实际包含的论文标题，返回格式：
论文1标题
论文2标题
...

只返回论文标题列表，每行一个，不要其他内容。"""

            # 调用 LLM 分析图片
            result = await multi_llm.analyze_image(image_data, prompt)

            # 解析返回的论文列表
            extracted_papers = [line.strip() for line in result.split('\n') if line.strip()]

        except Exception as e:
            return CheckResult(
                item=self.name,
                status=CheckStatus.WARNING,
                message=f"无法从检索报告中提取论文列表: {e}",
                evidence={"error": str(e)},
            )

        # 找出缺少检索报告的论文
        missing_papers = [p for p in papers if p not in extracted_papers]
        extra_papers = [p for p in extracted_papers if p not in papers]

        if not missing_papers and not extra_papers:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"所有 {len(papers)} 篇论文都有对应的检索报告",
                evidence={
                    "total_papers": len(papers),
                    "extracted_papers": len(extracted_papers),
                    "papers": papers,
                    "extracted": extracted_papers,
                },
            )

        messages = []
        if missing_papers:
            messages.append(f"缺少 {len(missing_papers)} 篇论文的检索报告: {', '.join(missing_papers)}")
        if extra_papers:
            messages.append(f"检索报告中包含 {len(extra_papers)} 篇不在项目中的论文: {', '.join(extra_papers)}")

        return CheckResult(
            item=self.name,
            status=CheckStatus.FAILED,
            message="; ".join(messages),
            evidence={
                "total_papers": len(papers),
                "extracted_papers": len(extracted_papers),
                "missing_papers": missing_papers,
                "extra_papers": extra_papers,
                "papers": papers,
                "extracted": extracted_papers,
            },
        )
