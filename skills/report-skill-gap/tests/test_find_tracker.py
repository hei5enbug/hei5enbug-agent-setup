#!/usr/bin/env python3
"""이슈 대상 탐색 스크립트의 플러그인 루트 찾기, 선언 선택, 스키마 검증, 출력 형식, 오류 처리를 검사한다."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "find_tracker.py"
CLAUDE_DIR = ".claude-plugin"
CODEX_DIR = ".codex-plugin"
DECLARATION = "issue-target.json"
VALID_DECLARATION = {
    "version": 1,
    "tracker": {"kind": "github", "location": "demo-org/demo-a"},
    "language": "en",
    "body_format": "markdown",
    "labels": ["bug", "enhancement"],
    "public": True,
    "write_approval": "direct",
}


def declaration(**changes: object) -> dict:
    return {**copy.deepcopy(VALID_DECLARATION), **changes}


def without(key: str) -> dict:
    data = declaration()
    del data[key]
    return data


class FindTrackerCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def plugin(self, name: str = "demo-a", folder: str = CLAUDE_DIR, manifest: object | None = None) -> Path:
        root = self.base / name
        (root / folder).mkdir(parents=True)
        content = {"name": name} if manifest is None else manifest
        (root / folder / "plugin.json").write_text(json.dumps(content), encoding="utf-8")
        return root

    def declare(self, root: Path, data: object) -> Path:
        path = root / DECLARATION
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        return path

    def run_script(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def parse(self, result: subprocess.CompletedProcess[str], code: int = 0) -> dict:
        self.assertEqual(code, result.returncode, result.stderr)
        return json.loads(result.stdout)


class DeclaredTest(FindTrackerCase):
    def test_public_github_declaration_requires_a_preview_even_with_direct_approval(self) -> None:
        """공개 저장소 선언은 write_approval이 direct여도 미리보기를 요구한다."""
        # Given
        root = self.plugin()
        path = self.declare(root, declaration())
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result)
        self.assertEqual("declared", data["status"])
        self.assertEqual(str(root), data["plugin_root"])
        self.assertEqual("demo-a", data["plugin_name"])
        self.assertEqual(str(path), data["declaration"])
        self.assertEqual([], data["problems"])
        self.assertEqual(
            {
                "version": 1,
                "tracker": {"kind": "github", "location": "demo-org/demo-a"},
                "language": "en",
                "body_format": "markdown",
                "labels": ["bug", "enhancement"],
                "label_mode": "pick",
                "public": True,
                "write_approval": "direct",
                "content_rules": None,
                "recommend": False,
                "preview_required": True,
            },
            data["target"],
        )

    def test_private_direct_declaration_does_not_require_a_preview(self) -> None:
        """비공개이고 direct인 선언은 미리보기를 요구하지 않는다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration(public=False, write_approval="direct", labels=[]))
        # When
        result = self.run_script(root)
        # Then
        target = self.parse(result)["target"]
        self.assertFalse(target["preview_required"])
        self.assertEqual([], target["labels"])

    def test_private_preview_declaration_requires_a_preview(self) -> None:
        """비공개여도 write_approval이 preview이면 미리보기를 요구한다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration(public=False, write_approval="preview"))
        # When
        result = self.run_script(root)
        # Then
        self.assertTrue(self.parse(result)["target"]["preview_required"])

    def test_nested_file_inside_a_skill_finds_the_plugin_root(self) -> None:
        """스킬 폴더 안쪽 파일을 넘겨도 그 파일을 품은 플러그인의 선언을 찾는다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration())
        skill = root / "skills" / "demo-skill" / "references"
        skill.mkdir(parents=True)
        target_file = skill / "SKILL.md"
        target_file.write_text("# demo\n", encoding="utf-8")
        # When
        result = self.run_script(target_file)
        # Then
        data = self.parse(result)
        self.assertEqual(str(root), data["plugin_root"])
        self.assertEqual("declared", data["status"])

    def test_nearest_plugin_root_wins_over_an_outer_one(self) -> None:
        """플러그인이 겹치면 가장 가까운 루트를 쓴다."""
        # Given
        outer = self.plugin("demo-a")
        self.declare(outer, declaration())
        inner = outer / "vendor" / "demo-b"
        (inner / CLAUDE_DIR).mkdir(parents=True)
        (inner / CLAUDE_DIR / "plugin.json").write_text('{"name": "demo-b"}', encoding="utf-8")
        # When
        result = self.run_script(inner)
        # Then
        data = self.parse(result)
        self.assertEqual(str(inner), data["plugin_root"])
        self.assertEqual("undeclared", data["status"])

    def test_codex_only_plugin_uses_the_root_declaration(self) -> None:
        """Codex 매니페스트만 있는 플러그인도 플러그인 루트의 선언을 쓴다."""
        # Given
        root = self.plugin("demo-b", folder=CODEX_DIR)
        path = self.declare(root, declaration(language="ko"))
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result)
        self.assertEqual("demo-b", data["plugin_name"])
        self.assertEqual(str(path), data["declaration"])
        self.assertEqual("ko", data["target"]["language"])

    def test_root_declaration_wins_over_files_in_manifest_folders(self) -> None:
        """매니페스트 폴더 안의 같은 이름 파일은 무시하고 루트의 선언을 쓴다."""
        # Given
        root = self.plugin("demo-a")
        (root / CODEX_DIR).mkdir()
        root_path = self.declare(root, declaration(language="en"))
        for folder in (CLAUDE_DIR, CODEX_DIR):
            (root / folder / DECLARATION).write_text(json.dumps(declaration(language="ko")), encoding="utf-8")
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result)
        self.assertEqual(str(root_path), data["declaration"])
        self.assertEqual("en", data["target"]["language"])

    def test_plugin_name_falls_back_to_the_codex_manifest(self) -> None:
        """Claude 매니페스트에 이름이 없으면 Codex 매니페스트의 이름을 쓴다."""
        # Given
        root = self.plugin("demo-a", manifest={"version": "1.0.0"})
        (root / CODEX_DIR).mkdir()
        (root / CODEX_DIR / "plugin.json").write_text('{"name": "demo-c"}', encoding="utf-8")
        # When
        result = self.run_script(root)
        # Then
        self.assertEqual("demo-c", self.parse(result)["plugin_name"])

    def test_plugin_name_is_null_when_no_manifest_has_a_name(self) -> None:
        """어느 매니페스트에도 이름이 없으면 plugin_name은 null이다."""
        # Given
        root = self.plugin("demo-a", manifest={"version": "1.0.0"})
        self.declare(root, declaration())
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result)
        self.assertIsNone(data["plugin_name"])
        self.assertEqual("declared", data["status"])

    def test_plugin_name_is_null_when_the_manifest_is_not_json(self) -> None:
        """매니페스트가 JSON이 아니면 plugin_name은 null이다."""
        # Given
        root = self.plugin("demo-a")
        (root / CLAUDE_DIR / "plugin.json").write_text("{not json", encoding="utf-8")
        # When
        result = self.run_script(root)
        # Then
        self.assertIsNone(self.parse(result)["plugin_name"])

    def test_non_ascii_values_are_printed_as_they_are(self) -> None:
        """비ASCII 값은 이스케이프하지 않고 그대로 출력한다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration(labels=["버그"]))
        # When
        result = self.run_script(root)
        # Then
        self.assertIn("버그", result.stdout)


class UndeclaredTest(FindTrackerCase):
    def test_plugin_without_a_declaration_is_undeclared(self) -> None:
        """선언 파일이 없는 플러그인은 undeclared이고 종료 코드 0이다."""
        # Given
        root = self.plugin()
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result)
        self.assertEqual("undeclared", data["status"])
        self.assertIsNone(data["declaration"])
        self.assertIsNone(data["target"])
        self.assertEqual([], data["problems"])

    def test_declaration_only_inside_a_manifest_folder_is_undeclared(self) -> None:
        """매니페스트 폴더 안에만 있는 선언 파일은 읽지 않는다."""
        # Given
        root = self.plugin()
        (root / CLAUDE_DIR / DECLARATION).write_text(json.dumps(declaration()), encoding="utf-8")
        # When
        result = self.run_script(root)
        # Then
        self.assertEqual("undeclared", self.parse(result)["status"])

    def test_declaration_directory_is_not_a_declaration(self) -> None:
        """선언 이름의 폴더는 선언 파일로 보지 않는다."""
        # Given
        root = self.plugin()
        (root / DECLARATION).mkdir()
        # When
        result = self.run_script(root)
        # Then
        self.assertEqual("undeclared", self.parse(result)["status"])


class UsageErrorTest(FindTrackerCase):
    def assert_usage_error(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(2, result.returncode)
        self.assertIn("error", json.loads(result.stdout))
        self.assertNotEqual("", result.stderr.strip())

    def test_path_without_a_plugin_root_is_a_usage_error(self) -> None:
        """플러그인 루트가 없는 경로는 사용법 오류이다."""
        # Given
        folder = self.base / "plain"
        folder.mkdir()
        # When
        result = self.run_script(folder)
        # Then
        self.assert_usage_error(result)

    def test_nonexistent_path_is_a_usage_error(self) -> None:
        """없는 경로는 사용법 오류이다."""
        # Given
        missing = self.base / "missing"
        # When
        result = self.run_script(missing)
        # Then
        self.assert_usage_error(result)
        self.assertEqual(f"path does not exist: {missing}", json.loads(result.stdout)["error"])

    def test_help_option_prints_usage_and_succeeds(self) -> None:
        """-h나 --help를 주면 경로로 읽지 않고 사용법을 출력한 뒤 0으로 끝난다."""
        for option in ("-h", "--help"):
            with self.subTest(option=option):
                # Given
                arguments = (option,)
                # When
                result = self.run_script(*arguments)
                # Then
                self.assertEqual(0, result.returncode)
                self.assertIn("usage: find_tracker.py <path>", result.stdout)
                self.assertNotIn("path does not exist", result.stdout + result.stderr)

    def test_missing_argument_is_a_usage_error(self) -> None:
        """인자가 없으면 사용법 오류이다."""
        # Given
        arguments: tuple = ()
        # When
        result = self.run_script(*arguments)
        # Then
        self.assert_usage_error(result)

    def test_extra_arguments_are_a_usage_error(self) -> None:
        """인자가 둘 이상이면 사용법 오류이다."""
        # Given
        root = self.plugin()
        # When
        result = self.run_script(root, root)
        # Then
        self.assert_usage_error(result)

    def test_manifest_folder_without_a_regular_manifest_is_not_a_root(self) -> None:
        """plugin.json이 일반 파일이 아닌 폴더는 플러그인 루트로 보지 않는다."""
        # Given
        folder = self.base / "demo-a"
        (folder / CLAUDE_DIR / "plugin.json").mkdir(parents=True)
        # When
        result = self.run_script(folder)
        # Then
        self.assert_usage_error(result)


class InvalidFileTest(FindTrackerCase):
    def assert_invalid(self, result: subprocess.CompletedProcess[str]) -> dict:
        data = self.parse(result, code=1)
        self.assertEqual("invalid", data["status"])
        self.assertIsNone(data["target"])
        self.assertTrue(data["problems"])
        return data

    def test_invalid_json_is_invalid(self) -> None:
        """JSON이 아닌 선언은 invalid이고 종료 코드 1이다."""
        # Given
        root = self.plugin()
        self.declare(root, "{not json")
        # When
        result = self.run_script(root)
        # Then
        self.assert_invalid(result)

    def test_non_utf8_bytes_are_invalid(self) -> None:
        """UTF-8이 아닌 바이트가 있는 선언은 invalid이다."""
        # Given
        root = self.plugin()
        (root / DECLARATION).write_bytes(b'{"version": \xff\xfe}')
        # When
        result = self.run_script(root)
        # Then
        data = self.assert_invalid(result)
        self.assertIn("UTF-8", data["problems"][0])

    def test_unreadable_declaration_is_invalid(self) -> None:
        """읽을 수 없는 선언은 invalid이다."""
        # Given
        root = self.plugin()
        path = self.declare(root, declaration())
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        if self.readable(path):
            self.skipTest("the current user can read any file")
        # When
        result = self.run_script(root)
        # Then
        self.assert_invalid(result)

    def readable(self, path: Path) -> bool:
        try:
            path.read_bytes()
        except OSError:
            return False
        return True

    def test_top_level_array_is_invalid(self) -> None:
        """최상위가 객체가 아니면 invalid이다."""
        # Given
        root = self.plugin()
        self.declare(root, [1])
        # When
        result = self.run_script(root)
        # Then
        self.assertIn("top level", self.assert_invalid(result)["problems"][0])


class SchemaTest(FindTrackerCase):
    def problems_of(self, data: object) -> list[str]:
        self.count = getattr(self, "count", 0) + 1
        root = self.plugin(f"demo-{self.count}")
        self.declare(root, data)
        result = self.run_script(root)
        parsed = self.parse(result, code=1)
        self.assertEqual("invalid", parsed["status"])
        self.assertIsNone(parsed["target"])
        return parsed["problems"]

    def test_each_invalid_value_reports_a_problem_naming_its_field(self) -> None:
        """잘못된 값 하나마다 해당 필드 이름을 담은 문제를 보고한다."""
        cases = {
            "unknown key": (declaration(extra=1), "extra"),
            "missing required key": (without("labels"), "labels"),
            "version true": (declaration(version=True), "version"),
            "version 2": (declaration(version=2), "version"),
            "version float": (declaration(version=1.0), "version"),
            "bad kind": (declaration(tracker={"kind": "svn", "location": "x"}), "tracker.kind"),
            "github without slash": (
                declaration(tracker={"kind": "github", "location": "demo-a"}),
                "tracker.location",
            ),
            "github with a hyphen edge": (
                declaration(tracker={"kind": "github", "location": "-demo/demo-a"}),
                "tracker.location",
            ),
            "empty location": (declaration(tracker={"kind": "other", "location": ""}), "tracker.location"),
            "padded location": (
                declaration(tracker={"kind": "other", "location": " demo "}),
                "tracker.location",
            ),
            "tracker with an extra key": (
                declaration(tracker={"kind": "other", "location": "demo", "url": "x"}),
                "tracker",
            ),
            "tracker not an object": (declaration(tracker="demo-org/demo-a"), "tracker"),
            "bad language": (declaration(language="english_US"), "language"),
            "bad body_format": (declaration(body_format="rtf"), "body_format"),
            "duplicate label": (declaration(labels=["bug", "bug"]), "labels"),
            "empty label": (declaration(labels=["bug", ""]), "labels"),
            "label not a string": (declaration(labels=[1]), "labels"),
            "labels a number": (declaration(labels=5), "labels"),
            "labels an object": (declaration(labels={"a": "b"}), "labels"),
            "template with an unknown placeholder": (declaration(labels="{owner}; skill-feedback"), "{owner}"),
            "template with an empty segment": (declaration(labels="{skill};;skill-feedback"), "labels"),
            "template with a trailing separator": (declaration(labels="{skill}; "), "labels"),
            "empty template": (declaration(labels=""), "labels"),
            "template with duplicate tags": (declaration(labels="skill-feedback; skill-feedback"), "labels"),
            "template with an unclosed brace": (declaration(labels="{skill; bug"), "labels"),
            "template with a stray closing brace": (declaration(labels="skill}; bug"), "labels"),
            "template with an empty placeholder": (declaration(labels="{}; bug"), "labels"),
            "recommend as string": (declaration(recommend="true"), "recommend"),
            "recommend as number": (declaration(recommend=1), "recommend"),
            "recommend null": (declaration(recommend=None), "recommend"),
            "public as string": (declaration(public="true"), "public"),
            "bad write_approval": (declaration(write_approval="auto"), "write_approval"),
            "content_rules absolute": (declaration(content_rules="/etc/hosts"), "content_rules"),
            "content_rules backslash": (declaration(content_rules="docs\\rules.md"), "content_rules"),
            "content_rules empty": (declaration(content_rules=""), "content_rules"),
            "content_rules escaping": (declaration(content_rules="../outside.md"), "content_rules"),
            "content_rules missing file": (declaration(content_rules="docs/missing.md"), "content_rules"),
        }
        for name, (data, field) in cases.items():
            with self.subTest(name):
                # Given
                payload = data
                # When
                problems = self.problems_of(payload)
                # Then
                self.assertTrue(any(field in problem for problem in problems), problems)

    def test_multiple_problems_are_reported_together(self) -> None:
        """문제가 여럿이면 한 번에 모두 보고한다."""
        # Given
        data = declaration(version=2, language="x", public="yes", extra=True)
        # When
        problems = self.problems_of(data)
        # Then
        for field in ("version", "language", "public", "extra"):
            self.assertTrue(any(field in problem for problem in problems), problems)
        self.assertGreaterEqual(len(problems), 4)

    def test_missing_content_rules_is_not_a_problem(self) -> None:
        """content_rules는 생략해도 된다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration())
        # When
        result = self.run_script(root)
        # Then
        self.assertIsNone(self.parse(result)["target"]["content_rules"])

    def test_non_github_location_needs_no_slash(self) -> None:
        """github가 아닌 추적기의 위치는 슬래시가 없어도 된다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration(tracker={"kind": "jira", "location": "DEMO"}))
        # When
        result = self.run_script(root)
        # Then
        self.assertEqual("DEMO", self.parse(result)["target"]["tracker"]["location"])

    def test_language_tags_with_a_region_are_valid(self) -> None:
        """지역이 붙은 언어 태그를 받아들인다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration(language="pt-BR"))
        # When
        result = self.run_script(root)
        # Then
        self.assertEqual("pt-BR", self.parse(result)["target"]["language"])


