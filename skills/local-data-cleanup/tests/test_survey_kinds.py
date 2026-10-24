#!/usr/bin/env python3
"""조사(survey) 명령이 종류별 항목, 정렬, 안내 문구, 기본 경로를 올바르게 만드는지 검사한다."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from data_fixture import SCRIPT_DIR, FixtureCase

CONSEQUENCE = "These sessions can no longer be resumed or reviewed."
PAST_UPDATE = "2020-01-01T00:00:00.000Z"
FUTURE_UPDATE = "2099-01-01T00:00:00.000Z"
SESSION_ID = "0199aaaa-0000-7000-8000-000000000003"


class ReleaseCase(FixtureCase):
    def make_releases(self, folder: Path, names: list[str]) -> None:
        for name in names:
            self.write(folder / name)
            self.age(folder / name)

    def test_claude_lower_versions_than_launcher_target_are_candidates(self) -> None:
        """Claude 실행 링크가 1.0.4를 가리키면 1.0.0부터 1.0.3까지만 후보이고 1.0.5는 version 때문에 보고 전용이다."""
        # given
        versions = self.install / "versions"
        self.make_releases(versions, ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4", "1.0.5"])
        os.symlink(versions / "1.0.4", self.launcher)
        # when
        result = self.survey("--host", "claude")
        # then
        displays = {item["display"]: item for item in result.data["items"] if item["kind"] == "superseded-release"}
        self.assertEqual(
            {f"<claude-install>/versions/1.0.{n}" for n in (0, 1, 2, 3, 5)}, set(displays)
        )
        for number in range(4):
            self.assertEqual("candidate", displays[f"<claude-install>/versions/1.0.{number}"]["verdict"])
        newer = displays["<claude-install>/versions/1.0.5"]
        self.assertEqual(("report-only", {"version"}), (newer["verdict"], self.checks_of(newer)))

    def test_codex_lower_releases_than_current_target_are_candidates(self) -> None:
        """Codex current 링크가 1.0.4를 가리키면 같은 releases 폴더의 낮은 버전만 후보이고 1.0.4는 항목이 아니다."""
        # given
        releases = self.codex / "packages" / "standalone" / "releases"
        self.make_releases(releases, ["1.0.0-demo", "1.0.1-demo", "1.0.4-demo", "1.0.5-demo", "notes"])
        os.symlink(releases / "1.0.4-demo", self.codex / "packages" / "standalone" / "current")
        # when
        result = self.survey("--host", "codex")
        # then
        items = {item["display"]: item for item in result.data["items"] if item["kind"] == "superseded-release"}
        base = "<codex>/packages/standalone/releases/"
        self.assertEqual({base + name for name in ("1.0.0-demo", "1.0.1-demo", "1.0.5-demo", "notes")}, set(items))
        self.assertEqual("candidate", items[base + "1.0.0-demo"]["verdict"])
        self.assertEqual({"version"}, self.checks_of(items[base + "1.0.5-demo"]))
        self.assertEqual({"version"}, self.checks_of(items[base + "notes"]))

    def test_claude_releases_without_launcher_link_are_not_items(self) -> None:
        """실행 링크가 versions 폴더를 가리키지 않으면 Claude 릴리스 항목을 만들지 않는다."""
        # given
        self.make_releases(self.install / "versions", ["1.0.0"])
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertEqual([], [i for i in result.data["items"] if i["kind"] == "superseded-release"])


class PluginVersionCase(FixtureCase):
    def install_plugin(self, updated: str) -> None:
        old, current = self.cache / "demo-market" / "demo-plugin" / "1.0.0", self.cache / "demo-market" / "demo-plugin" / "1.1.0"
        for folder in (old, current):
            self.write(folder / "plugin.bin")
            self.age(folder)
        self.write(self.cache / "demo-market" / "other-plugin" / "0.9.0" / "plugin.bin")
        self.age(self.cache / "demo-market" / "other-plugin" / "0.9.0")
        entry = {"scope": "user", "installPath": str(current), "version": "1.1.0", "installedAt": updated, "lastUpdated": updated}
        record = {"version": 2, "plugins": {"demo-plugin@demo-market": [entry]}}
        (self.claude / "plugins").mkdir(parents=True, exist_ok=True)
        (self.claude / "plugins" / "installed_plugins.json").write_text(json.dumps(record), encoding="utf-8")

    def test_old_plugin_version_is_candidate_without_earlier_claude_process(self) -> None:
        """갱신 시각이 과거이고 그보다 먼저 시작한 Claude Code 프로세스가 없으면 낮은 버전은 후보이고 설치된 버전은 아니다."""
        # given
        self.install_plugin(PAST_UPDATE)
        # when
        result = self.survey("--host", "claude")
        # then
        base = "<claude-plugin-cache>/demo-market/"
        self.assertEqual("candidate", self.item(result, base + "demo-plugin/1.0.0")["verdict"])
        installed = self.item(result, base + "demo-plugin/1.1.0")
        self.assertEqual("report-only", installed["verdict"])
        self.assertIn("link", self.checks_of(installed))
        self.assertEqual({"version"}, self.checks_of(self.item(result, base + "other-plugin/0.9.0")))

    def test_old_plugin_version_fails_owner_with_earlier_claude_process(self) -> None:
        """argv[0]의 이름이 claude인 프로세스가 갱신 시각보다 먼저 시작했으면 낮은 버전은 owner 때문에 보고 전용이다."""
        # given
        self.install_plugin(FUTURE_UPDATE)
        (self.root / "bin").mkdir()
        self.wait_ready(self.spawn(argv0=str(self.root / "bin" / "claude")))
        # when
        result = self.survey("--host", "claude")
        # then
        old = self.item(result, "demo-plugin/1.0.0")
        self.assertEqual("report-only", old["verdict"])
        self.assertIn("owner", self.checks_of(old))
        self.assertIn("started before the update", json.dumps(old["reasons"]))

    def test_broken_installed_list_makes_versions_report_only(self) -> None:
        """installed_plugins.json이 올바른 JSON이 아니면 owner 검사가 실패해 어떤 버전도 후보가 되지 않는다."""
        # given
        self.install_plugin(PAST_UPDATE)
        (self.claude / "plugins" / "installed_plugins.json").write_text("{broken", encoding="utf-8")
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertEqual({"owner"}, self.checks_of(self.item(result, "demo-plugin/1.0.0")))

    def test_version_between_installed_versions_is_not_a_candidate(self) -> None:
        """설치된 버전이 1.0.0과 1.2.0이면 둘 사이의 1.1.0은 version 때문에 보고 전용이고 둘보다 낮은 0.9.0만 후보다."""
        # given
        plugin = self.cache / "demo-market" / "demo-plugin"
        for name in ("0.9.0", "1.0.0", "1.1.0", "1.2.0"):
            self.write(plugin / name / "plugin.bin")
            self.age(plugin / name)
        entries = [
            {"scope": scope, "installPath": str(plugin / version), "version": version, "lastUpdated": PAST_UPDATE}
            for scope, version in (("user", "1.2.0"), ("project", "1.0.0"))
        ]
        record = {"version": 2, "plugins": {"demo-plugin@demo-market": entries}}
        self.write(self.claude / "plugins" / "installed_plugins.json").write_text(json.dumps(record), encoding="utf-8")
        # when
        result = self.survey("--host", "claude")
        # then
        between = self.item(result, "demo-plugin/1.1.0")
        self.assertEqual(("report-only", {"version"}), (between["verdict"], self.checks_of(between)))
        self.assertEqual("candidate", self.item(result, "demo-plugin/0.9.0")["verdict"])


class RecordsCase(FixtureCase):
    def claude_pair(self, project: str, name: str, days: float, size: int = 20000) -> None:
        record = self.write(self.claude / "projects" / project / f"{name}.jsonl", size)
        self.write(self.claude / "projects" / project / name / "sub.bin", size)
        self.age(record, days)
        self.age(self.claude / "projects" / project / name, days)

    def test_records_newer_than_threshold_leave_only_a_note(self) -> None:
        """30일보다 오래된 Claude 기록이 없으면 항목 없이 안내가 남고 보고된 age_days는 입력값 그대로다."""
        # given
        self.claude_pair("demo-project", "recent-session", days=3)
        # when
        result = self.survey("--host", "claude", "--age-days", "45")
        # then
        self.assertEqual([], [i for i in result.data["items"] if i["kind"] == "old-session-records"])
        self.assertEqual(45, result.data["config"]["age_days"])
        notes = result.data["notes"]
        self.assertEqual(1, len(notes))
        self.assertEqual("claude", notes[0]["host"])
        self.assertEqual(
            "nothing older than 45 days under <claude>/projects; nothing reclaimable there", notes[0]["text"]
        )

    def test_items_are_sorted_and_records_carry_user_decision(self) -> None:
        """항목은 크기 내림차순이고 old-session-records 항목은 모두 decision이 user이며 결과 문구를 담는다."""
        # given
        self.claude_pair("demo-project", "old-a", days=60, size=40000)
        self.claude_pair("demo-project", "old-b", days=70, size=5000)
        self.claude_pair("demo-project", "recent", days=1, size=90000)
        self.write(self.claude / "projects" / "demo-project" / "memory" / "note.md", 30000)
        for day, size in (("2026/01/05", 60000), ("2026/01/06", 30000), ("2026/02/01", 8000)):
            self.write(self.codex / "sessions" / day / f"rollout-demo-{SESSION_ID}.jsonl", size)
            self.age(self.codex / "sessions" / day)
        self.write(self.codex / "archived_sessions" / "old.jsonl", 20000)
        self.age(self.codex / "archived_sessions" / "old.jsonl")
        # when
        result = self.survey()
        # then
        sizes = [item["size"] for item in result.data["items"]]
        self.assertEqual(sorted(sizes, reverse=True), sizes)
        records = [i for i in result.data["items"] if i["kind"] == "old-session-records"]
        self.assertTrue(records)
        for item in records:
            self.assertEqual("user", item["decision"])
            self.assertEqual(CONSEQUENCE, item["consequence"])
        month = self.item(result, "<codex>/sessions/2026/01/05")
        self.assertEqual(2, len(month["paths"]))
        self.assertEqual("candidate", month["verdict"])
        project = self.item(result, "<claude>/projects/demo-project/")
        self.assertEqual(4, len(project["paths"]))
        self.assertEqual(4, len(project["identity"]))
        for item in result.data["items"]:
            self.assertNotIn("memory/note.md", " ".join(item["paths"]))
            self.assertNotIn("demo-project/recent", " ".join(item["paths"]))

    def test_items_below_min_size_are_counted_as_omitted(self) -> None:
        """--min-size보다 작은 항목은 items에서 빠지고 omitted의 개수와 크기로 집계된다."""
        # given
        self.scratch("small-session", size=100)
        # when
        result = self.survey("--min-size", "1G", "--host", "claude")
        # then
        self.assertEqual([], result.data["items"])
        self.assertEqual(1, result.data["omitted"]["count"])
        self.assertGreater(result.data["omitted"]["size"], 0)

    def test_hard_links_are_counted_once_per_item(self) -> None:
        """같은 파일에 하드링크가 둘 있는 스크래치 폴더의 크기는 일반 복사본 둘의 크기보다 작다."""
        # given
        single = self.scratch("single", size=100000)
        linked = self.scratch("linked", size=100000)
        os.link(linked / "data.bin", linked / "second.bin")
        self.age(linked)
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertLessEqual(self.item(result, "linked")["size"], self.item(result, "single")["size"] + 8192)
        self.assertTrue(single.exists())

    def test_hard_link_outside_the_item_is_not_counted(self) -> None:
        """항목 밖에도 하드링크가 남는 파일은 지워도 공간이 돌아오지 않으므로 항목 크기에 넣지 않는다."""
        # given
        shared = self.scratch("shared", size=200000)
        (self.root / "outside").mkdir()
        os.link(shared / "data.bin", self.root / "outside" / "kept.bin")
        # when
        result = self.survey("--host", "claude")
        # then
        self.assertLess(self.item(result, "shared")["size"], 100000)

    def test_codex_plugin_storage_is_listed_as_other(self) -> None:
        """Codex 데이터 폴더의 plugins는 이 스킬이 회수하는 종류가 아니므로 other로 보고 전용으로 나온다."""
        # given
        self.write(self.codex / "plugins" / "cache" / "demo-market" / "demo-plugin" / "1.0.0" / "plugin.bin")
        self.age(self.codex)
        # when
        result = self.survey("--host", "codex")
        # then
        item = self.item(result, "<codex>/plugins")
        self.assertEqual(("other", "report-only", {"kind"}), (item["kind"], item["verdict"], self.checks_of(item)))


class DefaultRootCase(FixtureCase):
    def test_defaults_resolve_under_home(self) -> None:
        """루트 옵션과 환경 변수가 없으면 빈 HOME 아래 기본 경로를 쓰고 없는 루트는 오류 없이 exists가 false다."""
        # given
        arguments = ["survey", "--host", "both", "--temp-root", str(self.temp), "--out", str(self.out / "s.json")]
        # when
        result = self.run_script(*arguments)
        # then
        self.assertEqual(0, result.code)
        roots = {root["name"]: root for root in result.data["roots"]}
        self.assertEqual(str(self.claude), roots["claude"]["path"])
        self.assertEqual(str(self.cache), roots["claude-plugin-cache"]["path"])
        self.assertEqual(str(self.install), roots["claude-install"]["path"])
        self.assertEqual(str(self.codex), roots["codex"]["path"])
        self.assertEqual(str(self.launcher), result.data["config"]["claude_launcher"])
        self.assertFalse(roots["claude"]["exists"])
        self.assertEqual([], result.data["items"])

    def test_environment_variables_override_home_defaults(self) -> None:
        """CLAUDE_CONFIG_DIR와 CODEX_HOME이 있으면 그 경로를 쓰고 플러그인 캐시는 Claude 폴더 아래로 따라간다."""
        # given
        claude, codex = self.root / "env-claude", self.root / "env-codex"
        environment = self.env(CLAUDE_CONFIG_DIR=str(claude), CODEX_HOME=str(codex))
        arguments = ["survey", "--host", "both", "--temp-root", str(self.temp), "--out", str(self.out / "s.json")]
        # when
        result = self.run_script(*arguments, environment=environment)
        # then
        config = result.data["config"]
        self.assertEqual(str(claude), config["claude_dir"])
        self.assertEqual(str(claude / "plugins" / "cache"), config["claude_plugin_cache"])
        self.assertEqual(str(codex), config["codex_dir"])

    def test_default_temp_roots_pick_existing_uid_folders_once(self) -> None:
        """기본 임시 루트 탐색은 claude-uid 폴더가 있는 기준 폴더만 고르고 같은 실제 경로는 한 번만 담는다."""
        # given
        sys.path.insert(0, str(SCRIPT_DIR))
        self.addCleanup(sys.path.remove, str(SCRIPT_DIR))
        import data_common

        first, second = self.root / "base-a", self.root / "base-b"
        (first / "claude-1234").mkdir(parents=True)
        os.symlink(first, second)
        (self.root / "base-c").mkdir()
        bases = [str(first), str(second), str(self.root / "base-c"), str(self.root / "missing")]
        # when
        roots = data_common.default_temp_roots(bases, 1234)
        # then
        self.assertEqual((str(first / "claude-1234"),), roots)
        self.assertEqual(["/x", "/tmp", "/y"], data_common.temp_bases({"CLAUDE_CODE_TMPDIR": "/x", "TMPDIR": "/y"}))


if __name__ == "__main__":
    unittest.main()
