# Runtime-only Komari bootstrap

This repository is intentionally reduced to the minimal runtime bootstrap.
It does not compile the Go project or package the Go source tree.

What it does:
- downloads the latest published komari release binary from `komari-monitor/komari`
- optionally pins a version with `KOMARI_VERSION`
- starts `./komari server` with `PORT`, `KOMARI_LISTEN`, `KOMARI_DATABASE`, and `KOMARI_ARGS`

Runtime entrypoint:
- `python app.py`

Recommended environment variables:
- `PORT=3000`
- `KOMARI_LISTEN=0.0.0.0:3000`
- `KOMARI_DATABASE=/data/komari.db`

To use the newest release, leave `KOMARI_VERSION` unset or set it to `latest`.
