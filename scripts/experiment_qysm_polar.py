#!/usr/bin/env python3
"""企业声明公章前处理实验。

目标：
- 不改主链路
- 只验证“圆章净化 + polar 展开 + 单链 OCR”这条路线
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


def _build_rolled_polar_variants(
    extractor: StampExtractor,
    raw_image: Image.Image,
    enhanced_image: Image.Image,
) -> List[Tuple[str, Image.Image]]:
    circles = extractor._detect_stamp_circle_candidates(raw_image)
    if not circles:
        return []
    gray = np.array(enhanced_image.convert("L"))
    candidates: List[Tuple[str, Image.Image]] = []
    scale = 2.0
    border = 24.0
    for circle_source, circle in circles:
        cx, cy, radius = circle
        if radius < 20:
            continue
        cx = cx * scale + border
        cy = cy * scale + border
        radius = radius * scale
        for candidate_name, inner_ratio, outer_ratio, start_deg, end_deg in (
            ("focus", 0.44, 0.90, -186.0, 6.0),
            ("wide", 0.38, 0.95, -194.0, 14.0),
            ("wider", 0.40, 0.94, -202.0, 22.0),
            ("widest", 0.42, 0.93, -214.0, 34.0),
            ("overscan", 0.43, 0.92, -226.0, 46.0),
            ("inner", 0.50, 0.86, -182.0, 2.0),
        ):
            band = extractor._unwrap_upper_annulus(
                gray,
                cx,
                cy,
                radius,
                inner_ratio=inner_ratio,
                outer_ratio=outer_ratio,
                start_deg=start_deg,
                end_deg=end_deg,
            )
            if band is None:
                continue
            band = extractor._remove_stamp_ring_rows(band)
            band = extractor._trim_unwrapped_band_rows(band)
            band = extractor._trim_unwrapped_band_cols(band)
            if band is None:
                continue
            band = extractor._roll_polar_band_to_blank_seam(band)
            forward = cv2.resize(
                band,
                (max(1600, band.shape[1] * 2), max(320, band.shape[0] * 3)),
                interpolation=cv2.INTER_CUBIC,
            )
            forward = cv2.copyMakeBorder(forward, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)
            candidates.append((f"{circle_source}_{candidate_name}_rolled", Image.fromarray(forward).convert("RGB")))
    return candidates


def _build_red_boost_source(image: Image.Image) -> Image.Image:
    rgb = np.array(image.convert("RGB")).astype(np.int16)
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    mask = (
        (red >= 95)
        & (red >= green + 16)
        & (red >= blue + 16)
    ).astype(np.uint8) * 255
    mask = cv2.medianBlur(mask, 3)
    kernel_close = np.ones((3, 3), dtype=np.uint8)
    kernel_dilate = np.ones((2, 2), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=2)
    mask = cv2.dilate(mask, kernel_dilate, iterations=1)
    mask = cv2.resize(
        mask,
        (max(1, image.size[0] * 2), max(1, image.size[1] * 2)),
        interpolation=cv2.INTER_CUBIC,
    )
    mask = cv2.copyMakeBorder(mask, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    return Image.fromarray(mask).convert("RGB")


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


async def _run_case(case: PolarCase, output_root: Path, candidate_filter: str = "") -> Dict[str, object]:
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
    _save_image(case_dir / "tight_crop.png", tight_crop)

    polar_raw_source = tight_crop or crop_image
    polar_enhanced_source = extractor._prepare_stamp_crop_for_polar(polar_raw_source)
    red_boost_source = _build_red_boost_source(polar_raw_source)
    _save_image(case_dir / "polar_source.png", polar_enhanced_source)
    _save_image(case_dir / "red_boost_source.png", red_boost_source)

    if polar_enhanced_source is None:
        return {
            "case": case.name,
            "expected": case.expected,
            "current": _extract_texts(current_result),
            "polar_best": [],
            "output_dir": str(case_dir),
            "error": "polar source not available",
        }

    candidates = extractor._build_stamp_polar_variants(
        raw_image=polar_raw_source,
        enhanced_image=polar_enhanced_source,
    )
    candidates.extend(
        _build_rolled_polar_variants(
            extractor=extractor,
            raw_image=polar_raw_source,
            enhanced_image=polar_enhanced_source,
        )
    )
    scored_candidates: List[Dict[str, object]] = []
    needle = str(candidate_filter or "").strip().lower()
    if needle:
        candidates = [(name, image) for name, image in candidates if needle in name.lower()]

    for candidate_name, candidate_image in candidates:
        _save_image(case_dir / f"{candidate_name}.png", candidate_image)
        scored_candidates.append(await _score_polar_candidate(extractor, candidate_name, candidate_image))

    scored_candidates.sort(key=lambda item: tuple(item["score"]), reverse=True)
    best = scored_candidates[0] if scored_candidates else {"texts": [], "candidate": "", "score": (-1, -1, -1.0)}

    red_boost_candidates = extractor._build_stamp_polar_variants(
        raw_image=polar_raw_source,
        enhanced_image=red_boost_source,
    )
    if needle:
        red_boost_candidates = [(name, image) for name, image in red_boost_candidates if needle in name.lower()]
    red_boost_scored: List[Dict[str, object]] = []
    for candidate_name, candidate_image in red_boost_candidates:
        _save_image(case_dir / f"redboost_{candidate_name}.png", candidate_image)
        red_boost_scored.append(await _score_polar_candidate(extractor, f"redboost_{candidate_name}", candidate_image))
    red_boost_scored.sort(key=lambda item: tuple(item["score"]), reverse=True)
    red_best = red_boost_scored[0] if red_boost_scored else {"texts": [], "candidate": "", "score": (-1, -1, -1.0)}

    return {
        "case": case.name,
        "expected": case.expected,
        "current": _extract_texts(current_result),
        "polar_best": list(best.get("texts") or []),
        "polar_candidate": best.get("candidate") or "",
        "polar_score": best.get("score"),
        "red_boost_best": list(red_best.get("texts") or []),
        "red_boost_candidate": red_best.get("candidate") or "",
        "red_boost_score": red_best.get("score"),
        "output_dir": str(case_dir),
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description="企业声明公章 polar 实验")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help=f"case name, available: {', '.join(sorted(CASES))}, default=all",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/tdkx/workspace/tech/debug_cropped/qysm_polar_experiment",
        help="directory for saving experiment images",
    )
    parser.add_argument(
        "--candidate-filter",
        default="",
        help="only run candidates whose name contains this string",
    )
    args = parser.parse_args()

    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    for case in _iter_cases(args.cases or ["all"]):
        summary = await _run_case(case, output_root, candidate_filter=args.candidate_filter)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(_main())
