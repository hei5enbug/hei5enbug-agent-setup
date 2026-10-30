from __future__ import annotations

import re
import time
from typing import Callable, Sequence

from refresh_orca import Orca
from refresh_screen import screen_host


TITLE = re.compile(r"/compact acts on the main conversation, not this agent")
OPTION = re.compile(r"^\s*(?P<mark>[❯>]\s+)?(?:\d+\.\s*)?(?P<label>\S.*?)\s*$")
SELECTION = re.compile(r"^\s*[❯>]\s+(?!/)\S")
CANCEL = "Cancel"
RUN = "Run /compact on the main conversation"
DOWN_KEY = "\x1b[B"
ENTER_KEY = "\r"
MAX_MOVES = 2
SETTLE_SECONDS = 3.0
TAIL_LINES = 15
FAILED = "failed:compact_dialog_open"


def selection_list(lines: Sequence[str]) -> bool:
    """True when a selection mark sits next to another indented option line in the screen's tail."""
    tail = [line for line in lines[-TAIL_LINES:] if line.strip()]
    for index, line in enumerate(tail):
        if not SELECTION.match(line):
            continue
        neighbors = tail[max(index - 1, 0):index] + tail[index + 1:index + 2]
        if any(other[:2].isspace() and not SELECTION.match(other) and not other.strip().startswith("⎿") for other in neighbors):
            return True
    return False


def classify(lines: Sequence[str]) -> tuple[str, str | None]:
    """`none`, `compact` with the selected option (`cancel` or `run`), or `other` for any different dialog."""
    if screen_host(lines) == "claude":
        return "none", None
    titles = [index for index, line in enumerate(lines) if TITLE.search(line)]
    if not titles:
        return ("other", None) if selection_list(lines) else ("none", None)
    marked: list[str] = []
    labels: list[str] = []
    columns: set[int] = set()
    others: list[int] = []
    for line in lines[titles[-1] + 1:]:
        match = OPTION.match(line) if line.strip() else None
        if match is None:
            continue
        label, column = match.group("label"), match.start("label")
        if label in (CANCEL, RUN):
            labels.append(label)
            columns.add(column)
            if match.group("mark"):
                marked.append(label)
        else:
            others.append(column if not match.group("mark") else -1)
    if sorted(labels) != sorted([CANCEL, RUN]) or len(marked) != 1 or len(columns) != 1 or -1 in others or columns & set(others):
        return "other", None
    return "compact", "cancel" if marked[0] == CANCEL else "run"


def dialog_open(lines: Sequence[str]) -> bool:
    return classify(lines)[0] != "none"


def answer_compact_dialog(orca: Orca, entry: dict, lines: Sequence[str], sleep: Callable[[float], None] = time.sleep) -> str:
    """Handle a dialog after `/compact`: `none` when absent, `wait` while it is being answered, or `failed:<code>`.

    Only the key that moves the selection is sent while it is on Cancel; Enter goes out once, on the run option.
    """
    kind, selected = classify(lines)
    if kind == "none":
        return "none"
    if kind == "other":
        return FAILED
    handle = entry["handle"]
    if selected == "run":
        if not entry.get("dialog_confirmed"):
            entry["dialog_confirmed"] = True
            orca.keys(handle, ENTER_KEY)
        return "wait"
    moves = entry.get("dialog_moves", 0)
    if moves >= MAX_MOVES:
        return FAILED
    entry["dialog_moves"] = moves + 1
    orca.keys(handle, DOWN_KEY)
    deadline = time.time() + SETTLE_SECONDS
    while classify(orca.screen(handle)[0]) == ("compact", "cancel") and time.time() < deadline:
        sleep(0.3)
    return "wait"
