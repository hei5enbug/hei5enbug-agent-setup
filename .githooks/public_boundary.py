"""Public boundary rules shared by the Git hooks, the agent hook, and the repository test.

Findings name the location and kind only, never the matched text.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    import boundary_cli

    sys.exit(boundary_cli.main(sys.argv[1:]))

import os
import re
from pathlib import Path


PRIVATE_WORDS_ENV = "HEI5ENBUG_PUBLIC_BOUNDARY_WORDS"
IDENTITY_CHECKS_EMAIL = False

FICTIONAL_HOME_NAMES = frozenset(
    {"test", "user", "alice", "bob", "u", "a", "other", "me", "demo", "nobody", "runner"}
)
ALLOWED_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
RESERVED_TOP_LEVEL_DOMAINS = frozenset({"test", "invalid", "example", "localhost"})

_NAME = r"[A-Za-z0-9._-]+"
_END = r"""(?=$|[\s"'`:;,)/])"""
HOME_PATH = re.compile(
    rf"/Users/(?P<mac>{_NAME}){_END}|/home/(?P<linux>{_NAME}){_END}"
    rf"|C:\\{{1,2}}Users\\{{1,2}}(?P<win>{_NAME})(?:\\|{_END})"
)
EMAIL = re.compile(
    r"(?P<local>[A-Za-z0-9._%+-]+)@(?P<domain>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})"
)
SECRET_SHAPES = (
    ("private-key-header", re.compile("-----BEGIN [A-Z ]*PRIVATE" + " KEY-----")),
    ("aws-access-key-id", re.compile("AKI" + "A[0-9A-Z]{16}")),
    ("github-token", re.compile(r"(?:gh[pos]_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("slack-token", re.compile("xox" + r"[abprs]-")),
)

# Per-file allowlist of exact matched strings, each with the reason the file may contain it.
ALLOWED_MATCHES: dict[str, dict[str, str]] = {}


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    import subprocess

    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, input=stdin).stdout


def _decode_text(data: bytes) -> str | None:
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_blobs(root: Path, entries: dict[str, str]) -> dict[str, bytes]:
    """Return the content of each named blob, keyed by path, from one batched read."""
    if not entries:
        return {}
    shas = list(dict.fromkeys(entries.values()))
    out = _git(root, "cat-file", "--batch", stdin=("\n".join(shas) + "\n").encode())
    contents: dict[str, bytes] = {}
    position = 0
    for sha in shas:
        end = out.index(b"\n", position)
        _sha, _type, size = out[position:end].split()
        start = end + 1
        contents[sha] = out[start : start + int(size)]
        position = start + int(size) + 1
    return {name: contents[sha] for name, sha in entries.items()}


def _staged_blobs(root: Path) -> dict[str, bytes]:
    entries: dict[str, str] = {}
    for record in _git(root, "ls-files", "-s", "-z").split(b"\0"):
        if not record:
            continue
        meta, _, raw_path = record.partition(b"\t")
        mode, sha, _stage = meta.decode().split()
        if mode in ("120000", "160000"):
            continue
        entries[raw_path.decode("utf-8", "surrogateescape")] = sha
    return read_blobs(root, entries)


def collect_text_files(root: Path) -> list[tuple[str, str]]:
    """Return what a commit would contain: staged blobs of tracked paths and working files not yet added."""
    files = []
    for name, data in _staged_blobs(root).items():
        text = _decode_text(data)
        if text is not None:
            files.append((name, text))
    others = _git(root, "ls-files", "-o", "--exclude-standard", "-z").split(b"\0")
    for raw in others:
        if not raw:
            continue
        name = raw.decode("utf-8", "surrogateescape")
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        text = _decode_text(path.read_bytes())
        if text is not None:
            files.append((name, text))
    return files


def _domain_allowed(domain: str) -> bool:
    if domain.rsplit(".", 1)[1] in RESERVED_TOP_LEVEL_DOMAINS:
        return True
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in ALLOWED_EMAIL_DOMAINS)


def compile_private_words(words: list[str]) -> tuple[re.Pattern[str], ...]:
    patterns = []
    for word in words:
        parts = word.split()
        if parts:
            body = r"\s+".join(re.escape(part) for part in parts)
            patterns.append(re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE))
    return tuple(patterns)


def read_word_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def load_private_words(root: Path, environ: dict[str, str] | None = None) -> tuple[re.Pattern[str], ...]:
    """Read the private word list the environment names; ignore one that lies inside the repository."""
    value = (environ if environ is not None else os.environ).get(PRIVATE_WORDS_ENV)
    if not value:
        return ()
    path = Path(value).expanduser().resolve()
    if path == root.resolve() or root.resolve() in path.parents:
        print(f"public boundary: {PRIVATE_WORDS_ENV} points inside the repository; ignored", file=sys.stderr)
        return ()
    try:
        return compile_private_words(read_word_file(path))
    except (OSError, UnicodeDecodeError):
        print(f"public boundary: {PRIVATE_WORDS_ENV} could not be read; private words not checked", file=sys.stderr)
        return ()


def scan_text(
    label: str,
    text: str,
    allowed: dict[str, str] | None = None,
    *,
    words: tuple[re.Pattern[str], ...] = (),
    check_email: bool = True,
) -> list[str]:
    allowed = allowed or {}
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in HOME_PATH.finditer(line):
            name = (match.group("mac") or match.group("linux") or match.group("win")).rstrip(".")
            if name.lower() in FICTIONAL_HOME_NAMES or match.group(0) in allowed:
                continue
            findings.append(f"{label}:{number}: home-path")
        for match in EMAIL.finditer(line) if check_email else ():
            domain = match.group("domain").lower()
            if match.group("local") == "git" and line[match.end() : match.end() + 1] == ":":
                continue
            if _domain_allowed(domain) or match.group(0) in allowed:
                continue
            findings.append(f"{label}:{number}: email")
        for kind, pattern in SECRET_SHAPES:
            for match in pattern.finditer(line):
                if match.group(0) in allowed:
                    continue
                findings.append(f"{label}:{number}: {kind}")
        for pattern in words:
            if pattern.search(line):
                findings.append(f"{label}:{number}: private-word")
    return findings


def scan_identity(label: str, text: str, words: tuple[re.Pattern[str], ...] = ()) -> list[str]:
    return scan_text(label, text, words=words, check_email=IDENTITY_CHECKS_EMAIL)
