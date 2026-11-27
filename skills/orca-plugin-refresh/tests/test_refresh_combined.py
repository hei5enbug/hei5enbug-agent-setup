from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orca_plugin_refresh_combined_under_test", SKILL / "scripts" / "orca_plugin_refresh.py")
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)

RUN_ID = "b" * 32
UPDATED = {"ok": True, "run_id": RUN_ID, "script": "/p/orca_plugin_refresh.py",
           "hosts": {"claude": {"before_version": "1.0.0", "after_version": "1.1.0", "plugins": []},
                     "codex": {"error": {"code": "plugin_not_installed", "message": "not installed"}}}}
ALL_FAILED = {"ok": False, "run_id": RUN_ID, "script": "/p/orca_plugin_refresh.py",
              "hosts": {"claude": {"error": {"code": "command_failed", "message": "x"}},
                        "codex": {"error": {"code": "update_deferred_active_session", "message": "y"}}}}
APPLIED = {"ok": True, "run_id": RUN_ID, "summary": {"done": 1}, "sessions": [{"terminal": "term_demo-a", "status": "done"}]}
SKIPPED = {"ok": False, "run_id": RUN_ID, "summary": {"skipped": 1}, "sessions": [{"terminal": "term_demo-a", "status": "skipped"}]}
ORPHANS = {"ok": True, "run_id": RUN_ID, "orphans": [], "recommended": []}


class Calls:
    """Patches the three steps of a refresh run and records which ran, with their arguments."""

    def __init__(self, update=UPDATED, applied=APPLIED, installed=None):
        self.log: list[tuple] = []
        self.update, self.applied, self.installed = update, applied, installed or update

    def step(self, name, result):
        def run(*args, **kwargs):
            self.log.append((name, args, kwargs))
            if isinstance(result, Exception):
                raise result
            return result
        return run

    def __enter__(self):
        self.patches = [
            patch.object(refresh, "command_update", side_effect=self.step("update", self.update)),
            patch.object(refresh, "command_apply_installed", side_effect=self.step("apply-installed", self.installed)),
            patch.object(refresh, "command_apply", side_effect=self.step("apply", self.applied)),
            patch.object(refresh, "run_orphans", side_effect=self.step("orphans", ORPHANS)),
        ]
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *exc):
        for item in self.patches:
            item.stop()

    @property
    def names(self):
        return [entry[0] for entry in self.log]


def run_main(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = refresh.main(list(argv))
    return code, json.loads(out.getvalue())


class RefreshCommandTest(unittest.TestCase):
    def test_업데이트가_성공하면_같은_run_id로_apply와_orphans를_돌리고_세_결과를_한_객체에_담는다(self):
        """term_demo-a: 한 호스트라도 오류가 없으면 refresh는 반환된 run id로 apply와 orphans를 이어 돌려 update, apply, orphans를 모두 내고 종료 코드 0이다."""
        # Given
        with Calls() as calls:
            # When
            code, output = run_main("refresh", "--also", "demo@market", "--compact", "never", "--json")

        # Then
        self.assertEqual(["update", "apply", "orphans"], calls.names)
        self.assertEqual((["demo@market"],), calls.log[0][1])
        self.assertEqual((RUN_ID, "never", [], 20), calls.log[1][1])
        self.assertEqual((RUN_ID,), calls.log[2][1])
        self.assertEqual({"ok", "update", "apply", "orphans", "questions"}, set(output))
        self.assertEqual((0, True), (code, output["ok"]))

    def test_모든_호스트가_오류면_apply와_orphans를_돌리지_않고_update_결과만_내며_종료_코드_2다(self):
        """모든 호스트에 이 플러그인 오류가 있으면 refresh는 apply도 orphans도 돌리지 않고 update 결과만 낸다."""
        # Given
        with Calls(update=ALL_FAILED) as calls:
            # When
            code, output = run_main("refresh", "--json")

        # Then
        self.assertEqual(["update"], calls.names)
        self.assertEqual({"ok", "update"}, set(output))
        self.assertEqual(2, code)

    def test_apply가_세션을_건너뛰어도_orphans는_돌리고_종료_코드_2다(self):
        """term_demo-a: apply가 세션을 skipped로 남겨도 orphans는 돌고 전체 ok는 false이며 종료 코드는 2다."""
        # Given
        with Calls(applied=SKIPPED) as calls:
            # When
            code, output = run_main("refresh", "--json")

        # Then
        self.assertEqual(["update", "apply", "orphans"], calls.names)
        self.assertEqual(SKIPPED, output["apply"])
        self.assertEqual((2, False), (code, output["ok"]))

    def test_apply가_오류를_내도_그_오류를_apply_칸에_담고_orphans를_돌린다(self):
        """다른 실행이 보내는 중이라 apply가 already_running 오류를 내도 refresh는 오류를 apply 칸에 담고 orphans를 돌린다."""
        # Given
        failure = refresh.RefreshError("already_running", "another run is sending")
        with Calls(applied=failure) as calls:
            # When
            code, output = run_main("refresh", "--json")

        # Then
        self.assertEqual(["update", "apply", "orphans"], calls.names)
        self.assertEqual({"ok": False, "error": {"code": "already_running", "message": "another run is sending"}}, output["apply"])
        self.assertEqual(2, code)

    def test_installed는_apply_installed를_돌리고_마켓과_설치_명령을_부르지_않는다(self):
        """--installed는 command_apply_installed만 시작점으로 쓰고 command_update(마켓플레이스와 설치 명령)는 부르지 않는다."""
        # Given
        with Calls() as calls:
            # When
            code, output = run_main("refresh", "--installed", "--json")

        # Then
        self.assertEqual(["apply-installed", "apply", "orphans"], calls.names)
        self.assertEqual((0, RUN_ID), (code, output["update"]["run_id"]))


class SkillStepsTest(unittest.TestCase):
    def test_SKILL은_첫_단계에서_refresh를_부르고_보통_실행에서_apply와_orphans를_손으로_돌리라고_하지_않는다(self):
        """SKILL.md 1단계는 refresh를 이름으로 부르고, 어떤 단계도 모델에게 apply나 orphans 명령을 따로 돌리라고 하지 않는다."""
        # Given
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        steps = dict(re.findall(r"^(\d)\. \*\*.*?\*\*(.*?)(?=^\d\. \*\*|^`--compact`)", text, re.S | re.M))

        # When
        by_hand = [number for number, body in steps.items() if re.search(r"run `python3 <script> (apply|orphans) ", body)]

        # Then
        self.assertIn("refresh", steps["1"].split("python3 <script>")[1][:30])
        self.assertEqual([], by_hand)


if __name__ == "__main__":
    unittest.main()
