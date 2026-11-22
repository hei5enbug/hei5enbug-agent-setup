"""Shared seed for the stored question input tasks: a fictional session transcript in the notes-cli repository."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

TRANSCRIPT = Path("session") / "demo-session.jsonl"
GREETING = "こんにちは"


def write_transcript(root: Path, label: str) -> None:
    """Write a three-line transcript whose one question tool input holds `label`, as raw characters."""
    question = {"question": "Which greeting should the demo tool print?", "header": "Greeting", "multiSelect": False,
                "options": [{"label": label, "description": "Print it first"},
                            {"label": "Hello", "description": "Print the English greeting"}]}
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Pick the greeting for the demo tool."}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": "toolu_demo_1", "name": "AskUserQuestion", "input": {"questions": [question]}}]}},
        {"type": "user", "message": {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "toolu_demo_1", "content": "The user answered: Hello"}]}},
    ]
    path = root / TRANSCRIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    for command in (["git", "add", "-A"], ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                                            "commit", "-q", "-m", "chore: add the demo session transcript"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
