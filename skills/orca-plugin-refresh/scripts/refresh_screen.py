from __future__ import annotations

import re
from typing import Sequence


CLAUDE_PLACEHOLDER = re.compile(r'^(Try ".*"|Message @[\w:.-]+…+)$')
CODEX_PLACEHOLDERS = {"Ask Codex to do anything", "Ask a follow-up question"}
CODEX_STARTING = "Waiting for startup"
SEPARATOR = re.compile(r"^\s*─{8,}\s*$")
TITLED_SEPARATOR = re.compile(r"^─{8,} \S.* ─+\s*$")
CODEX_FOOTER = re.compile(r"^\s{2}\S.* · ")
PROMPT_CHARACTERS = "$%#>❯➜»"
SPACED_PROMPT = re.compile(rf"[{re.escape(PROMPT_CHARACTERS)}](?=\s)")
GLYPH_PROMPT_END = re.compile("[\ue000-\uf8ff±✗✘✔✓●✚]$")
RIGHT_PROMPT_GAP = re.compile(r"\S {4,}\S")


def screen_host(lines: Sequence[str]) -> str | None:
    """The agent whose composer ends the screen, followed only by its indented footer."""
    def footer_only(rest: Sequence[str]) -> bool:
        return all(not line.strip() or line[:1].isspace() for line in rest)

    bounds = composer_bounds(lines)
    claude = bounds is not None and footer_only(lines[bounds[1] + 1:])
    prompts = [index for index, line in enumerate(lines) if line.strip().startswith("›")]
    codex = bool(prompts) and input_state("codex", lines) != "unknown" and footer_only(lines[prompts[-1] + 1:])
    return None if claude == codex else "claude" if claude else "codex"


def last_screen_line(lines: Sequence[str]) -> str:
    return next((line.rstrip("\r\n") for line in reversed(lines) if line.strip()), "")


def shell_prompt_empty(lines: Sequence[str]) -> bool:
    """True when the screen ends with a shell prompt and nothing typed after it, and no agent composer ends the screen."""
    return prompt_line_empty(last_screen_line(lines)) and screen_host(lines) is None


def screen_shape(lines: Sequence[str]) -> dict:
    """What the last non-blank screen line ends with, without its text."""
    ending = last_screen_line(lines).rstrip()[-1:]
    return {"ends_with": f"U+{ord(ending):04X}" if ending else None, "non_ascii_end": bool(ending) and not ending.isascii(),
            "prompt_character": any(char in last_screen_line(lines) for char in PROMPT_CHARACTERS), "agent_screen": screen_host(lines)}


def prompt_line_empty(line: str) -> bool:
    """Nothing but whitespace follows the first prompt character that is followed by whitespace. Without such a
    character the line is empty only when its single prompt character ends it; any other prompt character means
    typed text may follow a prompt that is not separated from it, so the line is not proven empty. A line that
    ends with neither is empty when a prompt glyph or git mark ends it and no wide gap hides a right-side prompt."""
    spaced = SPACED_PROMPT.search(line)
    if spaced:
        return not line[spaced.end():].strip()
    stripped = line.rstrip()
    if stripped.endswith(tuple(PROMPT_CHARACTERS)):
        return sum(stripped.count(char) for char in PROMPT_CHARACTERS) == 1
    return bool(GLYPH_PROMPT_END.search(stripped)) and not RIGHT_PROMPT_GAP.search(stripped.strip())


def opening_rule(line: str) -> bool:
    """Claude Code may print the session name at the end of the composer's top rule."""
    return bool(SEPARATOR.match(line) or TITLED_SEPARATOR.match(line))


def composer_bounds(lines: Sequence[str]) -> tuple[int, int] | None:
    """Find the composer, keeping indented draft rules inside its body."""
    for closing in range(len(lines) - 1, 0, -1):
        if not SEPARATOR.match(lines[closing]):
            continue
        bounds = None
        for opening in range(closing - 1, -1, -1):
            if not opening_rule(lines[opening]):
                continue
            if closing - opening >= 2 and lines[opening + 1].strip().startswith("❯"):
                bounds = opening, closing
                # Prefer the enclosing composer over indented rules in its draft.
                if not lines[opening][:1].isspace():
                    break
            elif bounds is not None and not lines[opening][:1].isspace():
                break
        return bounds
    return None


def input_state(host: str, lines: Sequence[str]) -> str:
    """Return `empty`, `text`, or `unknown` for the composer line of an agent TUI screen."""
    if host == "claude":
        bounds = composer_bounds(lines)
        if bounds is not None:
            opening, closing = bounds
            body = [line.strip() for line in lines[opening + 1:closing]]
            content = "\n".join([body[0][1:].strip(), *body[1:]]).strip()
            return "empty" if not content or CLAUDE_PLACEHOLDER.match(content) else "text"
        return "unknown"
    if any(CODEX_STARTING in line for line in lines[-8:]):
        return "unknown"
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped.startswith("›"):
            continue
        following = next((line for line in lines[index + 1:] if line.strip()), "")
        if not CODEX_FOOTER.match(following):
            return "unknown"
        content = stripped[1:].strip()
        return "empty" if not content or content in CODEX_PLACEHOLDERS else "text"
    return "unknown"


def codex_fresh(lines: Sequence[str]) -> bool:
    """A Codex session that never ran a turn has not loaded any instructions yet; its first turn loads the new ones."""
    banner = any("OpenAI Codex (v" in line for line in lines)
    conversation = any(line.strip().startswith("•") for line in lines)
    prompts = [line for line in lines if line.strip().startswith("›")]
    return banner and not conversation and len(prompts) <= 1 and input_state("codex", lines) != "text"
