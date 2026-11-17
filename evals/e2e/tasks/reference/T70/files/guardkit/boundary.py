"""Find fictional secret values in text and in the lines each commit of a range adds."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PATTERNS = {
    "token": re.compile(r"demo_tok_[A-Za-z0-9]{16}"),
    "password-url": re.compile(r"://[^/\s:@]+:[^@\s]+@"),
}


@dataclass(frozen=True)
class Finding:
    path: str
    kind: str
    commit: str = ""


def scan_text(text: str, path: str = "", commit: str = "") -> list[Finding]:
    return [Finding(path, kind, commit) for kind, pattern in PATTERNS.items() if pattern.search(text)]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def added_lines(repo: Path, commit: str) -> dict[str, list[str]]:
    diff = git(repo, "show", "--format=", "--first-parent", "-m", "-U0", "--no-color", "--no-ext-diff", commit)
    added: dict[str, list[str]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = None if line == "+++ /dev/null" else line[6:]
        elif line.startswith("+") and path is not None:
            added.setdefault(path, []).append(line[1:])
    return added


def scan_range(repo: Path, base: str, head: str) -> list[Finding]:
    found: list[Finding] = []
    for commit in git(repo, "rev-list", "--reverse", "--topo-order", f"{base}..{head}").split():
        for path, lines in sorted(added_lines(repo, commit).items()):
            found.extend(scan_text("\n".join(lines), path, commit))
    return found
