from webapp.models import Service
from webapp.views import render_dashboard, render_health, render_status_row

SERVICES = (Service("api", True, 40), Service("mailer", False, 0))


def test_row_shows_state_and_latency():
    assert render_status_row(SERVICES[0]) == '<tr class="up"><td>api</td><td>up</td><td>40 ms</td></tr>'


def test_row_escapes_the_name():
    assert "&lt;b&gt;" in render_status_row(Service("<b>", True, 1))


def test_dashboard_counts_healthy_services():
    assert "1 of 2 services healthy" in render_dashboard(SERVICES)


def test_health_lists_unhealthy_services():
    assert render_health(SERVICES) == {"ok": False, "unhealthy": ["mailer"]}
    assert render_health(SERVICES[:1]) == {"ok": True, "unhealthy": []}
