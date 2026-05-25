#!/usr/bin/env python3
"""Side experiment for tjdwyj stamp extraction.

This does not touch the main review flow. It reads selected PDFs, crops the
bottom-right stamp area, saves debug images, runs current stamp OCR on the crop,
and asks a targeted multimodal yes/no check against DB target unit.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import cv2
import fitz
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.extractors import StampExtractor
from src.services.review.agent import ReviewAgent
from src.services.review.reward_review_service import RewardReviewService
from src.services.review.smb_file_reader import SMBReviewFileReader


DEFAULT_CASE_IDS = [
    "tjdwyj_202540615_1757995952930_228a4bec",
    "tjdwyj_202540398_1757384100070_34ae5167",
    "tjdwyj_202540347_1757579792080_7bdb8e4c",
    "tjdwyj_202540750_1758003823130_2b6607f1",
]


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    return {
        row["case_id"]: row
        for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    }


def _extract_texts(result: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for item in result.get("stamps") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("unit") or item.get("text") or "").strip()
        if text and text not in texts:
            texts.append(text)
    return texts


def _pdf_page_image(file_data: bytes, zoom: float = 2.0) -> Image.Image:
    doc = fitz.open(stream=file_data, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _crop_ratio(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    x1, y1, x2, y2 = box
    return image.crop((int(width * x1), int(height * y1), int(width * x2), int(height * y2)))


def _red_enhance(image: Image.Image) -> Image.Image:
    rgb = np.array(image.convert("RGB"))
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    mask = (r > 110) & (r - g > 25) & (r - b > 25)
    out = np.full_like(rgb, 255)
    out[mask] = [220, 0, 0]
    mask_u8 = (mask.astype(np.uint8) * 255)
    kernel = np.ones((2, 2), np.uint8)
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask_u8 = cv2.dilate(mask_u8, kernel, iterations=1)
    out[mask_u8 > 0] = [220, 0, 0]
    return Image.fromarray(out)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _normalize_unit_text(value: str) -> str:
    return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/\"'“”‘’]", "", str(value or "")).lower()


def _edit_similarity(left: str, right: str) -> float:
    left_norm = _normalize_unit_text(left)
    right_norm = _normalize_unit_text(right)
    if not left_norm or not right_norm:
        return 0.0
    previous = list(range(len(right_norm) + 1))
    for i, left_char in enumerate(left_norm, start=1):
        current = [i] + [0] * len(right_norm)
        for j, right_char in enumerate(right_norm, start=1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (0 if left_char == right_char else 1),
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left_norm), len(right_norm), 1)


def _best_similarity(expected: str, texts: list[str]) -> tuple[float, str]:
    best_score = 0.0
    best_text = ""
    for text in texts:
        score = _edit_similarity(expected, text)
        if score > best_score:
            best_score = score
            best_text = text
    return best_score, best_text


async def _verify_crop(agent: ReviewAgent, crop: Image.Image, expected_unit: str) -> dict[str, str]:
    from langchain_core.messages import HumanMessage

    if not expected_unit:
        return {"status": "uncertain", "reason": "empty target"}
    content = [
        {
            "type": "text",
            "text": (
                "你在做提名意见表公章定向核验。\n"
                f"目标提名单位：{expected_unit}\n"
                "图中是页面右下角提名单位（公章）附近裁剪区域。"
                "只判断红色公章上的单位名称是否就是目标提名单位，不要根据正文或表格字段补全。"
                "能确认一致返回 yes，能确认不一致返回 no，看不清返回 uncertain。"
                "严格返回 JSON：{\"nomination_unit_stamp\": {\"status\": \"yes|no|uncertain\", \"reason\": \"\"}}"
            ),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,"
                + __import__("base64").b64encode(agent._compress_image_for_llm(_png_bytes(crop))).decode("utf-8")
            },
        },
    ]
    raw = await asyncio.wait_for(agent.llm.ainvoke([HumanMessage(content=content)]), timeout=45)
    text = raw.content if hasattr(raw, "content") else str(raw)
    match = re.search(r"\{.*\}", str(text), re.S)
    if not match:
        return {"status": "uncertain", "reason": str(text)[:200]}
    try:
        payload = json.loads(match.group(0))
    except Exception:
        return {"status": "uncertain", "reason": str(text)[:200]}
    item = payload.get("nomination_unit_stamp") or {}
    return {
        "status": str(item.get("status") or "").strip(),
        "reason": str(item.get("reason") or "").strip(),
    }


async def _run_case(case: dict[str, Any], output_root: Path) -> dict[str, Any]:
    reader = SMBReviewFileReader()
    reward_service = RewardReviewService()
    agent = ReviewAgent()
    extractor = StampExtractor()

    context = reward_service.build_context(case["project_id"], case["file_path"], case["doc_type"])
    expected_unit = str((context.get("target_values") or {}).get("nomination_unit_name") or "")
    file_data = reader.read_bytes(case["file_path"])
    page = _pdf_page_image(file_data, zoom=2.0)

    # Right-bottom form area containing "提名单位（公章）".
    crop = _crop_ratio(page, (0.48, 0.68, 0.96, 0.96))
    crop_wide = _crop_ratio(page, (0.36, 0.62, 0.98, 0.98))
    enhanced = _red_enhance(crop)
    stamp_quality = agent._analyze_red_stamp_quality(crop_wide)

    case_dir = output_root / str(case["case_id"])
    case_dir.mkdir(parents=True, exist_ok=True)
    page.save(case_dir / "source_page.png")
    crop.save(case_dir / "stamp_crop.png")
    crop_wide.save(case_dir / "stamp_crop_wide.png")
    enhanced.save(case_dir / "stamp_red_enhanced.png")

    current_crop = await agent._extract_stamps_from_image(crop, debug_prefix="")
    current_wide = await agent._extract_stamps_from_image(crop_wide, debug_prefix="")
    current_enhanced = await agent._extract_stamps_from_image(enhanced, debug_prefix="")
    verification = await _verify_crop(agent, crop, expected_unit)
    all_texts = _extract_texts(current_enhanced) or _extract_texts(current_crop) or _extract_texts(current_wide)
    best_score, best_text = _best_similarity(expected_unit, all_texts)
    verification_reason = str(verification.get("reason") or "")
    verification_status = str(verification.get("status") or "")
    verification_self_conflict = verification_status == "no" and (
        "一致" in verification_reason and "不一致" not in verification_reason
    )
    if expected_unit and _normalize_unit_text(expected_unit) in [_normalize_unit_text(text) for text in all_texts]:
        suggested_status = "passed"
        suggested_reason = "stamp text exactly matched expected unit"
    elif best_score >= 0.88 and not stamp_quality.get("low_quality"):
        suggested_status = "passed"
        suggested_reason = f"stamp text is highly similar to expected unit: {best_text} ({best_score:.3f})"
    elif verification_self_conflict and best_score >= 0.75 and not stamp_quality.get("low_quality"):
        suggested_status = "passed"
        suggested_reason = f"verification status conflicts with its reason; OCR supports expected unit: {best_text} ({best_score:.3f})"
    elif stamp_quality.get("red_present") and stamp_quality.get("low_quality"):
        suggested_status = "warning"
        suggested_reason = "red stamp exists but quality is too low for reliable OCR"
    elif verification.get("status") == "yes" and not all_texts:
        suggested_status = "warning"
        suggested_reason = "visual verification sees target stamp but OCR has no supporting text"
    elif verification.get("status") == "no":
        suggested_status = "failed"
        suggested_reason = "visual verification says target stamp is absent or inconsistent"
    else:
        suggested_status = "warning"
        suggested_reason = "stamp result is uncertain"

    return {
        "case_id": case["case_id"],
        "project_id": case["project_id"],
        "file_path": case["file_path"],
        "expected_unit": expected_unit,
        "context_errors": context.get("errors") or [],
        "crop_texts": _extract_texts(current_crop),
        "wide_texts": _extract_texts(current_wide),
        "enhanced_texts": _extract_texts(current_enhanced),
        "stamp_quality": stamp_quality,
        "verification": verification,
        "best_text": best_text,
        "best_similarity": round(best_score, 4),
        "verification_self_conflict": verification_self_conflict,
        "suggested_status": suggested_status,
        "suggested_reason": suggested_reason,
        "output_dir": str(case_dir),
    }


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="data/review_tests/cases.jsonl")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--output-dir", default="debug_cropped/tjdwyj_stamp_experiment")
    args = parser.parse_args()

    cases_by_id = _load_cases(Path(args.cases))
    case_ids = args.case_id or DEFAULT_CASE_IDS
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    results = []
    for case_id in case_ids:
        case = cases_by_id[case_id]
        result = await _run_case(case, output_root)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    (output_root / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(_main())
