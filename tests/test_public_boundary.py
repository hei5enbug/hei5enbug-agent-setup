"""Public boundary checks for the protected AGENTS.md section, tracked files, and commit messages.

The repository and its full history are public. These checks pin the protected rule section and reject
local home paths, real-looking email addresses, and credential shapes in every tracked text file and every
commit message reachable from HEAD. Findings name the location and kind only, never the matched text.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".githooks"))

from public_boundary import ALLOWED_MATCHES, collect_text_files, scan_text  # noqa: E402

AGENTS = REPO_ROOT / "AGENTS.md"
SECTION_HEADING = "## Public boundary (protected)"
PROTECTED_SECTION_SHA256 = "c0106bb1988e01e7adf842bb0689f8abb9c81001a738c9f971a02d4dbc0ec99b"


def _commit_messages() -> list[tuple[str, str]]:
    shas = subprocess.run(
        ["git", "log", "--format=%H"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.split()
    messages = []
    for sha in shas:
        body = subprocess.run(
            ["git", "show", "-s", "--format=%B", sha],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        messages.append((f"commit {sha[:12]}", body))
    return messages


def protected_section(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if line == SECTION_HEADING), None)
    if start is None:
        raise AssertionError(f"AGENTS.md has no '{SECTION_HEADING}' heading")
    return "\n".join(lines[start:]).rstrip()


class ProtectedSectionTests(unittest.TestCase):
    def test_보호_구간이_마지막_제목이다(self) -> None:
        """AGENTS.md에서 보호 구간 제목이 마지막 `## ` 제목이어야 한다."""
        # given
        lines = AGENTS.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")

        # when
        headings = [line for line in lines if line.startswith("## ")]

        # then
        self.assertEqual(SECTION_HEADING, headings[-1], "the protected section must be the last '## ' heading")

    def test_보호_구간의_해시가_고정값과_같다(self) -> None:
        """보호 구간 본문의 sha256이 고정값과 같아야 한다."""
        # given
        text = AGENTS.read_text(encoding="utf-8")

        # when
        digest = hashlib.sha256(protected_section(text).encode("utf-8")).hexdigest()

        # then
        self.assertEqual(
            PROTECTED_SECTION_SHA256,
            digest,
            "The 'Public boundary (protected)' section of AGENTS.md changed. It changes only when the owner "
            "explicitly asks for that change, alone in its own commit that also updates "
            "PROTECTED_SECTION_SHA256 in this test. See the section itself.",
        )


class LeakScanTests(unittest.TestCase):
    def test_추적_파일에_비공개_값이_없다(self) -> None:
        """추적 중인 모든 텍스트 파일에 실제 홈 경로, 이메일, 자격 증명 형태가 없어야 한다."""
        # given
        files = collect_text_files(REPO_ROOT)

        # when
        findings = []
        for name, text in files:
            findings.extend(scan_text(name, text, ALLOWED_MATCHES.get(name)))

        # then
        self.assertEqual([], findings, "tracked files contain values that must not be public")

    def test_커밋_메시지에_비공개_값이_없다(self) -> None:
        """HEAD에서 닿는 모든 커밋 메시지에 실제 홈 경로, 이메일, 자격 증명 형태가 없어야 한다."""
        # given
        messages = _commit_messages()

        # when
        findings = []
        for label, text in messages:
            findings.extend(scan_text(label, text))

        # then
        self.assertEqual([], findings, "commit messages contain values that must not be public")

    def test_스캐너가_각_종류를_잡고_허용_목록을_따른다(self) -> None:
        """스캐너가 각 종류를 보고하고 가상 이름과 예시 도메인은 통과시켜야 한다."""
        # given
        flagged = "\n".join(
            [
                "/Users/" + "realname/work",
                "/home/" + "realname/work",
                "C:\\Users\\" + "realname\\work",
                "me" + "@corp.test.io",
                "-----BEGIN " + "RSA PRIVATE KEY-----",
                "AKI" + "A" + "A" * 16,
                "ghp" + "_" + "a" * 24,
                "xox" + "b-123",
            ]
        )
        clean = "/home/alice/x /Users/demo/y me@example.com me@host.example.test"

        # when
        flagged_kinds = [item.rsplit(": ", 1)[1] for item in scan_text("f", flagged)]
        clean_findings = scan_text("f", clean)

        # then
        self.assertEqual(
            [
                "home-path",
                "home-path",
                "home-path",
                "email",
                "private-key-header",
                "aws-access-key-id",
                "github-token",
                "slack-token",
            ],
            flagged_kinds,
        )
        self.assertEqual([], clean_findings)

    def test_구분자_없이_끝나는_홈_디렉터리도_잡는다(self) -> None:
        """뒤에 슬래시가 없는 홈 디렉터리도 종료 문자 앞에서 가상 이름만 허용해야 한다."""
        # given
        real = "realname"
        flagged = [
            f"cd /home/{real}",
            f"open '/Users/{real}'",
            f"path=`/Users/{real}`",
            f"(/home/{real}), next",
            f"x /home/{real}; y",
            f"x /home/{real}: y",
            f"C:\\Users\\{real}",
            f"C:\\Users\\{real} next",
            f"/home/{real}",
        ]
        clean = ["cd /home/alice", "open '/Users/demo'", "(/home/test), x", "C:\\Users\\bob", "see /home/alice" + "."]

        # when
        flagged_counts = [len(scan_text("f", line)) for line in flagged]
        clean_findings = [item for line in clean for item in scan_text("f", line)]

        # then
        self.assertEqual([1] * len(flagged), flagged_counts)
        self.assertEqual([], clean_findings)

    def test_noreply_도메인은_허용하지_않는다(self) -> None:
        """users.noreply.github.com 주소는 실제 계정을 가리키므로 이메일로 보고해야 한다."""
        # given
        text = "12345+someone" + "@users.noreply.github.com"

        # when
        findings = scan_text("f", text)

        # then
        self.assertEqual(["f:1: email"], findings)

    def test_ssh_전송_형식만_이메일_규칙에서_제외한다(self) -> None:
        """로컬 부분이 git이고 뒤에 콜론이 오는 SSH 형식만 통과시켜야 한다."""
        # given
        ssh = "git clone git@" + "corp.io:org/repo.git"
        plain = "contact git@" + "corp.io for access"
        example = "git@example.com is fine"
        other_user = "deploy@" + "corp.io:repo"

        # when
        results = [scan_text("f", line) for line in (ssh, plain, example, other_user)]

        # then
        self.assertEqual([[], ["f:1: email"], [], ["f:1: email"]], results)


class CommittedContentTests(unittest.TestCase):
    def _repo(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        return root

    def test_스테이징된_내용을_작업_사본_대신_검사한다(self) -> None:
        """스테이징한 뒤 작업 사본에서 지운 토큰도 추적 파일 내용으로 찾아야 한다."""
        # given
        root = self._repo()
        token = "ghp" + "_" + "a" * 24
        (root / "notes.txt").write_text(f"key {token}\n", encoding="utf-8")
        subprocess.run(["git", "add", "notes.txt"], cwd=root, check=True)
        (root / "notes.txt").write_text("clean\n", encoding="utf-8")

        # when
        files = dict(collect_text_files(root))

        # then
        self.assertIn(token, files["notes.txt"])

    def test_추가하지_않은_파일은_작업_사본에서_읽는다(self) -> None:
        """추적되지 않고 무시되지 않은 파일은 작업 사본 내용으로 검사해야 한다."""
        # given
        root = self._repo()
        (root / "new.txt").write_text("fresh\n", encoding="utf-8")
        (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (root / "ignored.txt").write_text("hidden\n", encoding="utf-8")

        # when
        names = sorted(name for name, _ in collect_text_files(root))

        # then
        self.assertEqual([".gitignore", "new.txt"], names)

    def test_uv_lock도_다른_텍스트_파일처럼_검사한다(self) -> None:
        """uv.lock에 든 값도 건너뛰지 않고 검사 대상에 넣어야 한다."""
        # given
        root = self._repo()
        (root / "uv.lock").write_text("owner me" + "@corp.io\n", encoding="utf-8")
        subprocess.run(["git", "add", "uv.lock"], cwd=root, check=True)

        # when
        findings = [item for name, text in collect_text_files(root) for item in scan_text(name, text)]

        # then
        self.assertEqual(["uv.lock:1: email"], findings)

    def test_바이너리_파일은_건너뛴다(self) -> None:
        """NUL 바이트가 있는 파일은 텍스트 검사에서 제외해야 한다."""
        # given
        root = self._repo()
        (root / "blob.bin").write_bytes(b"\0\1ghp_" + b"a" * 24)
        subprocess.run(["git", "add", "blob.bin"], cwd=root, check=True)

        # when
        files = collect_text_files(root)

        # then
        self.assertEqual([], files)


if __name__ == "__main__":
    unittest.main()
