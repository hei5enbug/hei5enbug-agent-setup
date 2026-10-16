from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "secret_exec.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import secret_exec  # noqa: E402

SECRET = b"p@ss/w ord+1"
FAKE_CLI = """#!{python}
import json
import sys

with open({calls!r}, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": {tool!r}, "argv": sys.argv[1:]}}) + "\\n")
sys.stdout.buffer.write({stdout!r})
sys.stderr.buffer.write({stderr!r})
sys.exit({exit_code})
"""
FORMS_CODE = (
    "import base64,os,sys,urllib.parse as u;"
    "v=os.environ['TOKEN'];"
    "sys.stdout.write(' '.join([v, base64.b64encode(v.encode()).decode(), u.quote(v), u.quote(v, safe=''), u.quote_plus(v)]))"
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_command(name: str) -> list[str]:
    code = "import hashlib,os,sys;sys.stdout.write(hashlib.sha256(os.fsencode(os.environ[sys.argv[1]])).hexdigest())"
    return [sys.executable, "-c", code, name]


def python_command(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class SecretExecTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"

    def fake(self, tool: str, *, stdout: bytes = b"", stderr: bytes = b"", exit_code: int = 0) -> None:
        path = self.bin / tool
        path.write_text(
            FAKE_CLI.format(
                python=sys.executable, calls=str(self.calls), tool=tool, stdout=stdout, stderr=stderr, exit_code=exit_code,
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def recorded(self, tool: str) -> list[list[str]]:
        if not self.calls.exists():
            return []
        records = [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]
        return [record["argv"] for record in records if record["tool"] == tool]

    def run_helper(self, *arguments: str, input: bytes | None = None, timeout: float = 60):
        environment = dict(os.environ, PATH=str(self.bin))
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            env=environment,
            timeout=timeout,
            check=False,
            **stdin,
        )


class FetchSourceTest(SecretExecTest):
    def test_k8s_source_with_context_escapes_dotted_key_and_decodes_base64(self):
        """k8s 소스는 context를 붙여 점을 이스케이프한 jsonpath로 조회하고 base64를 디코딩해 주입한다."""
        # Given
        self.fake("kubectl", stdout=base64.b64encode(SECRET))

        # When
        result = self.run_helper(
            "--secret", "DB_PASSWORD=k8s:arn:aws:eks/cluster-a/prod/app-db/db.password", "--", *digest_command("DB_PASSWORD"),
        )

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), digest(SECRET))
        self.assertEqual(
            self.recorded("kubectl"),
            [["--context", "arn:aws:eks/cluster-a", "-n", "prod", "get", "secret", "app-db",
              "-o", r"jsonpath={.data.db\.password}"]],
        )

    def test_k8s_source_without_context_omits_the_context_flag(self):
        """context를 생략한 k8s 소스는 --context 없이 namespace와 secret으로 조회한다."""
        # Given
        self.fake("kubectl", stdout=base64.b64encode(SECRET))

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=k8s:prod/app-db/password", "--", *digest_command("DB_PASSWORD"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), digest(SECRET))
        self.assertEqual(
            self.recorded("kubectl"),
            [["-n", "prod", "get", "secret", "app-db", "-o", "jsonpath={.data.password}"]],
        )

    def test_keyvault_source_removes_exactly_one_trailing_newline(self):
        """Key Vault 값은 tsv 출력의 줄바꿈 하나만 제거하고 나머지는 그대로 주입한다."""
        # Given
        self.fake("az", stdout=SECRET + b"\n\n")

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=keyvault:vault-a/db-pass", "--", *digest_command("DB_PASSWORD"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), digest(SECRET + b"\n"))
        self.assertEqual(
            self.recorded("az"),
            [["keyvault", "secret", "show", "--vault-name", "vault-a", "--name", "db-pass",
              "--query", "value", "-o", "tsv"]],
        )

    def test_aws_source_without_key_uses_secret_string_as_text(self):
        """aws 소스는 SecretString을 text 출력으로 받아 CLI가 붙인 줄바꿈 하나를 뺀 값을 주입한다."""
        # Given
        self.fake("aws", stdout=SECRET + b"\n")

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=aws:prod/app", "--", *digest_command("DB_PASSWORD"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), digest(SECRET))
        self.assertEqual(
            self.recorded("aws"),
            [["secretsmanager", "get-secret-value", "--secret-id", "prod/app",
              "--query", "SecretString", "--output", "text"]],
        )

    def test_aws_json_key_injects_only_that_string_field(self):
        """aws의 #json 키는 SecretString을 JSON으로 읽어 그 문자열 필드만 주입한다."""
        # Given
        self.fake("aws", stdout=json.dumps({"api_token": SECRET.decode(), "other": "unused"}).encode() + b"\n")

        # When
        result = self.run_helper("--secret", "API_TOKEN=aws:prod/app#api_token", "--", *digest_command("API_TOKEN"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), digest(SECRET))
        self.assertEqual(self.recorded("aws")[0][3], "prod/app")

    def test_gcp_source_without_version_reads_latest(self):
        """gcp 소스에 버전이 없으면 latest 버전을 읽는다."""
        # Given
        self.fake("gcloud", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=gcp:proj-a/db-pass", "--", *digest_command("DB_PASSWORD"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), digest(SECRET))
        self.assertEqual(
            self.recorded("gcloud"),
            [["secrets", "versions", "access", "latest", "--secret", "db-pass", "--project", "proj-a"]],
        )

    def test_gcp_source_with_version_reads_that_version(self):
        """gcp 소스에 버전이 있으면 그 버전을 명시해 읽는다."""
        # Given
        self.fake("gcloud", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=gcp:proj-a/db-pass/3", "--", *digest_command("DB_PASSWORD"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.recorded("gcloud"),
            [["secrets", "versions", "access", "3", "--secret", "db-pass", "--project", "proj-a"]],
        )

    def test_fetch_argv_passes_shell_metacharacters_as_literal_arguments(self):
        """소스의 셸 특수문자는 셸을 거치지 않고 CLI 인자로 그대로 전달된다."""
        # Given
        self.fake("az", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=keyvault:vault-a/db$(id);echo", "--", *digest_command("DB_PASSWORD"))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.recorded("az")[0][6], "db$(id);echo")

    def test_invalid_variable_name_is_a_usage_error_without_fetching(self):
        """소문자가 든 VAR 이름은 사용 오류로 종료하고 어떤 값도 조회하지 않는다."""
        # Given
        self.fake("az", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "lower=keyvault:vault-a/db-pass", "--", "true")

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.recorded("az"), [])
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_no_binding_is_a_usage_error_without_running_the_command(self):
        """--secret나 --file 없이 부르면 명령을 실행하지 않고 사용 오류로 종료한다."""
        # Given
        self.fake("kubectl", stdout="pods")

        # When
        result = self.run_helper("--", "kubectl", "get", "pods")

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.recorded("kubectl"), [])
        self.assertIn(b"--secret", result.stderr)

    def test_malformed_sources_are_usage_errors_without_fetching(self):
        """형식이 잘못된 소스는 어떤 CLI도 실행하지 않고 사용 오류로 종료한다."""
        sources = [
            "DB=unknown:x",
            "DB=keyvault:onlyvault",
            "DB=keyvault:vault/",
            "DB=k8s:prod/app-db",
            "DB=k8s:/prod/app-db/key",
            "DB=aws:#key",
            "DB=aws:prod/app#",
            "DB=gcp:proj",
            "DB=gcp:proj/name/1/extra",
            "DB=plain-value",
        ]
        for source in sources:
            with self.subTest(source=source):
                # Given
                self.fake("az", stdout=SECRET)

                # When
                result = self.run_helper("--secret", source, "--", "true")

                # Then
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(b"cannot fetch", result.stderr)
                self.assertEqual(self.recorded("az"), [])

    def test_fetch_failure_exits_2_and_never_prints_the_fetched_output(self):
        """조회 명령이 실패하면 소스와 종료 코드만 알리고 조회 출력과 값은 어디에도 나오지 않는다."""
        # Given
        marker = self.root / "command-ran"
        self.fake("kubectl", stdout=base64.b64encode(SECRET), stderr=b"denied", exit_code=1)

        # When
        result = self.run_helper(
            "--secret", "DB_PASSWORD=k8s:prod/app-db/password", "--", *python_command(f"open({str(marker)!r}, 'w').close()"),
        )

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"k8s:prod/app-db/password", result.stderr)
        self.assertIn(b"exited with code 1", result.stderr)
        self.assertNotIn(b"denied", result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertFalse(marker.exists())
        for form in (SECRET, base64.b64encode(SECRET)):
            self.assertNotIn(form, result.stdout + result.stderr)

    def test_empty_fetched_value_is_a_fetch_failure(self):
        """빈 값은 주입할 수 없으므로 조회 실패로 종료한다."""
        # Given
        self.fake("az", stdout=b"\n")

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=keyvault:vault-a/db-pass", "--", "true")

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"the value is empty", result.stderr)

    def test_invalid_base64_from_k8s_is_a_fetch_failure(self):
        """Kubernetes 값이 base64가 아니면 디코딩 실패로 종료하고 원문을 출력하지 않는다."""
        # Given
        self.fake("kubectl", stdout=b"not*base64!")

        # When
        result = self.run_helper("--secret", "DB_PASSWORD=k8s:prod/app-db/password", "--", "true")

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"not valid base64", result.stderr)
        self.assertNotIn(b"not*base64!", result.stdout + result.stderr)


