from __future__ import annotations

CHOICES = ("wait", "interrupt", "skip")
REASONS = ("dialog_open", "input_not_restorable", "reload_needs_force", "orchestration_mail_pending", "state_unreadable")
CODEX_INSTALL = "codex_install"
CODEX_FLAGS = ("outside_orca", "own_session")
QUESTION_KEYS = ("id", "terminal", "host", "worktree", "title", "reason", "background", "options")
COMMAND_NAMES = {"reload": "/reload-plugins", "compact": "/compact", "clear": "/clear"}


def command_list(actions: list[str]) -> str:
    return " and ".join(COMMAND_NAMES.get(action, action) for action in actions) or "the planned commands"


def options_for(entry: dict) -> list[dict]:
    """The three answers to a question and what each would do, in one English sentence built from the entry."""
    commands = command_list(entry.get("actions") or [])
    reason, background = entry["ask"], entry.get("background")
    if reason == "input_not_restorable" or entry.get("input_unrestorable"):
        wait = (f"Nothing is typed now. The helper sends {commands} once the input line is empty or holds text it can restore "
                "exactly, and skips the session when the line does not change within one hour.")
    else:
        wait = f"Nothing is typed now. The helper sends {commands} once the session is idle, after the usual checks."
    stop = "Press Esc once to stop the current turn"
    stop += "; the Esc declines the open prompt. " if reason == "dialog_open" else ". "
    if background is False:
        then = "Then exit and resume the session, which loads the new plugins and instructions without compaction, "
    else:
        then = (f"The session may still owe a background task, subagent, or monitor, so it is not exited. Then send {commands}, "
                "which Claude Code may refuse if MCP tools changed; --force is never used, ")
    interrupt = (f"{stop}{then}and ask it to continue the work it was doing. "
                 "When the turn does not stop within 15 seconds, nothing more is sent.")
    return [{"choice": "wait", "effect": wait}, {"choice": "interrupt", "effect": interrupt},
            {"choice": "skip", "effect": "Nothing is sent to this session."}]


def question_record(question_id: str, entry: dict) -> dict:
    """The saved question for one session that ended its pass as `awaiting_answer`; `handle` stays in the run state only."""
    return {"id": question_id, "handle": entry["handle"], "terminal": f"…{entry['handle'][-6:]}", "host": entry["host"],
            "worktree": entry.get("worktree"), "title": entry.get("title"), "reason": entry["ask"],
            "background": entry.get("background"), "options": options_for(entry), "answer": None,
            "session": entry.get("asked_transcript"), "input_unrestorable": bool(entry.get("input_unrestorable"))}


def codex_options(session: dict) -> list[dict]:
    """The answers to a Codex install question: no Esc reaches a session outside Orca or the session running the skill, so
    they get `wait` and `skip` only."""
    subject = "this session" if session["own"] else "the session"
    options = [{"choice": "wait", "effect": (
        f"Nothing is sent now. The helper installs the Codex update once {subject} and every other session answered wait has "
        "ended its turn, then resumes the Codex sessions on replaced plugin folders, within one hour.")}]
    if not (session["own"] or session["outside_orca"]):
        options.append({"choice": "interrupt", "effect": (
            "Once every session answered wait has ended its turn, press Esc once in the session and confirm its turn aborted, install the "
            "Codex update, resume the session, and ask it to continue the work it was doing. When no turn abort is recorded within "
            "15 seconds, nothing more is sent to it and the update waits for its turn to end.")})
    return [*options, {"choice": "skip", "effect": "No Codex update this run; nothing is sent to any Codex session."}]


def codex_question_record(question_id: str, session: dict) -> dict:
    """The saved question for one busy Codex session that holds back the Codex install; `handle` and `rollout` stay in the run state only."""
    handle = session["handle"]
    return {"id": question_id, "handle": handle, "terminal": f"…{handle[-6:]}" if handle else None, "host": "codex",
            "worktree": session.get("worktree"), "title": None, "reason": CODEX_INSTALL, "background": None,
            "options": codex_options(session), "answer": None, "rollout": session.get("rollout"),
            "outside_orca": session["outside_orca"], "own_session": session["own"]}


def question_view(question: dict) -> dict:
    view = {key: question.get(key) for key in QUESTION_KEYS}
    view.update({key: True for key in CODEX_FLAGS if question.get(key)})
    return {**view, "answer": question.get("answer")} if question.get("answer") else view
