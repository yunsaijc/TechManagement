"""逻辑自洽校验服务入口"""
import time
from typing import Optional

from src.common.file_handler import get_parser
from src.common.models.logicons import ConflictItem, LogiConsResult, LogiConsSummary
from src.services.logicons.agent import LogiConsAgent
from src.services.logicons.llm_enhancer import LogiConsLLMEnhancer


class LogiConsService:
    """申报书/任务书全局逻辑一致性校验服务"""

    def __init__(self):
        self.llm_enhancer = LogiConsLLMEnhancer()

    async def check_text(
        self,
        *,
        project_id: str,
        text: str,
        budget_tolerance: float = 0.01,
        timeline_grace_years: int = 0,
        enable_llm_enhancement: bool = False,
    ) -> LogiConsResult:
        check_id = f"logicons_{int(time.time() * 1000)}"
        agent = LogiConsAgent(
            budget_tolerance=budget_tolerance,
            timeline_grace_years=timeline_grace_years,
        )
        base_result = await agent.run(check_id=check_id, project_id=project_id, text=text)

        if not enable_llm_enhancement:
            return base_result

        llm_conflicts = await self.llm_enhancer.find_additional_conflicts(
            text=text,
            existing_conflicts=base_result.conflicts,
            timeout_seconds=70.0,
        )

        merged_conflicts = self._merge_conflicts(base_result.conflicts, llm_conflicts)
        self._reindex_conflicts(merged_conflicts)

        base_result.conflicts = merged_conflicts
        base_result.summary = self._build_summary(merged_conflicts)
        if self.llm_enhancer.last_status == "error":
            base_result.warnings.append(self.llm_enhancer.last_message or "LLM 增强调用失败")
        elif llm_conflicts:
            base_result.warnings.append(f"LLM 增强新增冲突 {len(llm_conflicts)} 条")
        else:
            base_result.warnings.append(self.llm_enhancer.last_message or "LLM 增强未发现新增冲突")
        return base_result

    async def check_file(
        self,
        *,
        project_id: str,
        file_data: bytes,
        file_type: str,
        budget_tolerance: float = 0.01,
        timeline_grace_years: int = 0,
        enable_llm_enhancement: bool = False,
    ) -> LogiConsResult:
        parser = get_parser(file_type=file_type.lower())
        parsed = await parser.parse(file_data)
        text = parsed.content.to_text()
        return await self.check_text(
            project_id=project_id,
            text=text,
            budget_tolerance=budget_tolerance,
            timeline_grace_years=timeline_grace_years,
            enable_llm_enhancement=enable_llm_enhancement,
        )

    def _merge_conflicts(
        self,
        base_conflicts: list[ConflictItem],
        llm_conflicts: list[ConflictItem],
    ) -> list[ConflictItem]:
        merged = list(base_conflicts)
        seen = {(c.rule_code, c.message.strip()) for c in base_conflicts}
        for c in llm_conflicts:
            key = (c.rule_code, c.message.strip())
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)
        return merged

    def _reindex_conflicts(self, conflicts: list[ConflictItem]) -> None:
        for idx, item in enumerate(conflicts, start=1):
            item.conflict_id = f"C{idx:03d}"

    def _build_summary(self, conflicts: list[ConflictItem]) -> LogiConsSummary:
        high = sum(1 for c in conflicts if c.severity.value == "high")
        medium = sum(1 for c in conflicts if c.severity.value == "medium")
        low = sum(1 for c in conflicts if c.severity.value == "low")
        return LogiConsSummary(high=high, medium=medium, low=low, total=len(conflicts))


_service: Optional[LogiConsService] = None


def get_logicons_service() -> LogiConsService:
    """获取逻辑自洽服务单例"""
    global _service
    if _service is None:
        _service = LogiConsService()
    return _service
