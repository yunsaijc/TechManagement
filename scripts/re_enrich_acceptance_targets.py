#!/usr/bin/env python3
"""用最新定位逻辑重算 debug_accept 中已有项目的 viewer_rects。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.models.document import BoundingBox
from src.services.accept.models import ParsedAcceptanceBlock
from src.services.accept.render_acceptance_html import write_acceptance_results_files
from src.services.accept.viewer_target import build_page_sizes_map, enrich_acceptance_project_targets


def _block_from_dict(block_id: str, data: dict) -> ParsedAcceptanceBlock:
    bbox_data = data.get("bbox")
    bbox = None
    if isinstance(bbox_data, dict):
        bbox = BoundingBox(
            x=float(bbox_data.get("x") or 0),
            y=float(bbox_data.get("y") or 0),
            width=float(bbox_data.get("width") or bbox_data.get("w") or 0),
            height=float(bbox_data.get("height") or bbox_data.get("h") or 0),
        )
    return ParsedAcceptanceBlock(
        block_id=block_id,
        text=str(data.get("text") or ""),
        page=int(data.get("page") or 0),
        bbox=bbox,
        line_index_start=int(data.get("line_index_start") or 0),
        line_index_end=int(data.get("line_index_end") or 0),
    )


def _resolve_file_path(doc: dict, input_dir: Path) -> Path | None:
    raw = str(doc.get("file_path") or "").strip()
    if raw:
        candidate = Path(raw)
        if candidate.exists():
            return candidate
    browser = str(doc.get("browser_file") or "").strip()
    if browser:
        candidate = input_dir / browser
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    input_dir = ROOT / "debug_accept"
    results_path = input_dir / "acceptance_results.json"
    if not results_path.exists():
        print(f"[re-enrich] missing {results_path}")
        return 1

    projects = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(projects, list):
        print("[re-enrich] acceptance_results.json must be a list")
        return 1

    for project in projects:
        if not isinstance(project, dict):
            continue
        project_no = str(project.get("project_no") or "")
        document_blocks: dict[str, list[ParsedAcceptanceBlock]] = {}
        document_paths: dict[str, Path] = {}
        documents = project.get("documents")
        if not isinstance(documents, list):
            continue
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            file_name = str(doc.get("file_name") or "")
            if not file_name:
                continue
            file_path = _resolve_file_path(doc, input_dir)
            if file_path is not None:
                document_paths[file_name] = file_path
                doc["page_sizes"] = build_page_sizes_map(file_path)
            blocks_dict = doc.get("blocks")
            if isinstance(blocks_dict, dict):
                document_blocks[file_name] = [
                    _block_from_dict(block_id, block_data)
                    for block_id, block_data in blocks_dict.items()
                    if isinstance(block_data, dict)
                ]
        enrich_acceptance_project_targets(
            project,
            document_blocks=document_blocks,
            document_paths=document_paths,
        )
        print(f"[re-enrich] updated targets for {project_no}")

    results_path.write_text(json.dumps(projects, ensure_ascii=False), encoding="utf-8")
    write_acceptance_results_files(input_dir, projects)
    print(f"[re-enrich] wrote {results_path} and split frontend payloads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
