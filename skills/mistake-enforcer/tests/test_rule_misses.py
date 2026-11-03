import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "rule_misses.py"
RECORDS = Path(__file__).parent / "fixtures" / "records"
WINDOW = ["--since", "2026-10-04", "--until", "2026-11-03"]

REMINDER_RULE = {"id": "R-reminder", "source": "demo/core.md:10", "kinds": ["reminder"], "patterns": ["before the commit"]}
STOP_RULE = {"id": "R-stop", "source": "demo/core.md:20", "kinds": ["stop"], "patterns": ["Korean"]}
DENIAL_RULE = {"id": "R-denial", "source": "demo/core.md:30", "kinds": ["denial"], "patterns": ["denied by"]}


class AuditCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def run_audit(self, rules, *extra, records=RECORDS):
        rules_path = self.tmp / "rules.json"
        rules_path.write_text(json.dumps(rules), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--records", str(records), *WINDOW, "--rules", str(rules_path), *extra],
            capture_output=True,
            text=True,
            check=False,
        )

    def audit(self, rules, *extra):
        result = self.run_audit(rules, *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @staticmethod
    def by_id(report):
        return {rule["id"]: rule for rule in report["rules"]}


class CountTest(AuditCase):
    def test_같은_알림이_두_세션에_있으면_세션_2와_답변_수_기준_비율을_보고한다(self):
        # Given
        rules = [REMINDER_RULE]

        # When
        report = self.audit(rules)

        # Then
        rule = self.by_id(report)["R-reminder"]
        self.assertEqual((rule["sessions"], rule["hits"]), (2, 2))
        self.assertEqual(report["totals"]["replies"], 5)
        self.assertEqual(rule["per_100_replies"], 40.0)
        self.assertEqual(rule["source"], "demo/core.md:10")

    def test_하위_에이전트_사이드체인_기간_밖_기록은_세지_않는다(self):
        # Given
        rules = [REMINDER_RULE]

        # When
        report = self.audit(rules)

        # Then
        totals = report["totals"]
        self.assertEqual((totals["files"], totals["sessions"], totals["prompts"]), (2, 2, 3))
        self.assertEqual(self.by_id(report)["R-reminder"]["hits"], 2)
        texts = [example["text"] for example in self.by_id(report)["R-reminder"]["examples"]]
        self.assertTrue(all("Step 3" in text or "Step 7" in text for text in texts))

    def test_Stop과_거부_신호는_그_종류를_가진_규칙에만_맞는다(self):
        # Given
        wrong_kind = {"id": "R-wrong", "source": "demo/core.md:40", "kinds": ["reminder"], "patterns": ["Korean", "denied by"]}
        stop_only = {"id": "R-stop-denied", "source": "demo/core.md:50", "kinds": ["stop"], "patterns": ["denied by"]}
        rules = [wrong_kind, stop_only, STOP_RULE, DENIAL_RULE]

        # When
        report = self.audit(rules)

        # Then
        rules_by_id = self.by_id(report)
        self.assertEqual(rules_by_id["R-wrong"]["hits"], 0)
        self.assertEqual(rules_by_id["R-stop-denied"]["hits"], 0)
        self.assertEqual(rules_by_id["R-stop"]["hits"], 1)
        self.assertEqual(rules_by_id["R-denial"]["hits"], 1)

    def test_규칙에_없는_알림은_정규화한_서명으로_unmatched에_나온다(self):
        # Given
        rules = [REMINDER_RULE, STOP_RULE]

        # When
        report = self.audit(rules)

        # Then
        signatures = {(item["kind"], item["signature"]): item for item in report["unmatched"]}
        notice = signatures[("reminder", "New hook: check `X` N times")]
        self.assertEqual((notice["sessions"], notice["hits"]), (1, 1))
        self.assertIn("denial", {item["kind"] for item in report["unmatched"]})
        self.assertNotIn("stop", {item["kind"] for item in report["unmatched"]})


class CandidateTest(AuditCase):
    def candidates(self):
        out = self.tmp / "candidates.json"
        self.audit([REMINDER_RULE], "--candidates", str(out))
        return json.loads(out.read_text(encoding="utf-8"))

    def test_정정_요청은_직전_답변과_함께_하지_않았다는_최종_답변은_not_done으로_쓴다(self):
        # Given / When
        candidates = self.candidates()

        # Then
        correction = next(item for item in candidates if item["kind"] == "correction")
        self.assertIn("왜 테스트를 안 했어", correction["text"])
        self.assertIn("테스트를 실행하지 않았습니다", correction["previous"])
        not_done = next(item for item in candidates if item["kind"] == "not-done")
        self.assertIn("실행하지 않았습니다", not_done["text"])

    def test_평범한_요청과_완료_보고는_후보가_되지_않는다(self):
        # Given / When
        candidates = self.candidates()

        # Then
        self.assertEqual(len(candidates), 2)
        joined = " ".join(item["text"] for item in candidates)
        self.assertNotIn("README", joined)
        self.assertNotIn("끝났습니다", joined)


class FailureTest(AuditCase):
    def test_잘못된_규칙_파일은_종료_코드_2로_실패한다(self):
        # Given
        bad_rules = [{"id": "R-bad", "source": "demo/core.md:1", "kinds": ["reminder"], "patterns": ["(unclosed"]}]
        not_a_list = {"id": "R-object"}

        for rules in (bad_rules, not_a_list):
            with self.subTest(rules=rules):
                # When
                result = self.run_audit(rules)

                # Then
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.strip())

    def test_없는_기록_폴더는_종료_코드_2로_실패한다(self):
        # Given
        missing = self.tmp / "no-such-folder"

        # When
        result = self.run_audit([REMINDER_RULE], records=missing)

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
