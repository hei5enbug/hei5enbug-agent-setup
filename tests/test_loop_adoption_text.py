"""The text of each candidate loop shape of issue 102 is in the repository exactly when the record of issue 102 adopts it."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import loop_decision  # noqa: E402

RECORD = REPO_ROOT / "evals/e2e/records/102.json"
CANDIDATE = REPO_ROOT / "evals/e2e/candidates/102/apply.py"
SCRIPT, RULES = "scripts/text_review.py", "instructions/shared-text.md"


def candidate_module():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("candidate_102_apply", CANDIDATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def present(root: Path) -> set[str]:
    """The candidates whose whole text, in every file it changes, a checkout holds."""
    module = candidate_module()
    texts = {SCRIPT: (root / SCRIPT).read_text(encoding="utf-8"), RULES: (root / RULES).read_text(encoding="utf-8")}
    found = set()
    for name in module.CANDIDATES:
        edits = module.edits_for([name])
        if edits and all(replacement in texts[relative] for relative, items in edits for _, replacement in items):
            found.add(name)
    return found


def adopted(record: dict | None) -> set[str]:
    return set(loop_decision.adopted_candidates((record or {}).get("decisions") or []))


class AdoptionTextTest(unittest.TestCase):
    def test_저장소의_후보_문구는_기록이_채택한_후보와_정확히_같다(self):
        """records/102.json이 채택한 후보의 문구만 저장소에 있고, 기록이 없으면 어느 후보의 문구도 없다."""
        # given
        record = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.is_file() else None

        # when
        in_repository = present(REPO_ROOT)

        # then
        self.assertEqual(in_repository, adopted(record))


class CheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.checkout = Path(self._temp.name)
        for relative in (SCRIPT, RULES):
            (self.checkout / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO_ROOT / relative, self.checkout / relative)

    def test_검사는_후보를_적용한_사본에서만_그_후보를_찾고_일부만_적용된_후보는_찾지_않는다(self):
        """a는 규칙 문서에만, b는 스크립트에만, c는 둘 다에 문구가 있어야 찾으며, c의 규칙 문장만 있고 스크립트 변경이 없으면 찾지 않는다."""
        # given
        module = candidate_module()
        before = present(self.checkout)

        # when
        module.main([str(self.checkout), "--candidate", "a+c"])
        both = present(self.checkout)
        script = (self.checkout / SCRIPT).read_text(encoding="utf-8")
        (self.checkout / SCRIPT).write_text(script.replace("trim = load_trim(args.history, draft)\n", ""), encoding="utf-8")
        half = present(self.checkout)

        # then
        self.assertEqual((before, both, half), (set(), {"a", "c"}, {"a"}))

    def test_기록이_후보를_채택하지_않으면_그_후보의_문구가_있는_저장소를_불일치로_본다(self):
        """b를 적용한 사본이 b를 채택하지 않은 기록과 어긋나는 것을 같은 비교로 잡고, 채택한 기록과는 맞는다."""
        # given
        module = candidate_module()
        module.main([str(self.checkout), "--candidate", "b"])
        none = {"decisions": [{"candidate": "b", "verdict": "rejected", "step": "x"}]}
        taken = {"decisions": [{"candidate": "b", "verdict": "adopted", "step": "x"}]}

        # when
        found = present(self.checkout)

        # then
        self.assertNotEqual(found, adopted(none))
        self.assertEqual(found, adopted(taken))


if __name__ == "__main__":
    unittest.main()
