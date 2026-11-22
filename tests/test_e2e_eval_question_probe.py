"""Tests for the probe of whether a Codex PreToolUse hook receives request_user_input."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import cli, question_probe, question_probe_evidence as evidence  # noqa: E402

HOOK_SCRIPT = REPO_ROOT / "evals/e2e/harness/question_probe_hook.py"
SENTINEL = question_probe.SENTINEL

FAKE_CODEX = """#!{python}
import json, os, re, subprocess, sys
home = os.environ["CODEX_HOME"]
if os.path.isfile(os.path.join(home, "hooks.json")) and os.environ.get("FAKE_DELIVER") != "no-hooks":
    config = json.load(open(os.path.join(home, "hooks.json")))
    event = {{"hook_event_name": "PreToolUse", "tool_name": os.environ["FAKE_TOOL"], "tool_input": {{"questions": []}}}}
    reason = ""
    for entry in config["hooks"]["PreToolUse"]:
        if entry["matcher"] == "*" or re.search(entry["matcher"], event["tool_name"]):
            done = subprocess.run(entry["hooks"][0]["command"], shell=True, input=json.dumps(event), capture_output=True, text=True)
            reason += done.stdout
else:
    reason = ""
rows = [{{"type": "response_item", "payload": {{"type": "function_call", "name": "request_user_input", "call_id": "c1",
                                                  "arguments": "{{}}"}}}},
        {{"type": "response_item", "payload": {{"type": "function_call_output", "call_id": "c1", "output": reason or "answered"}}}}]
