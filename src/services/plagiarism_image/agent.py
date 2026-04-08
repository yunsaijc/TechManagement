"""Orchestrator for image plagiarism checks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

from .config import IMAGE_PLAGIARISM_DEBUG_ROOT
from .corpus import ImageCorpusManager
from .extractor import extract_images_from_file
from .hashing import ImageHasher
from .matcher import ImageMatcher, MatchConfig
from .report_builder import ImageReportBuilder
from .schemas import ImageAsset, ImageMatch


class ImagePlagiarismAgent:
    def __init__(
        self,
        high_score: float,
        medium_score: float,
        hash_hamming_max: int,
        min_inliers_high: int,
        include_low: bool = False,
        max_images_per_doc: int = 40,
    ) -> None:
        self.hasher = ImageHasher()
        self.matcher = ImageMatcher(
            MatchConfig(
                hash_hamming_max=hash_hamming_max,
                high_score=high_score,
                medium_score=medium_score,
                min_inliers_high=min_inliers_high,
            )
        )
        self.report_builder = ImageReportBuilder()
        self.include_low = include_low
        self.max_images_per_doc = max(1, max_images_per_doc)

    def check_documents(
        self,
        files: List[Tuple[str, str, bytes]],
        debug: bool = False,
        debug_output_dir: Path | None = None,
        debug_output_html: Path | None = None,
        max_pair_checks: int = 120000,
    ) -> Dict:
        assets_by_doc: Dict[str, List[ImageAsset]] = {}
        warnings: List[Dict] = []

        for doc_id, file_name, file_data in files:
            try:
                assets = extract_images_from_file(doc_id=doc_id, file_name=file_name, file_data=file_data)
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append({"doc_id": doc_id, "error": f"extract_failed: {exc}"})
                assets = []
            if len(assets) > self.max_images_per_doc:
                assets = assets[: self.max_images_per_doc]
                warnings.append({"doc_id": doc_id, "warning": f"images_truncated_to_{self.max_images_per_doc}"})
            assets_by_doc[doc_id] = assets

        # Build fingerprints once.
        runtime_fp: Dict[str, object] = {}
        for doc_id, assets in assets_by_doc.items():
            for asset in assets:
                fp = self.hasher.build(asset)
                if fp is None:
                    warnings.append({"doc_id": doc_id, "image_id": asset.image_id, "warning": "fingerprint_failed"})
                    continue
                runtime_fp[asset.image_id] = fp

        doc_ids = list(assets_by_doc.keys())
        matches: List[ImageMatch] = []
        checked = 0

        # Compare directed pairs: each doc as query against all other docs.
        for query_doc in doc_ids:
            query_assets = [a for a in assets_by_doc.get(query_doc, []) if a.image_id in runtime_fp]
            if not query_assets:
                continue
            for source_doc in doc_ids:
                if source_doc == query_doc:
                    continue
                source_assets = [a for a in assets_by_doc.get(source_doc, []) if a.image_id in runtime_fp]
                if not source_assets:
                    continue

                # Keep best match per query image -> source doc.
                best_by_query_img: Dict[str, ImageMatch] = {}
                for q in query_assets:
                    for s in source_assets:
                        if checked >= max_pair_checks:
                            warnings.append({"warning": "max_pair_checks_reached", "max_pair_checks": max_pair_checks})
                            break
                        checked += 1

                        area_ratio = (q.width * q.height) / max(1.0, float(s.width * s.height))
                        if area_ratio < 0.25 or area_ratio > 4.0:
                            continue

                        m = self.matcher.compare(
                            query_asset=q,
                            source_asset=s,
                            query_fp=runtime_fp[q.image_id],
                            source_fp=runtime_fp[s.image_id],
                        )
                        if m is None:
                            continue
                        if not self.include_low and m.level == "low":
                            continue

                        prev = best_by_query_img.get(q.image_id)
                        if prev is None or m.score > prev.score:
                            best_by_query_img[q.image_id] = m
                    if checked >= max_pair_checks:
                        break

                matches.extend(best_by_query_img.values())
                if checked >= max_pair_checks:
                    break
            if checked >= max_pair_checks:
                break

        # De-duplicate fully identical rows.
        dedup: Dict[Tuple[str, str, str, str], ImageMatch] = {}
        for m in matches:
            key = (m.query_doc, m.query_image_id, m.source_doc, m.source_image_id)
            if key not in dedup or dedup[key].score < m.score:
                dedup[key] = m
        final_matches = sorted(
            dedup.values(),
            key=lambda x: (x.query_doc, -x.score, x.source_doc, x.query_image_id),
        )

        level_count = defaultdict(int)
        for m in final_matches:
            level_count[m.level] += 1

        report_path = None
        if debug:
            out_dir = debug_output_dir or IMAGE_PLAGIARISM_DEBUG_ROOT
            output_html = debug_output_html or (out_dir / "plagiarism_image_report.html")
            image_bytes_map: Dict[str, bytes] = {}
            for assets in assets_by_doc.values():
                for asset in assets:
                    image_bytes_map[asset.image_id] = asset.image_bytes
            report_path = self.report_builder.build(
                title="图片查重报告",
                matches=final_matches,
                output_html_path=output_html,
                image_bytes_map=image_bytes_map,
            )

        return {
            "documents": len(doc_ids),
            "images": sum(len(v) for v in assets_by_doc.values()),
            "fingerprinted_images": len(runtime_fp),
            "pair_checks": checked,
            "matches": [asdict(m) for m in final_matches],
            "level_count": dict(level_count),
            "warnings": warnings,
            "debug_report_path": str(report_path) if report_path else None,
        }

    def check_documents_against_corpus(
        self,
        files: List[Tuple[str, str, bytes]],
        corpus_manager: ImageCorpusManager,
        debug: bool = False,
        debug_output_dir: Path | None = None,
        debug_output_html: Path | None = None,
        hash_hamming_max: int = 18,
        top_k_coarse: int = 80,
        top_k_final: int = 8,
        max_pair_checks: int = 120000,
    ) -> Dict:
        assets_by_doc: Dict[str, List[ImageAsset]] = {}
        warnings: List[Dict] = []
        runtime_fp: Dict[str, object] = {}

        for doc_id, file_name, file_data in files:
            try:
                assets = extract_images_from_file(doc_id=doc_id, file_name=file_name, file_data=file_data)
            except Exception as exc:
                warnings.append({"doc_id": doc_id, "error": f"extract_failed: {exc}"})
                assets = []
            if len(assets) > self.max_images_per_doc:
                assets = assets[: self.max_images_per_doc]
                warnings.append({"doc_id": doc_id, "warning": f"images_truncated_to_{self.max_images_per_doc}"})
            assets_by_doc[doc_id] = assets
            for asset in assets:
                fp = self.hasher.build(asset)
                if fp is None:
                    warnings.append({"doc_id": doc_id, "image_id": asset.image_id, "warning": "fingerprint_failed"})
                    continue
                runtime_fp[asset.image_id] = fp

        matches: List[ImageMatch] = []
        pair_checks = 0
        hard_stop = False

        for doc_id, assets in assets_by_doc.items():
            if hard_stop:
                break
            for asset in assets:
                if hard_stop:
                    break
                fp = runtime_fp.get(asset.image_id)
                if fp is None:
                    continue
                candidates = corpus_manager.retrieve_matches_for_query_image(
                    query_asset=asset,
                    query_fp=fp,
                    matcher=self.matcher,
                    include_low=self.include_low,
                    hash_hamming_max=hash_hamming_max,
                    top_k_coarse=top_k_coarse,
                    top_k_final=top_k_final,
                    exclude_doc_id=doc_id,
                )
                pair_checks += int(top_k_coarse)
                if pair_checks >= max_pair_checks:
                    warnings.append({"warning": "max_pair_checks_reached", "max_pair_checks": max_pair_checks})
                    hard_stop = True
                    break
                matches.extend(candidates)

        dedup: Dict[Tuple[str, str, str, str], ImageMatch] = {}
        for m in matches:
            key = (m.query_doc, m.query_image_id, m.source_doc, m.source_image_id)
            if key not in dedup or dedup[key].score < m.score:
                dedup[key] = m
        final_matches = sorted(
            dedup.values(),
            key=lambda x: (x.query_doc, -x.score, x.source_doc, x.query_image_id),
        )

        level_count = defaultdict(int)
        for m in final_matches:
            level_count[m.level] += 1

        report_path = None
        if debug:
            out_dir = debug_output_dir or IMAGE_PLAGIARISM_DEBUG_ROOT
            output_html = debug_output_html or (out_dir / "plagiarism_image_report.html")
            image_bytes_map: Dict[str, bytes] = {}
            for assets in assets_by_doc.values():
                for asset in assets:
                    image_bytes_map[asset.image_id] = asset.image_bytes
            for item in final_matches:
                if item.source_image_id in image_bytes_map:
                    continue
                src_bytes = corpus_manager.get_image_bytes(item.source_image_id)
                if src_bytes:
                    image_bytes_map[item.source_image_id] = src_bytes
            report_path = self.report_builder.build(
                title="图片查重报告",
                matches=final_matches,
                output_html_path=output_html,
                image_bytes_map=image_bytes_map,
            )

        return {
            "documents": len(assets_by_doc),
            "images": sum(len(v) for v in assets_by_doc.values()),
            "fingerprinted_images": len(runtime_fp),
            "pair_checks": pair_checks,
            "matches": [asdict(m) for m in final_matches],
            "level_count": dict(level_count),
            "warnings": warnings,
            "debug_report_path": str(report_path) if report_path else None,
        }
