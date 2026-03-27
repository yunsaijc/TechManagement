from typing import Optional
from src.common.models.perfcheck import PerfCheckResult
from src.services.perfcheck.agent import PerfCheckAgent

class PerfCheckService:
    """绩效核验核心服务层 (暴露给 API)"""

    def __init__(self):
        # 实际逻辑交由 Agent 处理，Service 层负责会话管理、权限等（当前为薄层）
        pass

    async def compare_files(
        self,
        project_id: str,
        declaration_file: bytes,
        declaration_file_type: str,
        task_file: bytes,
        task_file_type: str,
        budget_shift_threshold: float = 0.10,
        strict_mode: bool = True,
        enable_llm_enhancement: bool = False,
        enable_table_vision_extraction: bool = True,
        enable_llm_entailment: bool = True,
        on_progress=None,
        **kwargs
    ) -> PerfCheckResult:
        """从文件流开始比对"""
        agent = PerfCheckAgent(budget_shift_threshold=budget_shift_threshold)
        return await agent.run_compare_files(
            project_id=project_id,
            declaration_file=declaration_file,
            declaration_file_type=declaration_file_type,
            task_file=task_file,
            task_file_type=task_file_type,
            on_progress=on_progress,
            **kwargs
        )

    async def compare_text(
        self,
        project_id: str,
        declaration_text: str,
        task_text: str,
        budget_shift_threshold: float = 0.10,
        strict_mode: bool = True,
        enable_llm_enhancement: bool = False,
        enable_llm_entailment: bool = True,
        on_progress=None,
        **kwargs
    ) -> PerfCheckResult:
        """直接从文本开始比对"""
        agent = PerfCheckAgent(budget_shift_threshold=budget_shift_threshold)
        return await agent.run_compare_text(
            project_id=project_id,
            declaration_text=declaration_text,
            task_text=task_text,
            on_progress=on_progress,
            **kwargs
        )
