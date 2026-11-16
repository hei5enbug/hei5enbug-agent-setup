"""Tests for the seeded cases of the Fable-versus-Opus comparison: their data, seeding, and deterministic grading."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROLES = REPO_ROOT / "evals" / "model-roles"
sys.path.insert(0, str(MODEL_ROLES))

import mr_cases  # noqa: E402
import mr_grading  # noqa: E402

CASES = mr_cases.load_cases()
FENCE = "```"


def answer(*findings: tuple[str, str, str]) -> str:
    """An answer whose last block holds the given (location, problem, effect) findings."""
    items = [{"location": place, "problem": problem, "effect": effect} for place, problem, effect in findings]
    return f"notes\n{FENCE}json\n{json.dumps({'findings': items})}\n{FENCE}\n"


GOOD = {
    "T89": ("seatmap/seats.py:25", "hold_many checks the held seats before it takes the lock, a race between threads",
            "two threads can both pass and then exceed the capacity or hold the same seat twice"),
    "T90": ("pricing/api.py:17", "quote drops the documented public field total_cents and renames it",
            "reports/export.py raises KeyError and clients parsing the documented field break"),
    "T91": ("issue.md:16", "Proposal 2 contradicts acceptance criterion 2: entries only expire after 15 minutes",
            "a changed price can stay stale for up to 15 minutes, so the 30 seconds cannot be met"),
    "T92": ("design.md:14", "every retry gets a newly generated X-Delivery-Id and the subscriber cannot deduplicate",
            "a timeout after processing makes the subscriber act twice, for example a duplicate receipt email"),
    "T93": ("design.md:12", "hash(customer_id) % 8 puts acme-trading's 41 percent of the writes on one shard",
            "that hot shard takes about 492 inserts per second and exceeds the 400 a primary sustains"),
}


class CaseDataTest(unittest.TestCase):
    def test_사례는_T89부터_T93까지이고_검토_셋_토론_둘이다(self):
        """사례는 T89부터 T93까지 다섯 개이며 검토 사례 셋과 토론 사례 둘로 나뉜다."""
        # When
        roles = mr_cases.roles_by_case(CASES)

        # Then
        self.assertEqual(["T89", "T90", "T91", "T92", "T93"], list(roles))
        self.assertEqual(["reviewer"] * 3 + ["opponent"] * 2, list(roles.values()))

    def test_모든_사례는_심은_문제_하나와_맞는_위치_근거를_갖는다(self):
        """각 사례는 심은 문제 하나를 갖고, 그 위치 범위 안에 근거 문구가 실제로 있다."""
        for case_id, case in CASES.items():
            with self.subTest(case=case_id):
                # Given
                planted = [problem for problem in case["problems"] if problem["planted"]]

                # When
                lines_at = {
                    (name, place["start"], place["end"]): mr_cases.head_text(case_id, name).splitlines()
                    for problem in case["problems"] for place in problem["locations"]
                    for name in [place["file"]]
                }
                anchored = [
                    place["anchor"] in "\n".join(lines_at[(place["file"], place["start"], place["end"])][place["start"] - 1:place["end"]])
                    for problem in case["problems"] for place in problem["locations"]
                ]

                # Then
                self.assertEqual(1, len(planted))
                self.assertTrue(all(anchored))

    def test_후보에게_보이는_파일에는_정답_정보가_없다(self):
        """시드한 저장소와 프롬프트에는 심은 문제의 요약, case.json, 정답 키워드가 없다."""
        for case_id, case in CASES.items():
            with self.subTest(case=case_id), tempfile.TemporaryDirectory() as temp:
                # Given
                paths = mr_cases.seed(case_id, Path(temp) / "case")

                # When
                visible = [Path(paths["prompt"]).read_text(encoding="utf-8")] + [
                    path.read_text(encoding="utf-8", errors="replace")
                    for path in Path(paths["repo"]).rglob("*") if path.is_file() and ".git" not in path.parts
                ]

                # Then
                for problem in case["problems"]:
                    self.assertFalse(any(problem["summary"] in text or problem["id"] in text for text in visible))
                self.assertFalse((Path(paths["repo"]) / "case.json").exists())


class SeedingTest(unittest.TestCase):
    def seeded(self, case_id: str, temp: str) -> dict:
        return mr_cases.seed(case_id, Path(temp) / case_id)

    def commits(self, repo: str) -> list[str]:
        return subprocess.run(
            ["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.splitlines()

    def test_diff_사례는_기준_커밋과_변경_커밋을_만들고_나머지는_커밋_하나다(self):
        """T89와 T90은 기준과 변경의 두 커밋, T91부터 T93은 커밋 하나로 시드된다."""
        with tempfile.TemporaryDirectory() as temp:
            # When
            counts = {case_id: len(self.commits(self.seeded(case_id, temp)["repo"])) for case_id in CASES}

            # Then
            self.assertEqual({"T89": 2, "T90": 2, "T91": 1, "T92": 1, "T93": 1}, counts)

    def test_이미_내용이_있는_폴더에는_시드하지_않는다(self):
        """비어 있지 않은 repo 폴더에 시드하면 FileExistsError로 멈춘다."""
        with tempfile.TemporaryDirectory() as temp:
            # Given
            repo = Path(temp) / "case" / "repo"
            repo.mkdir(parents=True)
            (repo / "keep.txt").write_text("x", encoding="utf-8")

            # When / Then
            with self.assertRaises(FileExistsError):
                mr_cases.seed("T89", Path(temp) / "case")

    def test_검토_프롬프트는_독립_검증_문서의_검토_항목을_그대로_싣는다(self):
        """검토 프롬프트의 항목은 독립 검증 문서의 Review checks 글머리와 같고, 이슈 본문에는 구현 항목이 없다."""
        # Given
        document = (REPO_ROOT / "instructions" / "independent-model-validation.md").read_text(encoding="utf-8")

        # When
        diff, issue = mr_cases.review_checks("diff"), mr_cases.review_checks("issue")

        # Then
        self.assertIn("Contradictions and materially ambiguous wording", issue)
        self.assertNotIn("Side effects: trace each changed function", issue)
        for bullet in diff.splitlines():
            self.assertIn(" ".join(bullet.split()), " ".join(document.split()))

    def test_T89_저자_검사_문구는_시드한_저장소에서_사실이다(self):
        """T89 프롬프트가 말한 검사 결과(6 passed)는 시드한 저장소에서 그대로 재현된다."""
        with tempfile.TemporaryDirectory() as temp:
            # When
            done = subprocess.run(
                [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                cwd=self.seeded("T89", temp)["repo"], capture_output=True, text=True,
            )

            # Then
            self.assertIn("6 passed", done.stdout)

    def test_T90_저자_검사는_통과하지만_전체_테스트는_심은_문제로_실패한다(self):
        """T90은 tests/test_api.py의 3개가 통과하고, 전체 실행에서는 소비자 테스트가 KeyError로 실패한다."""
        with tempfile.TemporaryDirectory() as temp:
            # Given
            repo = self.seeded("T90", temp)["repo"]
            command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

            # When
            module = subprocess.run([*command, "tests/test_api.py"], cwd=repo, capture_output=True, text=True)
            everything = subprocess.run(command, cwd=repo, capture_output=True, text=True)

            # Then
            self.assertIn("3 passed", module.stdout)
            self.assertIn("KeyError", everything.stdout)


class GradingTest(unittest.TestCase):
    def test_심은_문제를_위치와_효과로_지적한_답은_사례마다_통과한다(self):
        """사례마다 심은 문제를 위치와 효과로 지적한 답 하나는 통과하고 놓친 것도 바깥 지적도 없다."""
        for case_id, finding in GOOD.items():
            with self.subTest(case=case_id):
                # When
                graded = mr_grading.grade(CASES[case_id], answer(finding))

                # Then
                self.assertEqual(
                    {"pass": True, "error": None, "findings": 1, "found": sorted(p["id"] for p in CASES[case_id]["problems"]),
                     "missed": [], "outside": []},
                    graded,
                )

    def test_심은_문제를_놓치면_실패한다(self):
        """지적이 없거나 다른 곳만 가리키면 심은 문제가 missed에 남아 실패한다."""
        for case_id, finding in GOOD.items():
            with self.subTest(case=case_id):
                # Given
                elsewhere = ("README.md:1", *finding[1:])

                # When
                none, wrong_place = mr_grading.grade(CASES[case_id], answer()), mr_grading.grade(CASES[case_id], answer(elsewhere))

                # Then
                self.assertEqual(([False, False], [True, True]), ([none["pass"], wrong_place["pass"]], [bool(none["missed"]), bool(wrong_place["missed"])]))
                self.assertEqual([{"index": 0, "location": "README.md:1"}], wrong_place["outside"])

    def test_목록_밖의_지적이_하나라도_있으면_심은_문제를_짚어도_실패한다(self):
        """올바른 지적에 목록에 없는 지적 하나를 더하면 outside에 그 지적이 남고 실패한다."""
        for case_id, finding in GOOD.items():
            with self.subTest(case=case_id):
                # Given
                extra = ("README.md:2", "the wording could be shorter", "readers lose a second")

                # When
                graded = mr_grading.grade(CASES[case_id], answer(finding, extra))

                # Then
                self.assertFalse(graded["pass"])
                self.assertEqual([], graded["missed"])
                self.assertEqual([{"index": 1, "location": "README.md:2"}], graded["outside"])

    def test_효과를_말하지_않거나_문제를_못_짚은_지적은_위치가_맞아도_심은_문제로_세지_않는다(self):
        """위치는 맞지만 효과가 비었거나 문제와 효과 키워드가 없는 지적은 목록 밖이 되어 실패한다."""
        # Given
        place = GOOD["T89"][0]
        no_effect = answer((place, "hold_many checks before the lock, a race", " "))
        vague = answer((place, "this part looks odd", "it is confusing"))

        # When
        graded = [mr_grading.grade(CASES["T89"], text) for text in (no_effect, vague)]

        # Then
        self.assertEqual([False, False], [item["pass"] for item in graded])
        self.assertEqual([["check-outside-lock"]] * 2, [item["missed"] for item in graded])

    def test_위치_표기는_앞_점_경로_범위_절대_경로_접미를_받아들인다(self):
        """./path:line, path:첫줄-끝줄, 작업 폴더 절대 경로 접두는 같은 위치로 읽고 범위가 겹치면 맞다."""
        # Given
        _, problem, effect = GOOD["T89"]
        forms = ["./seatmap/seats.py:25", "seatmap/seats.py:20-26", "/tmp/work/repo/seatmap/seats.py:30", "`seatmap/seats.py:24`"]

        # When
        passed = [mr_grading.grade(CASES["T89"], answer((form, problem, effect)))["pass"] for form in forms]

        # Then
        self.assertEqual([True] * 4, passed)

    def test_답에_블록이_없거나_깨졌거나_모양이_틀리면_오류로_실패한다(self):
        """json 블록이 없거나, JSON이 깨졌거나, findings가 목록이 아니거나, 지적에 문자열 필드가 없으면 error와 함께 실패한다."""
        # Given
        texts = [
            "no block",
            f"{FENCE}json\n{{not json\n{FENCE}",
            f'{FENCE}json\n{{"findings": "x"}}\n{FENCE}',
            f'{FENCE}json\n{{"findings": [{{"location": "a:1"}}]}}\n{FENCE}',
        ]

        # When
        graded = [mr_grading.grade(CASES["T89"], text) for text in texts]

        # Then
        self.assertEqual([False] * 4, [item["pass"] for item in graded])
        self.assertTrue(all(item["error"] for item in graded))
        self.assertEqual([["check-outside-lock"]] * 4, [item["missed"] for item in graded])

    def test_마지막_블록만_채점한다(self):
        """답에 json 블록이 둘이면 마지막 블록의 지적만 채점한다."""
        # Given
        text = answer(("README.md:1", "x", "y")) + answer(GOOD["T89"])

        # When
        graded = mr_grading.grade(CASES["T89"], text)

        # Then
        self.assertTrue(graded["pass"])


if __name__ == "__main__":
    unittest.main()
