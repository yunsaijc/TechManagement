#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from html import escape
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mammoth

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional preview dependency
    Image = None  # type: ignore[assignment]

try:
    import fitz
except ImportError:  # pragma: no cover - optional viewer dependency
    fitz = None  # type: ignore[assignment]

from src.common.models.document import BoundingBox
from src.services.accept.models import ParsedAcceptanceDocument
from src.services.accept.debug_workflow import (
    refresh_acceptance_project_payload,
    run_acceptance_project_pipeline,
    sanitize_json_compatible,
    sanitize_text_value,
)
from src.services.accept.render_acceptance_html import write_acceptance_html_shell, write_acceptance_results_files
from src.services.accept.service import AcceptanceAttachmentInput, AcceptanceService

try:
    import importlib.util

    _PACKET_BUILDER_PATH = ROOT / "src" / "services" / "evaluation" / "packet_builder.py"
    _PACKET_BUILDER_SPEC = importlib.util.spec_from_file_location(
        "accept_packet_builder",
        _PACKET_BUILDER_PATH,
    )
    if _PACKET_BUILDER_SPEC and _PACKET_BUILDER_SPEC.loader:
        _PACKET_BUILDER_MODULE = importlib.util.module_from_spec(_PACKET_BUILDER_SPEC)
        _PACKET_BUILDER_SPEC.loader.exec_module(_PACKET_BUILDER_MODULE)
        EvaluationPacketBuilder = getattr(_PACKET_BUILDER_MODULE, "EvaluationPacketBuilder", object)
    else:  # pragma: no cover - defensive fallback
        EvaluationPacketBuilder = object  # type: ignore[assignment]
except Exception:  # pragma: no cover - optional viewer dependency
    EvaluationPacketBuilder = object  # type: ignore[assignment]

try:
    from scripts.docx_preview_pdf import docx_to_pdf
except ImportError:  # pragma: no cover - optional preview dependency
    docx_to_pdf = None  # type: ignore[assignment]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local acceptance checks for a sampled batch.")
    parser.add_argument("--input-dir", default="debug_accept")
    parser.add_argument("--year", default="2019")
    parser.add_argument("--project-no", action="append", default=[], help="Only process the specified project number. Can be repeated.")
    parser.add_argument("--project-name", default="", help="Project name for single-project runs.")
    parser.add_argument("--taskbook-path", default="", help="Explicit taskbook path for a single project.")
    parser.add_argument("--acceptance-application-path", default="", help="Explicit acceptance application path for a single project.")
    parser.add_argument("--acceptance-attachment-dir", default="", help="Explicit acceptance attachment directory for a single project.")
    parser.add_argument("--disable-candidate-filter", action="store_true", help="Parse all attachments instead of coarse candidate filtering.")
    parser.add_argument("--skip-viewer", action="store_true", help="Skip generating PDF viewer assets for faster batch runs.")
    return parser.parse_args()


