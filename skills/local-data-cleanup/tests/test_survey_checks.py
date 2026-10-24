#!/usr/bin/env python3
"""조사(survey) 명령의 안전 검사가 후보를 보고 전용이나 보호 항목으로 바꾸는지 검사한다."""

from __future__ import annotations

import os
import shutil
import unittest

from data_fixture import HOLD_CODE, FixtureCase


class OwnerAndOpenCase(FixtureCase):
    def test_live_process_naming_or_inside_a_scratch_folder_blocks_it(self) -> None:
        """실행 중인 프로세스가 argv로 이름을 부르거나 작업 폴더가 안에 있는 스크래치 폴더는 후보가 되지 않는다."""
        # given
        named, inside, free = self.scratch("demo-a"), self.scratch("demo-c"), self.scratch("demo-b")
        self.wait_ready(self.spawn(HOLD_CODE, str(named)))
        self.wait_ready(self.spawn(cwd=inside))
        # when
        result = self.survey("--host", "claude")
        # then
        by_name = self.item(result, "demo-a")
        self.assertEqual("report-only", by_name["verdict"])
        self.assertIn("owner", self.checks_of(by_name))
        by_cwd = self.item(result, "demo-c")
        self.assertEqual("report-only", by_cwd["verdict"])
        self.assertTrue(self.checks_of(by_cwd) & {"owner", "open"})
        self.assertEqual("candidate", self.item(result, "demo-b")["verdict"])
        self.assertTrue(free.exists())

    def test_member_held_open_by_a_child_fails_open(self) -> None:
        """자식 프로세스가 안의 파일을 열어 둔 스크래치 폴더는 open 검사에서 실패한다."""
        # given
        held = self.scratch("held-session")
        self.hold_open(held / "data.bin")
        # when
        result = self.survey("--host", "claude")
        # then
        item = self.item(result, "held-session")
        self.assertEqual("report-only", item["verdict"])
        self.assertEqual({"open"}, self.checks_of(item))

    def test_session_id_in_an_active_session_file_fails_owner(self) -> None:
        """claude 폴더의 sessions 파일이 세션 ID를 언급하면 그 스크래치 폴더는 owner 검사에서 실패한다."""
        # given
        self.scratch("live-session-1")
        self.scratch("ended-session-2")
        self.write(self.claude / "sessions" / "100.json", 10).write_text('{"sessionId": "live-session-1"}')
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertEqual({"owner"}, self.checks_of(self.item(result, "live-session-1")))
        self.assertEqual("candidate", self.item(result, "ended-session-2")["verdict"])

    def test_recently_written_session_record_fails_owner(self) -> None:
        """같은 세션 ID의 기록 파일이 최근에 수정되었으면 그 스크래치 폴더는 owner 검사에서 실패한다."""
        # given
        self.scratch("busy-session", project="demo-project")
        self.write(self.claude / "projects" / "demo-project" / "busy-session.jsonl", 100)
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertIn("owner", self.checks_of(self.item(result, "busy-session")))


class ProtectedCase(FixtureCase):
    def test_state_database_is_protected_even_inside_a_temp_entry(self) -> None:
        """가장 큰 항목인 상태 DB와 임시 항목 안의 상태 DB는 protected이고 후보가 아니다."""
        # given
        self.write(self.codex / ".tmp" / "demo.sqlite", 500000)
        self.write(self.codex / ".tmp" / "entry" / "demo.sqlite", 100000)
        self.write(self.codex / ".tmp" / "plain" / "data.bin", 20000)
        self.age(self.codex / ".tmp")
        # when
        result = self.survey("--host", "codex")
        # then
        self.assertEqual("demo.sqlite", result.data["items"][0]["paths"][0].rsplit("/", 1)[-1])
        self.assertEqual("protected", self.item(result, "<codex>/.tmp/demo.sqlite")["verdict"])
        self.assertEqual("protected", self.item(result, "<codex>/.tmp/entry")["verdict"])
        self.assertEqual("candidate", self.item(result, "<codex>/.tmp/plain")["verdict"])

    def test_credentials_and_configuration_in_the_data_folder_are_protected_or_report_only(self) -> None:
        """데이터 폴더의 자격 증명과 설정은 protected이고 그 밖의 항목은 종류 때문에 보고 전용이다."""
        # given
        self.write(self.codex / "auth.json", 300)
        self.write(self.codex / "config.toml", 300)
        self.write(self.codex / "log" / "run.log", 20000)
        self.age(self.codex)
        # when
        result = self.survey("--host", "codex")
        # then
        self.assertEqual("protected", self.item(result, "<codex>/auth.json")["verdict"])
        self.assertEqual("protected", self.item(result, "<codex>/config.toml")["verdict"])
        other = self.item(result, "<codex>/log")
        self.assertEqual(("report-only", {"kind"}), (other["verdict"], self.checks_of(other)))

    def test_protect_option_marks_a_path_protected(self) -> None:
        """--protect로 지정한 경로와 겹치는 항목은 protected로 나온다."""
        # given
        kept = self.scratch("user-kept")
        self.scratch("not-kept")
        # when
        result = self.survey("--host", "claude", "--protect", str(kept))
        # then
        self.assertEqual("protected", self.item(result, "user-kept")["verdict"])
        self.assertEqual("candidate", self.item(result, "not-kept")["verdict"])


