"""
正文评审统一材料包构建器

负责把正文与附件合并为单个 PDF，并生成可跳转的 viewer 资产。
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from html import escape
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree as ET

import fitz
from PIL import Image


class EvaluationPacketBuilder:
    """统一材料包构建器"""

    def build(
        self,
        output_dir: Path,
        project_id: str,
        source_file: str,
        source_name: str,
        attachments: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """生成统一 packet 资产"""
        packet_root = output_dir / "projects" / project_id
        packet_root.mkdir(parents=True, exist_ok=True)

        ordered_sources = self._collect_sources(source_file, source_name, attachments or [])
        if not ordered_sources:
            return {}

        packet_doc = fitz.open()
        page_map: List[Dict[str, Any]] = []
        source_items: List[Dict[str, Any]] = []

        for order, item in enumerate(ordered_sources, start=1):
            path = Path(str(item.get("source_file") or "").strip())
            if not path.exists() or not path.is_file():
                continue
            merged_doc, merge_mode = self._open_mergeable_document(path)
            if merged_doc is None or merged_doc.page_count <= 0:
                continue

            start_page = packet_doc.page_count + 1
            packet_doc.insert_pdf(merged_doc)
            end_page = packet_doc.page_count
            page_count = max(0, end_page - start_page + 1)
            page_map.append(
                {
                    "source_file": str(path),
                    "source_name": str(item.get("source_name") or path.name),
                    "source_kind": str(item.get("source_kind") or "attachment"),
                    "doc_kind": str(item.get("doc_kind") or ""),
                    "start_page": start_page,
                    "end_page": end_page,
                    "page_count": page_count,
                    "merge_mode": merge_mode,
                }
            )
            source_items.append(
                {
                    "order": order,
                    "source_file": str(path),
                    "source_name": str(item.get("source_name") or path.name),
                    "source_kind": str(item.get("source_kind") or "attachment"),
                    "doc_kind": str(item.get("doc_kind") or ""),
                    "merge_mode": merge_mode,
                }
            )
            merged_doc.close()

        if packet_doc.page_count <= 0:
            packet_doc.close()
            return {}

        packet_bytes = packet_doc.tobytes(garbage=3, deflate=True)
        packet_doc.close()

        packet_file = packet_root / "evaluation_packet.pdf"
        page_map_file = packet_root / "evaluation_packet.page_map.json"
        packet_file.write_bytes(packet_bytes)
        page_map_file.write_text(json.dumps(page_map, ensure_ascii=False, indent=2), encoding="utf-8")

        viewer_assets = self._write_packet_viewer_assets(packet_root, packet_bytes, project_id)
        return {
            "packet_file": str(packet_file.relative_to(output_dir)),
            "packet_abs_path": str(packet_file.resolve()),
            "page_map_file": str(page_map_file.relative_to(output_dir)),
            "page_map": page_map,
            "source_items": source_items,
            "default_page": 1,
            "viewer_file": viewer_assets.get("viewer_file", ""),
            "page_images": viewer_assets.get("page_images", []),
        }

    def _collect_sources(
        self,
        source_file: str,
        source_name: str,
        attachments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """按顺序收集正文与附件"""
        sources: List[Dict[str, Any]] = []
        if source_file:
            path = Path(source_file)
            sources.append(
                {
                    "source_file": source_file,
                    "source_name": source_name or path.name,
                    "source_kind": "proposal",
                    "doc_kind": "",
                }
            )

        for item in attachments:
            if not isinstance(item, dict):
                continue
            file_ref = str(item.get("file_ref") or "").strip()
            if not file_ref:
                continue
            path = Path(file_ref)
            sources.append(
                {
                    "source_file": file_ref,
                    "source_name": str(item.get("file_name") or path.name),
                    "source_kind": "attachment",
                    "doc_kind": str(item.get("doc_kind") or ""),
                }
            )
        return sources

    def _write_packet_viewer_assets(
        self,
        packet_root: Path,
        packet_bytes: bytes,
        project_id: str,
    ) -> Dict[str, Any]:
        """生成 packet viewer HTML 与页面图像"""
        packet_doc = fitz.open(stream=packet_bytes, filetype="pdf")
        page_images: List[Dict[str, Any]] = []
        image_dir = packet_root / "packet_pages"
        image_dir.mkdir(parents=True, exist_ok=True)
        try:
            for page_index in range(packet_doc.page_count):
                page = packet_doc.load_page(page_index)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                image_path = image_dir / f"page-{page_index + 1:04d}.png"
                image_path.write_bytes(pix.tobytes("png"))
                page_images.append(
                    {
                        "page": page_index + 1,
                        "image_file": str(image_path),
                        "width": pix.width,
                        "height": pix.height,
                    }
                )
        finally:
            packet_doc.close()

        viewer_file = packet_root / "packet_viewer.html"
        viewer_file.write_text(
            self._build_packet_viewer_html(
                title=f"{project_id} 评审材料",
                page_images=page_images,
            ),
            encoding="utf-8",
        )
        return {
            "viewer_file": str(viewer_file.relative_to(packet_root.parent.parent)),
            "page_images": page_images,
        }

    def _build_packet_viewer_html(self, title: str, page_images: List[Dict[str, Any]]) -> str:
        """构造 packet viewer HTML"""
        pages_html: List[str] = []
        for item in page_images:
            page = int(item.get("page", 0) or 0)
            image_file = str(item.get("image_file") or "").strip()
            if not page or not image_file:
                continue
            image_src = f"packet_pages/{Path(image_file).name}"
            pages_html.append(
                "<section class='packet-page' "
                f"id='packet-page-{page}' data-page='{page}'>"
                f"<div class='page-index'>第 {page} 页</div>"
                f"<img loading='lazy' src='{escape(image_src)}' alt='packet page {page}'>"
                "</section>"
            )
        pages_content = "".join(pages_html) or "<div class='empty'>当前材料暂无可预览页面。</div>"
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #dfe5ec;
      --panel: #f3f6fa;
      --page-bg: #ffffff;
      --line: #c8d2de;
      --text: #182230;
      --muted: #5f6b7a;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    body {{ overflow-y: auto; }}
    .viewer-root {{ min-height: 100%; padding: 18px 0 28px; }}
    .viewer-head {{ display: flex; justify-content: center; padding: 0 12px 12px; }}
    .head-stack {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      max-width: min(900px, calc(100vw - 48px));
    }}
    .page-pill {{
      min-width: 110px;
      text-align: center;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(15, 118, 110, 0.18);
      background: rgba(255, 255, 255, 0.92);
      color: #115e59;
      font-size: 12px;
      font-weight: 700;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }}
    .focus-card {{
      display: none;
      width: min(900px, calc(100vw - 48px));
      padding: 10px 14px;
      border-radius: 16px;
      border: 1px solid rgba(15, 118, 110, 0.2);
      background: rgba(255, 255, 255, 0.94);
      color: var(--text);
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
    }}
    .focus-card.show {{ display: block; }}
    .focus-label {{
      font-size: 12px;
      font-weight: 800;
      color: #0f766e;
      margin-bottom: 4px;
    }}
    .focus-text {{
      font-size: 12px;
      line-height: 1.55;
      color: var(--muted);
      word-break: break-word;
    }}
    .pages {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 18px;
      padding: 0 10px;
    }}
    .packet-page {{
      position: relative;
      width: min(1380px, calc(100vw - 24px));
      background: var(--page-bg);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12);
    }}
    .packet-page.active {{
      border-color: rgba(15, 118, 110, 0.36);
      box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12), 0 18px 48px rgba(15, 23, 42, 0.12);
    }}
    .page-index {{
      padding: 9px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .packet-page img {{
      width: 100%;
      height: auto;
      display: block;
      background: #fff;
    }}
    .highlight-layer {{
      position: absolute;
      inset: 33px 0 0 0;
      pointer-events: none;
    }}
    .highlight-rect {{
      position: absolute;
      border-radius: 10px;
      background: rgba(251, 191, 36, 0.22);
      border: 3px solid rgba(245, 158, 11, 0.92);
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.75), 0 10px 24px rgba(245, 158, 11, 0.22);
    }}
    .empty {{
      padding: 32px;
      color: var(--muted);
      text-align: center;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="viewer-root">
    <div class="viewer-head">
      <div class="head-stack">
        <div class="page-pill" id="pagePill">第 1 页</div>
        <div class="focus-card" id="focusCard">
          <div class="focus-label" id="focusLabel">命中定位</div>
          <div class="focus-text" id="focusText"></div>
        </div>
      </div>
    </div>
    <div class="pages" id="pages">{pages_content}</div>
  </div>
  <script>
    const pagePill = document.getElementById("pagePill");
    const focusCard = document.getElementById("focusCard");
    const focusLabel = document.getElementById("focusLabel");
    const focusText = document.getElementById("focusText");
    let activePage = 1;

    function setActivePage(page) {{
      const pageNumber = Number(page || 1);
      activePage = pageNumber;
      document.querySelectorAll(".packet-page.active").forEach((node) => node.classList.remove("active"));
      const target = document.getElementById(`packet-page-${{pageNumber}}`);
      if (target) target.classList.add("active");
      if (pagePill) pagePill.textContent = `第 ${{pageNumber}} 页`;
    }}

    function gotoPage(page, smooth) {{
      const pageNumber = Number(page || 1);
      const target = document.getElementById(`packet-page-${{pageNumber}}`);
      if (!target) return;
      setActivePage(pageNumber);
      target.scrollIntoView({{ behavior: smooth ? "smooth" : "auto", block: "start" }});
    }}

    function clearHighlights() {{
      document.querySelectorAll(".highlight-layer").forEach((node) => node.remove());
    }}

    function applyHighlights(page, rects) {{
      clearHighlights();
      const pageNumber = Number(page || 0);
      const target = document.getElementById(`packet-page-${{pageNumber}}`);
      if (!target || !Array.isArray(rects) || !rects.length) return;
      const layer = document.createElement("div");
      layer.className = "highlight-layer";
      rects.forEach((item) => {{
        if (!item) return;
        const x = Number(item.x || 0);
        const y = Number(item.y || 0);
        const w = Number(item.w || 0);
        const h = Number(item.h || 0);
        if (!(w > 0) || !(h > 0)) return;
        const rect = document.createElement("div");
        rect.className = "highlight-rect";
        rect.style.left = `${{x * 100}}%`;
        rect.style.top = `${{y * 100}}%`;
        rect.style.width = `${{w * 100}}%`;
        rect.style.height = `${{h * 100}}%`;
        layer.appendChild(rect);
      }});
      if (layer.childElementCount) target.appendChild(layer);
    }}

    function updateFocusCard(payload) {{
      const label = String(payload.location_label || payload.label || "命中定位");
      const text = String(payload.highlight_text || payload.text || "").trim();
      if (!text) {{
        focusCard?.classList.remove("show");
        if (focusText) focusText.textContent = "";
        return;
      }}
      if (focusLabel) focusLabel.textContent = label;
      if (focusText) focusText.textContent = text;
      focusCard?.classList.add("show");
    }}

    window.addEventListener("message", (event) => {{
      const payload = event.data || {{}};
      if (payload.type !== "gotoPacketTarget") return;
      gotoPage(payload.page, true);
      applyHighlights(payload.page, payload.highlight_rects || []);
      updateFocusCard(payload);
    }});

    const observer = new IntersectionObserver((entries) => {{
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      const page = Number(visible.target.dataset.page || activePage || 1);
      setActivePage(page);
    }}, {{
      root: null,
      threshold: [0.35, 0.6, 0.85],
    }});

    document.querySelectorAll(".packet-page").forEach((node) => observer.observe(node));
    gotoPage(1, false);
  </script>
</body>
</html>"""

    def _open_mergeable_document(self, path: Path) -> tuple[fitz.Document | None, str]:
        """把不同材料转换为可合并 PDF 文档"""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return fitz.open(path), "pdf"
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}:
            return self._image_to_pdf_document(path), "image_to_pdf"
        if suffix == ".docx":
            return self._docx_to_fallback_pdf_document(path), "docx_fallback"
        return None, "unsupported"

    def _image_to_pdf_document(self, path: Path) -> fitz.Document:
        """图片转单页 PDF"""
        with Image.open(path) as image:
            rgb_image = image.convert("RGB")
            buffer = io.BytesIO()
            rgb_image.save(buffer, format="PDF", resolution=150.0)
        return fitz.open(stream=buffer.getvalue(), filetype="pdf")

    def _docx_to_fallback_pdf_document(self, path: Path) -> fitz.Document:
        """docx 降级转换为文本 PDF"""
        paragraphs = self._extract_docx_preview_paragraphs(path)
        if not paragraphs:
            paragraphs = [path.name]

        doc = fitz.open()
        page_width = 595
        page_height = 842
        margin_x = 44
        margin_y = 48
        font_size = 10
        line_height = 16
        usable_width = page_width - margin_x * 2
        usable_height = page_height - margin_y * 2
        max_lines = max(1, int(usable_height // line_height))
        lines: List[str] = []

        def append_wrapped(text: str) -> None:
            normalized = re.sub(r"\s+", " ", text).strip()
            if not normalized:
                lines.append("")
                return
            start = 0
            while start < len(normalized):
                lines.append(normalized[start:start + 42])
                start += 42

        for paragraph in paragraphs:
            append_wrapped(paragraph)
            lines.append("")

        cursor = 0
        while cursor < len(lines):
            page = doc.new_page(width=page_width, height=page_height)
            text_page = page.new_text_page()
            batch = lines[cursor:cursor + max_lines]
            for index, line in enumerate(batch):
                page.insert_text(
                    fitz.Point(margin_x, margin_y + line_height * (index + 1)),
                    line,
                    fontsize=font_size,
                    fontname="helv",
                )
            cursor += max_lines
        return doc

    def _extract_docx_preview_paragraphs(self, path: Path) -> List[str]:
        """轻量提取 docx 文本段落"""
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: List[str] = []
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        body = root.find("w:body", ns)
        if body is None:
            return paragraphs

        for child in list(body):
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = "".join(node.text or "" for node in child.findall(".//w:t", ns)).strip()
                normalized = re.sub(r"\s+", " ", text)
                if normalized:
                    paragraphs.append(normalized[:600])
            elif tag == "tbl":
                for row in child.findall("w:tr", ns):
                    cells = []
                    for cell in row.findall("w:tc", ns):
                        cell_text = "".join(node.text or "" for node in cell.findall(".//w:t", ns)).strip()
                        normalized = re.sub(r"\s+", " ", cell_text)
                        if normalized:
                            cells.append(normalized[:200])
                    if cells:
                        paragraphs.append(" | ".join(cells))
            if len(paragraphs) >= 500:
                break
        return paragraphs
