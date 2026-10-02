from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path


TAIL_BYTES = 4 * 1024 * 1024
MAX_BLOCKS_PER_TURN = 3
STATE_FILE = "language_guard_state.json"
STATE_RETENTION_SECONDS = 7 * 24 * 60 * 60
MIN_MEASURED_CHARACTERS = 20
MIN_TARGET_RATIO = 0.3
DEFAULT_CODEX_LANGUAGE = "Korean"

TARGET_RANGES = {
    "Korean": "가-힣ᄀ-ᇿ㄰-㆏",
    "Japanese": "぀-ヿ一-鿿",
    "Chinese": "一-鿿",
    "Russian": "Ѐ-ӿ",
    "Ukrainian": "Ѐ-ӿ",
    "Greek": "Ͱ-Ͽ",
    "Arabic": "؀-ۿ",
    "Hebrew": "֐-׿",
    "Thai": "฀-๿",
    "Hindi": "ऀ-ॿ",
}
ALIASES = {
    "Korean": ("korean", "ko", "한국어"),
    "Japanese": ("japanese", "ja", "日本語"),
    "Chinese": ("chinese", "zh", "中文", "简体中文", "繁體中文"),
    "Russian": ("russian", "ru", "русский"),
    "Ukrainian": ("ukrainian", "uk", "українська"),
    "Greek": ("greek", "el", "ελληνικά"),
    "Arabic": ("arabic", "ar", "العربية"),
    "Hebrew": ("hebrew", "he", "עברית"),
    "Thai": ("thai", "th", "ไทย"),
    "Hindi": ("hindi", "hi", "हिन्दी"),
}
LANGUAGE_BY_ALIAS = {alias.casefold(): name for name, aliases in ALIASES.items() for alias in aliases}
TARGET_PATTERNS = {name: re.compile(f"[{ranges}]") for name, ranges in TARGET_RANGES.items()}

FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?:(?!\n[ \t]*\n).)+?\1", re.DOTALL)
BLOCK_QUOTE = re.compile(r"^[ \t]*>.*$", re.MULTILINE)
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+|\bwww\.\S+")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
ASCII_LETTER = re.compile(r"[A-Za-z]")

STOP_REASON = (
    "Your last reply was not written in {language}. Rewrite the whole reply in {language} now. "
    "Keep code, identifiers, paths, and commands as they are, and put any text the user asked for "
    "in another language in a code block or block quote."
)
REMINDER = (
    "Your previous progress message was not written in {language}. "
    "Write every following message to the user, including progress updates, in {language}."
)


def codex_language() -> str:
    return os.environ.get("HEI5ENBUG_RESPONSE_LANGUAGE", "").strip() or DEFAULT_CODEX_LANGUAGE


def language_name(value: str) -> str | None:
    """Map a configured language value such as `ko-KR` or `한국어` to a supported language name."""
    text = value.strip().casefold()
    if text in LANGUAGE_BY_ALIAS:
        return LANGUAGE_BY_ALIAS[text]
    return LANGUAGE_BY_ALIAS.get(re.split(r"[-_]", text, maxsplit=1)[0])


def claude_language(event: dict) -> str | None:
    project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd")
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    candidates = []
    if isinstance(project, str) and project:
        candidates += [Path(project) / ".claude" / "settings.local.json", Path(project) / ".claude" / "settings.json"]
    candidates.append((Path(config) if config else Path.home() / ".claude") / "settings.json")
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("language")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(value, str) and value.strip():
            return value
    return None


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def resolve_language(event: dict, host: str) -> str | None:
    """Return the supported language name to enforce, or None when no enforcement applies."""
    value = codex_language() if host == "codex" else claude_language(event)
    return language_name(value) if value else None


def strip_fenced_code(text: str) -> str:
    kept = []
    fence = None
    for line in text.splitlines():
        opened = FENCE_OPEN.match(line)
        if fence is None:
            if opened:
                fence = opened[1]
            else:
                kept.append(line)
        elif opened and opened[1][0] == fence[0] and len(opened[1]) >= len(fence) and not line.strip(" \t`~"):
            fence = None
    return "\n".join(kept)


def measured_text(text: str) -> str:
    text = strip_fenced_code(text)
    for pattern in (INLINE_CODE, BLOCK_QUOTE, HTML_TAG, LINK_TARGET, URL):
        text = pattern.sub(" ", text)
    return text


def is_compliant(text: str, language: str) -> bool:
    rest = measured_text(text)
    target = len(TARGET_PATTERNS[language].findall(rest))
    letters = len(ASCII_LETTER.findall(rest))
    total = target + letters
    return total < MIN_MEASURED_CHARACTERS or target / total >= MIN_TARGET_RATIO


