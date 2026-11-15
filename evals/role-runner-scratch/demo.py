"""Seed the demo repository and check the three model runs of the role runner scratch-folder issue, with no model call."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SEEDED_TEST = "test_bulk_discount"
ORDERS = (("A-1", 4, 250), ("A-2", 7, 125), ("A-3", 3, 400))
EXPECTED_TOTAL = sum(quantity * cents for _, quantity, cents in ORDERS)
PYPROJECT = """[project]
name = "demo-pricing"
version = "0.1.0"
requires-python = ">=3.11"

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
addopts = "-p no:cacheprovider"
"""
PRICING = '''def bulk_price(quantity: int, unit_cents: int) -> int:
    """Return the price in cents; ten or more units get a ten percent discount."""
    total = quantity * unit_cents
    if quantity > 10:
        return total * 9 // 10
    return total
'''
TESTS = '''from pricing import bulk_price


def test_single_unit():
    assert bulk_price(1, 500) == 500


def test_bulk_discount():
    assert bulk_price(10, 500) == 4500
    assert bulk_price(11, 500) == 4950


def test_bulk_discount_boundary():
    assert bulk_price(9, 500) == 4500
'''
TEST_COMMAND = re.compile(r"pytest")
INSTALL_COMMAND = re.compile(r"\buv\s+(sync|pip|add|venv)|pip3?\s+install|npm\s+(install|i)\b|\bmake\s+test\b|pytest")
BROKEN_HEREDOC = "can't create temp file for here document"


def git(repo: Path, *arguments: str) -> str:
    environment = ["-c", "user.name=demo", "-c", "user.email=demo@example.com"]
    done = subprocess.run(["git", *environment, *arguments], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout


def seed(repo: Path, with_env: bool) -> None:
    """Create the demo repository: a uv project, one pytest test that fails on a seeded defect, and a data file."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (repo / "pricing.py").write_text(PRICING, encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_pricing.py").write_text(TESTS, encoding="utf-8")
    (repo / "conftest.py").write_text("", encoding="utf-8")
    (repo / "data").mkdir(exist_ok=True)
    rows = "\n".join(f"{order},{quantity},{cents}" for order, quantity, cents in ORDERS)
    (repo / "data" / "orders.csv").write_text("order,quantity,unit_cents\n" + rows + "\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    if with_env:
        subprocess.run(["uv", "sync"], cwd=repo, check=True)


def snapshot(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--ignored")


def tool_records(path: Path) -> list[tuple[str, str]]:
    """Return (call or output, text) pairs from a Codex rollout or a Claude transcript, in order."""
    records: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = entry.get("payload") if isinstance(entry, dict) else None
        kind = payload.get("type") if isinstance(payload, dict) else None
        if isinstance(kind, str) and kind.endswith("_call") and kind != "web_search_call":
            records.append(("call", json.dumps(payload, ensure_ascii=False)))
        elif isinstance(kind, str) and kind.endswith("_call_output"):
            records.append(("output", json.dumps(payload, ensure_ascii=False)))
        message = entry.get("message") if isinstance(entry, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                records.append(("call", json.dumps(item.get("input"), ensure_ascii=False)))
            elif isinstance(item, dict) and item.get("type") == "tool_result":
                records.append(("output", json.dumps(item.get("content"), ensure_ascii=False)))
    return records


def validation_failures(records: list[tuple[str, str]], answer: str) -> list[str]:
    calls = [text for kind, text in records if kind == "call"]
    outputs = [text for kind, text in records if kind == "output"]
    failures = []
    if not any(TEST_COMMAND.search(text) for text in calls):
        failures.append("no test command in the tool records")
    if not any(SEEDED_TEST in text and re.search(r"FAILED|AssertionError|assert ", text) for text in outputs):
        failures.append("no output shows the seeded assertion failing")
    if SEEDED_TEST not in answer:
        failures.append(f"the review does not name {SEEDED_TEST}")
    return failures


def scout_failures(records: list[tuple[str, str]], answer: str) -> list[str]:
    calls = [text for kind, text in records if kind == "call"]
    outputs = [text for kind, text in records if kind == "output"]
    failures = []
    if not any("<<" in text and "python" in text for text in calls):
        failures.append("no heredoc Python command in the tool records")
    if any(BROKEN_HEREDOC in text for text in outputs):
        failures.append("a heredoc failed to create its temp file")
    if str(EXPECTED_TOTAL) not in answer:
        failures.append(f"the result lacks the expected value {EXPECTED_TOTAL}")
    if any(INSTALL_COMMAND.search(text) for text in calls):
        failures.append("a test or install command ran")
    return failures


def check(kind: str, repo: Path, records_path: Path, answer: Path, before: Path) -> list[str]:
    records = tool_records(records_path)
    text = answer.read_text(encoding="utf-8")
    failures = validation_failures(records, text) if kind == "validation" else scout_failures(records, text)
    if snapshot(repo) != before.read_text(encoding="utf-8"):
        failures.append("git status --porcelain --ignored changed")
    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    seeding = commands.add_parser("seed")
    seeding.add_argument("repo", type=Path)
    seeding.add_argument("--with-env", action="store_true")
    snapping = commands.add_parser("snapshot")
    snapping.add_argument("repo", type=Path)
    snapping.add_argument("output", type=Path)
    checking = commands.add_parser("check")
    checking.add_argument("kind", choices=("validation", "scout"))
    checking.add_argument("repo", type=Path)
    checking.add_argument("--records", type=Path, required=True)
    checking.add_argument("--result", type=Path, required=True)
    checking.add_argument("--before", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "seed":
        seed(args.repo, args.with_env)
    elif args.command == "snapshot":
        args.output.write_text(snapshot(args.repo), encoding="utf-8")
    else:
        failures = check(args.kind, args.repo, args.records, args.result, args.before)
        print(json.dumps({"pass": not failures, "failures": failures}))
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
