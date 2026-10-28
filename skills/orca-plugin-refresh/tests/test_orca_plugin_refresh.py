from __future__ import annotations

import contextlib
import importlib.util
import io
import itertools
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "orca_plugin_refresh.py"
SPEC = importlib.util.spec_from_file_location("orca_plugin_refresh_under_test", SCRIPT)
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)
import refresh_core
import refresh_follow
import refresh_host_record
import refresh_install
import refresh_plugins
import refresh_screen
import refresh_sessions

CLAUDE_EMPTY = [
    "❯ /reload-plugins",
    "  ⎿  Reloaded: 7 plugins · 28 skills",
    "─" * 40,
    "❯ ",
    "─" * 40,
    "  ⏵⏵ auto mode on (shift+tab to cycle)",
]
CODEX_EMPTY = [
    "› old prompt",
    "• answer",
    "› Ask Codex to do anything",
    "  GPT-6-Luna low · /tmp/work",
    "  ? for shortcuts",
]


class FakeOrca:
    def __init__(self, terminals, *, busy=None, screens=None, on_send=None, ghosts=None, typed=None):
        self.list = terminals
        self.busy = dict(busy or {})
        self.screens = {handle: list(lines) for handle, lines in (screens or {}).items()}
        self.on_send = on_send
        self.ghosts = dict(ghosts or {})
        self.typed = dict(typed or {})
        self.sent: list[tuple[str, str]] = []
        self.keystrokes: list[tuple[str, str]] = []

    def terminals(self):
        return [dict(item) for item in self.list]

    def idle(self, handle):
        remaining = self.busy.get(handle, 0)
        if remaining:
            self.busy[handle] = remaining - 1
            return False
        return True

    def screen(self, handle):
        return list(self.screens.get(handle, CLAUDE_EMPTY)), self.draft(handle)

    def draft(self, handle):
        return self.typed.get(handle) or self.ghosts.get(handle)

    def keys(self, handle, text):
        self.keystrokes.append((handle, text))
        current = self.typed.get(handle, "")
        self.typed[handle] = current[:-1] if text == refresh.BACKSPACE else current + text
        if getattr(self, "on_keys", None):
            self.on_keys(self, handle, text)

    def show(self, handle, line):
        lines = self.screens.setdefault(handle, list(CLAUDE_EMPTY))
        composer = max(index for index, text in enumerate(lines) if text.strip().startswith(("❯", "›")))
        lines.insert(composer - 1 if lines[composer].strip().startswith("❯") else composer, line)

    def send(self, handle, text):
        self.sent.append((handle, text))
        if self.on_send:
            self.on_send(self, handle, text)

    def wait_idle(self, handle, timeout_ms, track=None):
        self.waits = getattr(self, "waits", []) + [handle]
        if handle in getattr(self, "wait_errors", set()):
            raise refresh.RefreshError("orca_rejected", "wait failed")
        if handle in getattr(self, "never_idle", set()):
            return False
        self.busy[handle] = 0
        return True


def terminal(handle, host):
    return {"handle": handle, "agentIdentity": host, "connected": True, "writable": True, "orphaned": False, "title": handle, "worktreePath": "/tmp/work"}


def user_record(text):
    return {"type": "user", "message": {"role": "user", "content": text}, "timestamp": refresh.now()}


def assistant_record(*parts):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(parts) or [{"type": "text", "text": "answer"}]},
            "timestamp": refresh.now()}


def result_record(text):
    content = [{"type": "tool_result", "tool_use_id": "toolu_demo", "content": text}]
    return {"type": "user", "message": {"role": "user", "content": content}, "timestamp": refresh.now()}


def tool_use(name, **arguments):
    return {"type": "tool_use", "id": "toolu_demo", "name": name, "input": arguments}


def turn_end():
    return {"type": "system", "subtype": "turn_duration", "durationMs": 1, "timestamp": refresh.now()}


FINISHED_TURN = [user_record("질문"), assistant_record(), turn_end()]
RUNNING_TURN = [*FINISHED_TURN, user_record("다음 질문"), assistant_record()]


def write_records(path, records, partial=""):
    Path(path).write_text("".join(json.dumps(record) + "\n" for record in records) + partial)
    return path


class InputStateTest(unittest.TestCase):
    def test_Claude_입력창은_비었거나_안내_문구일_때만_빈_것으로_본다(self):
        """구분선 사이 입력 줄이 비었거나 Try 안내 문구면 비었다고 보고, 글자가 있으면 입력 중으로 본다."""
        # Given
        placeholder = CLAUDE_EMPTY[:3] + ['❯ Try "edit <filepath> to..."'] + CLAUDE_EMPTY[4:]
        typed = CLAUDE_EMPTY[:3] + ["❯ 반쯤 쓴 질문"] + CLAUDE_EMPTY[4:]
        multiline = CLAUDE_EMPTY[:3] + ["❯ ", "  둘째 줄"] + CLAUDE_EMPTY[4:]
        titled = CLAUDE_EMPTY[:2] + ["─" * 40 + " demo 세션 ─"] + CLAUDE_EMPTY[3:]
        titled_draft = CLAUDE_EMPTY[:3] + ["❯ ", "  " + "─" * 8 + " demo ─"] + CLAUDE_EMPTY[4:]

        # When
        states = [refresh.input_state("claude", lines) for lines in (CLAUDE_EMPTY, placeholder, typed, multiline, titled, titled_draft, ["no composer"])]

        # Then
        self.assertEqual(["empty", "empty", "text", "text", "empty", "text", "unknown"], states)

    def test_Codex_입력창은_맨_아래_작성줄만_판단한다(self):
        """이전 대화의 › 줄은 무시하고 상태 줄 바로 위의 작성줄만 보며, 시작 중이거나 모양이 다르면 알 수 없음으로 본다."""
        # Given
        typed = CODEX_EMPTY[:2] + ["› 쓰다 만 요청"] + CODEX_EMPTY[3:]
        follow_up = CODEX_EMPTY[:2] + ["› Ask a follow-up question"] + CODEX_EMPTY[3:]
        starting = CODEX_EMPTY[:2] + ["› Waiting for startup"] + CODEX_EMPTY[3:]
        no_footer = CODEX_EMPTY[:3]

        # When
        states = [refresh.input_state("codex", lines) for lines in (CODEX_EMPTY, typed, follow_up, starting, no_footer)]

        # Then
        self.assertEqual(["empty", "text", "empty", "unknown", "unknown"], states)


class ComposerBoundaryTest(unittest.TestCase):
    def test_프롬프트가_없는_구분선_화면을_반복_탐색하지_않는다(self):
        """입력창 후보가 없으면 같은 줄들을 구분선마다 다시 검사하지 않는다."""
        # Given
        lines = ["─" * 40] * 64
        with patch.object(refresh_screen, "opening_rule", wraps=refresh.opening_rule) as opening:
            # When
            state = refresh.input_state("claude", lines)

        # Then
        self.assertEqual("unknown", state)
        self.assertLessEqual(opening.call_count, len(lines))

    def test_초안의_구분선과_프롬프트를_입력창_테두리로_오인하지_않는다(self):
        """들여쓴 구분선이나 프롬프트가 초안에 있으면 작성 중으로 본다."""
        # Given
        rule = "─" * 40
        titled = rule + " demo ─"
        cases = [
            [rule, "❯ ", "  " + "─" * 8, rule],
            [titled, "❯ ", "  " + "─" * 8, "  more", rule],
            [titled, "❯ ", "  " + "─" * 8, "  ❯ ", rule],
            ["  " + rule, "  ❯ ", "    " + rule, "    ❯ ", "  " + rule],
            [rule, "❯ ", "    " + rule, "    ❯ ", "  body", rule],
            [rule, '❯ Try "edit a file"', "  second line", rule],
        ]

        # When
        observed = [refresh.input_state("claude", lines) for lines in cases]

        # Then
        self.assertEqual(["text"] * len(cases), observed)

    def test_테두리의_공백이_달라도_빈_입력창을_인식한다(self):
        """위아래 테두리와 프롬프트의 공백이 달라도 빈 입력창은 빈 것으로 본다."""
        # Given
        rule = "─" * 40
        cases = [
            ["  " + rule, "❯ ", "  " + rule],
            ["  " + rule, "  ❯ ", "  " + rule],
            ["  " + rule, "❯ ", rule],
            [rule + " demo ─", "❯ ", "  " + rule],
        ]

        # When
        observed = [refresh.input_state("claude", lines) for lines in cases]

        # Then
        self.assertEqual(["empty"] * len(cases), observed)

    def test_명령_완료는_초안이_아닌_입력창_위의_마지막_항목에서_판단한다(self):
        """초안 속 가짜 결과는 무시하고 입력창 위의 실제 최신 결과만 인정한다."""
        # Given
        rule = "─" * 40
        titled = rule + " demo ─"
        result = "Reloaded: 7 plugins"
        cases = [
            ["❯ /other", "other", titled, "❯ /reload-plugins", result, "  " + rule, rule],
            ["❯ /other", "other", rule, "❯ ", "  " + rule, "  ❯ /reload-plugins", result, rule],
            ["❯ /reload-plugins", result, titled, "❯ draft", "  " + rule, rule],
            ["❯ /reload-plugins", result, "  " + rule, "  ❯ ", "  " + rule],
            ["❯ /reload-plugins", result, "❯ /other", "other", rule, "❯ ", rule],
        ]

        # When
        observed = [refresh.last_item_is(lines, "/reload-plugins", refresh.RELOAD_DONE) for lines in cases]

        # Then
        self.assertEqual([False, False, True, True, False], observed)

    def test_초안의_구분선_뒤에도_화면에_보이는_입력은_지우고_보낸다(self):
        """별도 초안 정보가 없어도 화면에 작성 중인 입력이 있으면 입력으로 알아보고, 지운 뒤 보내며 cleared로 알린다."""
        # Given
        rule = "─" * 40
        handle = "term_example"
        item = terminal(handle, "claude")
        fake = FakeOrca([item], screens={handle: [rule, "❯ ", "  " + "─" * 8, "  draft", rule]})

        def erase(orca, name, text):
            if text == refresh.BACKSPACE:
                orca.screens[name] = [rule, "❯ ", rule]
        fake.on_keys = erase
        entry = {"handle": handle, "host": "claude", "status": "pending", "actions": ["reload"]}
        with patch.object(refresh_sessions, "read_marker", return_value=None):
            # When
            refresh.step(fake, entry, {}, {handle: item})

        # Then
        self.assertEqual([(handle, "/reload-plugins")], fake.sent)
        self.assertEqual(refresh.BACKSPACE, fake.keystrokes[0][1])
        self.assertEqual(("sent", "cleared"), (entry["status"], entry["input"]))

    def test_검증은_초안에_적힌_미제출_결과를_완료로_보지_않는다(self):
        """결과 개수가 늘지 않은 상태에서 초안에만 적힌 명령과 결과는 완료가 아니다."""
        # Given
        rule = "─" * 40
        lines = ["❯ /other", "other", rule + " demo ─", "❯ /reload-plugins", "Reloaded: 7 plugins", "  " + "─" * 8, rule]
        handle = "term_example"
        fake = FakeOrca([terminal(handle, "claude")], screens={handle: lines})
        entry = {"handle": handle, "host": "claude", "actions": ["reload"], "sent_at": time.time(),
                 "before": refresh.result_counts(lines), "before_lines": []}
        with patch.object(refresh_sessions, "read_marker", return_value=None), patch.object(refresh_sessions, "transcript_records", return_value=[]):
            # When
            outcome = refresh.verify(fake, entry, {})

        # Then
        self.assertIsNone(outcome)

    def test_검증은_초안에_구분선이_있어도_제출된_결과를_인식한다(self):
        """입력창 위에 제출된 명령 결과가 있으면 초안 속 구분선과 무관하게 완료로 본다."""
        # Given
        rule = "─" * 40
        lines = ["❯ /reload-plugins", "Reloaded: 7 plugins", rule + " demo ─", "❯ draft", "  " + "─" * 8, rule]
        handle = "term_example"
        fake = FakeOrca([terminal(handle, "claude")], screens={handle: lines})
        entry = {"handle": handle, "host": "claude", "actions": ["reload"], "sent_at": time.time(),
                 "before": refresh.result_counts(lines), "before_lines": []}
        with patch.object(refresh_sessions, "read_marker", return_value=None), patch.object(refresh_sessions, "transcript_records", return_value=[]):
            # When
            outcome = refresh.verify(fake, entry, {})

        # Then
        self.assertEqual("done", outcome)


class CompactReasonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "1.0.0"
        self.root.mkdir()
        self.target = {"digest": "new", "root": str(self.root)}

    def marker(self, **changes):
        return {"schema": 1, "host": "codex", "digest": "new", "root": str(self.root), **changes}

    def test_표식과_목표를_비교해_compact_필요_여부를_정한다(self):
        """표식이 없거나 지침이 다르거나 Codex 경로가 바뀌었거나 Claude 옛 경로가 사라졌을 때만 compact가 필요하다."""
        # Given
        cases = [
            ("codex", None, "auto"),
            ("codex", self.marker(digest="old"), "auto"),
            ("codex", self.marker(root="/gone/0.9.0"), "auto"),
            ("claude", self.marker(host="claude", root="/gone/0.9.0"), "auto"),
            ("claude", self.marker(host="claude", root=str(self.root)), "auto"),
            ("codex", self.marker(), "auto"),
            ("codex", self.marker(digest="old"), "never"),
            ("codex", self.marker(), "always"),
        ]

        # When
        reasons = [refresh.compact_reason(host, marker, self.target, mode) for host, marker, mode in cases]

        # Then
        self.assertEqual(
            ["session_started_before_markers", "instructions_changed", "codex_root_replaced", "claude_root_removed", None, None, None, "requested"],
            reasons,
        )


class DriveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"ORCA_USER_DATA_PATH": self.temp.name, "XDG_STATE_HOME": self.temp.name, "ORCA_TERMINAL_HANDLE": "term_self"})
        self.env.start()
        self.addCleanup(self.env.stop)
        for module, name in ((refresh_sessions, "POLL_SECONDS"), (refresh_sessions, "DRAFT_STABLE_SECONDS"),
                             (refresh_follow, "IDLE_CONFIRM_SECONDS"), (refresh_sessions, "PROBE_RECHECK_SECONDS"),
                             (refresh_sessions, "CLEAR_SETTLE_SECONDS"), (refresh_sessions, "TYPE_CONFIRM_SECONDS")):
            patcher = patch.object(module, name, 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.state = {"hosts": {"claude": {"digest": "d", "root": self.temp.name}, "codex": {"digest": "d", "root": self.temp.name}}, "sessions": {}}
        installed = patch.object(refresh_follow, "install_current", return_value=True)
        self.install_current = installed.start()
        self.addCleanup(installed.stop)

    def write_marker(self, handle, host, digest="d", transcript=None):
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "host": host, "root": self.temp.name, "digest": digest, "written_at": refresh.now()}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        (directory / f"{handle}.json").write_text(json.dumps(payload))

    def simulate(self, fake, handle, text):
        if text == "/reload-plugins":
            fake.show(handle, "  ⎿  Reloaded: 7 plugins · 28 skills")
        elif text == "/compact" and handle.startswith("term_claude"):
            self.write_marker(handle, "claude")
        elif text == "/compact":
            fake.show(handle, "• Context compacted · 7s")

    def test_작업_중인_세션은_기다렸다가_reload와_compact를_순서대로_보내고_확인한다(self):
        """Claude는 reload 뒤 compact를 보내 새 표식으로 확인하고, Codex는 compact 표시로 확인하며, 바쁜 세션은 대기 상태가 된 뒤 보낸다."""
        # Given
        self.write_marker("term_claude", "claude", digest="old")
        self.write_marker("term_codex", "codex", digest="old")
        fake = FakeOrca(
            [terminal("term_claude", "claude"), terminal("term_codex", "codex"), terminal("term_shell", None)],
            busy={"term_claude": 2},
            screens={"term_codex": CODEX_EMPTY},
            on_send=self.simulate,
        )
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 60, sleep=lambda seconds: None)

        # Then
        by_handle = {entry["handle"]: entry for entry in sessions}
        self.assertEqual({"term_claude", "term_codex"}, set(by_handle))
        self.assertEqual(("done", ["reload", "compact"]), (by_handle["term_claude"]["status"], by_handle["term_claude"]["completed"]))
        self.assertEqual(("done", ["compact"]), (by_handle["term_codex"]["status"], by_handle["term_codex"]["completed"]))
        self.assertEqual("instructions_load_on_next_turn", by_handle["term_codex"]["note"])
        claude_commands = [text for handle, text in fake.sent if handle == "term_claude"]
        self.assertEqual(["/reload-plugins", "/compact"], claude_commands)

    def test_Orca가_agentIdentity를_빠뜨려도_표식과_화면이_같은_호스트면_세션으로_잡는다(self):
        """agentIdentity가 없는 터미널은 이 플러그인의 세션 표식이 가리키는 호스트의 입력창이 화면 맨 아래에 있을 때만 그 호스트 세션으로 본다."""
        # Given
        exited = CLAUDE_EMPTY + ["Resume this session with: claude --resume demo", "demo@example % "]
        for handle, host in (("term_claude", "claude"), ("term_codex", "codex"), ("term_exited", "claude"),
                             ("term_mismatch", "codex")):
            self.write_marker(handle, host)
        fake = FakeOrca(
            [{**terminal(handle, None), "agentIdentity": None} for handle in
             ("term_claude", "term_codex", "term_exited", "term_mismatch", "term_shell")],
            screens={"term_codex": CODEX_EMPTY, "term_exited": exited, "term_shell": ["demo@example % "]},
        )

        # When
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # Then
        self.assertEqual({"term_claude": "claude", "term_codex": "codex"},
                         {entry["handle"]: entry["host"] for entry in sessions})

    def test_agentIdentity_없이_잡은_세션이_대기_중_끝나_셸이_남으면_보내지_않는다(self):
        """표식으로 잡은 세션은 보내기 직전에도 그 호스트의 입력창이 화면 맨 아래에 있어야 하며, 옛 입력창 아래 셸 프롬프트가 있으면 보내지 않는다."""
        # Given
        self.write_marker("term_claude", "claude")
        live = {"term_claude": {**terminal("term_claude", None), "agentIdentity": None}}
        fake = FakeOrca(list(live.values()))
        entry = refresh.plan_sessions(fake, self.state, "never", [])[0]
        fake.screens["term_claude"] = CLAUDE_EMPTY + ["Resume this session with: claude --resume demo", "demo@example % "]

        # When
        reason, _ = refresh.ready(fake, entry, live)

        # Then
        self.assertEqual("input_unknown", reason)
        self.assertEqual([], fake.sent)

    def test_agentIdentity_없이_잡은_세션은_표식이_다른_호스트로_바뀔_때만_사라진_것으로_본다(self):
        """작업 중 화면이 달라져도 표식이 같은 호스트를 가리키면 남겨 두고, 표식이 사라지거나 다른 호스트면 사라진 것으로 본다."""
        # Given
        self.write_marker("term_claude", "claude")
        entry = {"handle": "term_claude", "host": "claude"}
        live = {"term_claude": {**terminal("term_claude", None), "agentIdentity": None}}
        kept = refresh.terminal_gone(entry, live)
        self.write_marker("term_claude", "codex")

        # When
        switched = refresh.terminal_gone(entry, live)

        # Then
        self.assertEqual((False, True), (kept, switched))

    def test_정확히_알_수_없는_입력이_남은_세션은_줄을_지우고_보낸다(self):
        """Orca 초안 없이 화면에만 보이는 입력은 되돌릴 수 없으므로 지운 뒤 명령을 보내고, 지웠다고 알린다."""
        # Given
        typed = CLAUDE_EMPTY[:3] + ["❯ 쓰던 글"] + CLAUDE_EMPTY[4:]
        fake = FakeOrca([terminal("term_claude", "claude")], screens={"term_claude": typed}, on_send=self.simulate)

        def erase(orca, handle, text):
            if text == refresh.BACKSPACE:
                orca.screens[handle] = list(CLAUDE_EMPTY)
        fake.on_keys = erase
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([("term_claude", "/reload-plugins")], fake.sent)
        self.assertEqual(refresh.BACKSPACE, fake.keystrokes[0][1])
        self.assertEqual(("done", "cleared"), (sessions[0]["status"], sessions[0]["input"]))

    def test_턴이_없던_Codex_세션은_첫_턴에_새_지침을_불러오므로_보내지_않는다(self):
        """Orca가 대기 상태로 보지 않는 새 Codex 세션은 배너만 있고 대화가 없으면 할 일 없음으로 끝내고, 대화가 있으면 계속 기다린다."""
        # Given
        fresh = [">_ OpenAI Codex (v0.159.2)", "  model: GPT-6-Luna low", *CODEX_EMPTY[2:]]
        used = [">_ OpenAI Codex (v0.159.2)", *CODEX_EMPTY]
        fake = FakeOrca(
            [terminal("term_fresh", "codex"), terminal("term_used", "codex")],
            busy={"term_fresh": 10**9, "term_used": 10**9},
            screens={"term_fresh": fresh, "term_used": used},
        )
        sessions = refresh.plan_sessions(fake, self.state, "always", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.3, sleep=lambda seconds: None)

        # Then
        by_handle = {entry["handle"]: entry for entry in sessions}
        self.assertEqual(("done", "fresh_session_loads_on_first_turn"), (by_handle["term_fresh"]["status"], by_handle["term_fresh"]["detail"]))
        self.assertEqual(("skipped", "busy"), (by_handle["term_used"]["status"], by_handle["term_used"]["detail"]))
        self.assertEqual([], fake.sent)

    def test_턴이_없던_Codex_세션이_대기_상태여도_표식이_없거나_낡았으면_명령을_보내지_않고_끝낸다(self):
        """대기 중인 새 Codex 세션은 표식이 없거나 낡아도 compact를 보내지 않고 할 일 없음으로 끝내며, 대화가 있는 세션에는 보낸다."""
        # Given
        fresh = [">_ OpenAI Codex (v0.159.2)", "  model: GPT-6-Luna low", *CODEX_EMPTY[2:]]
        used = [">_ OpenAI Codex (v0.159.2)", *CODEX_EMPTY]
        self.write_marker("term_stale", "codex", digest="old")
        fake = FakeOrca(
            [terminal("term_missing", "codex"), terminal("term_stale", "codex"), terminal("term_used", "codex")],
            screens={"term_missing": fresh, "term_stale": fresh, "term_used": used},
            on_send=self.simulate,
        )
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        by_handle = {entry["handle"]: entry for entry in sessions}
        for handle in ("term_missing", "term_stale"):
            self.assertEqual(("done", "fresh_session_loads_on_first_turn"), (by_handle[handle]["status"], by_handle[handle]["detail"]))
        self.assertEqual([("term_used", "/compact")], fake.sent)

    def test_Claude_추천_문구만_있으면_보내고_실제_입력은_지웠다가_그대로_되돌린다(self):
        """Orca 초안이 추천 문구뿐이면 한 글자 확인 뒤 reload를 보내고, 실제로 친 글은 지운 뒤 보내고 Enter 없이 그대로 되돌린다."""
        # Given
        fake = FakeOrca(
            [terminal("term_ghost", "claude"), terminal("term_typed", "claude")],
            ghosts={"term_ghost": "다음에 할 일 추천", "term_typed": "추천"},
            typed={"term_typed": "쓰던 질문"},
            on_send=self.simulate,
        )
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        with patch.object(refresh.time, "sleep", lambda seconds: None):
            refresh.drive(fake, sessions, self.state, time.time() + 1, sleep=lambda seconds: None)

        # Then
        by_handle = {entry["handle"]: entry for entry in sessions}
        self.assertEqual(("done", ["reload"]), (by_handle["term_ghost"]["status"], by_handle["term_ghost"]["completed"]))
        self.assertEqual(("done", ["reload"], "restored"), (by_handle["term_typed"]["status"], by_handle["term_typed"]["completed"], by_handle["term_typed"]["input"]))
        self.assertEqual("쓰던 질문", fake.draft("term_typed"))
        self.assertEqual("다음에 할 일 추천", fake.draft("term_ghost"))
        self.assertIn(("term_typed", "/reload-plugins"), fake.sent)
        self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_화면에서_결과가_밀려나도_대화_기록으로_reload를_확인한다(self):
        """화면의 결과 줄 개수가 그대로여도 표식에 남은 대화 기록에 보낸 뒤의 reload 결과가 있으면 반영으로 본다."""
        # Given
        transcript = Path(self.temp.name) / "session.jsonl"
        transcript.write_text("")
        self.write_marker("term_claude", "claude")
        marker_file = refresh.SESSION_CONTEXT.marker_directory() / "term_claude.json"
        marker_file.write_text(json.dumps({**json.loads(marker_file.read_text()), "transcript_path": str(transcript)}))

        def record(fake, handle, text):
            entry = {"type": "system", "subtype": "local_command", "timestamp": refresh.now(), "content": "<local-command-stdout>Reloaded: 6 plugins · 27 skills</local-command-stdout>"}
            with transcript.open("a") as stream:
                stream.write(json.dumps(entry) + "\n")
        fake = FakeOrca([terminal("term_claude", "claude")], on_send=record)
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual(("done", ["reload"]), (sessions[0]["status"], sessions[0]["completed"]))

    def compact_refused_session(self, handle, prompts):
        transcript = Path(self.temp.name) / f"{handle}.jsonl"
        commands = [
            {"type": "user", "message": {"role": "user", "content": "/compact"}, "timestamp": "2000-01-01T00:00:00Z"},
            {"type": "user", "message": {"role": "user", "content": "<command-name>/reload-plugins</command-name>"}, "timestamp": "2000-01-01T00:00:00Z"},
            {"type": "user", "message": {"role": "user", "content": "<local-command-caveat>The command below was run directly</local-command-caveat>"}, "timestamp": "2000-01-01T00:00:00Z"},
            {"type": "user", "message": {"role": "user", "content": "<local-command-stdout>Reloaded: 7 plugins</local-command-stdout>"}, "timestamp": "2000-01-01T00:00:00Z"},
        ]
        lines = commands + ([{"type": "user", "message": {"role": "user", "content": "실제 질문"}, "timestamp": "2000-01-01T00:00:00Z"}] if prompts else [])
        transcript.write_text("".join(json.dumps(line) + "\n" for line in lines))
        self.write_marker(handle, "claude", digest="old")
        marker_file = refresh.SESSION_CONTEXT.marker_directory() / f"{handle}.json"
        marker_file.write_text(json.dumps({**json.loads(marker_file.read_text()), "transcript_path": str(transcript)}))

        def respond(fake, sent_handle, text):
            if text == "/compact":
                record = {"type": "system", "subtype": "local_command", "timestamp": refresh.now(), "content": "<local-command-stdout>Not enough messages to compact.</local-command-stdout>"}
                with transcript.open("a") as stream:
                    stream.write(json.dumps(record) + "\n")
            elif text == "/clear":
                self.write_marker(sent_handle, "claude")
        return respond

    def test_compact할_대화가_없는_빈_세션만_clear로_새_지침을_넣는다(self):
        """Claude가 compact할 메시지가 없다고 답하면 사용자 프롬프트가 없는 세션만 /clear로 지침을 넣고, 프롬프트가 있으면 지우지 않고 실패로 알린다."""
        # Given
        empty = self.compact_refused_session("term_claude_empty", prompts=False)
        used = self.compact_refused_session("term_claude_used", prompts=True)
        fake = FakeOrca(
            [terminal("term_claude_empty", "claude"), terminal("term_claude_used", "claude")],
            on_send=lambda fake, handle, text: (empty if handle.endswith("empty") else used)(fake, handle, text),
        )
        sessions = [entry for entry in refresh.plan_sessions(fake, self.state, "auto", []) if entry.update(actions=["compact"]) is None]

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        by_handle = {entry["handle"]: entry for entry in sessions}
        self.assertEqual(("done", ["clear"], "empty_session_cleared"), (by_handle["term_claude_empty"]["status"], by_handle["term_claude_empty"]["completed"], by_handle["term_claude_empty"]["note"]))
        self.assertEqual(("failed", "compact_needs_more_messages"), (by_handle["term_claude_used"]["status"], by_handle["term_claude_used"]["detail"]))
        self.assertNotIn(("term_claude_used", "/clear"), fake.sent)

    def test_MCP_변경으로_reload가_거부되면_실패로_보고한다(self):
        """reload가 --force를 요구하며 거부되면 반영된 것으로 치지 않고 실패 이유를 남긴다."""
        # Given
        def refuse(fake, handle, text):
            fake.show(handle, "  ⎿  This reload changes MCP tools (x) — Run /reload-plugins --force to apply.")
        fake = FakeOrca([terminal("term_claude", "claude")], on_send=refuse)
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 60, sleep=lambda seconds: None)

        # Then
        self.assertEqual(("failed", "reload_needs_force"), (sessions[0]["status"], sessions[0]["detail"]))

    def test_플러그인_업데이트가_실패한_호스트의_세션은_건드리지_않는다(self):
        """해당 호스트 업데이트가 실패했으면 그 호스트 세션은 막힌 것으로 두고 명령을 보내지 않는다."""
        # Given
        state = {"hosts": {"claude": {"error": {"code": "x"}}, "codex": self.state["hosts"]["codex"]}}
        fake = FakeOrca([terminal("term_claude", "claude")])

        # When
        sessions = refresh.plan_sessions(fake, state, "auto", [])
        refresh.drive(fake, sessions, state, time.time() + 60, sleep=lambda seconds: None)

        # Then
        self.assertEqual(("blocked", "claude_update_failed"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual([], fake.sent)


class ReviewRegressionTest(DriveTest):
    def test_추천을_받아들인_입력은_이전_확인_결과로_보내지_않고_다시_확인해_지웠다가_되돌린다(self):
        """reload 전에 추천 문구로 확인했더라도 사용자가 그 추천을 받아들이면 compact 전에 다시 확인하고, 입력으로 판정되면 지운 뒤 보내고 그대로 되돌린다."""
        # Given
        self.write_marker("term_claude", "claude", digest="old")

        def accept_suggestion(fake, handle, text):
            if text == "/reload-plugins":
                fake.show(handle, "  ⎿  Reloaded: 7 plugins")
                fake.typed[handle] = "추천 문구"
            else:
                self.simulate(fake, handle, text)
        fake = FakeOrca([terminal("term_claude", "claude")], ghosts={"term_claude": "추천 문구"}, on_send=accept_suggestion)
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.5, sleep=lambda seconds: None)

        # Then
        self.assertEqual(["/reload-plugins", "/compact"], [text for _, text in fake.sent])
        self.assertEqual([refresh.PROBE_KEY, refresh.BACKSPACE], [text for _, text in fake.keystrokes[:2]])
        self.assertEqual(refresh.PROBE_KEY, fake.keystrokes[2][1])
        self.assertEqual(("done", "restored"), (sessions[0]["status"], sessions[0]["input"]))
        self.assertEqual("추천 문구", fake.draft("term_claude"))

    def test_확인_중에_사용자가_입력하면_지우지_않고_실패로_알린다(self):
        """확인용 글자 뒤에 사용자가 글자를 더 치면 백스페이스를 보내지 않아 사용자 입력을 지우지 않고 그 세션을 실패로 남긴다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], typed={"term_claude": "쓰던 글"})

        def user_types(fake, handle, text):
            if text == refresh.PROBE_KEY:
                fake.typed[handle] += "U"
        fake.on_keys = user_types
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.5, sleep=lambda seconds: None)

        # Then
        self.assertEqual(("failed", "probe_interrupted_check_input"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertNotIn(("term_claude", refresh.BACKSPACE), fake.keystrokes)
        self.assertEqual("쓰던 글xU", fake.draft("term_claude"))
        self.assertEqual([], fake.sent)

    def test_확인_중_추천_문구가_잠시_바뀌어도_입력이_깨끗하면_다시_확인해_보낸다(self):
        """확인용 글자가 남지 않고 초안이 비었거나 원래대로면 실패로 두지 않고 안정된 뒤 다시 확인해 보낸다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], ghosts={"term_claude": "추천 문구"}, on_send=self.simulate)
        replaced = []

        def replace_suggestion(fake, handle, text):
            if text == refresh.PROBE_KEY and not replaced:
                replaced.append(text)
                fake.typed[handle] = ""
                fake.ghosts.pop(handle)
        fake.on_keys = replace_suggestion
        sessions = refresh.plan_sessions(fake, self.state, "never", [])
        restore = lambda seconds: fake.ghosts.setdefault("term_claude", "추천 문구")

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=restore)

        # Then
        self.assertEqual(["/reload-plugins"], [text for _, text in fake.sent])
        self.assertEqual(1, sessions[0]["probe_retries"])
        self.assertEqual([refresh.PROBE_KEY, refresh.PROBE_KEY, refresh.BACKSPACE], [text for _, text in fake.keystrokes])
        self.assertEqual("done", sessions[0]["status"])

    def test_확인_뒤_초안에_다른_글이_섞이면_정리하지_않고_실패로_알린다(self):
        """확인 뒤 초안이 원래 값도 빈 값도 아니면 확인용 글자가 섞였을 수 있어 키를 더 보내지 않고 실패로 남긴다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], typed={"term_claude": "쓰던 글"})

        def mix(fake, handle, text):
            fake.typed[handle] = "다른 글x"
        fake.on_keys = mix
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.5, sleep=lambda seconds: None)

        # Then
        self.assertEqual(("failed", "probe_interrupted_check_input"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual([("term_claude", refresh.PROBE_KEY)], fake.keystrokes)
        self.assertEqual("다른 글x", fake.draft("term_claude"))
        self.assertEqual([], fake.sent)

    def test_확인이_깨끗하게_끊기는_일이_한도를_넘으면_실패로_알린다(self):
        """깨끗한 중단으로 다시 확인하는 횟수에는 한도가 있어 넘으면 입력줄을 확인하라는 실패로 남긴다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], ghosts={"term_claude": "추천 문구"})

        def replace_suggestion(fake, handle, text):
            if text == refresh.PROBE_KEY:
                fake.typed[handle] = ""
                fake.ghosts.pop(handle, None)
        fake.on_keys = replace_suggestion
        sessions = refresh.plan_sessions(fake, self.state, "never", [])
        restore = lambda seconds: fake.ghosts.setdefault("term_claude", "추천 문구")

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=restore)

        # Then
        self.assertEqual(("failed", "probe_interrupted_check_input"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual(refresh.PROBE_RETRIES, sessions[0]["probe_retries"])
        self.assertEqual([refresh.PROBE_KEY] * (refresh.PROBE_RETRIES + 1), [text for _, text in fake.keystrokes])
        self.assertEqual([], fake.sent)

    def test_넘겨받은_세션도_앞서_쓴_재확인_횟수를_이어서_센다(self):
        """도우미에 넘어온 세션은 앞단에서 쓴 재확인 횟수를 이어받아, 한도를 다 쓴 뒤의 중단은 바로 실패로 남긴다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], ghosts={"term_claude": "추천 문구"})

        def replace_suggestion(fake, handle, text):
            if text == refresh.PROBE_KEY:
                fake.typed[handle] = ""
                fake.ghosts.pop(handle, None)
        fake.on_keys = replace_suggestion
        sessions = refresh.plan_sessions(fake, self.state, "never", [])
        sessions[0]["probe_retries"] = refresh.PROBE_RETRIES
        restore = lambda seconds: fake.ghosts.setdefault("term_claude", "추천 문구")

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=restore)

        # Then
        self.assertEqual(("failed", "probe_interrupted_check_input"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual([refresh.PROBE_KEY], [text for _, text in fake.keystrokes])
        self.assertEqual([], fake.sent)

    def test_보내기_직전에_입력이_바뀌면_보내지_않는다(self):
        """준비 확인 뒤 보내기 직전에 초안이 달라지면 명령을 보내지 않고 다시 기다린다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], typed={"term_claude": "방금 친 글"})
        entry = {"handle": "term_claude", "host": "claude", "actions": ["reload"], "status": "pending", "observed_draft": None}

        # When
        with patch.object(refresh_sessions, "ready", return_value=(None, CLAUDE_EMPTY)):
            refresh.step(fake, entry, self.state["hosts"]["claude"], {"term_claude": terminal("term_claude", "claude")})

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("pending", "input_changed"), (entry["status"], entry["detail"]))

    def test_clear_직전에_대화가_생기면_clear하지_않는다(self):
        """빈 세션으로 판정한 뒤 /clear를 보내기 직전에 사용자 프롬프트가 생기면 /clear를 보내지 않는다."""
        # Given
        self.write_marker("term_claude", "claude", digest="old")
        fake = FakeOrca([terminal("term_claude", "claude")])
        entry = {"handle": "term_claude", "host": "claude", "actions": ["clear"], "status": "pending", "detail": "empty_session_needs_clear"}

        # When
        with patch.object(refresh_sessions, "claude_has_prompts", return_value=True):
            refresh.step(fake, entry, self.state["hosts"]["claude"], {"term_claude": terminal("term_claude", "claude")})

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("failed", "compact_needs_more_messages", ["compact:compact_needs_more_messages"]), (entry["status"], entry["detail"], entry["completed"]))

    def test_슬래시로_시작하는_실제_프롬프트는_대화로_센다(self):
        """/review 같은 사용자 명령은 대화로 세고, 스크립트가 보내는 명령과 명령 기록 줄만 대화가 아닌 것으로 본다."""
        # Given
        path = Path(self.temp.name) / "prompts.jsonl"
        base = [{"type": "user", "message": {"content": text}} for text in ("/compact", "<local-command-caveat>x</local-command-caveat>", "<command-name>/clear</command-name>")]
        path.write_text("".join(json.dumps(item) + "\n" for item in base))
        empty = refresh.claude_has_prompts(str(path))

        # When
        with path.open("a") as stream:
            stream.write(json.dumps({"type": "user", "message": {"content": "/review 결제 모듈"}}) + "\n")
        with_review = refresh.claude_has_prompts(str(path))

        # Then
        self.assertEqual((False, True), (empty, with_review))

    def test_기한이_지나면_새_명령은_시작하지_않고_보낸_명령만_확인한다(self):
        """기한이 이미 지났으면 대기 세션에 새 명령을 보내지 않고, 이미 보낸 명령은 결과를 확인할 때까지 기다린다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude"), terminal("term_codex", "codex")], screens={"term_codex": CODEX_EMPTY}, on_send=self.simulate)
        sessions = refresh.plan_sessions(fake, self.state, "always", [])
        codex = next(entry for entry in sessions if entry["host"] == "codex")
        refresh.step(fake, codex, self.state["hosts"]["codex"], {"term_codex": terminal("term_codex", "codex")})

        # When
        refresh.drive(fake, sessions, self.state, time.time() - 1, sleep=lambda seconds: None)

        # Then
        by_host = {entry["host"]: entry for entry in sessions}
        self.assertEqual(("skipped", "deadline_reached"), (by_host["claude"]["status"], by_host["claude"]["detail"]))
        self.assertEqual("done", by_host["codex"]["status"])
        self.assertEqual([("term_codex", "/compact")], fake.sent)

    def test_보내기_전에_있던_결과와_표식은_반영으로_치지_않는다(self):
        """보내기 전 위치 뒤에 추가된 대화 기록만 읽고, 보내기 전과 같은 시각의 표식은 새 결과로 보지 않는다."""
        # Given
        path = Path(self.temp.name) / "offset.jsonl"
        path.write_text(json.dumps({"subtype": "local_command", "content": "Reloaded: 1 plugin"}) + "\n")
        offset = refresh.transcript_size(str(path))
        big = {"type": "compacted", "payload": "x" * (refresh.TRANSCRIPT_TAIL_BYTES + 10)}
        with path.open("a") as stream:
            stream.write(json.dumps(big) + "\n" + '{"partial": ')
        stamp = refresh.now()
        entry = {"marker_before": refresh.parse_time(stamp), "marker_snapshot": {"written_at": stamp, "digest": "d"}}

        # When
        records = refresh.transcript_records(str(path), offset)
        same_marker = refresh.newer_marker(entry, {"written_at": stamp, "digest": "d"}, {"digest": "d"})

        # Then
        self.assertEqual(["compacted"], [record.get("type") for record in records])
        self.assertEqual("done", refresh.transcript_outcome("codex", "compact", records))
        self.assertFalse(same_marker)

    def test_화면_꼬리_변화만으로는_이전_reload_결과를_새_결과로_보지_않는다(self):
        """보내기 전 화면에도 같은 reload 결과가 마지막 항목이었다면 화면이 바뀌어도 반영으로 판단하지 않는다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")])
        entry = {"handle": "term_claude", "host": "claude", "actions": ["reload"], "status": "sent", "sent_at": time.time(), "before": refresh.result_counts(CLAUDE_EMPTY), "before_lines": CLAUDE_EMPTY, "marker_before": 0.0}
        fake.screens["term_claude"] = CLAUDE_EMPTY[:-1] + ["  ⏵⏵ auto mode on · 12:01"]

        # When
        outcome = refresh.verify(fake, entry, self.state["hosts"]["claude"])

        # Then
        self.assertIsNone(outcome)

    def test_도우미가_없거나_죽은_대기_항목은_다시_처리한다(self):
        """이전 실행의 대기 항목은 도우미가 살아 있거나 끝났을 때만 처리된 것으로 보고, 도우미 시작 실패는 실패로 남긴다."""
        # Given
        base = {"sessions": {"term_self": {"status": "queued_after_turn"}}}
        dead = {**base, "self": {"handle": "term_self", "helper_pid": 2**22}}
        running = {**base, "self": {"handle": "term_self", "helper_pid": os.getpid()}}
        fake = FakeOrca([terminal("term_self", "claude")])
        run_id = "c" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})

        # When
        states = [refresh.handled(dead, "term_self"), refresh.handled(running, "term_self")]
        def broken_spawn(run):
            raise OSError("fork failed")
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(run_id, "never", [], 30, spawn=broken_spawn)

        # Then
        self.assertEqual([None, "queued_after_turn"], states)
        self.assertEqual(("failed", "helper_start_failed"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_다른_실행이_보내는_중이면_apply를_시작하지_않는다(self):
        """모든 전송은 하나의 잠금을 공유하므로 다른 실행이 잠금을 쥐고 있으면 apply가 바로 거절된다."""
        # Given
        run_id = "d" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})

        # When
        with refresh.exclusive("sessions"):
            with self.assertRaises(refresh.RefreshError) as refused:
                refresh.command_apply(run_id, "never", [], 30, spawn=lambda run: 1)

        # Then
        self.assertEqual("already_running", refused.exception.code)

    def test_결과_확인_요청은_세션이_준비될_때까지_다시_시도한다(self):
        """자기 세션이 잠깐 작업 중이거나 추천 문구가 떠 있어도 준비될 때까지 기다렸다가 결과 확인 요청을 보낸다."""
        # Given
        fake = FakeOrca([terminal("term_self", "claude")], busy={"term_self": 3}, ghosts={"term_self": "새 추천"})
        entry = {"handle": "term_self", "host": "claude"}

        # When
        outcome = refresh.notify(fake, entry, "e" * 32, sleep=lambda seconds: None)

        # Then
        self.assertEqual("sent", outcome)
        self.assertIn("status --run-id " + "e" * 32, fake.sent[-1][1])
        self.assertEqual("새 추천", fake.draft("term_self"))

    def test_업데이트_뒤에는_새_설치본의_스크립트로_이어간다(self):
        """이 스크립트가 옛 설치본 안에 있으면 업데이트 결과는 새 설치본의 같은 스크립트 경로를 이어 쓸 경로로 돌려준다."""
        # Given
        new_root = Path(self.temp.name) / "new-install"
        relative = Path(refresh.__file__ if hasattr(refresh, "__file__") else SCRIPT).resolve().relative_to(refresh.PLUGIN_ROOT)
        (new_root / relative).parent.mkdir(parents=True)
        (new_root / relative).write_text("# copy")
        hosts = {"codex": {"previous_root": str(refresh.PLUGIN_ROOT), "root": str(new_root)}}

        # When
        script = refresh.continuation_script(hosts)

        # Then
        self.assertEqual(str(new_root / relative), script)


