#!/usr/bin/env python3
"""병합(merge)과 삭제(delete) 명령, 그리고 잘못된 인자와 입력 파일의 처리를 검사한다."""

from __future__ import annotations

import json
import os
import stat
import unittest

from data_fixture import FixtureCase


class InvalidInputCase(FixtureCase):
    def test_bad_size_and_negative_age_exit_with_two(self) -> None:
        """잘못된 크기와 음수 보존 일수는 종료 코드 2와 error 필드를 낸다."""
        # given
        base = ["survey", "--host", "claude", *self.root_options(), "--out", str(self.out / "s.json")]
        # when
        bad_size = self.run_script(*base, "--min-size", "12X")
        negative_age = self.run_script(*base, "--age-days", "-1")
        bad_host = self.run_script("survey", "--host", "other", "--out", str(self.out / "s.json"))
        # then
        for result in (bad_size, negative_age, bad_host):
            self.assertEqual(2, result.code)
            self.assertIn("error", result.data)
        self.assertFalse((self.out / "s.json").exists())

    def test_size_suffixes_are_binary(self) -> None:
        """크기는 바이트 수나 K, M, G 접미사를 받고 접미사는 1024 배수로 해석한다."""
        # given
        results = {}
        # when
        for text in ("512", "2K", "3M", "1G"):
            results[text] = self.survey("--min-size", text, "--host", "claude").data["config"]["min_size"]
        # then
        self.assertEqual({"512": 512, "2K": 2048, "3M": 3 * 1024**2, "1G": 1024**3}, results)


