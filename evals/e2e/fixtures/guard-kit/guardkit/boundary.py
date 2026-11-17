"""Find fictional secret values in text and in the files a range of commits touches."""

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


def scan_range(repo: Path, base: str, head: str) -> list[Finding]:
    found: list[Finding] = []
    names = git(repo, "diff", "--name-only", f"{base}..{head}").split()
    for name in names:
        try:
            text = git(repo, "show", f"{head}:{name}")
        except subprocess.CalledProcessError:
            continue
        found.extend(scan_text(text, name, head))
    return found