class RecentOutsideGitCase(FixtureCase):
    def test_folder_modified_an_hour_ago_is_report_only_recent(self) -> None:
        """한 시간 전에 수정된 폴더는 recent 검사에서 실패해 보고 전용이 된다."""
        # given
        folder = self.scratch("fresh-session")
        self.age(folder, days=1 / 24)
        # when
        result = self.survey("--host", "claude")
        # then
        item = self.item(result, "fresh-session")
        self.assertEqual(("report-only", {"recent"}), (item["verdict"], self.checks_of(item)))

    def test_symlink_member_pointing_outside_the_roots_fails_outside(self) -> None:
        """루트 밖 폴더를 가리키는 심볼릭 링크 항목은 outside 검사에서 실패한다."""
        # given
        elsewhere = self.root / "elsewhere"
        self.write(elsewhere / "data.bin")
        self.age(elsewhere)
        (self.temp / "demo-project").mkdir(parents=True)
        os.symlink(elsewhere, self.temp / "demo-project" / "linked-session")
        # when
        result = self.survey("--host", "claude")
        # then
        item = self.item(result, "linked-session")
        self.assertEqual("report-only", item["verdict"])
        self.assertIn("outside", self.checks_of(item))
        self.assertTrue((elsewhere / "data.bin").exists())

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_dirty_work_tree_fails_git_and_clean_one_passes(self) -> None:
        """커밋하지 않은 변경이나 무시되지 않은 새 파일이 있는 작업 트리는 git 검사에서 실패하고 깨끗한 것은 통과한다."""
        # given
        dirty, clean = self.temp / "demo-project" / "dirty-session", self.temp / "demo-project" / "clean-session"
        self.make_repo(dirty, dirty=True)
        self.make_repo(clean, dirty=False)
        self.age(dirty)
        self.age(clean)
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertEqual("report-only", self.item(result, "dirty-session")["verdict"])
        self.assertIn("git", self.checks_of(self.item(result, "dirty-session")))
        self.assertEqual("candidate", self.item(result, "clean-session")["verdict"])

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_member_inside_a_dirty_work_tree_fails_git(self) -> None:
        """작업 트리 안에 있고 무시되지 않은 새 파일을 가진 항목은 git 검사에서 실패한다."""
        # given
        self.make_repo(self.codex, dirty=False)
        self.write(self.codex / ".tmp" / "entry" / "data.bin")
        self.age(self.codex / ".tmp")
        # when
        result = self.survey("--host", "codex")
        # then
        self.assertIn("git", self.checks_of(self.item(result, "<codex>/.tmp/entry")))


class MissingCommandCase(FixtureCase):
    def test_without_lsof_candidates_become_report_only_open(self) -> None:
        """lsof를 쓸 수 없으면 후보였던 항목도 open 검사가 알 수 없음으로 실패해 보고 전용이 된다."""
        # given
        self.scratch("any-session")
        commands = self.root / "commands"
        commands.mkdir()
        for name in ("ps", "git"):
            os.symlink(shutil.which(name), commands / name)
        environment = self.env(PATH=str(commands))
        # when
        result = self.survey("--host", "claude", environment=environment)
        # then
        item = self.item(result, "any-session")
        self.assertEqual(("report-only", {"open"}), (item["verdict"], self.checks_of(item)))
        self.assertIn("unknown", item["reasons"][0]["detail"])

    def test_without_ps_every_owner_check_is_unknown(self) -> None:
        """ps를 쓸 수 없으면 owner 검사가 알 수 없음으로 실패해 아무것도 후보가 되지 않는다."""
        # given
        self.scratch("any-session")
        commands = self.root / "commands"
        commands.mkdir()
        os.symlink(shutil.which("lsof"), commands / "lsof")
        # when
        result = self.survey("--host", "claude", environment=self.env(PATH=str(commands)))
        # then
        self.assertIn("owner", self.checks_of(self.item(result, "any-session")))
        self.assertNotIn("candidate", {item["verdict"] for item in result.data["items"]})


if __name__ == "__main__":
    unittest.main()
