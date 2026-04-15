"""File-backed persistence for native sandbox simulation artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.models.simulation import BaselineSnapshot, ScenarioDefinition, SimulationResult
from src.services.sandbox.simulation.debug_html import render_debug_html

DEBUG_ROOT = Path("debug_sandbox")
BASE_DIR = Path("debug_sandbox/simulation")
LATEST_BASELINE_PATH = BASE_DIR / "baseline_latest.json"
LATEST_SCENARIO_PATH = BASE_DIR / "scenario_latest.json"
LATEST_SCENARIO_DEFINITION_PATH = BASE_DIR / "scenario_latest.definition.json"
LATEST_BASELINE_DEBUG_JSON_PATH = BASE_DIR / "baseline_latest.debug.json"
LATEST_BASELINE_DEBUG_HTML_PATH = BASE_DIR / "baseline_latest.debug.html"
LATEST_SCENARIO_DEBUG_JSON_PATH = BASE_DIR / "scenario_latest.debug.json"
LATEST_SCENARIO_DEBUG_HTML_PATH = BASE_DIR / "scenario_latest.debug.html"


def save_baseline_snapshot(snapshot: BaselineSnapshot) -> None:
    _write_model(LATEST_BASELINE_PATH, snapshot)
    save_baseline_debug_artifacts(snapshot)


def load_latest_baseline_snapshot() -> BaselineSnapshot | None:
    return _read_model(LATEST_BASELINE_PATH, BaselineSnapshot)


def save_scenario_result(result: SimulationResult) -> None:
    _write_model(LATEST_SCENARIO_PATH, result)
    save_scenario_debug_artifacts(result)


def save_scenario_definition(scenario: ScenarioDefinition) -> None:
    _write_model(LATEST_SCENARIO_DEFINITION_PATH, scenario)


def load_latest_scenario_definition() -> ScenarioDefinition | None:
    return _read_model(LATEST_SCENARIO_DEFINITION_PATH, ScenarioDefinition)


def load_latest_scenario_result() -> SimulationResult | None:
    return _read_model(LATEST_SCENARIO_PATH, SimulationResult)


def save_baseline_debug_artifacts(
    snapshot: BaselineSnapshot,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    debug_payload = payload or build_baseline_debug_payload(snapshot)
    return _save_debug_bundle(
        payload=debug_payload,
        json_path=LATEST_BASELINE_DEBUG_JSON_PATH,
        html_path=LATEST_BASELINE_DEBUG_HTML_PATH,
        html_title=f"Sandbox Simulation Baseline Debug - {snapshot.baseline_id}",
    )


def save_scenario_debug_artifacts(
    result: SimulationResult,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    debug_payload = payload or build_scenario_debug_payload(result)
    return _save_debug_bundle(
        payload=debug_payload,
        json_path=LATEST_SCENARIO_DEBUG_JSON_PATH,
        html_path=LATEST_SCENARIO_DEBUG_HTML_PATH,
        html_title=f"Sandbox Simulation Scenario Debug - {result.run_id}",
    )


def build_baseline_debug_payload(snapshot: BaselineSnapshot) -> dict[str, Any]:
    return {
        "meta": {
            "artifact_kind": "baseline",
            "generated_at": _now_text(),
            "baseline_id": snapshot.baseline_id,
            "forecast_window": snapshot.forecast_window,
        },
        "baseline": snapshot.model_dump(),
    }


def build_scenario_debug_payload(result: SimulationResult) -> dict[str, Any]:
    baseline = load_latest_baseline_snapshot()
    if baseline is not None and baseline.baseline_id != result.baseline_id:
        baseline = None

    scenario = load_latest_scenario_definition()
    if scenario is not None and (
        scenario.scenario_id != result.scenario_id or scenario.baseline_id != result.baseline_id
    ):
        scenario = None

    comparison = None
    explanation = None
    try:
        from src.services.sandbox.simulation.compare_service import compare_result

        comparison = compare_result(result).model_dump()
    except Exception as exc:  # pragma: no cover - best effort debug artifact
        comparison = {
            "error": f"failed to build comparison: {exc.__class__.__name__}",
        }

    try:
        from src.services.sandbox.simulation.explain_service import explain_result

        explanation = explain_result(result).model_dump()
    except Exception as exc:  # pragma: no cover - best effort debug artifact
        explanation = {
            "error": f"failed to build explanation: {exc.__class__.__name__}",
        }

    return {
        "meta": {
            "artifact_kind": "scenario",
            "generated_at": _now_text(),
            "baseline_id": result.baseline_id,
            "scenario_id": result.scenario_id,
            "run_id": result.run_id,
            "forecast_window": result.forecast_window,
            "engine": result.metadata.get("engine"),
        },
        "baseline": baseline.model_dump(mode="json") if baseline else None,
        "scenario": scenario.model_dump(mode="json") if scenario else None,
        "result": result.model_dump(),
        "comparison": comparison,
        "explanation": explanation,
    }


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


def _save_debug_bundle(
    *,
    payload: dict[str, Any],
    json_path: Path,
    html_path: Path,
    html_title: str,
) -> dict[str, str]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    html_content = render_debug_html(payload, title=html_title)
    html_path.write_text(html_content, encoding="utf-8")

    json_rel = json_path.relative_to(DEBUG_ROOT).as_posix()
    html_rel = html_path.relative_to(DEBUG_ROOT).as_posix()

    return {
        "json_path": str(json_path),
        "html_path": str(html_path),
        "json_url": f"/debug-sandbox/{json_rel}",
        "html_url": f"/debug-sandbox/{html_rel}",
    }


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
