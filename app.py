#!/usr/bin/env python3
"""Minimal runtime bootstrap for Komari.

This container does not compile the Go project. It downloads the published
komari release binary for the current architecture and starts it.

Environment variables:
  PORT                 Listening port (default: 25774)
  KOMARI_LISTEN        Bind address, defaults to 0.0.0.0:$PORT
  KOMARI_VERSION       Optional pinned tag, e.g. 1.5.0-fix1; empty/latest => latest release
  KOMARI_DOWNLOAD_URL  Optional direct binary URL
  KOMARI_DATABASE      SQLite file path, default ./data/komari.db
  KOMARI_ARGS          Extra args passed to ./komari server
"""

import json
import os
import platform
import stat
import subprocess
import sys
import urllib.request

REPO = "komari-monitor/komari"
BIN = "./komari"
FALLBACK_VERSION = "1.5.0-fix1"

ARCH_MAP = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "i386": "386",
    "i686": "386",
    "loongarch64": "loong64",
    "riscv64": "riscv64",
}


def detect_arch() -> str:
    return ARCH_MAP.get(platform.machine().lower(), "amd64")


def resolve_version() -> str:
    explicit = os.environ.get("KOMARI_VERSION", "").strip()
    if explicit and explicit != "latest":
        return explicit

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"User-Agent": "komari-bootstrap"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            tag = json.load(resp).get("tag_name")
            return tag or FALLBACK_VERSION
    except Exception:
        return FALLBACK_VERSION


def download_binary() -> None:
    if os.path.exists(BIN):
        print(f"[komari] {BIN} already exists, skip download")
        return

    custom = os.environ.get("KOMARI_DOWNLOAD_URL", "").strip()
    if custom:
        url = custom
    else:
        tag = os.environ.get("KOMARI_VERSION", "").strip()
        if not tag or tag == "latest":
            tag = resolve_version()
        url = f"https://github.com/{REPO}/releases/download/{tag}/komari-linux-{detect_arch()}"

    print(f"[komari] downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "komari-bootstrap"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    if len(data) < 1024 * 1024:
        raise RuntimeError(f"downloaded file too small ({len(data)} bytes)")

    with open(BIN, "wb") as f:
        f.write(data)
    os.chmod(BIN, os.stat(BIN).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"[komari] saved {BIN} ({len(data)} bytes)")


def build_cmd() -> list[str]:
    port = os.environ.get("PORT", "25774").strip()
    listen = os.environ.get("KOMARI_LISTEN", "").strip() or f"0.0.0.0:{port}"
    cmd = [BIN, "server", "--listen", listen]

    database = os.environ.get("KOMARI_DATABASE", "").strip()
    if database:
        cmd += ["--database", database]

    extra = os.environ.get("KOMARI_ARGS", "").strip()
    if extra:
        cmd += extra.split()

    return cmd


def main() -> None:
    download_binary()
    cmd = build_cmd()
    print(f"[komari] starting: {' '.join(cmd)}")
    os.execvp(BIN, cmd)


if __name__ == "__main__":
    main()
