"""批次级形式审查 Agent"""
import asyncio
import os
import time
from typing import List

from src.common.models import BatchReviewRequest, BatchReviewResult, ProjectReviewResult
from src.services.review.debug_writer import ReviewDebugWriter
from src.services.review.project_agent import ProjectReviewAgent
from src.services.review.project_context_builder import ProjectContextBuilder
from src.services.review.project_index_repo import ProjectIndexRepository


class BatchReviewAgent:
    """批次级形式审查 Agent"""

    def __init__(
        self,
        project_repo: ProjectIndexRepository | None = None,
        context_builder: ProjectContextBuilder | None = None,
        project_review_agent: ProjectReviewAgent | None = None,
    ):
        self.project_repo = project_repo or ProjectIndexRepository()
        self.context_builder = context_builder or ProjectContextBuilder()
        self.project_review_agent = project_review_agent or ProjectReviewAgent()
        self.project_concurrency = max(
            1,
            int(os.getenv("REVIEW_BATCH_PROJECT_CONCURRENCY", "2")),
        )

    async def process(self, request: BatchReviewRequest) -> BatchReviewResult:
        """执行批次级形式审查"""
        start_time = time.time()
        batch_id = f"batch_review_{int(time.time() * 1000)}"
        debug_writer = ReviewDebugWriter(batch_id)
        debug_writer.write_json("request.json", request.model_dump())
        project_rows = self.project_repo.get_projects_by_zxmc(
            request.zxmc,
            limit=request.limit,
            project_ids=request.project_ids,
        )
        debug_writer.write_json(
            "project_index.json",
            [row.model_dump() for row in project_rows],
        )
        semaphore = asyncio.Semaphore(self.project_concurrency)

        async def _process_project(row) -> ProjectReviewResult:
            async with semaphore:
                context = await self.context_builder.build(row)
                debug_writer.write_json(
                    f"projects/{row.project_id}.scan.json",
                    context.scan_info,
                )
                debug_writer.write_json(
                    f"projects/{row.project_id}.context.json",
                    context.model_dump(mode="json"),
                )
                project_result = await self.project_review_agent.process_context(context)
                debug_writer.write_json(
                    f"projects/{row.project_id}.result.json",
                    project_result.model_dump(mode="json"),
                )
                return project_result

        project_results: List[ProjectReviewResult] = list(
            await asyncio.gather(*[_process_project(row) for row in project_rows])
        )

        summary = self._generate_summary(project_results)
        suggestions = self._generate_suggestions(project_results)

        debug_writer.write_json(
            "batch_summary.json",
            {
                "zxmc": request.zxmc,
                "project_count": len(project_results),
                "summary": summary,
                "suggestions": suggestions,
            },
        )

        return BatchReviewResult(
            id=batch_id,
            zxmc=request.zxmc,
            project_count=len(project_results),
            project_results=project_results,
            debug_dir=debug_writer.output_dir,
            summary=summary,
            suggestions=suggestions,
            processing_time=time.time() - start_time,
        )

    def _generate_summary(self, project_results: List[ProjectReviewResult]) -> str:
        """生成批次摘要"""
        if not project_results:
            return "批次形式审查完成：未查询到项目"
        failed_projects = sum(
            1
            for result in project_results
            if any(item.status in {"failed", "warning"} for item in result.results) or result.manual_review_items
        )
        return f"批次形式审查完成：共 {len(project_results)} 个项目，需关注 {failed_projects} 个"

    def _generate_suggestions(self, project_results: List[ProjectReviewResult]) -> List[str]:
        """生成批次建议"""
        if any(result.manual_review_items for result in project_results):
            return ["存在附件类型识别不确定的项目，建议优先人工复核材料类型"]
        return []
