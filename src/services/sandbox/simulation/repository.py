"""File-backed persistence for native sandbox simulation artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.models.simulation import BaselineSnapshot, SimulationResult
from src.services.sandbox.simulation.debug_html import render_debug_html
from src.services.sandbox.simulation.debug_payload import build_debug_payload

DEBUG_ROOT = Path("debug_sandbox")
BASE_DIR = Path("debug_sandbox/simulation")
LATEST_BASELINE_PATH = BASE_DIR / "baseline_latest.json"
LATEST_SCENARIO_PATH = BASE_DIR / "scenario_latest.json"
LATEST_SCENARIO_DEFINITION_PATH = BASE_DIR / "scenario_latest.definition.json"
LATEST_BASELINE_DEBUG_JSON_PATH = BASE_DIR / "baseline_latest.debug.json"
LATEST_BASELINE_DEBUG_HTML_PATH = BASE_DIR / "baseline_latest.debug.html"
LATEST_SCENARIO_DEBUG_JSON_PATH = BASE_DIR / "scenario_latest.debug.json"
LATEST_SCENARIO_DEBUG_HTML_PATH = BASE_DIR / "scenario_latest.debug.html"


def save_baseline_snapshot(snapshot: BaselineSnapshot) -> dict[str, str]:
    debug_artifacts = _debug_artifact_refs(
        json_path=LATEST_BASELINE_DEBUG_JSON_PATH,
        html_path=LATEST_BASELINE_DEBUG_HTML_PATH,
    )
    _attach_debug_artifacts(snapshot, debug_artifacts)
    _write_model(LATEST_BASELINE_PATH, snapshot)
    save_baseline_debug_artifacts(snapshot)
    return debug_artifacts


def load_latest_baseline_snapshot() -> BaselineSnapshot | None:
    return _read_model(LATEST_BASELINE_PATH, BaselineSnapshot)


def save_scenario_result(
    result: SimulationResult,
    *,
    baseline: BaselineSnapshot | None = None,
    scenario: Any = None,
    comparison: Any = None,
    explanation: Any = None,
    contract: Any = None,
    compiled: Any = None,
) -> dict[str, str]:
    debug_artifacts = _debug_artifact_refs(
        json_path=LATEST_SCENARIO_DEBUG_JSON_PATH,
        html_path=LATEST_SCENARIO_DEBUG_HTML_PATH,
    )
    _attach_debug_artifacts(result, debug_artifacts)
    _write_model(LATEST_SCENARIO_PATH, result)
    save_scenario_debug_artifacts(
        result,
        baseline=baseline,
        scenario=scenario,
        comparison=comparison,
        explanation=explanation,
        contract=contract,
        compiled=compiled,
    )
    return debug_artifacts


def save_scenario_definition(scenario: Any) -> None:
    _write_model(LATEST_SCENARIO_DEFINITION_PATH, scenario)


def load_latest_scenario_definition() -> dict[str, Any] | None:
    if not LATEST_SCENARIO_DEFINITION_PATH.exists():
        return None
    with LATEST_SCENARIO_DEFINITION_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_latest_scenario_result() -> SimulationResult | None:
    return _read_model(LATEST_SCENARIO_PATH, SimulationResult)


def get_baseline_debug_artifacts() -> dict[str, str]:
    return _get_debug_artifacts(
        json_path=LATEST_BASELINE_DEBUG_JSON_PATH,
        html_path=LATEST_BASELINE_DEBUG_HTML_PATH,
    )


def get_scenario_debug_artifacts() -> dict[str, str]:
    return _get_debug_artifacts(
        json_path=LATEST_SCENARIO_DEBUG_JSON_PATH,
        html_path=LATEST_SCENARIO_DEBUG_HTML_PATH,
    )


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
    baseline: BaselineSnapshot | None = None,
    scenario: Any = None,
    comparison: Any = None,
    explanation: Any = None,
    contract: Any = None,
    compiled: Any = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    debug_payload = payload or build_scenario_debug_payload(
        result,
        baseline=baseline,
        scenario=scenario,
        comparison=comparison,
        explanation=explanation,
        contract=contract,
        compiled=compiled,
    )
    return _save_debug_bundle(
        payload=debug_payload,
        json_path=LATEST_SCENARIO_DEBUG_JSON_PATH,
        html_path=LATEST_SCENARIO_DEBUG_HTML_PATH,
        html_title=f"Sandbox Simulation Scenario Debug - {result.run_id}",
    )


def build_baseline_debug_payload(snapshot: BaselineSnapshot) -> dict[str, Any]:
    payload = build_debug_payload(baseline=snapshot)
    payload["meta"] = {
        "artifact_kind": "baseline",
        "generated_at": _now_text(),
        "baseline_id": snapshot.baseline_id,
        "forecast_window": snapshot.forecast_window,
    }
    return payload


def build_scenario_debug_payload(
    result: SimulationResult,
    *,
    baseline: BaselineSnapshot | None = None,
    scenario: Any = None,
    comparison: Any = None,
    explanation: Any = None,
    contract: Any = None,
    compiled: Any = None,
) -> dict[str, Any]:
    comparison_error = None
    explanation_error = None

    if comparison is None:
        try:
            from src.services.sandbox.simulation.compare_service import compare_result

            comparison = compare_result(result)
        except Exception as exc:  # pragma: no cover - best effort debug artifact
            comparison_error = f"failed to build comparison: {exc.__class__.__name__}"

    if explanation is None:
        try:
            from src.services.sandbox.simulation.explain_service import explain_result

            explanation = explain_result(result)
        except Exception as exc:  # pragma: no cover - best effort debug artifact
            explanation_error = f"failed to build explanation: {exc.__class__.__name__}"

    normalized_scenario = _model_dump_if_needed(scenario)

    payload = build_debug_payload(
        baseline=baseline,
        scenario=scenario,
        result=result,
        comparison=comparison,
        explanation=explanation,
        contract=contract,
        compiled=compiled,
    )
    payload["meta"] = {
        "artifact_kind": "scenario",
        "generated_at": _now_text(),
        "baseline_id": result.baseline_id,
        "scenario_id": result.scenario_id,
        "run_id": result.run_id,
        "forecast_window": result.forecast_window,
        "engine": result.metadata.get("engine"),
    }
    if normalized_scenario is not None:
        payload["scenario"] = normalized_scenario
    if comparison_error is not None:
        payload["comparison"] = {"error": comparison_error}
        payload["sanity_summary"]["warnings"].append(comparison_error)
    if explanation_error is not None:
        payload["explanation"] = {"error": explanation_error}
        payload["sanity_summary"]["warnings"].append(explanation_error)
    return payload


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(_model_dump_if_needed(model), fh, ensure_ascii=False, indent=2)


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
    payload.setdefault("meta", {})
    payload["meta"]["debug_json_path"] = str(json_path.resolve())
    payload["meta"]["debug_json_url"] = f"/debug-sandbox/{json_path.relative_to(DEBUG_ROOT).as_posix()}"
    payload["meta"]["debug_html_path"] = str(html_path.resolve())
    payload["meta"]["debug_html_url"] = f"/debug-sandbox/{html_path.relative_to(DEBUG_ROOT).as_posix()}"
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


def _get_debug_artifacts(
    *,
    json_path: Path,
    html_path: Path,
) -> dict[str, str]:
    payload: dict[str, str] = {}
    if json_path.exists():
        payload.update(_debug_artifact_refs(json_path=json_path, html_path=html_path, include_html=False))
    if html_path.exists():
        payload.update(_debug_artifact_refs(json_path=json_path, html_path=html_path, include_json=False))
    return payload


def _debug_artifact_refs(
    *,
    json_path: Path,
    html_path: Path,
    include_json: bool = True,
    include_html: bool = True,
) -> dict[str, str]:
    payload: dict[str, str] = {}
    if include_json:
        json_rel = json_path.relative_to(DEBUG_ROOT).as_posix()
        payload["debug_json_path"] = str(json_path.resolve())
        payload["debug_json_url"] = f"/debug-sandbox/{json_rel}"
    if include_html:
        html_rel = html_path.relative_to(DEBUG_ROOT).as_posix()
        payload["debug_html_path"] = str(html_path.resolve())
        payload["debug_html_url"] = f"/debug-sandbox/{html_rel}"
    return payload


def _attach_debug_artifacts(model: Any, debug_artifacts: dict[str, str]) -> None:
    metadata = getattr(model, "metadata", None)
    if isinstance(metadata, dict):
        metadata["debugArtifacts"] = dict(debug_artifacts)


def _model_dump_if_needed(value: Any) -> Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
