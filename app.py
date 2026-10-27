#!/usr/bin/env python3
"""Minimal runtime bootstrap for Komari.

This container does not compile the Go project. It downloads the published
komari release binary for the current architecture, starts it bound to the
loopback interface, and proxies one listening port to it.

Why the proxy: komari binds a single address; the platform gateway dials a
fixed container port (infrlo: 5000, verified live). The bootstrap listens on
that port (or $PORT when set) and raw-forwards to komari, which keeps
WebSocket (agent connections) working.

Why the log filter: the official binary always logs at Info to stdout and
reads no log-level env var, while a busy panel easily produces tens of
thousands of lines per hour. This bootstrap filters komari's stdout to
Warn+ (counting suppressed Info lines) unless KOMARI_VERBOSE=1.

Environment variables:
  PORT                 Listening port; overrides the default when set
  KOMARI_LISTEN        Komari bind address, defaults to 127.0.0.1:$PORT
  KOMARI_VERSION       Optional pinned tag, e.g. 1.6.1; empty/latest => latest release
  KOMARI_DOWNLOAD_URL  Optional direct binary URL
  KOMARI_DATABASE      SQLite file path, default ./data/komari.db
  KOMARI_ARGS          Extra args passed to ./komari server
  KOMARI_EXTRA_PORTS   Comma-separated extra ports to proxy (rarely needed)
  KOMARI_VERBOSE       Set to 1 to pass komari's Info logs through unfiltered
"""

import json
import os
import platform
import re
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

# Port the platform edge gateway dials (verified live on infrlo via the
# first-connection WARNING). PORT overrides it when set.
DEFAULT_PORT = 5000

# komari console lines look like "2026/10/27 16:20:57 [INFO/SERVER] message".
# Stderr and anything without this marker is treated as Warn+ and passed through.
KOMARI_LINE = re.compile(r"^\S+ \S+ \[(DEBUG|INFO|WARN|ERROR)/")

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
    """$PORT when set, otherwise the platform's default gateway port."""
    port = os.environ.get("PORT", "").strip()
    return [int(port) if port.isdigit() and port else DEFAULT_PORT]


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


class LevelFilter:
    """Forward komari stdout to the real stdout, dropping Info/Debug lines.

    Lines arrive one write() per line, so the pending count lives on the
    instance: a WARN/ERROR line flushes it first, keeping the suppress note
    right above the line it gives context to. A heartbeat every 10 minutes
    reports the total swallowed, proving the filter is alive.
    """

    def __init__(self) -> None:
        self.suppressed = 0   # total since last heartbeat
        self._pending = 0     # suppressed since last inline mention
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        passthrough = []
        for line in text.splitlines(keepends=True):
            m = KOMARI_LINE.match(line)
            if m and m.group(1) in ("DEBUG", "INFO"):
                with self._lock:
                    self.suppressed += 1
                    self._pending += 1
                continue
            with self._lock:
                pending, self._pending = self._pending, 0
            if pending:
                passthrough.append(f"[komari] {pending} info line(s) suppressed\n")
            passthrough.append(line)
        if passthrough:
            sys.__stdout__.write("".join(passthrough))
            sys.__stdout__.flush()

    def flush(self) -> None:
        sys.__stdout__.flush()

    def heartbeat(self) -> None:
        while True:
            time.sleep(600)
            with self._lock:
                if self.suppressed:
                    print(f"[komari] {self.suppressed} info line(s) suppressed "
                          f"in the last 10 min (set KOMARI_VERBOSE=1 to see them)",
                          flush=True)
                    self.suppressed = 0


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
    first = True

    while True:
        try:
            client, addr = srv.accept()
        except OSError:
            return
        if first:
            # Log at most once per port: this is how you learn which port the
            # platform gateway actually dials.
            log(f"WARNING: first connection on port {listen_port} from {addr[0]}:{addr[1]} "
                f"-> this is the effective gateway port")
            first = False
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
    komari = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              errors="replace", bufsize=1)

    # Give komari a moment, then check whether it came up.
    time.sleep(2)
    if komari.poll() is not None:
        log(f"komari exited with code {komari.returncode}")
        sys.exit(komari.returncode or 1)

    # Komari binds the loopback only; re-expose it on every plausible gateway
    # port (IPv4+IPv6). This process must stay alive to run the proxies.
    target_host, target_port = "127.0.0.1", parse_ports()[0]

    verbose = os.environ.get("KOMARI_VERBOSE", "").strip() == "1"
    flt = LevelFilter()

    def relay() -> None:
        # In verbose mode komari's lines go straight to the real stdout;
        # otherwise LevelFilter drops Info/Debug and counts them.
        stream = sys.__stdout__ if verbose else flt
        for line in iter(komari.stdout.readline, ""):
            stream.write(line)

    if not verbose:
        threading.Thread(target=flt.heartbeat, daemon=True).start()
    threading.Thread(target=relay, daemon=True).start()
    log("KOMARI_VERBOSE=1: Info logs pass through unfiltered" if verbose
        else "filtering komari Info logs (KOMARI_VERBOSE=1 to disable)")

    for p in parse_ports():
        threading.Thread(target=proxy_listener, args=(p, target_host, target_port),
                         daemon=True).start()

    try:
        komari.wait()
    except KeyboardInterrupt:
        komari.terminate()


if __name__ == "__main__":
    main()
