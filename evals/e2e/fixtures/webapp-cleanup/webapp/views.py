"""Pure functions that turn data into HTML. They never touch the network."""

from __future__ import annotations

from html import escape
from typing import Sequence

from .models import Service


def render_status_row(service: Service) -> str:
    badge = "up" if service.healthy else "down"
    return f'<tr class="{badge}"><td>{escape(service.name)}</td><td>{badge}</td><td>{service.latency_ms} ms</td></tr>'


def render_dashboard(services: Sequence[Service]) -> str:
    rows = "\n".join(render_status_row(service) for service in services)
    healthy = sum(1 for service in services if service.healthy)
    return (
        "<h1>Status</h1>\n"
        f"<p>{healthy} of {len(services)} services healthy</p>\n"
        f"<table>\n{rows}\n</table>"
    )


def render_health(services: Sequence[Service]) -> dict[str, object]:
    unhealthy = [service.name for service in services if not service.healthy]
    return {"ok": not unhealthy, "unhealthy": unhealthy}
