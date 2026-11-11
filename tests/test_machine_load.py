import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

import machine_load  # noqa: E402
from test_approval_guard import guard, state  # noqa: E402,F401

CPUS = 8


def counters(load=1.0, memory=0.30, storage=0.30):
    return machine_load.Counters(load * CPUS, CPUS, memory, storage)


def prompt(session="s1"):
    return {"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": "Continue", "cwd": "/tmp"}


def machine_lines(output):
    if output is None:
        return []
    context = output["hookSpecificOutput"]["additionalContext"]
    return [line for line in context.splitlines() if line.startswith("Machine load:")]


@pytest.fixture
def reading(state, monkeypatch):
    current = {"value": counters()}
    monkeypatch.setattr(machine_load, "system_counters", lambda cwd: current["value"])
    return current


def test_부하가_논리_CPU의_두_배_이상이면_첫_프롬프트에만_CPU_줄을_한_번_넣고_내려갔다_오르면_다시_넣는다(reading):
    # given
    reading["value"] = counters(load=2.5)
    # when
    first = machine_lines(guard.handle(prompt(), "claude"))
    second = machine_lines(guard.handle(prompt(), "claude"))
    reading["value"] = counters(load=1.0)
    calm = machine_lines(guard.handle(prompt(), "claude"))
    reading["value"] = counters(load=2.5)
    again = machine_lines(guard.handle(prompt(), "claude"))
    # then
    assert len(first) == 1 and "CPU" in first[0] and "20.0" in first[0] and "notice at 16.0" in first[0]
    assert second == [] and calm == []
    assert len(again) == 1


def test_상태를_쓰기_전_정리_중에_시간이_다_되면_알림을_표시한_것으로_기록하지_않아_다음_프롬프트에_다시_보인다(state, monkeypatch):
    # given
    import approval_state
    import hook_runtime
    real = approval_state._cleanup

    def timed_out(directory, keep):
        raise hook_runtime.HookTimeout

    monkeypatch.setattr(approval_state, "_cleanup", timed_out)
    # when
    with pytest.raises(hook_runtime.HookTimeout):
        approval_state.machine_load_shown("claude", "s1", True)
    monkeypatch.setattr(approval_state, "_cleanup", real)
    retried = approval_state.machine_load_shown("claude", "s1", True)
    # then
    assert retried is True


def test_가용_메모리가_10퍼센트_미만이면_메모리를_이름으로_밝히고_현재_값과_기준을_담는다(reading):
    # given
    reading["value"] = counters(memory=0.08)
    # when
    lines = machine_lines(guard.handle(prompt(), "claude"))
    # then
    assert len(lines) == 1 and "memory" in lines[0] and "8%" in lines[0] and "below 10%" in lines[0]
    assert "CPU" not in lines[0] and "storage" not in lines[0]


def test_작업_폴더_볼륨의_여유가_10퍼센트_미만이면_저장_공간을_밝히고_공간_확보를_권한다(reading):
    # given
    reading["value"] = counters(storage=0.05)
    # when
    lines = machine_lines(guard.handle(prompt(), "codex"))
    # then
    assert len(lines) == 1 and "storage" in lines[0] and "5%" in lines[0] and "freeing space" in lines[0]
    assert "waiting does not help" in lines[0]


def test_세_값이_모두_충분하면_줄을_넣지_않는다(reading):
    # given
    reading["value"] = counters(load=1.0, memory=0.30, storage=0.30)
    # when
    lines = machine_lines(guard.handle(prompt(), "claude"))
    # then
    assert lines == []


def test_CPU와_메모리가_함께_부족하면_한_줄에_둘을_모두_밝히고_세션마다_따로_센다(reading):
    # given
    reading["value"] = counters(load=3.0, memory=0.05)
    # when
    first = machine_lines(guard.handle(prompt("s1"), "claude"))
    other = machine_lines(guard.handle(prompt("s2"), "claude"))
    # then
    assert len(first) == 1 and "CPU" in first[0] and "memory" in first[0]
    assert len(other) == 1


def test_읽지_못한_계수기는_조용히_부족으로_치지_않는다(reading):
    # given
    reading["value"] = machine_load.Counters(None, None, None, None)
    # when
    lines = machine_lines(guard.handle(prompt(), "claude"))
    # then
    assert lines == []


def test_실제_계수기는_프로세스를_시작하지_않고_값을_읽는다(monkeypatch):
    # given
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError("a process was started")
    monkeypatch.delenv(machine_load.TEST_OVERRIDE, raising=False)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    # when
    found = machine_load.system_counters("/tmp")
    # then
    assert found.cpu_count and found.cpu_count >= 1
    assert found.storage_free_fraction is None or 0 <= found.storage_free_fraction <= 1


def test_proc_meminfo_본문에서_가용_비율을_계산한다():
    # given
    text = "MemTotal:       16000000 kB\nMemFree:  100 kB\nMemAvailable:    1600000 kB\n"
    # when
    fraction = machine_load.meminfo_fraction(text)
    # then
    assert fraction == pytest.approx(0.10)
    assert machine_load.meminfo_fraction("MemTotal: 5 kB\n") is None
