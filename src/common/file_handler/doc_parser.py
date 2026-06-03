"""Legacy Word `.doc` parser."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import BoundingBox, DocumentContent, TextBlock


class DOCParser(BaseFileParser):
    """Parse legacy `.doc` files.

    Preferred flow:
    1) Convert `.doc` -> `.docx` via LibreOffice/soffice
    2) Reuse DOCX parser (better structure and Chinese stability)
    3) Fallback to txt extraction and strings when conversion fails
    """

    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        # 主路径：先转 docx，再交给 DOCXParser，避免历史 .doc 解析时中文丢失。
        converted_docx = await asyncio.to_thread(self._convert_doc_to_docx, file_data)
        if converted_docx:
            from src.common.file_handler.docx_parser import DOCXParser

            docx_result = await DOCXParser().parse(converted_docx, **kwargs)
            metadata = dict(docx_result.metadata or {})
            metadata["parser"] = "soffice_docx"
            return ParseResult(
                content=docx_result.content,
                pages=docx_result.pages,
                metadata=metadata,
            )

        # 兜底路径：保持原有 txt/strings 策略，避免转换失败时完全不可用。
        text = await asyncio.to_thread(self._extract_text, file_data)
        parser_name = getattr(self, "_last_parser_name", "unknown")

        text_blocks: list[TextBlock] = []
        y_cursor = 0.0
        for line in text.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            text_blocks.append(
                TextBlock(
                    text=cleaned,
                    bbox=BoundingBox(x=0, y=y_cursor, width=0, height=20),
                    page=0,
                )
            )
            y_cursor += 20

        return ParseResult(
            content=DocumentContent(text_blocks=text_blocks),
            pages=1,
            metadata={
                "parser": parser_name,
                "total_blocks": len(text_blocks),
            },
        )

    async def extract_images(self, file_data: bytes) -> List[bytes]:
        return []

    def _convert_doc_to_docx(self, file_data: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="doc_convert_") as temp_dir:
            temp_root = Path(temp_dir)
            src_path = temp_root / "input.doc"
            src_path.write_bytes(file_data)

            home_dir = temp_root / "lo_home"
            profile_dir = temp_root / "lo_profile"
            out_dir = temp_root / "lo_out"
            home_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["HOME"] = str(home_dir)
            env["XDG_CONFIG_HOME"] = str(home_dir / ".config")
            env["XDG_CACHE_HOME"] = str(home_dir / ".cache")
            env["XDG_RUNTIME_DIR"] = str(home_dir / ".run")
            for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
                Path(env[key]).mkdir(parents=True, exist_ok=True)

            office_bin = shutil.which("libreoffice") or shutil.which("soffice")
            if not office_bin:
                return b""

            proc = subprocess.run(
                [
                    office_bin,
                    f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nolockcheck",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(out_dir),
                    str(src_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            if proc.returncode != 0:
                return b""

            docx_path = out_dir / "input.docx"
            if not docx_path.is_file():
                candidates = sorted(out_dir.glob("*.docx"))
                if candidates:
                    docx_path = candidates[0]
            if not docx_path.is_file():
                return b""
            return docx_path.read_bytes()

    def _extract_text(self, file_data: bytes) -> str:
        with tempfile.TemporaryDirectory(prefix="doc_parse_") as temp_dir:
            temp_root = Path(temp_dir)
            src_path = temp_root / "input.doc"
            src_path.write_bytes(file_data)
            txt = self._extract_text_via_soffice(src_path, temp_root)
            if txt.strip():
                self._last_parser_name = "soffice_txt"
                return txt

            txt = self._extract_text_via_strings(src_path)
            if txt.strip():
                self._last_parser_name = "strings_utf16"
                return txt

            raise RuntimeError("未能从 .doc 文件提取有效文本")

    def _extract_text_via_soffice(self, src_path: Path, temp_root: Path) -> str:
        home_dir = temp_root / "lo_home"
        profile_dir = temp_root / "lo_profile"
        out_dir = temp_root / "lo_out"
        home_dir.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        env["XDG_CONFIG_HOME"] = str(home_dir / ".config")
        env["XDG_CACHE_HOME"] = str(home_dir / ".cache")
        env["XDG_RUNTIME_DIR"] = str(home_dir / ".run")
        for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(
            [
                "soffice",
                f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--nodefault",
                "--nofirststartwizard",
                "--convert-to",
                "txt:Text",
                "--outdir",
                str(out_dir),
                str(src_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            return ""

        txt_path = out_dir / "input.txt"
        if not txt_path.is_file():
            candidates = sorted(out_dir.glob("*.txt"))
            if candidates:
                txt_path = candidates[0]
        if not txt_path.is_file():
            return ""

        raw = txt_path.read_bytes()
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "utf-16", "utf-16le", "latin1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")

    def _extract_text_via_strings(self, src_path: Path) -> str:
        if not shutil.which("strings"):
            return ""

        commands = [
            ["strings", "-el", "-n", "4", str(src_path)],
            ["strings", "-n", "8", str(src_path)],
        ]
        lines: list[str] = []
        seen: set[str] = set()
        for cmd in commands:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="ignore",
            )
            if proc.returncode != 0:
                continue
            for raw_line in proc.stdout.splitlines():
                cleaned = self._normalize_extracted_line(raw_line)
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                lines.append(cleaned)

        return "\n".join(lines)

    def _normalize_extracted_line(self, line: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(line or "").strip())
        if len(cleaned) < 2:
            return ""
        if self._junk_line(cleaned):
            return ""
        return cleaned

    def _junk_line(self, line: str) -> bool:
        lower = line.lower()
        if lower in {"msworddoc", "word.document.8", "microsoft office word"}:
            return True
        if lower.startswith("urn:schemas-microsoft-com:office:smarttags"):
            return True
        alpha_num = sum(ch.isalnum() for ch in line)
        punctuation = sum(not ch.isalnum() and not ch.isspace() for ch in line)
        if alpha_num == 0:
            return True
        if punctuation > alpha_num * 2:
            return True
        if len(line) >= 8 and len(set(line)) <= 3:
            return True
        return False
