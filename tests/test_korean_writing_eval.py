"""The Korean writing evaluation reads its rules from the shared text rules and keeps its cases well formed."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "evals" / "korean-writing"
sys.path.insert(0, str(EVAL_DIR))

import kw_aggregate  # noqa: E402
import kw_jobs  # noqa: E402
import kw_prompts  # noqa: E402
import kw_seeded  # noqa: E402

SHARED_TEXT = REPO_ROOT / "instructions" / "shared-text.md"


def grade_entry(missing=(), added=(), unnatural=0):
    return {"missing_facts": list(missing), "added_facts": list(added),
            "unnatural": [{"quote": "q", "why": "w"}] * unnatural}


class CasesTest(unittest.TestCase):
    def test_모든_작업은_원문과_필수_사실을_가진다(self):
        """각 작업은 다섯 종류 중 하나이며 원문과 고유 id의 필수 사실을 가진다."""
        # Given
        cases = kw_prompts.load_cases()

        # When
        kinds = {case["kind"] for case in cases.values()}

        # Then
        self.assertGreaterEqual(len(cases), 5)
        self.assertGreaterEqual(len(kinds), 5)
        for case in cases.values():
            with self.subTest(task=case["id"]):
                self.assertTrue(case["sources"].strip() and case["reader"].strip())
                ids = [fact["id"] for fact in case["facts"]]
                self.assertTrue(ids)
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(all(fact["text"].strip() for fact in case["facts"]))

    def test_시드_쌍은_작업과_사실을_가리킨다(self):
        """각 시드 쌍은 있는 작업을 가리키고, 사실 누락 쌍은 그 작업에 있는 사실을 가리킨다."""
        # Given
        cases = kw_prompts.load_cases()

        # When
        pairs = kw_prompts.load_seeded()

        # Then
        self.assertEqual({pair["check"] for pair in pairs}, {"missing_fact", "calque"})
        for pair in pairs:
            with self.subTest(pair=pair["id"]):
                self.assertIn(pair["task"], cases)
                self.assertNotEqual(pair["good"], pair["bad"])
                if pair["check"] == "missing_fact":
                    self.assertIn(pair["fact"], [fact["id"] for fact in cases[pair["task"]]["facts"]])


class PromptTest(unittest.TestCase):
    def test_규칙은_shared_text에서_실행_시점에_읽는다(self):
        """글쓰기 규칙은 복사본이 아니라 instructions/shared-text.md에서 읽는다."""
        # Given
        text = SHARED_TEXT.read_text(encoding="utf-8")

        # When
        rules = kw_prompts.load_rules()

        # Then
        self.assertIn(kw_prompts.COMPLETENESS_HEADING, rules)
        self.assertIn("1. Cut pass:", rules)
        self.assertIn("2. Completeness pass:", rules)
        self.assertNotIn("3. When the destination has a length budget", rules)
        self.assertIn(kw_prompts.READABLE_HEADING, rules)
        self.assertIn("such as 규칙, 응답 형식, or 정해 둔 동작", rules)
        self.assertIn(text.split(kw_prompts.READABLE_HEADING)[1].strip().splitlines()[0], rules)

    def test_규칙을_바꾸면_프롬프트가_따라_바뀐다(self):
        """shared-text.md의 문장이 바뀌면 작성자와 채점자 프롬프트에 그 문장이 들어간다."""
        # Given
        case = next(iter(kw_prompts.load_cases().values()))
        changed = SHARED_TEXT.read_text(encoding="utf-8").replace("Cut pass:", "Cut pass (changed marker):")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shared-text.md"
            path.write_text(changed, encoding="utf-8")

            # When
            rules = kw_prompts.load_rules(path)

        # Then
        self.assertIn("changed marker", kw_prompts.writer_prompt(case, rules))
        self.assertIn("changed marker", kw_prompts.grader_prompt(case, {"A": "초안"}, rules))

    def test_채점_프롬프트는_작성자_모델_이름을_담지_않는다(self):
        """채점자가 받는 입력에는 라벨만 있고 작성자 모델 이름이 없다."""
        # Given
        case = kw_prompts.load_cases()["t1"]
        writers = ["gpt-6.1-sol", "claude-opus-5-5"]
        key = kw_prompts.shuffle_key("seed", "t1", 1, writers)

        # When
        prompt = kw_prompts.grader_prompt(case, {label: "초안 " + label for label in key}, kw_prompts.load_rules())

        # Then
        self.assertEqual(sorted(key.values()), sorted(writers))
        for writer in writers:
            self.assertNotIn(writer, prompt)

    def test_섞는_순서는_같은_시드에서_같고_실행마다_다르다(self):
        """같은 시드, 작업, 실행이면 라벨 배정이 같고 실행 번호가 바뀌면 달라질 수 있다."""
        # Given
        writers = ["a", "b", "c", "d"]

        # When
        first = kw_prompts.shuffle_key("seed", "t1", 1, writers)
        again = kw_prompts.shuffle_key("seed", "t1", 1, list(reversed(writers)))
        orders = {tuple(kw_prompts.shuffle_key("seed", "t1", run, writers).values()) for run in range(1, 6)}

        # Then
        self.assertEqual(first, again)
        self.assertGreater(len(orders), 1)


class SeededCheckTest(unittest.TestCase):
    def pair(self, check):
        return next(pair for pair in kw_prompts.load_seeded() if pair["check"] == check)

    def test_사실이_빠진_초안을_잡으면_통과한다(self):
        """나쁜 초안에 사실 누락을 보고하고 좋은 초안만 순위에 올리면 통과한다."""
        # Given
        pair = self.pair("missing_fact")
        caught = {"drafts": {"A": grade_entry(), "B": grade_entry(missing=[pair["fact"]])}, "ranking": ["A"]}
        missed = {"drafts": {"A": grade_entry(), "B": grade_entry()}, "ranking": ["A", "B"]}

        # When
        results = (kw_seeded.check_pair(pair, "good_first", caught)[0], kw_seeded.check_pair(pair, "good_first", missed)[0])

        # Then
        self.assertEqual(results, (True, False))

    def test_번역투가_있는_초안을_더_낮게_매기면_통과한다(self):
        """번역투 초안이 더 낮은 순위이고 어색한 표현이 더 많으면 통과한다."""
        # Given
        pair = self.pair("calque")
        good = {"drafts": {"A": grade_entry(unnatural=3), "B": grade_entry(unnatural=0)}, "ranking": ["B", "A"]}
        flipped = {"drafts": {"A": grade_entry(unnatural=3), "B": grade_entry(unnatural=0)}, "ranking": ["A", "B"]}

        # When
        results = (kw_seeded.check_pair(pair, "bad_first", good)[0], kw_seeded.check_pair(pair, "bad_first", flipped)[0])

        # Then
        self.assertEqual(results, (True, False))


class CampaignTest(unittest.TestCase):
    def fake_model(self, favourite):
        def run(spec, prompt, out, tag, timeout=900):
            if tag.startswith("w_"):
                return {"ok": True, "text": "초안", "secs": 2.0, "usage": {"output_tokens": 5}, "cost": None, "model_ok": True}
            labels = [line.split()[2] for line in prompt.splitlines() if line.startswith("=== DRAFT ")]
            key = self.keys[tag]
            ranking = sorted(labels, key=lambda label: key[label] != favourite)
            grade = {"drafts": {label: grade_entry() for label in labels}, "ranking": ranking, "ranking_all": ranking}
            return {"ok": True, "text": json.dumps(grade), "secs": 1.0, "usage": None, "cost": None}
        return run

    def run_campaign(self, favourite, graders):
        writers = ["gpt-6.1-sol", "claude-opus-5-5"]
        specs = {"gpt-6.1-sol": "codex:gpt-6.1-sol", "claude-opus-5-5": "claude:claude-opus-5-5",
                 "gpt-6-astra": "codex:gpt-6-astra"}
        self.keys = {}
        for task in ("t1", "t2"):
            for run in (1, 2):
                for grader in graders:
                    self.keys[f"g_{task}_r{run}_{kw_jobs.slug(grader)}"] = kw_prompts.shuffle_key(
                        kw_prompts.DEFAULT_SEED, task, run, writers)
        with tempfile.TemporaryDirectory() as folder, patch.object(kw_jobs, "run_model", self.fake_model(favourite)):
            out = Path(folder)
            kw_jobs.run_campaign(out, specs, writers, graders, ["t1", "t2"], 2, 2, 1.0, 5,
                                 kw_prompts.DEFAULT_SEED, lambda message: None)
            return kw_aggregate.summarize(out)

    def test_두_계열_채점자가_같은_후보를_과반으로_고르면_승자다(self):
        """모든 채점자가 한 후보를 모든 작업 실행에서 1위로 고르고 사실 오류가 없으면 그 후보가 이긴다."""
        # Given
        graders = ["gpt-6-astra", "claude-opus-5-5"]

        # When
        summary = self.run_campaign("claude-opus-5-5", graders)

        # Then
        self.assertEqual(summary["decision"], {"verdict": "winner", "winner": "claude-opus-5-5"})
        self.assertEqual(summary["agreement"], [4, 4])
        self.assertTrue(summary["unconfirmed"])

    def test_한_계열_채점자만_채점하면_결론이_나지_않는다(self):
        """한 계열의 채점자만 남으면 그 채점자가 모두 같은 후보를 골라도 판정은 inconclusive다."""
        # Given
        graders = ["gpt-6-astra"]

        # When
        summary = self.run_campaign("claude-opus-5-5", graders)

        # Then
        self.assertEqual(summary["decision"], {"verdict": "inconclusive", "winner": None})

    def test_한_채점자만_고르면_결론이_나지_않는다(self):
        """한 후보를 1위로 고르는 채점자가 한 명뿐이면 판정은 inconclusive다."""
        # Given
        graders = ["gpt-6-astra", "claude-opus-5-5"]
        real = self.fake_model

        def mixed(favourite):
            run = real(favourite)
            other = real("gpt-6.1-sol")
            return lambda spec, prompt, out, tag, timeout=900: (other if tag.endswith("claude-opus-5-5") and tag.startswith("g_") else run)(spec, prompt, out, tag, timeout)

        self.fake_model = mixed

        # When
        summary = self.run_campaign("claude-opus-5-5", graders)

        # Then
        self.assertEqual(summary["decision"]["verdict"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