class ApplyTest(DriveTest):
    def save_state(self):
        run_id = "a" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})
        return run_id

    def test_자기_세션은_턴이_끝난_뒤_처리하도록_분리_작업에_넘긴다(self):
        """apply는 다른 세션을 먼저 처리하고, 스킬을 실행한 세션은 분리된 후처리에 맡기며 그 계획을 저장한다."""
        # Given
        self.write_marker("term_codex", "codex")
        fake = FakeOrca([terminal("term_self", "claude"), terminal("term_codex", "codex")], screens={"term_codex": CODEX_EMPTY})
        run_id = self.save_state()
        spawned: list[str] = []

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(run_id, "auto", [], 60, spawn=spawned.append)

        # Then
        statuses = {item["terminal"]: item["status"] for item in result["sessions"]}
        self.assertEqual({"…m_self": "queued_after_turn", "…_codex": "done"}, statuses)
        self.assertEqual([run_id], spawned)
        self.assertEqual([], fake.sent)
        self.assertEqual(["reload", "compact"], refresh.load_run(run_id)["self"]["actions"])

    def test_같은_실행을_다시_돌려도_끝난_세션에는_다시_보내지_않는다(self):
        """재실행은 남은 세션만 처리하고, 이미 compact한 Codex 세션을 표식이 갱신되기 전에 다시 compact하지 않는다."""
        # Given
        self.write_marker("term_codex", "codex", digest="old")
        fake = FakeOrca([terminal("term_codex", "codex")], screens={"term_codex": CODEX_EMPTY}, on_send=self.simulate)
        run_id = self.save_state()
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_apply(run_id, "auto", [], 60, spawn=lambda run: None)
        sent_first = list(fake.sent)

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            second = refresh.command_apply(run_id, "auto", [], 60, spawn=lambda run: None)

        # Then
        self.assertEqual([("term_codex", "/compact")], sent_first)
        self.assertEqual(sent_first, fake.sent)
        self.assertEqual("already_handled_in_this_run", second["sessions"][0]["detail"])

    def test_분리된_후처리는_자기_세션에_반영한_뒤_결과_확인을_요청한다(self):
        """후처리는 자기 세션이 대기 상태가 되면 reload와 compact를 보내고 확인한 뒤 결과 확인 메시지를 보낸다."""
        # Given
        fake = FakeOrca([terminal("term_claude_self", "claude")], on_send=self.simulate)
        run_id = self.save_state()
        state = refresh.load_run(run_id)
        state["self"] = {"handle": "term_claude_self", "host": "claude", "actions": ["reload", "compact"], "title": "t", "worktree": "/tmp/work"}
        refresh.save_json(refresh.run_path(run_id), state)

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_self_apply(run_id, sleep=lambda seconds: None)

        # Then
        commands = [text for _, text in fake.sent]
        self.assertEqual(["/reload-plugins", "/compact"], commands[:2])
        self.assertIn(f"XDG_STATE_HOME={self.temp.name} python3 ", commands[2])
        self.assertIn(f"status --run-id {run_id} --json", commands[2])
        saved = refresh.load_run(run_id)["sessions"]["term_claude_self"]
        self.assertEqual(("done", ["reload", "compact"]), (saved["status"], saved["completed"]))


