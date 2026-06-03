"""验收证据归一化。"""
from __future__ import annotations

import re
import unicodedata

from src.services.accept.models import AttachmentEvidence


SUBJECT_SCOPE_ALIASES = {
    "项目承担单位": ("承担单位", "项目承担单位", "申报单位"),
    "项目参与单位": ("参与单位", "协作单位", "合作单位"),
    "项目组": ("项目组", "课题组"),
}

FULLWIDTH_SPACE_PATTERN = re.compile(r"[\u3000\s]+")
ARTIFACT_CLEAN_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
YEAR_PATTERN = re.compile(r"(20\d{2})")

CURRENCY_UNIT_SCALE = {
    "元": 1.0,
    "万元": 10_000.0,
    "亿元": 100_000_000.0,
}


class EvidenceNormalizer:
    """统一证据口径，便于跨文档去重和数值比较。"""

    def normalize(self, items: list[AttachmentEvidence]) -> list[AttachmentEvidence]:
        normalized: list[AttachmentEvidence] = []
        for item in items:
            normalized.append(
                item.model_copy(
                    update={
                        "subject_scope": self.normalize_subject_scope(item.subject_scope),
                        "time_label": self.normalize_time_label(item.time_label),
                        "caliber_label": self.normalize_token_label(item.caliber_label),
                        "metric_variant": self.normalize_metric_variant(item.metric_variant),
                        "normalized_value": self.normalize_value(item.value, item.unit),
                        "normalized_unit": self.normalize_unit(item.unit),
                        "normalized_artifact_key": self.normalize_artifact_key(item.artifact_key or item.artifact_title),
                    }
                )
            )
        return normalized

    def normalize_value(self, value: float | None, unit: str) -> float | None:
        if value is None:
            return None
        normalized_unit = self.normalize_unit(unit)
        if normalized_unit in CURRENCY_UNIT_SCALE:
            return value * CURRENCY_UNIT_SCALE[normalized_unit]
        return value

    def convert_value(self, value: float, from_unit: str, to_unit: str) -> float:
        from_normalized = self.normalize_unit(from_unit)
        to_normalized = self.normalize_unit(to_unit)
        if from_normalized == to_normalized:
            return value
        if from_normalized in CURRENCY_UNIT_SCALE and to_normalized in CURRENCY_UNIT_SCALE:
            base_value = value * CURRENCY_UNIT_SCALE[from_normalized]
            return base_value / CURRENCY_UNIT_SCALE[to_normalized]
        return value

    def normalize_unit(self, unit: str) -> str:
        text = (unit or "").strip()
        if text in CURRENCY_UNIT_SCALE:
            return text
        if text in {"件", "项", "个"}:
            return "项"
        if text in {"人", "名"}:
            return "名"
        if text in {"篇", "份", "场", "次", "人次"}:
            return text
        return text

    def normalize_subject_scope(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        for canonical, aliases in SUBJECT_SCOPE_ALIASES.items():
            if any(alias in text for alias in aliases):
                return canonical
        return text

    def normalize_time_label(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        year_match = YEAR_PATTERN.search(text)
        if year_match:
            year = year_match.group(1)
            if "当年" in text:
                return f"{year}年/当年"
            return f"{year}年"
        return text

    def normalize_metric_variant(self, value: str) -> str:
        return self.normalize_token_label(value)

    def normalize_token_label(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        parts = [
            token.strip()
            for token in re.split(r"[／/\s]+", text)
            if token.strip()
        ]
        return " / ".join(dict.fromkeys(parts))

    def normalize_artifact_key(self, value: str) -> str:
        text = unicodedata.normalize("NFKC", value or "")
        text = FULLWIDTH_SPACE_PATTERN.sub("", text)
        text = text.replace("萦", "荧")
        text = text.replace("Ａ", "A").replace("Ｂ", "B").replace("Ｃ", "C").replace("Ｄ", "D")
        text = self._strip_publication_suffix(text)
        text = ARTIFACT_CLEAN_PATTERN.sub("", text)
        return text.upper()

    def _strip_publication_suffix(self, text: str) -> str:
        suffix_markers = (
            "光学学报",
            "光谱学与光谱分析",
            "计量学报",
            "仪器仪表学报",
            "Applied Spectroscopy",
            "Spectrochimica Acta",
            "Biomolecular Spectroscopy",
            "Journal",
            "Acta",
            "Spectroscopy",
            "中文核心",
            "SCI",
            "EI",
            "核心",
        )
        cut_at = None
        for marker in suffix_markers:
            idx = text.find(marker)
            if idx > 8 and (cut_at is None or idx < cut_at):
                cut_at = idx
        if cut_at is not None:
            text = text[:cut_at]
        text = re.sub(r"\[(?:J|P|D)\]\.?$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"(?:\(|（)\s*(?:SCI|EI|CSCD|核心).*?$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", "", text)
        return text
