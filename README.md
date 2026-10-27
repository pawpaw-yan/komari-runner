# Runtime-only Komari bootstrap

This repository is intentionally reduced to the minimal runtime bootstrap for
deploying Komari (https://github.com/komari-monitor/komari) on container
platforms that only offer a build command and a run command (e.g. infrlo).

It does **not** compile the Go project and does **not** contain the upstream Go
source tree; the upstream sources live in the original repository.

## What it does

1. downloads the latest published `komari` release binary from
   `komari-monitor/komari` (pinned via `KOMARI_VERSION`, falls back to
   `1.6.1` if the GitHub API is unreachable)
2. starts `./komari server` bound to the loopback interface
3. proxies every plausible platform gateway port (`$PORT` plus
   80/3000/5000/8000/8080/8888/25774/30033, IPv4+IPv6) to komari via raw
   TCP forwarding, so the edge gateway connects no matter which port it
   dials (WebSocket passes through untouched)

Runtime entrypoint: `python app.py` (or `python3 app.py` on Debian-based images).

The optional `--download-only` flag downloads the binary and exits, useful for
pre-downloading during the platform's build phase:

```
pip install -r requirements.txt && (python3 app.py --download-only || true)
```

Run command: `python3 app.py || python app.py`

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `PORT` | Primary komari port (included in the proxy list) | `8080` |
| `KOMARI_EXTRA_PORTS` | Extra proxied ports, comma-separated (added to the defaults) | `80,3000,5000,8000,8080,8888,25774,30033` |
| `KOMARI_LISTEN` | Bind address | `0.0.0.0:$PORT` |
| `KOMARI_VERSION` | Pin a release tag, e.g. `1.5.0-fix1`; `latest`/empty = latest release | latest |
| `KOMARI_DOWNLOAD_URL` | Direct binary URL (e.g. a mirror) | GitHub official URL |
| `KOMARI_DATABASE` | SQLite file path | `./data/komari.db` |
| `KOMARI_ARGS` | Extra args passed to `./komari server` | empty |

Deployment details for the infrlo platform (build/run commands, persistence,
WebSocket notes): see [doc/deploy-infrlo.md](doc/deploy-infrlo.md).

## Repository layout (after reduction)

Only these files are kept; everything else was upstream Komari source and was
removed in commit "Remove upstream Komari sources, keep runtime-only bootstrap":

| File | Purpose |
|---|---|
| `app.py` | Bootstrap: download binary → exec `komari server` |
| `requirements.txt` | Empty placeholder so the platform's default `pip install -r requirements.txt` build command succeeds |
| `doc/deploy-infrlo.md` | infrlo deployment guide |
| `README.md` / `README_zh-cn.md` | This documentation |
| `NOTICE` / `LICENSE` | Upstream attributions and MIT license kept for attribution |

## License

Komari is MIT licensed; this bootstrap retains the upstream `LICENSE` and
`NOTICE` for attribution.
