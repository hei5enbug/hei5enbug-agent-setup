from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "orca_plugin_refresh.py"
SPEC = importlib.util.spec_from_file_location("orca_plugin_refresh_claude_update_under_test", SCRIPT)
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)
import refresh_claude_update as claude_update
from refresh_process import ProcessOs, SessionProcess, release_report

CLAUDE_PATH = "/usr/local/bin/claude"
VERSIONS = "/home/test/.local/share/claude/versions"


class FakeClaude:
    """A fake `claude` install: `claude update` switches the current release, and every call is recorded."""

    def __init__(self, current="2.1.317", after="2.1.318", returncode=0, output="", error=None):
        self.current = current
        self.after = after
        self.returncode = returncode
        self.output = output
        self.error = error
        self.calls = []

    def run(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if self.error:
            raise self.error
        if self.returncode == 0:
            self.current = self.after
        return subprocess.CompletedProcess(list(argv), self.returncode, "", self.output)

    def system(self, environ=None, settings=None, which=CLAUDE_PATH, platform="linux"):
        files = settings or {}
        return claude_update.UpdateSystem(
            environ=lambda: environ or {},
            read_json=lambda path: files.get(str(path)),
            which=lambda name: which,
            run=self.run,
            release=lambda: self.current,
            platform=platform,
        )

    def process_os(self):
        return ProcessOs(
            which=lambda name: CLAUDE_PATH,
            realpath=lambda path: f"{VERSIONS}/{self.current}",
            exists=lambda path: True,
        )


def session_on(release):
    return SessionProcess(pid=1, argv=("claude",), env={}, exe=f"{VERSIONS}/{release}")


class ClaudeUpdateTest(unittest.TestCase):
    def test_업데이트가_성공하면_전후_릴리스를_보고하고_이전_릴리스의_세션을_outdated로_본다(self):
        """claude update가 2.1.317에서 2.1.318로 올리면 두 릴리스를 보고하고, 2.1.317 세션은 갱신 뒤에 읽은 설치본 때문에 host_release_outdated가 된다."""
        # Given
        fake = FakeClaude(current="2.1.317", after="2.1.318")
        session = session_on("2.1.317")
        before_step = release_report(session, fake.process_os())

        # When
        step = claude_update.run_claude_update(fake.system())
        after_step = release_report(session, fake.process_os())

        # Then
        self.assertEqual({"status": "updated", "before": "2.1.317", "after": "2.1.318"}, step)
        self.assertEqual([([CLAUDE_PATH, "update"], 300.0)], fake.calls)
        self.assertNotIn("host_release_outdated", before_step)
        self.assertEqual({"running": "2.1.317", "installed": "2.1.318"}, after_step["host_release_outdated"])

    def test_릴리스가_그대로면_current로_보고한다(self):
        """claude update 뒤에도 릴리스가 같으면 current로 보고하고 두 릴리스를 모두 담는다."""
        # Given
        fake = FakeClaude(current="2.1.318", after="2.1.318")

        # When
        step = claude_update.run_claude_update(fake.system())

        # Then
        self.assertEqual({"status": "current", "before": "2.1.318", "after": "2.1.318"}, step)

    def test_환경변수_DISABLE_UPDATES가_참이면_아무것도_실행하지_않고_건너뛴다(self):
        """DISABLE_UPDATES가 1, true, yes, on(대소문자 무관)이면 claude update를 실행하지 않고 updates_disabled로 건너뛴다."""
        for value in ("1", "true", "YES", "On"):
            with self.subTest(value=value):
                # Given
                fake = FakeClaude()

                # When
                step = claude_update.run_claude_update(fake.system(environ={"DISABLE_UPDATES": value}))

                # Then
                self.assertEqual({"status": "skipped", "before": None, "after": None, "reason": "updates_disabled"}, step)
                self.assertEqual([], fake.calls)

    def test_설정_파일의_env에_있는_DISABLE_UPDATES도_건너뛴다(self):
        """사용자 설정 파일이나 관리 설정 파일의 env 블록에 DISABLE_UPDATES가 참이면 환경변수 없이도 건너뛴다."""
        cases = {
            "사용자": {"/home/test/claude-config/settings.json": {"env": {"DISABLE_UPDATES": "1"}}},
            "관리": {"/etc/claude-code/managed-settings.json": {"env": {"DISABLE_UPDATES": "true"}}},
        }
        for name, settings in cases.items():
            with self.subTest(source=name):
                # Given
                fake = FakeClaude()

                # When
                step = claude_update.run_claude_update(
                    fake.system(environ={"CLAUDE_CONFIG_DIR": "/home/test/claude-config"}, settings=settings))

                # Then
                self.assertEqual("updates_disabled", step["reason"])
                self.assertEqual([], fake.calls)

    def test_macOS의_관리_설정_경로도_읽는다(self):
        """macOS에서는 /Library/Application Support/ClaudeCode/managed-settings.json의 env를 읽는다."""
        # Given
        fake = FakeClaude()
        settings = {"/Library/Application Support/ClaudeCode/managed-settings.json": {"env": {"DISABLE_UPDATES": "1"}}}

        # When
        step = claude_update.run_claude_update(fake.system(settings=settings, platform="darwin"))

        # Then
        self.assertEqual("updates_disabled", step["reason"])

    def test_DISABLE_AUTOUPDATER만으로는_건너뛰지_않는다(self):
        """DISABLE_AUTOUPDATER는 백그라운드 확인만 끄므로 환경변수와 설정 파일에 있어도 claude update를 실행한다."""
        # Given
        fake = FakeClaude()
        settings = {"/home/test/claude-config/settings.json": {"env": {"DISABLE_AUTOUPDATER": "1"}}}

        # When
        step = claude_update.run_claude_update(fake.system(
            environ={"DISABLE_AUTOUPDATER": "1", "CLAUDE_CONFIG_DIR": "/home/test/claude-config"}, settings=settings))

        # Then
        self.assertEqual("updated", step["status"])
        self.assertEqual(1, len(fake.calls))

    def test_읽을_수_없거나_형식이_다른_설정_파일은_무시한다(self):
        """설정 파일이 없거나 JSON이 아니거나 env가 객체가 아니거나 값이 거짓이면 건너뛰지 않는다."""
        # Given
        fake = FakeClaude()
        settings = {
            "/home/test/claude-config/settings.json": {"env": ["DISABLE_UPDATES"]},
            "/etc/claude-code/managed-settings.json": {"env": {"DISABLE_UPDATES": "0"}},
        }

        # When
        step = claude_update.run_claude_update(fake.system(environ={"CLAUDE_CONFIG_DIR": "/home/test/claude-config"}, settings=settings))

        # Then
        self.assertEqual("updated", step["status"])

    def test_설정_파일이_깨졌으면_실제_파일_읽기가_None을_돌려준다(self):
        """깨진 JSON이나 없는 파일은 예외 없이 None으로 읽혀 검사에서 무시된다."""
        # Given
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "settings.json"
            broken.write_text("{", encoding="utf-8")
            valid = Path(folder) / "valid.json"
            valid.write_text(json.dumps({"env": {}}), encoding="utf-8")

            # When
            results = [claude_update.read_json(path) for path in (broken, Path(folder) / "missing.json", valid)]

        # Then
        self.assertEqual([None, None, {"env": {}}], results)

    def test_claude가_PATH에_없으면_claude_missing으로_건너뛴다(self):
        """PATH에 claude가 없으면 아무것도 실행하지 않고 claude_missing으로 건너뛴다."""
        # Given
        fake = FakeClaude()

        # When
        step = claude_update.run_claude_update(fake.system(which=None))

        # Then
        self.assertEqual({"status": "skipped", "before": None, "after": None, "reason": "claude_missing"}, step)
        self.assertEqual([], fake.calls)

    def test_0이_아닌_종료_상태는_failed이고_마지막_출력_줄을_담는다(self):
        """종료 상태가 0이 아니면 failed로 보고하고 exit_status와 마지막 출력 한 줄(200자 이하)을 담으며 릴리스는 시도 뒤 값이다."""
        # Given
        fake = FakeClaude(current="2.1.317", returncode=3, output="start\n" + "x" * 300 + "\n")

        # When
        step = claude_update.run_claude_update(fake.system())

        # Then
        self.assertEqual("failed", step["status"])
        self.assertEqual(3, step["exit_status"])
        self.assertEqual("x" * 200, step["detail"])
        self.assertEqual(("2.1.317", "2.1.317"), (step["before"], step["after"]))

    def test_시간_초과와_시작_실패는_종료_상태_없이_failed로_보고한다(self):
        """300초 시간 초과와 실행 시작 실패는 exit_status를 null로 하고 한 줄 설명을 담은 failed로 보고한다."""
        cases = {
            "timeout": (subprocess.TimeoutExpired(["claude", "update"], 300.0), "timed out after 300 seconds"),
            "start": (OSError("denied"), "claude update could not start"),
        }
        for name, (error, detail) in cases.items():
            with self.subTest(case=name):
                # Given
                fake = FakeClaude(error=error)

                # When
                step = claude_update.run_claude_update(fake.system())

                # Then
                self.assertEqual({"status": "failed", "before": "2.1.317", "after": "2.1.317", "exit_status": None, "detail": detail}, step)


def stub_update(order, step):
    def call():
        order.append("claude_update")
        return step

    return call


class RunCommandTest(unittest.TestCase):
    def test_출력에_잘못된_바이트가_있어도_예외_없이_종료_코드와_대체_글자를_돌려준다(self):
        """claude update 출력이 UTF-8로 읽히지 않아도 단계가 멈추지 않고 실패 결과로 남도록 종료 코드와 대체한 출력을 돌려준다."""
        # Given
        argv = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'bad \\xff\\xfe'); sys.exit(3)"]

        # When
        result = claude_update.run_command(argv, 30)

        # Then
        self.assertEqual(3, result.returncode)
        self.assertIn("bad", result.stdout)
        self.assertIn("\ufffd", result.stdout)


