"""Eval viewer: HTML escaping, port fallback, and feedback save behavior."""

from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "eval-viewer" / "generate_review.py"
SPEC = importlib.util.spec_from_file_location("generate_review", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VIEWER_HTML = (SKILL_DIR / "eval-viewer" / "viewer.html").read_text()
SCRIPT_INJECTION = '</script><script>window.__plan_probe=true</script>'


def make_workspace(root: Path) -> Path:
    workspace = root / "demo-workspace"
    run_dir = workspace / "eval-1" / "with_skill" / "run-1"
    (run_dir / "outputs").mkdir(parents=True)
    (run_dir / "outputs" / "answer.txt").write_text("hello")
    (run_dir / "eval_metadata.json").write_text(json.dumps({"eval_id": 1, "prompt": "p"}))
    return workspace


class GenerateHtmlTest(unittest.TestCase):
    def test_runs_with_missing_metadata_are_sorted(self):
        """메타데이터가 없는 결과도 다른 실행 결과와 함께 표시한다."""
        # Given
        with tempfile.TemporaryDirectory() as td:
            workspace = make_workspace(Path(td))
            (workspace / "ungraded" / "outputs").mkdir(parents=True)
            # When
            runs = MODULE.find_runs(workspace)
            # Then
            self.assertEqual([run["eval_id"] for run in runs], [1, None])

    def test_repeated_runs_inherit_eval_metadata(self):
        """반복 실행은 평가 폴더의 메타데이터를 찾는다."""
        # Given
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eval_dir = root / "eval-2"
            (eval_dir / "with_skill" / "run-1" / "outputs").mkdir(parents=True)
            (eval_dir / "eval_metadata.json").write_text(json.dumps({"eval_id": 2, "prompt": "inherited"}))
            # When
            runs = MODULE.find_runs(root)
            # Then
            self.assertEqual(runs[0]["eval_id"], 2)
            self.assertEqual(runs[0]["prompt"], "inherited")

    def test_symlinked_outputs_are_not_embedded(self):
        """외부 파일 링크와 순환 폴더 링크는 보고서에 포함하지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as td:
            workspace = make_workspace(Path(td))
            external = Path(td) / "outside.txt"
            external.write_text("outside sentinel")
            outputs = workspace / "eval-1" / "with_skill" / "run-1" / "outputs"
            (outputs / "external.txt").symlink_to(external)
            (workspace / "cycle").symlink_to(workspace, target_is_directory=True)
            # When
            runs = MODULE.find_runs(workspace)
            # Then
            self.assertEqual(len(runs), 1)
            self.assertNotIn("outside sentinel", json.dumps(runs))

    def test_closing_script_tag_in_data_cannot_break_out(self):
        runs = [{"id": "r", "prompt": SCRIPT_INJECTION, "outputs": []}]
        html = MODULE.generate_html(runs, "demo")

        self.assertNotIn(SCRIPT_INJECTION, html)
        self.assertIn("\\u003c/script>", html)
        self.assertEqual(html.count("<script"), VIEWER_HTML.count("<script"))
        embedded = html[html.index("const EMBEDDED_DATA = ") + len("const EMBEDDED_DATA = "):]
        embedded = embedded[: embedded.index(";\n")]
        self.assertEqual(json.loads(embedded)["runs"][0]["prompt"], SCRIPT_INJECTION)


class PortHandlingTest(unittest.TestCase):
    def test_kill_port_is_gone(self):
        self.assertFalse(hasattr(MODULE, "_kill_port"))

    def test_busy_port_falls_back_without_touching_owner(self):
        occupant = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupant.bind(("127.0.0.1", 0))
        occupant.listen(1)
        busy_port = occupant.getsockname()[1]
        try:
            server, fell_back = MODULE.create_server(MODULE.ReviewHandler, busy_port)
            try:
                self.assertTrue(fell_back)
                self.assertNotEqual(server.server_address[1], busy_port)
                probe = socket.create_connection(("127.0.0.1", busy_port), timeout=2)
                probe.close()
            finally:
                server.server_close()
        finally:
            occupant.close()


class FeedbackServerTest(unittest.TestCase):
    def test_cross_origin_feedback_is_rejected(self):
        """외부 페이지에서 보낸 피드백 저장 요청은 거부한다."""
        # Given
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        # When
        conn.request("POST", "/api/feedback", body=b'{"reviews": []}', headers={
            "Origin": "https://outside.example", "Content-Type": "application/json",
        })
        response = conn.getresponse()
        # Then
        self.assertEqual(response.status, 403)
        self.assertFalse(self.feedback_path.exists())

    def test_wrong_host_cannot_read_feedback(self):
        """다른 호스트 이름을 사용한 요청에 평가 결과를 반환하지 않는다."""
        # Given
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        # When
        conn.request("GET", "/api/feedback", headers={"Host": "outside.example"})
        response = conn.getresponse()
        # Then
        self.assertEqual(response.status, 403)

    def test_negative_body_length_is_rejected_without_waiting(self):
        """음수 본문 길이는 입력을 무한히 기다리지 않고 거부한다."""
        # Given
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1)
        self.addCleanup(conn.close)
        # When
        conn.request("POST", "/api/feedback", headers={
            "Content-Type": "application/json", "Content-Length": "-1",
        })
        try:
            response = conn.getresponse()
        finally:
            conn.close()
        # Then
        self.assertEqual(response.status, 400)
        self.assertFalse(self.feedback_path.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = make_workspace(self.root)
        self.feedback_path = self.workspace / "feedback.json"
        handler = partial(MODULE.ReviewHandler, self.workspace, "demo", self.feedback_path, {}, None)
        self.server, _ = MODULE.create_server(handler, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def post(self, body: bytes, host: str | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if host is not None:
            headers["Host"] = host
        conn.request("POST", "/api/feedback", body=body, headers=headers)
        resp = conn.getresponse()
        payload = json.loads(resp.read() or b"{}")
        conn.close()
        return resp.status, payload

    def test_valid_post_saves_atomically(self):
        status, payload = self.post(json.dumps({"reviews": [{"run_id": "r", "feedback": "ok"}]}).encode())
        self.assertEqual(status, 200)
        self.assertIs(payload["ok"], True)
        self.assertEqual(json.loads(self.feedback_path.read_text())["reviews"][0]["feedback"], "ok")
        self.assertEqual([p.name for p in self.workspace.glob(".feedback-*")], [])

    def test_wrong_host_is_rejected(self):
        status, payload = self.post(b'{"reviews": []}', host="evil.example:80")
        self.assertEqual(status, 403)
        self.assertIs(payload["ok"], False)
        self.assertFalse(self.feedback_path.exists())

    def test_localhost_host_is_accepted(self):
        status, _ = self.post(b'{"reviews": []}', host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_invalid_json_is_rejected(self):
        status, payload = self.post(b"{not json")
        self.assertEqual(status, 400)
        self.assertIs(payload["ok"], False)
        self.assertFalse(self.feedback_path.exists())

    def test_missing_reviews_key_is_rejected(self):
        status, _ = self.post(b'{"other": 1}')
        self.assertEqual(status, 400)
        self.assertFalse(self.feedback_path.exists())

    def test_write_failure_reports_500_and_keeps_old_file(self):
        self.feedback_path.write_text('{"reviews": [{"run_id": "r", "feedback": "old"}]}\n')
        with patch.object(MODULE, "write_feedback", side_effect=OSError("disk full")):
            status, payload = self.post(b'{"reviews": []}')
        self.assertEqual(status, 500)
        self.assertIs(payload["ok"], False)
        self.assertIn("disk full", payload["error"])
        self.assertEqual(json.loads(self.feedback_path.read_text())["reviews"][0]["feedback"], "old")


class WriteFeedbackTest(unittest.TestCase):
    def test_failed_write_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "feedback.json"
            with patch.object(MODULE.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    MODULE.write_feedback(target, {"reviews": []})
            self.assertEqual(list(Path(td).iterdir()), [])


class ViewerTemplateTest(unittest.TestCase):
    def test_restore_is_not_gated_on_previous_iteration(self):
        self.assertNotIn("hasPrevious", VIEWER_HTML)

    def test_saved_requires_ok_response(self):
        self.assertIn("resp.ok && body && body.ok === true", VIEWER_HTML)
        self.assertIn("if (result.ok) {", VIEWER_HTML)

    def test_complete_submission_cancels_and_waits_for_auto_save(self):
        self.assertEqual(VIEWER_HTML.count("let saveTimeout = null;"), 1)
        submit = VIEWER_HTML.split("async function showDoneDialog()", 1)[1]
        submit = submit.split("function closeDoneDialog()", 1)[0]
        self.assertIn("clearTimeout(saveTimeout);", submit)
        self.assertIn("await saveQueue", submit)

    def test_closing_complete_dialog_does_not_reopen_review(self):
        close = VIEWER_HTML.split("function closeDoneDialog()", 1)[1]
        close = close.split("// ---- Toast", 1)[0]
        self.assertNotIn("saveCurrentFeedback", close)


if __name__ == "__main__":
    unittest.main()
