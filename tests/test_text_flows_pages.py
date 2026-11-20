"""Offline tests of the text flow comparison pages: neutral labels, a separate key file, and the form summary."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "text-flows"))

import tf_pages  # noqa: E402

FLOWS = {"F1": ("f1", "claude"), "F2": ("f2", "claude"), "F3": ("f3", "codex")}


def seed_run(root: Path, task: str, variant: str, host: str, text: str, form_ok=True, review_ok=False):
    directory = tf_pages.run_dir(root, "p3", task, variant, host)
    (directory / "grade").mkdir(parents=True)
    checks = [{"id": "output-exists", "required": True, "passed": form_ok}, {"id": "text-review-clean", "required": True, "passed": review_ok},
              {"id": "ran-text-review", "required": False, "passed": True}]
    (directory / "grade" / "grade.json").write_text(json.dumps({"checks": checks}), encoding="utf-8")
    (directory / "metrics.json").write_text(json.dumps({"status": "complete", "wall_seconds": 12, "cost": {
        "claude_list_cost_usd": 0.5, "claude_runner_list_cost_usd": 0.1, "codex_list_cost_usd_estimate": 0.2}}), encoding="utf-8")
    (directory / "view.json").write_text(json.dumps({"final_answer": text}), encoding="utf-8")
    repo = tf_pages.work_repo(root, "p3", task, variant, host)
    relative = tf_pages.KINDS[task][1]
    if relative:
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(text, encoding="utf-8")


class PagesTest(unittest.TestCase):
    def build(self, form_ok=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "runs", Path(tmp.name) / "out"
        for task in tf_pages.KINDS:
            for flow, (variant, host) in FLOWS.items():
                seed_run(root, task, variant, host, f"{task} text from {flow}", form_ok=form_ok or flow != "F2")
        return root, out, tf_pages.build(root, "p3", FLOWS, out)

    def test_페이지는_중립_라벨만_쓰고_흐름_이름이나_변형_이름을_담지_않는다(self):
        root, out, made = self.build()
        for name in made["pages"]:
            text = (out / name).read_text(encoding="utf-8")
            for secret in ("F1", "F2", "F3", "f1", "f2", "f3", "claude", "codex"):
                self.assertNotIn(f">{secret}<", text)
            self.assertIn("Text A", text)
        self.assertEqual(len(made["pages"]), 3)

    def test_키_파일은_라벨을_흐름에_연결하고_종류마다_순서가_다를_수_있다(self):
        root, out, _ = self.build()
        key = json.loads((out / "key.json").read_text(encoding="utf-8"))
        for task, labels in key.items():
            self.assertEqual(sorted(labels.values()), ["F1", "F2", "F3"])
        self.assertEqual(json.loads((out / "key.json").read_text()), key)

    def test_같은_시드는_같은_순서를_낸다(self):
        self.assertEqual(tf_pages.labels_for("T13", ["F1", "F2", "F3"], "s"), tf_pages.labels_for("T13", ["F3", "F1", "F2"], "s"))

    def test_형식_검사는_모델_검토_두_검사를_빼고_필수_검사만_센다(self):
        root, out, _ = self.build(form_ok=False)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertFalse(summary["T13"]["F2"]["form_pass"])
        self.assertEqual(summary["T13"]["F2"]["form_failed"], ["output-exists"])
        self.assertTrue(summary["T13"]["F1"]["form_pass"])
        self.assertFalse(summary["T13"]["F1"]["model_review_clean"])
        self.assertAlmostEqual(summary["T13"]["F1"]["cost_usd"], 0.8)

    def test_글이_없으면_그_종류_페이지는_만들지_않는다(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "runs", Path(tmp.name) / "out"
        seed_run(root, "T13", "f1", "claude", "only one")
        made = tf_pages.build(root, "p3", FLOWS, out)
        self.assertEqual(made["pages"], [])

    def test_흐름_인자는_형식을_검사한다(self):
        self.assertEqual(tf_pages.parse_flows("F1=f1:claude,F3=f3:codex"), {"F1": ("f1", "claude"), "F3": ("f3", "codex")})
        with self.assertRaises(ValueError):
            tf_pages.parse_flows("F1=f1")


if __name__ == "__main__":
    unittest.main()
