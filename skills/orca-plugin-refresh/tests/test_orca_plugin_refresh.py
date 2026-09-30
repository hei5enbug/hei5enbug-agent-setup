from __future__ import annotations

import importlib.util
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


def terminal(handle, host):
    return {"handle": handle, "agentIdentity": host, "connected": True, "writable": True, "orphaned": False, "title": handle, "worktreePath": "/tmp/work"}


class InputStateTest(unittest.TestCase):
    def test_Claude_입력창은_비었거나_안내_문구일_때만_빈_것으로_본다(self):
        """구분선 사이 입력 줄이 비었거나 Try 안내 문구면 비었다고 보고, 글자가 있으면 입력 중으로 본다."""
        # Given
        placeholder = CLAUDE_EMPTY[:3] + ['❯ Try "edit <filepath> to..."'] + CLAUDE_EMPTY[4:]
        typed = CLAUDE_EMPTY[:3] + ["❯ 반쯤 쓴 질문"] + CLAUDE_EMPTY[4:]
        multiline = CLAUDE_EMPTY[:3] + ["❯ ", "  둘째 줄"] + CLAUDE_EMPTY[4:]

        # When
        states = [refresh.input_state("claude", lines) for lines in (CLAUDE_EMPTY, placeholder, typed, multiline, ["no composer"])]

        # Then
        self.assertEqual(["empty", "empty", "text", "text", "unknown"], states)

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
        for name in ("POLL_SECONDS", "DRAFT_STABLE_SECONDS"):
            patcher = patch.object(refresh, name, 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.state = {"hosts": {"claude": {"digest": "d", "root": self.temp.name}, "codex": {"digest": "d", "root": self.temp.name}}, "sessions": {}}

    def write_marker(self, handle, host, digest="d"):
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "host": host, "root": self.temp.name, "digest": digest, "written_at": refresh.now()}
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

    def test_입력이_남은_세션은_보내지_않고_기한에_건너뛴다(self):
        """입력 줄에 글자가 있으면 명령을 보내지 않고, 기한이 지나면 이유와 함께 건너뛴 것으로 남긴다."""
        # Given
        typed = CLAUDE_EMPTY[:3] + ["❯ 쓰던 글"] + CLAUDE_EMPTY[4:]
        fake = FakeOrca([terminal("term_claude", "claude")], screens={"term_claude": typed})
        sessions = refresh.plan_sessions(fake, self.state, "never", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.3, sleep=lambda seconds: None)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "unsent_input"), (sessions[0]["status"], sessions[0]["detail"]))

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

    def test_Claude_추천_문구만_있으면_보내고_실제_입력이_있으면_지키고_건너뛴다(self):
        """Orca 초안이 추천 문구뿐이면 한 글자 확인 뒤 reload를 보내고, 실제로 친 글이 있으면 그 글을 그대로 두고 건너뛴다."""
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
        self.assertEqual(("skipped", "unsent_input"), (by_handle["term_typed"]["status"], by_handle["term_typed"]["detail"]))
        self.assertEqual("쓰던 질문", fake.draft("term_typed"))
        self.assertEqual("다음에 할 일 추천", fake.draft("term_ghost"))
        self.assertNotIn(("term_typed", "/reload-plugins"), fake.sent)
        self.assertEqual(2, sum(1 for handle, _ in fake.keystrokes if handle == "term_typed"))

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
    def test_추천을_받아들인_입력은_이전_확인_결과로_보내지_않는다(self):
        """reload 전에 추천 문구로 확인했더라도 사용자가 그 추천을 받아들이면 compact 전에 다시 확인해 보내지 않는다."""
        # Given
        self.write_marker("term_claude", "claude", digest="old")

        def accept_suggestion(fake, handle, text):
            if text == "/reload-plugins":
                fake.show(handle, "  ⎿  Reloaded: 7 plugins")
                fake.typed[handle] = "추천 문구"
        fake = FakeOrca([terminal("term_claude", "claude")], ghosts={"term_claude": "추천 문구"}, on_send=accept_suggestion)
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.5, sleep=lambda seconds: None)

        # Then
        self.assertEqual(["/reload-plugins"], [text for _, text in fake.sent])
        self.assertEqual(("skipped", "unsent_input"), (sessions[0]["status"], sessions[0]["detail"]))
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

    def test_보내기_직전에_입력이_바뀌면_보내지_않는다(self):
        """준비 확인 뒤 보내기 직전에 초안이 달라지면 명령을 보내지 않고 다시 기다린다."""
        # Given
        fake = FakeOrca([terminal("term_claude", "claude")], typed={"term_claude": "방금 친 글"})
        entry = {"handle": "term_claude", "host": "claude", "actions": ["reload"], "status": "pending", "observed_draft": None}

        # When
        with patch.object(refresh, "ready", return_value=(None, CLAUDE_EMPTY)):
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
        with patch.object(refresh, "claude_has_prompts", return_value=True):
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
        with patch.object(refresh, "executable", return_value="orca"), patch.object(refresh, "run", side_effect=completed):
            orca = refresh.Orca()
            observed = [orca.idle("term_x"), orca.idle("term_x")]
            with self.assertRaises(refresh.RefreshError) as stale:
                orca.idle("term_x")

        # Then
        self.assertEqual([False, True], observed)
        self.assertEqual("orca_rejected", stale.exception.code)