class FollowUpTest(DriveTest):
    def save_state(test, **extra):
        run_id = "f" * 32
        refresh.save_json(refresh.run_path(run_id), {**test.state, "run_id": run_id, **extra})
        return run_id

    def test_바쁜_세션은_기다리지_않고_도우미_하나에_넘긴다(self):
        """앞단은 쉬는 세션만 바로 처리하고, 바쁜 세션은 기한을 기다리지 않고 도우미 하나에 넘기며 넘긴 내용을 저장한다."""
        # Given
        self.write_marker("term_codex", "codex")
        fake = FakeOrca([terminal("term_self", "claude"), terminal("term_busy", "claude"), terminal("term_codex", "codex")],
                        busy={"term_busy": 10**6}, screens={"term_codex": CODEX_EMPTY})
        run_id = self.save_state()
        spawned: list[str] = []

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(run_id, "never", [], 1, spawn=lambda run: spawned.append(run) or 4242)

        # Then
        statuses = {item["terminal"]: (item["status"], item.get("detail")) for item in result["sessions"]}
        self.assertEqual(("deferred", "busy"), statuses["…m_busy"])
        self.assertEqual("queued_after_turn", statuses["…m_self"][0])
        self.assertEqual([run_id], spawned)
        self.assertTrue(result["ok"])
        saved = refresh.load_run(run_id)
        self.assertEqual(["term_busy"], [item["handle"] for item in saved["follow_up"]])
        self.assertEqual({"handle": "term_self", "host": "claude", "screen_identified": False}, saved["initiator"])
        self.assertEqual(4242, saved["helper"]["pid"])

    def test_표식으로_잡아_미룬_세션의_에이전트가_끝나면_도우미는_명령도_알림도_보내지_않는다(self):
        """agentIdentity 없이 표식과 화면으로 잡은 세션과 시작 세션을 도우미에 넘긴 뒤 둘 다 셸만 남으면, 도우미는 어느 쪽에도 보내지 않는다."""
        # Given
        for handle in ("term_self", "term_busy"):
            self.write_marker(handle, "claude", digest="old")
        bare = [{**terminal(handle, None), "agentIdentity": None} for handle in ("term_self", "term_busy")]
        fake = FakeOrca(bare, busy={"term_busy": 10**6}, on_send=self.simulate)
        run_id = self.save_state()
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_apply(run_id, "auto", [], 1, spawn=lambda run: 4242)
        exited = CLAUDE_EMPTY + ["Resume this session with: claude --resume demo", "demo@example % "]
        fake.screens.update({"term_self": list(exited), "term_busy": list(exited)})
        fake.busy.clear()

        def refuse(orca, handle, text):
            raise AssertionError(f"sent {text!r} to the shell left in {handle}")

        fake.on_send = refuse

        # When
        with (
            patch.object(refresh, "Orca", return_value=fake),
            patch.multiple(refresh, FOLLOW_UP_SECONDS=0.5, SELF_WAIT_SECONDS=0.5, NOTIFY_SECONDS=0.5),
        ):
            saved = refresh.load_run(run_id)
            saved["follow_up"] = [{**item, "deferred_at": time.time()} for item in saved["follow_up"]]
            refresh.save_json(refresh.run_path(run_id), saved)
            refresh.command_self_apply(run_id, sleep=lambda seconds: time.sleep(0.02))

        # Then
        self.assertEqual([], fake.sent)
        self.assertNotEqual("sent", refresh.command_status(run_id)["self_notification"])

    def test_도우미는_대기_완료_콜백을_받은_뒤_보내고_한_번만_알린다(self):
        """도우미는 바쁜 세션의 대기 완료 신호를 받은 뒤 다시 확인하고 보내며, 끝나면 시작한 세션에 결과 확인을 한 번 요청한다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "claude"), terminal("term_self", "claude")], busy={"term_busy": 10**6}, on_send=self.simulate)
        run_id = self.save_state(follow_up=[{"handle": "term_busy", "host": "claude", "actions": ["reload"], "detail": "busy", "deferred_at": time.time()}],
                                 initiator={"handle": "term_self", "host": "claude"})

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_self_apply(run_id, sleep=lambda seconds: None)

        # Then
        self.assertEqual(["term_busy"], fake.waits)
        self.assertEqual([("term_busy", "/reload-plugins")], fake.sent[:1])
        notices = [text for handle, text in fake.sent if handle == "term_self"]
        self.assertEqual(1, len(notices))
        self.assertIn("not refreshed", notices[0])
        status = refresh.command_status(run_id)
        self.assertEqual("done", next(item for item in status["sessions"] if item["terminal"] == "…m_busy")["status"])
        self.assertEqual([], status["not_refreshed"])
        self.assertEqual("sent", status["self_notification"])

    def test_기한까지_쉬지_않은_세션은_보내지_않고_미반영으로_보고한다(self):
        """기한 안에 대기 완료 신호가 없으면 명령을 보내지 않고, 결과의 미반영 목록에 이유와 함께 남긴다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "codex"), terminal("term_self", "claude")], busy={"term_busy": 10**6})
        fake.never_idle = {"term_busy"}
        run_id = self.save_state(follow_up=[{"handle": "term_busy", "host": "codex", "actions": ["compact"], "detail": "busy", "deferred_at": time.time() - refresh.FOLLOW_UP_SECONDS + 0.05}],
                                 initiator={"handle": "term_self", "host": "claude"})

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_self_apply(run_id, sleep=lambda seconds: time.sleep(0.02))

        # Then
        self.assertFalse([item for item in fake.sent if item[0] == "term_busy"])
        status = refresh.command_status(run_id)
        self.assertEqual([("skipped", "not_idle_before_deadline")], [(item["status"], item["detail"]) for item in status["not_refreshed"]])

    def test_대기_콜백이_실패하면_상태_확인으로_이어서_처리한다(self):
        """Orca 대기 호출이 오류를 내면 그 세션만 기존 상태 확인 방식으로 바꿔 기한 안에 처리한다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "claude")], busy={"term_busy": 2}, on_send=self.simulate)
        fake.wait_errors = {"term_busy"}
        entries = [{"handle": "term_busy", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy", "deadline": time.time() + 60, "deferred_at": time.time()}]

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual("done", entries[0]["status"])
        self.assertEqual([("term_busy", "/reload-plugins")], fake.sent)

    def test_입력_상태를_알_수_없어_미뤄진_세션도_기한까지_매번_다시_확인한다(self):
        """바쁨이 아닌 이유로 미뤄진 세션은 한 번만 보고 포기하지 않고, 매 확인마다 다시 읽어 준비되면 보내고 끝까지 안 되면 이유를 남긴다."""
        # Given
        unreadable = ["입력창이 없는 화면"]
        reads: list[str] = []

        def counting(fake):
            original = fake.screen
            fake.screen = lambda handle: (reads.append(handle), original(handle))[1]
            return fake

        ready = counting(FakeOrca([terminal("term_claude", "claude")], screens={"term_claude": list(unreadable)}, on_send=self.simulate))
        recovering = {"handle": "term_claude", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "input_unknown",
                      "deadline": time.time() + 60, "deferred_at": time.time()}

        def recover(seconds):
            if len(reads) >= 3 and not ready.sent:
                ready.screens["term_claude"] = list(CLAUDE_EMPTY[2:])

        stuck = counting(FakeOrca([terminal("term_claude", "claude")], screens={"term_claude": list(unreadable)}))
        now = [1000.0]
        stays = {"handle": "term_claude", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "input_unknown",
                 "deadline": now[0] + 0.3, "deferred_at": now[0]}

        def tick(seconds):
            now[0] += max(seconds, 0.02)

        # When
        refresh.follow_up(ready, [recovering], self.state, sleep=recover)
        recovered_reads = len(reads)
        reads.clear()
        with patch("time.time", lambda: now[0]), patch("time.sleep", tick):
            refresh.follow_up(stuck, [stays], self.state, sleep=tick)

        # Then
        self.assertEqual("done", recovering["status"])
        self.assertEqual([("term_claude", "/reload-plugins")], ready.sent)
        self.assertGreaterEqual(recovered_reads, 4)
        self.assertEqual(("skipped", "input_unknown"), (stays["status"], stays["detail"]))
        self.assertGreater(len(reads), 3)
        self.assertEqual([], stuck.sent)

    def test_기다리는_동안_설치가_바뀌거나_이미_새_지침이면_보내지_않는다(self):
        """보내기 직전에 설치본이 달라졌으면 건너뛰고, 넘긴 뒤 새 지침으로 다시 시작한 세션은 할 일 없음으로 끝낸다."""
        # Given
        fake = FakeOrca([terminal("term_a", "claude"), terminal("term_b", "codex")], screens={"term_b": CODEX_EMPTY})
        handed = time.time() - 1
        self.write_marker("term_b", "codex")
        changed = [{"handle": "term_a", "host": "claude", "actions": ["reload"], "status": "pending", "detail": None, "deadline": time.time() + 60, "deferred_at": handed}]
        restarted = [{"handle": "term_b", "host": "codex", "actions": ["compact"], "status": "pending", "detail": None, "deadline": time.time() + 60, "deferred_at": handed}]

        # When
        self.install_current.return_value = False
        refresh.follow_up(fake, changed, self.state, sleep=lambda seconds: None)
        self.install_current.return_value = True
        refresh.follow_up(fake, restarted, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "install_changed"), (changed[0]["status"], changed[0]["detail"]))
        self.assertEqual(("done", "already_current"), (restarted[0]["status"], restarted[0]["detail"]))

    def test_도우미가_잠금을_얻기_전에_다시_적용해도_도우미를_늘리거나_작업을_지우지_않는다(self):
        """기다리는 도우미가 살아 있으면 새 도우미를 띄우지 않고, 이미 넘긴 세션의 작업 목록은 그대로 둔다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "claude")], busy={"term_busy": 10**6})
        item = {"handle": "term_busy", "host": "claude", "actions": ["reload"], "detail": "busy", "deferred_at": time.time()}
        run_id = self.save_state(sessions={"term_busy": {"status": "deferred"}}, follow_up=[item], helper={"pid": os.getpid()})
        spawned: list[str] = []

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(run_id, "never", [], 1, spawn=lambda run: spawned.append(run) or 1)

        # Then
        self.assertEqual([], spawned)
        self.assertEqual("already_handled_in_this_run", result["sessions"][0]["detail"])
        self.assertEqual([["reload"]], [entry["actions"] for entry in refresh.load_run(run_id)["follow_up"]])

    def test_시작_세션에_할_일이_없으면_도우미가_이전_작업을_다시_보내지_않는다(self):
        """다른 세션만 넘길 때는 저장된 시작 세션 계획을 지워, 끝난 시작 세션에 명령을 다시 보내지 않는다."""
        # Given
        self.write_marker("term_self", "claude")
        fake = FakeOrca([terminal("term_self", "claude"), terminal("term_busy", "claude")], busy={"term_busy": 10**6})
        run_id = self.save_state(**{"self": {"handle": "term_self", "host": "claude", "actions": ["reload"], "title": "t", "worktree": "/tmp/work"},
                                    "sessions": {"term_self": {"status": "done"}}})

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_apply(run_id, "never", [], 1, spawn=lambda run: 7)

        # Then
        saved = refresh.load_run(run_id)
        self.assertNotIn("self", saved)
        self.assertEqual(["term_busy"], [item["handle"] for item in saved["follow_up"]])

    def test_시작_세션도_보내기_전에_설치_변경을_확인한다(self):
        """시작 세션도 기다리는 동안 설치본이 바뀌면 보내지 않는다."""
        # Given
        fake = FakeOrca([terminal("term_self", "claude")])
        entries = [{"handle": "term_self", "host": "claude", "actions": ["reload"], "status": "pending", "initiator": True, "detail": None, "deadline": time.time() + 60, "deferred_at": time.time()}]
        self.install_current.return_value = False

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "install_changed"), (entries[0]["status"], entries[0]["detail"]))

    def test_설치_경로가_바뀐_Codex_세션은_digest가_같아도_최신으로_보지_않는다(self):
        """넘긴 뒤 쓰인 표식이라도 Codex 설치 경로가 다르면 compact를 보낸다."""
        # Given
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "term_codex.json").write_text(json.dumps({"schema": 1, "host": "codex", "root": "/old/root", "digest": "d", "written_at": refresh.now()}))
        fake = FakeOrca([terminal("term_codex", "codex")], screens={"term_codex": CODEX_EMPTY}, on_send=self.simulate)
        entries = [{"handle": "term_codex", "host": "codex", "actions": ["compact"], "status": "pending", "detail": None, "deadline": time.time() + 60, "deferred_at": time.time() - 5}]

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual([("term_codex", "/compact")], fake.sent)
        self.assertEqual("done", entries[0]["status"])

    def test_재확인_중에_기한이_지나면_보내지_않는다(self):
        """한가함 신호 뒤 재확인을 기다리는 동안 기한이 지나면 명령을 보내지 않고 기한 초과로 남긴다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "claude")], busy={"term_busy": 10**6})
        entries = [{"handle": "term_busy", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy", "deadline": time.time() + 60, "deferred_at": time.time()}]

        def expire(seconds):
            if seconds == refresh_follow.IDLE_CONFIRM_SECONDS:
                entries[0]["deadline"] = time.time() - 1

        # When
        with patch.object(refresh_follow, "IDLE_CONFIRM_SECONDS", 0.001):
            refresh.follow_up(fake, entries, self.state, sleep=expire)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "not_idle_before_deadline"), (entries[0]["status"], entries[0]["detail"]))

    def test_대기_프로세스를_시작하지_못하면_상태_확인으로_넘어간다(self):
        """대기 프로세스 생성 오류도 콜백 실패로 보고 그 세션을 기존 상태 확인 방식으로 처리한다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "claude")], busy={"term_busy": 2}, on_send=self.simulate)
        fake.wait_idle = lambda handle, timeout_ms, track=None: (_ for _ in ()).throw(OSError("spawn failed"))
        entries = [{"handle": "term_busy", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy", "deadline": time.time() + 60, "deferred_at": time.time()}]

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual("done", entries[0]["status"])
        self.assertEqual([("term_busy", "/reload-plugins")], fake.sent)

    def test_대기_중인_세션의_터미널이_닫히면_대기를_끝내고_바로_건너뛴다(self):
        """Orca 대기가 막힌 채여도 터미널 목록에서 사라진 세션은 곧바로 terminal_gone으로 건너뛰고 그 대기 프로세스를 종료한다."""
        # Given
        processes = []

        class BlockedOrca(FakeOrca):
            def wait_idle(self, handle, timeout_ms, track=None):
                process = refresh.subprocess.Popen(["sleep", "30"])
                processes.append(process)
                track(process)
                process.wait()
                return False

        fake = BlockedOrca([terminal("term_busy", "claude")], busy={"term_busy": 10**6})
        entries = [{"handle": "term_busy", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy", "deadline": time.time() + 3600, "deferred_at": time.time()}]

        def close_terminal(seconds):
            for _ in range(100):
                if processes:
                    break
                time.sleep(0.02)
            fake.list = []

        # When
        started = time.time()
        refresh.follow_up(fake, entries, self.state, sleep=close_terminal)

        # Then
        self.assertLess(time.time() - started, 10)
        self.assertEqual(("skipped", "terminal_gone", []), (entries[0]["status"], entries[0]["detail"], entries[0]["actions"]))
        self.assertEqual(1, len(processes))
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual([], fake.sent)

    def test_터미널_목록을_잠시_못_읽어도_세션을_사라진_것으로_보지_않는다(self):
        """목록 조회가 일시적으로 실패한 동안은 대기 중인 세션을 건너뛰지 않고, 다시 읽히면 이어서 처리한다."""
        # Given
        fake = FakeOrca([terminal("term_busy", "claude")], busy={"term_busy": 2}, on_send=self.simulate)
        real = fake.terminals
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) in (2, 3):
                raise refresh.RefreshError("orca_rejected", "list failed")
            return real()

        fake.terminals = flaky
        entries = [{"handle": "term_busy", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy", "deadline": time.time() + 60, "deferred_at": time.time()}]
        seen = []

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: seen.append((entries[0]["status"], entries[0]["detail"])))

        # Then
        self.assertIn(("pending", "terminal_list_unavailable"), seen)
        self.assertNotIn("terminal_gone", [detail for _, detail in seen])
        self.assertEqual("done", entries[0]["status"])
        self.assertEqual([("term_busy", "/reload-plugins")], fake.sent)

    def test_끝난_세션은_도우미가_끝나기_전에_실행_상태에_반영한다(self):
        """다른 세션이 아직 기다리는 동안에도 먼저 끝난 세션은 저장된 실행 상태에서 done으로 보이고, 기다리는 세션은 deferred로 남는다."""
        # Given
        fake = FakeOrca([terminal("term_a", "claude"), terminal("term_b", "codex")], busy={"term_a": 10**6, "term_b": 10**6}, on_send=self.simulate)
        fake.never_idle = {"term_b"}
        handed = time.time() - refresh.FOLLOW_UP_SECONDS + 0.4
        run_id = self.save_state(sessions={"term_a": {"status": "deferred"}, "term_b": {"status": "deferred"}},
                                 follow_up=[{"handle": "term_a", "host": "claude", "actions": ["reload"], "detail": "busy", "deferred_at": time.time()},
                                            {"handle": "term_b", "host": "codex", "actions": ["compact"], "detail": "busy", "deferred_at": handed}])
        snapshots = []

        def watch(seconds):
            snapshots.append({handle: item["status"] for handle, item in refresh.load_run(run_id)["sessions"].items()})
            time.sleep(0.02)

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_self_apply(run_id, sleep=watch)

        # Then
        self.assertIn({"term_a": "done", "term_b": "deferred"}, snapshots)
        final = {item["terminal"]: item["status"] for item in refresh.command_status(run_id)["sessions"]}
        self.assertEqual({"…term_a": "done", "…term_b": "skipped"}, final)

    def test_취소한_뒤_등록된_대기_프로세스도_종료한다(self):
        """세션의 대기를 취소하면 그 뒤에 등록되는 같은 세션의 프로세스도 바로 종료되고 다른 세션의 대기는 그대로 둔다."""
        # Given
        waiters = refresh.IdleWaiters(FakeOrca([]))
        other = refresh.subprocess.Popen(["sleep", "30"])
        late = refresh.subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.kill)
        self.addCleanup(late.kill)
        waiters.track(other, "term_other")

        # When
        waiters.cancel("term_gone")
        waiters.track(late, "term_gone")

        # Then
        self.assertIsNotNone(late.poll())
        self.assertIsNone(other.poll())

    def test_정리_뒤에_등록된_대기_프로세스도_종료한다(self):
        """정리가 시작된 뒤 등록되는 대기 프로세스는 바로 종료되어 도우미 종료 뒤에 남지 않는다."""
        # Given
        waiters = refresh.IdleWaiters(FakeOrca([]))
        waiters.stop()
        late = refresh.subprocess.Popen(["sleep", "30"])

        # When
        waiters.track(late)

        # Then
        self.assertIsNotNone(late.poll())

    def test_도우미가_끝나면_남은_Orca_대기_프로세스를_모두_정리한다(self):
        """정리 단계는 아직 실행 중인 대기 프로세스를 종료하고 대기 스레드가 끝난 뒤에 돌아온다."""
        # Given
        class SlowOrca:
            def wait_idle(self, handle, timeout_ms, track=None):
                process = refresh.subprocess.Popen(["sleep", "30"])
                track(process)
                process.wait()
                return False
        waiters = refresh.IdleWaiters(SlowOrca())
        waiters.start("term_slow", time.time() + 60)
        for _ in range(50):
            if waiters.processes:
                break
            time.sleep(0.02)

        # When
        waiters.stop()

        # Then
        self.assertTrue(waiters.processes)
        self.assertTrue(all(process.poll() is not None for process in waiters.processes))
        self.assertFalse(waiters.waiting("term_slow"))


class HostRecordTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"
        refresh_host_record.EARLIER_SCANS.clear()
        self.addCleanup(refresh_host_record.EARLIER_SCANS.clear)

    def state(self, records, host="claude", partial=""):
        write_records(self.path, records, partial)
        return refresh_host_record.record_state(host, str(self.path))

    def test_중단_표시로_끝난_차례는_쉬는_것으로_본다(self):
        """사용자가 끊었다는 기록은 차례 종료 기록과 같이 끝난 차례로 보고, 그 뒤 새 프롬프트가 오면 진행 중으로 본다."""
        # Given
        interrupted = [*FINISHED_TURN, user_record("다음"), assistant_record(), user_record("[Request interrupted by user]")]

        # When
        states = [self.state(interrupted), self.state([*interrupted, user_record("또 질문")])]

        # Then
        self.assertEqual(["idle", "busy"], states)

    def test_알림이_남은_백그라운드_작업이_있으면_판단하지_않고_알린_뒤에는_쉬는_것으로_본다(self):
        """끝난 차례 앞에서 시작한 작업의 ID가 알림 없이 남았으면 None이고, 알림을 받은 차례까지 끝났으면 idle이며 알림을 막 받았으면 진행 중이다."""
        # Given
        launch = result_record("Command running in background with ID: bg1. Output is being written to: /tmp/work/bg1.output")
        notice = user_record("<task-notification>\n<task-id>bg1</task-id>\n<status>completed</status>\n</task-notification>")
        other = user_record("<task-notification>\n<task-id>other</task-id>\n</task-notification>")

        # When
        states = [
            self.state([user_record("질문"), launch, assistant_record(), turn_end()]),
            self.state([user_record("질문"), launch, assistant_record(), turn_end(), other, assistant_record(), turn_end()]),
            self.state([user_record("질문"), launch, assistant_record(), turn_end(), notice]),
            self.state([user_record("질문"), launch, assistant_record(), turn_end(), notice, assistant_record(), turn_end()]),
        ]

        # Then
        self.assertEqual([None, None, "busy", "idle"], states)

    def test_작업_시작_문구마다_ID를_읽고_ID가_없는_백그라운드_실행은_판단하지_않는다(self):
        """이동·에이전트·모니터·Task ID 문구에서 ID를 읽어 알림 여부를 보고, 실행 중이라고 하면서 ID를 주지 않는 결과는 None이다."""
        # Given
        launches = {
            "moved": ("Command moved to the background (ID: bg2)", "bg2"),
            "agent": ("Async agent launched successfully.\nagentId: ag3 (internal)", "ag3"),
            "monitor": ("Monitor started (task mon4, expires in 30m)", "mon4"),
            "task": ("Task ID: task5", "task5"),
        }

        # When
        pending = {name: self.state([user_record("질문"), result_record(text), turn_end()]) for name, (text, _) in launches.items()}
        notified = {name: self.state([user_record("질문"), result_record(text), turn_end(), user_record(f"<task-id>{task}</task-id>"),
                                       assistant_record(), turn_end()])
                    for name, (text, task) in launches.items()}
        unknown = self.state([user_record("질문"), result_record("The job runs in the background now"), turn_end()])
        no_agent_id = self.state([user_record("질문"), result_record("Async agent launched successfully."), turn_end()])

        # Then
        self.assertEqual({name: None for name in launches}, pending)
        self.assertEqual({name: "idle" for name in launches}, notified)
        self.assertEqual((None, None), (unknown, no_agent_id))

    def test_앞으로_올_깨우기_예약과_반복_예약이_있으면_판단하지_않는다(self):
        """이미 지난 ScheduleWakeup이나 stop인 것은 무시하고, 아직 오지 않은 깨우기와 CronCreate가 있으면 None이다."""
        # Given
        def with_tool(*parts, **extra):
            stamp = extra.get("timestamp", refresh.now())
            record = {**assistant_record(*parts), "timestamp": stamp}
            return [user_record("질문"), record, turn_end()]

        future = refresh.now()
        past = "2000-01-01T00:00:00.000+00:00"

        # When
        states = {
            "future": self.state(with_tool(tool_use("ScheduleWakeup", delaySeconds=3600), timestamp=future)),
            "past": self.state(with_tool(tool_use("ScheduleWakeup", delaySeconds=60), timestamp=past)),
            "stopped": self.state(with_tool(tool_use("ScheduleWakeup", delaySeconds=3600, stop=True), timestamp=future)),
            "cron": self.state(with_tool(tool_use("CronCreate", cron="* * * * *"), timestamp=past)),
        }

        # Then
        self.assertEqual({"future": None, "past": "idle", "stopped": "idle", "cron": None}, states)

    def test_결과가_아직_없는_가장_새_슬래시_명령은_진행_중이고_끝난_명령은_건너뛴다(self):
        """가장 새 command-name 기록에 뒤따르는 stdout이 없으면 busy이고, 있으면 그 명령 기록은 건너뛰고 앞선 차례로 판단한다."""
        # Given
        running = [*FINISHED_TURN, user_record("<command-name>/compact</command-name>"),
                   user_record("<local-command-caveat>The command below was run directly</local-command-caveat>")]
        done = [*running, user_record("<local-command-stdout>Compacted</local-command-stdout>")]

        # When
        states = [self.state(running), self.state(done)]

        # Then
        self.assertEqual(["busy", "idle"], states)

    def test_차례_종료_기록이_한_번도_없으면_진행_중으로_단정하지_않는다(self):
        """차례 종료 기록을 쓰지 않는 버전일 수 있으므로 마지막이 assistant 기록이어도 None이고, 기록이 있으면 busy이다."""
        # Given
        without_end = [user_record("질문"), assistant_record()]

        # When
        states = [self.state(without_end), self.state(RUNNING_TURN)]

        # Then
        self.assertEqual([None, "busy"], states)

    def test_부가_기록과_메타_기록은_차례_판단에서_건너뛴다(self):
        """비용·제목 같은 부가 기록, 다른 종류의 system 기록, isMeta 사용자 기록은 끝난 차례 뒤에 있어도 idle을 바꾸지 않는다."""
        # Given
        extra = [{"type": "last-prompt"}, {"type": "ai-title"}, {"type": "system", "subtype": "stop_hook_summary"},
                 {**user_record("메타"), "isMeta": True}, {**user_record("요약"), "isCompactSummary": True}]

        # When
        state = self.state([*FINISHED_TURN, *extra])

        # Then
        self.assertEqual("idle", state)

    def test_읽을_수_없거나_마지막_줄이_덜_쓰인_기록은_판단하지_않는다(self):
        """표식이나 경로가 없거나 파일이 없거나 마지막 줄이 끝나지 않았거나 비었으면 None이다."""
        # Given
        missing = Path(self.temp.name) / "missing.jsonl"

        # When
        states = [
            refresh_host_record.record_state("claude", None),
            refresh_host_record.record_state("claude", str(missing)),
            self.state(FINISHED_TURN, partial='{"type": "system", "sub'),
            self.state([]),
        ]

        # Then
        self.assertEqual([None, None, None, None], states)

    def test_큰_기록은_꼬리_범위만_읽고_잘린_첫_줄은_버린다(self):
        """512 KiB 앞부분은 읽지 않고, 범위 경계에서 잘린 줄은 해석하지 않고도 끝난 차례를 알아본다."""
        # Given
        filler = [user_record("x" * 2000) for _ in range(400)]

        # When
        state = self.state([*filler, *FINISHED_TURN])

        # Then
        self.assertGreater(self.path.stat().st_size, refresh_host_record.TRANSCRIPT_TAIL_BYTES)
        self.assertEqual("idle", state)

    def test_꼬리_범위_앞에서_시작한_작업의_알림이_없으면_판단하지_않고_알림이_뒤에_있으면_쉬는_것으로_본다(self):
        """512 KiB보다 앞에서 시작한 백그라운드 작업은 알림이 없으면 None이고, 꼬리 안에서 알림을 받고 차례가 끝났으면 idle이다."""
        # Given
        launch = result_record("Command running in background with ID: bgfar. Output is being written to: /tmp/work/bg.output")
        notice = user_record("<task-notification>\n<task-id>bgfar</task-id>\n</task-notification>")
        filler = [user_record("x" * 2000) for _ in range(400)]
        head = [user_record("질문"), launch, assistant_record()]

        # When
        pending = self.state([*head, *filler, assistant_record(), turn_end()])
        scanned = refresh_host_record.EARLIER_SCANS[str(self.path)]["scanned"]
        notified = self.state([*head, *filler, assistant_record(), turn_end(), notice, assistant_record(), turn_end()])

        # Then
        self.assertGreater(self.path.stat().st_size, refresh_host_record.TRANSCRIPT_TAIL_BYTES)
        self.assertEqual((None, "idle"), (pending, notified))
        self.assertGreaterEqual(refresh_host_record.EARLIER_SCANS[str(self.path)]["scanned"], scanned)

    def test_앞부분_검사_결과는_이어서_쓰고_파일이_줄거나_바뀌면_처음부터_다시_읽는다(self):
        """같은 파일에 기록이 덧붙으면 이미 읽은 길이 뒤만 읽고, 파일이 더 작아지면 캐시를 버리고 다시 읽는다."""
        # Given
        launch = result_record("Command running in background with ID: bgfar. Output is being written to: /tmp/work/bg.output")
        filler = [user_record("x" * 2000) for _ in range(500)]
        records = [user_record("질문"), launch, assistant_record(), *filler, assistant_record(), turn_end()]
        key = str(self.path)

        # When
        first = self.state(records)
        scanned_first = refresh_host_record.EARLIER_SCANS[key]["scanned"]
        with patch.object(refresh_host_record, "track_pending", wraps=refresh_host_record.track_pending) as tracked:
            second = self.state([*records, *filler[:100], assistant_record(), turn_end()])
            tail_records = len(refresh_host_record.transcript_tail(key)[0])
        scanned_second = refresh_host_record.EARLIER_SCANS[key]["scanned"]
        shrunk = self.state([user_record("질문"), *filler[:300], assistant_record(), turn_end()])

        # Then
        self.assertEqual((None, None, "idle"), (first, second, shrunk))
        self.assertGreater(scanned_second, scanned_first)
        self.assertEqual(tail_records, tracked.call_count)

    def test_Codex_롤아웃은_마지막_완전한_줄로_판단하고_덜_쓰인_줄은_판단하지_않는다(self):
        """차례 종료 이벤트는 idle, 다른 완전한 줄은 busy, 덜 쓰인 줄이나 빈 파일은 None이다."""
        # Given
        done = {"type": "event_msg", "payload": {"type": "task_complete"}}
        running = {"type": "event_msg", "payload": {"type": "agent_message"}}

        # When
        states = [
            self.state([running, done], host="codex"),
            self.state([done, running], host="codex"),
            self.state([done], host="codex", partial='{"type": "event_msg", "pay'),
            self.state([], host="codex"),
        ]

        # Then
        self.assertEqual(["idle", "busy", None, None], states)

    def test_세션_표식의_대화_기록_경로로_판단한다(self):
        """표식이 가리키는 대화 기록을 읽고, 표식이나 경로가 없으면 None이다."""
        # Given
        env = patch.dict(os.environ, {"ORCA_USER_DATA_PATH": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        write_records(self.path, FINISHED_TURN)
        (directory / "demo-with.json").write_text(json.dumps({"schema": 1, "host": "claude", "transcript_path": str(self.path)}))
        (directory / "demo-without.json").write_text(json.dumps({"schema": 1, "host": "claude"}))

        # When
        states = [refresh_sessions.host_record({"handle": handle, "host": "claude"}) for handle in ("demo-with", "demo-without", "demo-none")]

        # Then
        self.assertEqual(["idle", None, None], states)


class HostRecordFlowTest(unittest.TestCase):
    setUp = DriveTest.setUp
    write_marker = DriveTest.write_marker
    simulate = DriveTest.simulate

    def marker_with(self, handle, records, host="claude", partial=""):
        path = write_records(Path(self.temp.name) / f"{handle}.jsonl", records, partial)
        self.write_marker(handle, host, transcript=path)
        return path

    def entries(self, fake, mode="never"):
        return refresh.plan_sessions(fake, self.state, mode, [])

    def test_Orca_대기_신호가_안_와도_끝난_차례면_기한_안에_보내고_호스트_기록을_근거로_남긴다(self):
        """demo-a: 대화 기록이 끝난 차례이면 tui-idle이 끝내 만족되지 않아도 명령을 보내고 ready_signal을 host_record로 남긴다."""
        # Given
        self.marker_with("demo-a", FINISHED_TURN)
        fake = FakeOrca([terminal("demo-a", "claude")], busy={"demo-a": 10**9}, on_send=self.simulate)
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([("demo-a", "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "host_record"), (sessions[0]["status"], sessions[0]["ready_signal"]))
        self.assertEqual("host_record", refresh.public(sessions[0])["ready_signal"])

    def test_도우미도_Orca_대기_신호_없이_끝난_차례면_확인_뒤_보낸다(self):
        """demo-a: 도우미는 대기 콜백이 끝내 오지 않아도 대화 기록이 끝난 차례이고 확인 뒤에도 그대로면 보낸다."""
        # Given
        self.marker_with("demo-a", FINISHED_TURN)
        fake = FakeOrca([terminal("demo-a", "claude")], busy={"demo-a": 10**9}, on_send=self.simulate)
        fake.never_idle = {"demo-a"}
        entries = [{"handle": "demo-a", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy",
                    "deadline": time.time() + 60, "deferred_at": time.time()}]

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual([("demo-a", "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "host_record"), (entries[0]["status"], entries[0]["ready_signal"]))

    def test_진행_중인_차례는_Orca가_쉬는_중이라고_해도_보내지_않고_미룬다(self):
        """demo-b: 대화 기록이 진행 중인 차례이면 tui-idle이 만족돼도 보내지 않고 busy로 두었다가 기한에 도우미에 넘긴다."""
        # Given
        self.marker_with("demo-b", RUNNING_TURN)
        fake = FakeOrca([terminal("demo-b", "claude")], on_send=self.simulate)
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.3, sleep=lambda seconds: None, expire="deferred")

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("deferred", "busy"), (sessions[0]["status"], sessions[0]["detail"]))

    def test_도우미는_콜백이_쉬는_중이라고_해도_진행_중인_차례면_기다림을_다시_걸고_끝난_뒤에_보낸다(self):
        """대화 기록이 진행 중이면 콜백이 idle을 알려도 보내지 않고 대기를 다시 걸며, 기록이 끝난 차례가 되면 보낸다."""
        # Given
        path = self.marker_with("demo-b", RUNNING_TURN)
        fake = FakeOrca([terminal("demo-b", "claude")], on_send=self.simulate)
        entries = [{"handle": "demo-b", "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy",
                    "deadline": time.time() + 60, "deferred_at": time.time()}]
        polls = []

        def sleep(seconds):
            polls.append(len(fake.sent))
            if len(polls) == 3:
                write_records(path, [*RUNNING_TURN, turn_end()])

        # When
        refresh.follow_up(fake, entries, self.state, sleep=sleep)

        # Then
        self.assertGreaterEqual(len(fake.waits), 2)
        self.assertEqual([0, 0, 0], polls[:3])
        self.assertEqual([("demo-b", "/reload-plugins")], fake.sent)
        self.assertEqual("done", entries[0]["status"])

    def test_읽을_수_있는_호스트_기록이_없으면_예전처럼_tui_idle로_기다린다(self):
        """demo-e: 표식에 대화 기록이 없거나 파일이 없거나 마지막 줄이 덜 쓰였으면 Orca 대기 신호가 만족될 때만 보내고 그 신호를 남긴다."""
        # Given
        self.write_marker("demo-e1", "claude")
        self.write_marker("demo-e2", "claude", transcript=Path(self.temp.name) / "missing.jsonl")
        self.marker_with("demo-e3", FINISHED_TURN, partial='{"type": "sys')
        handles = ("demo-e1", "demo-e2", "demo-e3")
        fake = FakeOrca([terminal(handle, "claude") for handle in handles], busy={handle: 3 for handle in handles}, on_send=self.simulate)
        sessions = self.entries(fake)
        waits = []

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: waits.append(dict(fake.busy)))

        # Then
        self.assertTrue(all(counts[handle] > 0 for counts in waits[:1] for handle in handles))
        self.assertEqual({"tui_idle"}, {entry["ready_signal"] for entry in sessions})
        self.assertEqual({"done"}, {entry["status"] for entry in sessions})
        self.assertEqual(sorted(handles), sorted(handle for handle, _ in fake.sent))

    def test_확인과_보내기_사이에_새_턴이_시작되면_보내지_않고_다시_기다린다(self):
        """보내기 직전에 호스트 기록을 다시 읽어 busy이면 보내지 않고 turn_started로 대기 상태에 둔다."""
        # Given
        self.marker_with("demo-a", FINISHED_TURN)
        fake = FakeOrca([terminal("demo-a", "claude")], on_send=self.simulate)
        entry = self.entries(fake)[0]
        live = {"demo-a": terminal("demo-a", "claude")}
        records = iter(["idle", "busy"])

        # When
        with patch.object(refresh_sessions, "host_record", side_effect=lambda item: next(records)):
            refresh.step(fake, entry, self.state["hosts"]["claude"], live)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("pending", "turn_started"), (entry["status"], entry["detail"]))

    def test_보내지_못하고_넘기는_세션은_지운_입력을_먼저_되돌린다(self):
        """입력을 지운 뒤 새 턴이 시작돼 보내지 못하고 기한이 되면 도우미에 넘기기 전에 같은 글을 Enter 없이 되돌린다."""
        # Given
        self.marker_with("demo-c", FINISHED_TURN)
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "draft text"}, on_send=self.simulate)
        sessions = self.entries(fake)

        def host_record(entry):
            return "busy" if fake.draft("demo-c") is None else "idle"

        # When
        with patch.object(refresh_sessions, "host_record", side_effect=host_record):
            refresh.drive(fake, sessions, self.state, time.time() + 0.3, sleep=lambda seconds: time.sleep(0.05), expire="deferred")

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual("draft text", fake.draft("demo-c"))
        self.assertEqual(("deferred", "restored"), (sessions[0]["status"], sessions[0]["input"]))
        self.assertIn(sessions[0]["detail"], ("turn_started", "busy"))
        self.assertEqual({}, refresh_sessions.HELD_INPUT)
        self.assertFalse(sessions[0]["input_held"])

    def test_입력을_지우고_보낸_뒤_같은_글을_Enter_없이_되돌리고_글은_디스크에_남기지_않는다(self):
        """demo-c: 입력줄의 글을 메모리에만 두고 지운 뒤 명령을 보내 확인하고 그대로 되돌리며, 실행 상태 폴더 어느 파일에도 글이 없다."""
        # Given
        self.marker_with("demo-c", FINISHED_TURN)
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "draft text"}, on_send=self.simulate)
        run_id = "c" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(run_id, "never", [], 60, spawn=lambda run: 1)

        # Then
        self.assertEqual([("demo-c", "/reload-plugins")], fake.sent)
        typed = [text for _, text in fake.keystrokes]
        self.assertEqual([refresh.PROBE_KEY, refresh.BACKSPACE], typed[:2])
        self.assertEqual([refresh.BACKSPACE] * len("draft text"), typed[2:2 + len("draft text")])
        self.assertEqual("draft text", typed[-1])
        self.assertEqual("draft text", fake.draft("demo-c"))
        view = result["sessions"][0]
        self.assertEqual(("done", "restored", "host_record"), (view["status"], view["input"], view["ready_signal"]))
        stored = [path for path in Path(self.temp.name).rglob("*") if path.is_file() and "draft text" in path.read_text(errors="replace")]
        self.assertEqual([], stored)
        self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_지우는_도중_키_전송이_실패해도_남은_앞부분이면_뒷부분을_다시_쳐서_되돌린다(self):
        """백스페이스 도중 Orca 오류로 "draft " 같은 앞부분만 남으면 빠진 뒷부분을 쳐서 같은 글로 확인하고 명령은 보내지 않고 건너뛴다."""
        # Given
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "draft text"}, on_send=self.simulate)
        backspaces = []

        def fail_midway(orca, handle, text):
            if text == refresh.BACKSPACE:
                backspaces.append(text)
                if len(backspaces) == 5:
                    raise refresh.RefreshError("input_not_accepted", "Orca did not accept the keystroke.")
        fake.on_keys = fail_midway
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual("draft text", fake.draft("demo-c"))
        self.assertEqual(("skipped", "input_clear_failed", "restored"), (sessions[0]["status"], sessions[0]["detail"], sessions[0]["input"]))
        self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_지우는_도중_키_전송이_실패해도_남은_뒷부분이면_앞부분을_다시_쳐서_되돌린다(self):
        """커서가 중간에 있어 "def"만 남은 채 오류가 나도 지운 앞부분을 쳐서 같은 글로 확인한다."""
        # Given
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "abcdef"}, on_send=self.simulate)
        chars = list("abcdef")
        cursor = [6]
        backspaces = []

        def edit(orca, handle, text):
            if text == refresh.BACKSPACE:
                backspaces.append(text)
                if cursor[0]:
                    cursor[0] -= 1
                    del chars[cursor[0]]
                if len(backspaces) == 1:
                    cursor[0] = 3
            else:
                chars[cursor[0]:cursor[0]] = list(text)
                cursor[0] += len(text)
            orca.typed[handle] = "".join(chars)
            if text == refresh.BACKSPACE and len(backspaces) == 4:
                raise refresh.RefreshError("input_not_accepted", "Orca did not accept the keystroke.")
        fake.on_keys = edit
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual("abcdef", fake.draft("demo-c"))
        self.assertEqual(("skipped", "input_clear_failed", "restored"), (sessions[0]["status"], sessions[0]["detail"], sessions[0]["input"]))

    def test_복원_때_줄에_저장한_글의_앞부분이나_뒷부분이_남아_있으면_이어서_채운다(self):
        """지우다 만 글이 줄에 남아 있으면 빈 줄을 기다리거나 버리지 않고 저장한 글과 같아지도록 빠진 부분을 친다."""
        for left, expected in (("draft ", "draft text"), ("text", "draft text")):
            with self.subTest(left=left):
                # Given
                fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": left})
                if left == "text":
                    fake.on_keys = lambda orca, handle, text: orca.typed.__setitem__(handle, text + left)
                refresh_sessions.HELD_INPUT["demo-c"] = "draft text"
                entry = {"handle": "demo-c", "host": "claude", "status": "done", "detail": "applied", "input_held": True}

                # When
                self.addCleanup(refresh_sessions.HELD_INPUT.clear)
                while refresh_sessions.release_held(fake, entry):
                    pass

                # Then
                self.assertEqual(expected, fake.draft("demo-c"))
                self.assertEqual(("done", "restored"), (entry["status"], entry["input"]))
                self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_확인_뒤_보내기_직전에_호스트_기록이_없으면_tui_idle까지_확인하고_아니면_보내지_않는다(self):
        """준비 확인은 호스트 기록으로 통과했어도 마지막 재확인이 판단하지 못하면 Orca 대기 신호가 만족될 때만 보낸다."""
        # Given
        self.marker_with("demo-a", FINISHED_TURN)
        results = {}
        for name, busy in (("blocked", 10**9), ("satisfied", 0)):
            fake = FakeOrca([terminal("demo-a", "claude")], busy={"demo-a": busy}, on_send=self.simulate)
            entry = self.entries(fake)[0]
            records = iter(["idle", None])

            # When
            with patch.object(refresh_sessions, "host_record", side_effect=lambda item: next(records)):
                refresh.step(fake, entry, self.state["hosts"]["claude"], {"demo-a": terminal("demo-a", "claude")})
            results[name] = (list(fake.sent), entry["status"], entry["detail"])

        # Then
        self.assertEqual(([], "pending", "turn_started"), results["blocked"])
        self.assertEqual(([("demo-a", "/reload-plugins")], "sent"), results["satisfied"][:2])

    def test_완료_알림도_보내기_직전에_호스트_기록을_다시_확인한다(self):
        """알림 전송 직전에 새 턴이 시작됐으면 보내지 않고, 판단하지 못하면 tui-idle이 만족될 때만 보낸다."""
        # Given
        entry = {"handle": "demo-n", "host": "claude"}
        outcomes = {}
        cases = {"busy": (["idle", "busy"], 0), "undecided_blocked": (["idle", None], 10**9), "undecided_idle": (["idle", None], 0)}
        for name, (records, busy) in cases.items():
            fake = FakeOrca([terminal("demo-n", "claude")], busy={"demo-n": busy})
            sequence = itertools.cycle(records)

            # When
            with (patch.object(refresh_sessions, "host_record", side_effect=lambda item: next(sequence)),
                  patch.object(refresh, "NOTIFY_SECONDS", 0.2)):
                outcomes[name] = (refresh.notify(fake, entry, "r" * 32, lambda seconds: time.sleep(0.05)), len(fake.sent))

        # Then
        self.assertEqual({"busy": ("not_sent:turn_started", 0), "undecided_blocked": ("not_sent:turn_started", 0),
                          "undecided_idle": ("sent", 1)}, outcomes)

    def test_정확히_되돌릴_수_없는_입력은_지우고_보내고_글은_어디에도_남기지_않는다(self):
        """demo-d: 붙여넣기 자리표시가 있는 초안은 지운 뒤 명령을 보내 확인하고 cleared로 알리며, 실행 상태 폴더 어느 파일에도 글이 없다."""
        # Given
        draft = "[Pasted text #1 +20 lines]"
        self.marker_with("demo-d", FINISHED_TURN)
        fake = FakeOrca([terminal("demo-d", "claude")], typed={"demo-d": draft}, on_send=self.simulate)
        run_id = "d" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(run_id, "never", [], 60, spawn=lambda run: 1)

        # Then
        self.assertEqual([("demo-d", "/reload-plugins")], fake.sent)
        typed = [text for _, text in fake.keystrokes]
        self.assertEqual([refresh.PROBE_KEY, refresh.BACKSPACE], typed[:2])
        self.assertEqual([refresh.BACKSPACE] * (len(draft) + refresh_sessions.CLEAR_MARGIN), typed[2:])
        self.assertIsNone(fake.draft("demo-d"))
        view = result["sessions"][0]
        self.assertEqual(("done", "applied", "cleared"), (view["status"], view["detail"], view["input"]))
        stored = [path for path in Path(self.temp.name).rglob("*") if path.is_file() and draft in path.read_text(errors="replace")]
        self.assertEqual([], stored)
        self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_이미지_여러_줄_하이픈으로_시작하는_초안도_지우고_보낸다(self):
        """이미지 자리표시, 여러 줄, -로 시작하는 초안은 되돌릴 수 없으므로 모두 지운 뒤 보내고 cleared로 알린다."""
        for draft in ("앞 [Image #2] 뒤", "첫째 줄\n둘째 줄", "-v 옵션 설명"):
            with self.subTest(draft=draft):
                # Given
                fake = FakeOrca([terminal("demo-d", "claude")], typed={"demo-d": draft}, on_send=self.simulate)
                sessions = self.entries(fake)

                # When
                refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

                # Then
                self.assertEqual([("demo-d", "/reload-plugins")], fake.sent)
                self.assertIsNone(fake.draft("demo-d"))
                self.assertNotIn(draft, [text for _, text in fake.keystrokes])
                self.assertEqual(("done", "cleared"), (sessions[0]["status"], sessions[0]["input"]))

    def test_Codex_입력줄의_글도_지우고_보낸다(self):
        """Codex 입력줄에 글이 있으면 화면이 빈 입력줄로 확인될 때까지 지운 뒤 명령을 보내고 cleared로 알린다."""
        # Given
        typed = CODEX_EMPTY[:2] + ["› 쓰다 만 요청"] + CODEX_EMPTY[3:]
        fake = FakeOrca([terminal("demo-d", "codex")], screens={"demo-d": typed}, on_send=self.simulate)

        def edit_screen(orca, handle, text):
            lines = orca.screens[handle]
            index = max(i for i, line in enumerate(lines) if line.strip().startswith("›"))
            body = lines[index].strip()[1:].strip()
            lines[index] = "› " + (body[:-1] if text == refresh.BACKSPACE else body)
        fake.on_keys = edit_screen
        sessions = self.entries(fake, "always")

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([("demo-d", "/compact")], fake.sent)
        self.assertEqual({refresh.BACKSPACE}, {text for _, text in fake.keystrokes})
        self.assertEqual(("done", "cleared"), (sessions[0]["status"], sessions[0]["input"]))

    def screen_only_text(self, delete_clears, handle="demo-d"):
        typed = CLAUDE_EMPTY[:3] + ["❯ 쓰던 글"] + CLAUDE_EMPTY[4:]
        fake = FakeOrca([terminal(handle, "claude")], screens={handle: typed}, on_send=self.simulate)

        def keys(orca, name, text):
            if text == refresh_sessions.DELETE_KEY:
                orca.typed[name] = ""
                if delete_clears:
                    orca.screens[name] = list(CLAUDE_EMPTY)
        fake.on_keys = keys
        return fake

    def test_커서가_맨_앞인_화면_글은_백스페이스로_안_지워져도_앞으로_지우기_뒤에야_보낸다(self):
        """Orca 초안 없이 화면에만 보이는 글이 백스페이스로 남으면 지운 것으로 치지 않고, 앞으로 지우기 시도로 화면이 비어야 명령을 보낸다."""
        # Given
        fake = self.screen_only_text(delete_clears=True)
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        texts = [text for _, text in fake.keystrokes]
        self.assertIn(refresh_sessions.DELETE_KEY, texts)
        self.assertEqual([("demo-d", "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "cleared"), (sessions[0]["status"], sessions[0]["input"]))

    def test_화면_글이_끝내_안_지워지면_보내지_않고_지우기_실패로_건너뛴다(self):
        """초안이 비어 있어도 화면 입력줄에 글이 남아 있으면 지운 것으로 치지 않아 명령을 보내지 않고 clear_failed로 끝낸다."""
        # Given
        fake = self.screen_only_text(delete_clears=False)
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "input_clear_failed", "clear_failed"), (sessions[0]["status"], sessions[0]["detail"], sessions[0]["input"]))

    def test_지운_뒤_미룬_세션은_도우미가_끝낸_보고에도_cleared로_남는다(self):
        """입력을 지운 뒤 새 턴이 시작돼 도우미에 넘긴 세션은 도우미가 명령을 보내 끝낸 뒤에도 input이 cleared이다."""
        # Given
        self.marker_with("demo-d", FINISHED_TURN)
        fake = self.screen_only_text(delete_clears=True)
        fake.on_keys = lambda orca, name, text: orca.screens.__setitem__(name, list(CLAUDE_EMPTY)) if text == refresh.BACKSPACE else None
        phase = {"helper": False, "calls": 0}

        def host_record(entry):
            phase["calls"] += 1
            return "idle" if phase["helper"] or phase["calls"] == 1 else "busy"
        run_id = "e" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})

        # When
        with patch.object(refresh_sessions, "host_record", side_effect=host_record), patch.object(refresh, "Orca", return_value=fake):
            applied = refresh.command_apply(run_id, "never", [], 1, spawn=lambda run: 4242)
            handed = refresh.load_run(run_id)["follow_up"][0]
            phase["helper"] = True
            refresh.command_self_apply(run_id, sleep=lambda seconds: None)

        # Then
        self.assertEqual("deferred", applied["sessions"][0]["status"])
        self.assertEqual("cleared", handed["input"])
        final = refresh.command_status(run_id)["sessions"][0]
        self.assertEqual(("done", "cleared"), (final["status"], final["input"]))
        self.assertEqual([("demo-d", "/reload-plugins")], fake.sent)

    def test_모든_시도_뒤에도_줄이_비지_않으면_보내지_않고_지우기_실패로_건너뛴다(self):
        """백스페이스와 앞으로 지우기를 모두 쓴 세 번의 시도 뒤에도 입력이 남으면 명령을 보내지 않고 input_clear_failed / clear_failed로 끝낸다."""
        # Given
        draft = "[Pasted text #1 +20 lines]"
        fake = FakeOrca([terminal("demo-d", "claude")], typed={"demo-d": draft}, on_send=self.simulate)

        def stubborn(orca, handle, text):
            if text in (refresh.BACKSPACE, refresh_sessions.DELETE_KEY):
                orca.typed[handle] = draft
        fake.on_keys = stubborn
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(draft, fake.draft("demo-d"))
        self.assertEqual(("skipped", "input_clear_failed", "clear_failed"), (sessions[0]["status"], sessions[0]["detail"], sessions[0]["input"]))
        self.assertEqual(refresh_sessions.CLEAR_ROUNDS - 1, [text for _, text in fake.keystrokes].count(refresh_sessions.DELETE_KEY) // (len(draft) + refresh_sessions.CLEAR_MARGIN))
        self.assertNotIn("observed_draft", sessions[0])

    def test_지운_줄이_비지_않고_남은_글이_저장한_글의_뒷부분이면_앞부분을_다시_쳐서_건너뛴다(self):
        """커서가 중간에 있어 일부만 지워졌으면 지운 앞부분을 다시 쳐서 같은 글로 확인하고, 명령은 보내지 않고 input_clear_failed로 건너뛴다."""
        # Given
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "abcdef"}, on_send=self.simulate)
        chars = list("abcdef")
        cursor = [6]
        backspaces = []

        def edit(orca, handle, text):
            if text == refresh.BACKSPACE:
                backspaces.append(text)
                if cursor[0]:
                    cursor[0] -= 1
                    del chars[cursor[0]]
                if len(backspaces) == 1:
                    cursor[0] = 3
            else:
                chars[cursor[0]:cursor[0]] = list(text)
                cursor[0] += len(text)
            orca.typed[handle] = "".join(chars)
        fake.on_keys = edit
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual("abcdef", fake.draft("demo-c"))
        self.assertEqual(("skipped", "input_clear_failed", "restored"), (sessions[0]["status"], sessions[0]["detail"], sessions[0]["input"]))
        self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_그_사이_사용자가_새로_쓰면_덧붙이지_않고_줄이_쓰이는_중이라고_알린다(self):
        """보낸 뒤 줄이 비어 있지 않고 한도까지 그대로이면 저장한 글을 치지 않고 input_not_restored_line_in_use로 알린다."""
        # Given
        def user_types(orca, handle, text):
            if text == "/reload-plugins":
                orca.typed[handle] = "새로 쓴 글"
            self.simulate(orca, handle, text)
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "draft text"}, on_send=user_types)
        sessions = self.entries(fake)

        # When
        with patch.object(refresh_sessions, "RESTORE_WAIT_SECONDS", 0.2):
            refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: time.sleep(0.05))

        # Then
        self.assertEqual("새로 쓴 글", fake.draft("demo-c"))
        self.assertNotIn(("demo-c", "draft text"), fake.keystrokes)
        self.assertEqual(("failed", "input_not_restored_line_in_use"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual({}, refresh_sessions.HELD_INPUT)

    def test_되돌린_글이_초안으로_확인되지_않으면_복원_미확인으로_알린다(self):
        """저장한 글을 다시 쳤는데 초안이 같은 글이 아니면 input_restore_unconfirmed로 실패를 알리고 메모리에서 지운다."""
        # Given
        fake = FakeOrca([terminal("demo-c", "claude")], typed={"demo-c": "draft text"}, on_send=self.simulate)

        def drops(orca, handle, text):
            if text == "draft text":
                orca.typed[handle] = "draft"
        fake.on_keys = drops
        sessions = self.entries(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)

        # Then
        self.assertEqual(("failed", "input_restore_unconfirmed"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual({}, refresh_sessions.HELD_INPUT)


class ResultCountTest(unittest.TestCase):
    def test_이전_결과가_남아_있어도_새_결과가_생길_때만_반영으로_본다(self):
        """화면에 예전 reload 결과가 있어도 보내기 전보다 결과 줄이 늘어야 반영으로 판단한다."""
        # Given
        before = refresh.result_counts(CLAUDE_EMPTY)
        after = refresh.result_counts(CLAUDE_EMPTY[:2] + ["❯ /reload-plugins", "  ⎿  Reloaded: 7 plugins"] + CLAUDE_EMPTY[2:])

        # When
        grew = {name: after[name] > before[name] for name in after}

        # Then
        self.assertEqual(1, before["reloaded"])
        self.assertEqual({"reloaded": True, "refused": False, "claude_compacted": False, "codex_compacted": False, "nothing_to_compact": False}, grew)


class TranscriptTest(unittest.TestCase):
    def test_보낸_뒤의_기록만_호스트별_결과로_해석한다(self):
        """Claude는 local_command 결과로 reload 성공과 거부를, Codex는 compacted 기록으로 compact를 판정하고 보내기 전 기록은 무시한다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            old = {"type": "system", "subtype": "local_command", "timestamp": "2000-01-01T00:00:00Z", "content": "Reloaded: 1 plugin"}
            path.write_text(json.dumps(old) + "\n")
            offset = path.stat().st_size
            records = [
                {"type": "system", "subtype": "local_command", "timestamp": refresh.now(), "content": "This reload changes MCP tools (x) — Run /reload-plugins --force to apply."},
            ]
            with path.open("a") as stream:
                stream.write("\n".join(json.dumps(item) for item in records) + "\n")

            # When
            recent = refresh.transcript_records(str(path), offset)
            outcomes = [
                refresh.transcript_outcome("claude", "reload", recent),
                refresh.transcript_outcome("claude", "reload", [{"subtype": "local_command", "content": "Reloaded: 6 plugins"}]),
                refresh.transcript_outcome("codex", "compact", [{"type": "compacted"}]),
                refresh.transcript_outcome("codex", "compact", []),
                refresh.transcript_outcome("claude", "compact", [{"subtype": "local_command", "content": "Error during compaction: boom"}]),
                refresh.transcript_outcome("claude", "compact", [{"subtype": "local_command", "content": "Not enough messages to compact."}]),
            ]

        # Then
        self.assertEqual(1, len(recent))
        self.assertEqual(["failed:reload_needs_force", "done", "done", None, "failed:compact_error", "nothing_to_compact"], outcomes)

    def test_입력창_바로_위_항목이_보낸_명령의_결과인지_본다(self):
        """Claude 화면에서 입력창 위의 마지막 항목이 방금 보낸 명령과 그 결과일 때만 참이다."""
        # Given
        newest = CLAUDE_EMPTY
        older = ["❯ /reload-plugins", "  ⎿  Reloaded: 7 plugins", "❯ 다른 질문", "⏺ 답변"] + CLAUDE_EMPTY[2:]

        # When
        observed = [refresh.last_item_is(lines, "/reload-plugins", refresh.RELOAD_DONE) for lines in (newest, older)]

        # Then
        self.assertEqual([True, False], observed)


class OrcaWaitTest(unittest.TestCase):
    def test_대기_시간_초과_오류는_작업_중으로_해석한다(self):
        """Orca는 작업 중인 터미널에 timeout 오류와 종료 코드 1을 돌려주므로 이를 실패가 아니라 작업 중으로 본다."""
        # Given
        responses = [
            (1, {"ok": False, "error": {"code": "timeout", "message": "timeout"}}),
            (0, {"ok": True, "result": {"wait": {"satisfied": True}}}),
            (1, {"ok": False, "error": {"code": "terminal_handle_stale"}}),
        ]
        completed = [refresh.subprocess.CompletedProcess(["orca"], code, stdout=json.dumps(body), stderr="") for code, body in responses]

        # When
        with patch.object(refresh_core, "executable", return_value="orca"), patch.object(refresh_core, "run", side_effect=completed):
            orca = refresh.Orca()
            observed = [orca.idle("term_x"), orca.idle("term_x")]
            with self.assertRaises(refresh.RefreshError) as stale:
                orca.idle("term_x")

        # Then
        self.assertEqual([False, True], observed)
        self.assertEqual("orca_rejected", stale.exception.code)


class OrcaIdleCallbackTest(unittest.TestCase):
    def test_긴_대기는_완료와_시간_초과를_구분하고_프로세스를_넘긴다(self):
        """Orca 대기 결과가 완료면 참, 시간 초과면 거짓이며, 정리를 위해 시작한 프로세스를 호출자에게 알린다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "orca"
            script.write_text('#!/bin/sh\ncase "$4" in idle) echo \'{"ok": true, "result": {"wait": {"satisfied": true}}}\' ;; *) echo \'{"ok": false, "error": {"code": "timeout"}}\'; exit 1 ;; esac\n')
            script.chmod(0o755)
            with patch.dict(os.environ, {"ORCA_CLI_COMMAND": str(script)}):
                orca = refresh.Orca()
            tracked = []

            # When
            observed = [orca.wait_idle("idle", 1000, tracked.append), orca.wait_idle("busy", 1000, tracked.append)]

        # Then
        self.assertEqual([True, False], observed)
        self.assertEqual(2, len(tracked))


HOST_ONLY_HOOKS = {
    ("UserPromptSubmit", "scripts/session_context.py"),
    ("PreToolUse", "scripts/agent_guard.py"),
    ("PermissionRequest", "scripts/datagrip_guard.py"),
}


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "ORCA_USER_DATA_PATH": "",
                "XDG_STATE_HOME": self.temp.name,
                "CODEX_HOME": str(self.base / "codex-home"),
                "CLAUDE_CONFIG_DIR": str(self.base / "claude-config"),
            },
        )
        self.env.start()
        for name in (*refresh.CODEX_TURN_ENV, refresh.COMPANION_ENV):
            os.environ.pop(name, None)
        self.addCleanup(self.env.stop)
        trust = patch.object(refresh, "trust_codex_hooks", return_value="automatic trust is off in these tests")
        self.trust_codex_hooks = trust.start()
        self.addCleanup(trust.stop)

    def install(self, host, version, *, root=None, missing_target=None, manifest_version=None, instruction=None,
                missing_config=False, missing_module=False, direct_hooks=False):
        root = Path(root) if root else self.base / f"{host}-{version}"
        manifest_dir = root / (".claude-plugin" if host == "claude" else ".codex-plugin")
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"name": refresh.PLUGIN, "version": manifest_version or version}
        if host == "claude":
            manifest["hooks"] = ["./config/claude-mod.json", "./hooks/claude-hooks.json"]
            config = root / "config" / "claude-mod.json"
            module = root / "hooks" / "mod" / "register.js"
            config.parent.mkdir(parents=True, exist_ok=True)
            module.parent.mkdir(parents=True, exist_ok=True)
            if not missing_config:
                config.write_text(json.dumps({"modules": ["../hooks/mod/register.js"]}), encoding="utf-8")
            if not missing_module:
                module.write_text("export function register() {}\n", encoding="utf-8")
        else:
            manifest["hooks"] = ["./hooks/hooks.json", "./hooks/codex-hooks.json"]
        (manifest_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        shared, host_only = {}, {}
        launcher = root / refresh.HOOK_LAUNCHER
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        for target in refresh.REQUIRED_HOOK_TARGETS[host]:
            path = root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            if target != missing_target:
                path.write_text("# hook target\n", encoding="utf-8")
        for event, target in refresh.REQUIRED_HOOKS[host]:
            if direct_hooks:
                command = f'python3 "${{CLAUDE_PLUGIN_ROOT}}/{target}"'
            else:
                command = f'sh "${{CLAUDE_PLUGIN_ROOT}}/{refresh.HOOK_LAUNCHER}" {Path(target).name}'
            events = host_only if (event, target) in HOST_ONLY_HOOKS else shared
            events.setdefault(event, []).append({"hooks": [{"type": "command", "command": command}]})
        hook_path = root / "hooks" / "hooks.json"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(json.dumps({"hooks": shared}), encoding="utf-8")
        host_path = root / "hooks" / f"{host}-hooks.json"
        host_path.write_text(json.dumps({"hooks": host_only}), encoding="utf-8")
        instructions = root / "instructions"
        instructions.mkdir(parents=True, exist_ok=True)
        (instructions / "policy.md").write_text(instruction or f"{host} {version}\n", encoding="utf-8")
        return {"version": version, "root": root.as_posix()}

    def test_Codex_설치_뒤_이_플러그인의_훅을_자동으로_신뢰하면_경고_대신_신뢰했다고_알린다(self):
        """플러그인 파일이 바뀐 Codex 설치 뒤 자동 신뢰가 성공하면 경고 없이 codex_hooks_trusted를 남기고, 실패하면 이유와 함께 경고한다."""
        # Given
        codex_before = self.install("codex", "1.0.0", instruction="old\n")
        codex_after = self.install("codex", "1.1.0", instruction="new\n")
        states = [codex_before, codex_after, codex_before, codex_after]
        self.trust_codex_hooks.side_effect = [None, "the installed copy has local changes"]

        # When
        with (
            patch.object(refresh_install, "installed", side_effect=lambda host: states.pop(0)),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: None),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
        ):
            trusted = refresh.update_host("codex")
            refused = refresh.update_host("codex")

        # Then
        self.assertEqual(([], True), (trusted["warnings"], trusted.get("codex_hooks_trusted")))
        self.assertEqual([("codex_hooks_need_trust", "the installed copy has local changes")],
                         [(warning["code"], warning.get("detail")) for warning in refused["warnings"]])

    def test_Codex는_훅_정의가_같아도_플러그인_파일이_바뀌면_다시_신뢰하라고_경고한다(self):
        """Codex 훅 신뢰는 플러그인 파일 전체를 따르므로 지침 파일만 바뀌어도 경고하고, 파일이 그대로면 경고하지 않는다."""
        # Given
        codex_before = self.install("codex", "1.0.0", instruction="old\n")
        codex_after = self.install("codex", "1.1.0", instruction="new\n")
        states = [codex_before, codex_after, codex_before, codex_before]

        # When
        with (
            patch.object(refresh_install, "installed", side_effect=lambda host: states.pop(0)),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: None),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
        ):
            changed = refresh.update_host("codex")
            same = refresh.update_host("codex")

        # Then
        self.assertEqual(["codex_hooks_need_trust"], [warning["code"] for warning in changed["warnings"]])
        self.assertEqual([], same["warnings"])

    def test_같은_버전의_미배포_변경과_Codex_훅_변경을_경고한다(self):
        """Claude가 같은 버전이라 새 파일을 받지 못하면 버전을 올리라고, Codex 훅 정의가 바뀌면 다시 신뢰하라고 경고한다."""
        # Given
        claude = self.install("claude", "1.0.0")
        codex_before = self.install("codex", "1.0.0", instruction="old\n")
        codex_after = self.install("codex", "1.1.0", instruction="new\n")
        hooks_path = Path(codex_after["root"]) / "hooks" / "hooks.json"
        hooks_payload = json.loads(hooks_path.read_text(encoding="utf-8"))
        hooks_payload["revision"] = "changed"
        hooks_path.write_text(json.dumps(hooks_payload), encoding="utf-8")
        states = {"claude": [claude, claude], "codex": [codex_before, codex_after]}
        commands: list[list[str]] = []

        def fake_installed(host):
            return states[host].pop(0)

        # When
        with (
            patch.object(refresh_install, "installed", side_effect=fake_installed),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: commands.append(list(argv))),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
            patch.object(refresh, "claude_unreleased_changes", return_value=(["skills/x/SKILL.md"], None)),
        ):
            claude_result = refresh.update_host("claude")
            codex_result = refresh.update_host("codex")

        # Then
        self.assertEqual(["unreleased_same_version"], [warning["code"] for warning in claude_result["warnings"]])
        self.assertFalse(claude_result["instructions_changed"])
        self.assertEqual(["codex_hooks_need_trust"], [warning["code"] for warning in codex_result["warnings"]])
        self.assertTrue(codex_result["instructions_changed"])
        self.assertEqual(["claude", "plugin", "marketplace", "update", "hei5enbug"], commands[0])
        self.assertEqual(["codex", "plugin", "add", "hei5enbug-agent-setup@hei5enbug"], commands[3])

    def test_미배포_변경을_확인하지_못하면_변경_없음으로_보고하지_않는다(self):
        """설치 커밋이나 마켓플레이스 비교를 확인할 수 없으면 경고 없이 넘어가지 않고 확인 불가 경고를 남긴다."""
        # Given
        current = self.install("claude", "1.0.0")
        states = [current, current]

        # When
        with (
            patch.object(refresh_install, "installed", side_effect=lambda host: states.pop(0)),
            patch.object(refresh_core, "run"),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
            patch.object(refresh, "claude_unreleased_changes", return_value=([], "the installed commit is not in the marketplace clone")),
        ):
            result = refresh.update_host("claude")

        # Then
        self.assertEqual(["unreleased_check_unavailable"], [warning["code"] for warning in result["warnings"]])

    def test_업데이트_뒤_필수_훅_대상이_없으면_그_호스트는_실패로_남긴다(self):
        """새 설치본에서 필수 훅 파일이 빠졌으면 업데이트를 성공으로 보지 않는다."""
        # Given
        before = self.install("codex", "1.0.0")
        after = self.install("codex", "1.1.0", missing_target="scripts/language_guard.py")
        states = [before, after]
        commands = []

        # When
        with (
            patch.object(refresh_install, "installed", side_effect=lambda host: states.pop(0)),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: commands.append(list(argv))),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
        ):
            with self.assertRaises(refresh.RefreshError) as invalid:
                refresh.update_host("codex")

        # Then
        self.assertEqual("plugin_hook_target_missing", invalid.exception.code)
        self.assertEqual(2, len(commands))

    def update_claude_with_after(self, after):
        before = self.install("claude", "1.0.0")
        commands = []
        with (
            patch.object(refresh_install, "installed", side_effect=[before, after]),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: commands.append(list(argv))),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
            patch.object(refresh, "claude_unreleased_changes", return_value=([], None)),
        ):
            return refresh.update_host("claude")

    def test_업데이트_뒤_Claude_Mod_설정_파일이_없으면_실패로_남긴다(self):
        """매니페스트 hooks가 가리키는 Mod 설정 파일이 새 설치본에 없으면 성공으로 보지 않는다."""
        # Given
        after = self.install("claude", "1.1.0", missing_config=True)

        # When
        with self.assertRaises(refresh.RefreshError) as invalid:
            self.update_claude_with_after(after)

        # Then
        self.assertEqual("plugin_hook_target_missing", invalid.exception.code)

    def test_업데이트_뒤_Claude_Mod_모듈_파일이_없으면_실패로_남긴다(self):
        """Mod 설정이 나열한 모듈 파일이 새 설치본에 없으면 성공으로 보지 않는다."""
        # Given
        after = self.install("claude", "1.1.0", missing_module=True)

        # When
        with self.assertRaises(refresh.RefreshError) as invalid:
            self.update_claude_with_after(after)

        # Then
        self.assertEqual("plugin_hook_target_missing", invalid.exception.code)

    def test_Claude_매니페스트에_hooks가_없거나_설치_밖을_가리키면_실패한다(self):
        """hooks 값이 없거나 플러그인 루트 밖 경로이면 Mod 설정이 있어도 검증을 통과시키지 않는다."""
        # Given
        install = self.install("claude", "1.1.0")
        manifest_path = Path(install["root"]) / ".claude-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outside = self.base / "outside.json"
        outside.write_text(json.dumps({"modules": ["../hooks/mod/register.js"]}), encoding="utf-8")

        for hooks in (None, "../outside.json"):
            with self.subTest(hooks=hooks):
                changed = {key: value for key, value in manifest.items() if key != "hooks"}
                if hooks is not None:
                    changed["hooks"] = hooks
                manifest_path.write_text(json.dumps(changed), encoding="utf-8")

                # When
                with self.assertRaises(refresh.RefreshError) as invalid:
                    refresh.validate_install("claude", install)

                # Then
                self.assertEqual("plugin_hook_target_missing", invalid.exception.code)

    def test_Claude_Mod_설정과_모듈이_모두_있으면_검증을_통과한다(self):
        """매니페스트 hooks의 설정 파일과 그 모듈이 모두 설치돼 있으면 Claude 설치본 검증이 통과한다."""
        # Given
        install = self.install("claude", "1.1.0")

        # When
        result = refresh.validate_install("claude", install)

        # Then
        self.assertTrue(result["digest"])

    def test_예전처럼_스크립트를_직접_실행하는_훅도_검증을_통과한다(self):
        """실행기 이전 설치본처럼 훅이 Python 스크립트를 직접 실행해도 필요한 대상이 모두 있으면 통과한다."""
        # Given
        install = self.install("codex", "1.1.0", direct_hooks=True)

        # When
        result = refresh.validate_install("codex", install)

        # Then
        self.assertTrue(result["digest"])

    def test_실행기_뒤_스크립트가_없으면_대상_누락으로_실패한다(self):
        """실행기 형태의 훅이 가리키는 scripts/<이름>.py가 없으면 필수 대상이 빠진 것으로 본다."""
        # Given
        install = self.install("codex", "1.1.0", missing_target="scripts/agent_guard.py")

        # When
        with self.assertRaises(refresh.RefreshError) as invalid:
            refresh.validate_install("codex", install)

        # Then
        self.assertEqual("plugin_hook_target_missing", invalid.exception.code)

    def test_실행기_뒤_인자가_없거나_스크립트_이름이_아니면_지원하지_않는_훅이다(self):
        """실행기 다음 인자가 없거나 경로·옵션·.py가 아닌 이름이면 훅 대상을 확인할 수 없어 실패한다."""
        # Given
        install = self.install("claude", "1.1.0")
        hooks_path = Path(install["root"]) / "hooks" / "hooks.json"
        launcher = f'sh "${{CLAUDE_PLUGIN_ROOT}}/{refresh.HOOK_LAUNCHER}"'

        for suffix in ("", " ../x.py", " -m", " .hidden.py", " session_context.sh"):
            with self.subTest(suffix=suffix):
                hooks_path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
                    {"type": "command", "command": launcher + suffix}]}]}}), encoding="utf-8")

                # When
                with self.assertRaises(refresh.RefreshError) as invalid:
                    refresh.validate_install("claude", install)

                # Then
                self.assertEqual("plugin_hooks_invalid", invalid.exception.code)

    def test_저장소의_실제_훅_정의는_두_호스트에서_설치_검증을_통과한다(self):
        """저장소의 hooks/hooks.json과 매니페스트를 그대로 설치본으로 볼 때 Claude Code와 Codex 검증이 모두 통과한다."""
        # Given
        root = SCRIPT.parents[3]
        versions = {host: json.loads((root / folder / "plugin.json").read_text(encoding="utf-8"))["version"]
                    for host, folder in (("claude", ".claude-plugin"), ("codex", ".codex-plugin"))}

        # When
        results = {host: refresh.validate_install(host, {"root": root.as_posix(), "version": version})
                   for host, version in versions.items()}

        # Then
        self.assertTrue(all(result["digest"] for result in results.values()))

    def test_업데이트_뒤_manifest_version과_지침_digest가_없으면_실패한다(self):
        """새 설치본의 호스트 manifest 버전이 다르거나 지침 digest가 비어 있으면 성공으로 처리하지 않는다."""
        # Given
        before = self.install("codex", "1.0.0")
        mismatch = self.install("codex", "1.1.0", root=self.base / "codex-1.1.0-mismatch", manifest_version="9.9.9")
        valid_after = self.install("codex", "1.1.0", root=self.base / "codex-1.1.0-valid")
        commands = []

        # When
        with (
            patch.object(refresh_install, "installed", side_effect=[before, mismatch]),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: commands.append(list(argv))),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
        ):
            with self.assertRaises(refresh.RefreshError) as manifest:
                refresh.update_host("codex")
        with (
            patch.object(refresh_install, "installed", side_effect=[before, valid_after]),
            patch.object(refresh_core, "run", side_effect=lambda argv, **kwargs: commands.append(list(argv))),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
            patch.object(refresh.SESSION_CONTEXT, "instructions_digest", side_effect=["before", ""]),
        ):
            with self.assertRaises(refresh.RefreshError) as digest:
                refresh.update_host("codex")

        # Then
        self.assertEqual("plugin_manifest_mismatch", manifest.exception.code)
        self.assertEqual("plugin_digest_missing", digest.exception.code)
        self.assertEqual(4, len(commands))

    def test_읽을_수_없는_설치_JSON은_해당_호스트만_실패로_남긴다(self):
        """설치 manifest나 훅 JSON의 문자 인코딩이 깨져도 다른 호스트의 검증 결과는 보존한다."""
        # Given
        roots = {host: self.install(host, "1.2.3") for host in refresh.HOSTS}
        cases = [(".codex-plugin/plugin.json", "plugin_manifest_missing"), ("hooks/hooks.json", "plugin_hooks_missing")]

        for relative, expected in cases:
            with self.subTest(path=relative):
                path = Path(roots["codex"]["root"]) / relative
                original = path.read_bytes()
                path.write_bytes(b"\xff")
                try:
                    # When
                    with patch.object(refresh_install, "installed", side_effect=lambda host: roots[host]), patch.object(refresh_core, "run") as commands:
                        result = refresh.command_apply_installed()

                    # Then
                    self.assertFalse(result["ok"])
                    self.assertTrue(result["hosts"]["claude"]["digest"])
                    self.assertEqual(expected, result["hosts"]["codex"]["error"]["code"])
                    commands.assert_not_called()
                finally:
                    path.write_bytes(original)

    def test_apply_installed는_업데이트_명령_없이_기존_run_id로_적용할_상태를_저장한다(self):
        """apply-installed는 설치본을 읽어 기존 run 상태를 저장하고 같은 run ID를 apply에 넘길 수 있다."""
        # Given
        state_home = self.base / "state"
        codex_home = self.base / "codex-home"
        roots = {
            "claude": self.install("claude", "1.2.3"),
            "codex": self.install(
                "codex",
                "1.2.3",
                root=codex_home / "plugins" / "cache" / refresh.MARKETPLACE / refresh.PLUGIN / "1.2.3",
            ),
        }
        commands = []

        def read_only_run(argv, **kwargs):
            commands.append(list(argv))
            if argv[0] == "claude":
                payload = [{"id": refresh.PLUGIN_ID, "enabled": True, "version": "1.2.3", "installPath": roots["claude"]["root"]}]
            else:
                payload = {"installed": [{"pluginId": refresh.PLUGIN_ID, "enabled": True, "version": "1.2.3"}]}
            return refresh.subprocess.CompletedProcess(list(argv), 0, json.dumps(payload), "")

        with patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(state_home), "CODEX_HOME": str(codex_home), "ORCA_USER_DATA_PATH": ""},
        ), patch.object(refresh_core, "executable", side_effect=lambda name: name), patch.object(
            refresh_core, "run", side_effect=read_only_run
        ), patch.object(refresh, "update_host", side_effect=AssertionError("apply-installed must not update hosts")):
            # When
            result = refresh.command_apply_installed()
            state = refresh.load_run(result["run_id"])
            with patch.object(refresh, "Orca", return_value=FakeOrca([])):
                applied = refresh.command_apply(result["run_id"], "never", [], 30, spawn=lambda run_id: None)

        # Then
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], state["run_id"])
        self.assertEqual({"run_id", "created_at", "hosts", "sessions"}, set(state))
        self.assertEqual({}, state["sessions"])
        self.assertEqual({"before_version", "after_version", "root", "previous_root", "digest", "instructions_changed", "warnings", "plugins"}, set(state["hosts"]["claude"]))
        self.assertEqual([], state["hosts"]["claude"]["plugins"])
        self.assertEqual("1.2.3", state["hosts"]["claude"]["after_version"])
        self.assertEqual(result["run_id"], applied["run_id"])
        self.assertEqual(
            [["claude", "plugin", "list", "--json"], ["codex", "plugin", "list", "--json"]],
            commands,
        )

    def test_한_호스트_실패는_성공한_호스트_결과를_보존하고_실패_호스트의_세션은_막는다(self):
        """Codex 업데이트가 실패해도 Claude 결과를 보존하고 apply는 Codex 세션에 명령을 보내지 않는다."""
        # Given
        claude_result = {"before_version": "1.0.0", "after_version": "1.1.0", "root": "/c/1.1.0", "digest": "d"}
        codex_failure = refresh.RefreshError(
            "update_deferred_unknown_session_state",
            "unknown",
            {"root": "/x/1.0.0", "recovery_command": "python3 /x/script update --json"},
        )
        fake = FakeOrca([terminal("term_codex", "codex")])

        # When
        with patch.object(refresh, "update_host", side_effect=[claude_result, codex_failure]):
            result = refresh.command_update()
        with patch.object(refresh, "Orca", return_value=fake):
            applied = refresh.command_apply(result["run_id"], "never", [], 30, spawn=lambda run_id: None)

        # Then
        self.assertTrue(result["hosts"]["claude"].get("digest"))
        self.assertEqual("update_deferred_unknown_session_state", result["hosts"]["codex"]["error"]["code"])
        self.assertEqual("/x/1.0.0", result["hosts"]["codex"]["root"])
        self.assertEqual([("blocked", "codex_update_failed")], [(entry["status"], entry["detail"]) for entry in applied["sessions"]])
        self.assertEqual([], fake.sent)

    def plugin_root(self, host, plugin, marketplace, version):
        if host == "claude":
            return self.base / "claude-cache" / marketplace / plugin / version
        return self.base / "codex-home" / "plugins" / "cache" / marketplace / plugin / version

    def companion(self, host, plugin, marketplace, version, *, hooks=None, manifest_version=None, files=()):
        root = self.plugin_root(host, plugin, marketplace, version)
        manifest_dir = root / (".claude-plugin" if host == "claude" else ".codex-plugin")
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "plugin.json").write_text(json.dumps({"name": plugin, "version": manifest_version or version}), encoding="utf-8")
        for relative in files:
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text("#!/bin/sh\n", encoding="utf-8")
        if hooks is not None:
            (root / "hooks").mkdir(parents=True, exist_ok=True)
            (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": hooks}]}}), encoding="utf-8")
        return root

    def stage(self, fake, upgrade=True):
        """Install this plugin at 1.0.0 on both hosts, with 1.1.0 ready for the update."""
        for host in refresh.HOSTS:
            old = self.install(host, "1.0.0", root=self.plugin_root(host, refresh.PLUGIN, refresh.MARKETPLACE, "1.0.0"))
            fake.add(host, refresh.PLUGIN_ID, "1.0.0", old["root"])
            if upgrade:
                new = self.install(host, "1.1.0", root=self.plugin_root(host, refresh.PLUGIN, refresh.MARKETPLACE, "1.1.0"))
                fake.upgrade(host, refresh.PLUGIN_ID, "1.1.0", new["root"])

    def stage_companion(self, fake, host, plugin_id, before, after=None, **kwargs):
        plugin, marketplace = plugin_id.split("@")
        fake.add(host, plugin_id, before, self.companion(host, plugin, marketplace, before, **kwargs.get("old", {})))
        if after:
            fake.upgrade(host, plugin_id, after, self.companion(host, plugin, marketplace, after, **kwargs.get("new", {})))

    def run_with(self, fake, function, *args):
        with (
            patch.object(refresh_core, "run", side_effect=fake),
            patch.object(refresh_core, "executable", side_effect=lambda name: name),
            patch.object(refresh, "claude_unreleased_changes", return_value=([], None)),
            patch.object(refresh, "Orca", side_effect=AssertionError("updating must not read Orca")),
        ):
            return function(*args)

    @staticmethod
    def statuses(result, host):
        return [(item["plugin"], item["status"], item["before_version"], item["after_version"]) for item in result["hosts"][host]["plugins"]]

    def write_saved_option(self, value):
        config = self.base / "claude-config"
        config.mkdir(parents=True, exist_ok=True)
        options = {"refresh_plugins": value} if value is not None else {}
        payload = {"pluginConfigs": {f"{refresh.PLUGIN}@{refresh.MARKETPLACE}": {"options": options}}}
        (config / "settings.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_함께_갱신할_플러그인_목록은_인자_환경변수_저장된_옵션_순서로_고른다(self):
        """--also가 있으면 그것만, 없으면 환경변수, 그것도 비면 저장된 옵션을 쓰고 문자열은 쉼표와 공백으로, 목록은 항목별로 읽는다."""
        # Given
        self.write_saved_option("saved@m1")

        # When
        saved = refresh.companion_ids([])[0]
        with patch.dict(os.environ, {refresh.COMPANION_ENV: "env-a@m2, env-b@m2\nenv-c@m2"}):
            from_env = refresh.companion_ids([])[0]
            from_also = refresh.companion_ids(["also@m3"])[0]
        self.write_saved_option(["list-a@m4", "list-b@m4"])
        from_list = refresh.companion_ids([])[0]
        self.write_saved_option("")
        empty = refresh.companion_ids([])[0]
        (self.base / "claude-config" / "settings.json").write_text("{", encoding="utf-8")
        broken_ids, broken_extra = refresh.companion_ids([])

        # Then
        self.assertEqual(["saved@m1"], saved)
        self.assertEqual(["env-a@m2", "env-b@m2", "env-c@m2"], from_env)
        self.assertEqual(["also@m3"], from_also)
        self.assertEqual(["list-a@m4", "list-b@m4"], from_list)
        self.assertEqual([], empty)
        self.assertEqual([], broken_ids)
        self.assertIn("notice", broken_extra)

    def test_빈_환경변수는_저장된_옵션으로_넘어간다(self):
        """환경변수가 공백뿐이면 비어 있는 것으로 보고 저장된 옵션을 쓴다."""
        # Given
        self.write_saved_option("saved@m1")

        # When
        with patch.dict(os.environ, {refresh.COMPANION_ENV: "  ,  "}):
            ids = refresh.companion_ids([])[0]

        # Then
        self.assertEqual(["saved@m1"], ids)

    def test_잘못된_플러그인_ID는_명령_없이_위치만_알리고_원문을_싣지_않는다(self):
        """형식이 틀린 항목이 하나라도 있으면 어떤 명령도 실행하지 않고 1부터 센 순번과 코드만 돌려준다."""
        # Given
        invalid = ["no-at-sign", "name@", "@market", "a b@c", "-a@b", "a@b@c", "a@b\n", "x" * 129 + "@m", "name@mkt/evil", ""]
        secret = "not a valid id!!"
        fake = FakeCli()
        output = io.StringIO()

        # When
        for entry in invalid:
            with self.subTest(entry=entry), self.assertRaises(refresh.RefreshError) as refused:
                refresh.companion_ids(["good@mk", entry])
            self.assertEqual(("plugin_id_invalid", 2), (refused.exception.code, refused.exception.details["entry"]))
        with patch.object(refresh_core, "run", side_effect=fake), contextlib.redirect_stdout(output):
            code = refresh.main(["update", "--also", "good@mk", "--also", secret, "--json"])
        self.write_saved_option(["good@mk", 7])
        with self.assertRaises(refresh.RefreshError) as not_text:
            refresh.companion_ids([])

        # Then
        payload = json.loads(output.getvalue())
        self.assertEqual(2, code)
        self.assertEqual(("error", "plugin_id_invalid", 2, False), (payload["status"], payload["code"], payload["entry"], payload["ok"]))
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual([], fake.commands)
        self.assertEqual(2, not_text.exception.details["entry"])

    def test_중복과_자기_자신은_빼고_열_개까지만_남긴다(self):
        """같은 ID 중복과 이 플러그인 ID는 건너뛰고, 열 개를 넘는 항목은 버리며 몇 개를 버렸는지 알린다."""
        # Given
        entries = [refresh.PLUGIN_ID, "a@m", "a@m", *[f"p{index}@m" for index in range(12)]]

        # When
        ids, extra = refresh.companion_ids(entries)

        # Then
        self.assertEqual(["a@m", *[f"p{index}@m" for index in range(9)]], ids)
        self.assertEqual({"companions_dropped": 3}, extra)

    def test_함께_갱신하는_플러그인은_호스트마다_상태를_보고하고_마켓플레이스는_한_번만_갱신한다(self):
        """updated, current, not_installed를 두 호스트에서 보고하고, 같은 마켓플레이스는 호스트마다 한 번만 갱신한다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        for host in refresh.HOSTS:
            self.stage_companion(fake, host, "upd@mk", "1.0.0", "1.1.0")
            self.stage_companion(fake, host, "same@mk", "2.0.0")
            fake.add(host, "off@mk", "1.0.0", self.companion(host, "off", "mk", "1.0.0"), enabled=False)
        fake.marketplaces = [{"name": "mk", "source": "github", "installLocation": str(self.base / "mk-clone")}]
        ids = ["upd@mk", "same@mk", "gone@mk", "off@mk", refresh.PLUGIN_ID]

        # When
        result = self.run_with(fake, refresh.command_update, ids)

        # Then
        expected = [("upd@mk", "updated", "1.0.0", "1.1.0"), ("same@mk", "current", "2.0.0", "2.0.0"),
                    ("gone@mk", "not_installed", None, None), ("off@mk", "not_installed", None, None)]
        self.assertTrue(result["ok"])
        for host in refresh.HOSTS:
            self.assertEqual(expected, self.statuses(result, host))
        self.assertEqual("1.1.0", result["hosts"]["claude"]["after_version"])
        self.assertEqual(
            [["claude", "plugin", "marketplace", "update", "hei5enbug"], ["claude", "plugin", "update", refresh.PLUGIN_ID],
             ["claude", "plugin", "marketplace", "update", "mk"], ["claude", "plugin", "update", "upd@mk"], ["claude", "plugin", "update", "same@mk"],
             ["codex", "plugin", "marketplace", "upgrade", "hei5enbug"], ["codex", "plugin", "add", refresh.PLUGIN_ID],
             ["codex", "plugin", "marketplace", "upgrade", "mk"], ["codex", "plugin", "add", "upd@mk"], ["codex", "plugin", "add", "same@mk"]],
            fake.installs(),
        )

    def test_같은_마켓플레이스의_이_플러그인_갱신은_다시_하지_않고_실패는_함께_보고한다(self):
        """이 플러그인과 같은 마켓플레이스에 있는 동반 플러그인은 마켓플레이스를 다시 갱신하지 않고, 갱신이 실패하면 같은 오류를 보고한다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        self.stage_companion(fake, "claude", f"co@{refresh.MARKETPLACE}", "1.0.0")
        self.stage_companion(fake, "claude", "x@broken", "1.0.0")
        self.stage_companion(fake, "claude", "y@broken", "1.0.0")
        fake.failing.add(("claude", "plugin", "marketplace", "update", "broken"))

        # When
        result = self.run_with(fake, refresh.command_update, [f"co@{refresh.MARKETPLACE}", "x@broken", "y@broken"])

        # Then
        claude = {item["plugin"]: item for item in result["hosts"]["claude"]["plugins"]}
        self.assertEqual("current", claude[f"co@{refresh.MARKETPLACE}"]["status"])
        self.assertEqual(["command_failed", "command_failed"], [claude[name]["code"] for name in ("x@broken", "y@broken")])
        self.assertEqual(1, fake.installs().count(["claude", "plugin", "marketplace", "update", "broken"]))
        self.assertEqual(1, fake.installs().count(["claude", "plugin", "marketplace", "update", refresh.MARKETPLACE]))
        self.assertFalse(result["ok"])

    def stage_local(self):
        clone = self.base / "local-clone"
        (clone / ".claude-plugin").mkdir(parents=True)
        (clone / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [
            {"name": "loc", "source": "./plugins/loc"},
            {"name": "esc", "source": "../outside"},
            {"name": "obj", "source": {"source": "github"}},
            {"name": "bare", "source": "./plugins/bare"},
        ]}), encoding="utf-8")
        for folder, version in ((clone / "plugins" / "loc", "3.0.0"), (self.base / "outside", "9.9.9")):
            (folder / ".claude-plugin").mkdir(parents=True)
            (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        (clone / "plugins" / "bare").mkdir(parents=True)
        return clone

    def test_로컬_소스_플러그인은_설치_명령_없이_로컬_소스로_보고한다(self):
        """디렉터리나 파일 마켓플레이스와 git이 아닌 Codex 소스는 설치하지 않고, Claude는 폴더의 manifest에서 버전을 읽는다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        clone = self.stage_local()
        fake.marketplaces = [
            {"name": "dirmk", "source": "directory", "installLocation": str(clone)},
            {"name": "filemk", "source": "file", "installLocation": str(clone)},
        ]
        stale = self.base / "stale"
        stale.mkdir()
        for name in ("loc", "esc", "obj", "bare", "unlisted"):
            fake.add("claude", f"{name}@dirmk", "1.0.0", stale)
        fake.add("claude", "loc@filemk", "1.0.0", stale)
        fake.add("codex", "cx@localmk", "4.0.0", stale, source="local")
        fake.add("codex", "nosrc@localmk", "5.0.0", stale, source=None)
        ids = ["loc@dirmk", "esc@dirmk", "obj@dirmk", "bare@dirmk", "unlisted@dirmk", "loc@filemk", "cx@localmk", "nosrc@localmk"]

        # When
        result = self.run_with(fake, refresh.command_update, ids)

        # Then
        claude = {item["plugin"]: item for item in result["hosts"]["claude"]["plugins"] if item["status"] != "not_installed"}
        self.assertEqual({"loc@dirmk": "3.0.0", "loc@filemk": "3.0.0", "esc@dirmk": None, "obj@dirmk": None, "bare@dirmk": None, "unlisted@dirmk": None},
                         {name: item["after_version"] for name, item in claude.items()})
        self.assertEqual({"local_source"}, {item["status"] for item in claude.values()})
        self.assertEqual({"loads_from_folder_on_reload"}, {item["note"] for item in claude.values()})
        codex = {item["plugin"]: item for item in result["hosts"]["codex"]["plugins"] if item["status"] != "not_installed"}
        self.assertEqual({"cx@localmk": ("local_source", "4.0.0"), "nosrc@localmk": ("local_source", "5.0.0")},
                         {name: (item["status"], item["after_version"]) for name, item in codex.items()})
        self.assertTrue(all("note" not in item for item in codex.values()))
        self.assertTrue(result["ok"])
        self.assertFalse([command for command in fake.installs() if any(name in " ".join(command) for name in ("dirmk", "filemk", "localmk"))])

    def test_Claude_로컬_폴더_버전은_manifest가_없거나_폴더를_벗어나면_알_수_없다고_본다(self):
        """마켓플레이스 파일, 플러그인 항목, source 경로, 플러그인 manifest 중 하나라도 어긋나면 버전을 null로 둔다."""
        # Given
        clone = self.stage_local()
        entry = {"name": "dirmk", "source": "directory", "installLocation": str(clone)}
        escaped = clone / "plugins" / "link"
        escaped.parent.mkdir(exist_ok=True)
        escaped.symlink_to(self.base / "outside", target_is_directory=True)
        catalog = clone / ".claude-plugin" / "marketplace.json"
        payload = json.loads(catalog.read_text(encoding="utf-8"))
        payload["plugins"].append({"name": "link", "source": "./plugins/link"})
        payload["plugins"].append({"name": "absolute", "source": str(self.base / "outside")})
        catalog.write_text(json.dumps(payload), encoding="utf-8")

        # When
        versions = {name: refresh.folder_version(entry, name) for name in ("loc", "esc", "obj", "bare", "link", "absolute", "unlisted")}
        missing = refresh.folder_version({"name": "x", "installLocation": str(self.base / "nowhere")}, "loc")
        no_location = refresh.folder_version({"name": "x"}, "loc")

        # Then
        self.assertEqual({"loc": "3.0.0", "esc": None, "obj": None, "bare": None, "link": None, "absolute": None, "unlisted": None}, versions)
        self.assertIsNone(missing)
        self.assertIsNone(no_location)

    def test_동반_플러그인_검증이_실패해도_이_플러그인과_세션_적용은_막지_않는다(self):
        """동반 플러그인의 manifest 불일치와 없는 훅 대상은 그 항목의 error로만 남고 이 플러그인 호스트는 그대로 적용 가능하다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        pairs = {
            "bad@mk": {"new": {"manifest_version": "9.9.9"}},
            "hook@mk": {"new": {"hooks": [{"type": "command", "command": 'sh "${CLAUDE_PLUGIN_ROOT}/bin/run.sh"'}]}},
            "launch@mk": {"new": {"hooks": [{"type": "command", "command": 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hook_python.sh" runner.py'}],
                                  "files": ["scripts/hook_python.sh"]}},
            "good@mk": {"new": {"hooks": [
                {"type": "command", "command": '"${CLAUDE_PLUGIN_ROOT}/bin/run.sh" --flag'},
                {"type": "command", "command": "echo no target"},
                {"type": "prompt", "prompt": "hello"},
            ], "files": ["bin/run.sh"]}},
        }
        for host in refresh.HOSTS:
            for plugin_id, kwargs in pairs.items():
                self.stage_companion(fake, host, plugin_id, "1.0.0", "1.1.0", **kwargs)

        # When
        result = self.run_with(fake, refresh.command_update, list(pairs))
        state = refresh.load_run(result["run_id"])
        sessions = refresh.plan_sessions(FakeOrca([terminal("term_claude", "claude"), terminal("term_codex", "codex")]), state, "always", [])

        # Then
        self.assertFalse(result["ok"])
        for host in refresh.HOSTS:
            plugins = {item["plugin"]: item for item in result["hosts"][host]["plugins"]}
            self.assertEqual("plugin_manifest_mismatch", plugins["bad@mk"]["code"])
            self.assertEqual("plugin_hook_target_missing", plugins["hook@mk"]["code"])
            self.assertEqual("plugin_hook_target_missing", plugins["launch@mk"]["code"])
            self.assertEqual("updated", plugins["good@mk"]["status"])
            self.assertTrue(result["hosts"][host]["digest"])
            self.assertNotIn("error", result["hosts"][host])
        self.assertEqual({("claude", "pending"), ("codex", "pending")}, {(entry["host"], entry["status"]) for entry in sessions})

    def test_apply_installed는_동반_플러그인을_설치_명령_없이_검증해_보고한다(self):
        """apply-installed는 목록과 마켓플레이스 조회만 하며 current, not_installed, local_source, error를 각각 보고한다."""
        # Given
        fake = FakeCli()
        self.stage(fake, upgrade=False)
        clone = self.stage_local()
        fake.marketplaces = [{"name": "dirmk", "source": "directory", "installLocation": str(clone)}, {"name": "mk", "source": "github"}]
        for host in refresh.HOSTS:
            self.stage_companion(fake, host, "cur@mk", "1.0.0")
            self.stage_companion(fake, host, "bad@mk", "1.0.0", old={"manifest_version": "9.9.9"})
        fake.add("claude", "loc@dirmk", "1.0.0", self.base / "stale")
        fake.add("codex", "loc@dirmk", "1.0.0", self.base / "stale", source="local")

        # When
        result = self.run_with(fake, refresh.command_apply_installed, ["cur@mk", "bad@mk", "gone@mk", "loc@dirmk"])

        # Then
        self.assertFalse(result["ok"])
        for host in refresh.HOSTS:
            plugins = {item["plugin"]: item for item in result["hosts"][host]["plugins"]}
            self.assertEqual(
                {"cur@mk": "current", "bad@mk": "error", "gone@mk": "not_installed", "loc@dirmk": "local_source"},
                {name: item["status"] for name, item in plugins.items()},
            )
            self.assertEqual("plugin_manifest_mismatch", plugins["bad@mk"]["code"])
            self.assertEqual(("1.0.0", "1.0.0"), (plugins["cur@mk"]["before_version"], plugins["cur@mk"]["after_version"]))
            self.assertTrue(result["hosts"][host]["digest"])
        self.assertEqual([], fake.installs())

    def test_Codex_훅이_바뀌거나_생기거나_없어지거나_훅이_있는_플러그인의_파일이_바뀌면_동반_플러그인도_다시_신뢰하라고_경고한다(self):
        """Codex는 플러그인 파일 전체로 훅 신뢰를 정하므로, 훅 정의가 달라지거나 생기거나 사라질 때와 훅이 있는 플러그인의 파일이 바뀔 때 경고하고, 파일이 같거나 훅이 없거나 Claude이면 경고하지 않는다."""
        # Given
        hooks_a = [{"type": "command", "command": "echo a"}]
        hooks_b = [{"type": "command", "command": "echo b"}]
        cases = [("codex", None, hooks_a, "1.1.0", True), ("codex", hooks_a, hooks_b, "1.1.0", True),
                 ("codex", hooks_a, None, "1.1.0", True), ("codex", hooks_a, hooks_a, "1.1.0", True),
                 ("codex", hooks_a, hooks_a, "1.0.0", False), ("codex", None, None, "1.1.0", False),
                 ("claude", hooks_a, hooks_b, "1.1.0", False)]

        for index, (host, before, after, version, warned) in enumerate(cases):
            with self.subTest(host=host, before=before, after=after, version=version):
                fake = FakeCli()
                plugin_id = f"hk{index}@mk"
                self.stage_companion(fake, host, plugin_id, "1.0.0", version, old={"hooks": before}, new={"hooks": after})

                # When
                result = self.run_with(fake, refresh.refresh_companion, host, plugin_id, True, {})

                # Then
                self.assertEqual("updated" if version != "1.0.0" else "current", result["status"])
                self.assertEqual(["codex_hooks_need_trust"] if warned else [], [warning["code"] for warning in result["warnings"]])

    def test_Claude는_에이전트_환경에서도_설치한다(self):
        """Claude Code는 새 버전을 옛 폴더 옆에 두므로 에이전트 세션 환경 변수가 있어도 이 플러그인과 동반 플러그인을 설치한다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        self.stage_companion(fake, "claude", "upd@mk", "1.0.0", "1.1.0")
        agent = {"CLAUDECODE": "1", "CLAUDE_PLUGIN_ROOT": "/active", "PLUGIN_ROOT": "/active", "ORCA_TERMINAL_HANDLE": "term_x", "CLAUDE_CODE_ENTRYPOINT": "cli"}

        # When
        with patch.dict(os.environ, agent):
            result = self.run_with(fake, refresh.command_update, ["upd@mk"])

        # Then
        self.assertTrue(result["ok"])
        self.assertEqual("1.1.0", result["hosts"]["claude"]["after_version"])
        self.assertEqual("updated", result["hosts"]["claude"]["plugins"][0]["status"])
        self.assertIn(["claude", "plugin", "update", "upd@mk"], fake.installs())

    def test_Codex_차례가_진행_중이면_이_플러그인과_동반_플러그인_설치를_함께_미룬다(self):
        """호출 환경에 Codex 스레드가 있거나 최근 롤아웃이 진행 중이면 Codex 설치 명령 없이 복구 명령을 돌려주고 Claude는 설치한다."""
        # Given
        cases = [("update_deferred_active_session", {"CODEX_THREAD_ID": "thread"}, False), ("codex_turn_in_progress", {}, True)]

        for code, env, rollout in cases:
            with self.subTest(code=code):
                fake = FakeCli()
                self.stage(fake)
                for host in refresh.HOSTS:
                    self.stage_companion(fake, host, "upd@mk", "1.0.0", "1.1.0")
                if rollout:
                    write_rollout(self.base / "codex-home", "busy", [rollout_event("agent_message")])

                # When
                with patch.dict(os.environ, env):
                    result = self.run_with(fake, refresh.command_update, ["upd@mk", "gone@mk"])

                # Then
                codex = result["hosts"]["codex"]
                self.assertFalse(result["ok"])
                self.assertEqual(code, codex["error"]["code"])
                self.assertEqual(str(self.plugin_root("codex", refresh.PLUGIN, refresh.MARKETPLACE, "1.0.0").resolve()), codex["root"])
                self.assertTrue(codex["recovery_command"].endswith(" update --also upd@mk --also gone@mk --json"))
                self.assertNotIn("--offline", codex["recovery_command"])
                self.assertEqual([("upd@mk", "deferred", "1.0.0", "1.0.0"), ("gone@mk", "not_installed", None, None)], self.statuses(result, "codex"))
                self.assertEqual(code, codex["plugins"][0]["code"])
                self.assertEqual([], [command for command in fake.installs() if command[0] == "codex"])
                self.assertEqual("updated", result["hosts"]["claude"]["plugins"][0]["status"])
                self.assertIn(["claude", "plugin", "update", "upd@mk"], fake.installs())

    def test_offline_옵션과_세션_증명_코드는_없어졌다(self):
        """--offline은 인식하지 않는 인자로 거부되고, 오프라인 증명과 Orca 터미널 검사는 더 이상 없다."""
        # Given
        errors = io.StringIO()

        # When
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as refused:
            refresh.main(["update", "--offline", "--json"])

        # Then
        self.assertEqual(2, refused.exception.code)
        self.assertIn("--offline", errors.getvalue())
        for name in ("assert_update_safe", "active_orca_terminals", "ACTIVE_SESSION_ENV"):
            self.assertFalse(hasattr(refresh, name), name)
        self.assertNotIn("--offline", refresh.recovery_command(None))

    def test_Codex_게이트는_설치_명령_직전마다_다시_확인하고_막히면_이후_설치를_멈춘다(self):
        """마켓플레이스 갱신 뒤나 앞선 설치 뒤에 Codex 차례가 시작되면 그 설치부터 미루고 같은 실행의 이후 Codex 설치는 하지 않는다."""
        # Given
        main_market = ["codex", "plugin", "marketplace", "upgrade", refresh.MARKETPLACE]
        first_add = ["codex", "plugin", "add", refresh.PLUGIN_ID]
        companion_market = ["codex", "plugin", "marketplace", "upgrade", "mk"]
        cases = {
            "this-plugin": (main_market, "error", ["deferred", "deferred"], []),
            "after-this-plugin": (first_add, "updated", ["deferred", "deferred"], [first_add]),
            "companion-marketplace": (companion_market, "updated", ["deferred", "deferred"], [first_add]),
        }

        for name, (trigger, main_status, companions, adds) in cases.items():
            with self.subTest(name=name):
                fake = FakeCli()
                self.stage(fake)
                for host in refresh.HOSTS:
                    self.stage_companion(fake, host, "one@mk", "1.0.0", "1.1.0")
                    self.stage_companion(fake, host, "two@mk", "1.0.0", "1.1.0")

                def gate(host, fake=fake, trigger=trigger):
                    return refresh.RefreshError("codex_turn_in_progress", "A turn started.") if host == "codex" and trigger in fake.commands else None

                # When
                with patch.object(refresh_install, "install_gate", side_effect=gate):
                    result = self.run_with(fake, refresh.command_update, ["one@mk", "two@mk"])

                # Then
                codex = result["hosts"]["codex"]
                self.assertEqual(main_status, "error" if "error" in codex else "updated")
                if main_status == "error":
                    self.assertEqual("codex_turn_in_progress", codex["error"]["code"])
                    self.assertIn("--also one@mk --also two@mk", codex["recovery_command"])
                self.assertEqual(companions, [item["status"] for item in codex["plugins"]])
                self.assertEqual(adds, [command for command in fake.installs() if command[:3] == ["codex", "plugin", "add"]])
                self.assertEqual("updated", result["hosts"]["claude"]["plugins"][0]["status"])

    def test_로컬_소스에서_로드되는_이_플러그인은_설치하지_않고_적용에는_쓸_수_있다(self):
        """Claude 디렉터리·파일 마켓플레이스나 git이 아닌 Codex 소스는 설치 명령 없이 local_source로 보고하고 오류로 보지 않는다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        clone = self.base / "main-clone"
        (clone / ".claude-plugin").mkdir(parents=True)
        (clone / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [{"name": refresh.PLUGIN, "source": "./plugin"}]}), encoding="utf-8")
        (clone / "plugin" / ".claude-plugin").mkdir(parents=True)
        (clone / "plugin" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "7.0.0"}), encoding="utf-8")
        fake.plugins["codex"][refresh.PLUGIN_ID]["source"] = "local"

        for source in ("directory", "file"):
            with self.subTest(source=source):
                fake.marketplaces = [{"name": refresh.MARKETPLACE, "source": source, "installLocation": str(clone)}]
                fake.commands.clear()

                # When
                result = self.run_with(fake, refresh.command_update, [])
                state = refresh.load_run(result["run_id"])
                sessions = refresh.plan_sessions(FakeOrca([terminal("term_claude", "claude"), terminal("term_codex", "codex")]), state, "always", [])

                # Then
                claude, codex = result["hosts"]["claude"], result["hosts"]["codex"]
                self.assertTrue(result["ok"])
                self.assertEqual([], fake.installs())
                self.assertEqual((True, "7.0.0", "7.0.0", "loads_from_folder_on_reload"), (claude["local_source"], claude["before_version"], claude["after_version"], claude["note"]))
                self.assertEqual((True, "1.0.0", "1.0.0"), (codex["local_source"], codex["before_version"], codex["after_version"]))
                self.assertTrue(claude["digest"] and codex["digest"])
                self.assertEqual({("claude", "pending"), ("codex", "pending")}, {(entry["host"], entry["status"]) for entry in sessions})

        # Given
        (clone / "plugin" / ".claude-plugin" / "plugin.json").unlink()
        fake.commands.clear()

        # When
        fallback = self.run_with(fake, refresh.command_update, [])

        # Then
        self.assertEqual("1.0.0", fallback["hosts"]["claude"]["after_version"])
        self.assertEqual([], fake.installs())

    def test_로컬_소스인_이_플러그인은_Codex_게이트가_막혀도_미루지_않는다(self):
        """설치하지 않는 로컬 소스는 Codex 차례가 진행 중이어도 호스트 오류 없이 보고한다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        fake.plugins["codex"][refresh.PLUGIN_ID]["source"] = "local"

        # When
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "thread"}):
            result = self.run_with(fake, refresh.command_update, [])

        # Then
        self.assertNotIn("error", result["hosts"]["codex"])
        self.assertTrue(result["hosts"]["codex"]["local_source"])

    def test_JSON_객체가_아닌_마지막_줄은_진행_중으로_보고_예상하지_못한_오류는_미룬다(self):
        """마지막 줄이 null이나 배열이어도 죽지 않고 유휴로 보지 않으며, 게이트 안의 뜻밖의 예외는 상태 불명으로 미룬다."""
        # Given
        home = self.base / "codex-home"

        for text in ("null", "[]", "7", '"x"', "[1, 2]"):
            with self.subTest(text=text):
                path = write_rollout(home, "odd", [], text=json.dumps(rollout_event("task_complete")) + "\n" + text + "\n")

                # When
                idle = refresh.rollout_idle(path)
                gate = refresh.install_gate("codex")

                # Then
                self.assertFalse(idle)
                self.assertEqual("codex_turn_in_progress", gate.code)
        write_rollout(home, "idle", [rollout_event("task_complete")])
        Path(home / "sessions" / "2026" / "10" / "20" / "rollout-odd.jsonl").unlink()
        with patch.object(refresh_install, "rollout_idle", side_effect=RuntimeError("unexpected")):
            unexpected = refresh.install_gate("codex")
        with patch.object(refresh.os, "walk", side_effect=ValueError("unexpected")):
            walk = refresh.install_gate("codex")

        # Then
        self.assertEqual(["update_deferred_unknown_session_state"] * 2, [unexpected.code, walk.code])

    def test_동반_플러그인_검사_중_파일_오류는_그_항목만_오류로_남기고_실행을_저장한다(self):
        """권한 오류나 값 오류가 나도 명령이 끝나고, 해당 플러그인만 plugin_check_failed로 보고하며 이 플러그인 결과와 실행 상태는 저장된다."""
        # Given
        fake = FakeCli()
        self.stage(fake)
        for host in refresh.HOSTS:
            for plugin_id in ("denied@mk", "value@mk", "fine@mk"):
                self.stage_companion(fake, host, plugin_id, "1.0.0", "1.1.0")
        original = refresh.validate_companion

        def flaky(host, plugin_id, found):
            if plugin_id == "denied@mk":
                raise PermissionError("/private/path denied")
            if plugin_id == "value@mk":
                raise ValueError("bad")
            return original(host, plugin_id, found)

        # When
        with patch.object(refresh_plugins, "validate_companion", side_effect=flaky):
            result = self.run_with(fake, refresh.command_update, ["denied@mk", "value@mk", "fine@mk"])
        state = refresh.load_run(result["run_id"])

        # Then
        self.assertFalse(result["ok"])
        for host in refresh.HOSTS:
            plugins = {item["plugin"]: item for item in result["hosts"][host]["plugins"]}
            self.assertEqual(["plugin_check_failed"] * 2, [plugins["denied@mk"]["code"], plugins["value@mk"]["code"]])
            self.assertNotIn("/private", json.dumps(plugins["denied@mk"]))
            self.assertEqual("updated", plugins["fine@mk"]["status"])
            self.assertTrue(state["hosts"][host]["digest"])

    def test_복구_명령은_해석된_동반_플러그인을_순서대로_이어_붙인다(self):
        """복구 명령은 중복과 자기 자신을 뺀 동반 플러그인마다 --also를 셸 인용해 붙인다."""
        # When
        plain = refresh.recovery_command(None)
        with_ids = refresh.recovery_command(None, ["b@m", "a@n"])
        quoted = refresh.recovery_command(None, ["odd id@m"])
        resolved = refresh.companion_ids([refresh.PLUGIN_ID, "b@m", "a@n", "b@m"])[0]

        # Then
        self.assertTrue(plain.endswith(" update --json"))
        self.assertTrue(with_ids.endswith(" update --also b@m --also a@n --json"))
        self.assertTrue(quoted.endswith(" update --also 'odd id@m' --json"))
        self.assertEqual(["b@m", "a@n"], resolved)

    def test_훅_명령의_모든_플러그인_루트_인자와_실행기_뒤_스크립트를_확인한다(self):
        """한 명령에 대상이 여럿이거나 실행기가 여럿이어도 하나라도 없으면 이 플러그인과 동반 플러그인 모두 대상 누락으로 실패한다."""
        # Given
        root_token = "${CLAUDE_PLUGIN_ROOT}"
        launcher = f'sh "{root_token}/{refresh.HOOK_LAUNCHER}"'
        commands = {
            "second-argument": f'python3 "{root_token}/scripts/session_context.py" "{root_token}/scripts/gone.py"',
            "second-launcher": f"{launcher} session_context.py ; {launcher} gone.py",
        }
        install = self.install("codex", "1.1.0")
        hooks_path = Path(install["root"]) / "hooks" / "hooks.json"
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
        extra = self.companion("codex", "extra", "mk", "1.0.0", files=["scripts/session_context.py", refresh.HOOK_LAUNCHER])

        for name, command in commands.items():
            with self.subTest(name=name):
                changed = json.loads(json.dumps(payload))
                changed["hooks"]["SessionStart"][0]["hooks"].append({"type": "command", "command": command})
                hooks_path.write_text(json.dumps(changed), encoding="utf-8")
                (extra / "hooks").mkdir(exist_ok=True)
                (extra / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]}}), encoding="utf-8")

                # When
                with self.assertRaises(refresh.RefreshError) as strict:
                    refresh.validate_install("codex", install)
                with self.assertRaises(refresh.RefreshError) as lenient:
                    refresh.check_hooks("codex", extra, False)

                # Then
                self.assertEqual(("plugin_hook_target_missing",) * 2, (strict.exception.code, lenient.exception.code))
        hooks_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(refresh.validate_install("codex", install)["digest"])


    def test_호스트가_불러오는_훅_파일마다_필수_대상을_확인한다(self):
        """Claude는 hooks.json과 claude-hooks.json, Codex는 hooks.json과 codex-hooks.json의 대상 합집합이 호스트별 필수 대상을 채워야 한다."""
        # Given
        installs = {host: self.install(host, "1.1.0") for host in refresh.HOSTS}

        for host, install in installs.items():
            with self.subTest(host=host):
                host_file = Path(install["root"]) / "hooks" / f"{host}-hooks.json"
                original = host_file.read_text(encoding="utf-8")
                host_file.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                    {"type": "command", "command": f'sh "${{CLAUDE_PLUGIN_ROOT}}/{refresh.HOOK_LAUNCHER}" language_guard.py'}]}]}}), encoding="utf-8")

                # When
                with self.assertRaises(refresh.RefreshError) as omitted:
                    refresh.validate_install(host, install)
                host_file.write_text(original, encoding="utf-8")

                # Then
                self.assertEqual("plugin_hook_target_missing", omitted.exception.code)
                self.assertTrue(refresh.validate_install(host, install)["hooks"])

    def test_호스트_전용_등록이_빠지면_스크립트가_다른_이벤트에_남아도_실패한다(self):
        """Claude의 UserPromptSubmit session_context가 빠져 파일이 비면 plugin_hooks_invalid, Codex의 DataGrip PermissionRequest가 빠지면 plugin_hook_target_missing이다."""
        cases = {"claude": ("UserPromptSubmit", "plugin_hooks_invalid"), "codex": ("PermissionRequest", "plugin_hook_target_missing")}
        for host, (event, code) in cases.items():
            with self.subTest(host=host):
                # Given
                install = self.install(host, "1.1.0")
                host_file = Path(install["root"]) / "hooks" / f"{host}-hooks.json"
                payload = json.loads(host_file.read_text(encoding="utf-8"))
                del payload["hooks"][event]
                host_file.write_text(json.dumps(payload), encoding="utf-8")

                # When
                with self.assertRaises(refresh.RefreshError) as omitted:
                    refresh.validate_install(host, install)

                # Then
                self.assertEqual(code, omitted.exception.code)

    def test_Claude_전용_훅_파일에_훅_객체가_없으면_엄격_모드에서_실패한다(self):
        """Mod 설정이 아닌 나열 파일이 {}이면 건너뛰지 않고 plugin_hooks_invalid이다."""
        # Given
        install = self.install("claude", "1.1.0")
        (Path(install["root"]) / "hooks" / "claude-hooks.json").write_text("{}", encoding="utf-8")

        # When
        with self.assertRaises(refresh.RefreshError) as invalid:
            refresh.validate_install("claude", install)

        # Then
        self.assertEqual("plugin_hooks_invalid", invalid.exception.code)

    def test_매니페스트_훅_목록에_객체가_있으면_엄격_모드는_실패하고_동반_검사는_멈추지_않는다(self):
        """경로가 아닌 항목은 엄격 모드에서 plugin_hooks_invalid이고, 엄격하지 않은 검사는 그 항목을 건너뛴다."""
        # Given
        install = self.install("codex", "1.1.0")
        root = Path(install["root"])
        manifest = {"name": refresh.PLUGIN, "hooks": ["./hooks/hooks.json", {"hooks": {}}]}

        # When
        with self.assertRaises(refresh.RefreshError) as invalid:
            refresh.check_hooks("codex", root, True, manifest)
        relaxed, _ = refresh.check_hooks("codex", root, False, manifest)

        # Then
        self.assertEqual("plugin_hooks_invalid", invalid.exception.code)
        self.assertTrue(relaxed.startswith(b"./hooks/hooks.json\0"))

    def test_필수_대상은_호스트마다_다르다(self):
        """Claude Code는 agent_guard.py를 요구하지 않고 Codex는 요구한다."""
        # Given
        required = refresh.REQUIRED_HOOK_TARGETS

        # When
        claude, codex = set(required["claude"]), set(required["codex"])

        # Then
        self.assertNotIn("scripts/agent_guard.py", claude)
        self.assertEqual(claude | {"scripts/agent_guard.py"}, codex)

    def test_Codex_훅_파일_하나만_바뀌어도_훅_해시가_달라진다(self):
        """다이제스트는 hooks.json뿐 아니라 매니페스트가 나열한 모든 훅 파일을 읽기 순서대로 덮는다."""
        # Given
        install = self.install("codex", "1.1.0")
        root = Path(install["root"])
        before = refresh.validate_install("codex", install)["hooks"]
        host_file = root / "hooks" / "codex-hooks.json"
        payload = json.loads(host_file.read_text(encoding="utf-8"))
        payload["revision"] = "changed"
        host_file.write_text(json.dumps(payload), encoding="utf-8")

        # When
        after = refresh.validate_install("codex", install)["hooks"]
        listed = refresh.hooks_digest("codex", root)

        # Then
        self.assertNotEqual(before, after)
        self.assertEqual(after, listed)

    def test_Claude_Mod_설정과_훅이_없는_나열_파일은_훅_파일로_읽지_않는다(self):
        """Claude는 hooks.json과 훅 객체가 있는 나열 파일만 읽고, modules가 있는 Mod 설정은 건너뛴다."""
        # Given
        install = self.install("claude", "1.1.0")
        root = Path(install["root"])
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

        # When
        entries = refresh.hook_file_entries("claude", manifest)
        hooks_bytes, targets = refresh.check_hooks("claude", root, True, manifest)

        # Then
        self.assertEqual([("./hooks/hooks.json", False), ("./config/claude-mod.json", True), ("./hooks/claude-hooks.json", False)], entries)
        self.assertNotIn(b"modules", hooks_bytes)
        self.assertTrue(set(refresh.REQUIRED_HOOKS["claude"]) <= targets)

    def test_나열한_훅_파일이_없거나_루트_밖이면_엄격_모드만_실패한다(self):
        """매니페스트가 나열한 훅 파일이 없으면 plugin_hooks_missing, 루트 밖이면 plugin_hooks_invalid이고 동반 플러그인 검사는 건너뛴다."""
        # Given
        install = self.install("codex", "1.1.0")
        root = Path(install["root"])
        manifest_path = root / ".codex-plugin" / "plugin.json"
        base = json.loads(manifest_path.read_text(encoding="utf-8"))
        cases = [("./hooks/gone.json", "plugin_hooks_missing"), ("../outside.json", "plugin_hooks_invalid"), ("hooks/codex-hooks.json", "plugin_hooks_invalid")]

        for listed, code in cases:
            with self.subTest(listed=listed):
                manifest = {**base, "hooks": ["./hooks/hooks.json", listed]}
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                # When
                with self.assertRaises(refresh.RefreshError) as strict:
                    refresh.validate_install("codex", install)
                lenient = refresh.check_hooks("codex", root, False, manifest)

                # Then
                self.assertEqual(code, strict.exception.code)
                self.assertTrue(lenient[0])

    def test_매니페스트가_훅을_나열하지_않는_Codex_플러그인은_hooks_json을_읽는다(self):
        """나열이 없는 동반 플러그인은 예전처럼 hooks/hooks.json만 읽고, 파일이 없으면 None을 돌려준다."""
        # Given
        with_hooks = self.companion("codex", "plain", "mk", "1.0.0", hooks=[{"type": "command", "command": "echo a"}])
        without = self.companion("codex", "bare", "mk", "1.0.0")

        # When
        found = refresh.check_hooks("codex", with_hooks, False, {"name": "plain"})
        absent = refresh.check_hooks("codex", without, False, {"name": "bare"})

        # Then
        self.assertTrue(found[0].startswith(b"./hooks/hooks.json\0"))
        self.assertEqual((None, set()), absent)


class FakeCli:
    """Stands in for the claude and codex plugin commands: listings come from `plugins`, and an update applies `upgrades`."""

    def __init__(self):
        self.commands: list[list[str]] = []
        self.plugins: dict[str, dict[str, dict]] = {"claude": {}, "codex": {}}
        self.upgrades: dict[tuple[str, str], dict] = {}
        self.marketplaces: list[dict] = []
        self.failing: set[tuple[str, ...]] = set()

    def add(self, host, plugin_id, version, root, enabled=True, source="git"):
        self.plugins[host][plugin_id] = {"version": version, "root": str(root), "enabled": enabled, "source": source}

    def upgrade(self, host, plugin_id, version, root):
        self.upgrades[(host, plugin_id)] = {"version": version, "root": str(root)}

    def installs(self):
        return [command for command in self.commands if "list" not in command]

    def listing(self, host):
        if host == "claude":
            return [{"id": name, "enabled": item["enabled"], "version": item["version"], "installPath": item["root"]} for name, item in self.plugins[host].items()]
        installed = []
        for name, item in self.plugins[host].items():
            entry = {"pluginId": name, "enabled": item["enabled"], "version": item["version"]}
            if item["source"]:
                entry["marketplaceSource"] = {"sourceType": item["source"]}
            installed.append(entry)
        return {"installed": installed}

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.commands.append(argv)
        host, rest = argv[0], argv[1:]
        if rest == ["plugin", "list", "--json"]:
            payload = self.listing(host)
        elif rest == ["plugin", "marketplace", "list", "--json"]:
            payload = self.marketplaces
        else:
            if tuple(argv) in self.failing:
                raise refresh.RefreshError("command_failed", "the command failed")
            if rest[:2] == ["plugin", "update" if host == "claude" else "add"] and (host, rest[2]) in self.upgrades:
                self.plugins[host][rest[2]].update(self.upgrades[(host, rest[2])])
            return refresh.subprocess.CompletedProcess(argv, 0, "", "")
        return refresh.subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")


def rollout_event(kind, outer="event_msg"):
    return {"type": outer, "payload": {"type": kind}}


def write_rollout(home, name, events, *, text=None, age=0.0):
    path = Path(home) / "sessions" / "2026" / "10" / "20" / f"rollout-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    if age:
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
    return path


class CodexHookTrustTest(unittest.TestCase):
    def listing(self, root, trust):
        hook = {"key": f"{refresh.CODEX_HOOK_TRUST.PLUGIN_ID}:hooks/hooks.json:pre_tool_use:0:0", "trustStatus": trust,
                "pluginId": refresh.CODEX_HOOK_TRUST.PLUGIN_ID, "currentHash": "sha256:x",
                "sourcePath": str(Path(root) / "hooks" / "hooks.json")}
        return [{"data": [{"cwd": str(Path.home()), "hooks": [hook]}]}]

    def test_신뢰할_훅이_없으면_성공으로_보고_검증되지_않은_설치본은_이유를_돌려준다(self):
        """이 플러그인의 훅이 모두 신뢰됨이면 None이고, git 저장소가 아닌 설치본의 modified 훅은 신뢰하지 않고 이유를 돌려준다."""
        # Given
        with tempfile.TemporaryDirectory() as root:
            calls = [self.listing(root, "trusted"), self.listing(root, "modified")]
            with (
                patch.object(refresh_core, "executable", side_effect=lambda name: name),
                patch.object(refresh.CODEX_HOOK_TRUST, "app_server_calls", side_effect=lambda *args: calls.pop(0)),
            ):
                # When
                outcomes = [refresh.trust_codex_hooks(), refresh.trust_codex_hooks()]

        # Then
        self.assertIsNone(outcomes[0])
        self.assertIsInstance(outcomes[1], str)
        self.assertEqual([], calls)


class CodexGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "codex-home"
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for name in refresh.CODEX_TURN_ENV:
            os.environ.pop(name, None)

    def code(self):
        gate = refresh.install_gate("codex")
        return gate.code if gate else None

    def test_Claude_Code는_언제나_설치할_수_있다(self):
        """Claude Code는 새 버전을 옆에 두므로 Codex 환경이나 진행 중인 롤아웃이 있어도 막지 않는다."""
        # Given
        write_rollout(self.home, "busy", [rollout_event("agent_message")])

        # When
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "thread"}):
            gate = refresh.install_gate("claude")

        # Then
        self.assertIsNone(gate)

    def test_Codex_차례_안에서_실행하면_세션_환경_변수만으로_미룬다(self):
        """CODEX_THREAD_ID나 CODEX_SESSION_ID가 있으면 롤아웃을 보기 전에 활성 세션으로 미룬다."""
        for name in refresh.CODEX_TURN_ENV:
            with self.subTest(name=name), patch.dict(os.environ, {name: ""}):
                # When
                code = self.code()

                # Then
                self.assertEqual("update_deferred_active_session", code)

    def test_마지막_완전한_줄이_차례_종료이면_설치할_수_있다(self):
        """최근 롤아웃의 마지막 줄이 task_complete나 turn_aborted이면 유휴로 보고, 바깥 type이 다르면 진행 중으로 본다."""
        # Given
        write_rollout(self.home, "done", [rollout_event("task_started"), rollout_event("task_complete")])
        write_rollout(self.home, "aborted", [rollout_event("task_started"), rollout_event("turn_aborted")])
        idle = self.code()
        wrong_outer = write_rollout(self.home, "wrong", [rollout_event("task_complete", outer="response_item")])

        # When
        busy = self.code()
        wrong_outer.unlink()

        # Then
        self.assertIsNone(idle)
        self.assertEqual("codex_turn_in_progress", busy)
        self.assertIsNone(self.code())

    def test_마지막_줄이_차례_종료가_아니면_진행_중으로_미룬다(self):
        """마지막 줄이 다른 이벤트이거나 JSON이 아니거나 비어 있으면 진행 중으로 보고, 한 세션만 진행 중이어도 미룬다."""
        # Given
        write_rollout(self.home, "done", [rollout_event("task_complete")])
        cases = {
            "message": [rollout_event("task_complete"), rollout_event("agent_message")],
            "started": [rollout_event("task_started")],
        }

        for name, events in cases.items():
            with self.subTest(name=name):
                path = write_rollout(self.home, "busy", events)

                # When
                code = self.code()
                path.unlink()

                # Then
                self.assertEqual("codex_turn_in_progress", code)
        for name, text in {"not-json": '{"type": "event_msg"}\nnot json\n', "empty": "", "blank": "\n\n"}.items():
            with self.subTest(name=name):
                path = write_rollout(self.home, "odd", [], text=text)
                code = self.code()
                path.unlink()
                self.assertEqual("codex_turn_in_progress", code)

    def test_줄이_끝나지_않은_롤아웃은_진행_중으로_미룬다(self):
        """마지막 줄이 줄바꿈 없이 끝나면 쓰는 중으로 보고, 앞 줄이 task_complete여도 미룬다."""
        # Given
        complete = json.dumps(rollout_event("task_complete"))
        cases = {
            "truncated": complete + "\n" + '{"type": "event_msg", "payl',
            "no-newline": complete,
        }

        for name, text in cases.items():
            with self.subTest(name=name):
                path = write_rollout(self.home, "partial", [], text=text)

                # When
                code = self.code()
                path.unlink()

                # Then
                self.assertEqual("codex_turn_in_progress", code)

    def test_오래된_롤아웃은_무시하고_최근_롤아웃만_본다(self):
        """30분보다 오래 전에 수정된 롤아웃은 진행 중이어도 보지 않고, 그 안쪽 롤아웃은 본다."""
        # Given
        write_rollout(self.home, "old", [rollout_event("agent_message")], age=31 * 60)
        ignored = self.code()
        write_rollout(self.home, "recent", [rollout_event("agent_message")], age=29 * 60)

        # When
        seen = self.code()

        # Then
        self.assertIsNone(ignored)
        self.assertEqual("codex_turn_in_progress", seen)

    def test_세션_폴더가_없으면_진행_중인_차례가_없다고_본다(self):
        """Codex 세션 폴더가 아예 없으면 세션이 없는 것이므로 설치할 수 있다."""
        # When
        code = self.code()

        # Then
        self.assertIsNone(code)

    def test_세션_폴더를_읽을_수_없으면_상태를_알_수_없다고_미룬다(self):
        """폴더 순회 오류, 폴더가 아닌 세션 경로, 읽을 수 없는 롤아웃은 상태 불명으로 미룬다."""
        # Given
        (self.home / "sessions").mkdir(parents=True)

        def broken_walk(top, onerror=None, **kwargs):
            onerror(PermissionError("denied"))
            return iter(())

        # When
        with patch.object(refresh.os, "walk", broken_walk):
            walk_error = self.code()
        write_rollout(self.home, "recent", [rollout_event("task_complete")])
        with patch.object(refresh_install, "rollout_idle", side_effect=PermissionError("denied")):
            read_error = self.code()
        shutil.rmtree(self.home / "sessions")
        (self.home / "sessions").write_text("not a folder", encoding="utf-8")
        not_folder = self.code()

        # Then
        self.assertEqual(["update_deferred_unknown_session_state"] * 3, [walk_error, read_error, not_folder])

    def test_꼬리_범위를_넘는_롤아웃은_마지막_줄만_보고_판단한다(self):
        """파일이 꼬리 한도보다 커도 마지막 완전한 줄로 판단하고, 한도보다 긴 마지막 줄은 확인할 수 없어 미룬다."""
        # Given
        padding = {"type": "event_msg", "payload": {"type": "agent_message", "text": "x" * 1000}}
        size = write_rollout(self.home, "long", [padding] * 200 + [rollout_event("task_complete")]).stat().st_size
        idle = self.code()
        huge = {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "y" * (refresh.ROLLOUT_TAIL_BYTES + 10)}}
        write_rollout(self.home, "long", [rollout_event("task_started"), huge])

        # When
        deferred = self.code()

        # Then
        self.assertGreater(size, refresh.ROLLOUT_TAIL_BYTES)
        self.assertIsNone(idle)
        self.assertEqual("codex_turn_in_progress", deferred)


class WaitLimitTest(unittest.TestCase):
    def test_바쁜_세션과_이_세션은_한_시간까지_기다린다(self):
        """넘겨받은 세션과 이 세션의 대기 한도는 모두 한 시간이다."""
        # Then
        self.assertEqual((3600, 3600), (refresh.FOLLOW_UP_SECONDS, refresh.SELF_WAIT_SECONDS))


@unittest.skipUnless(shutil.which("orca") and os.environ.get("ORCA_TERMINAL_HANDLE"), "Run inside an Orca terminal with the Orca CLI to check the live response shapes.")
class LiveOrcaContractTest(unittest.TestCase):
    def test_실제_Orca_응답이_스크립트가_읽는_형태를_유지한다(self):
        """실제 Orca의 터미널 목록, 대기 확인, 화면, 커서 응답이 스크립트가 쓰는 필드를 그대로 제공한다."""
        # Given
        orca = refresh.Orca()
        handle = os.environ["ORCA_TERMINAL_HANDLE"]

        # When
        terminals = {item["handle"]: item for item in orca.terminals()}
        idle = orca.idle(handle)
        lines, draft = orca.screen(handle)

        # Then
        self.assertIn(handle, terminals)
        self.assertTrue({"connected", "writable"} <= set(terminals[handle]))
        self.assertIn(refresh.terminal_host(orca, terminals[handle]), {"claude", "codex"})
        self.assertIsInstance(idle, bool)
        self.assertTrue(lines and all(isinstance(line, str) for line in lines))
        self.assertTrue(draft is None or isinstance(draft, str))


if __name__ == "__main__":
    unittest.main()
