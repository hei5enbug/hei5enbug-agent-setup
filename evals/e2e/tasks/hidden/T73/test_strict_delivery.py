import json
import re
from pathlib import Path

import pytest

from host.context import MAX_CONTEXT_BYTES, render_context
from host.options import load_options

ROOT = Path(__file__).resolve().parents[2]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_the_manifest_offers_strict_between_auto_and_manual_and_keeps_auto_as_the_default():
    delivery = load_options(ROOT)["delivery"]
    assert delivery["options"] == ["auto", "strict", "manual"]
    assert delivery["default"] == "auto"
    assert delivery["type"] == "string"
    assert "strict" in delivery["description"]
    assert delivery["description"].isascii()
    assert set(json.loads(read("plugin.json"))["userConfig"]) == {"delivery"}


@pytest.mark.parametrize(("value", "line"), [
    ("strict", "Delivery: Strict (`strict`)."),
    (" STRICT ", "Delivery: Strict (`strict`)."),
    ("manual", "Delivery: Manual (`manual`)."),
    ("auto", "Delivery: Auto (`auto`)."),
    ("stricter", "Delivery: Auto (`auto`)."),
    ("", "Delivery: Auto (`auto`)."),
])
def test_the_context_names_the_delivery_mode(value, line):
    text = render_context(ROOT, {"HOST_OPTION_DELIVERY": value})
    assert line in text
    assert text.count("Delivery:") == 1


def test_the_budget_is_kept_and_not_raised():
    assert MAX_CONTEXT_BYTES == 1800
    assert len(render_context(ROOT, {"HOST_OPTION_DELIVERY": "strict"}).encode("utf-8")) <= MAX_CONTEXT_BYTES


def test_routing_describes_strict_and_keeps_the_other_modes():
    text = read("instructions/routing.md")
    strict = [line for line in text.splitlines() if line.startswith("- `strict`:")]
    assert len(strict) == 1
    assert re.search(r"stop", strict[0], re.I) and re.search(r"report", strict[0], re.I)
    assert "- `auto`: the session picks the delivery per change and goes on without asking." in text
    assert "- `manual`: the session asks before it delivers a change and waits for the answer." in text
    assert text.splitlines().index(strict[0]) > text.splitlines().index(
        "- `auto`: the session picks the delivery per change and goes on without asking.")


def test_the_configuration_table_lists_strict_in_the_source_and_its_mirror():
    for relative in ("docs/configuration.md", "docs/ko/docs/configuration.ko.md"):
        rows = [line for line in read(relative).splitlines() if line.startswith("| `delivery` |")]
        assert len(rows) == 1 and "`strict`" in rows[0], relative
        assert "`auto`" in rows[0] and "`manual`" in rows[0]
        assert rows[0].rstrip().endswith("| `auto` |")


def test_the_routing_mirror_describes_strict_and_keeps_its_header():
    lines = read("docs/ko/instructions/routing.ko.md").splitlines()
    assert lines[0] == "# 라우팅"
    assert lines[2].startswith("> 영어 원본: [routing.md](../../../instructions/routing.md)")
    assert sum(1 for line in lines if line.startswith("- `strict`:")) == 1
    assert sum(1 for line in lines if line.startswith("- `")) == 3


def test_the_configuration_mirror_keeps_its_header():
    lines = read("docs/ko/docs/configuration.ko.md").splitlines()
    assert lines[0] == "# 설정"
    assert lines[2].startswith("> 영어 원본: [configuration.md](../../../docs/configuration.md)")