class UpdateTest(unittest.TestCase):
    def test_같은_버전의_미배포_변경과_Codex_훅_변경을_경고한다(self):
        """Claude가 같은 버전이라 새 파일을 받지 못하면 버전을 올리라고, Codex 훅 정의가 바뀌면 다시 신뢰하라고 경고한다."""
        # Given
        states = {"claude": [{"version": "1.0.0", "root": "/c/1.0.0"}] * 2, "codex": [{"version": "1.0.0", "root": "/x/1.0.0"}, {"version": "1.1.0", "root": "/x/1.1.0"}]}
        snapshots = {"/c/1.0.0": {"digest": "a", "hooks": "h"}, "/x/1.0.0": {"digest": "a", "hooks": "h1"}, "/x/1.1.0": {"digest": "b", "hooks": "h2"}}
        commands: list[list[str]] = []

        def fake_installed(host):
            return states[host].pop(0)

        # When
        with (
            patch.object(refresh, "installed", side_effect=fake_installed),
            patch.object(refresh, "snapshot", side_effect=lambda root: snapshots[root]),
            patch.object(refresh, "run", side_effect=lambda argv, **kwargs: commands.append(list(argv))),
            patch.object(refresh, "executable", side_effect=lambda name: name),
            patch.object(refresh, "claude_unreleased_changes", return_value=(["skills/x/SKILL.md"], None)),
        ):
            claude = refresh.update_host("claude")
            codex = refresh.update_host("codex")

        # Then
        self.assertEqual(["unreleased_same_version"], [warning["code"] for warning in claude["warnings"]])
        self.assertFalse(claude["instructions_changed"])
        self.assertEqual(["codex_hooks_need_trust"], [warning["code"] for warning in codex["warnings"]])
        self.assertTrue(codex["instructions_changed"])
        self.assertEqual(["claude", "plugin", "marketplace", "update", "hei5enbug"], commands[0])
        self.assertEqual(["codex", "plugin", "add", "hei5enbug-agent-setup@hei5enbug"], commands[3])

    def test_미배포_변경을_확인하지_못하면_변경_없음으로_보고하지_않는다(self):
        """설치 커밋이나 마켓플레이스 비교를 확인할 수 없으면 경고 없이 넘어가지 않고 확인 불가 경고를 남긴다."""
        # Given
        states = [{"version": "1.0.0", "root": "/c/1.0.0"}] * 2

        # When
        with (
            patch.object(refresh, "installed", side_effect=lambda host: states.pop(0)),
            patch.object(refresh, "snapshot", return_value={"digest": "a", "hooks": "h"}),
            patch.object(refresh, "run"),
            patch.object(refresh, "executable", side_effect=lambda name: name),
            patch.object(refresh, "claude_unreleased_changes", return_value=([], "the installed commit is not in the marketplace clone")),
        ):
            result = refresh.update_host("claude")

        # Then
        self.assertEqual(["unreleased_check_unavailable"], [warning["code"] for warning in result["warnings"]])


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
        self.assertTrue({"agentIdentity", "connected", "writable"} <= set(terminals[handle]))
        self.assertIsInstance(idle, bool)
        self.assertTrue(lines and all(isinstance(line, str) for line in lines))
        self.assertTrue(draft is None or isinstance(draft, str))


if __name__ == "__main__":
    unittest.main()
