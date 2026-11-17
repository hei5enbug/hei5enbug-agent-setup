#!/usr/bin/env python3
"""Print every question-tool input that a session transcript stores, as raw characters, and flag escape text.

A transcript line is JSON, so a `\\u3053` in the file can be the JSON spelling of the kana, which the input never held
as escape text, or the six characters of escape text the input itself held. Decoding each line settles which, which a
text search of the file cannot. Reads a Claude Code transcript (`AskUserQuestion` in an assistant message) and a Codex
rollout (`request_user_input` function call). Exit 0 when no stored string holds escape text, 1 when one does, 2 when
the file cannot be read.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

TOOLS = ("AskUserQuestion", "request_user_input")
ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}")


def tool_inputs(record: Any) -> Iterator[tuple[str, Any]]:
    if not isinstance(record, dict):
        return
    content = (record.get("message") or {}).get("content") if isinstance(record.get("message"), dict) else None
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in TOOLS:
            yield block["name"], block.get("input")
    payload = record.get("payload")
    if isinstance(payload, dict) and payload.get("type") == "function_call" and payload.get("name") in TOOLS:
        try:
            yield payload["name"], json.loads(payload.get("arguments") or "")
        except ValueError:
            return


def strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")


def report(lines: Iterator[str]) -> tuple[list[str], bool]:
    out, escaped, number = [], False, 0
    for text in lines:
        try:
            record = json.loads(text)
        except ValueError:
            continue
        for tool, tool_input in tool_inputs(record):
            number += 1
            for path, value in strings(tool_input):
                flag = ESCAPE.search(value) is not None
                escaped = escaped or flag
                out.append(f'{number} {tool} {path}: "{value}"' + ("  <- the stored input itself holds escape text" if flag else ""))
    out.append(f"question inputs: {number}; stored escape text: {'yes' if escaped else 'no'}")
    return out, escaped


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: stored_question_input.py <session transcript file>", file=sys.stderr)
        return 2
    try:
        lines = Path(argv[1]).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        print(f"cannot read {argv[1]}: {error}", file=sys.stderr)
        return 2
    out, escaped = report(iter(lines))
    print("\n".join(out))
    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
