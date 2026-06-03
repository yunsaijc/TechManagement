"""OCR 文字识别处理器"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import List

from src.common.models.document import BoundingBox, TextBlock


class OCRProcessor:
    """OCR 处理器 - 基于 PaddleOCR 实现"""

    def __init__(self, languages: List[str] = None):
        """初始化 OCR 处理器

        Args:
            languages: 语言列表，默认 ['ch_sim', 'en']
        """
        self.languages = languages or ["ch_sim", "en"]
        self._reader = None

    def _get_reader(self):
        """延迟加载 reader"""
        if self._reader is None:
            os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")
            os.environ.setdefault("PADDLE_PDX_USE_PIR_TRT", "False")
            os.environ.setdefault("FLAGS_enable_pir_api", "0")
            from paddleocr import PaddleOCR

            self._reader = PaddleOCR(use_angle_cls=False, lang="ch")
        return self._reader

    async def recognize(
        self,
        image_data: bytes,
        page: int = 0,
    ) -> List[TextBlock]:
        """识别文字

        Args:
            image_data: 图片数据
            page: 页码

        Returns:
            文本块列表
        """
        import numpy as np

        nparr = np.frombuffer(image_data, dtype=np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return []

        height, width = img.shape[:2]
        max_side = max(height, width)
        if max_side > 1800:
            scale = 1800 / max_side
            img = cv2.resize(img, (max(1, int(width * scale)), max(1, int(height * scale))))

        img_height, img_width = img.shape[:2]

        ok, encoded = cv2.imencode(".png", img)
        if not ok:
            return []

        reader = self._get_reader()
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            tmp.write(encoded.tobytes())
            tmp.flush()
            result = reader.predict(tmp.name)
        if not result:
            return []
        first = result[0]
        texts_raw = first.get("rec_texts", [])
        boxes_raw = first.get("rec_boxes", [])
        scores_raw = first.get("rec_scores", [])
        texts = list(texts_raw) if texts_raw is not None else []
        boxes = list(boxes_raw) if boxes_raw is not None else []
        scores = list(scores_raw) if scores_raw is not None else []

        text_blocks = []
        for idx, text in enumerate(texts):
            if not text.strip() or idx >= len(boxes):
                continue
            left, top, right, bottom = boxes[idx]
            left = max(0, int(left))
            top = max(0, int(top))
            right = min(img_width, int(right))
            bottom = min(img_height, int(bottom))
            confidence = float(scores[idx]) if idx < len(scores) else 0.0

            text_blocks.append(
                TextBlock(
                    text=text,
                    bbox=BoundingBox(
                        x=left,
                        y=top,
                        width=max(0, right - left),
                        height=max(0, bottom - top),
                    ),
                    page=page,
                    confidence=confidence,
                )
            )

        return text_blocks


# 简单回退实现
class SimpleOCRProcessor:
    """简单的 OCR 处理器 - 基于 Tesseract 的稳定回退实现"""

    def __init__(self, languages: List[str] | None = None):
        self.languages = languages or self._default_languages()
        self._tesseract = shutil.which("tesseract")
        if not self._tesseract:
            raise RuntimeError("tesseract not installed")
        self._available_languages = self._list_languages()
        self.languages = [lang for lang in self.languages if lang in self._available_languages] or ["eng"]

    async def recognize(
        self,
        image_data: bytes,
        page: int = 0,
    ) -> List[TextBlock]:
        """识别文字"""
        lang = "+".join(self.languages)
        # Fallback path: if cv2 is unavailable, run tesseract directly on the
        # input image bytes produced by the upstream renderer.
        if cv2 is None:
            with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
                tmp.write(image_data)
                tmp.flush()
                proc = subprocess.run(
                    [self._tesseract, tmp.name, "stdout", "-l", lang, "--psm", "6", "tsv"],
                    capture_output=True,
                    text=True,
                )
        else:
            import numpy as np

            nparr = np.frombuffer(image_data, dtype=np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return []

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            ok, encoded = cv2.imencode(".png", binary)
            if not ok:
                return []

            with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
                tmp.write(encoded.tobytes())
                tmp.flush()
                proc = subprocess.run(
                    [self._tesseract, tmp.name, "stdout", "-l", lang, "--psm", "6", "tsv"],
                    capture_output=True,
                    text=True,
                )
        if proc.returncode != 0:
            return []

        text_blocks: list[TextBlock] = []
        for line in proc.stdout.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 12:
                continue
            level, _, _, _, _, _, left, top, width, height, conf, text = parts[:11] + ["\t".join(parts[11:])]
            if level != "5":
                continue
            text = (text or "").strip()
            if not text:
                continue
            try:
                confidence = max(0.0, float(conf)) / 100.0
            except ValueError:
                confidence = 0.0
            try:
                bbox = BoundingBox(
                    x=float(left),
                    y=float(top),
                    width=float(width),
                    height=float(height),
                )
            except ValueError:
                continue
            text_blocks.append(TextBlock(text=text, bbox=bbox, page=page, confidence=confidence))
        return text_blocks

    def _list_languages(self) -> set[str]:
        proc = subprocess.run(
            [self._tesseract, "--list-langs"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return {"eng"}
        langs = {
            line.strip()
            for line in proc.stdout.splitlines()
            if line.strip() and not line.startswith("List of available languages")
        }
        return langs or {"eng"}

    @staticmethod
    def _default_languages() -> List[str]:
        preferred = os.getenv("ACCEPT_TESSERACT_LANGS", "").strip()
        if preferred:
            return [part.strip() for part in preferred.split("+") if part.strip()]
        return ["chi_sim", "eng", "osd"]


# 尝试导入 cv2
try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore
