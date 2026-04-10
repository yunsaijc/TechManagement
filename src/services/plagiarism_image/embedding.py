"""Bailian multimodal embedding client for image reranking."""

from __future__ import annotations

import base64
import time
from typing import List, Optional

import cv2
import numpy as np
import requests

from .config import (
    IMAGE_EMBEDDING_API_KEY,
    IMAGE_EMBEDDING_BASE_URL,
    IMAGE_EMBEDDING_BATCH_SIZE,
    IMAGE_EMBEDDING_DIMENSION,
    IMAGE_EMBEDDING_JPEG_QUALITY,
    IMAGE_EMBEDDING_MAX_SIDE,
    IMAGE_EMBEDDING_MODEL,
    IMAGE_EMBEDDING_RES_LEVEL,
    IMAGE_EMBEDDING_TIMEOUT_SECONDS,
)


class BailianImageEmbeddingClient:
    """Small REST client for Bailian multimodal image embeddings.

    The client is intentionally conservative: images are resized before upload,
    requests are small-batched, and vectors are L2-normalized before storage.
    """

    def __init__(self) -> None:
        self.api_key = IMAGE_EMBEDDING_API_KEY
        self.base_url = IMAGE_EMBEDDING_BASE_URL.rstrip("/")
        self.model = IMAGE_EMBEDDING_MODEL
        self.dimension = int(IMAGE_EMBEDDING_DIMENSION)
        self.batch_size = max(1, int(IMAGE_EMBEDDING_BATCH_SIZE))
        self.timeout_seconds = float(IMAGE_EMBEDDING_TIMEOUT_SECONDS)
        self._session = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def embed_images(self, image_bytes_list: List[bytes]) -> List[Optional[np.ndarray]]:
        if not image_bytes_list:
            return []
        if not self.enabled:
            return [None for _ in image_bytes_list]

        out: List[Optional[np.ndarray]] = []
        for start in range(0, len(image_bytes_list), self.batch_size):
            batch = image_bytes_list[start : start + self.batch_size]
            out.extend(self._embed_batch(batch))
        return out

    def _embed_batch(self, image_bytes_list: List[bytes]) -> List[Optional[np.ndarray]]:
        encoded_items: List[Optional[str]] = [self._to_data_uri(item) for item in image_bytes_list]
        valid_positions = [idx for idx, item in enumerate(encoded_items) if item]
        if not valid_positions:
            return [None for _ in image_bytes_list]

        contents = [{"image": encoded_items[idx]} for idx in valid_positions]
        payload = {
            "model": self.model,
            "input": {"contents": contents},
            "parameters": {
                "dimension": self.dimension,
                "output_type": "dense",
            },
        }
        if IMAGE_EMBEDDING_RES_LEVEL:
            payload["parameters"]["res_level"] = int(IMAGE_EMBEDDING_RES_LEVEL)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self._session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                if resp.status_code == 429 and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                result = resp.json()
                vectors = self._parse_vectors(result)
                if len(vectors) != len(valid_positions):
                    raise RuntimeError(f"Bailian image embedding response mismatch: expected {len(valid_positions)}, got {len(vectors)}")
                out: List[Optional[np.ndarray]] = [None for _ in image_bytes_list]
                for pos, vec in zip(valid_positions, vectors):
                    out[pos] = self._normalize_vector(vec)
                return out
            except Exception as exc:  # pragma: no cover - network defensive path
                last_exc = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if last_exc:
            raise last_exc
        return [None for _ in image_bytes_list]

    @staticmethod
    def _parse_vectors(result: dict) -> List[List[float]]:
        output = result.get("output") or {}
        embeddings = output.get("embeddings") or result.get("data") or []
        vectors: List[List[float]] = []
        for item in embeddings:
            if not isinstance(item, dict):
                continue
            emb = item.get("embedding") or item.get("vector")
            if isinstance(emb, list):
                vectors.append(emb)
        return vectors

    @staticmethod
    def _normalize_vector(vec: List[float]) -> Optional[np.ndarray]:
        arr = np.asarray(vec, dtype=np.float32)
        if arr.ndim != 1 or arr.size == 0:
            return None
        norm = float(np.linalg.norm(arr))
        if norm <= 0.0:
            return None
        return arr / norm

    @staticmethod
    def _to_data_uri(image_bytes: bytes) -> Optional[str]:
        if not image_bytes:
            return None
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return None
        h, w = image.shape[:2]
        max_side = max(h, w)
        if max_side > IMAGE_EMBEDDING_MAX_SIDE:
            scale = float(IMAGE_EMBEDDING_MAX_SIDE) / float(max_side)
            nw = max(1, int(round(w * scale)))
            nh = max(1, int(round(h * scale)))
            image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(IMAGE_EMBEDDING_JPEG_QUALITY)])
        if not ok:
            return None
        b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
