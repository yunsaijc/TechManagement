"""Build a lightweight HTML report for image plagiarism results."""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from .schemas import ImageMatch


class ImageReportBuilder:
    def build(
        self,
        title: str,
        matches: List[ImageMatch],
        output_html_path: Path,
        image_bytes_map: Optional[Dict[str, bytes]] = None,
    ) -> Path:
        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes_map = image_bytes_map or {}
        grouped: Dict[str, List[ImageMatch]] = {}
        for item in matches:
            grouped.setdefault(item.query_doc, []).append(item)

        sections: List[str] = []
        for query_doc, items in sorted(grouped.items()):
            rows = []
            for m in sorted(items, key=lambda x: (-x.score, x.source_doc, x.source_image_id)):
                q_img = self._to_data_uri(image_bytes_map.get(m.query_image_id))
                s_img = self._to_data_uri(image_bytes_map.get(m.source_image_id))
                rows.append(
                    "<tr>"
                    f"<td>{self._render_thumb(q_img, m.query_image_id)}</td>"
                    f"<td>{self._render_thumb(s_img, m.source_image_id)}</td>"
                    f"<td>{html.escape(m.source_doc)}</td>"
                    f"<td>{m.level}</td>"
                    f"<td>{m.score:.4f}</td>"
                    f"<td>{m.hash_hamming}</td>"
                    f"<td>{m.inliers}</td>"
                    f"<td>{html.escape(m.reason)}</td>"
                    "</tr>"
                )

            sections.append(
                f"<h2>{html.escape(query_doc)} ({len(items)} matches)</h2>"
                "<table>"
                "<thead><tr>"
                "<th>query_image</th><th>source_image</th><th>source_doc</th><th>level</th>"
                "<th>score</th><th>hamming</th><th>inliers</th><th>reason</th>"
                "</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                "</table>"
            )

        body = (
            "<p class='empty'>No matches.</p>" if not sections else "".join(sections)
        )
        html_text = f"""<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; margin: 20px; color: #111827; }}
    h1 {{ margin: 0 0 16px; }}
    h2 {{ margin: 22px 0 8px; font-size: 16px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 6px 8px; font-size: 12px; text-align: left; }}
    td {{ vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .empty {{ color: #6b7280; }}
    .thumb-wrap {{ display: flex; flex-direction: column; gap: 6px; min-width: 160px; max-width: 220px; }}
    .thumb-wrap img {{ max-width: 210px; max-height: 130px; border: 1px solid #d1d5db; object-fit: contain; background: #fff; }}
    .thumb-id {{ font-size: 11px; color: #374151; word-break: break-all; }}
    .thumb-miss {{ color: #9ca3af; font-style: italic; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p>total matches: {len(matches)}</p>
  {body}
</body>
</html>"""
        output_html_path.write_text(html_text, encoding="utf-8")
        return output_html_path

    def _render_thumb(self, data_uri: Optional[str], image_id: str) -> str:
        safe_id = html.escape(image_id)
        if not data_uri:
            return f"<div class='thumb-wrap'><div class='thumb-miss'>[无图像预览]</div><div class='thumb-id'>{safe_id}</div></div>"
        return (
            "<div class='thumb-wrap'>"
            f"<img src='{data_uri}' alt='{safe_id}' />"
            f"<div class='thumb-id'>{safe_id}</div>"
            "</div>"
        )

    def _to_data_uri(self, image_bytes: Optional[bytes]) -> Optional[str]:
        if not image_bytes:
            return None
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return None
        h, w = image.shape[:2]
        max_side = max(h, w)
        if max_side > 220:
            scale = 220.0 / float(max_side)
            nw = max(1, int(round(w * scale)))
            nh = max(1, int(round(h * scale)))
            image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return None
        b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
