"""Extract image assets from DOCX/PDF/image files."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import List, Tuple

import cv2
import fitz
import numpy as np

from .schemas import ImageAsset

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _image_size(image_bytes: bytes) -> Tuple[int, int]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return 0, 0
    h, w = img.shape[:2]
    return int(w), int(h)


def _is_supported_image_name(name: str) -> bool:
    return Path(name.lower()).suffix in _IMAGE_EXT


def _detect_type(file_name: str) -> str:
    suffix = Path(file_name.lower()).suffix
    if suffix == ".docx":
        return "docx"
    if suffix == ".pdf":
        return "pdf"
    if suffix in _IMAGE_EXT:
        return "image"
    return "unknown"


def extract_images_from_file(doc_id: str, file_name: str, file_data: bytes) -> List[ImageAsset]:
    file_type = _detect_type(file_name)
    if file_type == "docx":
        return _extract_docx_images(doc_id, file_name, file_data)
    if file_type == "pdf":
        return _extract_pdf_images(doc_id, file_name, file_data)
    if file_type == "image":
        return _extract_standalone_image(doc_id, file_name, file_data)
    return []


def _extract_docx_images(doc_id: str, file_name: str, file_data: bytes) -> List[ImageAsset]:
    assets: List[ImageAsset] = []
    with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
        media_names = [
            name for name in zf.namelist()
            if name.startswith("word/media/") and _is_supported_image_name(name)
        ]
        media_names.sort()
        for idx, name in enumerate(media_names, 1):
            raw = zf.read(name)
            width, height = _image_size(raw)
            if width < 64 or height < 64:
                continue
            image_id = f"{doc_id}#p1i{idx}"
            assets.append(
                ImageAsset(
                    doc_id=doc_id,
                    image_id=image_id,
                    file_name=file_name,
                    page=1,
                    image_index=idx,
                    image_bytes=raw,
                    width=width,
                    height=height,
                )
            )
    return assets


def _extract_pdf_images(doc_id: str, file_name: str, file_data: bytes) -> List[ImageAsset]:
    assets: List[ImageAsset] = []
    pdf = fitz.open(stream=file_data, filetype="pdf")
    try:
        counter = 0
        for page_idx in range(pdf.page_count):
            page = pdf[page_idx]
            images = page.get_images(full=True)
            for item in images:
                xref = item[0]
                meta = pdf.extract_image(xref)
                raw = meta.get("image")
                if not raw:
                    continue
                width, height = _image_size(raw)
                if width < 64 or height < 64:
                    continue
                counter += 1
                image_id = f"{doc_id}#p{page_idx + 1}i{counter}"
                assets.append(
                    ImageAsset(
                        doc_id=doc_id,
                        image_id=image_id,
                        file_name=file_name,
                        page=page_idx + 1,
                        image_index=counter,
                        image_bytes=raw,
                        width=width,
                        height=height,
                    )
                )
    finally:
        pdf.close()
    return assets


def _extract_standalone_image(doc_id: str, file_name: str, file_data: bytes) -> List[ImageAsset]:
    width, height = _image_size(file_data)
    if width < 64 or height < 64:
        return []
    return [
        ImageAsset(
            doc_id=doc_id,
            image_id=f"{doc_id}#p1i1",
            file_name=file_name,
            page=1,
            image_index=1,
            image_bytes=file_data,
            width=width,
            height=height,
        )
    ]
