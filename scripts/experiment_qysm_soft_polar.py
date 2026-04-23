#!/usr/bin/env python3
"""企业声明公章软 annulus + upper polar 实验。

目标：
- 不改主链路
- 固定走 qysm 企业公章 crop
- 圆心/半径沿用当前检测逻辑
- annulus 内保留红色灰度细节，不做硬二值 ring
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.extractors.stamp import StampExtractor
from src.services.review.agent import ReviewAgent
from src.services.review.smb_file_reader import SMBReviewFileReader


@dataclass(frozen=True)
class PolarCase:
    name: str
    file_path: str
    expected: str
    crop_box: Tuple[float, float, float, float] = (0.45, 0.44, 0.88, 0.82)


CASES: Dict[str, PolarCase] = {
    "qysm_202560032": PolarCase(
        name="qysm_202560032",
        file_path=r"FJCL\static\rpw\zmcl2025\2025-109-6001\1763603584754.PDF",
        expected="润泽智算科技集团股份有限公司",
    ),
    "qysm_202560030": PolarCase(
        name="qysm_202560030",
        file_path=r"FJCL\static\rpw\zmcl2025\2025-243-6003\1763523592841.pdf",
        expected="北京煜鼎增材制造研究院股份有限公司",
    ),
    "qysm_202560033": PolarCase(
        name="qysm_202560033",
        file_path=r"FJCL\static\rpw\zmcl2025\2025-243-6004\1763544252972.pdf",
        expected="芯昇科技有限公司",
    ),
}


POLAR_CONFIGS: Tuple[Tuple[str, float, float, float, float], ...] = (
    ("soft_focus", 0.46, 0.90, -186.0, 6.0),
    ("soft_wide", 0.42, 0.95, -210.0, 30.0),
    ("soft_overscan", 0.40, 0.97, -228.0, 48.0),
    ("soft_topsafe", 0.37, 0.985, -236.0, 56.0),
)


def _iter_cases(names: Iterable[str]) -> List[PolarCase]:
    resolved: List[PolarCase] = []
    for name in names:
        key = str(name).strip()
        if not key:
            continue
        if key == "all":
            for case in CASES.values():
                if case not in resolved:
                    resolved.append(case)
            continue
        case = CASES.get(key)
        if case is None:
            raise SystemExit(f"unknown case: {key}")
        resolved.append(case)
    return resolved


def _extract_texts(stamps_result: Dict[str, object]) -> List[str]:
    texts: List[str] = []
    for item in list((stamps_result or {}).get("stamps", []) or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("unit") or item.get("text") or "").strip()
        if text and text not in texts:
            texts.append(text)
    return texts


def _save_image(path: Path, image: Optional[Image.Image]) -> None:
    if image is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _build_soft_polar_source(
    image: Image.Image,
    red_gain: float,
    sharpen_amount: float,
) -> Image.Image:
    rgb = np.array(image.convert("RGB")).astype(np.float32)
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    dominance = np.maximum(0.0, red - np.maximum(green, blue))
    dominance = np.clip(dominance * red_gain, 0.0, 255.0)
    gray = 255.0 - dominance
    gray = cv2.medianBlur(gray.astype(np.uint8), 3)
    gray = cv2.resize(
        gray,
        (max(1, image.size[0] * 2), max(1, image.size[1] * 2)),
        interpolation=cv2.INTER_CUBIC,
    )
    if sharpen_amount > 0:
        blur = cv2.GaussianBlur(gray, (0, 0), 1.1)
        gray = cv2.addWeighted(gray, 1.0 + sharpen_amount, blur, -sharpen_amount, 0)
    gray = cv2.copyMakeBorder(gray, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    return Image.fromarray(gray).convert("RGB")


def _build_annulus_preview(
    source_image: Image.Image,
    circle: Tuple[float, float, float],
    inner_ratio: float,
    outer_ratio: float,
) -> Image.Image:
    gray = np.array(source_image.convert("L"))
    height, width = gray.shape[:2]
    cx, cy, radius = circle
    cx = cx * 2.0 + 24.0
    cy = cy * 2.0 + 24.0
    radius = radius * 2.0
    yy, xx = np.ogrid[:height, :width]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    mask = (dist >= radius * inner_ratio) & (dist <= radius * outer_ratio)
    out = np.full_like(gray, 255)
    out[mask] = gray[mask]
    return Image.fromarray(out).convert("RGB")


async def _score_polar_candidate(
    extractor: StampExtractor,
    candidate_name: str,
    polar_image: Image.Image,
) -> Dict[str, object]:
    polar_bytes = extractor._image_to_png_bytes(polar_image)
    ocr_inputs: List[Tuple[str, bytes]] = [(candidate_name, polar_bytes)]
    ocr_inputs.extend(extractor._build_polar_segments(polar_image))
    results = await asyncio.gather(
        *[
            extractor._run_qwen_ocr(
                image_data=image_data,
                prompt="请对这张公章文字展开图执行 OCR，只返回图片中实际可见文字，不要纠错，不要补全。",
                debug_name=f"exp_{candidate_name}_{name}_ocr",
                task="advanced_recognition",
                enable_rotate=False,
            )
            for name, image_data in ocr_inputs
        ],
        return_exceptions=True,
    )

    ordered_segment_texts: List[str] = []
    full_texts: List[str] = []
    per_input: List[Dict[str, object]] = []
    for (name, _), result in zip(ocr_inputs, results):
        if isinstance(result, Exception):
            per_input.append({"variant": name, "texts": [], "error": str(result)})
            continue
        texts = extractor._extract_stamp_unit_texts(result, variant_name=name)
        per_input.append({"variant": name, "texts": texts})
        if name == candidate_name:
            full_texts = [text for text in texts if text]
        elif name.startswith("polar_upper_seg"):
            merged = extractor._merge_ordered_stamp_texts(texts)
            if merged:
                ordered_segment_texts.append(merged)

    merged_segment = extractor._merge_overlapping_stamp_segments(ordered_segment_texts)
    texts: List[str] = []
    for text in full_texts:
        normalized = extractor._normalize_stamp_unit_text(text)
        if normalized and normalized not in texts:
            texts.append(normalized)
    if merged_segment and merged_segment not in texts:
        texts.append(merged_segment)

    primary_text = texts[0] if texts else ""
    edge_penalty = extractor._polar_edge_cut_penalty(polar_image)
    score = (
        len(primary_text),
        sum(1 for item in ordered_segment_texts if item),
        1.0 - edge_penalty,
    )
    return {
        "candidate": candidate_name,
        "texts": texts[:2],
        "score": score,
        "ocr": per_input,
    }


async def _run_case(case: PolarCase, output_root: Path) -> Dict[str, object]:
    reader = SMBReviewFileReader()
    agent = ReviewAgent()
    extractor = StampExtractor()

    file_data = reader.read_bytes(case.file_path)
    page_data = agent._pdf_to_image(file_data)
    page_image = Image.open(io.BytesIO(page_data)).convert("RGB")
    crop_image = agent._crop_ratio_image(page_image, case.crop_box)
    crop_bytes = agent._image_to_png_bytes(crop_image)

    case_dir = output_root / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    _save_image(case_dir / "page1.png", page_image)
    _save_image(case_dir / "crop.png", crop_image)

    current_result = await extractor.extract(crop_bytes)
    current_result = current_result or {"stamps": []}

    tight_crop = extractor._crop_largest_red_stamp_component(crop_image)
    polar_raw_source = tight_crop or crop_image
    _save_image(case_dir / "tight_crop.png", tight_crop)

    circles = extractor._detect_stamp_circle_candidates(polar_raw_source)
    if not circles:
        return {
            "case": case.name,
            "expected": case.expected,
            "current": _extract_texts(current_result),
            "best": [],
            "error": "circle not found",
            "output_dir": str(case_dir),
        }

    scored_candidates: List[Dict[str, object]] = []
    for source_name, red_gain, sharpen_amount in (
        ("soft_base", 2.2, 0.0),
        ("soft_sharp", 2.4, 0.55),
    ):
        source_image = _build_soft_polar_source(
            polar_raw_source,
            red_gain=red_gain,
            sharpen_amount=sharpen_amount,
        )
        _save_image(case_dir / f"{source_name}_source.png", source_image)

        gray = np.array(source_image.convert("L"))
        for circle_name, circle in circles:
            for config_name, inner_ratio, outer_ratio, start_deg, end_deg in POLAR_CONFIGS:
                annulus_preview = _build_annulus_preview(
                    source_image=source_image,
                    circle=circle,
                    inner_ratio=inner_ratio,
                    outer_ratio=outer_ratio,
                )
                _save_image(case_dir / f"{source_name}_{circle_name}_{config_name}_annulus.png", annulus_preview)

                cx, cy, radius = circle
                band = extractor._unwrap_upper_annulus(
                    gray,
                    cx * 2.0 + 24.0,
                    cy * 2.0 + 24.0,
                    radius * 2.0,
                    inner_ratio=inner_ratio,
                    outer_ratio=outer_ratio,
                    start_deg=start_deg,
                    end_deg=end_deg,
                )
                if band is None:
                    continue
                band = extractor._trim_unwrapped_band_rows(band)
                band = extractor._trim_unwrapped_band_cols(band)
                if band is None:
                    continue
                band = cv2.resize(
                    band,
                    (max(1600, band.shape[1] * 2), max(320, band.shape[0] * 3)),
                    interpolation=cv2.INTER_CUBIC,
                )
                band = cv2.copyMakeBorder(band, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)
                polar_image = Image.fromarray(band).convert("RGB")
                candidate_name = f"{source_name}_{circle_name}_{config_name}"
                _save_image(case_dir / f"{candidate_name}.png", polar_image)
                scored_candidates.append(await _score_polar_candidate(extractor, candidate_name, polar_image))

    scored_candidates.sort(key=lambda item: tuple(item["score"]), reverse=True)
    best = scored_candidates[0] if scored_candidates else {"texts": [], "candidate": "", "score": (-1, -1, -1.0)}

    return {
        "case": case.name,
        "expected": case.expected,
        "current": _extract_texts(current_result),
        "best": list(best.get("texts") or []),
        "best_candidate": best.get("candidate") or "",
        "best_score": best.get("score"),
        "top3": [
            {
                "candidate": str(item.get("candidate") or ""),
                "texts": list(item.get("texts") or []),
                "score": item.get("score"),
            }
            for item in scored_candidates[:3]
        ],
        "output_dir": str(case_dir),
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description="企业声明公章软 annulus + upper polar 实验")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help=f"case name, available: {', '.join(sorted(CASES))}, default=all",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/tdkx/workspace/tech/debug_cropped/qysm_soft_polar_experiment",
        help="directory for saving experiment images",
    )
    args = parser.parse_args()

    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    for case in _iter_cases(args.cases or ["all"]):
        summary = await _run_case(case, output_root)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(_main())
