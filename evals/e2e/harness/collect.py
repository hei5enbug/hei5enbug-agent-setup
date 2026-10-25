"""Copy the host records of one run (main, subagent, and role runner transcripts, Codex rollouts, assignments)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .transcript import assignment_paths, leading_cd, read_jsonl, role_runner_status

ROLLOUT_MARGIN_BEFORE = timedelta(seconds=5)
ROLLOUT_MARGIN_AFTER = timedelta(seconds=120)


def find_main_transcript(config_dir: Path, session_id: str) -> Path | None:
    matches = sorted((config_dir / "projects").glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None


def collect_claude(config_dir: Path, session_id: str, destination: Path) -> dict[str, Any]:
    """Copy the main transcript and subagent records; return what was found."""
    main = find_main_transcript(config_dir, session_id) if session_id else None
    found: dict[str, Any] = {"main": None, "subagents": []}
    if main is None:
        return found
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main, destination / "main.jsonl")
    found["main"] = "main.jsonl"
    source = main.parent / session_id / "subagents"
    if source.is_dir():
        target = destination / "subagents"
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir()):
            if item.is_file():
                shutil.copy2(item, target / item.name)
                found["subagents"].append(item.name)
    return found


def load_subagents(directory: Path) -> list[dict[str, Any]]:
    """Return [{meta, events}] for each agent-*.jsonl in a copied subagents directory."""
    records: list[dict[str, Any]] = []
    if not directory.is_dir():
        return records
    for transcript in sorted(directory.glob("agent-*.jsonl")):
        meta_path = transcript.with_suffix(".meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        except ValueError:
            meta = {}
        records.append({"meta": meta if isinstance(meta, dict) else {}, "events": read_jsonl(transcript)})
    return records


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _within(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def rollout_matches(first_line: dict[str, Any], work_dir: Path, start: datetime, end: datetime) -> bool:
    payload = first_line.get("payload") if isinstance(first_line.get("payload"), dict) else {}
    if first_line.get("type") != "session_meta" or not _within(str(payload.get("cwd", "")), work_dir):
        return False
    started = _parse_time(payload.get("timestamp") or first_line.get("timestamp"))
    return started is not None and start - ROLLOUT_MARGIN_BEFORE <= started <= end + ROLLOUT_MARGIN_AFTER


def find_rollouts(codex_home: Path, work_dir: Path, start: datetime, end: datetime) -> list[Path]:
    sessions = codex_home / "sessions"
    days = {
        moment.strftime("%Y/%m/%d")
        for anchor in (start, end)
        for offset in (-1, 0, 1)
        for moment in ((anchor + timedelta(days=offset)).astimezone(timezone.utc), (anchor + timedelta(days=offset)).astimezone())
    }
    matches: list[Path] = []
    for day in sorted(days):
        for rollout in sorted((sessions / day).glob("rollout-*.jsonl")):
            first = next(iter(read_jsonl_head(rollout)), None)
            if first is not None and rollout_matches(first, work_dir, start, end):
                matches.append(rollout)
    return matches


def read_jsonl_head(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            line = stream.readline()
    except OSError:
        return []
    try:
        parsed = json.loads(line)
    except ValueError:
        return []
    return [parsed] if isinstance(parsed, dict) else []


def collect_codex(codex_home: Path, work_dir: Path, start: datetime, end: datetime, destination: Path) -> list[str]:
    copied: list[str] = []
    for rollout in find_rollouts(codex_home, work_dir, start, end):
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rollout, destination / rollout.name)
        copied.append(rollout.name)
    return copied


def rollout_roles(tool_calls: list[dict[str, Any]]) -> dict[str, str]:
    """Map rollout file name -> role from the role_runner status lines in tool results."""
    roles: dict[str, str] = {}
    for call in tool_calls:
        status = role_runner_status(call.get("result_text", ""))
        evidence = status.get("evidence") if status else None
        if isinstance(evidence, dict) and evidence.get("rollout"):
            roles[Path(str(evidence["rollout"])).name] = str(status.get("role") or status.get("capability") or "unknown")
    return roles


def load_rollouts(directory: Path, roles: dict[str, str]) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    return [
        {"role": roles.get(item.name, "unknown"), "name": item.name, "events": read_jsonl(item)}
        for item in sorted(directory.glob("rollout-*.jsonl"))
    ]


def resolve_assignment(path: str, command: str, repo: Path | None) -> Path:
    """An --assignment path as the shell saw it: relative paths start in the leading `cd` directory or the run repo."""
    source = Path(path).expanduser()
    if source.is_absolute() or repo is None:
        return source
    folder = leading_cd(command)
    base = Path(folder).expanduser() if folder else Path()
    return (base if base.is_absolute() else repo / base) / source


def collect_assignments(tool_calls: list[dict[str, Any]], destination: Path, repo: Path | None = None) -> dict[str, str]:
    """Copy assignment files still on disk that Bash role_runner commands named; index them by the literal path."""
    texts: dict[str, str] = {}
    names: dict[str, str] = {}
    for call in tool_calls:
        if call.get("name") != "Bash":
            continue
        command = str(call.get("input", {}).get("command", ""))
        for path in assignment_paths(command):
            source = resolve_assignment(path, command, repo)
            if source.is_file() and path not in texts:
                destination.mkdir(parents=True, exist_ok=True)
                text = source.read_text(encoding="utf-8", errors="replace")
                names[path] = f"{len(texts) + 1:02d}-{source.name}"
                (destination / names[path]).write_text(text, encoding="utf-8")
                texts[path] = text
    if names:
        (destination / "index.json").write_text(json.dumps(names, indent=2), encoding="utf-8")
    return texts


def runner_transcript_paths(tool_calls: list[dict[str, Any]]) -> list[tuple[str, Path]]:
    """(role, transcript path) of every Claude role_runner session named by a status line, in first-seen order."""
    found: list[tuple[str, Path]] = []
    for call in tool_calls:
        status = role_runner_status(str(call.get("result_text", "")))
        evidence = status.get("evidence") if status else None
        if status and status.get("runner") == "claude" and isinstance(evidence, dict) and evidence.get("transcript"):
            entry = (str(status.get("role") or "unknown"), Path(str(evidence["transcript"])))
            if entry not in found:
                found.append(entry)
    return found


def collect_runner_transcripts(tool_calls: list[dict[str, Any]], destination: Path) -> list[str]:
    """Copy the transcripts of Claude role_runner sessions to <role>-<n>.jsonl; return the copied names."""
    copied: list[str] = []
    counts: dict[str, int] = {}
    for role, source in runner_transcript_paths(tool_calls):
        if not source.is_file():
            continue
        counts[role] = counts.get(role, 0) + 1
        name = f"{role}-{counts[role]}.jsonl"
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / name)
        copied.append(name)
    return copied


def load_runner_transcripts(directory: Path) -> list[dict[str, Any]]:
    """[{role, name, events}] for each copied <role>-<n>.jsonl."""
    if not directory.is_dir():
        return []
    return [
        {"role": item.stem.rsplit("-", 1)[0], "name": item.name, "events": read_jsonl(item)}
        for item in sorted(directory.glob("*.jsonl"))
    ]


def load_assignments(directory: Path) -> dict[str, str]:
    try:
        names = json.loads((directory / "index.json").read_text(encoding="utf-8"))
        return {path: (directory / name).read_text(encoding="utf-8") for path, name in names.items()}
    except (OSError, ValueError, AttributeError):
        return {}