class OutputMaskingTest(SecretExecTest):
    def test_raw_base64_and_url_quoted_forms_are_all_masked(self):
        """원문, base64, URL 인코딩 형태는 모두 ***로 가려진다."""
        # Given
        self.fake("az", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command(FORMS_CODE))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"*** *** *** *** ***")

    def test_stderr_of_the_child_is_masked(self):
        """자식 프로세스의 stderr에 나온 값도 같은 규칙으로 가려진다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = "import base64,os,sys;v=os.environ['TOKEN'];sys.stderr.write(v + ' ' + base64.b64encode(v.encode()).decode())"

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command(code))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"*** ***")

    def test_short_values_are_masked(self):
        """네 글자보다 짧은 값도 가려진다."""
        # Given
        self.fake("az", stdout=b"ab")
        code = "import os;print('[' + os.environ['PIN'] + ']')"

        # When
        result = self.run_helper("--secret", "PIN=keyvault:vault-a/pin", "--", *python_command(code))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"[***]\n")

    def test_value_split_across_read_chunks_is_masked(self):
        """값이 두 번의 출력 청크로 나뉘어도 전체가 가려진다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = (
            "import os,sys,time;v=os.environ['TOKEN'];"
            "sys.stdout.write('pre-' + v[:4]);sys.stdout.flush();time.sleep(0.3);"
            "sys.stdout.write(v[4:] + '-post');sys.stdout.flush()"
        )

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command(code))

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"pre-***-post")

    def test_stderr_from_a_failed_fetch_is_never_printed(self):
        """조회 실패의 stderr는 값이 섞였을 수 있으므로 출력하지 않고, 소스와 종료 코드만 알린다."""
        # Given
        self.fake("az", stdout=SECRET)
        self.fake("kubectl", stderr=b"error near " + SECRET + b" and a diagnostic", exit_code=1)

        # When
        result = self.run_helper(
            "--secret", "TOKEN=keyvault:vault-a/token", "--secret", "OTHER=k8s:prod/app-db/password", "--", "true",
        )

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"cannot fetch k8s:prod/app-db/password", result.stderr)
        self.assertIn(b"kubectl exited with code 1", result.stderr)
        self.assertNotIn(b"error near", result.stdout + result.stderr)
        self.assertNotIn(b"diagnostic", result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_mask_is_identical_for_every_chunk_split(self):
        """모든 위치에서 나눈 청크 입력이 한 번에 준 입력과 같은 결과를 낸다."""
        # Given
        value = b"s3cr3t/v al"
        text = b"a " + value + b" b " + base64.b64encode(value) + b" c " + value.replace(b" ", b"%20") + b" d"
        expected = b"a *** b *** c *** d"

        for split in range(len(text) + 1):
            with self.subTest(split=split):
                # When
                masker = secret_exec.OutputMasker([value])
                output = masker.feed(text[:split]) + masker.feed(text[split:]) + masker.finish()

                # Then
                self.assertEqual(output, expected)

    def test_overlapping_occurrences_are_all_masked(self):
        """서로 겹치는 두 번의 등장도 빠짐없이 가려져 일부가 드러나지 않는다."""
        # Given
        value = b"xyx"
        text = b"xyxyx"

        # When
        output = secret_exec.mask_bytes(text, [value])

        # Then
        self.assertEqual(output, b"***")


class FileInjectionTest(SecretExecTest):
    def test_file_is_0600_inside_a_0700_directory_and_is_removed_afterwards(self):
        """--file 값은 0600 파일로 0700 디렉터리에 쓰이고, 실행이 끝나면 디렉터리째 지워진다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = (
            "import hashlib,json,os,stat,sys;p=os.environ['CERT'];"
            "print(json.dumps({'path': p,"
            " 'file': oct(stat.S_IMODE(os.stat(p).st_mode)),"
            " 'dir': oct(stat.S_IMODE(os.stat(os.path.dirname(p)).st_mode)),"
            " 'sha': hashlib.sha256(open(p, 'rb').read()).hexdigest()}))"
        )

        # When
        result = self.run_helper("--file", "CERT=keyvault:vault-a/cert", "--", *python_command(code))

        # Then
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["file"], "0o600")
        self.assertEqual(report["dir"], "0o700")
        self.assertEqual(report["sha"], digest(SECRET))
        self.assertFalse(Path(report["path"]).parent.exists())

    def test_file_directory_is_removed_after_child_failure(self):
        """자식 프로세스가 실패해도 --file 디렉터리는 지워지고 자식의 종료 코드가 전달된다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = "import os,sys;sys.stdout.write(os.environ['CERT']);sys.exit(3)"

        # When
        result = self.run_helper("--file", "CERT=keyvault:vault-a/cert", "--", *python_command(code))

        # Then
        self.assertEqual(result.returncode, 3)
        self.assertFalse(Path(result.stdout.decode()).parent.exists())

    def test_file_directory_is_removed_when_the_helper_is_terminated(self):
        """실행 중 SIGTERM을 받으면 자식을 정리하고 --file 디렉터리를 지운 뒤 128+신호로 끝난다."""
        # Given
        self.fake("az", stdout=SECRET)
        environment = dict(os.environ, PATH=str(self.bin))
        # The masker holds back a short tail, so pad the line to let the path reach the test before the signal.
        code = (
            "import os,sys,time;sys.stdout.write(os.environ['CERT'] + '\\n' + 'x' * 64);sys.stdout.flush();time.sleep(60)"
        )
        helper = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--file", "CERT=keyvault:vault-a/cert", "--", *python_command(code)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        self.addCleanup(lambda: helper.poll() is None and helper.kill())
        path = helper.stdout.readline().decode().strip()

        # When
        helper.send_signal(signal.SIGTERM)
        helper.communicate(timeout=30)

        # Then
        self.assertEqual(helper.returncode, 143)
        self.assertFalse(Path(path).parent.exists())


class ProcessTest(SecretExecTest):
    def test_fetch_timeout_names_the_source_and_exits_two_without_exposing_output(self):
        """각 비밀 조회는 30초 제한을 적용하고 시간이 지나면 소스만 알리며 2로 종료한다."""
        # given
        source = "keyvault:vault-a/token"
        timeout = subprocess.TimeoutExpired(["az"], 30, output=SECRET, stderr=SECRET)
        # when
        with patch.object(secret_exec.subprocess, "run", side_effect=timeout) as fetch_call, \
                patch.object(secret_exec, "install_signal_handlers"), patch.object(secret_exec, "report") as report:
            result = secret_exec.main(["--secret", "TOKEN=" + source, "--", "true"])
        # then
        self.assertEqual(result, 2)
        self.assertEqual(fetch_call.call_args.kwargs["timeout"], 30)
        self.assertEqual(report.call_args.args, (f"cannot fetch {source}: az timed out",))
        self.assertNotIn(SECRET.decode(), report.call_args.args[0])

    def test_child_exit_code_is_passed_through(self):
        """자식 프로세스의 종료 코드를 그대로 반환한다."""
        # Given
        self.fake("az", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command("import sys;sys.exit(7)"))

        # Then
        self.assertEqual(result.returncode, 7)

    def test_child_killed_by_a_signal_exits_with_128_plus_the_signal(self):
        """신호로 죽은 자식은 128에 신호 번호를 더한 코드로 끝난다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = "import os,signal;os.kill(os.getpid(), signal.SIGTERM)"

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command(code))

        # Then
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)

    def test_timeout_kills_the_process_group_and_exits_124(self):
        """--timeout이 지나면 자식의 프로세스 그룹을 죽이고 124로 끝난다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "time.sleep(60)"
        )
        started = time.monotonic()

        # When
        result = self.run_helper("--timeout", "0.5", "--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command(code))

        # Then
        self.assertEqual(result.returncode, 124)
        self.assertLess(time.monotonic() - started, 30)

    def test_stdin_is_passed_through_to_the_child(self):
        """표준 입력은 자식 프로세스까지 그대로 전달된다."""
        # Given
        self.fake("az", stdout=SECRET)
        code = "import sys;sys.stdout.write(sys.stdin.read().upper())"

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", *python_command(code), input=b"hello")

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"HELLO")

    def test_missing_command_exits_127(self):
        """실행할 수 없는 명령은 127로 끝난다."""
        # Given
        self.fake("az", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "--", "no-such-command-for-secret-exec")

        # Then
        self.assertEqual(result.returncode, 127)

    def test_command_must_follow_a_divider(self):
        """-- 없이 명령을 주면 사용 오류로 종료하고 아무 CLI도 실행하지 않는다."""
        # Given
        self.fake("az", stdout=SECRET)

        # When
        result = self.run_helper("--secret", "TOKEN=keyvault:vault-a/token", "true")

        # Then
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.recorded("az"), [])


if __name__ == "__main__":
    unittest.main()