day = os.path.join(home, "sessions", "2026", "11", "17")
os.makedirs(day, exist_ok=True)
open(os.path.join(day, "rollout-main.jsonl"), "w").write("".join(json.dumps(row) + "\\n" for row in rows))
print(json.dumps({{"argv": sys.argv[1:], "stdin_closed": sys.stdin.read() == ""}}))
"""


def call_rows(name: str = "request_user_input", output: str = "answered") -> list[dict]:
    return [
        {"type": "response_item", "payload": {"type": "function_call", "name": name, "call_id": "c1", "arguments": "{}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": output}},
    ]


def hook_line(label: str, tool: str) -> dict:
    return {"label": label, "at": 1.0, "event": {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"questions": []}}}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class VerdictFromFixturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.trial = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.trial, ignore_errors=True))

    def evidence(self, rollout: list[dict], log: list[dict]) -> dict:
        write_jsonl(self.trial / "codex-home/sessions/2026/11/17/rollout-a.jsonl", rollout)
        write_jsonl(self.trial / "hook-log.jsonl", log)
        return evidence.collect_evidence(self.trial, "hook-log.jsonl", self.trial / "codex-home/sessions", SENTINEL)

    def test_훅이_호출을_받고_거부가_롤아웃에_보이면_delivered_and_denied다(self) -> None:
        # given: the guard hook logged request_user_input and the tool output carries the sentinel reason
        rollout, log = call_rows(output=f"hook denied: {SENTINEL}"), [hook_line("guard", "request_user_input")]
        # when
        found = self.evidence(rollout, log)
        # then
        self.assertEqual(found["verdict"], evidence.DELIVERED_DENIED)
        self.assertEqual(found["received_tool_input_keys"], ["questions"])
        self.assertEqual(found["question_calls"], 1)

    def test_훅이_로그에_있으나_거부가_보이지_않으면_delivered다(self) -> None:
        found = self.evidence(call_rows(output="answered"), [hook_line("guard", "request_user_input")])
        self.assertEqual(found["verdict"], evidence.DELIVERED)

    def test_다른_도구는_훅이_받고_질문_도구는_못_받으면_not_delivered다(self) -> None:
        # regression: a control hook that saw other tools must not be read as "hooks inactive"
        found = self.evidence(call_rows(), [hook_line("control", "exec_command")])
        self.assertEqual(found["verdict"], evidence.NOT_DELIVERED)
        self.assertEqual(found["control_tool_names"], ["exec_command"])

    def test_훅_로그가_비어_있으면_hooks_inactive라서_결론을_내지_않는다(self) -> None:
        found = self.evidence(call_rows(), [])
        self.assertEqual(found["verdict"], evidence.HOOKS_INACTIVE)
        self.assertNotIn(found["verdict"], evidence.CONCLUSIVE)

    def test_질문_도구를_부르지_않았으면_not_called다(self) -> None:
        found = self.evidence(call_rows(name="exec_command"), [hook_line("control", "exec_command")])
        self.assertEqual(found["verdict"], evidence.NOT_CALLED)

    def test_롤아웃의_훅_관련_이벤트_이름을_모은다(self) -> None:
        rows = [*call_rows(), {"type": "event_msg", "payload": {"type": "hook_completed"}}]
        self.assertEqual(self.evidence(rows, [])["rollout_hook_events"], ["hook_completed"])


class ProbeHookScriptTest(unittest.TestCase):
    def run_hook(self, *args: str, stdin: str) -> tuple[str, list[dict]]:
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "log.jsonl"
            done = subprocess.run([sys.executable, str(HOOK_SCRIPT), str(log), *args], input=stdin, capture_output=True,
                                  text=True, check=True)
            return done.stdout, evidence.hook_entries(log)

    def test_deny_옵션이_있으면_로그를_쓰고_거부_결정을_출력한다(self) -> None:
        out, entries = self.run_hook("guard", "--deny", "NOPE", stdin='{"tool_name": "request_user_input"}')
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((decision["permissionDecision"], decision["permissionDecisionReason"]), ("deny", "NOPE"))
        self.assertEqual((entries[0]["label"], entries[0]["event"]["tool_name"]), ("guard", "request_user_input"))

    def test_deny_옵션이_없으면_로그만_쓰고_아무것도_출력하지_않는다(self) -> None:
        out, entries = self.run_hook("control", stdin='{"tool_name": "exec_command"}')
        self.assertEqual(out, "")
        self.assertEqual(len(entries), 1)


class DryRunAndRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def fake_codex(self) -> Path:
        path = self.root / "fake-codex"
        path.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def auth_home(self) -> Path:
        home = self.root / "auth"
        home.mkdir()
        (home / "auth.json").write_text("SENTINEL-NEVER-READ", encoding="utf-8")
        return home

    def run_probe(self, tool: str, deliver: str = "yes") -> tuple[int, str, Path]:
        trial = self.root / f"trial-{tool}-{deliver}"
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"FAKE_TOOL": tool, "FAKE_DELIVER": deliver}):
            code = question_probe.probe(trial, str(self.fake_codex()), "demo-model", "low", 60.0, False, out,
                                        source_home=self.auth_home())
        return code, out.getvalue(), trial

    def test_dry_run은_명령을_출력하고_폴더도_프로세스도_만들지_않는다(self) -> None:
        # given: a trial folder that does not exist and a subprocess that would fail the test
        trial, out = self.root / "never", io.StringIO()
        # when
        with mock.patch("subprocess.run", side_effect=AssertionError("started a process")):
            code = question_probe.probe(trial, "codex", "demo-model", "low", 60.0, True, out)
        # then
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertFalse(trial.exists())
        for expected in ("codex exec --json -m demo-model", "request_user_input", "hooks.json", "--deny", "CODEX_HOME="):
            self.assertIn(expected, text)

    def test_cli_dry_run은_같은_계획을_출력한다(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["probe-question-hook", "--dry-run", "--dir", str(self.root / "t")])
        self.assertEqual(code, 0)
        self.assertIn("dry run: nothing is started", out.getvalue())
        self.assertFalse((self.root / "t").exists())

    def test_격리된_홈에_훅과_인증_링크를_두고_세션_증거로_delivered_and_denied를_낸다(self) -> None:
        code, out, trial = self.run_probe("request_user_input")
        found = json.loads((trial / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual((code, found["verdict"]), (0, evidence.DELIVERED_DENIED))
        self.assertTrue((trial / "codex-home/auth.json").is_symlink())
        self.assertNotIn("SENTINEL-NEVER-READ", out)
        self.assertEqual(found["argv"][1:3], ["exec", "--json"])

    def test_훅이_질문_도구를_받지_못하는_세션은_not_delivered로_끝난다(self) -> None:
        code, _, trial = self.run_probe("exec_command")
        found = json.loads((trial / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(found["verdict"], evidence.NOT_DELIVERED)
        self.assertEqual(code, 0)

    def test_결론이_없는_결과는_종료_코드_3이다(self) -> None:
        code, _, trial = self.run_probe("request_user_input", deliver="no-hooks")
        self.assertEqual(code, question_probe.INCONCLUSIVE_EXIT)

    def test_비어_있지_않은_폴더는_거부한다(self) -> None:
        trial = self.root / "used"
        trial.mkdir()
        (trial / "x").write_text("1", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            code = question_probe.probe(trial, "codex", "m", "low", 1.0, False, io.StringIO(), source_home=self.auth_home())
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
