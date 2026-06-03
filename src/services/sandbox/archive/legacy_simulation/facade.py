"""Unified public facade for sandbox simulation."""

from __future__ import annotations

from typing import Any


def run_forecast(*args: Any, **kwargs: Any):
    from .prototype import run_forecast as _run_forecast

    return _run_forecast(*args, **kwargs)


def load_latest_report(*args: Any, **kwargs: Any):
    from .prototype import load_latest_report as _load_latest_report

    return _load_latest_report(*args, **kwargs)


def run_baseline_snapshot(*args: Any, **kwargs: Any):
    from .baseline_service import run_baseline_snapshot as _run_baseline_snapshot

    return _run_baseline_snapshot(*args, **kwargs)


def load_latest_baseline_snapshot(*args: Any, **kwargs: Any):
    from .baseline_service import load_latest_baseline_snapshot as _load_latest_baseline_snapshot

    return _load_latest_baseline_snapshot(*args, **kwargs)


def report_to_baseline_snapshot(*args: Any, **kwargs: Any):
    from .baseline_service import report_to_baseline_snapshot as _report_to_baseline_snapshot

    return _report_to_baseline_snapshot(*args, **kwargs)


def run_scenario(*args: Any, **kwargs: Any):
    from .scenario_service import run_scenario as _run_scenario

    return _run_scenario(*args, **kwargs)


def load_latest_scenario_result(*args: Any, **kwargs: Any):
    from .scenario_service import load_latest_scenario_result as _load_latest_scenario_result

    return _load_latest_scenario_result(*args, **kwargs)


def build_default_scenario(*args: Any, **kwargs: Any):
    from .scenario_service import build_default_scenario as _build_default_scenario

    return _build_default_scenario(*args, **kwargs)


def report_to_simulation_result(*args: Any, **kwargs: Any):
    from .scenario_service import report_to_simulation_result as _report_to_simulation_result

    return _report_to_simulation_result(*args, **kwargs)
