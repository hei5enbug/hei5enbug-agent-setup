"""Offline tests of the GPT role comparison: the decision rule, the cost and status evidence, the new cases, and one whole
run with a fake role runner. No model is called."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "gpt-roles"))

import gr_cases  # noqa: E402
import gr_core  # noqa: E402
import gr_decide  # noqa: E402
import gr_language  # noqa: E402
import gr_run  # noqa: E402
import gr_text_cases  # noqa: E402
import gr_worker_cases  # noqa: E402


def row(role, case, model, passed=True, cost=0.10, wall=60.0, rep=1):
    return {"role": role, "case": case, "model": model, "effort": "high", "rep": rep, "passed": passed, "failures": [],
            "cost_usd": cost, "wall_seconds": wall, "rollout": ""}


def rollout_lines(model, usage):
    return [
        {"type": "session_meta", "payload": {"cwd": "/tmp/text-review-abc", "timestamp": "2026-11-20T00:00:00Z"}},
        {"type": "turn_context", "payload": {"model": model, "effort": "high"}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": usage, "total_token_usage": usage}}},
    ]


class EfficiencyRuleTest(unittest.TestCase):
    def table(self, *rows):
        return gr_decide.cells(rows, "reviewer")

    def test_모든_사례를_통과하지_못한_후보는_자격이_없다(self):
        """given 한 후보가 사례 하나를 실패했을 때 then 통과한 후보만 남고 가장 싼 쪽이 이긴다."""
        table = self.table(row("reviewer", "A", "x", passed=False, cost=0.01), row("reviewer", "A", "y", cost=0.50))
        decision = gr_decide.role_decision(table, ("x", "y"), ["A"])
        self.assertEqual((decision["status"], decision["winner"]), ("winner", "y"))

    def test_1_5배이고_60초_넘게_느린_후보는_탈락한다(self):
        table = self.table(row("reviewer", "A", "x", cost=0.10, wall=30), row("reviewer", "A", "y", cost=0.05, wall=100))
        decision = gr_decide.role_decision(table, ("x", "y"), ["A"])
        self.assertEqual(decision["winner"], "x")
        self.assertIn("y", decision["dropped"])

    def test_1_5배여도_60초_이하로_느리면_탈락하지_않는다(self):
        table = self.table(row("reviewer", "A", "x", cost=0.50, wall=30), row("reviewer", "A", "y", cost=0.20, wall=89))
        self.assertEqual(gr_decide.role_decision(table, ("x", "y"), ["A"])["winner"], "y")

    def test_비용_차이가_10퍼센트_안이면_더_빠른_후보가_이긴다(self):
        table = self.table(row("reviewer", "A", "x", cost=1.00, wall=90), row("reviewer", "A", "y", cost=1.09, wall=60))
        self.assertEqual(gr_decide.role_decision(table, ("x", "y"), ["A"])["winner"], "y")

    def test_비용_차이가_5센트_안이면_더_빠른_후보가_이긴다(self):
        table = self.table(row("reviewer", "A", "x", cost=0.10, wall=90), row("reviewer", "A", "y", cost=0.149, wall=60))
        self.assertEqual(gr_decide.role_decision(table, ("x", "y"), ["A"])["winner"], "y")

    def test_통과도_없으면_승자가_없다(self):
        table = self.table(row("reviewer", "A", "x", passed=False))
        self.assertEqual(gr_decide.role_decision(table, ("x",), ["A"])["status"], "none")

    def test_묶음_안에서_속도까지_같으면_동률이다(self):
        table = self.table(row("reviewer", "A", "x", cost=0.10, wall=60), row("reviewer", "A", "y", cost=0.10, wall=60))
        self.assertEqual(gr_decide.role_decision(table, ("x", "y"), ["A"])["status"], "tie")

    def test_두_번째_반복은_평균으로_세고_한_번이라도_실패하면_실패다(self):
        table = self.table(row("reviewer", "A", "x", cost=0.10, rep=1), row("reviewer", "A", "x", passed=False, cost=0.30, rep=2))
        self.assertFalse(table["x"]["A"]["passed"])
        self.assertAlmostEqual(table["x"]["A"]["cost"], 0.20)


def sol_rows(new_cost, old_cost=1.0, new_passes=True, role_set=gr_decide.SOL_ROLES):
    rows = []
    for role in role_set:
        rows.append(row(role, "A", "gpt-6.1-sol", cost=old_cost))
        rows.append(row(role, "A", "gpt-6.2-sol", passed=new_passes, cost=new_cost))
    return rows


class SolReplacementTest(unittest.TestCase):
    def test_6_2_sol이_모든_사례를_통과하고_비용이_밴드_밖으로_싸면_전부_바꾼다(self):
        plan = gr_decide.registry_plan(sol_rows(0.50))
        self.assertTrue(plan["sol"]["replace_all_with_6_2_sol"])
        self.assertEqual(plan["changes"]["opponents.codex.model"], "gpt-6.2-sol")
        self.assertEqual(plan["changes"]["scripts/text_review.py REVIEW_MODELS"], "gpt-6.2-sol")

    def test_한_역할에서_6_1_sol이_통과하는_사례를_6_2_sol이_못하면_바꾸지_않는다(self):
        rows = sol_rows(0.50)
        rows = [r for r in rows if not (r["role"] == "language" and r["model"] == "gpt-6.2-sol")] + [
            row("language", "A", "gpt-6.2-sol", passed=False, cost=0.5)]
        plan = gr_decide.registry_plan(rows)
        self.assertFalse(plan["sol"]["replace_all_with_6_2_sol"])
        self.assertNotIn("opponents.codex.model", plan["changes"])

    def test_비용이_밴드_안이면_바꾸지_않는다(self):
        self.assertFalse(gr_decide.registry_plan(sol_rows(0.95))["sol"]["replace_all_with_6_2_sol"])

    def test_측정되지_않은_역할이_있으면_바꾸지_않는다(self):
        rows = sol_rows(0.50, role_set=("reviewer", "language"))
        self.assertFalse(gr_decide.registry_plan(rows)["sol"]["replace_all_with_6_2_sol"])

    def test_terra가_한_역할을_이기면_그_역할만_terra로_바뀐다(self):
        rows = sol_rows(2.0)
        rows.append(row("reviewer", "A", "gpt-6.1-terra", cost=0.2))
        plan = gr_decide.registry_plan(rows)
        self.assertEqual(plan["sol"]["single_role_winners"], {"reviewer": "gpt-6.1-terra"})
        self.assertEqual(plan["changes"]["codex_agents.reviewer.model"], "gpt-6.1-terra")
        self.assertNotIn("opponents.codex.model", plan["changes"])


class LunaReplacementTest(unittest.TestCase):
    def rows(self, new_pass=True, new_cost=0.05, old_cost=0.05):
        out = []
        for role in gr_decide.LUNA_ROLES:
            out.append(row(role, "A", "gpt-5.6-luna", cost=old_cost))
            out.append(row(role, "A", "gpt-6-luna", passed=new_pass, cost=new_cost))
        return out

    def test_6_luna가_같거나_낫다면_쓴다(self):
        plan = gr_decide.registry_plan(self.rows())
        self.assertEqual(plan["changes"]["runner.role_model"], "gpt-6-luna")
        self.assertEqual(plan["changes"]["codex_agents.scout.model"], "gpt-6-luna")

    def test_6_luna가_사례를_못_통과하면_5_6_luna를_유지한다(self):
        plan = gr_decide.registry_plan(self.rows(new_pass=False))
        self.assertNotIn("runner.role_model", plan["changes"])
        self.assertEqual(plan["luna"]["roles"]["scout"]["use"], "gpt-5.6-luna")

    def test_6_luna가_밴드_밖으로_비싸면_유지한다(self):
        self.assertEqual(gr_decide.registry_plan(self.rows(new_cost=0.50))["luna"]["roles"]["worker"]["use"], "gpt-5.6-luna")


class EvidenceTest(unittest.TestCase):
    def test_요청에_정가를_적용해_비용을_계산한다(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            usage = {"input_tokens": 200_000, "cached_input_tokens": 100_000, "output_tokens": 50_000}
            path.write_text("\n".join(json.dumps(item) for item in rollout_lines("gpt-6.2-sol", usage)), encoding="utf-8")
            self.assertAlmostEqual(gr_core.rollout_cost(path, "gpt-6.2-sol"), 0.2 + 0.01 + 0.5)

    def test_초안_호출의_토큰_사용량은_캐시_읽기와_쓰기를_따로_계산한다(self):
        tokens = {"input_tokens": 100_000, "cached_input_tokens": 40_000, "cache_write_input_tokens": 10_000, "output_tokens": 10_000}
        self.assertAlmostEqual(gr_core.usage_cost("gpt-6-luna", tokens), 0.05 * 0.10 + 0.04 * 0.01 + 0.01 * 0.125 + 0.01 * 0.5, places=6)

    def test_다른_모델이_답한_롤아웃은_오류다(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in rollout_lines("gpt-6.1-sol", {"input_tokens": 10, "output_tokens": 1})), encoding="utf-8")
            with self.assertRaises(ValueError):
                gr_core.rollout_cost(path, "gpt-6.2-sol")

    def test_상태_줄은_검증된_같은_모델과_노력이어야_한다(self):
        line = json.dumps({"exit": 0, "verified": True, "model": "gpt-6-luna", "effort": "high", "evidence": {}})
        self.assertEqual(gr_core.verified_status("noise\n" + line, "gpt-6-luna", "high")["model"], "gpt-6-luna")
        with self.assertRaises(ValueError):
            gr_core.verified_status(line, "gpt-6.2-sol", "high")
        with self.assertRaises(ValueError):
            gr_core.verified_status(line.replace("true", "false"), "gpt-6-luna", "high")

    def test_다른_세션의_롤아웃은_모델로_걸러낸다(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            folder = home / "sessions" / "2026" / "11" / "20"
            folder.mkdir(parents=True)
            for name, model in (("rollout-a.jsonl", "gpt-6.1-sol"), ("rollout-b.jsonl", "gpt-6.2-sol")):
                (folder / name).write_text("\n".join(json.dumps(i) for i in rollout_lines(model, {"input_tokens": 1})), encoding="utf-8")
            found = gr_core.rollouts_since(0, "text-review-", "gpt-6.2-sol", home)
            self.assertEqual([path.name for path in found], ["rollout-b.jsonl"])

    def test_플러그인_사본은_러너가_후보_모델을_시작하도록_목록만_늘린다(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = gr_core.plugin_copy(Path(tmp) / "plugin")
            listed = json.loads((copy / "config" / "model-registry.json").read_text())["runner"]["review_models"]
            self.assertIn("gpt-6.2-sol", listed)
            self.assertIn("gpt-6-luna", listed)
            self.assertTrue((copy / "scripts" / "role_runner.py").is_file())


class WorkerCasesTest(unittest.TestCase):
    SOLUTIONS = {
        "W1": {"slugs/text.py": 'import re\n\n\ndef slugify(text):\n    """Lowercase text, hyphenate each run of non-alphanumerics, strip the ends."""\n    return re.sub(r"[\\W_]+", "-", text.lower()).strip("-")\n'},
        "W2": {
            "inventory/stock.py": gr_worker_cases.STOCK_SOURCE + (
                "\n    def reserve(self, sku, quantity):\n        left = self._available[sku]\n        if quantity < 1 or quantity > left:\n"
                "            raise ValueError(quantity)\n        self._available[sku] = left - quantity\n        return self._available[sku]\n"),
            "inventory/report.py": gr_worker_cases.REPORT_SOURCE + (
                "\n\ndef low_stock(stock, threshold):\n    return [sku for sku in stock.skus() if stock.available(sku) <= threshold]\n"),
        },
    }

    def seed(self, case_id):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        return repo, gr_worker_cases.seed(case_id, repo)

    def test_시드_그대로면_숨은_테스트가_실패한다(self):
        for case_id in ("W1", "W2", "W3"):
            repo, base = self.seed(case_id)
            self.assertTrue(any("hidden tests fail" in item for item in gr_worker_cases.failures(case_id, repo, base)), case_id)

    def test_올바른_수정은_통과한다(self):
        for case_id, files in self.SOLUTIONS.items():
            repo, base = self.seed(case_id)
            for relative, text in files.items():
                (repo / relative).write_text(text, encoding="utf-8")
            self.assertEqual(gr_worker_cases.failures(case_id, repo, base), [], case_id)

    def test_W3의_올바른_이름_변경은_통과하고_별칭은_실패한다(self):
        repo, base = self.seed("W3")
        for path in list((repo / "billing").glob("*.py")) + [repo / "tests" / "test_totals.py", repo / "README.md"]:
            path.write_text(path.read_text().replace("calc_total", "total_cents"), encoding="utf-8")
        self.assertEqual(gr_worker_cases.failures("W3", repo, base), [])
        (repo / "billing" / "totals.py").write_text(
            (repo / "billing" / "totals.py").read_text() + "\ncalc_total = total_cents\n", encoding="utf-8")
        self.assertTrue(gr_worker_cases.failures("W3", repo, base))

    def test_허용되지_않은_경로나_커밋은_실패다(self):
        repo, base = self.seed("W1")
        (repo / "slugs" / "text.py").write_text(self.SOLUTIONS["W1"]["slugs/text.py"], encoding="utf-8")
        (repo / "notes.txt").write_text("x", encoding="utf-8")
        self.assertTrue(any("outside the allowed" in item for item in gr_worker_cases.failures("W1", repo, base)))
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "-qam", "x"], check=True, capture_output=True)
        self.assertIn("a commit was made", gr_worker_cases.failures("W1", repo, base))


class TextAndScoutCasesTest(unittest.TestCase):
    def test_심은_결함을_찾고_다른_지적이_없으면_통과한다(self):
        good = {"findings": [{"type": "removable", "quote": "fixes the stale cache after an import", "reason": "the source shows no cache change"}]}
        self.assertEqual(gr_text_cases.failures("TR1", good), [])

    def test_심은_결함을_놓치거나_범위_밖_지적이_있으면_실패다(self):
        self.assertTrue(gr_text_cases.failures("TR1", {"findings": []}))
        extra = {"findings": [{"type": "removable", "quote": "the stale cache", "reason": "cache"}, {"type": "ambiguous", "quote": "one row", "reason": "x"}]}
        self.assertTrue(any("outside" in item for item in gr_text_cases.failures("TR1", extra)))
        self.assertTrue(gr_text_cases.failures("TR2", {"errors": ["usage"]}))

    def test_시드한_초안은_결정적_검사를_통과한다(self):
        for case_id, case in gr_text_cases.CASES.items():
            with tempfile.TemporaryDirectory() as tmp:
                paths = gr_text_cases.seed(case_id, Path(tmp))
                done = subprocess.run([sys.executable, str(ROOT / "scripts" / "text_review.py"), "check", "--kind", case["kind"], str(paths["draft"])],
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stdout)

    def test_정찰_사례_채점기(self):
        self.assertEqual(gr_cases.scout_failures("SC1", "`demo-lib/src/parser.py` lines 8-9: `for delimiter in DELIMITERS` tries them in order."), [])
        self.assertTrue(gr_cases.scout_failures("SC1", "It splits at the first delimiter."))
        self.assertEqual(gr_cases.scout_failures("SC2", "blocked: demo-lib/docs/missing.md does not exist."), [])
        self.assertTrue(gr_cases.scout_failures("SC2", "missing.md does not list deployment steps."))
        self.assertEqual(gr_cases.scout_failures("SC3", "Delimiters `=` and `:`; the maximum line length is not stated."), [])
        self.assertTrue(gr_cases.scout_failures("SC3", "Delimiters `=` and `:`; lines may be 80 characters."))

    def test_연구자_채점기(self):
        good = "RFC 2119, 1997, Key words for use in RFCs to Indicate Requirement Levels, https://www.rfc-editor.org/rfc/rfc2119"
        self.assertEqual(gr_cases.researcher_failures(good, '{"type":"web_search_call"}'), [])
        self.assertEqual(gr_cases.researcher_failures(good, 'await tools.web__run({search_query:[{q:"x"}]})'), [])
        self.assertTrue(gr_cases.researcher_failures(good, "no search"))

    def test_세_정찰_사례와_두_새_사례는_결정적_검사로_시드된다(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            gr_cases.seed_scout_demo(repo)
            self.assertTrue((repo / "demo-lib" / "src" / "parser.py").is_file())


class LanguageResultsTest(unittest.TestCase):
    def test_초안과_채점에서_통과_비용_순위를_만든다(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "drafts").mkdir()
            (out / "grades").mkdir()
            for writer, secs in (("gpt-6.1-sol", 40.0), ("gpt-6.2-sol", 30.0)):
                (out / "drafts" / f"t1_r1_{writer}.json").write_text(json.dumps({
                    "ok": True, "writer": writer, "task": "t1", "run": 1, "secs": secs,
                    "usage": {"input_tokens": 10_000, "cached_input_tokens": 0, "output_tokens": 1_000}}), encoding="utf-8")
            entry = lambda missing: {"missing_facts": missing, "added_facts": [], "unnatural": []}  # noqa: E731
            (out / "grades" / "t1_r1_g.json").write_text(json.dumps({
                "task": "t1", "run": 1, "grader": "claude-opus-5-5", "key": {"A": "gpt-6.1-sol", "B": "gpt-6.2-sol"},
                "res": {"ok": True, "cost": 0.2}, "grade": {"drafts": {"A": entry(["f4"]), "B": entry([])}, "ranking": ["B"]}}), encoding="utf-8")
            found = {item["model"]: item for item in gr_language.results(out)}
            self.assertFalse(found["gpt-6.1-sol"]["passed"])
            self.assertTrue(found["gpt-6.2-sol"]["passed"])
            self.assertEqual(found["gpt-6.2-sol"]["rank"], 1)
            self.assertAlmostEqual(found["gpt-6.2-sol"]["cost_usd"], 0.02 + 0.01)


FAKE_RUNNER = '''#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
role, model, effort = args[0], args[args.index("--model") + 1], args[args.index("--effort") + 1]
result = Path(args[args.index("--result") + 1])
text = Path("slugs/text.py")
text.write_text(text.read_text().replace("out.append(char if char.isalnum() else \\"-\\")", "out.append(char if char.isalnum() else \\"-\\")").replace(
    "return \\"\\".join(out).strip(\\"-\\")", "import re\\n    return re.sub(\\"-+\\", \\"-\\", \\"\\".join(out)).strip(\\"-\\")"))
result.write_text("done")
rollout = Path(sys.argv[0]).parent / "rollout.jsonl"
usage = {"input_tokens": 100000, "cached_input_tokens": 0, "output_tokens": 10000}
lines = [{"type": "session_meta", "payload": {"cwd": "/x"}}, {"type": "turn_context", "payload": {"model": model, "effort": effort}},
         {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": usage, "total_token_usage": usage}}}]
rollout.write_text("\\n".join(json.dumps(l) for l in lines))
print(json.dumps({"role": role, "model": model, "effort": effort, "verified": True, "exit": 0, "evidence": {"rollout": str(rollout)}}))
'''


class DryCheckTest(unittest.TestCase):
    def test_모든_사례는_모델_호출_없이_시드되고_명령을_출력한다(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = gr_core.plugin_copy(Path(tmp) / "plugin")
            for case_id, case in gr_cases.CASES.items():
                found = gr_run.dry_check(case_id, "gpt-6.2-sol", plugin)
                self.assertEqual(found["case"], case_id)
                self.assertEqual(found["effort"], case.effort)
                self.assertTrue(found["command"])

    def test_러너가_모르는_모델은_오류다(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = gr_core.plugin_copy(Path(tmp) / "plugin", extra_models=())
            with self.assertRaises(gr_run.CaseError):
                gr_run.dry_check("W1", "gpt-6.2-sol", plugin)


class WholeRunTest(unittest.TestCase):
    def test_가짜_러너로_작업자_사례_한_번을_끝까지_돌리고_결과_파일을_쓴다(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "plugin"
            (plugin / "scripts").mkdir(parents=True)
            (plugin / "scripts" / "role_runner.py").write_text(FAKE_RUNNER, encoding="utf-8")
            result = gr_run.execute("W1", "gpt-6.2-sol", Path(tmp) / "out", 1, plugin)
            self.assertTrue(result["passed"], result["failures"])
            self.assertAlmostEqual(result["cost_usd"], 0.2 + 0.1)
            self.assertTrue(gr_core.result_path(Path(tmp) / "out", "worker", "W1", "gpt-6.2-sol", 1).is_file())
            self.assertEqual(len(gr_core.load_results(Path(tmp) / "out")), 1)

    def test_러너가_검증하지_못하면_채점하지_않고_오류를_낸다(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "plugin"
            (plugin / "scripts").mkdir(parents=True)
            (plugin / "scripts" / "role_runner.py").write_text("import json\nprint(json.dumps({'verified': False, 'exit': 4}))\n", encoding="utf-8")
            with self.assertRaises(gr_run.CaseError):
                gr_run.execute("W1", "gpt-6.2-sol", Path(tmp) / "out", 1, plugin)
            self.assertEqual(gr_core.load_results(Path(tmp) / "out") if (Path(tmp) / "out" / "results").exists() else [], [])


if __name__ == "__main__":
    unittest.main()
