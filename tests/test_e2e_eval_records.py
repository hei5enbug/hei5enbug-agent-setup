"""Unit tests for the measurement record format and its validator."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import records  # noqa: E402

MODELS = {
    "claude": {"main": {"model": "claude-opus-5-5", "effort": "high"}, "worker": {"model": "claude-sonnet-5-5", "effort": "high"}},
    "codex": {"main": {"model": "gpt-6.1-sol", "effort": "high"}},
}


def run(variant, host, wall, cost):
    return {"case": "T08", "variant": variant, "host": host, "rep": 1, "models": MODELS[host],
            "checks": {"only-config-changed": True, "one-line-diff": True, "text-review-clean": True},
            "wall_seconds": wall, "cost_usd": cost,
            "reviews": [{"findings": [{"sentence": "demo finding"}]}, {"findings": []}]}


def complete():
    return records.build_record(
        92, ["T08"], {"before": "0123abc", "after": "4567def"},
        [run(v, h, 120.5 if v == "before" else 118.0, 0.42) for v in ("before", "after") for h in ("claude", "codex")],
        [{"case": "T08", "measure": "quality", "verdict": "pass", "step": "first run"},
         {"case": "T08", "measure": "wall_seconds", "verdict": "pass", "step": "first run"}])


class RecordValidatorTest(unittest.TestCase):
    def test_모든_필드가_있는_가상_기록은_검증을_통과한다(self):
        """given 사례, 변형별 리비전, 실행별 호스트와 역할별 모델, 검사 결과, 시간, 비용, 판정과 단계가 모두 있을 때 when 검증하면 then 문제가 없다."""
        # given
        record = complete()

        # when
        problems = records.validate_record(record)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(sorted(record), ["cases", "issue", "runs", "variants", "verdicts"])

    def test_필드가_하나라도_빠진_기록은_거부된다(self):
        """given 각 실행과 판정에서 필수 필드를 하나씩 뺀 기록일 때 when 검증하면 then 빠진 필드를 이름으로 거부한다."""
        for key in records.RUN_REQUIRED:
            with self.subTest(run_field=key):
                # given
                record = copy.deepcopy(complete())
                del record["runs"][0][key]

                # when
                problems = records.validate_record(record)

                # then
                self.assertIn(f"runs[0] lacks {key}", problems)
        for key in ("cases", "variants", "runs", "verdicts", "issue"):
            with self.subTest(top_field=key):
                record = copy.deepcopy(complete())
                del record[key]
                self.assertIn(f"the record lacks {key}", records.validate_record(record))
        record = copy.deepcopy(complete())
        del record["verdicts"][0]["step"]
        self.assertIn("verdicts[0] lacks step", records.validate_record(record))

    def test_절대_로컬_경로가_들어간_기록은_거부된다(self):
        """given 검사 이름이나 리비전에 절대 로컬 경로가 들어갔을 때 when 검증하면 then 경로를 이유로 거부한다."""
        for place in ("check", "revision", "review"):
            with self.subTest(place):
                # given
                record = copy.deepcopy(complete())
                if place == "check":
                    record["runs"][0]["checks"]["/home/test/work/out.txt exists"] = True
                elif place == "revision":
                    record["variants"]["after"]["revision"] = "/tmp/work/export"
                else:
                    record["runs"][0]["reviews"][0]["findings"][0]["sentence"] = "see /Users/demo/notes.md"

                # when
                problems = records.validate_record(record)

                # then
                self.assertIn("the record contains an absolute local path", problems)

    def test_허용하지_않은_모델이나_호스트가_들어간_기록은_거부된다(self):
        """given 상한을 넘는 모델이나 알 수 없는 호스트일 때 when 검증하면 then 그 역할과 필드를 이유로 거부한다."""
        # given
        stronger = copy.deepcopy(complete())
        stronger["runs"][1]["models"]["review"] = {"model": "gpt-6-astra", "effort": "high"}
        unknown = copy.deepcopy(complete())
        unknown["runs"][0]["host"] = "gemini"

        # when
        stronger_problems = records.validate_record(stronger)
        unknown_problems = records.validate_record(unknown)

        # then
        self.assertIn("runs[1] role review uses a model outside the allowed models", stronger_problems)
        self.assertIn("runs[0] host is not one of claude, codex", unknown_problems)

    def test_측정값이_없는_실행은_null로_남길_수_있다(self):
        """given 비용을 못 읽은 실행일 때 when 검증하면 then null은 허용되지만 문자열은 거부된다."""
        # given
        record = copy.deepcopy(complete())
        record["runs"][0]["cost_usd"] = None
        text = copy.deepcopy(complete())
        text["runs"][0]["cost_usd"] = "0.4"

        # when / then
        self.assertEqual(records.validate_record(record), [])
        self.assertIn("runs[0] cost_usd is not a number or null", records.validate_record(text))

    def test_기록_폴더_검증은_이슈_번호_파일_이름과_내용을_함께_본다(self):
        """given 올바른 기록과 파일 이름이 다른 기록이 있는 폴더일 때 when 폴더를 검증하면 then 이름이 틀린 파일만 문제로 나온다."""
        # given
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records.write_record(complete(), root)
            (root / "7.json").write_text(json.dumps(complete()), encoding="utf-8")

            # when
            found = records.validate_directory(root)

            # then
            self.assertEqual(list(found), ["7.json"])

    def test_저장소의_모든_기록_파일은_검증을_통과한다(self):
        """given 저장소의 evals/e2e/records 폴더일 때 when 검증하면 then 문제가 있는 기록이 없다."""
        # given / when
        found = records.validate_directory()

        # then
        self.assertEqual(found, {})

    def test_허용_모델과_노력_값은_모델_레지스트리를_벗어나지_않는다(self):
        """given 모델 레지스트리의 고정 모델과 노력 목록일 때 when 기록 검증기의 허용값과 비교하면 then 모두 레지스트리 안에 있다."""
        # given
        registry = json.loads((REPO_ROOT / "config/model-registry.json").read_text(encoding="utf-8"))

        # when / then
        self.assertLessEqual(records.ALLOWED_MODELS, set(registry["pins"].values()))
        self.assertLessEqual(records.EFFORTS, set(registry["efforts"]))
        self.assertNotIn("claude-fable-5-2", records.ALLOWED_MODELS)
        self.assertNotIn("gpt-6-astra", records.ALLOWED_MODELS)


if __name__ == "__main__":
    unittest.main()
