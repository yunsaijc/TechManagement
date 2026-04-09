"""Schemas for image plagiarism detection."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ImageAsset:
    doc_id: str
    image_id: str
    file_name: str
    page: int
    image_index: int
    image_bytes: bytes
    width: int
    height: int


@dataclass
class ImageFingerprint:
    image_id: str
    doc_id: str
    sha256_raw: str
    sha256_norm: str
    phash_hex: str
    width: int
    height: int
    keypoints: int
    descriptor_rows: int


@dataclass
class ImageMatch:
    query_doc: str
    query_image_id: str
    source_doc: str
    source_image_id: str
    score: float
    hash_hamming: int
    hash_score: float
    inliers: int
    geometry_score: float
    level: str
    reason: str
    query_page: int
    source_page: int
    debug_note: Optional[str] = None
