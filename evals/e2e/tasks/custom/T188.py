"""Evidence for the three research-report routing cases."""

import json
import re

SKILL = "research-report-writer"
PATH = f"{SKILL}/SKILL.md"
READ = re.compile(r"(?:^|[;&|(\s])(?:cat|sed|rg|grep|head|tail|nl|less|more|awk|bat)\s")
REFERENCE = re.compile(r"research-report-writer|research.report skill|(?:연구|조사|검증).{0,13}(?:스킬|보고서 작성)", re.I)
QUESTION = re.compile(r"[?？]|할까요|할지|해도 될|would you|should (?:I|we)", re.I)
ADVICE = re.compile(r"추천|권장|제안|쓰면|쓸까요|사용하|consider|recommend|suggest|use", re.I)
NEGATION = re.compile(r"(?:사용|추천|권장|제안)하지\s*않|쓰지\s*않|(?:did not|do not|didn't|won't)\s+(?:use|recommend)", re.I)
QUESTION_TOOLS = {"AskUserQuestion", "request_user_input", "request_user_input_async"}
WORK = re.compile(r"(?:^|[/\s\"'])logs(?:/|[\"'\s]|$)|research-report-writer/SKILL\.md|(?:^|[/\s\"'])out/report\.md")
SHELL_WRITE = re.compile(r"(?:^|[;&|(\s])(?:tee|touch|mkdir|cp|mv|rm|apply_patch)\s|(?:^|[^<])>{1,2}\s*[^\s&>]")


def value(ok, passed, failed):
    return bool(ok), passed if ok else failed, {}


def skill_loaded(call):
    output = str(call.get("result_text") or "")
    if call.get("is_error") or not output.strip():
        return False
    inputs = call.get("input") or {}
    name = call.get("name")
    if name == "Skill":
        return str(inputs.get("skill", "")).rsplit(":", 1)[-1] == SKILL
    has_body = "# Research Report Writer" in output or "name: research-report-writer" in output
    if name == "Read":
        return str(inputs.get("file_path", "")).endswith(PATH) and has_body
    command = str(inputs.get("command", ""))
    return name == "Bash" and "SKILL.md" in command and bool(READ.search(command)) and has_body


def stream_events(ctx):
    stream = ctx.work.parents[1] / "stream.jsonl"
    if not stream.is_file():
        return
    with stream.open(encoding="utf-8") as events:
        for line in events:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def run_loaded_skill(ctx):
    if any(skill_loaded(call) for call in ctx.view.get("tool_calls", [])):
        return True
    for event in stream_events(ctx):
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "command_execution":
            call = {"name": "Bash", "input": {"command": item.get("command")},
                    "result_text": item.get("aggregated_output"), "is_error": item.get("exit_code") != 0}
            if skill_loaded(call):
                return True
    return False


def asks_about_skill(view):
    messages = [*view.get("assistant_texts", []), view.get("final_answer", "")]
    messages.extend(json.dumps(call.get("input") or {}, ensure_ascii=False)
                    for call in view.get("tool_calls", []) if call.get("name") in QUESTION_TOOLS)
    return any(REFERENCE.search(message) and QUESTION.search(message) for message in messages)


def direct_skill_started(ctx):
    ok = run_loaded_skill(ctx) and not asks_about_skill(ctx.view)
    return value(ok, "skill started without an opt-in question", "skill was not loaded or asked for opt-in")


def timeout_evidence(ctx):
    path = ctx.repo / "out/report.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    values = all(re.search(pattern, text) for pattern in (
        r"(?<![\d.])5(?![\d.])", r"(?<![\d.])10(?![\d.])",
        r"(?<![\d.])(?:12|0\.12)(?![\d.])", r"(?<![\d.])(?:4|0\.04)(?![\d.])",
    ))
    return value(values, "both settings and observed error values are reported", "a seeded setting or error value is missing")


LISTING_SEGMENT = re.compile(r"^(?:pwd|ls(?:\s.*)?|rg\s+--files(?:\s.*)?|find\s.*|fd(?:\s.*)?|head(?:\s+-n?\s*\d+)?|sort|wc\s+-l)$")


def lists_names_only(command):
    """True when every part of a shell command only lists file names, without reading any file's content."""
    segments = [part.strip() for part in re.split(r"&&|\|\||[;|]", command) if part.strip()]
    return bool(segments) and all(LISTING_SEGMENT.match(part) for part in segments)


def inputs_are_work(name, inputs):
    if name in {"Write", "Edit", "MultiEdit", "ApplyPatch", "apply_patch"}:
        return True
    if name == "Skill" and str(inputs.get("skill", "")).rsplit(":", 1)[-1] == SKILL:
        return True
    command = str(inputs.get("command") or "")
    if name == "Bash" and SHELL_WRITE.search(command):
        return True
    if name == "Bash" and lists_names_only(command):
        return False
    return name not in QUESTION_TOOLS and bool(WORK.search(json.dumps(inputs, ensure_ascii=False)))


def consent_before_tool_work(ctx, tool_use_id):
    for call in ctx.view.get("tool_calls", []):
        if call.get("id") == tool_use_id:
            return True
        if inputs_are_work(call.get("name"), call.get("input") or {}):
            return False
    return False


def consent_before_text_work(ctx, question):
    last_message = ""
    for event in stream_events(ctx):
        kind = event.get("type")
        if kind == "result" and str(event.get("result", "")).strip() == question:
            return True
        if kind == "assistant":
            for block in (event.get("message") or {}).get("content", []):
                if block.get("type") == "tool_use" and inputs_are_work(block.get("name"), block.get("input") or {}):
                    return False
        item = event.get("item") or {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            last_message = str(item.get("text", "")).strip()
        if kind in {"item.started", "item.completed"} and item.get("type") == "command_execution":
            if inputs_are_work("Bash", {"command": item.get("command")}):
                return False
        if kind in {"item.started", "item.completed"} and item.get("type") == "file_change":
            return False
        if kind == "turn.completed" and last_message == question:
            return True
    return False


def skill_started_after_consent(ctx):
    exchanges = [exchange for exchange in ctx.view.get("user_exchanges", [])
                 if "use-research-skill" in exchange.get("matched", [])]
    if len(exchanges) != 1 or not exchanges[0].get("answered"):
        return False, "expected one answered opt-in question", {}
    answer = exchanges[0]
    if answer.get("edited"):
        return False, "files were changed before consent", {}
    ident = answer.get("tool_use_id")
    ordered = consent_before_tool_work(ctx, ident) if ident else consent_before_text_work(ctx, answer["question"].strip())
    loaded = any(skill_loaded(call) for call in ctx.view.get("tool_calls", []))
    return value(ordered and loaded, "one opt-in preceded analysis and skill loading",
                 "analysis or skill loading preceded consent, or the order could not be verified")


def skill_not_suggested(ctx):
    view = ctx.view
    seen = [*view.get("assistant_texts", []), view.get("final_answer", "")]
    seen.extend(json.dumps(call.get("input") or {}, ensure_ascii=False)
                for call in view.get("tool_calls", []) if call.get("name") in QUESTION_TOOLS)
    recommended = any(REFERENCE.search(text) and ADVICE.search(text) and not NEGATION.search(text)
                      for message in seen for text in message.splitlines())
    ok = not run_loaded_skill(ctx) and not recommended and not asks_about_skill(view)
    return value(ok, "README task did not use or recommend the skill", "the research skill was loaded or suggested")
