"""File-backed persistence for native sandbox simulation artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from src.common.models.simulation import BaselineSnapshot, SimulationResult

BASE_DIR = Path("debug_sandbox/simulation")
LATEST_BASELINE_PATH = BASE_DIR / "baseline_latest.json"
LATEST_SCENARIO_PATH = BASE_DIR / "scenario_latest.json"


def save_baseline_snapshot(snapshot: BaselineSnapshot) -> None:
    _write_model(LATEST_BASELINE_PATH, snapshot)


def load_latest_baseline_snapshot() -> BaselineSnapshot | None:
    return _read_model(LATEST_BASELINE_PATH, BaselineSnapshot)


def save_scenario_result(result: SimulationResult) -> None:
    _write_model(LATEST_SCENARIO_PATH, result)


def load_latest_scenario_result() -> SimulationResult | None:
    return _read_model(LATEST_SCENARIO_PATH, SimulationResult)


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(model.model_dump(), fh, ensure_ascii=False, indent=2)


def _read_model(path: Path, model_cls):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return model_cls.model_validate(payload)
