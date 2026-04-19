"""SMB 文件读取器。

用于按 share 内路径或 UNC 路径读取远端文件，供单文档审查接口复用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PureWindowsPath


class SMBConfigurationError(RuntimeError):
    """SMB 配置错误。"""


class SMBFileReadError(RuntimeError):
    """SMB 文件读取失败。"""


@dataclass(slots=True)
class SMBReviewSettings:
    """形式审查 SMB 连接配置。"""

    host: str
    share: str
    username: str
    password: str
    port: int = 445
    base_dir: str = ""

    @classmethod
    def from_env(cls) -> "SMBReviewSettings":
        """从环境变量加载配置。"""
        host = str(os.getenv("REVIEW_SMB_HOST", "")).strip()
        share = str(os.getenv("REVIEW_SMB_SHARE", "")).strip()
        username = str(os.getenv("REVIEW_SMB_USERNAME", "")).strip()
        password = str(os.getenv("REVIEW_SMB_PASSWORD", ""))
        port_raw = str(os.getenv("REVIEW_SMB_PORT", "445")).strip() or "445"
        base_dir = str(os.getenv("REVIEW_SMB_BASE_DIR", "")).strip()

        missing = [
            name
            for name, value in {
                "REVIEW_SMB_HOST": host,
                "REVIEW_SMB_SHARE": share,
                "REVIEW_SMB_USERNAME": username,
                "REVIEW_SMB_PASSWORD": password,
            }.items()
            if value == ""
        ]
        if missing:
            raise SMBConfigurationError(f"缺少 SMB 配置: {', '.join(missing)}")

        try:
            port = int(port_raw)
        except ValueError as exc:
            raise SMBConfigurationError(f"REVIEW_SMB_PORT 非法: {port_raw}") from exc

        return cls(
            host=host,
            share=share,
            username=username,
            password=password,
            port=port,
            base_dir=base_dir,
        )


class SMBReviewFileReader:
    """读取用于形式审查的 SMB 文件。"""

    def __init__(self, settings: SMBReviewSettings | None = None):
        self.settings = settings or SMBReviewSettings.from_env()

    def normalize_share_path(self, file_path: str) -> str:
        """把输入路径标准化为 share 内相对路径。"""
        raw = str(file_path or "").strip()
        if not raw:
            raise SMBFileReadError("file_path 不能为空")

        normalized = raw.replace("/", "\\")
        relative_parts = self._extract_relative_parts(normalized)
        base_parts = self._split_parts(self.settings.base_dir)

        if base_parts and not self._starts_with(relative_parts, base_parts):
            relative_parts = [*base_parts, *relative_parts]

        if not relative_parts:
            raise SMBFileReadError("file_path 未指向具体文件")

        return "\\".join(relative_parts)

    def build_unc_path(self, file_path: str) -> str:
        """构造完整 UNC 路径。"""
        relative_path = self.normalize_share_path(file_path)
        return f"\\\\{self.settings.host}\\{self.settings.share}\\{relative_path}"

    def read_bytes(self, file_path: str) -> bytes:
        """读取远端文件字节。"""
        unc_path = self.build_unc_path(file_path)
        try:
            import smbclient  # type: ignore
        except ModuleNotFoundError as exc:
            raise SMBConfigurationError(
                "缺少 smbprotocol 依赖，请执行 `uv add smbprotocol` 或 `uv sync`"
            ) from exc

        try:
            smbclient.register_session(
                self.settings.host,
                username=self.settings.username,
                password=self.settings.password,
                port=self.settings.port,
            )
            with smbclient.open_file(unc_path, mode="rb") as fp:
                return fp.read()
        except Exception as exc:
            raise SMBFileReadError(f"读取 SMB 文件失败: {unc_path}: {exc}") from exc

    def _extract_relative_parts(self, normalized_path: str) -> list[str]:
        if normalized_path.startswith("\\\\"):
            parts = [part.strip() for part in normalized_path.lstrip("\\").split("\\") if part.strip()]
            if len(parts) < 3:
                raise SMBFileReadError("UNC 路径格式非法")
            host, share = parts[0], parts[1]
            if host.lower() != self.settings.host.lower():
                raise SMBFileReadError(f"SMB 主机不匹配: {host}")
            if share.lower() != self.settings.share.lower():
                raise SMBFileReadError(f"SMB 共享名不匹配: {share}")
            relative_parts = parts[2:]
        else:
            parts = self._split_parts(normalized_path)
            relative_parts = parts
            if len(relative_parts) >= 2 and relative_parts[0].lower() == self.settings.host.lower():
                if relative_parts[1].lower() != self.settings.share.lower():
                    raise SMBFileReadError(f"SMB 共享名不匹配: {relative_parts[1]}")
                relative_parts = relative_parts[2:]
            elif relative_parts and relative_parts[0].lower() == self.settings.share.lower():
                relative_parts = relative_parts[1:]

        self._validate_parts(relative_parts)
        return relative_parts

    @staticmethod
    def _split_parts(value: str) -> list[str]:
        path = PureWindowsPath(str(value or "").replace("/", "\\"))
        parts = [str(part).strip() for part in path.parts if str(part).strip() not in {"", "\\"}]
        return [part for part in parts if part]

    @staticmethod
    def _validate_parts(parts: list[str]) -> None:
        for part in parts:
            if part in {".", ".."}:
                raise SMBFileReadError("file_path 非法，禁止使用相对跳转")

    @staticmethod
    def _starts_with(parts: list[str], prefix: list[str]) -> bool:
        if len(parts) < len(prefix):
            return False
        return [item.lower() for item in parts[: len(prefix)]] == [item.lower() for item in prefix]
