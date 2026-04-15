"""Build a text-plagiarism-style HTML report for image plagiarism results."""

from __future__ import annotations

import hashlib
import html
import io
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import mammoth
import numpy as np

from .extractor import extract_images_from_file
from .schemas import ImageMatch


class ImageReportBuilder:
    def build(
        self,
        title: str,
        matches: List[ImageMatch],
        output_html_path: Path,
        image_bytes_map: Optional[Dict[str, bytes]] = None,
        primary_documents: Optional[Dict[str, Tuple[str, bytes]]] = None,
        document_labels: Optional[Dict[str, str]] = None,
    ) -> Path:
        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes_map = image_bytes_map or {}
        primary_documents = primary_documents or {}
        document_labels = document_labels or {}
        assets_dir = output_html_path.parent / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        asset_url_cache: Dict[Tuple[str, int], Optional[str]] = {}

        grouped_docs: Dict[str, Dict[str, List[ImageMatch]]] = defaultdict(lambda: defaultdict(list))
        for item in matches:
            grouped_docs[item.query_doc][item.query_image_id].append(item)

        level_counter = Counter(item.level for item in matches)
        reason_counter = Counter(item.reason for item in matches)
        doc_order = sorted(grouped_docs.keys())

        nav_items: List[str] = []
        doc_views: List[str] = []
        for idx, query_doc in enumerate(doc_order):
            image_groups = grouped_docs[query_doc]
            ordered_query_ids = sorted(image_groups.keys(), key=self._image_sort_key)
            doc_matches = [m for qid in ordered_query_ids for m in image_groups[qid]]
            max_score = max((m.score for m in doc_matches), default=0.0)
            active = " active" if idx == 0 else ""
            query_label = self._display_doc_label(query_doc, document_labels, idx)
            source_doc_labels = self._build_source_doc_labels(doc_matches)
            nav_items.append(
                f"<button class='nav-item{active}' data-doc-target='{self._doc_target(query_doc)}'>"
                f"<div class='nav-item-title'>{html.escape(query_label)}</div>"
                f"<small>{len(ordered_query_ids)} 张命中图 · 最高分 {max_score:.4f}</small>"
                "</button>"
            )

            primary_doc = primary_documents.get(query_doc)
            primary_html = self._build_primary_html(
                query_doc=query_doc,
                query_label=query_label,
                ordered_query_ids=ordered_query_ids,
                image_groups=image_groups,
                image_bytes_map=image_bytes_map,
                primary_doc=primary_doc,
                assets_dir=assets_dir,
                asset_url_cache=asset_url_cache,
            )
            source_nav = self._build_source_nav(query_doc, ordered_query_ids, image_groups)
            source_html = self._build_source_panel(
                query_doc,
                ordered_query_ids,
                image_groups,
                image_bytes_map,
                assets_dir,
                asset_url_cache,
                source_doc_labels,
            )
            doc_views.append(
                f"""
                <section class="doc-view{active}" data-doc-view="{self._doc_target(query_doc)}">
                  <div class="panel">
                    <div class="panel-header"><span>Primary</span><span>{html.escape(query_label)}</span></div>
                    <div class="panel-body primary-panel">{primary_html}</div>
                  </div>
                  <div class="panel">
                    <div class="panel-header"><span>Source</span><span>来源图片</span></div>
                    <div class="panel-body source-panel">
                      {source_nav}
                      {source_html}
                    </div>
                  </div>
                </section>
                """
            )

        stats = self._build_stats(len(doc_order), len(matches), level_counter, reason_counter)
        html_text = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fb; color: #1f2937; }}
    .page {{ height: 100vh; display: flex; flex-direction: column; }}
    .toolbar {{ position: sticky; top: 0; z-index: 20; background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 14px 18px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
    .title {{ font-size: 18px; font-weight: 700; }}
    .title-sub {{ font-size: 13px; color: #6b7280; margin-top: 4px; }}
    .meta {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .main {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 280px 1fr; gap: 12px; padding: 12px; }}
    .sidebar {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; overflow: auto; }}
    .content {{ min-height: 0; }}
    .doc-view {{ display: none; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; height: 100%; }}
    .doc-view.active {{ display: grid; }}
    .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; display: flex; flex-direction: column; min-height: 0; }}
    .panel-header {{ padding: 12px 14px; border-bottom: 1px solid #e5e7eb; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; }}
    .panel-body {{ padding: 12px; overflow: auto; scroll-behavior: smooth; min-height: 0; }}
    .nav-title {{ font-weight: 700; margin-bottom: 10px; }}
    .nav-item {{ width: 100%; text-align: left; border: 1px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 10px; margin-bottom: 8px; cursor: pointer; }}
    .nav-item:hover, .nav-item.active {{ border-color: #fca5a5; background: #fff5f5; }}
    .nav-item-title {{ font-weight: 700; word-break: break-all; }}
    .nav-item small {{ display: block; color: #6b7280; margin-top: 4px; }}
    .empty {{ color: #9ca3af; font-size: 13px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 10px; width: 100%; }}
    .stat-card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; }}
    .stat-label {{ font-size: 12px; color: #64748b; }}
    .stat-value {{ margin-top: 4px; font-size: 20px; font-weight: 700; color: #0f172a; }}
    .docx-content {{ line-height: 1.75; font-size: 14px; color: #243043; }}
    .docx-content p {{ margin: 8px 0; }}
    .docx-content img {{ max-width: 100%; height: auto; }}
    .docx-content table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
    .docx-content td, .docx-content th {{ border: 1px solid #d1d5db; padding: 6px 8px; }}
    .docx-content .img-block {{ margin: 12px 0; padding: 10px; border: 1px solid transparent; border-radius: 12px; background: #fff; }}
    .docx-content .img-block.hit {{ cursor: pointer; }}
    .docx-content .img-block.hit.high {{ border-color: rgba(239, 68, 68, .45); background: rgba(254, 242, 242, .7); }}
    .docx-content .img-block.hit.medium {{ border-color: rgba(245, 158, 11, .45); background: rgba(255, 247, 237, .75); }}
    .docx-content .img-block.active {{ box-shadow: 0 0 0 2px rgba(59, 130, 246, .18); border-color: rgba(59, 130, 246, .45); }}
    .img-badge-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
    .img-badge {{ border-radius: 999px; padding: 4px 9px; font-size: 11px; font-weight: 700; }}
    .img-badge.high {{ background: #fee2e2; color: #b91c1c; }}
    .img-badge.medium {{ background: #ffedd5; color: #b45309; }}
    .img-badge.meta {{ background: #eef2ff; color: #3730a3; }}
    .source-nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
    .source-tab {{ border: 1px solid #e5e7eb; background: #fff; border-radius: 999px; padding: 6px 10px; font-size: 12px; cursor: pointer; }}
    .source-tab.active {{ border-color: #93c5fd; background: #eff6ff; color: #1d4ed8; }}
    .source-group {{ display: none; }}
    .source-group.active {{ display: block; }}
    .source-group-title {{ font-size: 14px; font-weight: 700; margin-bottom: 10px; }}
    .source-doc-block {{ border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; margin-bottom: 12px; overflow: hidden; }}
    .source-doc-head {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; background: #f9fafb; font-weight: 700; word-break: break-all; }}
    .source-doc-grid {{ padding: 12px; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
    .source-card {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; background: #fff; }}
    .source-card.high {{ border-color: rgba(239, 68, 68, .4); }}
    .source-card.medium {{ border-color: rgba(245, 158, 11, .4); }}
    .source-card img {{ width: 100%; max-height: 180px; object-fit: contain; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; cursor: zoom-in; }}
    img[data-lazy-src] {{ min-height: 48px; background: #f8fafc; }}
    .source-card-meta {{ margin-top: 8px; font-size: 12px; color: #6b7280; line-height: 1.55; }}
    .score-pills {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .score-pill {{ border-radius: 999px; padding: 4px 8px; font-size: 11px; background: #f3f4f6; color: #374151; }}
    .lightbox {{ position: fixed; inset: 0; display: none; align-items: center; justify-content: center; background: rgba(15, 23, 42, .82); z-index: 50; }}
    .lightbox.open {{ display: flex; }}
    .lightbox img {{ max-width: 92vw; max-height: 88vh; border-radius: 12px; background: #fff; }}
    .lightbox-close {{ position: absolute; top: 18px; right: 22px; width: 38px; height: 38px; border: 0; border-radius: 999px; background: rgba(255,255,255,.2); color: #fff; font-size: 24px; cursor: pointer; }}
    @media (max-width: 1100px) {{
      .doc-view.active {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 900px) {{
      .main {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="toolbar">
      <div>
        <div class="title">{html.escape(title)}</div>
        <div class="title-sub">左侧按文档导航，右侧为双栏视图：Primary 展示完整主文档流，Source 展示当前主图的来源图片与跳转。</div>
        <div class="stats">{stats}</div>
      </div>
      <div class="meta">
        <div class="pill">主文档：{len(doc_order)}</div>
        <div class="pill">匹配对：{len(matches)}</div>
        <div class="pill">High：{level_counter.get('high', 0)}</div>
        <div class="pill">Medium：{level_counter.get('medium', 0)}</div>
      </div>
    </div>
    <div class="main">
      <aside class="sidebar">
        <div class="nav-title">文档导航</div>
        {''.join(nav_items) or '<div class="empty">暂无命中文档</div>'}
      </aside>
      <section class="content">
        {''.join(doc_views) or '<div class="empty">No matches.</div>'}
      </section>
    </div>
  </div>
  <div id="lightbox" class="lightbox">
    <button id="lightbox-close" class="lightbox-close" type="button">&times;</button>
    <img id="lightbox-image" src="" alt="preview"/>
  </div>
  <script>
    const hydrateImages = (root) => {{
      if (!root) return;
      root.querySelectorAll('img[data-lazy-src]').forEach((img) => {{
        if (!img.getAttribute('src')) {{
          img.setAttribute('src', img.dataset.lazySrc);
        }}
        if (!img.dataset.previewSrc) {{
          img.dataset.previewSrc = img.dataset.lazySrc;
        }}
      }});
    }};

    const activateDoc = (docTarget) => {{
      document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.docTarget === docTarget));
      document.querySelectorAll('.doc-view').forEach(view => view.classList.toggle('active', view.dataset.docView === docTarget));
      const activeView = document.querySelector(`.doc-view[data-doc-view="${{docTarget}}"]`);
      if (!activeView) return;
      hydrateImages(activeView.querySelector('.primary-panel'));
      const firstHit = activeView.querySelector('.img-block.hit');
      if (firstHit) activateImage(docTarget, firstHit.dataset.imageId, false);
    }};

    const activateImage = (docTarget, imageId, scrollIntoView=true) => {{
      const view = document.querySelector(`.doc-view[data-doc-view="${{docTarget}}"]`);
      if (!view) return;
      view.querySelectorAll('.img-block.hit').forEach(node => node.classList.toggle('active', node.dataset.imageId === imageId));
      view.querySelectorAll('.source-tab').forEach(node => node.classList.toggle('active', node.dataset.imageId === imageId));
      view.querySelectorAll('.source-group').forEach(node => node.classList.toggle('active', node.dataset.imageId === imageId));
      hydrateImages(view.querySelector(`.source-group[data-image-id="${{imageId}}"]`));
      if (scrollIntoView) {{
        const primaryNode = view.querySelector(`.img-block[data-image-id="${{imageId}}"]`);
        if (primaryNode) primaryNode.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }};

    document.querySelectorAll('.nav-item').forEach(btn => {{
      btn.addEventListener('click', () => activateDoc(btn.dataset.docTarget));
    }});
    document.querySelectorAll('.img-block.hit').forEach(node => {{
      node.addEventListener('click', () => activateImage(node.dataset.docTarget, node.dataset.imageId));
    }});
    document.querySelectorAll('.source-tab').forEach(node => {{
      node.addEventListener('click', () => activateImage(node.dataset.docTarget, node.dataset.imageId));
    }});

    const lightbox = document.getElementById('lightbox');
    const lightboxImage = document.getElementById('lightbox-image');
    const closeBtn = document.getElementById('lightbox-close');
    document.querySelectorAll('[data-preview-src]').forEach(node => {{
      node.addEventListener('click', (event) => {{
        event.stopPropagation();
        lightboxImage.src = node.dataset.previewSrc;
        lightbox.classList.add('open');
      }});
    }});
    const closeLightbox = () => {{ lightbox.classList.remove('open'); lightboxImage.src = ''; }};
    closeBtn.addEventListener('click', closeLightbox);
    lightbox.addEventListener('click', (event) => {{ if (event.target === lightbox) closeLightbox(); }});
    document.addEventListener('keydown', (event) => {{ if (event.key === 'Escape') closeLightbox(); }});

    const firstDoc = document.querySelector('.nav-item.active') || document.querySelector('.nav-item');
    if (firstDoc) activateDoc(firstDoc.dataset.docTarget);
  </script>
</body>
</html>"""
        output_html_path.write_text(html_text, encoding="utf-8")
        return output_html_path

    def _build_stats(self, doc_count: int, match_count: int, level_counter: Counter, reason_counter: Counter) -> str:
        stats = [
            ("命中文档", str(doc_count)),
            ("匹配对", str(match_count)),
            ("High", str(level_counter.get("high", 0))),
            ("Medium", str(level_counter.get("medium", 0))),
        ]
        return "".join(
            f"<div class='stat-card'><div class='stat-label'>{html.escape(label)}</div><div class='stat-value'>{html.escape(value)}</div></div>"
            for label, value in stats
        )

    @staticmethod
    def _display_doc_label(doc_id: str, document_labels: Dict[str, str], index: int) -> str:
        label = (document_labels.get(doc_id) or "").strip()
        if label:
            return label
        return f"文档 {index + 1}"

    @staticmethod
    def _build_source_doc_labels(doc_matches: List[ImageMatch]) -> Dict[str, str]:
        labels: Dict[str, str] = {}
        for idx, source_doc in enumerate(sorted({item.source_doc for item in doc_matches})):
            labels[source_doc] = f"来源文档 {idx + 1}"
        return labels

    def _build_source_nav(
        self,
        query_doc: str,
        ordered_query_ids: List[str],
        image_groups: Dict[str, List[ImageMatch]],
    ) -> str:
        items = []
        for idx, query_image_id in enumerate(ordered_query_ids):
            items.append(
                f"<button class='source-tab{' active' if idx == 0 else ''}' data-doc-target='{self._doc_target(query_doc)}' data-image-id='{html.escape(query_image_id)}'>"
                f"图片 {idx + 1} · {len(image_groups[query_image_id])} 个命中"
                "</button>"
            )
        return f"<div class='source-nav'>{''.join(items)}</div>"

    def _build_source_panel(
        self,
        query_doc: str,
        ordered_query_ids: List[str],
        image_groups: Dict[str, List[ImageMatch]],
        image_bytes_map: Dict[str, bytes],
        assets_dir: Path,
        asset_url_cache: Dict[Tuple[str, int], Optional[str]],
        source_doc_labels: Dict[str, str],
    ) -> str:
        groups_html: List[str] = []
        for idx, query_image_id in enumerate(ordered_query_ids):
            matches = sorted(image_groups[query_image_id], key=lambda m: (-m.score, m.source_doc, m.source_image_id))
            by_source_doc: Dict[str, List[ImageMatch]] = defaultdict(list)
            for match in matches:
                by_source_doc[match.source_doc].append(match)
            source_doc_blocks: List[str] = []
            for source_doc in sorted(by_source_doc.keys()):
                cards: List[str] = []
                for match in by_source_doc[source_doc]:
                    img_uri = self._write_asset_file(
                        image_bytes=image_bytes_map.get(match.source_image_id),
                        assets_dir=assets_dir,
                        cache=asset_url_cache,
                        max_side=180,
                    )
                    embedding = "-" if match.embedding_score is None else f"{match.embedding_score:.4f}"
                    cards.append(
                        f"""
                        <article class="source-card {html.escape(match.level)}">
                          {self._render_source_image(img_uri, match.source_image_id, eager=(idx == 0))}
                          <div class="score-pills">
                            <span class="score-pill">score {match.score:.4f}</span>
                            <span class="score-pill">embedding {embedding}</span>
                            <span class="score-pill">ham {match.hash_hamming}</span>
                            <span class="score-pill">inliers {match.inliers}</span>
                          </div>
                          <div class="source-card-meta">页码 {match.source_page} · {html.escape(match.reason)}</div>
                        </article>
                        """
                    )
                source_doc_blocks.append(
                    f"<section class='source-doc-block'><div class='source-doc-head'>{html.escape(source_doc_labels.get(source_doc, '来源文档'))}</div><div class='source-doc-grid'>{''.join(cards)}</div></section>"
                )
            groups_html.append(
                f"<div class='source-group{' active' if idx == 0 else ''}' data-image-id='{html.escape(query_image_id)}'>"
                f"<div class='source-group-title'>图片 {idx + 1} 的来源图片</div>"
                f"{''.join(source_doc_blocks) or '<div class=\"empty\">暂无来源图片</div>'}"
                "</div>"
            )
        return "".join(groups_html)

    def _build_primary_html(
        self,
        query_doc: str,
        query_label: str,
        ordered_query_ids: List[str],
        image_groups: Dict[str, List[ImageMatch]],
        image_bytes_map: Dict[str, bytes],
        primary_doc: Optional[Tuple[str, bytes]],
        assets_dir: Path,
        asset_url_cache: Dict[Tuple[str, int], Optional[str]],
    ) -> str:
        if primary_doc is None:
            return self._fallback_primary_html(query_doc, query_label, ordered_query_ids, image_groups, image_bytes_map, assets_dir, asset_url_cache)
        file_name, file_data = primary_doc
        suffix = Path(file_name).suffix.lower()
        if suffix != ".docx":
            return self._fallback_primary_html(query_doc, query_label, ordered_query_ids, image_groups, image_bytes_map, assets_dir, asset_url_cache)

        try:
            result = mammoth.convert_to_html(
                io.BytesIO(file_data),
                convert_image=mammoth.images.data_uri,
                ignore_empty_paragraphs=True,
            )
            html_content = result.value
            all_assets = extract_images_from_file(doc_id=query_doc, file_name=file_name, file_data=file_data)
        except Exception:
            return self._fallback_primary_html(query_doc, query_label, ordered_query_ids, image_groups, image_bytes_map, assets_dir, asset_url_cache)

        html_content = self._post_process_primary_html(html_content)
        image_id_by_sha: Dict[str, List[str]] = defaultdict(list)
        fallback_ids: List[str] = []
        for asset in all_assets:
            asset_sha = self._sha256(asset.image_bytes)
            image_id_by_sha[asset_sha].append(asset.image_id)
            fallback_ids.append(asset.image_id)
        primary_anchor_assigned: set[str] = set()

        def replace_img(match: re.Match[str]) -> str:
            tag = match.group(0)
            src_match = re.search(r'src="([^"]+)"', tag)
            if not src_match:
                return tag
            src = src_match.group(1)
            decoded = self._data_uri_bytes(src)
            image_id = None
            if decoded is not None:
                sha = self._sha256(decoded)
                candidates = image_id_by_sha.get(sha)
                if candidates:
                    image_id = candidates.pop(0)
            if image_id is None and fallback_ids:
                image_id = fallback_ids.pop(0)
            if image_id is None:
                thumb_src = self._write_asset_file(decoded, assets_dir, asset_url_cache, max_side=280) if decoded is not None else None
                if thumb_src:
                    tag = self._replace_img_src(tag, thumb_src)
                    tag = re.sub(r"<img", "<img loading='lazy' data-preview-src=\"" + html.escape(thumb_src, quote=True) + "\"", tag, count=1)
                return f"<div class='img-block'>{tag}</div>"
            level = self._dominant_level(image_groups.get(image_id, []))
            is_hit_anchor = image_id in image_groups and image_id not in primary_anchor_assigned
            if is_hit_anchor:
                primary_anchor_assigned.add(image_id)
            hit = " hit" if is_hit_anchor else ""
            badge = ""
            if image_id in image_groups:
                score = max(m.score for m in image_groups[image_id])
                image_no = ordered_query_ids.index(image_id) + 1 if image_id in ordered_query_ids else 0
                badge = (
                    "<div class='img-badge-row'>"
                    f"<span class='img-badge meta'>图片 {image_no}</span>"
                    f"<span class='img-badge {html.escape(level)}'>{html.escape(level.upper())}</span>"
                    f"<span class='img-badge meta'>score {score:.4f}</span>"
                    "</div>"
                )
            thumb_src = self._write_asset_file(decoded, assets_dir, asset_url_cache, max_side=300) if decoded is not None else None
            if thumb_src:
                tag = self._replace_img_src(tag, thumb_src)
                src = thumb_src
            decorated_tag = re.sub(r"<img", "<img loading='lazy' data-preview-src=\"" + html.escape(src, quote=True) + "\"", tag, count=1)
            data_attrs = ""
            if is_hit_anchor:
                data_attrs = f" data-doc-target='{self._doc_target(query_doc)}' data-image-id='{html.escape(image_id)}'"
            return (
                f"<div class='img-block{hit} {html.escape(level)}'{data_attrs}>"
                f"{badge}{decorated_tag}</div>"
            )

        return re.sub(r"<img\b[^>]*>", replace_img, html_content)

    def _fallback_primary_html(
        self,
        query_doc: str,
        query_label: str,
        ordered_query_ids: List[str],
        image_groups: Dict[str, List[ImageMatch]],
        image_bytes_map: Dict[str, bytes],
        assets_dir: Path,
        asset_url_cache: Dict[Tuple[str, int], Optional[str]],
    ) -> str:
        blocks = []
        for image_id in ordered_query_ids:
            uri = self._write_asset_file(
                image_bytes=image_bytes_map.get(image_id),
                assets_dir=assets_dir,
                cache=asset_url_cache,
                max_side=300,
            )
            level = self._dominant_level(image_groups.get(image_id, []))
            score = max((m.score for m in image_groups.get(image_id, [])), default=0.0)
            blocks.append(
                f"<div class='img-block hit {html.escape(level)}' data-doc-target='{self._doc_target(query_doc)}' data-image-id='{html.escape(image_id)}'>"
                f"<div class='img-badge-row'><span class='img-badge meta'>图片 {ordered_query_ids.index(image_id) + 1}</span><span class='img-badge {html.escape(level)}'>{html.escape(level.upper())}</span><span class='img-badge meta'>score {score:.4f}</span></div>"
                f"{self._render_source_image(uri, image_id, eager=True)}"
                "</div>"
            )
        return f"<div class='docx-content'>{''.join(blocks) or '<p class=\"empty\">无主文档内容</p>'}</div>"

    @staticmethod
    def _post_process_primary_html(html_content: str) -> str:
        html_content = re.sub(r"<table", '<table class="docx-table"', html_content)
        html_content = re.sub(r"<p>", '<p class="docx-paragraph">', html_content)
        html_content = re.sub(r"<img", '<img class="docx-image"', html_content)
        return f'<div class="docx-content">{html_content}</div>'

    @staticmethod
    def _render_source_image(data_uri: Optional[str], image_id: str, eager: bool = False) -> str:
        safe_id = html.escape(image_id)
        if not data_uri:
            return "<div class='thumb-miss'>[无图像预览]</div>"
        if eager:
            return f"<img src='{data_uri}' loading='lazy' alt='{safe_id}' data-preview-src='{data_uri}'/>"
        return f"<img data-lazy-src='{data_uri}' loading='lazy' alt='{safe_id}'/>"

    @staticmethod
    def _replace_img_src(tag: str, new_src: str) -> str:
        escaped = html.escape(new_src, quote=True)
        if re.search(r'src="[^"]*"', tag):
            return re.sub(r'src="[^"]*"', f'src="{escaped}"', tag, count=1)
        return tag.replace("<img", f"<img src=\"{escaped}\"", 1)

    @staticmethod
    def _dominant_level(items: List[ImageMatch]) -> str:
        if not items:
            return "low"
        rank = {"high": 2, "medium": 1, "low": 0}
        best = "low"
        for item in items:
            if rank.get(item.level, 0) > rank.get(best, 0):
                best = item.level
        return best

    @staticmethod
    def _doc_target(query_doc: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "-", query_doc).strip("-").lower() or "doc"

    @staticmethod
    def _image_sort_key(image_id: str) -> Tuple[int, int, str]:
        match = re.search(r"#p(\d+)i(\d+)$", image_id or "")
        if match:
            return int(match.group(1)), int(match.group(2)), image_id
        return (10**9, 10**9, image_id or "")

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _data_uri_bytes(src: str) -> Optional[bytes]:
        if not src.startswith("data:"):
            return None
        try:
            import base64
            _, b64 = src.split(",", 1)
            return base64.b64decode(b64)
        except Exception:
            return None

    def _write_asset_file(
        self,
        image_bytes: Optional[bytes],
        assets_dir: Path,
        cache: Dict[Tuple[str, int], Optional[str]],
        max_side: int,
    ) -> Optional[str]:
        if not image_bytes:
            return None
        sha = self._sha256(image_bytes)
        cache_key = (sha, int(max_side))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return None
        h, w = image.shape[:2]
        current_max = max(h, w)
        if current_max > max_side:
            scale = float(max_side) / float(current_max)
            nw = max(1, int(round(w * scale)))
            nh = max(1, int(round(h * scale)))
            image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 62])
        if not ok:
            return None
        file_name = f"{sha}_{max_side}.jpg"
        out_path = assets_dir / file_name
        if not out_path.exists():
            out_path.write_bytes(encoded.tobytes())
        rel = f"assets/{file_name}"
        cache[cache_key] = rel
        return rel
