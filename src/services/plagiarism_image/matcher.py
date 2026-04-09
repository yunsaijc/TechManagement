"""Image matching logic: hash gate + geometric verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .config import (
    DEFAULT_HASH_HAMMING_MAX,
    DEFAULT_HIGH_SCORE,
    DEFAULT_MEDIUM_SCORE,
    DEFAULT_MIN_INLIERS,
)
from .hashing import RuntimeImageFingerprint, phash_hamming
from .schemas import ImageAsset, ImageMatch


@dataclass
class MatchConfig:
    hash_hamming_max: int = DEFAULT_HASH_HAMMING_MAX
    high_score: float = DEFAULT_HIGH_SCORE
    medium_score: float = DEFAULT_MEDIUM_SCORE
    min_inliers_high: int = DEFAULT_MIN_INLIERS


class ImageMatcher:
    def __init__(self, cfg: Optional[MatchConfig] = None) -> None:
        self.cfg = cfg or MatchConfig()
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    def compare(
        self,
        query_asset: ImageAsset,
        source_asset: ImageAsset,
        query_fp: RuntimeImageFingerprint,
        source_fp: RuntimeImageFingerprint,
    ) -> Optional[ImageMatch]:
        if query_asset.doc_id == source_asset.doc_id:
            return None

        if query_fp.meta.sha256_norm == source_fp.meta.sha256_norm:
            return ImageMatch(
                query_doc=query_asset.doc_id,
                query_image_id=query_asset.image_id,
                source_doc=source_asset.doc_id,
                source_image_id=source_asset.image_id,
                score=1.0,
                hash_hamming=0,
                hash_score=1.0,
                inliers=0,
                geometry_score=1.0,
                level="high",
                reason="exact_sha256_norm",
                query_page=query_asset.page,
                source_page=source_asset.page,
            )

        hamming = phash_hamming(query_fp.meta.phash_hex, source_fp.meta.phash_hex)
        if hamming > self.cfg.hash_hamming_max:
            return None

        hash_score = max(0.0, 1.0 - (float(hamming) / 64.0))
        inliers = self._geometry_inliers(
            query_fp.keypoint_pts,
            source_fp.keypoint_pts,
            query_fp.descriptors,
            source_fp.descriptors,
        )
        geometry_score = min(float(inliers) / 40.0, 1.0)

        score = round(0.6 * hash_score + 0.4 * geometry_score, 4)
        if score >= self.cfg.high_score and inliers >= self.cfg.min_inliers_high:
            level = "high"
        elif score >= self.cfg.medium_score:
            level = "medium"
        else:
            level = "low"

        return ImageMatch(
            query_doc=query_asset.doc_id,
            query_image_id=query_asset.image_id,
            source_doc=source_asset.doc_id,
            source_image_id=source_asset.image_id,
            score=score,
            hash_hamming=hamming,
            hash_score=round(hash_score, 4),
            inliers=inliers,
            geometry_score=round(geometry_score, 4),
            level=level,
            reason="hash+geometry",
            query_page=query_asset.page,
            source_page=source_asset.page,
        )

    def _geometry_inliers(
        self,
        pts_a: np.ndarray,
        pts_b: np.ndarray,
        desc_a: Optional[np.ndarray],
        desc_b: Optional[np.ndarray],
    ) -> int:
        if desc_a is None or desc_b is None:
            return 0
        if len(pts_a) == 0 or len(pts_b) == 0:
            return 0
        if len(desc_a) < 8 or len(desc_b) < 8:
            return 0

        try:
            knn = self._bf.knnMatch(desc_a, desc_b, k=2)
        except cv2.error:
            return 0

        good = []
        for pair in knn:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < 0.75 * n.distance:
                good.append(m)

        if len(good) < 8:
            return 0

        src = np.float32([pts_a[m.queryIdx] for m in good]).reshape(-1, 1, 2)
        dst = np.float32([pts_b[m.trainIdx] for m in good]).reshape(-1, 1, 2)

        try:
            _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        except cv2.error:
            return 0
        if mask is None:
            return 0
        return int(mask.ravel().sum())
