#!/usr/bin/env python3
"""批量修正 debug_accept packet_viewer 的高亮层与滚动定位。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWERS_ROOT = ROOT / "debug_accept" / "viewers" / "projects"

GET_PAGE_CANVAS = """    function getPageCanvas(pageNumber) {
      const target = document.getElementById(`packet-page-${pageNumber}`);
      if (!target) return null;
      let canvas = target.querySelector(".packet-page-canvas");
      if (!canvas) {
        const img = target.querySelector("img");
        if (!img) return target;
        canvas = document.createElement("div");
        canvas.className = "packet-page-canvas";
        img.parentNode.insertBefore(canvas, img);
        canvas.appendChild(img);
      }
      return canvas;
    }
"""

NEW_CENTER = """    function centerOnRect(page, rects, smooth) {
      const pageNumber = Number(page || 0);
      const canvas = getPageCanvas(pageNumber);
      if (!canvas || !Array.isArray(rects) || !rects.length) return;
      const validRects = rects.filter((item) => item && Number(item.w || 0) > 0 && Number(item.h || 0) > 0);
      if (!validRects.length) return;
      const first = validRects[0];
      const canvasBox = canvas.getBoundingClientRect();
      const rectCenterY = canvasBox.top + canvasBox.height * (Number(first.y || 0) + Number(first.h || 0) / 2);
      const desiredTop = window.scrollY + rectCenterY - Math.max(220, window.innerHeight * 0.42);
      window.scrollTo({
        top: Math.max(0, desiredTop),
        behavior: smooth ? "smooth" : "auto",
      });
    }"""

NEW_APPLY = """    function applyHighlights(page, rects) {
      clearHighlights();
      const pageNumber = Number(page || 0);
      const canvas = getPageCanvas(pageNumber);
      if (!canvas || !Array.isArray(rects) || !rects.length) return;
      const merged = rects
        .filter((item) => item && Number(item.w || 0) > 0 && Number(item.h || 0) > 0)
        .sort((a, b) => Number(a.y || 0) - Number(b.y || 0) || Number(a.x || 0) - Number(b.x || 0));
      const layer = document.createElement("div");
      layer.className = "highlight-layer";
      merged.forEach((item) => {
        const x = Number(item.x || 0);
        const y = Number(item.y || 0);
        const w = Number(item.w || 0);
        const h = Number(item.h || 0);
        if (!(w > 0) || !(h > 0)) return;
        const rect = document.createElement("div");
        rect.className = "highlight-rect";
        rect.style.left = `${x * 100}%`;
        rect.style.top = `${y * 100}%`;
        rect.style.width = `${w * 100}%`;
        rect.style.height = `${h * 100}%`;
        layer.appendChild(rect);
      });
      if (layer.childElementCount) canvas.appendChild(layer);
    }"""

CENTER_MARKERS = (
    'function centerOnRect(page, rects, smooth) {',
    "function centerOnRect(page, rects, smooth) {",
)

APPLY_MARKERS = (
    'function applyHighlights(page, rects) {',
    "function applyHighlights(page, rects) {",
)


def _replace_function(text: str, marker: str, replacement: str) -> str:
    start = text.find(marker)
    if start < 0:
        return text
    brace_start = text.find("{", start)
    if brace_start < 0:
        return text
    depth = 0
    end = brace_start
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    return text[:start] + replacement + text[end:]


def patch_viewer_text(text: str) -> str:
    original = text
    if "function getPageCanvas(pageNumber)" not in text:
        anchor = 'function centerOnRect(page, rects, smooth) {'
        if anchor not in text:
            anchor = "function centerOnRect(page, rects, smooth) {"
        if anchor in text:
            text = text.replace(anchor, GET_PAGE_CANVAS + "\n" + anchor, 1)

    for marker in CENTER_MARKERS:
        if marker in text:
            text = _replace_function(text, marker, NEW_CENTER)
            break

    for marker in APPLY_MARKERS:
        if marker in text:
            text = _replace_function(text, marker, NEW_APPLY)
            break

    text = text.replace("inset: 33px 0 0 0;", "inset: 0;")
    if ".packet-page-canvas {" not in text and ".packet-page img {" in text:
        text = text.replace(
            ".packet-page img {",
            ".packet-page-canvas {\n      position: relative;\n      width: 100%;\n    }\n    .packet-page-canvas img {",
            1,
        )
    return text if text != original else original


def main() -> int:
    if not VIEWERS_ROOT.exists():
        print(f"[patch-viewers] skip: {VIEWERS_ROOT} not found")
        return 0
    updated = 0
    for path in VIEWERS_ROOT.rglob("packet_viewer.html"):
        original = path.read_text(encoding="utf-8")
        patched = patch_viewer_text(original)
        if patched != original:
            path.write_text(patched, encoding="utf-8")
            updated += 1
    print(f"[patch-viewers] updated {updated} packet_viewer.html files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
