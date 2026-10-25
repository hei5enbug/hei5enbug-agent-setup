# webapp-cleanup

A tiny status dashboard served with the Python standard library. It lists a few services with their health and
latency and exposes a JSON health endpoint.

## Run

```bash
python3 -m webapp.server
```

Open `http://127.0.0.1:8080/` for the dashboard and `/health` for the JSON summary.

## Configuration

Values come from environment variables. For local work, put them in a `.env` file next to this README; the file is
ignored by git.

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_HOST` | `127.0.0.1` | Address to listen on. |
| `DEMO_PORT` | `8080` | Port to listen on. |
| `DEMO_DEBUG` | unset | Set to `1` to enable debug output. |
| `DEMO_SESSION_KEY` | empty | Key used to sign sessions. Keep it out of logs and commits. |

## Build

`python3 scripts/build_assets.py` copies `static/` into `build/` and writes a manifest. Packaging writes archives to
`dist/`. Both folders hold generated output.

## Development

```bash
python3 -m pytest -q
```

Project rules are in [AGENTS.md](AGENTS.md). The Korean mirror of this file is
[docs/ko/README.ko.md](docs/ko/README.ko.md).
