"""Shared PDF page renderer with optional orientation correction."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import tempfile
import threading
from collections import OrderedDict
from typing import Any

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_ORIENTATION_MODEL: Any = None
_ORIENTATION_LOCK = threading.Lock()
_RENDER_CACHE: "OrderedDict[tuple[str, float, bool], bytes]" = OrderedDict()
_RENDER_CACHE_LOCK = threading.Lock()
_RENDER_CACHE_SIZE = 32


def render_pdf_first_page(
    file_data: bytes,
    *,
    zoom: float = 3.0,
    correct_orientation: bool = True,
) -> bytes:
    """Render the first PDF page to PNG bytes.

    Non-PDF input is returned unchanged. Orientation correction uses PaddleOCR's
    document orientation classifier and only rotates on high confidence.
    """
    if not file_data.startswith(b"%PDF"):
        return file_data

    cache_key = _cache_key(file_data, zoom, correct_orientation)
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        import fitz

        doc = fitz.open(stream=file_data, filetype="pdf")
        if doc.page_count <= 0:
            doc.close()
            return file_data

        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image_data = pix.tobytes("png")
        doc.close()

        if correct_orientation and _orientation_enabled():
            image_data = _correct_orientation(image_data)

        _set_cached(cache_key, image_data)
        return image_data
    except Exception as exc:
        logger.warning("[PDFRenderer] PDF 渲染失败，使用原始文件: %s", exc)
        return file_data


def _orientation_enabled() -> bool:
    value = os.getenv("REVIEW_ENABLE_PDF_ORIENTATION_CORRECTION", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _correct_orientation(image_data: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img).convert("RGB")

        angle, score = _classify_orientation(img)
        min_score = float(os.getenv("REVIEW_PDF_ORIENTATION_MIN_SCORE", "0.80"))
        if angle not in {90, 180, 270} or score < min_score:
            return image_data

        corrected = img.rotate(angle, expand=True, fillcolor="white")
        out = io.BytesIO()
        corrected.save(out, format="PNG")
        logger.info("[PDFRenderer] PDF 页面方向纠正: rotate_ccw=%s, score=%.4f", angle, score)
        return out.getvalue()
    except Exception as exc:
        logger.warning("[PDFRenderer] PDF 页面方向判断失败，跳过纠正: %s", exc)
        return image_data


def _classify_orientation(img: Image.Image) -> tuple[int, float]:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    with _ORIENTATION_LOCK:
        model = _get_orientation_model()
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            img.save(tmp.name)
            results = list(model.predict(tmp.name))

    if not results:
        return 0, 0.0

    result = results[0]
    labels = _result_get(result, "label_names")
    scores = _result_get(result, "scores")
    if labels is None:
        labels = []
    if scores is None:
        scores = []
    label = str(labels[0]) if len(labels) > 0 else "0"
    score = float(scores[0]) if len(scores) > 0 else 0.0
    try:
        angle = int(float(label))
    except Exception:
        angle = 0
    if angle not in {0, 90, 180, 270}:
        angle = 0
    return angle, score


def _get_orientation_model() -> Any:
    global _ORIENTATION_MODEL
    if _ORIENTATION_MODEL is None:
        from paddleocr import DocImgOrientationClassification

        _ORIENTATION_MODEL = DocImgOrientationClassification()
    return _ORIENTATION_MODEL


def _result_get(result: Any, key: str) -> Any:
    if isinstance(result, dict):
        return result.get(key)
    try:
        return result[key]
    except Exception:
        return getattr(result, key, None)


def _cache_key(file_data: bytes, zoom: float, correct_orientation: bool) -> tuple[str, float, bool]:
    digest = hashlib.sha1(file_data).hexdigest()
    return digest, float(zoom), bool(correct_orientation)


def _get_cached(key: tuple[str, float, bool]) -> bytes | None:
    with _RENDER_CACHE_LOCK:
        value = _RENDER_CACHE.get(key)
        if value is not None:
            _RENDER_CACHE.move_to_end(key)
        return value


def _set_cached(key: tuple[str, float, bool], value: bytes) -> None:
    with _RENDER_CACHE_LOCK:
        _RENDER_CACHE[key] = value
        _RENDER_CACHE.move_to_end(key)
        while len(_RENDER_CACHE) > _RENDER_CACHE_SIZE:
            _RENDER_CACHE.popitem(last=False)
