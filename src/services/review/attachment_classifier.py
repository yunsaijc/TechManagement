"""LLM 辅助的项目附件分类器"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

import fitz

from src.common.llm import get_default_llm_client
from src.common.vision.multimodal import MultimodalLLM
from src.services.review.project_config import (
    ATTACHMENT_FILENAME_HINTS,
    get_attachment_kind_definitions,
    normalize_attachment_doc_kind,
)


class AttachmentClassifier:
    """对项目附件进行预定义类别分类"""

    UNKNOWN_DOC_KIND = "unknown_attachment"

    def __init__(self, llm: Any = None):
        self.llm = llm or get_default_llm_client()
        self.multi_llm = MultimodalLLM(self.llm) if self.llm else None
        self.confidence_threshold = float(os.getenv("REVIEW_ATTACHMENT_CLASSIFY_CONFIDENCE", "0.70"))

    async def classify(self, file_path: Path) -> Dict[str, Any]:
        """对单个附件分类"""
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

        return {
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
                "final_doc_kind": final_doc_kind,
                "final_source": final_source,
                "final_confidence": final_confidence,
                "confidence_threshold": self.confidence_threshold,
            },
        }

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

                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                text_parts = []
                for page_index in range(min(2, doc.page_count)):
                    text = doc.load_page(page_index).get_text("text").strip()
                    if text:
                        text_parts.append(text)
                doc.close()
                return {
                    "image_data": pix.tobytes("png"),
                    "preview_type": "pdf_first_page",
                    "page_count": len(text_parts) or 1,
                    "text_excerpt": "\n".join(text_parts)[:2500],
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
