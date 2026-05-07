#!/usr/bin/env python3
"""旁路实验：对比当前通用公章识别和实验变体链公章识别。

不改主链路，只读取样例文件并输出两套识别结果：
- current: 现在线上使用的 StampExtractor.extract()
- experimental: 复用现有 enhanced/tight/polar 变体链
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.extractors.stamp import StampExtractor
from src.services.review.agent import ReviewAgent
from src.services.review.smb_file_reader import SMBReviewFileReader


@dataclass(frozen=True)
class StampCase:
    name: str
    label: str
    file_path: str
    crop_box: Tuple[float, float, float, float]
    role_key: str
    expected: str = ""


CASES: Dict[str, StampCase] = {
    "dywcdwcns_stamp": StampCase(
        name="dywcdwcns_stamp",
        label="第一完成单位承诺书公章",
        file_path=r"FJCL\static\rpw\zmcl2025\2025-113-4010\1757993455092.pdf",
        crop_box=(0.34, 0.52, 0.82, 0.86),
        role_key="dywcdwcns",
        expected="河北雄安轨道快线有限责任公司",
    ),
    "qysm_company_stamp": StampCase(
        name="qysm_company_stamp",
        label="企业声明企业公章",
        file_path=r"FJCL\static\rpw\zmcl2025\2025-109-6001\1763603584754.PDF",
        crop_box=(0.45, 0.44, 0.88, 0.82),
        role_key="enterprise",
        expected="润泽智算科技集团股份有限公司",
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


def _save_image(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


async def _run_case(case: StampCase, output_root: Path) -> Dict[str, object]:
    reader = SMBReviewFileReader()
    agent = ReviewAgent()
    extractor = StampExtractor()

    file_data = reader.read_bytes(case.file_path)
    page_data = agent._pdf_to_image(file_data)
    page_image = Image.open(io.BytesIO(page_data)).convert("RGB")
    crop_image = agent._crop_ratio_image(page_image, case.crop_box)
    crop_bytes = agent._image_to_png_bytes(crop_image)

    case_dir = output_root / case.name
    _save_image(case_dir / "page1.png", page_image)
    _save_image(case_dir / "crop.png", crop_image)

    current_result = await extractor.extract(crop_bytes)
    current_result = current_result or {"stamps": []}

    variant_bundle = extractor._build_stamp_ocr_variants(crop_image, role_key=case.role_key)
    for variant_name, variant_bytes in list(variant_bundle.get("variants", []) or []):
        try:
            variant_image = Image.open(io.BytesIO(variant_bytes)).convert("RGB")
            _save_image(case_dir / f"{variant_name}.png", variant_image)
        except Exception:
            pass

    experimental_result = await extractor._qwen_extract_stamps_from_variants(
        variants=list(variant_bundle.get("variants", []) or []),
        region_name=case.label,
        role_key=case.role_key,
        polar_raw_source=variant_bundle.get("polar_raw_source"),
        polar_enhanced_source=variant_bundle.get("polar_enhanced_source"),
        polar_source_variant=str(variant_bundle.get("polar_source_variant") or ""),
    )

    summary = {
        "case": case.name,
        "label": case.label,
        "expected": case.expected,
        "current": {
            "texts": _extract_texts(current_result),
            "stamps": current_result.get("stamps", []),
        },
        "experimental": {
            "texts": _extract_texts(experimental_result),
            "stamps": experimental_result.get("stamps", []),
            "variant": experimental_result.get("variant", ""),
        },
        "output_dir": str(case_dir),
    }
    return summary


def _iter_cases(names: Iterable[str]) -> List[StampCase]:
    resolved: List[StampCase] = []
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


async def _main() -> None:
    parser = argparse.ArgumentParser(description="旁路对比当前/实验公章识别")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help=f"case name, available: {', '.join(sorted(CASES))}, default=all",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/tdkx/workspace/tech/debug_cropped/stamp_ab",
        help="directory for saving crop/page images",
    )
    args = parser.parse_args()

    case_names = args.cases or ["all"]
    cases = _iter_cases(case_names)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    for case in cases:
        summary = await _run_case(case, output_root)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(_main())