class MergeCase(FixtureCase):
    def make_four(self) -> tuple[object, dict[str, int]]:
        for name in ("demo-a", "demo-b", "demo-c", "demo-d"):
            self.scratch(name)
        survey = self.survey("--host", "claude")
        return survey, {name: self.item(survey, name)["id"] for name in ("demo-a", "demo-b", "demo-c", "demo-d")}

    def test_only_delete_verdicts_become_offers(self) -> None:
        """다른 호스트의 verdict가 delete일 때만 offer가 되고 keep, unknown, 누락은 이유와 함께 보고 전용이 된다."""
        # given
        survey, ids = self.make_four()
        verdicts = {ids["demo-a"]: "delete", ids["demo-b"]: "keep", ids["demo-c"]: "unknown", 999: "delete"}
        # when
        merged = self.merge(survey, verdicts)
        # then
        self.assertEqual(0, merged.code)
        self.assertEqual("merge", merged.data["command"])
        self.assertEqual({"host": "codex", "model": "demo-model"}, merged.data["peer"])
        self.assertEqual([999], merged.data["ignored"])
        by_name = {name: self.item(merged, name) for name in ids}
        self.assertEqual("offer", by_name["demo-a"]["verdict"])
        for name, expected in (("demo-b", "differs: demo reason"), ("demo-c", "unknown"), ("demo-d", "unknown")):
            self.assertEqual("report-only", by_name[name]["verdict"])
            self.assertEqual({"peer"}, self.checks_of(by_name[name]))
            self.assertIn(expected, by_name[name]["reasons"][-1]["detail"])
        self.assertEqual("unknown", by_name["demo-d"]["peer"]["verdict"])
        self.assertTrue((self.out / "plan.json").exists())

    def test_protected_item_never_becomes_an_offer(self) -> None:
        """protected 항목에 delete verdict가 와도 offer가 되지 않고 ignored에 담긴다."""
        # given
        self.write(self.codex / ".tmp" / "demo.sqlite", 400000)
        self.write(self.codex / ".tmp" / "plain" / "data.bin", 30000)
        self.age(self.codex / ".tmp")
        survey = self.survey("--host", "codex")
        protected_id = self.item(survey, "demo.sqlite")["id"]
        # when
        merged = self.merge(survey, {item["id"]: "delete" for item in survey.data["items"]})
        # then
        self.assertEqual("protected", self.item(merged, "demo.sqlite")["verdict"])
        self.assertIn(protected_id, merged.data["ignored"])
        self.assertEqual("offer", self.item(merged, "plain")["verdict"])

    def test_unavailable_peer_makes_every_candidate_report_only(self) -> None:
        """다른 호스트의 판정을 받을 수 없으면 peer 파일 없이 병합하고 모든 후보를 이유와 함께 보고 전용으로 둔다."""
        # given
        survey, ids = self.make_four()
        # when
        result = self.run_script(
            "merge", "--survey", str(self.out / "survey.json"), "--peer-unavailable", "the Codex route failed",
            "--self-host", "claude", "--out", str(self.out / "plan.json"),
        )
        # then
        self.assertEqual(0, result.code)
        self.assertEqual({"host": None, "model": None, "unavailable": "the Codex route failed"}, result.data["peer"])
        for name in ids:
            item = self.item(result, name)
            self.assertEqual("report-only", item["verdict"])
            self.assertIn("the Codex route failed", item["reasons"][-1]["detail"])
        self.assertTrue((self.out / "plan.json").exists())

    def test_peer_file_and_unavailable_reason_are_exclusive(self) -> None:
        """peer 파일과 판정 불가 이유를 함께 주거나 둘 다 빼면 종료 코드 2로 거부한다."""
        # given
        survey, ids = self.make_four()
        (self.out / "peer.json").write_text(json.dumps({"host": "codex", "verdicts": []}), encoding="utf-8")
        base = ["merge", "--survey", str(self.out / "survey.json"), "--self-host", "claude",
                "--out", str(self.out / "plan.json")]
        both = base + ["--peer", str(self.out / "peer.json"), "--peer-unavailable", "demo"]
        # when
        results = [self.run_script(*arguments) for arguments in (both, base)]
        # then
        self.assertEqual([2, 2], [result.code for result in results])
        self.assertFalse((self.out / "plan.json").exists())

    def test_peer_from_the_same_host_is_rejected(self) -> None:
        """자기 호스트와 같은 호스트의 peer 파일은 종료 코드 2로 거부한다."""
        # given
        survey, ids = self.make_four()
        peer = {"host": "claude", "verdicts": [{"id": ids["demo-a"], "verdict": "delete", "reason": "demo"}]}
        (self.out / "peer.json").write_text(json.dumps(peer), encoding="utf-8")
        # when
        result = self.run_script(
            "merge", "--survey", str(self.out / "survey.json"), "--peer", str(self.out / "peer.json"),
            "--self-host", "claude", "--out", str(self.out / "plan.json"),
        )
        # then
        self.assertEqual(2, result.code)
        self.assertIn("other host", result.data["error"])
        self.assertFalse((self.out / "plan.json").exists())

    def test_malformed_peer_files_exit_with_two(self) -> None:
        """JSON이 아니거나 스키마가 틀리거나 id가 중복된 peer 파일은 종료 코드 2로 거부한다."""
        # given
        survey, ids = self.make_four()
        entry = {"id": ids["demo-a"], "verdict": "delete", "reason": "demo"}
        bad_peers = [
            "{not json",
            json.dumps({"host": "codex"}),
            json.dumps({"host": "codex", "verdicts": [{"id": 1, "verdict": "maybe", "reason": "x"}]}),
            json.dumps({"host": "codex", "verdicts": [{"id": "1", "verdict": "keep", "reason": "x"}]}),
            json.dumps({"host": "codex", "verdicts": [entry, entry]}),
            json.dumps({"host": "other", "verdicts": []}),
            json.dumps([entry]),
        ]
        for text in bad_peers:
            with self.subTest(peer=text):
                (self.out / "peer.json").write_text(text, encoding="utf-8")
                # when
                result = self.run_script(
                    "merge", "--survey", str(self.out / "survey.json"), "--peer", str(self.out / "peer.json"),
                    "--self-host", "claude", "--out", str(self.out / "plan.json"),
                )
                # then
                self.assertEqual(2, result.code)
                self.assertIn("error", result.data)


