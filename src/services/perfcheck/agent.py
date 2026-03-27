import uuid
import logging
import asyncio
from typing import Callable, List, Optional

from src.common.models.perfcheck import (
    PerfCheckResult, DocumentSchema, MetricComparison, 
    ContentComparison, BudgetComparison
)
from src.services.perfcheck.parser import PerfCheckParser
from src.services.perfcheck.detector import PerfCheckDetector

logger = logging.getLogger(__name__)

class PerfCheckAgent:
    """绩效核验业务编排 Agent"""

    def __init__(self, budget_shift_threshold: float = 0.10):
        self.parser = PerfCheckParser()
        self.detector = PerfCheckDetector()
        self.budget_threshold = budget_shift_threshold

    async def run_compare_text(
        self,
        project_id: str,
        declaration_text: str,
        task_text: str,
        on_progress: Optional[Callable[[float, str, str], None]] = None,
        **kwargs
    ) -> PerfCheckResult:
        """从文本开始执行全流程核验"""
        if on_progress:
            on_progress(0.05, "extract", "开始结构化抽取（申报书/任务书，并行）")
        apply_schema, task_schema = await asyncio.gather(
            self.parser.extract_schema_from_text(declaration_text),
            self.parser.extract_schema_from_text(task_text),
        )
        
        return await self._execute_detection(project_id, apply_schema, task_schema, on_progress=on_progress)

    async def run_compare_files(
        self,
        project_id: str,
        declaration_file: bytes,
        declaration_file_type: str,
        task_file: bytes,
        task_file_type: str,
        on_progress: Optional[Callable[[float, str, str], None]] = None,
        **kwargs
    ) -> PerfCheckResult:
        """从文件流开始执行全流程核验"""
        if on_progress:
            on_progress(0.05, "parse", "解析申报书/任务书文件（并行）")
        apply_schema, task_schema = await asyncio.gather(
            self.parser.parse_to_schema(declaration_file, declaration_file_type),
            self.parser.parse_to_schema(task_file, task_file_type),
        )
        
        return await self._execute_detection(project_id, apply_schema, task_schema, on_progress=on_progress)

    async def _execute_detection(
        self,
        project_id: str,
        apply_schema: DocumentSchema,
        task_schema: DocumentSchema,
        on_progress: Optional[Callable[[float, str, str], None]] = None,
    ) -> PerfCheckResult:
        """执行核心差异检测逻辑"""
        task_id = str(uuid.uuid4())[:8]
        if on_progress:
            on_progress(0.40, "detect", "开始差异检测（指标/内容/预算）")
        
        # 2. 差异检测
        metrics_risks, content_risks, budget_risks, other_risks, unit_budget_risks = await self.detector.detect_differences(
            apply_schema, task_schema, self.budget_threshold
        )
        if on_progress:
            on_progress(0.78, "summary", "生成核验摘要")

        # 3. 生成简短总结
        summary = self._generate_summary(metrics_risks, content_risks, budget_risks)
        if on_progress:
            on_progress(0.95, "finalize", "整理输出结果")
        
        return PerfCheckResult(
            project_id=project_id or apply_schema.project_name,
            task_id=task_id,
            metrics_risks=metrics_risks,
            content_risks=content_risks,
            budget_risks=budget_risks,
            other_risks=other_risks,
            unit_budget_risks=unit_budget_risks,
            summary=summary,
            warnings=[]
        )

    def _generate_summary(self, m_risks, c_risks, b_risks) -> str:
        """生成核验结论概要"""
        content_level = str(getattr(c_risks[0], "risk_level", "")).upper() if c_risks else ""
        red_counts = len([r for r in m_risks if r.risk_level == "RED"]) + \
                     len([r for r in c_risks if r.risk_level == "RED"]) + \
                     len([r for r in b_risks if r.risk_level == "RED"])

        yellow_counts = len([r for r in m_risks if r.risk_level == "YELLOW"]) + \
                        len([r for r in c_risks if r.risk_level == "YELLOW"]) + \
                        len([r for r in b_risks if r.risk_level == "YELLOW"])

        if red_counts == 0 and yellow_counts == 0:
            if content_level == "GREEN":
                return "项目研究内容判定为“内容一致或扩展”，核心绩效指标与预算变动整体在合理范围内。"
            return "项目绩效指标与任务书保持一致，预算变动在合理范围内。"

        if content_level == "RED":
            return "研究内容判定为“严重缩水”，建议优先核查任务书对申报书核心内容的覆盖完整性。"

        if content_level == "YELLOW":
            return "研究内容判定为“部分缩水”，任务书仅覆盖申报书部分内容，建议逐条补齐。"
        
        if red_counts > 0:
            return f"检测到 {red_counts} 项重点差异，主要涉及绩效缩水或内容删减，建议重点核对。"
        
        return "检测到部分中度风险变动，请关注预算占比调整。"