class TrackerKeysTest(FindTrackerCase):
    def target_of(self, data: object) -> dict:
        root = self.plugin()
        self.declare(root, data)
        return self.parse(self.run_script(root))["target"]

    def test_html_body_format_is_valid(self) -> None:
        """body_format에 html을 선언할 수 있다."""
        # Given
        data = declaration(body_format="html")
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("html", target["body_format"])

    def test_list_labels_are_picked_and_kept_as_declared(self) -> None:
        """목록 라벨은 pick 모드이고 선언한 그대로 유지된다."""
        # Given
        data = declaration(labels=["bug", "enhancement"])
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("pick", target["label_mode"])
        self.assertEqual(["bug", "enhancement"], target["labels"])

    def test_template_labels_are_kept_as_declared_in_template_mode(self) -> None:
        """템플릿 문자열 라벨은 template 모드이고 선언한 문자열 그대로 유지된다."""
        # Given
        data = declaration(labels="{skill}; skill-feedback")
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("template", target["label_mode"])
        self.assertEqual("{skill}; skill-feedback", target["labels"])

    def test_template_without_a_placeholder_is_valid(self) -> None:
        """플레이스홀더가 없는 고정 태그 템플릿도 유효하다."""
        # Given
        data = declaration(labels="skill-feedback;  demo ")
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("template", target["label_mode"])

    def test_single_tag_template_is_valid(self) -> None:
        """구분자가 없는 한 개짜리 템플릿도 유효하다."""
        # Given
        data = declaration(labels="{skill}")
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("template", target["label_mode"])

    def test_list_label_with_braces_keeps_the_old_validation(self) -> None:
        """목록 라벨은 중괄호가 있어도 예전 검증만 받아 유효하다."""
        # Given
        data = declaration(labels=["bug}", "{skill}"])
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("pick", target["label_mode"])
        self.assertEqual(["bug}", "{skill}"], target["labels"])

    def test_empty_label_list_stays_in_pick_mode(self) -> None:
        """빈 라벨 목록은 pick 모드로 유지된다."""
        # Given
        data = declaration(labels=[])
        # When
        target = self.target_of(data)
        # Then
        self.assertEqual("pick", target["label_mode"])
        self.assertEqual([], target["labels"])

    def test_recommend_is_false_when_absent(self) -> None:
        """recommend를 생략하면 target.recommend는 false이다."""
        # Given
        data = declaration()
        # When
        target = self.target_of(data)
        # Then
        self.assertIs(False, target["recommend"])

    def test_recommend_true_is_reported(self) -> None:
        """recommend를 true로 선언하면 target.recommend가 true이다."""
        # Given
        data = declaration(recommend=True)
        # When
        target = self.target_of(data)
        # Then
        self.assertIs(True, target["recommend"])

    def test_recommend_false_is_reported(self) -> None:
        """recommend를 false로 선언하면 target.recommend가 false이다."""
        # Given
        data = declaration(recommend=False)
        # When
        target = self.target_of(data)
        # Then
        self.assertIs(False, target["recommend"])

    def test_unknown_placeholder_problem_names_the_placeholder(self) -> None:
        """알 수 없는 플레이스홀더 문제는 그 플레이스홀더 이름을 담는다."""
        # Given
        root = self.plugin()
        self.declare(root, declaration(labels="{owner}; skill-feedback"))
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result, code=1)
        self.assertEqual("invalid", data["status"])
        self.assertTrue(any("{owner}" in problem for problem in data["problems"]), data["problems"])


