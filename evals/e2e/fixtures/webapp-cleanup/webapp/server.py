"""HTTP server: `python3 -m webapp.server` serves the dashboard and a JSON health endpoint."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from .config import Settings, load_settings
from .models import Service
from .views import render_dashboard, render_health

SERVICES = (
    Service("api", True, 42),
    Service("worker", True, 118),
    Service("mailer", False, 0),
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", render_dashboard(SERVICES).encode("utf-8"))
        elif self.path == "/health":
            self._send(200, "application/json", json.dumps(render_health(SERVICES)).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(settings: Settings) -> None:
    HTTPServer((settings.host, settings.port), Handler).serve_forever()


if __name__ == "__main__":
    serve(load_settings())
