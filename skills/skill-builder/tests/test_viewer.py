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
