"""Sandbox 共享数据层占位实现。

完整实现依赖独立工作区中的图数据库与项目事实管道。此处提供最小桩实现，
保证应用可导入、启动；调用 baseline 等接口时若未配置真实数据会得到空结果或明确错误。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def load_project_facts(*, start_year: int, end_year: int) -> list[Any]:
    return []


def build_topic_aggregates(project_facts: list[Any]) -> list[Any]:
    return []


def build_topic_year_aggregates(project_facts: list[Any]) -> list[Any]:
    return []


def load_graph_topic_metrics(*, start_year: int, end_year: int) -> list[Any]:
    return []


def load_graph_window_metadata(*, start_year: int, end_year: int) -> dict[str, Any]:
    return {}


def load_topic_migration_edges(*, start_year: int, end_year: int) -> list[Any]:
    return []


@dataclass
class GraphProfileStub:
    status: str = "stub"
    message: str = "sandbox data layer not configured in this workspace"


@dataclass
class GraphReadinessStub:
    ready: bool = False
    message: str = "sandbox data layer not configured in this workspace"


def inspect_graph_profile() -> GraphProfileStub:
    return GraphProfileStub()


def verify_graph_readiness() -> GraphReadinessStub:
    return GraphReadinessStub()
