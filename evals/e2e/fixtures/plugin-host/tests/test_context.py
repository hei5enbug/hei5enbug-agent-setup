from pathlib import Path

import pytest

from host.context import MAX_CONTEXT_BYTES, render_context

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("value", "line"), [
    (None, "Delivery: Auto (`auto`)."),
    ("auto", "Delivery: Auto (`auto`)."),
    (" Manual ", "Delivery: Manual (`manual`)."),
    ("bogus", "Delivery: Auto (`auto`)."),
])
def test_the_context_names_the_delivery_mode(value, line):
    environ = {} if value is None else {"HOST_OPTION_DELIVERY": value}
    text = render_context(ROOT, environ)
    assert line in text
    assert text.count("Delivery:") == 1


def test_the_context_stays_within_its_budget():
    assert len(render_context(ROOT, {}).encode("utf-8")) <= MAX_CONTEXT_BYTES
