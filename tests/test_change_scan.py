"""Tests for the script that lists what a change did to the contracts, literals, and failure handlers of its Python code."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = REPO_ROOT / "evals/e2e/candidates/93/change_scan.py"
INSTALLED = REPO_ROOT / "scripts/change_scan.py"
SCRIPT = INSTALLED if INSTALLED.is_file() else CANDIDATE
GIT_ENV = {
    **os.environ, "GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Demo Dev", "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
BASE_FILES = {
    "shop/lookup.py": 'def find(conn, key):\n    """Find a row."""\n    return (conn[key], 1)\n\n\ndef other(conn):\n    return conn\n',
    "shop/billing.py": "from .lookup import find\n\n\ndef label(conn, key):\n    name, _ = find(conn, key)\n    return name\n",
    "shop/report.py": 'RATE = 0.0725\n\n\ndef tax(amount):\n    try:\n        return amount * RATE\n    except TypeError:\n        raise\n',
    "tests/test_lookup.py": "from shop.lookup import find\n\n\ndef test_find():\n    assert find({'a': 1}, 'a') == (1, 1)\n",
}


def load_script():
    spec = importlib.util.spec_from_file_location("change_scan_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout


class ChangeScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.repo = Path(self._temp.name)
        self.script = load_script()
        git(self.repo, "init", "-q", "-b", "main")
        self.write(BASE_FILES)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD").strip()

    def write(self, files: dict[str, str]) -> None:
        for relative, text in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def scan(self) -> dict:
        return self.script.scan(self.repo, self.base)

    def test_바뀐_반환_계약은_변경이_건드리지_않은_파일의_호출자와_함께_나열한다(self):
        """given find의 반환 값을 튜플에서 사전으로 바꾸고 billing은 건드리지 않은 변경 when 스캔하면 then find 계약이 billing 호출자와 함께 나온다."""
        # given
        self.write({"shop/lookup.py": 'def find(conn, key):\n    """Find a row."""\n    return {"name": conn[key]}\n\n\ndef other(conn):\n    return conn\n'})

        # when
        found = self.scan()["contracts"]

        # then
        self.assertEqual([item["definition"] for item in found], ["shop/lookup.py:find"])
        self.assertEqual(found[0]["kind"], "changed")
        self.assertIn("shop/billing.py:1", found[0]["callers"])
        self.assertIn("shop/billing.py:5", found[0]["callers"])

    def test_호출자도_함께_고친_파일은_호출자로_나열하지_않는다(self):
        """given billing도 함께 고친 변경 when 스캔하면 then 계약은 나오지만 billing은 호출자 목록에 없다."""
        # given
        self.write({"shop/lookup.py": "def find(conn, key):\n    return conn[key]\n\n\ndef other(conn):\n    return conn\n",
                    "shop/billing.py": "from .lookup import find\n\n\ndef label(conn, key):\n    return find(conn, key)\n"})

        # when
        found = {item["definition"]: item for item in self.scan()["contracts"]}

        # then
        self.assertEqual(sorted(found), ["shop/billing.py:label", "shop/lookup.py:find"])
        self.assertEqual([caller for caller in found["shop/lookup.py:find"]["callers"] if caller.startswith("shop/billing.py")], [])

    def test_삭제한_정의는_삭제됨으로_나열하고_본문만_바꾼_정의는_나열하지_않는다(self):
        """given other를 지우고 find의 본문 주석만 바꾼 변경 when 스캔하면 then other만 removed로 나온다."""
        # given
        self.write({"shop/lookup.py": 'def find(conn, key):\n    """Find a row by key."""\n    return (conn[key], 1)\n'})

        # when
        found = self.scan()["contracts"]

        # then
        self.assertEqual([(item["definition"], item["kind"]) for item in found], [("shop/lookup.py:other", "removed")])

    def test_다른_파일에도_있는_리터럴을_더하면_두_곳을_함께_나열한다(self):
        """given 같은 세금률 0.0725를 새 파일에 다시 적은 변경 when 스캔하면 then 리터럴이 두 자리와 함께 나온다."""
        # given
        self.write({"shop/statement.py": "def total(amount):\n    return amount * 1.0725 - amount * 0.0725 + amount * 0.0725\n"})

        # when
        found = self.scan()["literals"]

        # then
        self.assertEqual([(item["added_in"], item["literal"]) for item in found], [("shop/statement.py", 0.0725)])
        self.assertIn("shop/report.py:1", found[0]["also_at"])

    def test_이미_있던_리터럴과_작은_정수와_독스트링은_나열하지_않는다(self):
        """given 기존 리터럴을 그대로 두고 작은 정수, 짧은 문자열, 독스트링만 더한 변경 when 스캔하면 then 리터럴 목록은 비어 있다."""
        # given
        self.write({"shop/report.py": 'RATE = 0.0725\n\n\ndef tax(amount):\n    """Tax of an amount."""\n    try:\n        return amount * RATE + 3\n    except TypeError:\n        raise\n',
                    "shop/other.py": 'def go():\n    """Tax of an amount."""\n    return "ab" + "x y z w"\n'})

        # when
        found = self.scan()["literals"]

        # then
        self.assertEqual(found, [])

    def test_다시_던지지도_보고하지도_않는_새_처리기만_나열한다(self):
        """given 상수만 돌려주는 처리기, 다시 던지는 처리기, 메시지를 만드는 처리기를 더한 변경 when 스캔하면 then 상수만 돌려주는 처리기 하나만 나온다."""
        # given
        self.write({"shop/export.py": (
            "def put(client, data):\n"
            "    try:\n        client.put(data)\n    except OSError:\n        pass\n\n\n"
            "def get(client):\n"
            "    try:\n        return client.get()\n    except OSError:\n        raise\n\n\n"
            "def say(client):\n"
            "    try:\n        client.get()\n    except OSError as exc:\n        return f'failed: {exc}'\n")})

        # when
        found = self.scan()["handlers"]

        # then
        self.assertEqual([(item["at"], item["catches"], item["body"]) for item in found], [("shop/export.py:4", "OSError", "pass")])

    def test_원래_있던_처리기와_테스트_파일의_변경은_스캔하지_않는다(self):
        """given 원래 있던 처리기를 그대로 두고 테스트 파일에 처리기와 리터럴을 더한 변경 when 스캔하면 then 세 목록이 모두 비어 있다."""
        # given
        self.write({"tests/test_lookup.py": "def test_x():\n    try:\n        pass\n    except Exception:\n        pass\n    assert 12345 == 12345\n"})

        # when
        found = self.scan()

        # then
        self.assertEqual(found, {"contracts": [], "literals": [], "handlers": []})

    def test_추적하지_않는_새_파일도_스캔하고_변경이_없으면_빈_목록을_출력한다(self):
        """given 추적하지 않는 새 파일에 처리기를 더한 변경과 변경 없음 when 명령으로 실행하면 then 앞은 처리기를 나열하고 뒤는 세 빈 목록을 출력한다."""
        # given
        empty = subprocess.run([sys.executable, str(SCRIPT), self.base, "--repo", str(self.repo)], capture_output=True, text=True)
        self.write({"shop/new.py": "def go(f):\n    try:\n        f()\n    except Exception:\n        return None\n"})

        # when
        filled = subprocess.run([sys.executable, str(SCRIPT), self.base, "--repo", str(self.repo)], capture_output=True, text=True)

        # then
        self.assertEqual(json.loads(empty.stdout), {"contracts": [], "literals": [], "handlers": []})
        self.assertEqual([item["at"] for item in json.loads(filled.stdout)["handlers"]], ["shop/new.py:4"])

    def test_모르는_리비전은_종료_코드_2로_알린다(self):
        """given 저장소에 없는 기준 리비전 when 실행하면 then 종료 코드 2이고 stderr에 원인이 있다."""
        # given / when
        done = subprocess.run([sys.executable, str(SCRIPT), "no-such-revision", "--repo", str(self.repo)], capture_output=True, text=True)

        # then
        self.assertEqual(done.returncode, 2)
        self.assertIn("change_scan:", done.stderr)


if __name__ == "__main__":
    unittest.main()