class CommandWiringTest(unittest.TestCase):
    PLUGIN_RESULT = {"before_version": "1.0.0", "after_version": "1.1.0", "root": "/c/1.1.0", "digest": "d", "warnings": []}
    FAILED = {"status": "failed", "before": "2.1.317", "after": "2.1.317", "exit_status": 3, "detail": "network down"}

    def command_update(self, step, plugin_result=None):
        order = []

        def host(name, context=None):
            order.append(f"host:{name}")
            if isinstance(plugin_result, Exception):
                raise plugin_result
            return dict(plugin_result or self.PLUGIN_RESULT)

        with (
            patch.object(refresh, "run_claude_update", side_effect=stub_update(order, step)),
            patch.object(refresh, "update_host", side_effect=host),
            patch.object(refresh.installs, "install_gate", return_value=None),
            patch.object(refresh, "prepare_marketplaces", side_effect=lambda ids, context, **kwargs: context.update(release_pins={}, release_errors={})),
            patch.object(refresh, "save_json"),
        ):
            return refresh.command_update(), order

    def command_apply_installed(self, step):
        order = []
        current = {"version": "1.0.0", "root": "/c/1.0.0"}

        def validate(host, installed):
            order.append(f"host:{host}")
            return {"digest": "d"}

        with (
            patch.object(refresh, "run_claude_update", side_effect=stub_update(order, step)),
            patch.object(refresh.installs, "installed", return_value=current),
            patch.object(refresh, "validate_install", side_effect=validate),
            patch.object(refresh, "save_json"),
        ):
            return refresh.command_apply_installed(), order

    def test_update는_호스트_반복_전에_한_번만_실행하고_결과를_claude_code에_담는다(self):
        """update 명령은 호스트 반복 전에 claude update 단계를 정확히 한 번 실행하고 hosts.claude.claude_code에 담는다."""
        # Given
        step = {"status": "updated", "before": "2.1.317", "after": "2.1.318"}

        # When
        result, order = self.command_update(step)

        # Then
        self.assertEqual(["claude_update", "host:claude", "host:codex"], order)
        self.assertEqual(step, result["hosts"]["claude"]["claude_code"])
        self.assertNotIn("claude_code", result["hosts"]["codex"])
        self.assertTrue(result["ok"])

    def test_apply_installed도_호스트_반복_전에_한_번만_실행한다(self):
        """apply-installed 명령도 호스트 반복 전에 claude update 단계를 정확히 한 번 실행하고 결과를 claude_code에 담는다."""
        # Given
        step = {"status": "current", "before": "2.1.318", "after": "2.1.318"}

        # When
        result, order = self.command_apply_installed(step)

        # Then
        self.assertEqual(["claude_update", "host:claude", "host:codex"], order)
        self.assertEqual(step, result["hosts"]["claude"]["claude_code"])
        self.assertTrue(result["ok"])

    def test_건너뛴_단계는_사유와_함께_보고하고_경고를_만들지_않는다(self):
        """건너뛴 단계는 reason과 함께 보고하고 호스트 경고를 늘리지 않는다."""
        # Given
        step = {"status": "skipped", "before": None, "after": None, "reason": "updates_disabled"}

        # When
        result, _ = self.command_update(step)

        # Then
        self.assertEqual(step, result["hosts"]["claude"]["claude_code"])
        self.assertEqual([], result["hosts"]["claude"]["warnings"])

    def test_실패한_단계는_경고만_더하고_플러그인_결과와_ok를_바꾸지_않는다(self):
        """claude update가 실패해도 경고 claude_update_failed만 더하고 플러그인 결과, ok, 호스트 필드는 단계가 없을 때와 같다."""
        # Given
        skipped = {"status": "skipped", "before": None, "after": None, "reason": "claude_missing"}
        baseline, _ = self.command_update(skipped)

        # When
        result, _ = self.command_update(self.FAILED)

        # Then
        claude = result["hosts"]["claude"]
        self.assertEqual(self.FAILED, claude["claude_code"])
        self.assertEqual("claude_update_failed", claude["warnings"][-1]["code"])
        self.assertIn("exit status 3", claude["warnings"][-1]["message"])
        self.assertEqual(baseline["ok"], result["ok"])
        self.assertEqual(baseline["hosts"]["codex"], result["hosts"]["codex"])
        self.assertEqual({key: value for key, value in baseline["hosts"]["claude"].items() if key not in ("claude_code", "warnings")},
                         {key: value for key, value in claude.items() if key not in ("claude_code", "warnings")})

    def test_실패한_단계는_호스트_오류가_있어도_경고_목록을_만들어_붙인다(self):
        """플러그인 업데이트가 오류로 끝나 경고 목록이 없어도 claude_code와 경고를 붙이고 오류와 ok는 그대로 둔다."""
        # Given
        failure = refresh.RefreshError("command_failed", "plugin update failed")

        # When
        result, _ = self.command_update(self.FAILED, plugin_result=failure)

        # Then
        claude = result["hosts"]["claude"]
        self.assertFalse(result["ok"])
        self.assertEqual("command_failed", claude["error"]["code"])
        self.assertEqual(self.FAILED, claude["claude_code"])
        self.assertEqual(["claude_update_failed"], [warning["code"] for warning in claude["warnings"]])

    def test_apply_installed는_실패한_단계에도_호스트를_돌려준다(self):
        """claude update가 실패해도 apply-installed는 설치본을 읽은 호스트와 digest를 그대로 돌려주고 ok를 유지한다."""
        # Given / When
        result, _ = self.command_apply_installed(self.FAILED)

        # Then
        claude = result["hosts"]["claude"]
        self.assertTrue(result["ok"])
        self.assertEqual("d", claude["digest"])
        self.assertEqual("1.0.0", claude["after_version"])
        self.assertEqual(["claude_update_failed"], [warning["code"] for warning in claude["warnings"]])


if __name__ == "__main__":
    unittest.main()
