"""Tests for the seeded cases of the Fable-versus-Opus comparison: their data, seeding, and deterministic grading."""

from __future__ import annotations

import json
import re
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

GOOD_KO = {
    "T89": ("seatmap/seats.py:25", "hold_many가 점유 검사와 정원 검사를 lock을 잡기 전에 해서 검사와 쓰기 사이에 경쟁 상태가 생긴다",
            "두 스레드가 동시에 호출하면 둘 다 통과해 같은 좌석을 덮어쓰거나 정원을 초과한다"),
    "T90": ("pricing/api.py:17", "공개 계약인 문서화된 필드 total_cents를 제거하고 total로 바꿨다",
            "reports/export.py가 KeyError로 실패하고 필드를 파싱하는 클라이언트가 깨진다"),
    "T91": ("issue.md:16", "제안 2의 만료 15분은 완료 기준 2의 30초와 충돌한다",
            "바뀐 가격이 최대 15분 동안 반영되지 않아 기준 2를 충족할 수 없다"),
    "T92": ("design.md:14", "재시도마다 X-Delivery-Id를 새로 생성해서 구독자가 중복을 걸러낼 수 없다",
            "처리 뒤 시간 초과가 나면 같은 이벤트가 두 번 처리되어 영수증 메일이 중복 발송된다"),
    "T93": ("design.md:12", "acme-trading이 전체 쓰기의 41퍼센트라서 hash(customer_id) % 8이 한 샤드에 쏠림을 만든다",
            "그 샤드는 초당 492건을 받아 primary가 버티는 400건을 초과한다"),
}

NON_PLANTED = {
    "tests-lack-concurrent-case": ("tests/test_seats.py:25", "the hold_many tests only run from one thread in sequence and none is concurrent",
                                   "the race passes the suite because the multi-threaded use is never tested"),
    "export-test-fails-unrun": ("tests/test_export.py:5", "this consumer test fails with KeyError after the change",
                                "the author ran only tests/test_api.py, so the failing regression was not caught"),
    "format-amount-negative": ("pricing/api.py:8", "format_amount floors with // and %, so a negative amount is wrong",
                               "-5 cents becomes -1.95 instead of -0.05"),
    "invalidate-yet-stale": ("issue.md:9", "invalidate(sku) runs after every change yet prices stay stale for up to one minute",
                             "the cause is not explained, so nobody knows whether to fix or remove the call"),
    "peak-load-undefined": ("issue.md:22", "'At peak load' has no definition of the peak or how it is measured",
                            "nobody can reproduce or judge whether criterion 1 passes"),
    "unhandled-responses": ("design.md:13", "a 4xx such as 429, a 3xx, or a non-200 2xx response is not defined",
                            "those deliveries are dropped silently without a retry or an alert"),
    "alert-per-delivery": ("design.md:16", "an alert is raised for every failed delivery",
                           "one long outage floods the operators with one alert per event"),
    "delivery-state-unspecified": ("design.md:12", "the delivery state, the next attempt time, and the worker are not defined",
                                   "pending retries are lost on a restart and several instances send duplicates"),
    "replay-id-and-state": ("design.md:17", "replay and the 'exactly as stored' criterion leave open which X-Delivery-Id is used",
                            "a replayed delivery that was already processed repeats the event twice"),
    "ac1-checks-arrival-only": ("design.md:21", "acceptance criterion 1 only checks that every event arrives",
                                "an implementation that sends the same event six times still passes"),
    "ac1-ac2-conflict": ("design.md:21", "acceptance criterion 2 conflicts with criterion 1 for the largest customer",
                         "no placement meets both criteria"),
    "copy-plan-underspecified": ("design.md:16", "the one-time copy has no write freeze, cutover order, or rollback",
                                 "orders written during the copy can be lost or duplicated"),
    "ac3-checks-exactly-one-shard": ("design.md:22", "criterion 3 only requires exactly one shard, not the correct shard",
                                     "a misplaced order passes and is missing from the customer's page"),
    "no-resize-or-exception-path": ("design.md:12", "there is no resize procedure or exception for the fixed hash",
                                    "changing the shard count remaps most customers and needs a full copy"),
    "queries-beyond-list-my-orders": ("design.md:13", "only the list my orders query is covered, not a lookup by order id",
                                      "such a lookup has no defined route and must query all 8 shards"),
}

OPINION_AT_UNLISTED_LINE = {
    "T89": "seatmap/seats.py:42", "T90": "pricing/api.py:3", "T91": "issue.md:4",
    "T92": "design.md:6", "T93": "design.md:5",
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
                self.assertEqual((True, None, 1, [], []), (graded["pass"], graded["error"], graded["findings"], graded["missed"], graded["outside"]))
                self.assertIn(mr_grading.planted(CASES[case_id])[0], graded["found"])

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

    def test_한국어로_쓴_지적도_심은_문제를_위치와_효과로_짚으면_통과한다(self):
        """실행기가 사용자의 언어를 따르므로, 한국어 지적이 심은 문제의 위치에서 문제와 효과를 말하면 사례마다 통과한다."""
        for case_id, finding in GOOD_KO.items():
            with self.subTest(case=case_id):
                # When
                graded = mr_grading.grade(CASES[case_id], answer(finding))

                # Then
                self.assertEqual((True, [], []), (graded["pass"], graded["missed"], graded["outside"]))
                self.assertIn(mr_grading.planted(CASES[case_id])[0], graded["found"])

    def test_모든_목록_문제는_한국어_키워드를_함께_갖는다(self):
        """심은 문제와 심지 않은 실제 문제 모두 문제 키워드와 효과 키워드에 한글 대안이 하나 이상 있다."""
        hangul = re.compile("[가-힣]")
        for case_id, case in CASES.items():
            for problem in case["problems"]:
                with self.subTest(case=case_id, problem=problem["id"]):
                    self.assertTrue(any(hangul.search(item) for item in problem["problem_any"]))
                    self.assertTrue(any(hangul.search(item) for item in problem["effect_any"]))

    def test_심지_않은_실제_문제를_짚은_지적은_그_문제와_맞고_목록_밖이_아니다(self):
        """목록에 더한 실제 문제 각각은 자기 위치의 지적과 맞고, 그 지적만 있는 답에서 outside가 비며 심은 문제는 missed에 남는다."""
        listed = {problem["id"]: case_id for case_id, case in CASES.items() for problem in case["problems"] if not problem["planted"]}
        self.assertEqual(set(listed), set(NON_PLANTED))
        for problem_id, case_id in listed.items():
            with self.subTest(problem=problem_id):
                # When
                graded = mr_grading.grade(CASES[case_id], answer(NON_PLANTED[problem_id]))

                # Then
                self.assertIn(problem_id, graded["found"])
                self.assertEqual([], graded["outside"])
                self.assertEqual(mr_grading.planted(CASES[case_id]), graded["missed"])

    def test_목록에_없는_줄의_의견은_사례마다_계속_목록_밖이다(self):
        """심은 문제를 짚은 답에 목록에 없는 줄의 의견 하나를 더하면 그 의견은 outside에 남고 사례는 실패한다."""
        for case_id, place in OPINION_AT_UNLISTED_LINE.items():
            with self.subTest(case=case_id):
                # Given
                opinion = (place, "the rationale for this choice is missing and a measurement would help", "readers cannot judge the benefit")

                # When
                graded = mr_grading.grade(CASES[case_id], answer(GOOD[case_id], opinion))

                # Then
                self.assertEqual((False, [{"index": 1, "location": place}]), (graded["pass"], graded["outside"]))


if __name__ == "__main__":
    unittest.main()
