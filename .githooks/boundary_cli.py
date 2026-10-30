"""Entry points of the Git hooks and the agent hook."""

from __future__ import annotations

import os
import sys

FINDINGS_EXIT = 1
USAGE = "usage: public_boundary.py pre-commit | commit-msg <file> | pre-push <remote> <url> | agent-hook"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def report(findings: list[str]) -> int:
    if not findings:
        return 0
    print("public boundary: findings (matched values are not shown)", file=sys.stderr)
    print("\n".join(f"  {item}" for item in dict.fromkeys(findings)), file=sys.stderr)
    return FINDINGS_EXIT


def collect(mode: str, argv: list[str]) -> list[str] | None:
    from pathlib import Path

    import boundary_git
    from public_boundary import load_private_words

    words = load_private_words(Path(ROOT))
    if mode == "pre-commit":
        top = Path.cwd()
        return boundary_git.staged_findings(top, words) + boundary_git.identity_findings(top, words)
    if mode == "commit-msg" and len(argv) > 1:
        text = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
        kept = "\n".join("" if line.startswith("#") else line for line in text.splitlines())
        return boundary_git.message_findings("commit message", kept, words)
    if mode == "pre-push":
        return boundary_git.pre_push_findings(Path.cwd(), sys.stdin.read(), words)
    return None


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode == "agent-hook":
        import boundary_agent

        return boundary_agent.run(sys.stdin.read(), ROOT)
    import boundary_git

    try:
        findings = collect(mode, argv)
    except (OSError, boundary_git.CheckError) as error:
        print(f"public boundary: the check could not run, so it is blocked: {error}", file=sys.stderr)
        return FINDINGS_EXIT
    if findings is None:
        print(USAGE, file=sys.stderr)
        return FINDINGS_EXIT
    return report(findings)
