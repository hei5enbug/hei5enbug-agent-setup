"""Every statement about what Claude Code or Codex can or cannot do is registered with its official source.

`config/host-facts.json` lists each verified host-capability statement with its page, quote, version, and
verification date, and each plugin-design line that only names which host this plugin covers.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "host-facts.json"
MAX_AGE_DAYS = 30
HOSTS = {"claude", "codex", "both"}
KINDS = {"host-fact", "plugin-design"}
SCANNED_SUFFIXES = {".md", ".py", ".json", ".toml", ".sh", ".js", ".mjs", ".yml", ".yaml"}
EXCLUDED = re.compile(r"^docs/ko/|(^|/)(tests|evals)/|\.test\.ts$|^config/host-facts\.json$")
LIMITATION = re.compile(
    r"\b(cannot|can't|can not|does not support|do not support|doesn't support|not supported|unsupported|unverified"
    r"|does not document|not documented|only (?:on|in) (?:Codex|Claude Code|Claude)"
    r"|(?:Codex|Claude Code|Claude)(?:-| )only)\b",
    re.IGNORECASE,
)
HOST = re.compile(r"Claude Code|Codex", re.IGNORECASE)
FIX = "verify the statement against the official docs and register it in config/host-facts.json"


def registry() -> list[dict]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["claims"]


def scanned_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    return [name for name in listed
            if Path(name).suffix in SCANNED_SUFFIXES and not EXCLUDED.search(name) and (REPO_ROOT / name).is_file()]


def limitation_lines() -> list[tuple[str, int, str]]:
    found = []
    for name in scanned_files():
        for number, line in enumerate((REPO_ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            if LIMITATION.search(line) and HOST.search(line):
                found.append((name, number, line))
    return found


def registered_fragments() -> list[tuple[str, str]]:
    return [(item["file"], item["contains"]) for claim in registry() for item in claim["lines"]]


def test_the_registry_entries_are_complete():
    """Each claim has a unique id, a known host and kind, and the fields its kind requires."""
    claims = registry()
    ids = [claim["id"] for claim in claims]
    assert len(ids) == len(set(ids)), "claim ids must be unique"
    for claim in claims:
        assert claim["host"] in HOSTS and claim["kind"] in KINDS, claim["id"]
        assert claim["lines"], f"{claim['id']} must name the lines it covers"
        if claim["kind"] == "host-fact":
            assert claim["statement"].strip() and claim["quote"].strip(), claim["id"]
            assert claim["doc_url"].startswith(("https://", "local evidence")), claim["id"]
            assert date.fromisoformat(claim["verified_on"]) <= date.today(), claim["id"]
        else:
            assert claim["reason"].strip(), claim["id"]


def test_every_registered_line_still_exists():
    """A registered fragment that no longer appears in its file is stale; remove or update the entry."""
    missing = []
    for name, fragment in registered_fragments():
        path = REPO_ROOT / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not any(fragment in line for line in text.splitlines()):
            missing.append(f"{name}: {fragment!r}")
    assert missing == [], "update or remove these config/host-facts.json lines:\n" + "\n".join(missing)


def test_every_host_limitation_phrase_is_registered():
    """A line that says Claude Code or Codex cannot, does not support, or only offers something must be registered."""
    fragments = registered_fragments()
    unregistered = [f"{name}:{number}: {line.strip()[:140]}" for name, number, line in limitation_lines()
                    if not any(name == file and fragment in line for file, fragment in fragments)]
    assert unregistered == [], f"{FIX}:\n" + "\n".join(unregistered)


@pytest.mark.parametrize("claim", [c for c in registry() if c["kind"] == "host-fact"], ids=lambda c: c["id"])
def test_host_facts_are_reverified_within_thirty_days(claim):
    """Re-read the official page, correct the entry and the files it covers, then set verified_on to that date."""
    age = date.today() - date.fromisoformat(claim["verified_on"])
    assert age <= timedelta(days=MAX_AGE_DAYS), (
        f"{claim['id']} was verified {age.days} days ago: re-check {claim['doc_url']} and update verified_on")