def read_entries(path: object) -> list[dict]:
    """Parse the JSONL tail of a transcript, ignoring malformed lines."""
    if not isinstance(path, str) or not path:
        return []
    with open(path, "rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - TAIL_BYTES)
        stream.seek(start)
        data = stream.read()
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]
    entries = []
    for line in lines:
        try:
            entry = json.loads(line.rstrip(b"\r").decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def content_blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def claude_messages(entries: list[dict]) -> list[tuple[dict, dict]]:
    pairs = []
    for entry in entries:
        message = entry.get("message")
        if entry.get("type") in ("assistant", "user") and isinstance(message, dict):
            pairs.append((entry, message))
    return pairs


def is_codex_format(entries: list[dict]) -> bool:
    return any(entry.get("type") == "response_item" and isinstance(entry.get("payload"), dict) for entry in entries)


def claude_last_assistant_text(entries: list[dict]) -> str:
    assistants = [
        message
        for entry, message in claude_messages(entries)
        if entry.get("type") == "assistant" and not entry.get("isSidechain") and message.get("model") != "<synthetic>"
    ]
    if not assistants:
        return ""
    message_id = assistants[-1].get("id")
    group = [m for m in assistants if message_id is not None and m.get("id") == message_id] or [assistants[-1]]
    texts = [b.get("text") for m in group for b in content_blocks(m) if b.get("type") == "text"]
    return "\n".join(t for t in texts if isinstance(t, str))


def codex_message_text(payload: dict) -> str:
    texts = [b.get("text") for b in content_blocks(payload) if b.get("type") == "output_text"]
    return "\n".join(t for t in texts if isinstance(t, str))


def codex_last_assistant_text(entries: list[dict]) -> str:
    latest = None
    for entry in reversed(entries):
        payload = entry.get("payload")
        if entry.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        if payload.get("role") == "user":
            break
        if payload.get("role") != "assistant":
            continue
        if payload.get("phase") == "final_answer":
            return codex_message_text(payload)
        if latest is None:
            latest = payload
    return codex_message_text(latest) if latest else ""


def last_assistant_text(event: dict) -> str:
    message = event.get("last_assistant_message")
    if isinstance(message, str) and message.strip():
        return message
    entries = read_entries(event.get("transcript_path"))
    return codex_last_assistant_text(entries) if is_codex_format(entries) else claude_last_assistant_text(entries)


def claude_preceding_text(entries: list[dict], tool_use_id: str) -> str | None:
    owner = None
    for entry, message in claude_messages(entries):
        if entry.get("type") == "assistant" and any(
            b.get("type") == "tool_use" and b.get("id") == tool_use_id for b in content_blocks(message)
        ):
            owner = message
            break
    if owner is None:
        return None
    message_id = owner.get("id")
    group = [
        message
        for entry, message in claude_messages(entries)
        if entry.get("type") == "assistant" and (message is owner or (message_id is not None and message.get("id") == message_id))
    ]
    texts = []
    for message in group:
        for block in content_blocks(message):
            if block.get("type") == "tool_use":
                return "\n".join(texts) if block.get("id") == tool_use_id else None
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
    return None


def is_codex_call(payload: dict) -> bool:
    kind = payload.get("type")
    return isinstance(kind, str) and (kind.endswith("_call") or kind in ("function_call", "custom_tool_call"))


def is_codex_tool_item(payload: dict) -> bool:
    kind = payload.get("type")
    return isinstance(kind, str) and (is_codex_call(payload) or kind.endswith("_call_output") or kind.endswith("_output"))


def codex_preceding_text(entries: list[dict], tool_use_id: str) -> str | None:
    payloads = [e["payload"] for e in entries if e.get("type") == "response_item" and isinstance(e.get("payload"), dict)]
    index = next(
        (i for i, p in enumerate(payloads) if is_codex_call(p) and p.get("call_id") == tool_use_id),
        None,
    )
    if index is None:
        return None
    texts = []
    for payload in reversed(payloads[:index]):
        if is_codex_tool_item(payload):
            break
        if payload.get("type") != "message":
            continue
        if payload.get("role") == "user":
            break
        if payload.get("role") == "assistant":
            texts.append(codex_message_text(payload))
    return "\n".join(reversed(texts)) if texts else None


def preceding_progress_text(event: dict) -> str | None:
    tool_use_id = event.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None
    entries = read_entries(event.get("transcript_path"))
    if is_codex_format(entries):
        return codex_preceding_text(entries, tool_use_id)
    return claude_preceding_text(entries, tool_use_id)


def data_directory() -> Path | None:
    value = os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("PLUGIN_DATA")
    return Path(value) if value else None


def record_block(directory: Path, key: str) -> bool:
    """Count one block for this turn and report whether the cap still allowed it."""
    path = directory / STATE_FILE
    now = time.time()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        loaded = {}
    state = {
        name: entry
        for name, entry in (loaded.items() if isinstance(loaded, dict) else [])
        if isinstance(entry, dict)
        and isinstance(entry.get("count"), int)
        and isinstance(entry.get("time"), (int, float))
        and entry["time"] >= now - STATE_RETENTION_SECONDS
    }
    count = state.get(key, {}).get("count", 0)
    if count >= MAX_BLOCKS_PER_TURN:
        return False
    state[key] = {"count": count + 1, "time": now}
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".language-guard-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def may_block(event: dict) -> bool:
    directory = data_directory()
    turn = next((v for v in (event.get("prompt_id"), event.get("turn_id")) if isinstance(v, str) and v), None)
    if directory is not None and turn is not None:
        key = f"{event.get('session_id') or ''}:{turn}"
        try:
            return record_block(directory, key)
        except OSError:
            pass
    return event.get("stop_hook_active") is not True


def handle_stop(event: dict, language: str) -> dict | None:
    text = last_assistant_text(event)
    if not text.strip() or is_compliant(text, language):
        return None
    if not may_block(event):
        return None
    return {"decision": "block", "reason": STOP_REASON.format(language=language)}


def handle_post_tool_use(event: dict, language: str) -> dict | None:
    text = preceding_progress_text(event)
    if text is None or not text.strip() or is_compliant(text, language):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": REMINDER.format(language=language),
        }
    }


HANDLERS = {"Stop": handle_stop, "PostToolUse": handle_post_tool_use}


def handle(event: object) -> dict | None:
    if not isinstance(event, dict) or event.get("agent_id"):
        return None
    handler = HANDLERS.get(event.get("hook_event_name"))
    if handler is None:
        return None
    language = resolve_language(event, detect_host())
    return handler(event, language) if language else None


def main() -> int:
    try:
        output = handle(json.load(sys.stdin))
    except Exception:
        output = None
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
