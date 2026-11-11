"""Stop hook that makes the independent text review run before a final report that follows a change.

It continues the turn once, as Stop hook feedback, when the main session ends a turn that changed files with a report
that no `text_review.py` review checked, or that differs from the draft the last passing review checked. Any
unreadable input lets the stop pass.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_runtime  # noqa: E402
from orca_status_hook import is_real_prompt  # noqa: E402
from required_checks_hook import ASSIGNMENT, WRAPPERS, git_subcommand, segments_of  # noqa: E402
from text_review import report_digest  # noqa: E402

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
AGENT_TOOLS = frozenset({"Agent", "Task"})
READ_ONLY_AGENT_MARKERS = ("scout", "review", "explore", "plan", "guide", "statusline")
RUNNER_SCRIPT = "role_runner.py"
WRITING_RUNNER_ROLES = frozenset({"worker", "implementation", "designer", "language", "writer", "agent"})
MINIMUM_REPORT_CHARACTERS = 400
REVIEW_SCRIPT = "text_review.py"
FINAL_REPORT_KIND = "final-report"
ASSISTANT_ENTRY = re.compile(rb'"type": ?"assistant"')
USER_ENTRY = re.compile(rb'"type": ?"user"')
TOOL_RESULT_BLOCK = re.compile(rb'"type": ?"tool_result"')
DIGEST_KEY = "final_report_sha256"
DIGEST_VALUE = re.compile(rf'"{DIGEST_KEY}":\s*"([0-9a-f]{{64}})"')
WRITE_PREFILTER = re.compile(r">|\btee\b|\s-[A-Za-z]*i|--in-place")
HEREDOC_START = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
OPERATOR_CHARS = frozenset(";&|<>")
SINGLE_OPERATORS = frozenset("()\n")
WRITE_OPERATORS = frozenset({">", ">>", ">|", "&>", "&>>"})
IN_PLACE_OPTION = re.compile(r"^-[A-Za-z]*i|^--in-place")
IN_PLACE_COMMANDS = frozenset({"sed", "perl"})
NON_FILE_PREFIXES = ("$", "~", "&")
SCRATCH_PREFIXES = ("/dev/", "/tmp/", "/private/", "/var/folders/")
INTERPRETER_PREFILTER = re.compile(r"python|node|ruby|perl")
INTERPRETER = re.compile(r"^(?:python[0-9.]*|node|ruby|perl)$")
CODE_OPTION = re.compile(r"^-[A-Za-z]*[ce]$|^--eval$")
WRITE_CALL = re.compile(
    r"write_text\(|write_bytes\(|(?<!stdout)(?<!stderr)\.write\(|json\.dump\(|shutil\.(?:copy|move)"
    r"|os\.(?:replace|rename)\(|writeFileSync\(|appendFileSync\(|File\.write\("
    r"|\bopen\(.*?,\s*(?:mode\s*=\s*)?['\"][rwabxt+]*[wax][rwabxt+]*['\"]"
)


MISSING_REVIEW = "ends with a final report that no text review checked"
CHANGED_REPORT = "differs from the draft that the last passing text review checked"
FEEDBACK_MARKS = ((MISSING_REVIEW, MISSING_REVIEW.encode()), (CHANGED_REPORT, CHANGED_REPORT.encode()))


@dataclass(frozen=True)
class TurnFacts:
    changed_files: bool = False
    reviewed: bool = False
    review_ids: frozenset[str] = frozenset()
    digest: str | None = None
    told: frozenset[str] = frozenset()


def reason_text(root: Path) -> str:
    return (
        f"This turn changed files and {MISSING_REVIEW}. "
        f"Read {root}/instructions/shared-text.md, section \"Independent text review\", then run "
        f"`python3 {root}/scripts/text_review.py review --kind {FINAL_REPORT_KIND} --draft <file> ...` on the report "
        "and apply its findings. "
        "Review every other text this turn wrote for other people the same way, with its own --kind. "
        "Then send the report again."
    )


def runs_review(command: str) -> bool:
    for tokens in segments_of(command):
        for index, token in enumerate(tokens):
            if os.path.basename(token) != REVIEW_SCRIPT:
                continue
            rest = tokens[index + 1 :]
            words = [word for word in rest if not word.startswith("-")]
            if words[:1] in (["review"], ["check"]) and (
                f"--kind={FINAL_REPORT_KIND}" in rest
                or any(a == "--kind" and b == FINAL_REPORT_KIND for a, b in zip(rest, rest[1:]))
            ):
                return True
    return False


def mismatch_reason_text(root: Path) -> str:
    return (
        f"The final report {CHANGED_REPORT}. "
        "Send that reviewed text unchanged, or run "
        f"`python3 {root}/scripts/text_review.py review --kind {FINAL_REPORT_KIND} --draft <file> ...` "
        "again on the changed report and send the text that passes."
    )


def runs_commit(command: str) -> bool:
    return any(git_subcommand(tokens) == "commit" for tokens in segments_of(command))


def without_heredoc_bodies(command: str) -> str:
    kept: list[str] = []
    terminators: deque[str] = deque()
    for line in command.splitlines():
        if terminators:
            if line.strip() == terminators[0]:
                terminators.popleft()
            continue
        kept.append(line)
        terminators.extend(match.group(2) for match in HEREDOC_START.finditer(line))
    return "\n".join(kept)


def lex(command: str) -> list[tuple[bool, str]]:
    """Split into (is_operator, text) tokens; a quoted operator character stays inside its word."""
    tokens: list[tuple[bool, str]] = []
    word: list[str] = []
    in_word = False
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        index += 1
        if quote:
            if char == quote:
                quote = ""
            elif char == "\\" and quote == '"' and index < len(command):
                word.append(command[index])
                index += 1
            else:
                word.append(char)
            continue
        if char == "\\" and index < len(command):
            word.append(command[index])
            in_word = True
            index += 1
        elif char in "'\"":
            quote, in_word = char, True
        elif char == "#" and not in_word:
            while index < len(command) and command[index] != "\n":
                index += 1
        elif char in OPERATOR_CHARS or char in SINGLE_OPERATORS or char in " \t\r":
            if in_word:
                tokens.append((False, "".join(word)))
                word, in_word = [], False
            if char in OPERATOR_CHARS:
                start = index - 1
                while index < len(command) and command[index] in OPERATOR_CHARS:
                    index += 1
                tokens.append((True, command[start:index]))
            elif char in SINGLE_OPERATORS:
                tokens.append((True, char))
        else:
            word.append(char)
            in_word = True
    if quote:
        raise ValueError("unterminated quote")
    if in_word:
        tokens.append((False, "".join(word)))
    return tokens


def command_segments(command: str) -> list[tuple[list[str], list[str]]]:
    """Return each simple command as its words and the targets of its output redirections."""
    segments: list[tuple[list[str], list[str]]] = []
    words: list[str] = []
    targets: list[str] = []
    pending = ""
    for is_operator, text in lex(without_heredoc_bodies(command)):
        if not is_operator:
            if pending == "write":
                targets.append(text)
            elif not pending:
                words.append(text)
            pending = ""
        elif "<" in text or ">" in text:
            pending = "write" if text in WRITE_OPERATORS else "skip"
            if words and words[-1].isdigit():
                words = words[:-1]
        else:
            pending = ""
            segments.append((words, targets))
            words, targets = [], []
    return [*segments, (words, targets)]


def command_index(words: list[str]) -> int:
    index = 0
    while index < len(words) and (ASSIGNMENT.match(words[index]) or words[index] in WRAPPERS):
        index += 1
    return index


def in_place_files(arguments: list[str]) -> list[str]:
    if not any(IN_PLACE_OPTION.match(argument) for argument in arguments):
        return []
    positional: list[str] = []
    has_script_option = False
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
        elif argument in ("-e", "-f"):
            has_script_option, skip_next = True, True
        elif argument and not argument.startswith("-"):
            positional.append(argument)
    return positional if has_script_option else positional[1:]


def segment_written_paths(words: list[str], targets: list[str]) -> list[str]:
    index = command_index(words)
    name = os.path.basename(words[index]) if index < len(words) else ""
    arguments = words[index + 1 :]
    if name == "tee":
        return [*targets, *(argument for argument in arguments if not argument.startswith("-"))]
    if name in IN_PLACE_COMMANDS:
        return [*targets, *in_place_files(arguments)]
    return targets


def heredoc_blocks(command: str) -> list[tuple[str, str]]:
    """Return each heredoc as the line that opens it and its body."""
    blocks: list[tuple[str, str]] = []
    terminators: deque[str] = deque()
    header, body = "", []
    for line in command.splitlines():
        if not terminators:
            header, body = line, []
            terminators.extend(match.group(2) for match in HEREDOC_START.finditer(line))
        elif line.strip() == terminators[0]:
            terminators.popleft()
            if not terminators:
                blocks.append((header, "\n".join(body)))
        else:
            body.append(line)
    if terminators and body:
        blocks.append((header, "\n".join(body)))
    return blocks


def interpreter_arguments(words: list[str]) -> list[str] | None:
    index = command_index(words)
    if index < len(words) and INTERPRETER.match(os.path.basename(words[index])):
        return words[index + 1 :]
    return None


def runs_writing_script(command: str) -> bool:
    if not (INTERPRETER_PREFILTER.search(command) and WRITE_CALL.search(command)):
        return False
    try:
        for words, _ in command_segments(command):
            arguments = interpreter_arguments(words)
            if arguments and any(CODE_OPTION.match(a) for a in arguments) and WRITE_CALL.search(" ".join(arguments)):
                return True
        for header, body in heredoc_blocks(command):
            if WRITE_CALL.search(body) and any(
                interpreter_arguments(words) is not None for words, _ in command_segments(header)
            ):
                return True
    except ValueError:
        return False
    return False


def is_project_path(path: str) -> bool:
    return bool(path) and not path.startswith(NON_FILE_PREFIXES + SCRATCH_PREFIXES)


def writes_file(command: str) -> bool:
    if not WRITE_PREFILTER.search(command):
        return False
    try:
        segments = command_segments(command)
    except ValueError:
        return False
    return any(is_project_path(path) for words, targets in segments for path in segment_written_paths(words, targets))


def delegates_writing(tool_input: dict) -> bool:
    agent_type = tool_input.get("subagent_type")
    if not isinstance(agent_type, str) or not agent_type.strip():
        return True
    lowered = agent_type.lower()
    return not any(marker in lowered for marker in READ_ONLY_AGENT_MARKERS)


def runs_writing_role(command: str) -> bool:
    for tokens in segments_of(command):
        for index, token in enumerate(tokens):
            if os.path.basename(token) != RUNNER_SCRIPT:
                continue
            words = [word for word in tokens[index + 1 :] if not word.startswith("-")]
            if words[:1] and words[0] in WRITING_RUNNER_ROLES:
                return True
    return False


def block_facts(block: dict, facts: TurnFacts) -> TurnFacts:
    if block.get("type") != "tool_use":
        return facts
    name = block.get("name")
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name in EDIT_TOOLS:
        return replace(facts, changed_files=True)
    if name in AGENT_TOOLS:
        return replace(facts, changed_files=facts.changed_files or delegates_writing(tool_input))
    command = tool_input.get("command")
    if name == "Bash" and isinstance(command, str):
        runs = REVIEW_SCRIPT in command and runs_review(command)
        tool_id = block.get("id")
        ids = facts.review_ids | {tool_id} if runs and isinstance(tool_id, str) else facts.review_ids
        return replace(
            facts,
            changed_files=facts.changed_files
            or ("commit" in command and runs_commit(command))
            or writes_file(command)
            or runs_writing_script(command)
            or (RUNNER_SCRIPT in command and runs_writing_role(command)),
            reviewed=facts.reviewed or runs,
            review_ids=ids,
        )
    return facts


def result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"] for block in content if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def result_facts(content: object, facts: TurnFacts) -> TurnFacts:
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        if block.get("tool_use_id") not in facts.review_ids:
            continue
        digests = DIGEST_VALUE.findall(result_text(block.get("content")))
        if digests:
            facts = replace(facts, digest=digests[-1])
    return facts


def skips_line(line: bytes) -> bool:
    if ASSISTANT_ENTRY.search(line):
        return False
    if not USER_ENTRY.search(line):
        return True
    return bool(TOOL_RESULT_BLOCK.search(line)) and DIGEST_KEY.encode() not in line


def current_turn_facts(transcript_path: str) -> TurnFacts:
    """Return what the turn after the last real user prompt did, reading the transcript once.

    A line that cannot be parsed may hide the latest prompt, so it yields empty facts and the stop passes.
    """
    facts = TurnFacts()
    with open(transcript_path, "rb") as stream:
        for line in stream:
            told = frozenset(mark for mark, raw in FEEDBACK_MARKS if raw in line)
            if told - facts.told:
                facts = replace(facts, told=facts.told | told)
            if skips_line(line):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                return TurnFacts()
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict) or entry.get("isSidechain"):
                continue
            content = message.get("content")
            if entry.get("type") == "user":
                if is_real_prompt(entry, message):
                    facts = TurnFacts()
                else:
                    facts = result_facts(content, facts)
                continue
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict):
                    facts = block_facts(block, facts)
    return facts


def asks_question(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return not lines or lines[-1].endswith(("?", "？"))


def is_report(text: str) -> bool:
    return len(text.strip()) >= MINIMUM_REPORT_CHARACTERS


def is_main_session(event: dict) -> bool:
    if os.environ.get("HEI5ENBUG_ASSIGNED_ROLE") or os.environ.get("HEI5ENBUG_PARENT_SESSION"):
        return False
    return not event.get("agent_id")


def feedback(reason: str) -> dict:
    """Continue the turn as Stop hook feedback, which Claude Code shows instead of a hook error."""
    return {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}


def decide(event: object) -> dict | None:
    if not isinstance(event, dict) or event.get("hook_event_name") not in (None, "Stop"):
        return None
    if not is_main_session(event) or event.get("background_tasks"):
        return None
    transcript = event.get("transcript_path")
    message = event.get("last_assistant_message")
    if not isinstance(message, str) or not isinstance(transcript, str) or asks_question(message):
        return None
    facts = current_turn_facts(transcript)
    if not facts.changed_files:
        return None
    root = Path(__file__).resolve().parents[1]
    if facts.digest and report_digest(message) != facts.digest and CHANGED_REPORT not in facts.told:
        return feedback(mismatch_reason_text(root))
    if not facts.reviewed and is_report(message) and MISSING_REVIEW not in facts.told:
        return feedback(reason_text(root))
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        result = decide(event)
    except Exception as error:
        hook_runtime.report_error("final_report_hook.py", error)
        return 0
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(hook_runtime.run("final_report_hook.py", main))
