#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pexpect


def run_ssh(host: str, user: str, password: str, remote_cmd: str, timeout: int = 120) -> str:
    child = pexpect.spawn(
        "ssh",
        ["-o", "StrictHostKeyChecking=no", f"{user}@{host}", remote_cmd],
        encoding="utf-8",
        codec_errors="ignore",
        timeout=timeout,
    )
    idx = child.expect(["password:", pexpect.EOF, pexpect.TIMEOUT])
    if idx == 0:
        child.sendline(password)
        child.expect(pexpect.EOF)
    return child.before


def run_scp(host: str, user: str, password: str, remote_path: str, local_path: str, timeout: int = 600) -> str:
    child = pexpect.spawn(
        "scp",
        ["-r", "-o", "StrictHostKeyChecking=no", f"{user}@{host}:{remote_path}", local_path],
        encoding="utf-8",
        codec_errors="ignore",
        timeout=timeout,
    )
    idx = child.expect(["password:", pexpect.EOF, pexpect.TIMEOUT])
    if idx == 0:
        child.sendline(password)
        child.expect(pexpect.EOF)
    return child.before


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    ssh_parser = subparsers.add_parser("ssh")
    ssh_parser.add_argument("--host", required=True)
    ssh_parser.add_argument("--user", required=True)
    ssh_parser.add_argument("--password", required=True)
    ssh_parser.add_argument("--timeout", type=int, default=120)
    ssh_parser.add_argument("remote_cmd")

    scp_parser = subparsers.add_parser("scp")
    scp_parser.add_argument("--host", required=True)
    scp_parser.add_argument("--user", required=True)
    scp_parser.add_argument("--password", required=True)
    scp_parser.add_argument("--timeout", type=int, default=600)
    scp_parser.add_argument("remote_path")
    scp_parser.add_argument("local_path")

    args = parser.parse_args()
    if args.action == "ssh":
        sys.stdout.write(run_ssh(args.host, args.user, args.password, args.remote_cmd, args.timeout))
        return 0
    if args.action == "scp":
        local_path = Path(args.local_path)
        if local_path.parent != Path("."):
            local_path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout.write(run_scp(args.host, args.user, args.password, args.remote_path, args.local_path, args.timeout))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