class DeleteCase(FixtureCase):
    def test_selected_item_with_a_read_only_subfolder_is_deleted(self) -> None:
        """읽기 전용 하위 폴더를 가진 선택 항목은 지워지고, 항목 밖 읽기 전용 폴더의 권한은 그대로이며, 확보 용량은 양수다."""
        # given
        target = self.scratch("target-session")
        self.write(target / "locked" / "inner" / "data.bin")
        self.age(target)
        sibling = self.scratch("sibling-session")
        outside = self.root / "outside" / "locked"
        self.write(outside / "data.bin")
        for folder in (target / "locked" / "inner", target / "locked", sibling, outside):
            os.chmod(folder, 0o555)
        survey = self.survey("--host", "claude")
        merged = self.merge(survey, {self.item(survey, "target-session")["id"]: "delete"})
        # when
        result = self.delete(str(self.item(merged, "target-session")["id"]))
        # then
        self.assertEqual(0, result.code, result.data)
        self.assertFalse(target.exists())
        entry = result.data["deleted"][0]
        self.assertTrue(entry["gone"])
        self.assertGreater(entry["freed"], 0)
        self.assertEqual(entry["freed"], result.data["freed_total"])
        self.assertEqual(0o555, stat.S_IMODE(outside.stat().st_mode))
        self.assertEqual(0o555, stat.S_IMODE(sibling.stat().st_mode))
        self.assertTrue(result.data["verification"]["links_unchanged"])
        self.assertTrue(result.data["verification"]["protected_unchanged"])

    def test_empty_selection_deletes_nothing(self) -> None:
        """선택이 없거나 빈 값뿐이면 아무것도 지우지 않고 종료 코드 0과 안내를 낸다."""
        # given
        self.scratch("keep-session")
        merged = self.offer_all(self.survey("--host", "claude"))
        before = self.tree(self.root)
        # when
        none_selected = self.delete()
        blank_selected = self.delete("")
        # then
        self.assertEqual(merged.code, 0)
        for result in (none_selected, blank_selected):
            self.assertEqual(0, result.code)
            self.assertEqual([], result.data["selected"])
            self.assertEqual([], result.data["deleted"])
            self.assertEqual("nothing selected; nothing was deleted", result.data["note"])
        self.assertEqual(before, self.tree(self.root))

    def test_non_offer_id_is_refused_and_nothing_is_deleted(self) -> None:
        """offer가 아닌 번호가 하나라도 있으면 그 번호를 알리고 종료 코드 2로 아무것도 지우지 않는다."""
        # given
        offered = self.scratch("offered-session")
        survey = self.survey("--host", "claude")
        merged = self.merge(survey, {self.item(survey, "offered-session")["id"]: "delete"})
        offered_id = self.item(merged, "offered-session")["id"]
        # when
        result = self.delete(str(offered_id), "77")
        # then
        self.assertEqual(2, result.code)
        self.assertIn("77", result.data["error"])
        self.assertTrue(offered.exists())

    def test_comma_separated_selection_and_report_only_refusal(self) -> None:
        """쉼표로 묶은 번호를 받고, 보고 전용 번호가 섞이면 전부 거부한다."""
        # given
        first, second = self.scratch("first-session"), self.scratch("second-session")
        survey = self.survey("--host", "claude")
        first_id, second_id = (self.item(survey, name)["id"] for name in ("first-session", "second-session"))
        merged = self.merge(survey, {first_id: "delete", second_id: "keep"})
        # when
        refused = self.delete(f"{first_id},{second_id}")
        # then
        self.assertEqual(2, refused.code)
        self.assertIn(str(second_id), refused.data["error"])
        self.assertTrue(first.exists() and second.exists())
        self.assertEqual(merged.code, 0)

    def test_item_touched_after_the_merge_is_skipped(self) -> None:
        """병합 뒤에 안쪽 파일이 수정된 항목은 recent로 건너뛰고 지우지 않으며 종료 코드 1이다."""
        # given
        touched, untouched = self.scratch("touched-session"), self.scratch("untouched-session")
        merged = self.offer_all(self.survey("--host", "claude"))
        self.write(touched / "new-file.bin", 10)
        ids = [str(self.item(merged, "/" + name)["id"]) for name in ("touched-session", "untouched-session")]
        # when
        result = self.delete(*ids)
        # then
        self.assertEqual(1, result.code)
        self.assertTrue(touched.exists())
        self.assertFalse(untouched.exists())
        skipped = result.data["skipped"]
        self.assertEqual(1, len(skipped))
        self.assertEqual("recent", skipped[0]["reasons"][0]["check"])
        self.assertEqual(1, len(result.data["deleted"]))

    def test_replaced_member_is_skipped_by_identity(self) -> None:
        """병합 뒤에 같은 이름으로 다시 만들어진 폴더는 identity가 달라 건너뛴다."""
        # given
        target = self.scratch("replaced-session")
        merged = self.offer_all(self.survey("--host", "claude"))
        target.rename(self.root / "moved-away")
        self.scratch("replaced-session")
        # when
        result = self.delete(str(self.item(merged, "replaced-session")["id"]))
        # then
        self.assertEqual(1, result.code)
        self.assertEqual("identity", result.data["skipped"][0]["reasons"][0]["check"])
        self.assertTrue(target.exists())
        self.assertTrue((self.root / "moved-away").exists())

    def test_normal_delete_leaves_links_and_protected_paths_unchanged(self) -> None:
        """정상 삭제 뒤 검증 표시는 모두 참이고 current 링크와 보호 파일은 그대로다."""
        # given
        releases = self.codex / "packages" / "standalone" / "releases"
        for name in ("1.0.0-demo", "1.0.1-demo"):
            self.write(releases / name / "bin.bin")
            self.age(releases / name)
        link = self.codex / "packages" / "standalone" / "current"
        os.symlink(releases / "1.0.1-demo", link)
        database = self.write(self.codex / "state.sqlite", 4000)
        wal = self.write(self.codex / "state.sqlite-wal", 100)
        merged = self.offer_all(self.survey("--host", "codex"))
        item = self.item(merged, "1.0.0-demo")
        # when
        result = self.delete(str(item["id"]))
        # then
        self.assertEqual(0, result.code, result.data)
        self.assertTrue(result.data["verification"]["links_unchanged"])
        self.assertTrue(result.data["verification"]["protected_unchanged"])
        self.assertEqual(str(releases / "1.0.1-demo"), os.readlink(link))
        self.assertFalse((releases / "1.0.0-demo").exists())
        self.assertTrue((releases / "1.0.1-demo").exists())
        self.assertTrue(database.exists() and wal.exists())

    def test_freed_size_leaves_out_a_file_hard_linked_outside_the_item(self) -> None:
        """항목 밖에 하드링크가 남는 파일은 삭제해도 확보 용량에 넣지 않고 밖의 링크는 그대로 남는다."""
        # given
        target = self.scratch("linked-session", size=200000)
        kept = self.root / "outside" / "kept.bin"
        kept.parent.mkdir()
        os.link(target / "data.bin", kept)
        merged = self.offer_all(self.survey("--host", "claude"))
        # when
        result = self.delete(str(self.item(merged, "linked-session")["id"]))
        # then
        self.assertEqual(0, result.code, result.data)
        self.assertFalse(target.exists())
        self.assertTrue(kept.exists())
        self.assertLess(result.data["freed_total"], 100000)

    def test_plan_that_is_not_a_merge_output_exits_with_two(self) -> None:
        """병합 결과가 아닌 계획 파일은 종료 코드 2로 거부한다."""
        # given
        self.scratch("any-session")
        self.survey("--host", "claude")
        (self.out / "plan.json").write_text((self.out / "survey.json").read_text(encoding="utf-8"), encoding="utf-8")
        # when
        result = self.delete("1")
        # then
        self.assertEqual(2, result.code)
        self.assertIn("merge", result.data["error"])


if __name__ == "__main__":
    unittest.main()
