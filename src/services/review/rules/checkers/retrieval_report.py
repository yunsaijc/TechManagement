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
                message='未提供论文列表元数据（papers），无法判断是否缺少论文检索报告。请在“补充信息”里提供，例如：{"papers":["论文1标题","论文2标题","论文3标题","论文4标题","论文5标题","论文6标题"]}',
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

        import re
        def _simplify(s: str) -> str:
            x = str(s or "").strip()
            x = re.sub(r"^\s*(?:\d+(?:\.\d+)*-)?(?:论文-)?", "", x)
            x = re.sub(r"^\s*(?:\(?（?\s*\d+\s*\)?）?)\s*", "", x)
            x = re.sub(r"[\s\u3000·•，,。；;:：()（）\[\]【】<>《》\\/_\-~—–]+", "", x)
            return x.casefold()
        def _match(a: str, b: str) -> bool:
            sa = _simplify(a)
            sb = _simplify(b)
            if not sa or not sb:
                return False
            if sa == sb:
                return True
            if len(sa) >= 10 and sa in sb:
                return True
            if len(sb) >= 10 and sb in sa:
                return True
            return False
        matched_indices = set()
        for i, p in enumerate(papers or []):
            for j, q in enumerate(extracted_papers or []):
                if j in matched_indices:
                    continue
                if _match(p, q):
                    matched_indices.add(j)
                    break
        missing_papers = []
        for p in papers or []:
            found = False
            for j, q in enumerate(extracted_papers or []):
                if _match(p, q):
                    found = True
                    break
            if not found:
                missing_papers.append(p)
        extra_papers = []
        for q in extracted_papers or []:
            found = False
            for p in papers or []:
                if _match(p, q):
                    found = True
                    break
            if not found:
                extra_papers.append(q)

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

        def _truncate_list(xs, limit=5):
            arr = [str(x).strip() for x in xs if str(x).strip()]
            if len(arr) > limit:
                return arr[:limit] + [f"…（共 {len(arr)} 篇）"]
            return arr
        messages = []
        if missing_papers:
            msgs = _truncate_list(missing_papers)
            messages.append(f"缺少 {len(missing_papers)} 篇论文的检索报告: {', '.join(msgs)}")
        if extra_papers:
            msgs = _truncate_list(extra_papers)
            messages.append(f"检索报告中包含 {len(extra_papers)} 篇不在项目中的论文: {', '.join(msgs)}")

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