def read_pairings(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def load_existing_results(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def merge_project_results(
    existing_results: list[dict[str, object]],
    new_results: list[dict[str, object]],
) -> list[dict[str, object]]:
    """按 project_no 合并批处理结果，避免单项目重跑覆盖其它项目。"""
    replaced = {str(item.get("project_no") or "") for item in new_results if str(item.get("project_no") or "")}
    if not replaced:
        return list(existing_results)
    merged = [
        item
        for item in existing_results
        if str(item.get("project_no") or "") not in replaced
    ]
    merged.extend(new_results)
    return merged


def backup_results_file(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        return
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_path.write_bytes(path.read_bytes())


def detect_file_type(file_name: str) -> str:
    return file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "txt"


def slugify(value: str) -> str:
    safe = []
    for ch in value.strip():
        safe.append(ch if ch.isalnum() else "_")
    return "".join(safe).strip("_") or "doc"


METRIC_ATTACHMENT_HINTS = {
    "发明专利": ("专利", "专利证", "知识产权", "发明", "受理", "授权"),
    "实用新型专利": ("专利", "专利证", "知识产权", "实用新型", "受理", "授权"),
    "软件著作权": ("软著", "软件著作权", "著作权", "登记证"),
    "科技论文": ("论文", "期刊", "录用", "文章", "journal", "article", "paper", "doi"),
    "培养研究生": ("学位论文", "硕士学位论文", "研究生", "硕士", "博士"),
    "科技报告": ("报告", "科技报告", "总结"),
    "研究报告": ("报告", "研究报告", "总结"),
    "决策咨询报告": ("报告", "咨询"),
    "技术标准": ("标准",),
    "新增销售收入": ("审计", "财务", "销售", "收入", "发票", "合同"),
    "新增利税": ("审计", "财务", "利税", "利润", "发票", "合同"),
}
GENERIC_ATTACHMENT_HINTS = ("验收", "申请", "自评价", "总结", "报告", "审计", "合同", "发票", "检测")
TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,}")
WHITESPACE_PATTERN = re.compile(r"\s+")


def _require_fitz() -> object:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required for PDF viewer assets. Install pymupdf or use --skip-viewer.")
    return fitz


@lru_cache(maxsize=512)
def get_document_page_size(path_str: str, page_index: int) -> tuple[float, float] | None:
    path = Path(path_str)
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = _require_fitz().open(path)
        try:
            if page_index < 0 or page_index >= doc.page_count:
                return None
            rect = doc.load_page(page_index).rect
            return float(rect.width or 0.0), float(rect.height or 0.0)
        finally:
            doc.close()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}:
        if Image is None:
            return None
        if page_index not in {0, 1}:
            return None
        with Image.open(path) as image:
            return float(image.width or 0.0), float(image.height or 0.0)
    return None


def normalize_rect(path: Path, page_index: int, bbox: BoundingBox | None) -> list[dict[str, float]]:
    if bbox is None:
        return []
    page_size = get_document_page_size(str(path), page_index)
    if not page_size:
        return []
    page_width, page_height = page_size
    if page_width <= 0 or page_height <= 0:
        return []
    x = max(0.0, min(float(bbox.x) / page_width, 1.0))
    y = max(0.0, min(float(bbox.y) / page_height, 1.0))
    w = max(0.0, min(float(bbox.width) / page_width, 1.0 - x))
    h = max(0.0, min(float(bbox.height) / page_height, 1.0 - y))
    if w <= 0 or h <= 0:
        return []
    return [{"x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6)}]


def inflate_rects(rects: list[dict[str, float]], *, pad_x: float = 0.008, pad_y: float = 0.012) -> list[dict[str, float]]:
    if not rects:
        return []
    inflated: list[dict[str, float]] = []
    for rect in rects:
        if not isinstance(rect, dict):
            continue
        x = max(0.0, float(rect.get("x") or 0.0) - pad_x)
        y = max(0.0, float(rect.get("y") or 0.0) - pad_y)
        w = float(rect.get("w") or 0.0) + pad_x * 2
        h = float(rect.get("h") or 0.0) + pad_y * 2
        if w <= 0 or h <= 0:
            continue
        if x + w > 1.0:
            w = max(0.0, 1.0 - x)
        if y + h > 1.0:
            h = max(0.0, 1.0 - y)
        if w <= 0 or h <= 0:
            continue
        inflated.append(
            {
                "x": round(x, 6),
                "y": round(y, 6),
                "w": round(w, 6),
                "h": round(h, 6),
            }
        )
    return inflated


def merge_rects(rects: list[dict[str, float]]) -> list[dict[str, float]]:
    if not rects:
        return []
    xs = []
    ys = []
    x2s = []
    y2s = []
    for rect in rects:
        if not isinstance(rect, dict):
            continue
        x = float(rect.get("x") or 0.0)
        y = float(rect.get("y") or 0.0)
        w = float(rect.get("w") or 0.0)
        h = float(rect.get("h") or 0.0)
        if w <= 0 or h <= 0:
            continue
        xs.append(x)
        ys.append(y)
        x2s.append(x + w)
        y2s.append(y + h)
    if not xs:
        return []
    x1 = max(0.0, min(xs))
    y1 = max(0.0, min(ys))
    x2 = min(1.0, max(x2s))
    y2 = min(1.0, max(y2s))
    if x2 <= x1 or y2 <= y1:
        return []
    return [{"x": round(x1, 6), "y": round(y1, 6), "w": round(x2 - x1, 6), "h": round(y2 - y1, 6)}]


def preferred_block_rect(
    path: Path,
    page_index: int,
    block: object | None,
    text: str,
    *,
    title: str = "",
    doc_kind: str = "",
    blocks: list[object] | None = None,
    metric_name: str = "",
) -> list[dict[str, float]]:
    if blocks:
        from src.services.accept.viewer_target import resolve_evidence_target

        resolved = resolve_evidence_target(
            file_path=path,
            page_index=page_index,
            block=block,  # type: ignore[arg-type]
            blocks=blocks,  # type: ignore[arg-type]
            text=text,
            metric_name=metric_name,
            title=title,
            doc_kind=doc_kind,
        )
        rects = resolved.get("viewer_rects") or []
        if rects:
            return inflate_rects(rects)
    rects: list[dict[str, float]] = []
    if block is not None:
        bbox = getattr(block, "bbox", None)
        rects = normalize_rect(path, page_index, bbox)
    if not rects and text:
        rects = search_rects_in_pdf(path, page_index, text)
    rects = merge_rects(rects) if len(rects) > 1 else rects
    return inflate_rects(rects)


def _normalize_search_text(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()


def _candidate_search_texts(text: str) -> list[str]:
    compact = _normalize_search_text(text)
    if not compact:
        return []
    candidates: list[str] = [compact]
    for sep in ("；", ";", "。", ".", "，", ",", ":", "："):
        if sep in compact:
            parts = [part.strip() for part in compact.split(sep) if len(part.strip()) >= 8]
            candidates.extend(parts[:4])
    deduped: list[str] = []
    seen = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if len(normalized) < 6 or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized[:180])
    return deduped


def search_rects_in_pdf(path: Path, page_index: int, text: str) -> list[dict[str, float]]:
    if path.suffix.lower() != ".pdf":
        return []
    candidates = _candidate_search_texts(text)
    if not candidates:
        return []
    doc = _require_fitz().open(path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        page_rect = page.rect
        if page_rect.width <= 0 or page_rect.height <= 0:
            return []
        for candidate in candidates:
            try:
                hits = page.search_for(candidate)
            except Exception:
                hits = []
            if not hits:
                continue
            rects: list[dict[str, float]] = []
            for hit in hits[:6]:
                x = max(0.0, min(float(hit.x0) / page_rect.width, 1.0))
                y = max(0.0, min(float(hit.y0) / page_rect.height, 1.0))
                w = max(0.0, min(float(hit.width) / page_rect.width, 1.0 - x))
                h = max(0.0, min(float(hit.height) / page_rect.height, 1.0 - y))
                if w <= 0 or h <= 0:
                    continue
                rects.append({"x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6)})
            if rects:
                return rects
        return []
    finally:
        doc.close()


def tokenize_text(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text or "")}


async def select_candidate_attachment_paths(
    *,
    attachment_dir: Path,
    taskbook: ParsedAcceptanceDocument,
    yssq: ParsedAcceptanceDocument,
    service: AcceptanceService,
) -> list[Path]:
    all_files = sorted(file_path for file_path in attachment_dir.rglob("*") if file_path.is_file())
    if not all_files:
        return []

    commitments = service.kpi_extractor.extract(taskbook)
    project_tokens = {
        token
        for token in tokenize_text(f"{taskbook.text}\n{yssq.text}")
        if len(token) >= 4 and not token.isdigit()
    }
    required_hints = set(GENERIC_ATTACHMENT_HINTS)
    for commitment in commitments:
        required_hints.update(METRIC_ATTACHMENT_HINTS.get(commitment.metric_name, ()))
        required_hints.update(keyword for keyword in commitment.keywords if len(keyword) >= 2)

    selected: list[Path] = []
    pending_parse_paths: list[Path] = []
    for file_path in all_files:
        name = file_path.name.lower()
        if any(hint.lower() in name for hint in required_hints):
            selected.append(file_path)
            continue
        pending_parse_paths.append(file_path)

    semaphore = asyncio.Semaphore(4)

    async def _inspect_candidate(file_path: Path) -> Path | None:
        try:
            async with semaphore:
                parsed_document = await service.parser.parse_bytes(
                    file_data=file_path.read_bytes(),
                    file_type=detect_file_type(file_path.name),
                    file_name=file_path.name,
                )
        except Exception:
            return None
        file_tokens = tokenize_text(f"{file_path.stem}\n{parsed_document.text[:4000]}")
        if project_tokens and file_tokens & project_tokens:
            return file_path
        # Fall back to parsed evidence signals so split/renamed deliverable PDFs
        # are not dropped just because the filename lacks obvious project hints.
        try:
            evidence_items = service.evidence_normalizer.normalize(service.extract_evidence(parsed_document))
        except Exception:
            evidence_items = []
        if any(
            item.evidence_role != "derived"
            and item.evidence_mode in {"itemized", "summary"}
            and item.metric_category in {"成果产出", "知识产权", "人才培养"}
            for item in evidence_items
        ):
            return file_path
        return None

    inspected = await asyncio.gather(*(_inspect_candidate(file_path) for file_path in pending_parse_paths))
    selected.extend(path for path in inspected if path is not None)

    if not selected:
        return all_files

    # Avoid over-pruning: if coarse filter still keeps very little, add summary-like reports as a backstop.
    selected_set = {path.resolve() for path in selected}
    for file_path in all_files:
        name = file_path.name.lower()
        if file_path.resolve() in selected_set:
            continue
        if any(hint.lower() in name for hint in GENERIC_ATTACHMENT_HINTS):
            selected.append(file_path)
            selected_set.add(file_path.resolve())
    return sorted(selected)


def build_pdf_viewer_assets(
    *,
    builder: EvaluationPacketBuilder | None,
    viewers_root: Path,
    project_no: str,
    file_path: Path,
) -> dict[str, object]:
    if builder is None:
        return {}
    if file_path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}:
        return {}
    viewer_project_id = f"{project_no}_{slugify(file_path.stem)}"
    packet_root = viewers_root / "projects" / viewer_project_id
    viewer_file = packet_root / "packet_viewer.html"
    packet_file = packet_root / "evaluation_packet.pdf"
    if viewer_file.exists() and not _packet_viewer_needs_rebuild(viewer_file):
        page_images = []
        page_dir = packet_root / "packet_pages"
        if page_dir.exists():
            for page_image in sorted(page_dir.glob("page-*.png")):
                page_images.append({"image_file": str(page_image)})
        subdocs = []
        subdocs_file = packet_root / "virtual_subdocs.json"
        if subdocs_file.exists():
            try:
                subdocs = json.loads(subdocs_file.read_text(encoding="utf-8"))
            except Exception:
                subdocs = []
        return {
            "viewer_file": f"viewers/projects/{viewer_project_id}/packet_viewer.html",
            "packet_file": f"viewers/projects/{viewer_project_id}/evaluation_packet.pdf" if packet_file.exists() else "",
            "page_images": page_images,
            "subdocs": subdocs,
        }
    packet = builder.build(
        output_dir=viewers_root,
        project_id=viewer_project_id,
        source_file=str(file_path),
        source_name=file_path.name,
        attachments=[],
    )
    if not packet:
        return {}
    return {
        "viewer_file": f"viewers/{packet.get('viewer_file', '')}",
        "packet_file": f"viewers/{packet.get('packet_file', '')}",
        "page_images": packet.get("page_images", []),
        "subdocs": packet.get("subdocs", []),
    }


def _packet_viewer_needs_rebuild(viewer_file: Path) -> bool:
    try:
        html = viewer_file.read_text(encoding="utf-8")
    except Exception:
        return True
    # Older generated viewers put page images directly inside .packet-page, so
    # the fit-to-width image CSS did not apply and scanned certificates were cropped.
    return "<div class='packet-page-canvas'>" not in html and 'class="packet-page-canvas"' not in html


def to_browser_relative(input_dir: Path, file_path: Path) -> str:
    try:
        return file_path.resolve().relative_to(input_dir.resolve()).as_posix()
    except ValueError:
        return str(file_path)


def build_office_preview_assets(
    *,
    input_dir: Path,
    project_no: str,
    file_path: Path,
) -> dict[str, object]:
    suffix = file_path.suffix.lower()
    if suffix not in {".doc", ".docx"}:
        return {}

    def is_usable_preview_html(html_path: Path) -> bool:
        if not html_path.exists() or html_path.stat().st_size <= 0:
            return False
        try:
            content = html_path.read_text(encoding="utf-8")
        except Exception:
            return False
        if "Message(type='warning'" in content or "An unrecognised element was ignored" in content:
            return False
        if "Unrecognised paragraph style" in content:
            return False
        return True

    def is_usable_preview_pdf(pdf_path: Path, *, strict: bool = True) -> bool:
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            return False
        try:
            doc = _require_fitz().open(pdf_path)
        except Exception:
            return False
        try:
            if doc.page_count <= 0:
                return False
            if strict and doc.page_count == 1:
                text = doc[0].get_text("text") or ""
                # Single-page, text-heavy outputs are typically the fallback htmlbox PDF,
                # which destroys original pagination/table layout for Word previews.
                if len(text.strip()) >= 4000:
                    return False
            return True
        finally:
            doc.close()

    preview_root = input_dir / "viewers" / "original_docs" / f"{project_no}_{slugify(file_path.stem)}"
    preview_root.mkdir(parents=True, exist_ok=True)
    preview_html = preview_root / f"{file_path.stem}.html"
    preview_pdf = preview_root / f"{file_path.stem}.pdf"
    source_layout_pdf = preview_root / f"{file_path.stem}.source-layout.pdf"
    office_bin = shutil.which("libreoffice") or shutil.which("soffice")

    def build_preview_payload(
        *,
        preview_file: Path | None = None,
        preview_type: str = "",
        preview_origin: str = "",
        location_mode: str = "none",
        location_note: str = "",
        source_layout_file: Path | None = None,
    ) -> dict[str, object]:
        return {
            "preview_file": to_browser_relative(input_dir, preview_file) if preview_file else "",
            "preview_type": preview_type,
            "preview_origin": preview_origin,
            "location_mode": location_mode,
            "location_note": location_note,
            "source_layout_file": to_browser_relative(input_dir, source_layout_file) if source_layout_file else "",
        }

    def _run_soffice_convert(target_pdf: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="accept_doc_preview_") as temp_dir:
            temp_root = Path(temp_dir)
            temp_src = temp_root / file_path.name
            temp_src.write_bytes(file_path.read_bytes())
            soffice_profile = temp_root / "soffice-profile"
            soffice_profile.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["HOME"] = str(temp_root)
            env["XDG_RUNTIME_DIR"] = str(temp_root)
            env["SAL_USE_VCLPLUGIN"] = "svp"
            user_installation = soffice_profile.resolve().as_uri()
            cmd = [
                office_bin,
                f"-env:UserInstallation={user_installation}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(preview_root),
                str(temp_src),
            ]
            subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            generated_default_pdf = preview_root / f"{temp_src.stem}.pdf"
            if generated_default_pdf.exists() and generated_default_pdf != target_pdf:
                shutil.copyfile(generated_default_pdf, target_pdf)

    needs_regen_source_pdf = (
        not source_layout_pdf.exists()
        or source_layout_pdf.stat().st_mtime < file_path.stat().st_mtime
        or not is_usable_preview_pdf(source_layout_pdf)
    )
    if needs_regen_source_pdf and office_bin:
        try:
            _run_soffice_convert(source_layout_pdf)
        except Exception:
            pass
    if is_usable_preview_pdf(source_layout_pdf, strict=True):
        return build_preview_payload(
            preview_file=source_layout_pdf,
            preview_type="pdf",
            preview_origin="soffice_source_pdf",
            location_mode="page_only",
            location_note="当前 Word 仅使用 LibreOffice 导出的原版式 PDF 预览，尚未建立文本块到页内坐标的重解析映射，因此只支持页级跳转，不支持精确框选定位。",
            source_layout_file=source_layout_pdf,
        )

    if is_usable_preview_html(preview_html):
        return build_preview_payload(
            preview_file=preview_html,
            preview_type="html",
            preview_origin="mammoth_html",
            location_mode="anchor_only",
            location_note="当前 Word 预览来自 Mammoth HTML 重排版，不是原件保真页面，只能做文本浏览/锚点跳转，不能作为页内证据定位底稿。",
        )

    needs_regen_html = (
        not preview_html.exists()
        or preview_html.stat().st_mtime < file_path.stat().st_mtime
        or not is_usable_preview_html(preview_html)
    )
    if needs_regen_html:
        try:
            with file_path.open("rb") as source:
                converted = mammoth.convert_to_html(source)
            html_body = converted.value or ""
            preview_html.write_text(
                f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      background: #f7fafc;
      color: #1f2937;
      line-height: 1.75;
    }}
    .docx-page {{
      max-width: 980px;
      margin: 0 auto;
      background: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 16px;
      padding: 28px 32px;
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
    }}
    h1,h2,h3 {{ margin: 1.2em 0 0.6em; line-height: 1.25; }}
    p {{ margin: 0 0 0.8em; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
    td, th {{ border: 1px solid #cbd5e1; padding: 6px 8px; vertical-align: top; }}
    img {{ max-width: 100%; height: auto; }}
  </style>
</head>
<body>
  <div class="docx-page">
    {html_body}
  </div>
</body>
</html>""",
                encoding="utf-8",
            )
            return build_preview_payload(
                preview_file=preview_html,
                preview_type="html",
                preview_origin="mammoth_html",
                location_mode="anchor_only",
                location_note="当前 Word 预览来自 Mammoth HTML 重排版，不是原件保真页面，只能做文本浏览/锚点跳转，不能作为页内证据定位底稿。",
            )
        except Exception:
            pass

    if is_usable_preview_html(preview_html):
        return build_preview_payload(
            preview_file=preview_html,
            preview_type="html",
            preview_origin="mammoth_html",
            location_mode="anchor_only",
            location_note="当前 Word 预览来自 Mammoth HTML 重排版，不是原件保真页面，只能做文本浏览/锚点跳转，不能作为页内证据定位底稿。",
        )

    needs_regen_pdf = (
        not preview_pdf.exists()
        or preview_pdf.stat().st_mtime < file_path.stat().st_mtime
        or not is_usable_preview_pdf(preview_pdf)
    )
    if needs_regen_pdf and office_bin:
        try:
            _run_soffice_convert(preview_pdf)
        except Exception:
            pass
        if not is_usable_preview_pdf(preview_pdf) and docx_to_pdf is not None:
            try:
                docx_to_pdf(file_path, preview_pdf)
            except Exception:
                pass
    if not is_usable_preview_pdf(preview_pdf, strict=False):
        generated = sorted(preview_root.glob("*.pdf"))
        if generated:
            preview_pdf = next((path for path in generated if is_usable_preview_pdf(path, strict=False)), generated[0])
    if is_usable_preview_pdf(preview_pdf, strict=False):
        preview_origin = "fallback_pdf"
        if source_layout_pdf.exists() and preview_pdf.resolve() == source_layout_pdf.resolve():
            preview_origin = "soffice_source_pdf"
        elif docx_to_pdf is not None and preview_pdf.name == f"{file_path.stem}.pdf":
            preview_origin = "htmlbox_fallback_pdf"
        location_mode = "page_only" if preview_origin == "soffice_source_pdf" else "none"
        location_note = (
            "当前 Word 仅使用 LibreOffice 导出的原版式 PDF 预览，尚未建立文本块到页内坐标的重解析映射，因此只支持页级跳转，不支持精确框选定位。"
            if preview_origin == "soffice_source_pdf"
            else "当前 PDF 不是从 Word 原件保真导出的定位底稿，可能来自 fallback 重排，仅可用于浏览，不能用于证据定位。"
        )
        return build_preview_payload(
            preview_file=preview_pdf,
            preview_type="pdf",
            preview_origin=preview_origin,
            location_mode=location_mode,
            location_note=location_note,
            source_layout_file=source_layout_pdf if preview_origin == "soffice_source_pdf" else None,
        )
    return {}


def build_document_payload(
    *,
    input_dir: Path,
    document: ParsedAcceptanceDocument,
    file_path: Path,
    viewer_assets: dict[str, object],
    preview_assets: dict[str, object],
    role: str,
    display_title: str,
    subdocs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    from src.services.accept.viewer_target import build_page_sizes_map

    blocks = {
        block.block_id: block
        for block in document.blocks
    }
    page_sizes = build_page_sizes_map(file_path if file_path.exists() else None)
    return {
        "role": role,
        "file_name": document.file_name,
        "display_title": display_title,
        "file_path": str(file_path),
        "browser_file": to_browser_relative(input_dir, file_path),
        "file_type": document.file_type,
        "page_count": int(document.metadata.get("pages") or 0),
        "page_sizes": page_sizes,
        "viewer_file": viewer_assets.get("viewer_file", ""),
        "packet_file": viewer_assets.get("packet_file", ""),
        "preview_file": preview_assets.get("preview_file", ""),
        "preview_type": preview_assets.get("preview_type", ""),
        "preview_origin": preview_assets.get("preview_origin", ""),
        "location_mode": preview_assets.get("location_mode", "none"),
        "location_note": preview_assets.get("location_note", ""),
        "source_layout_file": preview_assets.get("source_layout_file", ""),
        "subdocs": subdocs if subdocs is not None else viewer_assets.get("subdocs", []),
        "blocks": blocks,
    }


async def enrich_project_payload_async(
    *,
    artifacts,
    service: AcceptanceService,
) -> dict[str, object]:
    return await refresh_acceptance_project_payload(
        artifacts=artifacts,
        service=service,
        include_viewer_assets=True,
        include_target_enrichment=True,
    )


def choose_primary_docs_from_attachments(
    *,
    extractor: AttachmentEvidenceExtractor,
    parsed_documents: list[tuple[Path, ParsedAcceptanceDocument]],
) -> tuple[tuple[Path, ParsedAcceptanceDocument] | None, tuple[Path, ParsedAcceptanceDocument] | None]:
    preferred_taskbook: tuple[Path, ParsedAcceptanceDocument] | None = None
    preferred_yssq: tuple[Path, ParsedAcceptanceDocument] | None = None
    for source_path, parsed_document in parsed_documents:
        if source_path.suffix.lower() != ".pdf":
            continue
        doc_kind = extractor._classify_doc_kind(parsed_document)
        if doc_kind == "任务书" and preferred_taskbook is None:
            preferred_taskbook = (source_path, parsed_document)
        elif doc_kind == "验收申请" and preferred_yssq is None:
            preferred_yssq = (source_path, parsed_document)
    return preferred_taskbook, preferred_yssq


def build_attachment_subdocs(
    *,
    file_name: str,
    file_path: Path,
    parsed_document: ParsedAcceptanceDocument,
    evidence_items: list[object],
    service: AcceptanceService,
) -> list[dict[str, object]]:
    candidates = service.evidence_extractor.build_subdoc_candidates(
        parsed_document,
        list(evidence_items),  # type: ignore[arg-type]
    )
    subdocs: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    block_map = {block.block_id: block for block in parsed_document.blocks}
    for candidate in candidates:
        metric_name = str(candidate.get("metric_name") or "")
        if metric_name and metric_name not in {"科技论文", "发明专利", "实用新型专利", "软件著作权", "培养研究生"}:
            continue
        artifact_key = (
            str(candidate.get("artifact_key") or "").strip()
            or str(candidate.get("title") or "").strip()
            or f"{file_name}:{candidate.get('source_block_id', '')}:{candidate.get('source_page', 0)}"
        )
        if artifact_key in seen_keys:
            continue
        seen_keys.add(artifact_key)
        block_id = str(candidate.get("source_block_id") or "")
        block = block_map.get(block_id)
        title = str(candidate.get("title") or metric_name or file_name).strip()
        source_page = int(candidate.get("source_page") or 0)
        viewer_rects = []
        if block is not None:
            viewer_rects = preferred_block_rect(
                file_path,
                source_page,
                block,
                title,
            )
        subdocs.append(
            {
                "title": title,
                "metric_name": metric_name,
                "metric_variant": str(candidate.get("metric_variant") or ""),
                "artifact_key": artifact_key,
                "source_page": source_page,
                "source_block_id": block_id,
                "viewer_page": int(candidate.get("viewer_page") or source_page + 1),
                "viewer_rects": viewer_rects,
                "doc_kind": str(candidate.get("doc_kind") or ""),
            }
        )
    return subdocs


def build_attachment_subdocs_from_rows(
    *,
    file_name: str,
    row_payloads: list[dict[str, object]],
) -> list[dict[str, object]]:
    subdocs: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for row in row_payloads:
        for detail in row.get("match_details", []) or []:
            if not isinstance(detail, dict):
                continue
            if detail.get("file_name") != file_name:
                continue
            doc_kind = str(detail.get("doc_kind") or "")
            artifact_key = (
                str(detail.get("artifact_key") or "").strip()
                or f"{file_name}:{detail.get('source_block_id', '')}:{detail.get('source_page', 0)}:{detail.get('display_title') or detail.get('title') or doc_kind}"
            )
            if artifact_key in seen_keys:
                continue
            seen_keys.add(artifact_key)
            title = str(detail.get("display_title") or detail.get("title") or detail.get("excerpt") or doc_kind or file_name).strip()
            subdocs.append(
                {
                    "title": title,
                    "metric_name": str(detail.get("metric_name") or ""),
                    "metric_variant": str(detail.get("metric_variant") or ""),
                    "artifact_key": artifact_key,
                    "source_page": int(detail.get("source_page") or 0),
                    "source_block_id": str(detail.get("source_block_id") or ""),
                    "viewer_page": int(detail.get("viewer_page") or 0),
                    "viewer_rects": detail.get("viewer_rects") or [],
                    "doc_kind": doc_kind,
                }
            )
    return subdocs


async def run_batch(
    input_dir: Path,
    year: str,
    *,
    project_nos: set[str] | None = None,
    single_project: dict[str, str] | None = None,
    disable_candidate_filter: bool = False,
    skip_viewer: bool = False,
) -> dict[str, object]:
    service = AcceptanceService(cache_dir=input_dir / ".accept_parse_cache" / year)
    packet_builder = EvaluationPacketBuilder()
    results_path = input_dir / "acceptance_results.json"
    html_path = input_dir / "index.html"
    field_extract_path = input_dir / "project_field_extract.tsv"
    mapping_summary_path = input_dir / "yssq_yssqfj_mapping_summary.tsv"
    partial_run = bool(single_project or project_nos)
    if single_project:
        pairings = [single_project]
    else:
        pairings = read_pairings(input_dir / "project_pairing.tsv")
        if project_nos:
            pairings = [pair for pair in pairings if pair["project_no"] in project_nos]
    total_projects = len(pairings)

    sample_root = input_dir / "sample_batch" / "files" / year
    hts_root = sample_root / "hts"
    yssq_root = sample_root / "yssq"
    yssqfj_root = sample_root / "yssqfj"
    existing_results = load_existing_results(results_path)
    results: list[dict[str, object]] = []
    field_rows: list[list[object]] = []
    mapping_rows: list[list[object]] = []
    processed_projects = 0
    viewer_tasks: list[tuple[int, asyncio.Task[dict[str, object]]]] = []

    for index, pair in enumerate(pairings, start=1):
        project_started_at = perf_counter()
        project_no = pair["project_no"]
        project_name = pair.get("project_name") or ""
        hts_path = Path(pair.get("taskbook_path") or (hts_root / pair["hts_file"]))
        yssq_path = Path(pair.get("acceptance_application_path") or (yssq_root / pair["yssq_file"]))
        attachment_dir = Path(pair.get("acceptance_attachment_dir") or (yssqfj_root / pair["yssqfj_dir"]))
        print(
            f"[accept-batch] project {index}/{total_projects} start "
            f"project_no={project_no} project_name={project_name}"
        )

        artifacts = await run_acceptance_project_pipeline(
            input_dir=input_dir,
            year=year,
            project_no=project_no,
            taskbook_path=hts_path,
            yssq_path=yssq_path,
            attachment_dir=attachment_dir,
            project_name=project_name,
            service=service,
            include_viewer_assets=False,
            include_target_enrichment=False,
            disable_candidate_filter=disable_candidate_filter,
        )
        result = artifacts.result
        project_payload = dict(artifacts.project_payload)
        parsed_attachments = artifacts.parsed_attachments
        parse_elapsed = perf_counter() - project_started_at
        print(
            f"[accept-batch] project {index}/{total_projects} parsed "
            f"project_no={project_no} attachments={len(parsed_attachments)} "
            f"elapsed={parse_elapsed:.1f}s"
        )
        results.append(project_payload)
        current_results = merge_project_results(existing_results, results)
        sanitized_current_results = sanitize_json_compatible(current_results)
        backup_results_file(results_path)
        write_acceptance_results_files(input_dir, sanitized_current_results)

        for item in result.extracted_commitments:
            field_rows.append(
                [
                    year,
                    project_no,
                    project_name,
                    "hts",
                    artifacts.taskbook_path_for_use.name,
                    item.metric_category,
                    item.metric_name,
                    item.target_value,
                    item.target_unit,
                    item.comparator,
                    item.source_line,
                ]
            )

        for document in parsed_attachments:
            if service.evidence_extractor.should_skip_attachment(document):
                continue
            evidence_items = service.evidence_normalizer.normalize(service.extract_evidence(document))
            mapping_rows.append(
                [
                    year,
                    project_no,
                    project_name,
                    artifacts.yssq_path_for_use.name,
                    attachment_dir.name,
                    document.file_name,
                    document.file_type,
                    len(document.lines),
                    len(evidence_items),
                ]
            )
            for item in evidence_items:
                field_rows.append(
                    [
                        year,
                        project_no,
                        project_name,
                        "yssqfj" if document.file_name != yssq_path.name else "yssq",
                        document.file_name,
                        item.metric_category,
                        item.metric_name,
                        item.value if item.value is not None else item.implicit_count,
                        item.unit,
                        "",
                        item.excerpt,
                    ]
                )
        processed_projects += 1
        project_elapsed = perf_counter() - project_started_at
        print(
            f"[accept-batch] project {index}/{total_projects} done "
            f"project_no={project_no} commitments={result.fulfilled_commitments}/{result.total_commitments} "
            f"(partial={result.partial_commitments} missing={result.missing_commitments}) "
            f"elapsed={project_elapsed:.1f}s"
        )

        if not skip_viewer:
            viewer_tasks.append(
                (
                    len(results) - 1,
                    asyncio.create_task(enrich_project_payload_async(artifacts=artifacts, service=service)),
                )
            )

    if viewer_tasks:
        for result_index, task in viewer_tasks:
            try:
                results[result_index] = dict(await task)
            except Exception:
                continue

    results = merge_project_results(existing_results, results)

    sanitized_results = sanitize_json_compatible(results)
    backup_results_file(results_path)
    write_acceptance_results_files(input_dir, sanitized_results)
    write_tsv(
        field_extract_path,
        [
            "year",
            "project_no",
            "project_name",
            "source_kind",
            "source_file",
            "metric_category",
            "metric_name",
            "value",
            "unit",
            "comparator",
            "source_excerpt",
        ],
        field_rows,
    )
    write_tsv(
        mapping_summary_path,
        [
            "year",
            "project_no",
            "project_name",
            "yssq_file",
            "yssqfj_dir",
            "attachment_file",
            "attachment_type",
            "text_line_count",
            "evidence_item_count",
        ],
        mapping_rows,
    )
    write_acceptance_html_shell(html_path)

    total_commitments = sum(int(item.get("total_commitments") or 0) for item in results)
    fulfilled_commitments = sum(int(item.get("fulfilled_commitments") or 0) for item in results)
    partial_commitments = sum(int(item.get("partial_commitments") or 0) for item in results)
    missing_commitments = sum(int(item.get("missing_commitments") or 0) for item in results)
    warning_projects = sum(1 for item in results if item.get("warnings"))
    return {
        "year": year,
        "project_count": processed_projects,
        "warning_projects": warning_projects,
        "total_commitments": total_commitments,
        "fulfilled_commitments": fulfilled_commitments,
        "partial_commitments": partial_commitments,
        "missing_commitments": missing_commitments,
        "results_path": str(results_path),
        "html_path": str(html_path),
        "field_extract_path": str(field_extract_path),
        "mapping_summary_path": str(mapping_summary_path),
    }


def write_tsv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow([sanitize_text_value(item) for item in headers])
        writer.writerows(
            [
                [sanitize_text_value(item) if isinstance(item, str) else item for item in row]
                for row in rows
            ]
        )


def main() -> int:
    args = parse_args()
    started_at = perf_counter()
    input_dir = Path(args.input_dir)
    single_project = None
    if args.taskbook_path and args.acceptance_application_path and args.acceptance_attachment_dir:
        single_project = {
            "project_no": args.project_no[0] if args.project_no else "single-project",
            "project_name": args.project_name or "单项目验收",
            "taskbook_path": args.taskbook_path,
            "acceptance_application_path": args.acceptance_application_path,
            "acceptance_attachment_dir": args.acceptance_attachment_dir,
            "hts_file": Path(args.taskbook_path).name,
            "yssq_file": Path(args.acceptance_application_path).name,
            "yssqfj_dir": Path(args.acceptance_attachment_dir).name,
        }
    try:
        summary = asyncio.run(
            run_batch(
                input_dir,
                args.year,
                project_nos=set(args.project_no) or None,
                single_project=single_project,
                disable_candidate_filter=args.disable_candidate_filter,
                skip_viewer=args.skip_viewer,
            )
        )
    except Exception as exc:
        elapsed = perf_counter() - started_at
        print(
            f"[accept-batch] failed year={args.year} input_dir={input_dir} "
            f"elapsed={elapsed:.1f}s error={exc.__class__.__name__}: {exc}",
            file=sys.stderr,
        )
        raise

    elapsed = perf_counter() - started_at
    print(
        f"[accept-batch] completed year={summary['year']} "
        f"projects={summary['project_count']} warnings={summary['warning_projects']} "
        f"commitments={summary['fulfilled_commitments']}/{summary['total_commitments']} "
        f"(partial={summary['partial_commitments']} missing={summary['missing_commitments']}) "
        f"elapsed={elapsed:.1f}s"
    )
    print(f"[accept-batch] acceptance_results={summary['results_path']}")
    print(f"[accept-batch] html={summary['html_path']}")
    print(f"[accept-batch] field_extract={summary['field_extract_path']}")
    print(f"[accept-batch] mapping_summary={summary['mapping_summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