class ContentRulesTest(FindTrackerCase):
    def test_valid_content_rules_is_resolved_to_an_absolute_path_inside_the_root(self) -> None:
        """올바른 content_rules는 루트 안의 절대 경로로 바뀐다."""
        # Given
        root = self.plugin()
        rules = root / "docs" / "issue-rules.md"
        rules.parent.mkdir()
        rules.write_text("# rules\n", encoding="utf-8")
        self.declare(root, declaration(content_rules="docs/./issue-rules.md"))
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result)
        self.assertEqual(str(rules), data["target"]["content_rules"])

    def test_symlink_pointing_outside_the_root_is_rejected(self) -> None:
        """루트 밖을 가리키는 심볼릭 링크는 거부한다."""
        # Given
        root = self.plugin()
        outside = self.base / "outside.md"
        outside.write_text("# outside\n", encoding="utf-8")
        (root / "rules.md").symlink_to(outside)
        self.declare(root, declaration(content_rules="rules.md"))
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result, code=1)
        self.assertEqual("invalid", data["status"])
        self.assertTrue(any("content_rules" in problem for problem in data["problems"]))

    def test_symlink_pointing_inside_the_root_resolves_to_its_target(self) -> None:
        """루트 안을 가리키는 심볼릭 링크는 실제 파일의 절대 경로로 바뀐다."""
        # Given
        root = self.plugin()
        real = root / "docs" / "real.md"
        real.parent.mkdir()
        real.write_text("# real\n", encoding="utf-8")
        (root / "rules.md").symlink_to(real)
        self.declare(root, declaration(content_rules="rules.md"))
        # When
        result = self.run_script(root)
        # Then
        self.assertEqual(str(real), self.parse(result)["target"]["content_rules"])

    def test_directory_is_not_a_regular_file(self) -> None:
        """폴더를 가리키는 content_rules는 거부한다."""
        # Given
        root = self.plugin()
        (root / "docs").mkdir()
        self.declare(root, declaration(content_rules="docs"))
        # When
        result = self.run_script(root)
        # Then
        data = self.parse(result, code=1)
        self.assertTrue(any("content_rules" in problem for problem in data["problems"]))


if __name__ == "__main__":
    unittest.main()
