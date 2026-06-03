"""验收文档解析。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.common.file_handler import get_parser

from src.services.accept.models import ParsedAcceptanceBlock, ParsedAcceptanceDocument


PARSER_CACHE_VERSION = "v6-ocr-fallback-without-cv2"


class AcceptanceDocumentParser:
    """基于通用文件解析器的验收文档解析器。"""

    def __init__(self, *, cache_dir: Path | None = None) -> None:
        self._parsers: dict[str, object] = {}
        self._memory_cache: dict[str, ParsedAcceptanceDocument] = {}
        self._cache_dir = cache_dir
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def parse_bytes(
        self,
        *,
        file_data: bytes,
        file_type: str,
        file_name: str = "",
    ) -> ParsedAcceptanceDocument:
        ft = file_type.lower()
        cache_key = self._cache_key(ft, file_data)
        cached = self._load_cached(cache_key)
        if cached is not None:
            return cached.model_copy(update={"file_name": file_name, "file_type": ft}, deep=True)
        if ft not in self._parsers:
            self._parsers[ft] = get_parser(ft)
        parser = self._parsers[ft]
        result = await parser.parse(file_data)
        text_blocks = sorted(
            result.content.text_blocks,
            key=lambda block: (block.page, block.bbox.y, block.bbox.x),
        )
        lines: list[str] = []
        parsed_blocks: list[ParsedAcceptanceBlock] = []
        line_index = 0
        for idx, block in enumerate(text_blocks):
            normalized = self._normalize_line(block.text)
            if not normalized:
                continue
            lines.append(normalized)
            parsed_blocks.append(
                ParsedAcceptanceBlock(
                    block_id=f"b-{idx + 1}",
                    text=normalized,
                    page=int(block.page or 0),
                    bbox=block.bbox,
                    line_index_start=line_index,
                    line_index_end=line_index,
                )
            )
            line_index += 1
        document = ParsedAcceptanceDocument(
            file_name=file_name,
            file_type=ft,
            text="\n".join(lines),
            lines=lines,
            metadata={"pages": result.pages, **(result.metadata or {})},
            blocks=parsed_blocks,
        )
        self._store_cached(cache_key, document)
        return document

    def parse_text(
        self,
        *,
        text: str,
        file_name: str = "",
        file_type: str = "text",
    ) -> ParsedAcceptanceDocument:
        lines = [self._normalize_line(line) for line in text.splitlines()]
        lines = [line for line in lines if line]
        blocks = [
            ParsedAcceptanceBlock(
                block_id=f"b-{idx + 1}",
                text=line,
                page=0,
                bbox=None,
                line_index_start=idx,
                line_index_end=idx,
            )
            for idx, line in enumerate(lines)
        ]
        return ParsedAcceptanceDocument(
            file_name=file_name,
            file_type=file_type,
            text="\n".join(lines),
            lines=lines,
            metadata={},
            blocks=blocks,
        )

    @staticmethod
    def _normalize_line(text: str) -> str:
        return " ".join((text or "").replace("\x00", "").split()).strip()

    @staticmethod
    def _cache_key(file_type: str, file_data: bytes) -> str:
        digest = hashlib.sha1()
        digest.update(PARSER_CACHE_VERSION.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_type.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_data)
        return digest.hexdigest()

    def _load_cached(self, cache_key: str) -> ParsedAcceptanceDocument | None:
        cached = self._memory_cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(deep=True)
        if not self._cache_dir:
            return None
        cache_path = self._cache_dir / f"{cache_key}.json"
        if not cache_path.exists():
            return None
        try:
            cached = ParsedAcceptanceDocument.model_validate(json.loads(cache_path.read_text(encoding="utf-8")))
        except Exception:
            return None
        self._memory_cache[cache_key] = cached
        return cached.model_copy(deep=True)

    def _store_cached(self, cache_key: str, document: ParsedAcceptanceDocument) -> None:
        cached = document.model_copy(deep=True)
        self._memory_cache[cache_key] = cached
        if not self._cache_dir:
            return
        cache_path = self._cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            return
        try:
            cache_path.write_text(cached.model_dump_json(), encoding="utf-8")
        except Exception:
            return
