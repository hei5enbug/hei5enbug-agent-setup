"""Unit tests for the headless render step and the four UI tasks T82 to T84 and T112 of the end-to-end evaluation.

Each task's checks are proved offline: the unmodified fixture fails, the reference solution passes, and the deliberately
broken inputs the design names fail exactly the check they should. Tests that render need bun and Chrome and skip
without them; the rest run anywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import graders, render, transcript  # noqa: E402

UI_TASKS = ("T82", "T83", "T84", "T112")
TOOLS_MISSING = render.find_tool(render.BUN_ENV, ("bun",)) is None or render.find_tool(
    render.CHROME_ENV, render.CHROME_NAMES, render.CHROME_FALLBACKS) is None
NEEDS_RENDER = unittest.skipIf(TOOLS_MISSING, "bun or Chrome is not installed")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SETTINGS = "src/SettingsPanel.tsx"


def delegation(agent_type: str, kind_class: str, efforts: list[str] | None = None) -> dict[str, Any]:
    return {"kind": "agent", "type": agent_type, "class": kind_class, "prompt": "", "exit": None, "tool_use_id": "t1",
            "order": 0, "is_error": False, "completed": True, "call_effort": None, "efforts": efforts or []}


def view_with(*delegations: dict[str, Any]) -> dict[str, Any]:
    return {"delegations": list(delegations), "tool_calls": [], "assistant_texts": [], "final_answer": ""}


DESIGNER = view_with(delegation("hei5enbug-agent-setup:designer", "design"))
DESIGNER_HIGH = view_with(delegation("hei5enbug-agent-setup:designer", "design", ["high"]))
DESIGNER_XHIGH = view_with(delegation("hei5enbug-agent-setup:designer", "design", ["xhigh"]))
SONNET_WORKER = view_with(delegation("hei5enbug-agent-setup:sonnet-worker", "implementation"))
NO_DELEGATION = view_with()


class UiTaskCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def load(self, task_id: str) -> dict[str, Any]:
        return graders.load_task(TASKS_ROOT, task_id)

    def repo_for(self, task_id: str, reference: bool = False) -> tuple[Path, str]:
        self.count = getattr(self, "count", 0) + 1
        repo = self.root / f"run-{task_id}-{'ref' if reference else 'base'}-{self.count}"
        base = graders.materialize_fixture(self.load(task_id), FIXTURES_ROOT, TASKS_ROOT, repo)
        if reference:
            env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
            subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(repo)], cwd=repo,
                           env=env, check=True, capture_output=True, text=True)
        return repo, base

    def results(self, task_id: str, repo: Path, base: str, view: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        """Run every check of the task on a copy of `repo` and return the results by check id."""
        task = self.load(task_id)
        work = self.root / f"work-{repo.name}"
        copy = work / "repo"
        shutil.copytree(repo, copy, symlinks=True)
        ctx = graders.GradeContext(task=task, repo=copy, base=base, view=view or DESIGNER_HIGH, tasks_root=TASKS_ROOT,
                                   work=work, origin=repo)
        ctx.snapshot_git_facts()
        return {spec["id"]: graders.run_check(ctx, spec) for spec in task["checks"]}

    def failed_required(self, found: dict[str, dict[str, Any]]) -> set[str]:
        return {name for name, result in found.items() if result["required"] and not result["passed"]}

    def edit(self, repo: Path, relative: str, old: str, new: str) -> None:
        path = repo / relative
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, f"{relative}: {old[:40]!r}")
        path.write_text(text.replace(old, new), encoding="utf-8")

    def append(self, repo: Path, relative: str, text: str) -> None:
        path = repo / relative
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


class TaskDefinitionTest(UiTaskCase):
    def test_세_UI_과제의_정의는_프롬프트_픽스처_참조_해법_검사_함수가_모두_있다(self):
        """T82 T83 T84은 프롬프트, demo-app 픽스처, 참조 해법이 있고 모든 custom 검사 함수가 정의돼 있다."""
        for task_id in UI_TASKS:
            with self.subTest(task_id):
                # given
                task = self.load(task_id)
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")

                # when
                missing = [name for name, ok in (
                    ("prompt", (TASKS_ROOT / task["prompt_file"]).is_file()),
                    ("fixture", (FIXTURES_ROOT / task["fixture"] / "src").is_dir()),
                    ("reference", (TASKS_ROOT / "reference" / task_id / "apply.py").is_file())) if not ok]
                missing += [check["id"] for check in task["checks"]
                            if check["kind"] == "custom" and f"def {check['function']}(" not in source]
                unknown = [check["kind"] for check in task["checks"] if check["kind"] not in graders.CHECKS]

                # then
                self.assertEqual((missing, unknown), ([], []))
                self.assertEqual(task["fixture"], "demo-app")

    def test_라우팅_검사는_필수가_아니어서_before_변형의_숨은_검사_통과가_성공으로_남는다(self):
        """routing-* 검사는 required가 아니다. 그래야 C1을 디자이너가 처리하는 변형도 숨은 검사 통과를 비교할 수 있다."""
        for task_id in UI_TASKS:
            with self.subTest(task_id):
                routing = [check for check in self.load(task_id)["checks"] if check["id"].startswith("routing-")]
                self.assertEqual([(check["id"], check["required"]) for check in routing],
                                 [(f"routing-{'sonnet-worker' if task_id == 'T82' else 'designer'}", False)])

    def test_프롬프트가_고정한_줄_번호와_값이_픽스처의_실제_줄과_맞는다(self):
        """T82 프롬프트의 7 9 17 27번 줄은 픽스처 SettingsPanel.tsx에서 바꿀 값을 정확히 담고 있다."""
        lines = (FIXTURES_ROOT / "demo-app" / SETTINGS).read_text(encoding="utf-8").splitlines()
        self.assertIn("gap: 12", lines[6])
        self.assertIn("<span>Display name</span>", lines[8])
        self.assertIn("<span>Notifications</span>", lines[16])
        self.assertIn('<Button variant="ghost">Cancel</Button>', lines[26])


class RoutingCheckTest(UiTaskCase):
    def routing(self, task_id: str, view: dict[str, Any]) -> bool:
        """Only the routing check, which needs no render."""
        repo, base = self.repo_for(task_id)
        task = self.load(task_id)
        work = self.root / "routing-work"
        copy = work / "repo"
        if copy.exists():
            shutil.rmtree(work)
        shutil.copytree(repo, copy, symlinks=True)
        ctx = graders.GradeContext(task=task, repo=copy, base=base, view=view, tasks_root=TASKS_ROOT, work=work)
        spec = next(check for check in task["checks"] if check["id"].startswith("routing-"))
        return graders.run_check(ctx, spec)["passed"]

    def test_T82은_sonnet_worker로_보냈을_때만_라우팅이_통과한다(self):
        self.assertTrue(self.routing("T82", SONNET_WORKER))
        self.assertFalse(self.routing("T82", DESIGNER))
        self.assertFalse(self.routing("T82", NO_DELEGATION))

    def test_T82은_디자이너와_sonnet_worker를_함께_쓰면_라우팅_실패다(self):
        both = view_with(delegation("hei5enbug-agent-setup:sonnet-worker", "implementation"),
                         delegation("hei5enbug-agent-setup:designer", "design"))
        self.assertFalse(self.routing("T82", both))

    def test_T83와_T84은_디자이너로_보냈을_때만_라우팅이_통과한다(self):
        for task_id in ("T83", "T84"):
            with self.subTest(task_id):
                self.assertTrue(self.routing(task_id, DESIGNER))
                self.assertFalse(self.routing(task_id, SONNET_WORKER))
                self.assertFalse(self.routing(task_id, NO_DELEGATION))

    def test_오류로_끝난_위임은_라우팅으로_치지_않는다(self):
        failed = view_with({**delegation("hei5enbug-agent-setup:designer", "design"), "is_error": True})
        self.assertFalse(self.routing("T83", failed))


class EffortCheckTest(UiTaskCase):
    """The designer effort checks read the efforts a subagent record shows, so they need no render."""

    def effort_passes(self, task_id: str, view: dict[str, Any]) -> bool:
        repo, base = self.repo_for(task_id)
        task = self.load(task_id)
        work = self.root / "effort-work"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(repo, work / "repo", symlinks=True)
        ctx = graders.GradeContext(task=task, repo=work / "repo", base=base, view=view, tasks_root=TASKS_ROOT, work=work)
        spec = next(check for check in task["checks"] if check["id"].startswith("effort-designer-"))
        self.assertTrue(spec["required"])
        return graders.run_check(ctx, spec)["passed"]

    def test_T83와_T84은_디자이너가_high로_돌았을_때만_필수_effort_검사가_통과한다(self):
        for task_id in ("T83", "T84"):
            with self.subTest(task_id):
                self.assertTrue(self.effort_passes(task_id, DESIGNER_HIGH))
                self.assertFalse(self.effort_passes(task_id, DESIGNER_XHIGH))
                self.assertFalse(self.effort_passes(task_id, DESIGNER))
                self.assertFalse(self.effort_passes(task_id, SONNET_WORKER))
                self.assertFalse(self.effort_passes(task_id, NO_DELEGATION))

    def test_T112은_디자이너가_xhigh로_돌았을_때만_필수_effort_검사가_통과한다(self):
        self.assertTrue(self.effort_passes("T112", DESIGNER_XHIGH))
        self.assertFalse(self.effort_passes("T112", DESIGNER_HIGH))
        self.assertFalse(self.effort_passes("T112", DESIGNER))
        self.assertFalse(self.effort_passes("T112", NO_DELEGATION))

    def test_디자이너가_둘이고_하나라도_다른_effort면_실패하고_오류로_끝난_위임은_세지_않는다(self):
        mixed = view_with(delegation("hei5enbug-agent-setup:designer", "design", ["high"]),
                          delegation("hei5enbug-agent-setup:designer", "design", ["xhigh"]))
        switched = view_with(delegation("hei5enbug-agent-setup:designer", "design", ["high", "xhigh"]))
        failed = view_with({**delegation("hei5enbug-agent-setup:designer", "design", ["xhigh"]), "is_error": True},
                           delegation("hei5enbug-agent-setup:designer", "design", ["high"]))
        self.assertFalse(self.effort_passes("T83", mixed))
        self.assertFalse(self.effort_passes("T83", switched))
        self.assertTrue(self.effort_passes("T83", failed))


class DelegationEffortTest(unittest.TestCase):
    def view(self, call_input: dict[str, Any], record_events: list[dict[str, Any]], meta_effort: str | None = None) -> dict[str, Any]:
        events = [
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": "tu-design", "name": "Agent", "input": {"subagent_type": "hei5enbug-agent-setup:designer",
                                                                                   "prompt": "x", **call_input}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu-design", "content": "done"}]}},
        ]
        meta = {"agentType": "hei5enbug-agent-setup:designer", "toolUseId": "tu-design", **({"effort": meta_effort} if meta_effort else {})}
        return transcript.build_view(events, [{"meta": meta, "events": record_events}])

    def test_위임은_호출의_effort와_서브에이전트_기록의_effort를_따로_담는다(self):
        events = [{"type": "assistant", "effort": "high", "message": {"id": "a", "content": []}},
                  {"type": "assistant", "effort": "high", "message": {"id": "b", "content": []}}]
        found = self.view({"effort": "high"}, events)["delegations"][0]
        self.assertEqual((found["call_effort"], found["efforts"]), ("high", ["high"]))

    def test_호출이_effort를_넘기지_않으면_기록의_effort만_남고_기록이_없으면_메타를_쓴다(self):
        events = [{"type": "assistant", "effort": "xhigh", "message": {"id": "a", "content": []}}]
        plain = self.view({}, events, meta_effort="high")["delegations"][0]
        meta_only = self.view({}, [{"type": "user"}], meta_effort="high")["delegations"][0]
        bare = self.view({}, [{"type": "user"}])["delegations"][0]
        self.assertEqual((plain["call_effort"], plain["efforts"]), (None, ["xhigh"]))
        self.assertEqual(meta_only["efforts"], ["high"])
        self.assertEqual(bare["efforts"], [])


class SettingsPanelTest(UiTaskCase):
    """T82 line checks need no render, so these run without bun and Chrome."""

    LINE_CHECKS = {"spacing-16", "label-full-name", "label-email-alerts", "variant-secondary"}

    def line_results(self, repo: Path, base: str) -> dict[str, dict[str, Any]]:
        task = self.load("T82")
        skipped = {"renders"}
        task = {**task, "checks": [check for check in task["checks"] if check["id"] not in skipped]}
        work = self.root / f"line-work-{repo.name}"
        copy = work / "repo"
        shutil.copytree(repo, copy, symlinks=True)
        ctx = graders.GradeContext(task=task, repo=copy, base=base, view=SONNET_WORKER, tasks_root=TASKS_ROOT, work=work)
        ctx.snapshot_git_facts()
        return {spec["id"]: graders.run_check(ctx, spec) for spec in task["checks"]}

    def test_수정하지_않은_저장소는_네_가지_수정_검사에서_실패한다(self):
        repo, base = self.repo_for("T82")
        found = self.line_results(repo, base)
        self.assertEqual(self.failed_required(found), self.LINE_CHECKS)
        self.assertTrue(found["nothing-else-changed"]["passed"])

    def test_참조_해법은_모든_필수_검사를_통과한다(self):
        repo, base = self.repo_for("T82", reference=True)
        found = self.line_results(repo, base)
        self.assertEqual(self.failed_required(found), set(), {k: v["detail"] for k, v in found.items() if not v["passed"]})
        self.assertTrue(found["routing-sonnet-worker"]["passed"])

    def test_설계가_정한_잘못된_입력_다른_줄을_하나_더_고치면_그_줄_검사만_실패한다(self):
        repo, base = self.repo_for("T82", reference=True)
        self.edit(repo, SETTINGS, 'value="Mina Park"', 'value="Mina P."')
        found = self.line_results(repo, base)
        self.assertEqual(self.failed_required(found), {"nothing-else-changed"})
        self.assertIn("10", found["nothing-else-changed"]["detail"])

    def test_줄을_더하거나_지우면_줄_수가_달라져_nothing_else_changed가_실패한다(self):
        repo, base = self.repo_for("T82", reference=True)
        self.append(repo, SETTINGS, "// note\n")
        self.assertIn("nothing-else-changed", self.failed_required(self.line_results(repo, base)))

    def test_다른_파일을_고치면_only_allowed_files_changed가_실패한다(self):
        repo, base = self.repo_for("T82", reference=True)
        self.append(repo, "src/styles.css", "\n.extra {\n  margin: 0;\n}\n")
        self.assertEqual(self.failed_required(self.line_results(repo, base)), {"only-allowed-files-changed"})

    def test_네_곳_중_하나만_틀려도_그_검사가_실패한다(self):
        for name, old, new in (("spacing-16", "gap: 16", "gap: 24"), ("label-full-name", "Full name", "Name"),
                               ("label-email-alerts", "Email alerts", "Alerts"),
                               ("variant-secondary", 'variant="secondary"', 'variant="danger"')):
            with self.subTest(name):
                repo = self.root / f"wrong-{name}"
                shutil.copytree(self.repo_for("T82", reference=True)[0], repo, symlinks=True)
                base = subprocess.run(["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"], check=True,
                                      capture_output=True, text=True).stdout.strip()
                self.edit(repo, SETTINGS, old, new)
                self.assertIn(name, self.failed_required(self.line_results(repo, base)))


@NEEDS_RENDER
class RenderedTaskTest(UiTaskCase):
    def test_수정하지_않은_Profile은_두_칸_검사에서_실패하고_넘침_검사는_통과한다(self):
        repo, base = self.repo_for("T83")
        found = self.results("T83", repo, base)
        self.assertEqual(self.failed_required(found), {"columns-side-by-side-1280", "columns-stack-375", "content-kept"})

    def test_T83_참조_해법은_모든_필수_검사를_통과한다(self):
        repo, base = self.repo_for("T83", reference=True)
        found = self.results("T83", repo, base, DESIGNER_HIGH)
        self.assertEqual(self.failed_required(found), set(), {k: v["detail"] for k, v in found.items() if not v["passed"]})
        self.assertTrue(found["routing-designer"]["passed"])

    def test_T83_고정_폭_두_칸은_375px에서_쌓이지_않고_가로로_넘쳐_실패한다(self):
        repo, base = self.repo_for("T83", reference=True)
        self.append(repo, "src/styles.css",
                    "\n.profile-columns {\n  display: flex;\n  flex-direction: row;\n}\n\n.profile-column {\n  flex: 0 0 500px;\n}\n"
                    "\n@media (max-width: 640px) {\n  .profile-columns {\n    flex-direction: row;\n  }\n}\n")
        found = self.results("T83", repo, base)
        self.assertEqual(self.failed_required(found), {"columns-stack-375", "no-overflow-375"})
        self.assertTrue(found["columns-side-by-side-1280"]["passed"])

    def test_T83_쌓이지만_고정_폭이_남아_375px에서_넘치면_넘침_검사만_실패한다(self):
        repo, base = self.repo_for("T83", reference=True)
        self.append(repo, "src/styles.css", "\n.profile-column {\n  width: 500px;\n}\n")
        found = self.results("T83", repo, base)
        self.assertEqual(self.failed_required(found), {"no-overflow-375"})

    def test_T83는_칸_표시를_빼면_두_칸_검사가_실패한다(self):
        repo, base = self.repo_for("T83", reference=True)
        self.edit(repo, "src/Profile.tsx", ' data-testid="col-right"', "")
        found = self.results("T83", repo, base)
        self.assertEqual(self.failed_required(found), {"columns-side-by-side-1280", "columns-stack-375", "content-kept"})

    def test_수정하지_않은_Plans는_한_줄_배치_검사에서_실패한다(self):
        repo, base = self.repo_for("T84")
        found = self.results("T84", repo, base)
        self.assertEqual(self.failed_required(found), {"named-values-1280", "cards-visible-375", "plans-kept"})

    def test_T84_참조_해법은_모든_필수_검사를_통과한다(self):
        repo, base = self.repo_for("T84", reference=True)
        found = self.results("T84", repo, base, DESIGNER_HIGH)
        self.assertEqual(self.failed_required(found), set(), {k: v["detail"] for k, v in found.items() if not v["passed"]})
        self.assertTrue(found["routing-designer"]["passed"])

    def test_T84_고정_폭_카드를_줄이지_않으면_375px에서_넘쳐_실패한다(self):
        repo, base = self.repo_for("T84", reference=True)
        self.append(repo, "src/styles.css", "\n.plan-list {\n  flex-wrap: nowrap;\n}\n\n.plan {\n  flex: none;\n}\n"
                    "\n@media (max-width: 720px) {\n  .plan-list {\n    flex-direction: row;\n  }\n\n  .plan {\n    width: 320px;\n  }\n}\n")
        found = self.results("T84", repo, base)
        self.assertEqual(self.failed_required(found), {"cards-visible-375", "no-overflow-375"})
        self.assertTrue(found["named-values-1280"]["passed"])

    def test_T84_이름_붙은_값이_다르면_1280px_검사가_실패한다(self):
        repo, base = self.repo_for("T84", reference=True)
        self.append(repo, "src/styles.css", "\n.plan {\n  width: 300px;\n}\n")
        self.assertIn("named-values-1280", self.failed_required(self.results("T84", repo, base)))

    def test_T84_지정하지_않은_파일을_고치면_변경_범위_검사가_실패한다(self):
        repo, base = self.repo_for("T84", reference=True)
        self.edit(repo, "src/components/Button.tsx", '"ghost"', '"ghost" | "link"')
        self.assertEqual(self.failed_required(self.results("T84", repo, base)), {"only-allowed-files-changed"})

    def test_수정하지_않은_저장소는_T112의_화면_검사에서_실패한다(self):
        repo, base = self.repo_for("T112")
        found = self.results("T112", repo, base, DESIGNER_XHIGH)
        self.assertEqual(self.failed_required(found), {"invoices-listed", "rows-stacked-1280", "rows-visible-375", "renders",
                                                       "no-overflow-1280", "no-overflow-375"})

    def test_T112_참조_해법은_모든_필수_검사를_통과한다(self):
        repo, base = self.repo_for("T112", reference=True)
        found = self.results("T112", repo, base, DESIGNER_XHIGH)
        self.assertEqual(self.failed_required(found), set(), {k: v["detail"] for k, v in found.items() if not v["passed"]})
        self.assertTrue(found["routing-designer"]["passed"])

    def test_T112_effort가_high면_다른_검사가_모두_통과해도_effort_검사만_실패한다(self):
        repo, base = self.repo_for("T112", reference=True)
        found = self.results("T112", repo, base, DESIGNER_HIGH)
        self.assertEqual(self.failed_required(found), {"effort-designer-xhigh"})

    def test_T112_고정_폭_행은_375px에서_넘쳐_보임_검사와_넘침_검사가_실패한다(self):
        repo, base = self.repo_for("T112", reference=True)
        self.append(repo, "src/styles.css", "\n.invoice-row {\n  width: 500px;\n}\n")
        found = self.results("T112", repo, base, DESIGNER_XHIGH)
        self.assertEqual(self.failed_required(found), {"rows-visible-375", "no-overflow-375"})

    def test_T112_행이_하나_모자라면_목록_검사가_실패한다(self):
        repo, base = self.repo_for("T112", reference=True)
        self.edit(repo, "src/Invoices.tsx", '{ name: "May invoice", amount: "$135.00", status: "Due" },', "")
        found = self.results("T112", repo, base, DESIGNER_XHIGH)
        self.assertIn("invoices-listed", self.failed_required(found))

    def test_T112_지정하지_않은_파일을_고치면_변경_범위_검사가_실패한다(self):
        repo, base = self.repo_for("T112", reference=True)
        self.edit(repo, "src/components/Button.tsx", '"ghost"', '"ghost" | "link"')
        self.assertEqual(self.failed_required(self.results("T112", repo, base, DESIGNER_XHIGH)), {"only-allowed-files-changed"})

    def test_T82_참조_해법은_화면이_그려지고_스크린샷이_PNG로_남는다(self):
        repo, base = self.repo_for("T82", reference=True)
        found = self.results("T82", repo, base, SONNET_WORKER)
        self.assertEqual(self.failed_required(found), set())
        shots = found["renders"]["data"]["screenshots"]
        self.assertEqual(sorted(shots), ["1280", "375"])
        for width, path in shots.items():
            with self.subTest(width):
                self.assertEqual(Path(path).read_bytes()[:8], PNG_MAGIC)
                self.assertGreater(int(width), 0)

    def test_화면이_번들되지_않으면_renders와_모든_배치_검사가_실패한다(self):
        repo, base = self.repo_for("T83", reference=True)
        self.edit(repo, "src/Profile.tsx", "export default function Profile() {", "export default function Profile( {")
        found = self.results("T83", repo, base)
        self.assertFalse(found["renders"]["passed"])
        self.assertIn("bun build failed", found["renders"]["detail"])
        self.assertTrue({"columns-side-by-side-1280", "no-overflow-375"} <= self.failed_required(found))

    def test_화면이_실행_중_오류를_내면_renders가_실패한다(self):
        repo, base = self.repo_for("T83", reference=True)
        self.edit(repo, "src/Profile.tsx", "const activity = [", "const missing = (null as unknown as string[]).length;\nconst activity = [")
        found = self.results("T83", repo, base)
        self.assertFalse(found["renders"]["passed"])


class RenderToolsTest(unittest.TestCase):
    def test_bun이나_Chrome이_없으면_판정_불가_예외를_낸다(self):
        with mock.patch.dict(os.environ, {render.BUN_ENV: "/nonexistent/bun"}):
            with self.assertRaises(render.RenderUnavailable) as caught:
                render.require_tools()
        self.assertTrue(caught.exception.no_verdict)
        self.assertIn("bun", str(caught.exception))

    def test_도구가_없을_때_채점기는_검사_실패가_아니라_판정_불가로_멈춘다(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            task = json.loads((TASKS_ROOT / "T83.json").read_text(encoding="utf-8"))
            base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
            work = root / "work"
            shutil.copytree(repo, work / "repo", symlinks=True)
            ctx = graders.GradeContext(task=task, repo=work / "repo", base=base, view=DESIGNER, tasks_root=TASKS_ROOT, work=work)
            spec = next(check for check in task["checks"] if check["id"] == "renders")
            with mock.patch.dict(os.environ, {render.BUN_ENV: "/nonexistent/bun"}):
                with self.assertRaises(render.RenderUnavailable):
                    graders.run_check(ctx, spec)

    def test_설정한_경로가_없으면_PATH를_뒤지지_않고_없다고_본다(self):
        with mock.patch.dict(os.environ, {render.CHROME_ENV: "/nonexistent/chrome"}):
            self.assertIsNone(render.find_tool(render.CHROME_ENV, render.CHROME_NAMES, render.CHROME_FALLBACKS))

    def test_화면_이름은_파일_경로에서_안전한_슬러그가_된다(self):
        self.assertEqual(render.screen_slug("src/SettingsPanel.tsx"), "settingspanel")
        self.assertEqual(render.screen_slug("src/My Screen!.tsx"), "my-screen")


if __name__ == "__main__":
    unittest.main()
