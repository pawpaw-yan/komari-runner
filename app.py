#!/usr/bin/env python3
"""Minimal runtime bootstrap for Komari.

This container does not compile the Go project. It downloads the published
komari release binary for the current architecture, starts it bound to the
loopback interface, and proxies every plausible platform gateway port to it.

Why the proxy: container platforms route their edge gateway to a fixed port
(often 8080/3000) or to $PORT, sometimes dialing the IPv6 loopback. Komari
can only bind one address, so we can't know which port the gateway dials.
raw TCP forwarding keeps WebSocket (agent connections) working.

Environment variables:
  PORT                 Primary listening port (default: 8080)
  KOMARI_LISTEN        Komari bind address, defaults to 127.0.0.1:$PORT
  KOMARI_VERSION       Optional pinned tag, e.g. 1.6.1; empty/latest => latest release
  KOMARI_DOWNLOAD_URL  Optional direct binary URL
  KOMARI_DATABASE      SQLite file path, default ./data/komari.db
  KOMARI_ARGS          Extra args passed to ./komari server
  KOMARI_EXTRA_PORTS   Comma-separated extra ports to proxy (added to the defaults)
"""

import json
import os
import platform
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request

# Platform log collectors pipe stdout, which makes Python block-buffer it.
# Without this every print() below is lost when execvp replaces the process.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

REPO = "komari-monitor/komari"
BIN = "./komari"
FALLBACK_VERSION = "1.6.1"

# The edge gateway may dial any of these; $PORT is added at runtime.
DEFAULT_EXTRA_PORTS = (3000, 5000, 8000, 8080, 8888)

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


def log(msg: str) -> None:
    print(f"[komari] {msg}", flush=True)


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
        log(f"{BIN} already exists, skip download")
        return

    custom = os.environ.get("KOMARI_DOWNLOAD_URL", "").strip()
    if custom:
        url = custom
    else:
        tag = os.environ.get("KOMARI_VERSION", "").strip()
        if not tag or tag == "latest":
            tag = resolve_version()
        url = f"https://github.com/{REPO}/releases/download/{tag}/komari-linux-{detect_arch()}"

    log(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "komari-bootstrap"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    if len(data) < 1024 * 1024:
        raise RuntimeError(f"downloaded file too small ({len(data)} bytes)")

    with open(BIN, "wb") as f:
        f.write(data)
    os.chmod(BIN, os.stat(BIN).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log(f"saved {BIN} ({len(data)} bytes)")


def parse_ports() -> list[int]:
    """Primary port first, then the extra gateway candidates, deduplicated."""
    port = int(os.environ.get("PORT", "8080").strip() or "8080")
    extra = os.environ.get("KOMARI_EXTRA_PORTS", "").strip()
    ports = [port]
    for p in extra.split(",") if extra else DEFAULT_EXTRA_PORTS:
        p = p.strip()
        if p and p.isdigit() and int(p) != port:
            ports.append(int(p))
    return ports


def build_cmd() -> list[str]:
    port = parse_ports()[0]
    listen = os.environ.get("KOMARI_LISTEN", "").strip() or f"127.0.0.1:{port}"
    cmd = [BIN, "server", "--listen", listen]

    database = os.environ.get("KOMARI_DATABASE", "").strip()
    if database:
        cmd += ["--database", database]

    extra = os.environ.get("KOMARI_ARGS", "").strip()
    if extra:
        cmd += extra.split()

    return cmd


def pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        src.close()
        dst.close()


def proxy_listener(listen_port: int, target_host: str, target_port: int) -> None:
    """Accept connections on listen_port and raw-forward them to the target."""
    try:
        srv = socket.create_server(("::", listen_port), family=socket.AF_INET6,
                                   dualstack_ipv6=True)
    except OSError:
        try:
            srv = socket.create_server(("0.0.0.0", listen_port))
        except OSError as e:
            log(f"port {listen_port} unavailable ({e}), gateway likely dials another one")
            return
    log(f"proxy listening on port {listen_port} -> {target_host}:{target_port}")

    while True:
        try:
            client, addr = srv.accept()
        except OSError:
            return
        try:
            upstream = socket.create_connection((target_host, target_port), timeout=10)
        except OSError:
            client.close()
            continue
        threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pump, args=(upstream, client), daemon=True).start()


def main() -> None:
    download_binary()

    # --download-only: pre-download the binary during the build phase, then exit
    # so the platform's build command finishes instead of blocking on a server.
    if "--download-only" in sys.argv:
        log("--download-only given, binary ready, exiting")
        return

    cmd = build_cmd()
    log(f"starting: {' '.join(cmd)}")
    komari = subprocess.Popen(cmd)

    # Give komari a moment, then check whether it came up.
    time.sleep(2)
    if komari.poll() is not None:
        log(f"komari exited with code {komari.returncode}")
        sys.exit(komari.returncode or 1)

    # Komari binds the loopback only; re-expose it on every plausible gateway
    # port (IPv4+IPv6). execvp is no longer possible: this process must stay
    # alive to run the proxies.
    target_host, target_port = "127.0.0.1", parse_ports()[0]
    for p in parse_ports():
        threading.Thread(target=proxy_listener, args=(p, target_host, target_port),
                         daemon=True).start()

    try:
        komari.wait()
    except KeyboardInterrupt:
        komari.terminate()


if __name__ == "__main__":
    main()
