"""Image fingerprinting utilities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .schemas import ImageAsset, ImageFingerprint


@dataclass
class RuntimeImageFingerprint:
    meta: ImageFingerprint
    normalized_bgr: np.ndarray
    gray: np.ndarray
    keypoint_pts: np.ndarray
    descriptors: Optional[np.ndarray]


class ImageHasher:
    def __init__(self) -> None:
        self._orb = cv2.ORB_create(nfeatures=1200)

    def build(self, asset: ImageAsset) -> Optional[RuntimeImageFingerprint]:
        arr = np.frombuffer(asset.image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return None

        normalized = self._normalize(bgr)
        gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
        keypoints, descriptors = self._orb.detectAndCompute(gray, None)
        keypoint_pts = (
            np.float32([kp.pt for kp in keypoints]).reshape(-1, 2)
            if keypoints is not None and len(keypoints) > 0
            else np.empty((0, 2), dtype=np.float32)
        )

        sha256_raw = hashlib.sha256(asset.image_bytes).hexdigest()
        ok, png = cv2.imencode(".png", normalized)
        if not ok:
            return None
        sha256_norm = hashlib.sha256(png.tobytes()).hexdigest()
        phash = cv2.img_hash.pHash(normalized)
        phash_hex = bytes(phash.flatten()).hex()

        meta = ImageFingerprint(
            image_id=asset.image_id,
            doc_id=asset.doc_id,
            sha256_raw=sha256_raw,
            sha256_norm=sha256_norm,
            phash_hex=phash_hex,
            width=int(asset.width),
            height=int(asset.height),
            keypoints=len(keypoints) if keypoints is not None else 0,
            descriptor_rows=int(descriptors.shape[0]) if descriptors is not None else 0,
        )
        return RuntimeImageFingerprint(
            meta=meta,
            normalized_bgr=normalized,
            gray=gray,
            keypoint_pts=keypoint_pts,
            descriptors=descriptors,
        )

    @staticmethod
    def _normalize(bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        max_side = max(h, w)
        if max_side <= 1024:
            return bgr
        scale = 1024.0 / float(max_side)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)


def phash_hamming(phash_hex_a: str, phash_hex_b: str) -> int:
    if not phash_hex_a or not phash_hex_b:
        return 64
    if len(phash_hex_a) != len(phash_hex_b):
        return 64
    return (int(phash_hex_a, 16) ^ int(phash_hex_b, 16)).bit_count()
