"""Shared by the custom checks of the text tasks: run scripts/text_review.py on a finished text.

`review` and `check` exit 0 without findings and 1 with findings. Any other exit means no verdict, so the check
raises NoVerdict, which the harness records as grade_error and `regrade` can retry. A test replaces the script
through a JSON file named by E2E_TEXT_REVIEW_STUB: {"review": {"output": "...", "exit_code": 0}, "check": {...}}.
When the first review returns findings, the same text is reviewed once more and the check fails only when both
reviews return findings. The optional stub entry "review_again" answers that second review; without it "review"
answers both.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

STUB_ENV = "E2E_TEXT_REVIEW_STUB"
TIMEOUT_SECONDS = 1700
FINDING_LIMIT = 6
RAN_REVIEW = re.compile(r"text_review\.py[\"']?\s+review\b")


class NoVerdict(RuntimeError):
    no_verdict = True


def repository_root(ctx) -> Path:
    return Path(ctx.tasks_root).resolve().parents[2]


def run_script(ctx, command: str, args: list[str], again: bool = False) -> tuple[int, str]:
    stub = os.environ.get(STUB_ENV)
    if stub:
        seeded = json.loads(Path(stub).read_text(encoding="utf-8"))
        entry = seeded[f"{command}_again"] if again and f"{command}_again" in seeded else seeded[command]
        return int(entry["exit_code"]), str(entry["output"])
    script = repository_root(ctx) / "scripts" / "text_review.py"
    try:
        completed = subprocess.run([sys.executable, str(script), command, *args], cwd=ctx.work, capture_output=True,
                                   text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NoVerdict(f"text_review.py {command} did not finish: {error}") from error
    return completed.returncode, completed.stdout


def findings_of(output: str) -> list:
    try:
        parsed = json.loads(output)
    except ValueError:
        return []
    found = parsed.get("findings") if isinstance(parsed, dict) else None
    return found if isinstance(found, list) else []


def verdict(command: str, code: int, output: str) -> tuple[bool, str, dict]:
    if code == 0:
        return True, "no findings", {}
    if code == 1:
        findings = findings_of(output)
        shown = "; ".join(json.dumps(item, ensure_ascii=False) for item in findings[:FINDING_LIMIT])
        return False, f"{len(findings)} finding(s): {shown}" if findings else f"findings: {output[:400]}", {
            "findings": findings}
    raise NoVerdict(f"text_review.py {command} exited {code}: {output[:400]}")


def existing(ctx, relative: str) -> Path | None:
    path = Path(ctx.repo) / relative
    return path if path.is_file() and path.read_text(encoding="utf-8", errors="replace").strip() else None


def side_file(ctx, name: str, text: str) -> Path:
    path = Path(ctx.work) / "text_review" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def review(ctx, kind: str, draft: Path | None, rules: str | None = None, sources: tuple = (),
           budget: int | None = None, no_ticket_keys: bool = False) -> tuple[bool, str, dict]:
    if draft is None:
        return False, "no text was written", {}
    args = ["--kind", kind, "--draft", str(draft), "--reviews", "1"]
    rules_file = existing(ctx, rules) if rules else None
    if rules_file:
        args += ["--rules", str(rules_file)]
    for source in sources:
        path = Path(source) if isinstance(source, Path) else existing(ctx, source)
        if path:
            args += ["--source", str(path)]
    if budget:
        args += ["--budget", str(budget)]
    if no_ticket_keys:
        args.append("--no-ticket-keys")
    code, output = run_script(ctx, "review", args)
    first = verdict("review", code, output)
    if first[0]:
        return first
    code, output = run_script(ctx, "review", args, again=True)
    second = verdict("review", code, output)
    reviews = [{"findings": first[2].get("findings", [])}, {"findings": second[2].get("findings", [])}]
    if second[0]:
        return True, f"no findings on the second review; first review: {first[1]}", {"findings": [], "reviews": reviews}
    return False, f"first review: {first[1]}; second review: {second[1]}", {"findings": second[2].get("findings", []),
                                                                         "reviews": reviews}


def check(ctx, kind: str, draft: Path | None) -> tuple[bool, str, dict]:
    if draft is None:
        return False, "no text was written", {}
    code, output = run_script(ctx, "check", ["--kind", kind, str(draft)])
    return verdict("check", code, output)


def ran_text_review(ctx) -> tuple[bool, str, dict]:
    commands = [str(call.get("input", {}).get("command", "")) for call in ctx.view.get("tool_calls", [])
                if call.get("name") == "Bash"]
    ran = [command[:120] for command in commands if RAN_REVIEW.search(command)]
    return bool(ran), f"{len(ran)} review run(s)" if ran else "text_review.py review was never run", {"runs": ran}


def final_answer_file(ctx) -> Path | None:
    text = str(ctx.view.get("final_answer", "")).strip()
    return side_file(ctx, "final-answer.txt", text) if text else None


def head_message_file(ctx) -> Path | None:
    message = ctx.git("log", "-1", "--format=%B", f"{ctx.base}..HEAD").strip()
    return side_file(ctx, "commit-message.txt", message + "\n") if message else None


def patch_file(ctx, name: str = "change.patch") -> Path:
    ctx.git("add", "-N", ".")
    return side_file(ctx, name, ctx.git("diff", ctx.base))


def base_patch_file(ctx, name: str = "base.patch") -> Path:
    return side_file(ctx, name, ctx.git("show", "--format=", ctx.base))


def text_of(ctx, relative: str) -> str | None:
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
