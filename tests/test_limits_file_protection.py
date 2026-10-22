"""Acceptance checks: the database read limits file and its folder stay protected against shell quoting, escapes,
joins, and paths the guard cannot resolve, through the real hook entry points."""
import pytest

from test_approval_guard import bash_event, guard, state  # noqa: F401

LIMITS_NAME = "db-read-limits.json"


@pytest.fixture(autouse=True)
def config_home(state, monkeypatch):  # noqa: F811
    monkeypatch.setenv("XDG_CONFIG_HOME", str(state / "config"))
    folder = state / "config" / "hei5enbug-agent-setup"
    folder.mkdir(parents=True)
    return folder


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def asks_every_time(output):
    return decision(output) == "ask" and output["hookSpecificOutput"]["permissionDecisionReason"].startswith(
        "Asks every time:")


def file_event(tool, path, cwd=None):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": {key: str(path)}}
    if cwd is not None:
        event["cwd"] = str(cwd)
    return event


@pytest.mark.parametrize("command", [
    "printf '%s' '{}' > db-read-lim\"\"its.json",
    "tee db-read-l\\imits.json",
    "mv x db-read-\"limits.json\"",
    "cp x 'db-read-'limits.json",
    "sed -i s/a/b/ db-read-li\"mits\".json",
    "printf x | tee ./db-read-limits.json",
    "a=db-read-; b=limits.json; echo x > $a$b",
    "echo x > db-read-limits.json",
    "dd if=x of=db-read-lim''its.json",
    "truncate -s 0 db-read-l\\imits.json",
    "install -m 600 x db-read-\"limi\"ts.json",
    "ln -sf x db-read-\"limits\".json",
    "bash -c \"printf x > db-read-lim''its.json\"",
])
def test_따옴표와_이스케이프와_이어_붙이기로_쪼갠_한도_파일_이름도_쓰기면_매번_묻는다(config_home, command):
    # given
    event = bash_event(command, cwd=config_home)
    # when
    output = guard.handle(event, "claude")
    # then
    assert asks_every_time(output)


@pytest.mark.parametrize("command", [
    "echo x > \"$XDG_CONFIG_HOME\"/hei5enbug-agent-setup/db-read-lim\"\"its.json",
    "mv \"{folder}/db-read-\"limits.json {folder}/old.json",
    "rm -r {folder}",
    "rm -rf \"{parent}/hei5enbug-agent-\"setup",
    "rm -rf {folder}/",
    "mv {folder} {folder}.bak",
    "rm -rf {config}",
    "mv {config} {config}.bak",
])
def test_절대_경로와_폴더_자체를_지우거나_옮기는_명령도_매번_묻는다(config_home, state, command):
    # given
    text = command.format(folder=config_home, parent=config_home.parent, config=config_home.parent)
    event = bash_event(text, cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert asks_every_time(output)


@pytest.mark.parametrize("command", [
    "cd {folder} && printf x > \"$(cat name.txt)\"",
    "printf x > \"$TARGET_FILE\"",
    "printf x | tee \"$TARGET_FILE\"",
    "mv x \"$(echo y)\"",
    "cp x `echo y`",
    "sed -i s/a/b/ \"$TARGET_FILE\"",
])
def test_풀지_못한_경로의_쓰기는_작업_폴더가_한도_폴더_안이면_매번_묻는다(config_home, command):
    # given
    event = bash_event(command.format(folder=config_home), cwd=config_home)
    # when
    output = guard.handle(event, "claude")
    # then
    assert asks_every_time(output)


@pytest.mark.parametrize("command", [
    "printf x > \"$TARGET_FILE\"", "printf x | tee \"$TARGET_FILE\"", "mv x \"$(echo y)\"",
])
def test_풀지_못한_경로의_쓰기도_한도_폴더와_무관하면_이_규칙으로_묻지_않는다(state, command):
    # given
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert not asks_every_time(output)


@pytest.mark.parametrize("command", [
    "cat db-read-limits.json", "cat db-read-lim\"\"its.json", "grep cost db-read-l\\imits.json",
    "ls -l {folder}", "wc -c db-read-limits.json", "head -c 10 'db-read-'limits.json",
])
def test_한도_파일을_읽기만_하는_명령은_이름을_쪼개도_묻지_않는다(config_home, command):
    # given
    event = bash_event(command.format(folder=config_home), cwd=config_home)
    # when
    output = guard.handle(event, "claude")
    # then
    assert not asks_every_time(output)


def test_한도_파일과_무관한_쓰기는_한도_폴더_밖에서_묻지_않는다(state):
    # given
    event = bash_event("printf x > notes.txt", cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert not asks_every_time(output)


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_편집_도구가_절대_경로와_상대_경로와_링크로_한도_파일을_바꾸면_매번_묻는다(config_home, state, tool):
    # given
    link = state / "alias.json"
    link.symlink_to(config_home / LIMITS_NAME)
    events = [file_event(tool, config_home / LIMITS_NAME), file_event(tool, LIMITS_NAME, cwd=config_home),
              file_event(tool, f"../hei5enbug-agent-setup/{LIMITS_NAME}", cwd=config_home),
              file_event(tool, link)]
    # when
    outputs = [guard.handle(event, "claude") for event in events]
    # then
    assert all(asks_every_time(output) for output in outputs)


@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_한도_폴더의_다른_파일을_편집하는_것은_묻지_않는다(config_home, tool):
    # given
    event = file_event(tool, config_home / "notes.txt")
    # when
    output = guard.handle(event, "claude")
    # then
    assert not asks_every_time(output)
