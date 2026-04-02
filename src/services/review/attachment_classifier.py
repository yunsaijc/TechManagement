"""LLM 辅助的项目附件分类器"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict

import fitz

from src.common.llm import get_default_llm_client
from src.common.review_runtime import ReviewRuntime
from src.common.vision.multimodal import MultimodalLLM
from src.services.review.project_config import (
    ATTACHMENT_FILENAME_HINTS,
    get_attachment_kind_definitions,
    normalize_attachment_doc_kind,
)


class AttachmentClassifier:
    """对项目附件进行预定义类别分类"""

    UNKNOWN_DOC_KIND = "unknown_attachment"
    OTHER_DOC_KIND = "other_supporting_material"

    def __init__(self, llm: Any = None):
        self.llm = llm or get_default_llm_client()
        self.multi_llm = MultimodalLLM(self.llm) if self.llm else None
        self.confidence_threshold = float(ReviewRuntime.ATTACHMENT_CLASSIFY_CONFIDENCE)
        self.pdf_render_zoom = max(1.0, float(ReviewRuntime.ATTACHMENT_PDF_RENDER_ZOOM))
        self.pdf_text_pages = max(1, int(ReviewRuntime.ATTACHMENT_PDF_TEXT_PAGES))
        self.preview_text_limit = max(500, int(ReviewRuntime.ATTACHMENT_PREVIEW_TEXT_LIMIT))
        self.secondary_pdf_sample_pages = 3
        self.cache_dir = Path(ReviewRuntime.ATTACHMENT_CLASSIFY_CACHE_DIR)
        self.cache_version = str(ReviewRuntime.ATTACHMENT_CLASSIFY_CACHE_VERSION)

    async def classify(self, file_path: Path) -> Dict[str, Any]:
        """对单个附件分类"""
        cache_key = self._build_cache_key(file_path)
        cached_result = self._load_cached_result(cache_key)
        if cached_result:
            details = cached_result.get("details", {})
            if isinstance(details, dict):
                details["cache_hit"] = True
            cached_result["details"] = details
            return cached_result

        file_name = file_path.name
        hint_kind, hint_confidence = self._classify_by_filename(file_name)
        preview = self._build_preview(file_path)

        llm_result = {
            "doc_kind": self.UNKNOWN_DOC_KIND,
            "confidence": 0.0,
            "reason": "未执行 LLM 分类",
            "visible_clues": [],
            "raw_response": "",
        }
        llm_error = ""
        secondary_refine = {
            "enabled": bool(preview.get("image_data") and self.multi_llm),
            "applied": False,
            "doc_kind": self.UNKNOWN_DOC_KIND,
            "confidence": 0.0,
            "reason": "",
            "raw_response": "",
            "error": "",
        }

        if preview.get("image_data") and self.multi_llm:
            try:
                prompt = self._build_prompt(
                    file_name=file_name,
                    extracted_text=preview.get("text_excerpt", ""),
                    filename_hint=hint_kind,
                )
                raw_response = await self.multi_llm.analyze_image(preview["image_data"], prompt)
                llm_result = self._parse_llm_response(raw_response)
                llm_result["raw_response"] = raw_response
            except Exception as exc:
                llm_error = str(exc)
                llm_result["reason"] = f"LLM 分类失败: {exc}"

        final_doc_kind = self.UNKNOWN_DOC_KIND
        final_confidence = 0.0
        final_source = "unclassified"
        final_reason = llm_result["reason"]

        llm_doc_kind = llm_result["doc_kind"]
        llm_confidence = llm_result["confidence"]
        if llm_doc_kind != self.UNKNOWN_DOC_KIND and llm_confidence >= self.confidence_threshold:
            final_doc_kind = llm_doc_kind
            final_confidence = llm_confidence
            final_source = "llm"
            final_reason = llm_result["reason"]
        elif hint_kind != self.UNKNOWN_DOC_KIND and not preview.get("image_data"):
            final_doc_kind = hint_kind
            final_confidence = hint_confidence
            final_source = "filename_rule_fallback"
            final_reason = "文件不可预览，按文件名规则回退分类"

        # 若首轮被归为“其他支撑材料”，执行二次细分类复核
        if (
            final_doc_kind == self.OTHER_DOC_KIND
            and preview.get("image_data")
            and self.multi_llm
        ):
            secondary_refine["applied"] = True
            try:
                if file_path.suffix.lower() == ".pdf":
                    sampled_pages = self._build_pdf_secondary_samples(file_path, self.secondary_pdf_sample_pages)
                    secondary_refine["sampled_pages"] = [
                        {"page": item["page"], "error": item.get("error", "")}
                        for item in sampled_pages
                    ]
                    best_doc_kind = final_doc_kind
                    best_confidence = final_confidence
                    best_reason = ""
                    page_candidates = []
                    for sample in sampled_pages:
                        image_data = sample.get("image_data", b"")
                        if not image_data:
                            continue
                        page_prompt = self._build_refine_prompt(
                            file_name=f"{file_name} [page={sample['page']}]",
                            extracted_text=sample.get("text_excerpt", ""),
                        )
                        page_raw = await self.multi_llm.analyze_image(image_data, page_prompt)
                        page_result = self._parse_llm_response(page_raw)
                        page_candidates.append(
                            {
                                "page": sample["page"],
                                "doc_kind": page_result["doc_kind"],
                                "confidence": page_result["confidence"],
                                "reason": page_result["reason"],
                            }
                        )
                        if (
                            page_result["doc_kind"] not in {self.UNKNOWN_DOC_KIND, self.OTHER_DOC_KIND}
                            and page_result["confidence"] > best_confidence
                            and page_result["confidence"] >= self.confidence_threshold
                        ):
                            best_doc_kind = page_result["doc_kind"]
                            best_confidence = page_result["confidence"]
                            best_reason = page_result["reason"]
                    if page_candidates:
                        secondary_refine["page_candidates"] = page_candidates
                        top_page = max(page_candidates, key=lambda item: float(item.get("confidence", 0.0) or 0.0))
                        secondary_refine["doc_kind"] = str(top_page.get("doc_kind", "")).strip() or self.UNKNOWN_DOC_KIND
                        secondary_refine["confidence"] = float(top_page.get("confidence", 0.0) or 0.0)
                        secondary_refine["reason"] = str(top_page.get("reason", "")).strip()
                    if best_doc_kind != final_doc_kind:
                        final_doc_kind = best_doc_kind
                        final_confidence = best_confidence
                        final_source = "llm_secondary_refine_multi_page"
                        final_reason = f"二次多页复核改判：{best_reason}"
                else:
                    refine_prompt = self._build_refine_prompt(
                        file_name=file_name,
                        extracted_text=preview.get("text_excerpt", ""),
                    )
                    refine_raw = await self.multi_llm.analyze_image(preview["image_data"], refine_prompt)
                    refine_result = self._parse_llm_response(refine_raw)
                    secondary_refine.update(
                        {
                            "doc_kind": refine_result["doc_kind"],
                            "confidence": refine_result["confidence"],
                            "reason": refine_result["reason"],
                            "raw_response": refine_raw,
                        }
                    )
                    if (
                        refine_result["doc_kind"] not in {self.UNKNOWN_DOC_KIND, self.OTHER_DOC_KIND}
                        and refine_result["confidence"] >= self.confidence_threshold
                    ):
                        final_doc_kind = refine_result["doc_kind"]
                        final_confidence = refine_result["confidence"]
                        final_source = "llm_secondary_refine"
                        final_reason = f"二次复核改判：{refine_result['reason']}"
            except Exception as exc:
                secondary_refine["error"] = str(exc)

        contains_doc_kinds = self._collect_contains_doc_kinds(
            llm_result=llm_result,
            secondary_refine=secondary_refine,
        )

        result = {
            "doc_kind": final_doc_kind,
            "confidence": final_confidence,
            "source": final_source,
            "reason": final_reason,
            "details": {
                "file_name": file_name,
                "preview_type": preview.get("preview_type", ""),
                "page_count": preview.get("page_count", 0),
                "text_excerpt": preview.get("text_excerpt", ""),
                "filename_hint": {
                    "doc_kind": hint_kind,
                    "confidence": hint_confidence,
                },
                "llm": {
                    "doc_kind": llm_doc_kind,
                    "confidence": llm_confidence,
                    "reason": llm_result["reason"],
                    "visible_clues": llm_result["visible_clues"],
                    "raw_response": llm_result["raw_response"],
                    "error": llm_error,
                },
                "llm_secondary_refine": secondary_refine,
                "contains_doc_kinds": contains_doc_kinds,
                "final_doc_kind": final_doc_kind,
                "final_source": final_source,
                "final_confidence": final_confidence,
                "confidence_threshold": self.confidence_threshold,
                "cache_hit": False,
            },
        }
        self._save_cached_result(cache_key, result)
        return result

    def _build_cache_key(self, file_path: Path) -> str:
        """构建附件分类缓存键"""
        try:
            stat = file_path.stat()
            raw = (
                f"{file_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|"
                f"{self.cache_version}|{self.confidence_threshold}|{self.secondary_pdf_sample_pages}"
            )
        except Exception:
            raw = f"{file_path}|{self.cache_version}|{self.confidence_threshold}|{self.secondary_pdf_sample_pages}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _cache_file_path(self, cache_key: str) -> Path:
        """缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"

    def _load_cached_result(self, cache_key: str) -> Dict[str, Any] | None:
        """读取附件分类缓存"""
        try:
            cache_file = self._cache_file_path(cache_key)
            if not cache_file.exists():
                return None
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_cached_result(self, cache_key: str, result: Dict[str, Any]) -> None:
        """写入附件分类缓存"""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self._cache_file_path(cache_key)
            cache_file.write_text(
                json.dumps(result, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            # 缓存失败不影响主流程
            return

    def _classify_by_filename(self, file_name: str) -> tuple[str, float]:
        """按文件名给出弱提示"""
        normalized = self._normalize_name(file_name)
        if not normalized:
            return self.UNKNOWN_DOC_KIND, 0.0
        for keyword, doc_kind in ATTACHMENT_FILENAME_HINTS:
            if keyword in normalized:
                return doc_kind, 0.95
        return self.UNKNOWN_DOC_KIND, 0.0

    def _build_preview(self, file_path: Path) -> Dict[str, Any]:
        """构造附件预览"""
        suffix = file_path.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            return {
                "image_data": file_path.read_bytes(),
                "preview_type": "image",
                "page_count": 1,
                "text_excerpt": "",
            }

        if suffix == ".pdf":
            try:
                file_data = file_path.read_bytes()
                doc = fitz.open(stream=file_data, filetype="pdf")
                if doc.page_count == 0:
                    doc.close()
                    return {"image_data": b"", "preview_type": "pdf", "page_count": 0, "text_excerpt": ""}

                page_count = doc.page_count
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(self.pdf_render_zoom, self.pdf_render_zoom))
                text_parts = []
                for page_index in range(min(self.pdf_text_pages, page_count)):
                    text = doc.load_page(page_index).get_text("text").strip()
                    if text:
                        text_parts.append(text)
                doc.close()
                return {
                    "image_data": pix.tobytes("png"),
                    "preview_type": "pdf_first_page",
                    "page_count": page_count,
                    "text_excerpt": "\n".join(text_parts)[: self.preview_text_limit],
                }
            except Exception:
                return {"image_data": b"", "preview_type": "pdf_error", "page_count": 0, "text_excerpt": ""}

        return {"image_data": b"", "preview_type": f"unsupported:{suffix or 'unknown'}", "page_count": 0, "text_excerpt": ""}

    def _build_prompt(self, file_name: str, extracted_text: str, filename_hint: str) -> str:
        """构造分类提示词"""
        category_lines = []
        for item in get_attachment_kind_definitions(include_unknown=True):
            category_lines.append(
                f"- {item['doc_kind']}: {item['label']}。{item['description']}"
            )
        categories_text = "\n".join(category_lines)
        filename_hint_text = filename_hint if filename_hint != self.UNKNOWN_DOC_KIND else "无"
        text_excerpt = extracted_text or "无可提取文字"
        return f"""你在做科技项目形式审查附件分类。

请结合附件第一页图像、文件名、可见文字，将该附件归类到一个且仅一个预定义 doc_kind。
不要猜测。无法可靠判断时返回 unknown_attachment。若材料明显属于项目附件但不属于重点材料类别，返回 other_supporting_material。

允许的 doc_kind 如下：
{categories_text}

输出必须是 JSON，不要输出其他内容：
{{
  "doc_kind": "从允许值中选择",
  "confidence": 0.0,
  "reason": "不超过60字，说明判断依据",
  "visible_clues": ["从图像或文字中看到的关键词或版式线索"]
}}

判定要求：
1. `confidence` 取值 0 到 1。
2. 如果只看到普通说明、封面、扫描件片段，不能据此强行归类。
3. 承诺书、协议、许可、推荐函、检索报告、证书类材料应有明显标题或正文线索。
4. 文件名规则提示只能作为弱参考，不能压过图像内容。

文件名：{file_name}
文件名规则提示：{filename_hint_text}
        可提取文字：
{text_excerpt}
"""

    def _build_refine_prompt(self, file_name: str, extracted_text: str) -> str:
        """针对“其他支撑材料”的二次细分类提示词"""
        specific_lines = []
        for item in get_attachment_kind_definitions(include_unknown=False):
            doc_kind = item["doc_kind"]
            if doc_kind in {self.OTHER_DOC_KIND, self.UNKNOWN_DOC_KIND}:
                continue
            specific_lines.append(f"- {doc_kind}: {item['label']}。{item['description']}")
        categories_text = "\n".join(specific_lines)
        text_excerpt = extracted_text or "无可提取文字"
        return f"""你正在做附件“其他支撑材料”的二次细分类复核。

目标：判断该附件是否其实属于某个明确的专项材料类别；若都不满足，再返回 other_supporting_material。

可选 doc_kind：
{categories_text}
- other_supporting_material: 其他支撑材料
- unknown_attachment: 无法判断

输出必须是 JSON：
{{
  "doc_kind": "从可选值中选择一个",
  "confidence": 0.0,
  "reason": "不超过60字，说明依据",
  "visible_clues": ["关键线索"]
}}

要求：
1. 若存在明确标题/章/正文结构可对应某个具体类别，优先返回具体类别。
2. 只有确实无法归入具体类别，才返回 other_supporting_material。
3. 不要基于想象推断。

文件名：{file_name}
可提取文字：
{text_excerpt}
"""

    def _build_pdf_secondary_samples(self, file_path: Path, max_samples: int) -> list[Dict[str, Any]]:
        """针对 PDF 二次复核，抽样多页（首/中/尾）"""
        samples: list[Dict[str, Any]] = []
        try:
            file_data = file_path.read_bytes()
            doc = fitz.open(stream=file_data, filetype="pdf")
            page_count = doc.page_count
            if page_count <= 1:
                doc.close()
                return samples
            candidate_indexes = {0, page_count - 1, page_count // 2}
            ordered_indexes = sorted(candidate_indexes)[: max_samples]
            for page_index in ordered_indexes:
                try:
                    page = doc.load_page(page_index)
                    pix = page.get_pixmap(matrix=fitz.Matrix(self.pdf_render_zoom, self.pdf_render_zoom))
                    text_excerpt = page.get_text("text").strip()[: self.preview_text_limit]
                    samples.append(
                        {
                            "page": page_index + 1,
                            "image_data": pix.tobytes("png"),
                            "text_excerpt": text_excerpt,
                        }
                    )
                except Exception as exc:
                    samples.append({"page": page_index + 1, "image_data": b"", "text_excerpt": "", "error": str(exc)})
            doc.close()
            return samples
        except Exception as exc:
            return [{"page": 0, "image_data": b"", "text_excerpt": "", "error": str(exc)}]

    def _collect_contains_doc_kinds(self, llm_result: Dict[str, Any], secondary_refine: Dict[str, Any]) -> list[str]:
        """聚合单文件内识别到的多类别（用于后续规则判定）"""
        candidates: set[str] = set()
        llm_kind = str(llm_result.get("doc_kind", "")).strip()
        llm_conf = float(llm_result.get("confidence", 0.0) or 0.0)
        if llm_kind and llm_kind not in {self.UNKNOWN_DOC_KIND, self.OTHER_DOC_KIND} and llm_conf >= self.confidence_threshold:
            candidates.add(llm_kind)

        refine_kind = str(secondary_refine.get("doc_kind", "")).strip()
        refine_conf = float(secondary_refine.get("confidence", 0.0) or 0.0)
        if refine_kind and refine_kind not in {self.UNKNOWN_DOC_KIND, self.OTHER_DOC_KIND} and refine_conf >= self.confidence_threshold:
            candidates.add(refine_kind)

        page_candidates = secondary_refine.get("page_candidates", [])
        if isinstance(page_candidates, list):
            for item in page_candidates:
                if not isinstance(item, dict):
                    continue
                page_kind = str(item.get("doc_kind", "")).strip()
                page_conf = float(item.get("confidence", 0.0) or 0.0)
                if page_kind and page_kind not in {self.UNKNOWN_DOC_KIND, self.OTHER_DOC_KIND} and page_conf >= self.confidence_threshold:
                    candidates.add(page_kind)
        return sorted(candidates)

    def _parse_llm_response(self, raw_text: str) -> Dict[str, Any]:
        """解析 LLM 输出"""
        payload = self._extract_json(raw_text)
        data = json.loads(payload) if payload else {}
        doc_kind = normalize_attachment_doc_kind(data.get("doc_kind"))
        confidence = self._normalize_confidence(data.get("confidence"))
        visible_clues = data.get("visible_clues") or []
        if not isinstance(visible_clues, list):
            visible_clues = [str(visible_clues)]
        return {
            "doc_kind": doc_kind,
            "confidence": confidence,
            "reason": str(data.get("reason") or "").strip()[:120] or "模型未提供原因",
            "visible_clues": [str(item).strip()[:80] for item in visible_clues if str(item).strip()][:6],
            "raw_response": raw_text,
        }

    def _extract_json(self, text: str) -> str:
        """从模型输出中提取 JSON"""
        stripped = str(text or "").strip()
        if stripped.startswith("```"):
            parts = stripped.split("```", 2)
            if len(parts) >= 2:
                stripped = parts[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]

        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        return match.group(0) if match else "{}"

    def _normalize_name(self, file_name: str) -> str:
        """归一化文件名"""
        stem = Path(file_name).stem
        text = re.sub(r"[\s_\-.()]+", "", stem)
        if not text:
            return ""
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
            return ""
        return text

    def _normalize_confidence(self, value: Any) -> float:
        """归一化置信度"""
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, round(confidence, 4)))
