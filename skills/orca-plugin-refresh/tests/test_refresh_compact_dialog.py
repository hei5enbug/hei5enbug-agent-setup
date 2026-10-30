from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import CLAUDE_EMPTY, FakeOrca, refresh, terminal

import refresh_dialog
import refresh_sessions

HANDLE = "term_claude"
DOWN = "\x1b[B"
ENTER = "\r"
TITLE = " /compact acts on the main conversation, not this agent"
CANCEL = "Cancel"
RUN = "Run /compact on the main conversation"


def dialog_screen(selected, mark="❯"):
    options = [CANCEL, RUN]
    rows = [f" {mark} {label}" if label == selected else f"   {label}" for label in options]
    return ["❯ /compact", "", TITLE, "", *rows, "", "  Esc to cancel"]


OTHER_DIALOG = ["❯ /compact", "", " Do you want to proceed?", "", " ❯ 1. Yes", "   2. No", "", "  Esc to cancel"]


class CompactDialogTest(unittest.TestCase):
    setUp_base = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker

    def setUp(self):
        self.setUp_base()
        patcher = patch.object(refresh_dialog, "SETTLE_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def session(self, fake):
        self.write_marker(HANDLE, "claude", digest="old")
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])
        sessions[0]["actions"] = ["compact"]
        return sessions

    def dialog_fake(self, screen, *, moves_selection=True, typed=None):
        """A session that answers /compact with a dialog; Down moves the selection and Enter on the run option compacts."""
        enters = []

        def on_send(fake, handle, text):
            fake.screens[handle] = list(screen)

        def on_keys(fake, handle, text):
            if text == DOWN and moves_selection and fake.screens[handle][4].lstrip()[0] in "❯>":
                fake.screens[handle] = dialog_screen(RUN)
            elif text == ENTER:
                enters.append(fake.screens[handle][4:6])
                if fake.screens[handle][5].lstrip()[0] in "❯>":
                    self.write_marker(handle, "claude")
                    fake.screens[handle] = list(CLAUDE_EMPTY)

        fake = FakeOrca([terminal(HANDLE, "claude")], on_send=on_send, typed=typed)
        fake.on_keys = on_keys
        fake.enters = enters
        return fake

    def drive(self, fake, sessions, seconds=5):
        refresh.drive(fake, sessions, self.state, time.time() + seconds, sleep=lambda seconds: None)

    def test_Cancel이_선택된_대화상자는_아래_키로_옮긴_뒤에만_Enter를_보내_compact를_끝낸다(self):
        """선택 표시가 Cancel일 때는 아래 키만 보내고, 선택이 Run으로 옮겨진 것을 다시 읽은 뒤에만 Enter를 보내 done으로 확인한다."""
        for mark in ("❯", ">"):
            with self.subTest(mark=mark):
                # Given
                fake = self.dialog_fake(dialog_screen(CANCEL, mark))
                sessions = self.session(fake)

                # When
                self.drive(fake, sessions)

                # Then
                self.assertEqual(("done", ["compact"]), (sessions[0]["status"], sessions[0]["completed"]))
                self.assertEqual([(HANDLE, DOWN), (HANDLE, ENTER)], fake.keystrokes)
                self.assertEqual([(HANDLE, "/compact")], fake.sent)
                self.assertEqual(1, len(fake.enters))

    def test_이미_Run이_선택된_대화상자는_Enter만_보낸다(self):
        """선택이 처음부터 Run on the main conversation이면 아래 키 없이 Enter 한 번으로 확인한다."""
        # Given
        fake = self.dialog_fake(dialog_screen(RUN))
        sessions = self.session(fake)

        # When
        self.drive(fake, sessions)

        # Then
        self.assertEqual("done", sessions[0]["status"])
        self.assertEqual([(HANDLE, ENTER)], fake.keystrokes)

    def test_선택이_Cancel에서_움직이지_않으면_Enter를_보내지_않고_실패로_끝낸다(self):
        """아래 키를 보내도 선택이 Cancel에 남으면 Cancel을 확인하지 않고 compact_dialog_open으로 끝내며 키 횟수를 제한한다."""
        # Given
        fake = self.dialog_fake(dialog_screen(CANCEL), moves_selection=False)
        sessions = self.session(fake)

        # When
        self.drive(fake, sessions)

        # Then
        self.assertEqual(("failed", "compact_dialog_open"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertNotIn((HANDLE, ENTER), fake.keystrokes)
        self.assertLessEqual(len(fake.keystrokes), refresh_dialog.MAX_MOVES)

    def test_알_수_없는_대화상자는_키를_보내지_않고_compact_dialog_open으로_끝낸다(self):
        """제목이 다른 선택 목록이나 선택지가 다른 compact 대화상자는 건드리지 않고 실패로 알린다."""
        extra = dialog_screen(CANCEL)[:-2] + ["   Always run", "", "  Esc to cancel"]
        for name, screen in (("other", OTHER_DIALOG), ("extra_option", extra)):
            with self.subTest(name=name):
                # Given
                self.setUp()
                fake = self.dialog_fake(screen)
                sessions = self.session(fake)

                # When
                self.drive(fake, sessions)

                # Then
                self.assertEqual(("failed", "compact_dialog_open"), (sessions[0]["status"], sessions[0]["detail"]))
                self.assertEqual([], fake.keystrokes)
                self.assertEqual([(HANDLE, "/compact")], fake.sent)

    def test_대화상자가_열린_화면에는_다음_실행이_명령도_글자도_입력하지_않는다(self):
        """준비 확인은 열린 대화상자를 준비되지 않음으로 보고, 입력 초안이 있어도 키 하나 보내지 않는다."""
        for typed in (None, "남은 글자"):
            with self.subTest(typed=typed):
                # Given
                fake = FakeOrca([terminal(HANDLE, "claude")], screens={HANDLE: dialog_screen(CANCEL)}, typed={HANDLE: typed} if typed else None)
                self.write_marker(HANDLE, "claude", digest="old")
                sessions = refresh.plan_sessions(fake, self.state, "auto", [])
                live = {item["handle"]: item for item in fake.terminals()}

                # When
                reason, _ = refresh_sessions.ready(fake, sessions[0], live)

                # Then
                self.assertEqual("input_unknown", reason)
                self.assertEqual(([], []), (fake.sent, fake.keystrokes))

    def test_일반_화면의_선택_표시_없는_입력창은_대화상자로_보지_않는다(self):
        """입력창이 화면 끝에 있는 일반 화면과 명령을 되풀이해 보여 주는 화면은 대화상자로 판정하지 않는다."""
        # Given
        screens = [CLAUDE_EMPTY, ["❯ /compact", "  ⎿  Compacted", "> quoted text"]]

        # When
        kinds = [refresh_dialog.classify(screen) for screen in screens]

        # Then
        self.assertEqual([("none", None), ("none", None)], kinds)


if __name__ == "__main__":
    unittest.main()
