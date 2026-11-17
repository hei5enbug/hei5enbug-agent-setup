"""Tests for the requirements agreement measurement: the step each host registers, the candidate that a step builds, the
repository state that a record requires, and the cap exception of the `claude-fable-5-2` step."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import agreement_candidate as candidate  # noqa: E402
from harness import agreement_decision as decision  # noqa: E402
from harness import caps, command, plugin_export, records  # noqa: E402
from harness.agreement_candidate import CandidateError, DiskSource, GitSource  # noqa: E402
from harness.config import CAP_EXCEPTION_MODEL  # noqa: E402

PASS2 = [True, True]
ALL = {case: PASS2 for case in decision.CASES}
ABCD = {case: PASS2 for case in decision.ABCD}
FAIL_A = {**ABCD, "A": [True, False]}
HOSTS = ("claude", "codex")


def steps_of(**per_step: dict[str, dict[str, list[bool]]]) -> dict[str, dict[str, dict[str, list[bool]]]]:
    return per_step


def both(runs: dict[str, list[bool]]) -> dict[str, dict[str, list[bool]]]:
    return {"claude": dict(runs), "codex": dict(runs)}


class DecisionTest(unittest.TestCase):
    def test_1단계가_두_호스트에서_모든_사례를_통과하면_에이전트_없이_1단계를_등록한다(self):
        """step1이 A부터 G까지 두 번씩 통과하면 두 호스트 모두 step1이고 드래프터 에이전트는 없다."""
        # given
        steps = {"step1": both(ALL)}

        # when
        result = decision.decide(steps)

        # then
        self.assertEqual(result["registered"], {"claude": "step1", "codex": "step1"})
        self.assertEqual((result["state"], result["drafters"]), ("adopted", {}))
        self.assertEqual(decision.expected_state({"state": "adopted", "registered": result["registered"]}),
                         {"rules": True, "agent": False, "retired": True})

    def test_한_호스트에서_1단계가_A에서_실패하고_2단계가_통과하면_그_호스트만_opus를_등록한다(self):
        """claude에서 step1이 A를 한 번 실패하고 step2가 A~D를 통과하면 claude만 claude-opus-5-5 xhigh로 등록한다."""
        # given
        steps = {"step1": {"claude": {**ALL, "A": [True, False]}, "codex": ALL}, "step2": {"claude": ABCD}}

        # when
        result = decision.decide(steps)

        # then
        self.assertEqual(result["registered"], {"claude": "step2", "codex": "step1"})
        self.assertEqual(result["drafters"], {"claude": {"model": "claude-opus-5-5", "effort": "xhigh"}})
        self.assertEqual(decision.expected_state({"state": result["state"], "registered": result["registered"]})["agent"], True)

    def test_2단계가_1단계가_실패한_사례만_통과하고_나머지는_돌리지_않았으면_아무것도_등록하지_않는다(self):
        """step2가 A만 두 번 통과하고 B~D를 돌리지 않았으면 그 호스트는 등록 없이 보류된다."""
        # given
        steps = {"step1": {"claude": {**ALL, "A": [False, False]}, "codex": ALL}, "step2": {"claude": {"A": PASS2}}}

        # when
        result = decision.decide(steps)

        # then
        self.assertEqual(result["registered"]["claude"], None)
        self.assertEqual(result["hosts"]["claude"]["status"], "pending")
        self.assertEqual(result["state"], "undecided")

    def test_1단계와_2단계가_실패하고_3단계_high가_통과하면_fable_high를_등록하고_xhigh는_high가_실패할_때만_본다(self):
        """step3-high가 통과하면 fable high, 실패하고 step3-xhigh가 통과하면 fable xhigh, step3-xhigh를 안 돌렸으면 보류다."""
        # given
        failing = {"step1": {"claude": {**ALL, "A": [False, False]}, "codex": ALL}, "step2": {"claude": FAIL_A}}

        # when
        high = decision.decide({**failing, "step3-high": {"claude": ABCD}})
        xhigh = decision.decide({**failing, "step3-high": {"claude": FAIL_A}, "step3-xhigh": {"claude": ABCD}})
        waiting = decision.decide({**failing, "step3-high": {"claude": FAIL_A}})

        # then
        self.assertEqual(high["drafters"]["claude"], {"model": CAP_EXCEPTION_MODEL, "effort": "high"})
        self.assertEqual(xhigh["drafters"]["claude"], {"model": CAP_EXCEPTION_MODEL, "effort": "xhigh"})
        self.assertEqual(waiting["hosts"]["claude"]["status"], "pending")

    def test_E_F_G_중_하나가_실패한_호스트는_단계가_통과해도_등록하지_않고_도입하지_않는다(self):
        """claude에서 case F가 한 번 실패하면 step2가 A~D를 통과해도 등록하지 않고 상태는 도입 안 함이다."""
        # given
        steps = {"step1": {"claude": {**ALL, "F": [True, False]}, "codex": ALL}, "step2": {"claude": ABCD}}

        # when
        result = decision.decide(steps)

        # then
        self.assertEqual(result["hosts"]["claude"]["status"], "no registration")
        self.assertIn("case F", result["hosts"]["claude"]["reason"])
        self.assertEqual(result["state"], "not adopted")

    def test_어느_단계도_통과하지_못하면_등록하지_않고_도입하지_않는다(self):
        """step1부터 step3-xhigh까지 모두 실패한 호스트는 등록이 없고 합의는 도입하지 않는다."""
        # given
        bad = {"A": [False, False], **{case: PASS2 for case in "BCD"}}
        steps = {"step1": {"claude": {**ALL, "A": [False, False]}, "codex": ALL}, "step2": {"claude": bad},
                 "step3-high": {"claude": bad}, "step3-xhigh": {"claude": bad}}

        # when
        result = decision.decide(steps)

        # then
        self.assertEqual(result["registered"]["claude"], None)
        self.assertEqual(result["state"], "not adopted")
        self.assertEqual(decision.expected_state({"state": "not adopted", "registered": result["registered"]}),
                         {"rules": False, "agent": False, "retired": False})

    def test_사례마다_세어진_실행이_둘_미만이면_통과로_세지_않는다(self):
        """B가 한 번만 세어진 step1은 통과가 아니라 보류이고, 다른 단계의 통과가 그 자리를 채우지 못한다."""
        # given
        steps = {"step1": both({**ALL, "B": [True]}), "step2": both(ABCD)}

        # when
        result = decision.decide(steps)

        # then
        self.assertEqual(result["registered"], {"claude": None, "codex": None})
        self.assertEqual(result["state"], "undecided")

    def test_fable_단계의_A_D_통과_조건은_인자로_바꿀_수_있고_E_G_조건은_그대로_적용된다(self):
        """소유자가 정할 조건 함수가 A~D 판정만 바꾸고, E~G가 실패한 호스트는 그 함수가 통과여도 등록하지 않는다."""
        # given
        failing = {"step1": {"claude": {**ALL, "A": [False, False]}, "codex": ALL}, "step2": {"claude": FAIL_A}}
        steps = {**failing, "step3-high": {"claude": {"A": [True]}}}
        lenient = lambda runs: all(any(results) for results in runs.values())  # noqa: E731
        gate_fail = {"step1": {"claude": {**ALL, "G": [False, True]}, "codex": ALL}, "step3-high": {"claude": {"A": [True]}}}

        # when
        by_default = decision.decide(steps)
        by_rule = decision.decide(steps, fable_rule=lenient)
        gated = decision.decide(gate_fail, fable_rule=lenient)

        # then
        self.assertEqual(by_default["registered"]["claude"], None)
        self.assertEqual(by_rule["registered"]["claude"], "step3-high")
        self.assertEqual(gated["hosts"]["claude"]["status"], "no registration")

    def test_기록이_자기_실행이_정하지_않는_등록이나_상태를_적으면_검증이_막는다(self):
        """registered나 state가 실행 결과와 다르거나 드래프터가 단계의 모델이 아니면 검증 문제로 나온다."""
        # given
        steps = {"step1": {"claude": {**ALL, "A": [False, False]}, "codex": ALL}, "step2": {"claude": ABCD}}
        honest = {"steps": steps, "registered": {"claude": "step2", "codex": "step1"}, "state": "adopted",
                  "drafters": {"step2": {"claude": {"model": "claude-opus-5-5", "effort": "not measured"}}}}
        lie = {**honest, "registered": {"claude": "step1", "codex": "step1"}}
        wrong_model = {**honest, "drafters": {"step2": {"claude": {"model": "claude-sonnet-5-5", "effort": "xhigh"}}}}

        # when
        problems = [decision.agreement_problems(item) for item in (honest, lie, wrong_model)]

        # then
        self.assertEqual(problems[0], [])
        self.assertIn("agreement registered", problems[1][0])
        self.assertIn("does not name", problems[2][0])

    def test_기록은_agreement_구역을_받고_드래프터_역할에만_fable_모델을_허용한다(self):
        """record 검증은 agreement 구역을 검사하고, fable 모델은 spec-drafter 역할의 실행에만 허용한다."""
        # given
        def run(role: str, model: str) -> dict[str, Any]:
            return {"case": "T46", "variant": "a", "host": "claude", "models": {role: {"model": model, "effort": "high"}},
                    "checks": {"hidden-tests": True}, "wall_seconds": 1.0, "cost_usd": 1.0}

        record = {"issue": 96, "cases": ["T46"], "variants": {"a": {"revision": "abc1234"}}, "runs": [run("subagent:x:spec-drafter", CAP_EXCEPTION_MODEL)],
                  "verdicts": [{"case": "T46", "verdict": "pass", "step": "ok"}]}
        misplaced = {**record, "runs": [run("main", CAP_EXCEPTION_MODEL)]}
        bad_section = {**record, "agreement": {"steps": {"step1": {"claude": {"A": [True]}}}, "registered": {}, "state": "adopted"}}

        # when
        results = [records.validate_record(item) for item in (record, misplaced, bad_section)]

        # then
        self.assertEqual(results[0], [])
        self.assertTrue(any("outside the allowed models" in item for item in results[1]))
        self.assertTrue(any("agreement registered" in item or "agreement state" in item for item in results[2]))


def copy_edited_paths(destination: Path) -> None:
    """The files a candidate edits, from the repository, into a scratch tree that is its own git repository."""
    for relative in {*decision.adoption_tree_paths(), "instructions/session/core.md", "instructions/session/claude-code.md",
                     "instructions/session/codex.md"}:
        source = REPO_ROOT / relative
        if source.is_file():
            (destination / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / relative)
    for prefix in candidate.load_edits()["retire_paths"]:
        if (REPO_ROOT / prefix).is_dir():
            shutil.copytree(REPO_ROOT / prefix, destination / prefix, ignore=shutil.ignore_patterns("__pycache__"))


class CandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def scratch(self, name: str = "tree") -> Path:
        tree = self.root / name
        tree.mkdir()
        copy_edited_paths(tree)
        return tree

    def test_후보의_수정은_지금_저장소의_파일에_그대로_적용된다(self):
        """모든 단계와 폐기까지 포함한 수정이 현재 파일의 정확히 한 곳에 맞아 떨어진다. 파일이 바뀌어 어긋나면 여기서 먼저 알린다."""
        for steps in ({"claude": "step1", "codex": "step1"}, {"claude": "step2", "codex": "step2"},
                      {"claude": "step3-high", "codex": "step1"}):
            with self.subTest(steps=steps):
                # given
                source = DiskSource(REPO_ROOT)

                # when
                changes = candidate.candidate_changes(source, steps, retire=True)

                # then
                self.assertIn(candidate.INSTRUCTION, changes)
                self.assertEqual(candidate.AGENT in changes, candidate.uses_agent(steps))
                self.assertTrue(all(path.startswith("skills/deep-interview") or path.startswith("docs/ko/skills/deep-interview")
                                    for path, text in changes.items() if text is None))

    def test_후보는_common_md를_키우지_않고_새_진입_줄을_만들지_않는다(self):
        """계획 라우팅 예외를 넣어도 common.md의 바이트 수가 늘지 않고 'Before' 진입 줄이 새로 생기지 않는다."""
        # given
        before = (REPO_ROOT / "instructions/session/common.md").read_text(encoding="utf-8")

        # when
        changes = candidate.candidate_changes(DiskSource(REPO_ROOT), {"claude": "step1", "codex": "step1"})
        after = changes["instructions/session/common.md"]

        # then
        self.assertLessEqual(len(after.encode("utf-8")), len(before.encode("utf-8")))
        entries = lambda text: [line for line in text.splitlines() if line.startswith("- Before")]  # noqa: E731
        self.assertEqual(entries(after), entries(before))
        self.assertIn("(../requirements-agreement.md)", after)
        self.assertIn("they remain automatic", after)

    def test_후보를_적용해도_세션_문맥은_두_호스트_모두_커지지_않는다(self):
        """Claude와 Codex 세션 문맥의 바이트 수가 후보 적용 뒤에도 전보다 크지 않다."""
        # given
        tree = self.scratch()
        before = self.context_sizes(REPO_ROOT)

        # when
        candidate.adopt(tree, {"claude": "step2", "codex": "step2"})
        after = self.context_sizes(tree)

        # then
        self.assertLessEqual(after["claude"], before["claude"])
        self.assertLessEqual(after["codex"], before["codex"])

    def context_sizes(self, repo: Path) -> dict[str, int]:
        hooks = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]["hooks"][0]
        sizes = {}
        for host in ("claude", "codex"):
            base = Path(tempfile.mkdtemp(prefix="h5", dir="/tmp"))
            self.addCleanup(shutil.rmtree, base, True)
            root = base / "p"
            root.mkdir()
            shutil.copy2(REPO_ROOT / "AGENTS.md", root / "AGENTS.md")
            for name in ("scripts", "config", ".claude-plugin", "standalone-agents", "docs/ko/instructions"):
                shutil.copytree(REPO_ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(REPO_ROOT / "instructions", root / "instructions", dirs_exist_ok=True)
            if repo != REPO_ROOT:
                shutil.copytree(repo / "instructions", root / "instructions", dirs_exist_ok=True)
            (base / "bin").mkdir()
            (base / "bin" / "python3").symlink_to(sys.executable)
            (base / "proj").mkdir()
            env = {"PATH": f"{base / 'bin'}{os.pathsep}{os.defpath}", "CLAUDE_PLUGIN_ROOT": str(root), "CODEX_HOME": str(base / "ch"),
                   "XDG_STATE_HOME": str(base / "st"), **({"PLUGIN_ROOT": str(root)} if host == "codex" else {})}
            done = subprocess.run(hooks["command"], shell=True, cwd=base / "proj", env=env, text=True, capture_output=True,
                                  input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}), timeout=hooks["timeout"])
            sizes[host] = len(json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"].encode("utf-8"))
        return sizes

    def test_후보의_드래프터_문단은_호스트마다_다른_단계를_그대로_적는다(self):
        """한 호스트는 메인 세션, 다른 호스트는 에이전트일 때 문단이 호스트별로 갈리고 에이전트 설명은 한 번만 붙는다."""
        # given
        mixed = {"claude": "step2", "codex": "step1"}

        # when
        text = candidate.drafter_text(mixed)

        # then
        self.assertIn("On Claude Code, a read-only `spec-drafter` on `claude-opus-5-5` at `xhigh`", text)
        self.assertIn("On Codex, the main session writes the draft.", text)
        self.assertEqual(text.count("never the conversation"), 1)
        self.assertNotIn("never the conversation", candidate.drafter_text({"claude": "step1", "codex": "step1"}))

    def test_두_호스트가_서로_다른_에이전트_단계를_등록하면_하나의_에이전트_파일로_담을_수_없다고_멈춘다(self):
        """claude는 step2, codex는 step3-high처럼 에이전트 모델이 다르면 후보 생성이 CandidateError로 멈춘다."""
        # given
        steps = {"claude": "step2", "codex": "step3-high"}

        # when / then
        with self.assertRaises(CandidateError):
            candidate.candidate_changes(DiskSource(REPO_ROOT), steps)

    def test_맞지_않는_수정은_조용히_넘어가지_않고_멈춘다(self):
        """수정 앞부분이 파일과 다르거나 두 곳에 맞으면 CandidateError로 멈춘다."""
        # given
        text = "one\ntwo\ntwo\n"

        # when / then
        with self.assertRaises(CandidateError):
            candidate.exact_edit("x", text, "three", "4")
        with self.assertRaises(CandidateError):
            candidate.exact_edit("x", text, "two", "4")

    def test_후보를_적용하면_저장소_상태_검사가_기대와_맞고_적용_전에는_도입_기대와_어긋난다(self):
        """단계별로 후보를 적용한 뒤 상태 검사가 채택 기대와 일치하고, 적용 전 트리는 미채택 기대와 일치한다."""
        for steps in ({"claude": "step1", "codex": "step1"}, {"claude": "step2", "codex": "step2"},
                      {"claude": "step3-high", "codex": "step3-high"}):
            with self.subTest(steps=steps):
                # given
                tree = self.scratch(f"tree-{steps['claude']}")
                untouched = decision.repository_problems(tree, decision.expected_state(None))
                adopted_expectation = decision.expected_state({"state": "adopted", "registered": steps})

                # when
                before_problems = decision.repository_problems(tree, adopted_expectation)
                candidate.adopt(tree, steps)
                after_problems = decision.repository_problems(tree, adopted_expectation)

                # then
                self.assertEqual(untouched, [])
                self.assertTrue(before_problems)
                self.assertEqual(after_problems, [])
                self.assertEqual((tree / candidate.AGENT).is_file(), candidate.uses_agent(steps))
                self.assertFalse((tree / "skills" / ("deep" + "-interview")).exists())

    def test_후보의_에이전트는_레지스트리와_매니페스트와_핀_테스트에_함께_등록된다(self):
        """step2는 opus xhigh, step3-high는 fable high로 에이전트 정의, 레지스트리 항목, 매니페스트 목록, 핀 테스트가 같은 값을 쓴다."""
        for step, (model, effort) in candidate.AGENT_STEPS.items():
            with self.subTest(step=step):
                # given
                steps = {"claude": step, "codex": step}

                # when
                changes = candidate.candidate_changes(DiskSource(REPO_ROOT), steps)

                # then
                registry = json.loads(changes[candidate.REGISTRY] or "")
                entry = registry["claude_agents"]["hei5enbug-agent-setup:spec-drafter"]
                manifest = json.loads(changes[".claude-plugin/plugin.json"] or "")
                self.assertEqual((entry["model"], entry["effort"]), (model, effort))
                self.assertIn(f"model: {model}\neffort: {effort}\n", changes[candidate.AGENT] or "")
                self.assertIn("./agents/spec-drafter.md", manifest["agents"])
                self.assertIn(f'("{model}", "{effort}")', changes[candidate.PIN_TEST] or "")

    def test_후보_참조는_기준_개정_위에_커밋_하나로_만들어지고_작업_트리와_인덱스를_건드리지_않는다(self):
        """commit_ref는 기준 커밋을 부모로 하는 커밋을 refs/e2e 아래에 쓰고, 같은 입력이면 같은 커밋이며, 저장소의 작업 트리는 그대로다."""
        # given
        repo = self.root / "repo"
        repo.mkdir()
        copy_edited_paths(repo)
        env = {**os.environ, "GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
               "GIT_COMMITTER_NAME": "Demo Dev", "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_CONFIG_GLOBAL": os.devnull}
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
            subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=env, check=True, capture_output=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        steps = {"claude": "step2", "codex": "step2"}

        # when
        first = candidate.commit_ref(repo, base, "step2", steps)
        second = candidate.commit_ref(repo, base, "step2", steps)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
        parent = subprocess.run(["git", "rev-parse", f"{first}^"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        held = GitSource(repo, f"{candidate.REF_PREFIX}step2")

        # then
        self.assertEqual(first, second)
        self.assertEqual((status, parent), ("", base))
        self.assertIn("# Requirements agreement", held.read(candidate.INSTRUCTION) or "")
        self.assertIsNone(GitSource(repo, base).read(candidate.INSTRUCTION))
        self.assertEqual(len(held.paths("skills/" + "deep" + "-interview")), len(GitSource(repo, base).paths("skills/" + "deep" + "-interview")))


class RepositoryStateTest(unittest.TestCase):
    def test_저장소는_기록이_정한_상태와_같다(self):
        """#96 기록이 없으면 규칙, 에이전트, 폐기 어느 것도 저장소에 없고, 기록이 있으면 기록의 등록 결과와 같은 상태다."""
        # given
        path = E2E_ROOT / "records" / "96.json"
        section = json.loads(path.read_text(encoding="utf-8")).get("agreement") if path.is_file() else None

        # when
        problems = decision.repository_problems(REPO_ROOT, decision.expected_state(section))

        # then
        self.assertEqual(problems, [])


class CapExceptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        for relative in ("agents/spec-drafter.md", "instructions/requirements-agreement.md", "instructions/other.md", "agents/designer.md"):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.root / relative).write_text(f"model: {CAP_EXCEPTION_MODEL}\n", encoding="utf-8")

    def test_예외가_없으면_fable은_모든_파일에서_opus로_바뀌고_있으면_드래프터_파일에서만_남는다(self):
        """예외 없는 내보내기는 fable을 모두 바꾸고, 예외가 있으면 spec-drafter와 합의 규칙 파일에서만 남고 다른 파일은 바뀐다."""
        # given
        plain, excepted = self.root / "plain", self.root / "excepted"
        shutil.copytree(self.root / "agents", plain / "agents")
        shutil.copytree(self.root / "instructions", plain / "instructions")
        shutil.copytree(self.root / "agents", excepted / "agents")
        shutil.copytree(self.root / "instructions", excepted / "instructions")

        # when
        plugin_export.apply_cap_transform(plain)
        record = plugin_export.apply_cap_transform(excepted, CAP_EXCEPTION_MODEL)

        # then
        read = lambda tree, name: (tree / name).read_text(encoding="utf-8")  # noqa: E731
        self.assertTrue(all("claude-opus-5-5" in read(plain, name) for name in
                            ("agents/spec-drafter.md", "instructions/requirements-agreement.md", "instructions/other.md")))
        self.assertIn(CAP_EXCEPTION_MODEL, read(excepted, "agents/spec-drafter.md"))
        self.assertIn(CAP_EXCEPTION_MODEL, read(excepted, "instructions/requirements-agreement.md"))
        self.assertIn("claude-opus-5-5", read(excepted, "instructions/other.md"))
        self.assertIn("claude-opus-5-5", read(excepted, "agents/designer.md"))
        self.assertNotEqual(record["rules_digest"], plugin_export.cap_rules_digest())

    def test_변형_파일은_fable_예외만_받아들인다(self):
        """cap_exception은 claude-fable-5-2만 받고 다른 모델 이름은 설정 오류다."""
        # given
        base = {"name": "v", "ref": "main", "settings": {}, "env": {}, "extra_args": []}

        # when
        allowed = command.validate_variant({**base, "cap_exception": CAP_EXCEPTION_MODEL})

        # then
        self.assertEqual(allowed["cap_exception"], CAP_EXCEPTION_MODEL)
        with self.assertRaises(command.ConfigError):
            command.validate_variant({**base, "cap_exception": "claude-opus-5-5"})
        with self.assertRaises(command.ConfigError):
            command.validate_variant({**base, "cap_exception": "gpt-6-astra"})

    def test_실행_검사는_드래프터_역할의_fable만_넘기고_메인_세션의_fable은_위반으로_센다(self):
        """예외가 켜진 실행에서 spec-drafter 하위 에이전트의 fable은 통과하지만 메인 세션이나 다른 역할의 fable은 위반이다."""
        # given
        request = {"model": CAP_EXCEPTION_MODEL}
        by_source = {"main": [], "subagent:hei5enbug-agent-setup:spec-drafter": [request], "subagent:hei5enbug-agent-setup:designer": [request]}
        stream = [{"type": "result", "modelUsage": {CAP_EXCEPTION_MODEL: {}}}]

        # when
        with_exception = caps.scan_run(stream_events=stream, by_source=by_source, tool_calls=[], rollouts=[], exception=CAP_EXCEPTION_MODEL)
        without = caps.scan_run(stream_events=stream, by_source=by_source, tool_calls=[], rollouts=[])

        # then
        self.assertEqual([item["role"] for item in with_exception], ["subagent:hei5enbug-agent-setup:designer"])
        self.assertTrue(any("spec-drafter" in item["role"] for item in without))


if __name__ == "__main__":
    unittest.main()
