"""Tests for the comparison record, its decision rule, the pin consistency check, the host evidence, and the commands."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROLES = REPO_ROOT / "evals" / "model-roles"
sys.path.insert(0, str(MODEL_ROLES))

import mr_cases  # noqa: E402
import mr_cli  # noqa: E402
import mr_evidence  # noqa: E402
import mr_pins  # noqa: E402
import mr_record as rec  # noqa: E402

ROLES = mr_cases.roles_by_case(mr_cases.load_cases())
OPUS_HIGH, OPUS_XHIGH, FABLE_HIGH, FABLE_XHIGH = rec.CANDIDATES
REGISTRY = json.loads((REPO_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))


def outcome(passed: dict, cost: dict | None = None) -> list[dict]:
    """Results for every case and candidate: passed maps (candidate index, case) to a bool, cost maps candidate index to a case cost."""
    results = []
    for index, (model, effort) in enumerate(rec.CANDIDATES):
        for case in ROLES:
            results.append({
                "case": case, "model": model, "effort": effort, "passed": passed.get((index, case), False),
                "host_model": model, "host_effort": effort, "cost_usd": (cost or {}).get(index, 1.0),
                "wall_seconds": 30.0, "attempts": 1,
            })
    return results


def record_of(passed: dict, cost: dict | None = None) -> dict:
    return rec.build_record(84, ROLES, outcome(passed, cost))


def wins(index: int, *cases: str) -> dict:
    return {(index, case): True for case in cases}


class DecisionRuleTest(unittest.TestCase):
    def decisions(self, passed: dict, cost: dict | None = None) -> dict:
        return rec.decisions(record_of(passed, cost))

    def test_역할은_자기_사례의_통과_수가_가장_많은_후보를_고른다(self):
        """검토 사례에서 Opus xhigh만 셋을 통과하면 비싸도 reviewer 승자이고, 토론 사례는 따로 센다."""
        # Given
        passed = {**wins(1, "T89", "T90", "T91"), **wins(0, "T89", "T90"), **wins(2, "T92", "T93")}
        cost = {0: 0.5, 1: 9.0, 2: 3.0, 3: 1.0}

        # When
        decided = self.decisions(passed, cost)

        # Then
        self.assertEqual({"status": "winner", "winner": {"model": rec.OPUS, "effort": "xhigh"}}, decided["reviewer"])
        self.assertEqual({"status": "winner", "winner": {"model": rec.FABLE, "effort": "high"}}, decided["opponent"])

    def test_통과_수가_같으면_그_사례들의_비용이_가장_낮은_후보를_고른다(self):
        """네 후보가 같은 수를 통과하면 역할 사례의 비용 합이 가장 낮은 후보가 이기고 다른 역할의 비용은 세지 않는다."""
        # Given
        passed = {(index, case): True for index in range(4) for case in ROLES}
        cost = {0: 4.0, 1: 3.0, 2: 2.0, 3: 5.0}

        # When
        decided = self.decisions(passed, cost)

        # Then
        self.assertEqual(rec.FABLE, decided["reviewer"]["winner"]["model"])
        self.assertEqual("high", decided["reviewer"]["winner"]["effort"])
        self.assertEqual(
            round(2.0 * 3, 6),
            next(item for item in record_of(passed, cost)["roles"]["reviewer"]["candidates"] if item["model"] == rec.FABLE and item["effort"] == "high")["cost_usd"],
        )

    def test_통과_수가_적은_후보는_싸도_지지_않을_수_없다(self):
        """가장 싼 후보가 통과를 하나 덜 하면 더 많이 통과한 비싼 후보가 이긴다."""
        # Given
        passed = {**wins(0, "T89", "T90"), **wins(2, "T89", "T90", "T91")}
        cost = {0: 0.1, 1: 5.0, 2: 8.0, 3: 5.0}

        # When
        decided = self.decisions(passed, cost)

        # Then
        self.assertEqual({"model": rec.FABLE, "effort": "high"}, decided["reviewer"]["winner"])

    def test_통과_수와_비용이_모두_같으면_승자를_정하지_않는다(self):
        """모든 후보가 같은 수를 통과하고 비용도 같으면 tie이고 승자가 없다."""
        # When
        decided = self.decisions({})

        # Then
        self.assertEqual({"status": "tie", "winner": None}, decided["reviewer"])
        self.assertEqual({"status": "tie", "winner": None}, decided["opponent"])

    def test_Opus가_이기면_그_역할은_Opus_모델을_고른다(self):
        """토론 사례에서 Opus high가 가장 싸게 같은 수를 통과하면 opponent 승자는 Opus이다."""
        # Given
        passed = {(index, case): True for index in range(4) for case in ("T92", "T93")}
        cost = {0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0}

        # When
        decided = self.decisions(passed, cost)

        # Then
        self.assertEqual({"model": rec.OPUS, "effort": "high"}, decided["opponent"]["winner"])


class RecordFormatTest(unittest.TestCase):
    def problems(self, record: dict) -> list[str]:
        return rec.record_problems(record, ROLES)

    def test_다섯_사례_네_후보의_스무_결과가_갖춰진_기록은_문제가_없다(self):
        """스무 개 결과가 모두 있고 계산된 roles가 맞는 기록은 문제가 없다."""
        # When
        problems = self.problems(record_of(wins(3, "T89")))

        # Then
        self.assertEqual([], problems)

    def test_결과가_하나라도_빠지거나_겹치면_기록이_성립하지_않는다(self):
        """사례 하나가 빠지거나 같은 결과가 둘이면 사례와 후보마다 결과 하나라는 문제를 돌려준다."""
        # Given
        full = record_of({})
        missing = {**full, "results": full["results"][1:]}
        doubled = {**full, "results": full["results"][1:] + [full["results"][1]]}

        # When
        found = [self.problems(missing), self.problems(doubled)]

        # Then
        self.assertEqual([["a recorded comparison holds exactly one result per case and candidate"]] * 2, found)

    def test_호스트_기록의_모델이나_강도가_후보와_다르면_거부한다(self):
        """host_model이나 host_effort가 후보와 다르거나 비용과 시간이 음수이면 그 결과를 거부한다."""
        # Given
        for key, value, text in (
            ("host_model", "claude-sonnet-5-5", "host record shows model"), ("host_effort", "medium", "host record shows effort"),
            ("cost_usd", -1, "cost_usd"), ("wall_seconds", None, "wall_seconds"), ("attempts", 0, "attempts"),
        ):
            with self.subTest(key=key):
                record = record_of({})
                record["results"][0][key] = value

                # When
                problems = self.problems(record)

                # Then
                self.assertEqual(1, len(problems), problems)
                self.assertIn(text, problems[0])

    def test_계산된_roles를_고쳐_쓰면_거부한다(self):
        """승자나 통과 수나 비용을 손으로 바꾼 roles는 규칙을 결과에 적용한 값과 다르다고 거부된다."""
        for edit in (
            lambda record: record["roles"]["reviewer"]["decision"].update(winner={"model": rec.OPUS, "effort": "high"}),
            lambda record: record["roles"]["opponent"]["candidates"][0].update(passes=2),
            lambda record: record["roles"]["reviewer"]["candidates"][1].update(cost_usd=0.5),
        ):
            with self.subTest():
                record = record_of({})
                edit(record)

                # When
                problems = self.problems(record)

                # Then
                self.assertEqual(["roles do not match the rule applied to the results"], problems)

    def test_대기_기록은_결과도_roles도_담지_않는다(self):
        """pending 기록은 결과와 roles가 비어 있어야 하고, 결과가 있으면 거부한다."""
        # Given
        pending = rec.pending_record(84, ROLES)
        filled = {**pending, "results": outcome({})}

        # When / Then
        self.assertEqual([], self.problems(pending))
        self.assertEqual(["a pending record holds no results and no roles"], self.problems(filled))

    def test_저장소의_기록은_형식을_지킨다(self):
        """저장소의 record.json은 형식 검사를 통과한다."""
        # Given
        stored = json.loads((MODEL_ROLES / "record.json").read_text(encoding="utf-8"))

        # When
        problems = self.problems(stored)

        # Then
        self.assertEqual([], problems)


PIN_LINES = {
    "instructions/independent-model-validation.md": ("| GPT |", "| GPT | `{model}` | `{effort}` |"),
    "AGENTS.md": ("| GPT-authored", "  | GPT-authored, including work drafted on `gpt-6.1-sol` | `role_runner.py reviewer --model {model} --effort {effort}` |"),
    "skills/tiki-taka/SKILL.md": ("- Fix a Claude opponent", "- Fix a Claude opponent to `{model}` with `{effort}` reasoning effort."),
    "docs/ko/skills/tiki-taka/SKILL.ko.md": ("- Claude 상대는", "- Claude 상대는 {model}, 사고 강도 {effort}로 고정하라."),
}


def transformed(read, winner_model: str, effort: str):
    """Return a file reader that shows the pins after a decision: every Claude pin of the comparison names the winner and its effort."""
    other = rec.OPUS if winner_model == rec.FABLE else rec.FABLE

    def reader(path: str) -> str:
        lines = []
        for line in read(path).replace(other, winner_model).splitlines():
            start, template = PIN_LINES.get(path, (None, None))
            lines.append(template.format(model=winner_model, effort=effort) if start and line.lstrip().startswith(start) else line)
        return "\n".join(lines) + "\n"

    return reader


def real_reader(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


class PinConsistencyTest(unittest.TestCase):
    def test_기록이_대기_중이면_저장소의_핀은_기준_그대로이다(self):
        """pending 기록에서는 레지스트리와 규칙 문서가 모두 현재 핀(Fable xhigh 상대, Opus와 Fable 검토자)이고 문제가 없다."""
        # When
        problems = mr_pins.pin_problems(rec.pending_record(84, ROLES), REGISTRY, real_reader)

        # Then
        self.assertEqual([], problems)

    def test_기록이_없는데_핀이_바뀌면_문제로_잡는다(self):
        """pending 기록에서 상대 모델을 Opus로 바꾸거나 검토자 문서에서 Fable을 빼면 각각 문제가 된다."""
        # Given
        registry = copy.deepcopy(REGISTRY)
        registry["opponents"]["claude"]["model"] = rec.OPUS
        fewer = lambda path: real_reader(path).replace(rec.FABLE, rec.OPUS) if path == "instructions/independent-model-validation.md" else real_reader(path)

        # When
        pending = rec.pending_record(84, ROLES)
        registry_problems = mr_pins.pin_problems(pending, registry, real_reader)
        text_problems = mr_pins.pin_problems(pending, REGISTRY, fewer)

        # Then
        self.assertEqual(["registry opponents.claude.model is 'claude-opus-5-5', expected 'claude-fable-5-2'"], registry_problems)
        self.assertEqual(
            ["instructions/independent-model-validation.md: the pin site names ['claude-opus-5-5'], "
             "expected ['claude-fable-5-2', 'claude-opus-5-5']"] * 2,
            text_problems,
        )

    def test_승자가_정해진_기록이면_모든_핀_위치가_승자만_이름해야_한다(self):
        """Opus가 두 역할을 이긴 기록에서는 현재 저장소가 문제를 돌려주고, 핀을 승자로 바꾼 저장소는 문제가 없다."""
        # Given
        passed = {**wins(0, "T89", "T90", "T91", "T92", "T93")}
        record = record_of(passed, {0: 0.5, 1: 1.0, 2: 1.0, 3: 1.0})
        registry = copy.deepcopy(REGISTRY)
        registry["opponents"]["claude"]["model"] = rec.OPUS
        registry["opponents"]["effort"] = "high"
        registry["runner"]["independent_review"]["gpt"] = [rec.OPUS]

        # When
        before = mr_pins.pin_problems(record, REGISTRY, real_reader)
        after = mr_pins.pin_problems(record, registry, transformed(real_reader, rec.OPUS, "high"))

        # Then
        self.assertGreaterEqual(len(before), 4)
        self.assertEqual([], after)

    def test_효과_강도는_승자의_것만_남아야_한다(self):
        """Opus xhigh가 이긴 기록에서 검토 표 행이 high도 함께 적고 있으면 강도 문제가 된다."""
        # Given
        passed = wins(1, "T89", "T90", "T91")
        record = record_of(passed, {0: 1.0, 1: 0.5, 2: 1.0, 3: 1.0})
        registry = copy.deepcopy(REGISTRY)
        registry["runner"]["independent_review"]["gpt"] = [rec.OPUS]
        swapped = transformed(real_reader, rec.OPUS, "xhigh")
        mixed = lambda path: swapped(path).replace("| GPT | `claude-opus-5-5` | `xhigh` |", "| GPT | `claude-opus-5-5` | `high` or `xhigh` |")

        # When
        problems = [item for item in mr_pins.pin_problems(record, registry, mixed) if "effort" in item]

        # Then
        self.assertEqual(1, len(problems), problems)
        self.assertIn("instructions/independent-model-validation.md", problems[0])

    def test_동률인_역할은_기준_핀을_유지한다(self):
        """모든 후보가 비긴 기록에서는 기준 핀이 문제없고, 상대 모델이 바뀌어 있으면 문제가 된다."""
        # Given
        record = record_of({})
        registry = copy.deepcopy(REGISTRY)
        registry["opponents"]["claude"]["model"] = rec.OPUS

        # When
        unchanged = mr_pins.pin_problems(record, REGISTRY, real_reader)
        changed = mr_pins.pin_problems(record, registry, real_reader)

        # Then
        self.assertEqual([], unchanged)
        self.assertEqual(["registry opponents.claude.model is 'claude-opus-5-5', expected 'claude-fable-5-2'"], changed)

    def test_규칙_문서의_문구가_바뀌어_위치를_못_찾으면_알린다(self):
        """핀 위치의 앵커 문구를 찾지 못하면 어디를 고쳐야 하는지 알리는 문제를 돌려준다."""
        # Given
        broken = lambda path: real_reader(path).replace("Fix a Claude opponent to", "Use a Claude opponent of")

        # When
        problems = mr_pins.pin_problems(rec.pending_record(84, ROLES), REGISTRY, broken)

        # Then
        self.assertTrue(any("skills/tiki-taka/SKILL.md: no line matches" in item for item in problems), problems)


def write_transcript(home: Path, session: str, entries: list[dict]) -> None:
    folder = home / "projects" / "-tmp-work"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{session}.jsonl").write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")


def assistant(model: str, effort: str, stamp: str, message_id: str, usage: dict) -> dict:
    return {"type": "assistant", "effort": effort, "timestamp": stamp,
            "message": {"id": message_id, "model": model, "usage": usage}}


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def test_기록의_모델_강도와_표_가격으로_계산한_비용과_걸린_시간을_돌려준다(self):
        """Opus 응답 둘의 토큰을 표 가격으로 계산한 비용과 첫 기록부터 마지막 기록까지의 초를 돌려준다."""
        # Given
        usage = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 10000}
        write_transcript(self.home, "s1", [
            {"type": "user", "timestamp": "2026-01-01T00:00:00Z"},
            assistant(rec.OPUS, "xhigh", "2026-01-01T00:00:10Z", "m1", usage),
            assistant(rec.OPUS, "xhigh", "2026-01-01T00:01:30Z", "m2", usage),
            assistant(rec.OPUS, "xhigh", "2026-01-01T00:01:30Z", "m2", usage),
        ])

        # When
        found = mr_evidence.run_evidence("s1", self.home)

        # Then
        per_request = (1000 * 4.0 + 500 * 20.0 + 10000 * 0.20) / 1_000_000
        self.assertEqual(
            {"session": "s1", "host_model": rec.OPUS, "host_effort": "xhigh", "cost_usd": round(2 * per_request, 6),
             "wall_seconds": 90.0, "answers": 3},
            found,
        )

    def test_합성_응답은_모델_증거가_아니고_섞인_모델과_강도는_그대로_드러난다(self):
        """<synthetic> 응답은 세지 않고, 한 기록에 두 모델이나 두 강도가 있으면 host 값에 둘 다 나타난다."""
        # Given
        usage = {"input_tokens": 100, "output_tokens": 100}
        write_transcript(self.home, "s2", [
            assistant("<synthetic>", "high", "2026-01-01T00:00:00Z", "x", usage),
            assistant(rec.OPUS, "high", "2026-01-01T00:00:01Z", "a", usage),
            assistant(rec.FABLE, "xhigh", "2026-01-01T00:00:02Z", "b", usage),
        ])

        # When
        found = mr_evidence.run_evidence("s2", self.home)

        # Then
        self.assertEqual(f"{rec.FABLE}|{rec.OPUS}", found["host_model"])
        self.assertEqual("high|xhigh", found["host_effort"])
        self.assertEqual(2, found["answers"])

    def test_기록이_없거나_가격이_없는_모델이면_오류이다(self):
        """없는 세션, 응답이 없는 기록, 가격표에 없는 모델은 EvidenceError이다."""
        # Given
        write_transcript(self.home, "empty", [{"type": "user", "timestamp": "2026-01-01T00:00:00Z"}])
        write_transcript(self.home, "odd", [assistant("claude-unknown-1", "high", "2026-01-01T00:00:00Z", "a", {"input_tokens": 1})])

        # When / Then
        for session in ("missing", "empty", "odd", "../x"):
            with self.subTest(session=session), self.assertRaises(mr_evidence.EvidenceError):
                mr_evidence.run_evidence(session, self.home)

    def test_상태_줄은_성공하고_검증된_Claude_실행만_세션을_준다(self):
        """exit 0, verified, claude 실행의 마지막 상태 줄만 세션을 주고 실패, 미검증, Codex 실행은 거부한다."""
        # Given
        ok = {"runner": "claude", "model": rec.OPUS, "effort": "high", "verified": True, "exit": 0, "evidence": {"session": "s9"}}

        # When
        accepted = mr_evidence.status_session("role_runner: note\n" + json.dumps(ok))

        # Then
        self.assertEqual({"session": "s9", "model": rec.OPUS, "effort": "high"}, accepted)
        for change in ({"exit": 4}, {"verified": False}, {"runner": "codex"}, {"evidence": {}}):
            with self.subTest(change=change), self.assertRaises(mr_evidence.EvidenceError):
                mr_evidence.status_session(json.dumps({**ok, **change}))
        with self.assertRaises(mr_evidence.EvidenceError):
            mr_evidence.status_session("no json here")

    def test_상대_상태_폴더에서_세션_모델_강도를_읽는다(self):
        """상태 폴더의 session-id, active-model, active-effort를 읽고 하나라도 없으면 오류이다."""
        # Given
        for name, value in (("session-id", "s7"), ("active-model", rec.FABLE), ("active-effort", "xhigh")):
            (self.home / name).write_text(value + "\n", encoding="utf-8")

        # When
        found = mr_evidence.state_session(self.home)
        (self.home / "active-effort").unlink()

        # Then
        self.assertEqual({"session": "s7", "model": rec.FABLE, "effort": "xhigh"}, found)
        with self.assertRaises(mr_evidence.EvidenceError):
            mr_evidence.state_session(self.home)


class CommandTest(unittest.TestCase):
    def test_후보의_모델과_강도가_기록과_다르면_결과를_쓰지_않는다(self):
        """실행 기록이 Opus high인데 Fable xhigh 후보로 결과를 만들면 오류로 멈추고 결과 파일이 없다."""
        with tempfile.TemporaryDirectory() as temp:
            # Given
            base = Path(temp)
            status = {"runner": "claude", "model": rec.OPUS, "effort": "high", "verified": True, "exit": 0, "evidence": {"session": "s1"}}
            (base / "status.json").write_text(json.dumps(status), encoding="utf-8")
            (base / "answer.md").write_text("x", encoding="utf-8")
            argv = ["mr_cli.py", "result", "T89", "--candidate", f"{rec.FABLE}/xhigh", "--answer", str(base / "answer.md"),
                    "--status-line", str(base / "status.json"), "--out", str(base / "out.json")]

            # When
            with patch.object(sys, "argv", argv):
                code = mr_cli.main()

            # Then
            self.assertEqual(2, code)
            self.assertFalse((base / "out.json").exists())

    def test_결과_항목은_채점과_호스트_기록과_이전_시도_합계로_만든다(self):
        """통과한 채점, 호스트 기록, 이전 시도의 비용과 시간을 더해 결과 항목 하나를 만든다."""
        # Given
        grade = {"pass": True}
        evidence = {"host_model": rec.OPUS, "host_effort": "high", "cost_usd": 0.25, "wall_seconds": 40.0}

        # When
        entry = mr_cli.result_entry("T90", (rec.OPUS, "high"), grade, evidence, 2, 0.1, 5.0)

        # Then
        self.assertEqual(
            {"case": "T90", "model": rec.OPUS, "effort": "high", "passed": True, "host_model": rec.OPUS, "host_effort": "high",
             "cost_usd": 0.35, "wall_seconds": 45.0, "attempts": 2},
            entry,
        )

    def test_build는_결과_스무_개로_기록을_쓰고_모자라면_쓰지_않는다(self):
        """결과 파일 스무 개로 record를 쓰고, 하나 모자라면 문제를 출력하고 파일을 만들지 않는다."""
        with tempfile.TemporaryDirectory() as temp:
            # Given
            base = Path(temp)
            files = []
            for index, item in enumerate(outcome(wins(3, "T89"))):
                path = base / f"r{index}.json"
                path.write_text(json.dumps(item), encoding="utf-8")
                files.append(str(path))

            # When
            with patch.object(sys, "argv", ["mr_cli.py", "build", "--results", *files, "--out", str(base / "ok.json")]):
                complete = mr_cli.main()
            with patch.object(sys, "argv", ["mr_cli.py", "build", "--results", *files[1:], "--out", str(base / "bad.json")]):
                short = mr_cli.main()

            # Then
            self.assertEqual((0, 1), (complete, short))
            self.assertEqual("recorded", json.loads((base / "ok.json").read_text(encoding="utf-8"))["status"])
            self.assertFalse((base / "bad.json").exists())

    def test_상대_실행기_사본은_후보의_모델과_강도를_실행기_설정으로_보여준다(self):
        """사본의 실행기는 모델만 바꾸고, --fast가 없으면 xhigh, 있으면 high를 설정으로 보여준다. 사본은 저장소를 건드리지 않는다."""
        with tempfile.TemporaryDirectory() as temp:
            # Given
            out = Path(temp) / "plugin"
            before = real_reader("config/model-registry.json")
            with patch.object(sys, "argv", ["mr_cli.py", "opponent-plugin", "--model", rec.OPUS, "--out", str(out)]):
                code = mr_cli.main()
            script = out / "skills" / "tiki-taka" / "run-opponent.sh"

            # When
            shown = {
                flag: subprocess.run(
                    ["bash", str(script), "--opponent", "claude", "--show-config", *flag],
                    capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                ).stdout.strip()
                for flag in ((), ("--fast",))
            }

            # Then
            self.assertEqual(0, code)
            self.assertEqual({(): f"opponent=claude model={rec.OPUS} effort=xhigh",
                              ("--fast",): f"opponent=claude model={rec.OPUS} effort=high"}, shown)
            self.assertEqual(before, real_reader("config/model-registry.json"))

    def test_저장소의_기록과_핀은_check를_통과한다(self):
        """저장소의 record.json과 핀 위치는 check 명령을 통과한다. 기록이 대기 중이면 핀은 바뀌지 않은 상태여야 한다."""
        # When
        done = subprocess.run([sys.executable, "-B", str(MODEL_ROLES / "mr_cli.py"), "check"], capture_output=True, text=True)

        # Then
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
