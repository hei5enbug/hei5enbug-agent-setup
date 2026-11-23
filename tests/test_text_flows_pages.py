"""Offline tests of the text flow comparison pages: neutral labels, a separate key file, and the form summary."""
import json
import re
import subprocess
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
    relative = tf_pages.ALL_KINDS[task][1]
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

    def test_글은_고정_버전_마크다운_렌더러로_그리고_원문은_마크다운_블록에_둔다(self):
        root, out, made = self.build()
        text = (out / made["pages"][0]).read_text(encoding="utf-8")
        self.assertIn("https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js", text)
        self.assertIn("gfm: true, breaks: true", text)
        blocks = re.findall(r'<script type="text/markdown">(.*?)</script>', text, flags=re.DOTALL)
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(" text from " in block for block in blocks))

    def test_마크다운_원문의_스크립트_종료_표기는_블록을_닫지_않도록_보호된다(self):
        text = tf_pages.page("T13", {"A": "x </script><script>alert(1)</script> <!-- y", "B": "plain"})
        blocks = re.findall(r'<script type="text/markdown">(.*?)</script>', text, flags=re.DOTALL)
        self.assertEqual(len(blocks), 2)
        self.assertIn("<\\/script>", blocks[0])
        self.assertEqual(text.count("</script>"), 4)
        self.assertIn("replace(/<\\\\\\/script/gi", text)

    def test_렌더러를_못_불러오면_일반_텍스트가_그대로_남고_원문_HTML은_이스케이프된다(self):
        text = tf_pages.page("T13", {"A": "<b>bold</b> & more", "B": "plain"})
        self.assertIn('<pre class="plain">&lt;b&gt;bold&lt;/b&gt; &amp; more</pre>', text)
        self.assertIn("if (!window.marked) return;", text)
        self.assertIn("renderer: { html: escapeHtml }", text)

    def test_페이지는_테마_토큰과_다크_모드와_폰_너비를_갖추고_답변_버튼은_한_줄을_낸다(self):
        text = tf_pages.page("T13", {"A": "a", "B": "b"})
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', text)
        self.assertIn("@media (prefers-color-scheme: dark)", text)
        self.assertIn('[data-theme="dark"]', text)
        self.assertIn("var(--bg)", text)
        self.assertIn("overflow-x:auto", text)
        self.assertIn(">Show my answer</button>", text)
        self.assertNotIn("Show my ranking", text)
        self.assertIn("'T13 ' + rows.join(' ')", text)

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

    def test_tasks_옵션은_추가_글쓰기_과제의_페이지를_만들고_커밋_메시지는_저장소_마지막_커밋에서_읽는다(self):
        """T13 T15 T20 밖의 글쓰기 과제를 비교하지 못하면 묶음 전체의 글 품질을 눈으로 가릴 수 없으므로, 파일 과제와 커밋 과제 모두 페이지가 생긴다."""
        # given
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "runs", Path(tmp.name) / "out"
        for flow, (variant, host) in FLOWS.items():
            seed_run(root, "T14", variant, host, f"reply from {flow}")
            directory = tf_pages.run_dir(root, "p3", "T17", variant, host)
            (directory / "grade").mkdir(parents=True)
            repo = tf_pages.work_repo(root, "p3", "T17", variant, host)
            repo.mkdir(parents=True)
            for command in (["init", "-q"], ["-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-q", "--allow-empty", "-m", f"subject from {flow}"]):
                subprocess.run(["git", "-C", str(repo), *command], check=True, capture_output=True)
        # when
        made = tf_pages.build(root, "p3", FLOWS, out, tasks=("T14", "T17"))
        # then
        self.assertEqual(made["pages"], ["t14-ranking.html", "t17-ranking.html"])
        self.assertIn("subject from F1", (out / "t17-ranking.html").read_text(encoding="utf-8"))

    def test_T23과_T24의_수정_초안도_tasks_옵션으로_페이지가_생긴다(self):
        """T23과 T24의 수정 초안을 비교 대상으로 등록하지 않으면 #81의 세 과제 중 둘을 눈으로 가릴 수 없으므로, 두 과제 모두 페이지가 생기고 두 번째 초안 파일을 읽는다."""
        # given
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "runs", Path(tmp.name) / "out"
        for task in ("T23", "T24"):
            for flow, (variant, host) in FLOWS.items():
                seed_run(root, task, variant, host, f"{task} draft from {flow}")
        # when
        made = tf_pages.build(root, "p3", FLOWS, out, tasks=("T23", "T24"))
        # then
        self.assertEqual(made["pages"], ["t23-ranking.html", "t24-ranking.html"])
        self.assertIn("T24 draft from F3", (out / "t24-ranking.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
