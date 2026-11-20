"""Acceptance checks for the `auto` implementation worker route in the Claude session context and manifest."""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import session_context  # noqa: E402

VARIABLE = "CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER"
DESCRIPTION = (
    "Route implementation work: auto (the main session picks per task: the plugin worker on haiku for easy work "
    "or sonnet for normal or hard work, and a GPT worker, gpt-6-luna for easy work or gpt-6.2-sol for hard work, "
    "only when a Claude route fails or stops on a usage limit), haiku, sonnet, or opus (the plugin worker on that "
    "model only), codex (a GPT worker through the role runner at high, gpt-6-luna for easy work or gpt-6.2-sol "
    "for hard work), or sol (gpt-6.2-sol at high through the role runner)."
)


def context(monkeypatch, value=None):
    monkeypatch.delenv("PLUGIN_ROOT", raising=False)
    if value is None:
        monkeypatch.delenv(VARIABLE, raising=False)
    else:
        monkeypatch.setenv(VARIABLE, value)
    return session_context.render_context(REPO_ROOT, "claude")


@pytest.mark.parametrize(("value", "line"), [
    (None, "Implementation worker route: Auto (`auto`)."),
    ("", "Implementation worker route: Auto (`auto`)."),
    ("auto", "Implementation worker route: Auto (`auto`)."),
    (" AUTO ", "Implementation worker route: Auto (`auto`)."),
    ("bogus", "Implementation worker route: Auto (`auto`)."),
    ("sonnet", "Implementation worker route: Sonnet (`sonnet`)."),
    ("codex", "Implementation worker route: Codex (`codex`)."),
    (" HaIku ", "Implementation worker route: Haiku (`haiku`)."),
    ("sol", "Implementation worker route: Sol (`sol`)."),
    ("SOL", "Implementation worker route: Sol (`sol`)."),
])
def test_세션_컨텍스트는_구현_경로_한_줄을_담는다(monkeypatch, value, line):
    text = context(monkeypatch, value)
    assert line in text
    assert text.count("Implementation worker route:") == 1
    assert len(text.encode("utf-8")) < session_context.MAX_CONTEXT_BYTES


def test_codex_세션에는_구현_경로_줄이_없다(monkeypatch):
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    monkeypatch.delenv("HEI5ENBUG_RESPONSE_LANGUAGE", raising=False)
    text = session_context.render_context(REPO_ROOT, "codex")
    assert "Implementation worker route" not in text


def test_매니페스트는_auto를_기본으로_하는_여섯_경로를_선언한다():
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    option = manifest["userConfig"]["implementation_worker"]
    assert option == {
        "type": "string",
        "title": "Implementation worker",
        "description": DESCRIPTION,
        "options": ["auto", "codex", "haiku", "sol", "sonnet", "opus"],
        "default": "auto",
    }
    assert option["description"].isascii()
