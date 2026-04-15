from typing import Any, Optional

from src.common.models.logicon import LogicOnResult
from src.services.logicon.agent import LogicOnAgent


class LogicOnService:
    def __init__(self):
        pass

    async def check_file(
        self,
        *,
        file_data: bytes,
        file_type: str,
        doc_kind: str = "auto",
        enable_llm: bool = False,
        return_graph: bool = False,
        amount_tolerance_wan: float = 0.01,
        date_tolerance_days: int = 30,
        metric_tolerance_ratio: float = 0.01,
        **kwargs: Any,
    ) -> LogicOnResult:
        agent = LogicOnAgent(
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
        )
        return await agent.check_file(
            file_data=file_data,
            file_type=file_type,
            doc_kind=doc_kind,
            enable_llm=enable_llm,
            return_graph=return_graph,
            **kwargs,
        )

    async def check_text(
        self,
        *,
        text: str,
        doc_kind: str = "auto",
        enable_llm: bool = False,
        return_graph: bool = False,
        amount_tolerance_wan: float = 0.01,
        date_tolerance_days: int = 30,
        metric_tolerance_ratio: float = 0.01,
        **kwargs: Any,
    ) -> LogicOnResult:
        agent = LogicOnAgent(
            amount_tolerance_wan=amount_tolerance_wan,
            date_tolerance_days=date_tolerance_days,
            metric_tolerance_ratio=metric_tolerance_ratio,
        )
        return await agent.check_text(
            text=text,
            doc_kind=doc_kind,
            enable_llm=enable_llm,
            return_graph=return_graph,
            **kwargs,
        )
