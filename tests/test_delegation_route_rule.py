"""The Delegation rule of the session instructions follows the route record of #109, and the session file never grows."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON = REPO_ROOT / "instructions/session/common.md"
DETAIL = REPO_ROOT / "instructions/implementation-delegation.md"
RECORD = REPO_ROOT / "evals/e2e/records/109.json"

COMMON_BYTES_BEFORE = 5655
CURRENT_BULLET = (
    "- Delegate implementation that changes more than two files to the implementation worker when it has a clear scope\n"
    "  and acceptance check."
)
ROUTE_PHRASES = {
    "delegate": "to the implementation worker on both hosts",
    "main": "in the main session on both hosts",
}
DETAIL_HEADING = "## Implementation route"


def delegation_section(text: str) -> str:
    match = re.search(r"^## Delegation\n(.*?)(?=^## )", text, re.S | re.M)
    return match.group(1) if match else ""


def rule_problems(common: str, detail: str, choice: dict | None) -> list[str]:
    """What is wrong with the Delegation rule given the record's route choice: no choice keeps the current rule."""
    problems = []
    if len(common.encode("utf-8")) > COMMON_BYTES_BEFORE:
        problems.append(f"common.md is larger than the {COMMON_BYTES_BEFORE} bytes it had before")
    section = delegation_section(common)
    route = choice.get("route") if choice and choice.get("verdict") == "winner" else None
    if route is None:
        if CURRENT_BULLET not in section:
            problems.append("the Delegation rule changed although no record chose a route")
        if DETAIL_HEADING in detail:
            problems.append("implementation-delegation.md holds a route section although no record chose a route")
        return problems
    named = [name for name, phrase in ROUTE_PHRASES.items() if phrase in section]
    if named != [route]:
        problems.append(f"the Delegation rule names {named or 'no route'}, the record chose {route}")
    if DETAIL_HEADING in detail:
        added = detail.split(DETAIL_HEADING, 1)[1].split("\n## ", 1)[0]
        if ROUTE_PHRASES[route] not in added:
            problems.append(f"the route section of implementation-delegation.md does not state {route}")
    return problems


def chosen_route() -> dict | None:
    if not RECORD.is_file():
        return None
    return json.loads(RECORD.read_text(encoding="utf-8")).get("route_choice")


class DelegationRouteRuleTest(unittest.TestCase):
    def test_현재_규칙은_기록이_경로를_고르기_전에는_바뀌지_않고_사이즈도_그대로다(self):
        """given 실제 지침 파일과 기록 when 규칙을 검사하면 then 기록이 고른 경로와 어긋나는 점이 없다."""
        # given
        common = COMMON.read_text(encoding="utf-8")
        detail = DETAIL.read_text(encoding="utf-8")

        # when
        problems = rule_problems(common, detail, chosen_route())

        # then
        self.assertEqual(problems, [])

    def test_선택이_없으면_문장이_바뀌거나_세부_절이_생기면_잡아낸다(self):
        """given 선택이 없는 기록과 바뀐 위임 문장, 경로 절 when 검사하면 then 두 문제를 모두 알린다."""
        # given
        common = COMMON.read_text(encoding="utf-8").replace("when it has a clear scope", "always")
        detail = DETAIL.read_text(encoding="utf-8") + f"\n{DETAIL_HEADING}\n\nx\n"

        # when
        problems = rule_problems(common, detail, None)

        # then
        self.assertEqual(len(problems), 2)
        self.assertIn("changed although no record chose a route", problems[0])

    def test_고른_경로와_다른_경로를_말하거나_두_경로를_함께_말하면_잡아낸다(self):
        """given delegate를 고른 기록 when 규칙이 main을 말하거나 둘 다 말하면 then 어긋남을 알리고 맞게 쓰면 통과한다."""
        # given
        base = COMMON.read_text(encoding="utf-8")
        marked = base.replace("when it has a clear scope\n  and acceptance check.", f"{ROUTE_PHRASES['delegate']}.")
        wrong = base.replace("when it has a clear scope\n  and acceptance check.", f"{ROUTE_PHRASES['main']}.")
        both = base.replace("when it has a clear scope\n  and acceptance check.", f"{ROUTE_PHRASES['main']}, {ROUTE_PHRASES['delegate']}.")
        choice = {"verdict": "winner", "route": "delegate"}

        # when
        results = [rule_problems(text, "", choice) for text in (marked, wrong, both)]

        # then
        self.assertEqual(results[0], [])
        self.assertIn("the Delegation rule names ['main'], the record chose delegate", results[1])
        self.assertIn("the Delegation rule names ['delegate', 'main'], the record chose delegate", results[2])

    def test_세부는_고른_경로를_말해야_하고_common이_커지면_잡아낸다(self):
        """given delegate를 고른 기록 when 세부 절이 다른 경로를 말하거나 common.md가 커지면 then 각각 알린다."""
        # given
        marked = COMMON.read_text(encoding="utf-8").replace(
            "when it has a clear scope\n  and acceptance check.", f"{ROUTE_PHRASES['delegate']}.")
        choice = {"verdict": "winner", "route": "delegate"}
        wrong_detail = f"{DETAIL_HEADING}\n\nWork {ROUTE_PHRASES['main']}.\n"

        # when
        detail_problems = rule_problems(marked, wrong_detail, choice)
        size_problems = rule_problems(marked + "x" * COMMON_BYTES_BEFORE, "", choice)

        # then
        self.assertEqual(detail_problems, ["the route section of implementation-delegation.md does not state delegate"])
        self.assertEqual(size_problems, [f"common.md is larger than the {COMMON_BYTES_BEFORE} bytes it had before"])


if __name__ == "__main__":
    unittest.main()
