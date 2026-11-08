import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "writing-surfaces.json"
TASKS = ROOT / "evals" / "e2e" / "tasks"


def load_text_review():
    spec = importlib.util.spec_from_file_location("text_review", ROOT / "scripts" / "text_review.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WritingSurfacesTest(unittest.TestCase):
    def setUp(self):
        self.kinds = json.loads(REGISTRY.read_text(encoding="utf-8"))["kinds"]

    def test_목록의_글_종류는_검토_스크립트가_받는_종류와_같다(self):
        """검토 스크립트에 글 종류를 더하거나 빼면 목록과 평가 작업도 함께 맞춰야 하므로, other를 뺀 두 집합이 같다."""
        # given
        reviewed = set(load_text_review().KINDS) - {"other"}

        # when
        listed = set(self.kinds)

        # then
        self.assertEqual(reviewed, listed)

    def test_목록이_가리키는_규칙과_작성_파일은_모두_있다(self):
        """이름이 바뀌거나 지워진 스킬이나 지침이 목록에 남으면 그 글의 규칙을 바꿀 때 평가를 놓치므로, 모든 경로가 있어야 한다."""
        # given
        paths = {path for entry in self.kinds.values() for path in [*entry["rules"], *entry["writers"]]}

        # when
        missing = sorted(path for path in paths if not (ROOT / path).is_file())

        # then
        self.assertEqual([], missing)

    def test_글_종류마다_독립_검토를_필수로_통과해야_하는_평가_작업이_있다(self):
        """평가 작업이 사라지거나 text-review-clean 검사를 잃으면 규칙 변경을 검증할 수 없으므로, 종류마다 그 필수 검사가 있다."""
        # given
        tasks = {kind: TASKS / f"{entry['eval_task']}.json" for kind, entry in self.kinds.items()}

        # when
        gaps = []
        for kind, path in tasks.items():
            checks = json.loads(path.read_text(encoding="utf-8"))["checks"] if path.is_file() else []
            if not any(check.get("id") == "text-review-clean" and check.get("required") for check in checks):
                gaps.append(kind)

        # then
        self.assertEqual([], gaps)


if __name__ == "__main__":
    unittest.main()
