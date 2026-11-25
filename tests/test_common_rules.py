#!/usr/bin/env python3
"""항상 로드되는 공통 규칙이 두 호스트의 메인 세션 문맥에 실리는지 검사한다."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import session_context  # noqa: E402


def contexts() -> dict[str, str]:
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PLUGIN_ROOT", None)
        return {host: " ".join(session_context.render_context(REPO_ROOT, host).split()) for host in ("claude", "codex")}


class CommonRulesTest(unittest.TestCase):
    def assert_in_every_context(self, *phrases: str) -> None:
        for host, context in contexts().items():
            for phrase in phrases:
                with self.subTest(host=host, phrase=phrase):
                    self.assertIn(phrase, context)

    def test_답변은_추천을_먼저_두고_처음_읽는_사람에게_간결하며_기존_스레드에는_새_내용만_더한다(self):
        """결정을 묻는 답변은 추천과 이유를 먼저 쓰고, 필요한 내용만 한 가지로 읽히게 쓰며, 기존 스레드에는 새 내용만 더한다."""
        # Given
        phrases = (
            "for a decision, one recommendation and its reason, then the alternatives",
            "Keep only what the reader needs, give each sentence one reading",
            "define terms a first-time reader would not know",
            "In an existing thread, read it first and add only what is new.",
        )

        # When / Then
        self.assert_in_every_context(*phrases)

    def test_명확한_요청은_요청만_하고_문서_규칙과_작업_준비_규칙이_후속_수정을_둘로_한정한다(self):
        """코어는 대체한 문장을 두 호스트 문맥에서 빼고 더 짧게 쓰며, 후속 수정 규칙은 문서 지침과 작업 준비에 있다."""
        # Given
        replaced = "Do not add design, tests, implementation, or planning beyond the request."
        sentence = "Add no design, tests, implementation, docs, or plans beyond the request."
        documentation = " ".join((REPO_ROOT / "instructions/documentation.md").read_text(encoding="utf-8").split())
        execution = (REPO_ROOT / "instructions/implementation-execution.md").read_text(encoding="utf-8")
        preparation = " ".join(execution.split("## Task preparation", 1)[1].split("## Assignment fields", 1)[0].split())

        # When
        measured = (len(sentence.encode("utf-8")), len(replaced.encode("utf-8")))

        # Then
        self.assert_in_every_context(sentence)
        for host, context in contexts().items():
            with self.subTest(host=host):
                self.assertNotIn(replaced, context)
        self.assertLessEqual(*measured)
        self.assertIn("existing text that the change made false needs correcting", documentation)
        self.assertIn("a repository rule requires text for something the change adds", documentation)
        self.assertIn("existing text or tests that the change made false, and text that a repository rule requires", preparation)
        self.assertIn("add no text about it", documentation)

    def test_일정이나_다음_실행을_기다리기_전에_지금_안전하게_확인할_방법을_먼저_찾는다(self):
        """세션 문맥은 기다리기 전에 직접 확인하고 묻기 참조를 읽게 하며, 참조는 지금 확인할 방법과 기다릴 때 밝힐 내용을 정한다."""
        # Given
        asking = " ".join((REPO_ROOT / "instructions/asking-the-user.md").read_text(encoding="utf-8").split())

        # When
        steps = (
            "Before proposing to wait for a schedule, a later run, or new data,",
            "such as a manual trigger, a dry run, a replay of recorded input, or a comparison with a past window",
            "Propose waiting only when none exists, and give the reason and the earliest time to check.",
        )

        # Then
        self.assert_in_every_context(
            "instead of asking about it or waiting for a later run.",
            "Before asking the user anything or proposing to wait, read",
        )
        for step in steps:
            with self.subTest(step=step):
                self.assertIn(step, asking)

    def test_질문_창의_문구도_답변_규칙을_따르고_사용자가_쓰지_않은_용어는_같은_뜻의_쉬운_말로_바꾸고_없을_때만_정의한다(self):
        """질문, 머리말, 선택지 이름과 설명은 그 창만 보는 사람이 읽을 수 있게 쓰고, 사용자가 쓰지 않은 용어와 식별자는 쉬운 말을 먼저 쓰고 없을 때만 정의한다."""
        # Given
        asking = " ".join((REPO_ROOT / "instructions/asking-the-user.md").read_text(encoding="utf-8").split())

        # When
        rules = (
            "Word the question, its header, and each option's label and description by the reply rules in the common "
            "session instructions, for a reader who sees only that dialog.",
            "When a term, abbreviation, internal component name, or code identifier that the user has not used in the "
            "conversation would appear there, use a plain phrase with the same meaning when one exists,",
            "and define the term in the same text only when no such phrase exists.",
        )

        # Then
        self.assert_in_every_context("Before asking the user anything or proposing to wait, read")
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, asking)

    def test_질문_창은_결정_대상과_항목을_쉬운_말로_밝히고_번호만으로_부르지_않으며_진행_과정을_뺀다(self):
        """질문 창을 보는 사람이 결정 대상, 영향받는 항목, 선택지별 결과를 알 수 있게 쓰고, 번호나 위치로만 항목을 부르거나 진행 과정을 되풀이하지 않는다."""
        # Given
        asking = " ".join((REPO_ROOT / "instructions/asking-the-user.md").read_text(encoding="utf-8").split())

        # When
        rules = (
            "what the decision is about, from one line that names the thing it changes;",
            "each item the choice affects, quoted or described in plain words, never only by its number or position in "
            "a text the dialog does not show;",
            "and what happens to each item under each option.",
            "Keep the question to one sentence and put details in the option descriptions or the diagram.",
            "Leave out how you reached the question, such as a reviewer's findings or earlier attempts, unless it "
            "changes which option is right.",
        )

        # Then
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, asking)

    def test_질문_창_입력은_원문_글자로_쓰고_깨진_글자_신고에는_자기_입력부터_확인한다(self):
        """구조화된 질문 도구의 입력은 유니코드 이스케이프 없이 쓰고 다시 읽으며, 깨진 글자 신고에는 자기 도구 입력을 먼저 본다."""
        # Given
        asking = " ".join((REPO_ROOT / "instructions/asking-the-user.md").read_text(encoding="utf-8").split())

        # When
        rules = (
            "write the question, its header, and each option's label and description as raw characters, never as JSON "
            "unicode escapes such as `\\uXXXX`,",
            "reread it once before sending and fix any character that differs from the word you meant.",
            "When the user reports a wrong or garbled character in a question dialog, read your own tool input as "
            "stored in the session transcript file first,",
            "Say whether the reported character is in that stored input before naming any other cause, and name the "
            "host or a plugin only when that input is correct and the shown text differs.",
        )

        # Then
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, asking)

    def test_이름_결정_배포가_바뀌면_이미_만든_산출물의_옛_값을_찾아_고치고_보고한다(self):
        """이름 변경, 결정 변경, 되돌리기 뒤에는 작업이 만들거나 올린 산출물의 옛 값을 고치거나 알리고 최종 보고에 적는다."""
        # Given
        rule = (
            "After a rename, a changed decision, or a rollback, update or report every earlier output of the work that "
            "still shows the old value, such as code, documents, descriptions, tickets, or comments, and list each in "
            "the report."
        )

        # When / Then
        self.assert_in_every_context(rule)

    def test_스킬의_워크플로는_사용자가_줄일_수_있는_기본_실행이고_skill_builder는_단계를_따로_실행할_수_있게_쓴다(self):
        """세션 문맥은 요청한 단계만 실행하고 건너뛴 단계를 알리게 하며, skill-builder는 단계마다 입력을 적어 일부만 실행할 수 있게 한다."""
        # Given
        builder = " ".join((REPO_ROOT / "skills/skill-builder/SKILL.md").read_text(encoding="utf-8").split())

        # When
        default_run = "Write the workflow as its default run: give each step the inputs it needs and what it produces"

        # Then
        self.assert_in_every_context(
            "A skill's workflow is a default the user can narrow: run only the steps asked for, and name skipped ones at the end."
        )
        self.assertIn(default_run, builder)

    def test_반복될_교정과_조사는_승인을_받아_작업별로_읽히는_짧은_저장소_지침이나_ADR로_남긴다(self):
        """세션 문맥은 작업을 끝내기 전에 저장소 지침 참조를 읽게 하고, 참조는 승인, 검사 우선, 진입 줄, 짧은 ADR, 교체를 정한다."""
        # Given
        guidance = " ".join((REPO_ROOT / "instructions/repository-guidance.md").read_text(encoding="utf-8").split())

        # When
        rules = (
            "recommend recording it in one line, and change no file until the user approves",
            "recommend the `mistake-enforcer` skill instead of a written rule",
            "Keep in that file only rules that every task needs.",
            '"Before <task>, read <file>."',
            "a short ADR of at most 30 lines",
            "Replace or delete an outdated entry instead of appending to it.",
        )

        # Then
        self.assert_in_every_context(
            "Before ending work in which a user correction or a costly investigation is likely to recur, read"
        )
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, guidance)

    def test_사용자가_직접_쓴_turbogoal이나_ulw는_빠른_모드를_켜고_품질과_승인_규칙은_그대로_둔다(self):
        """세션 문맥은 붙여 넣거나 인용한 글이 아닌 사용자 글의 키워드에만 빠른 모드 참조를 읽게 하고, 참조는 로컬 상한과 유지할 규칙을 정한다."""
        # Given
        fast = " ".join((REPO_ROOT / "instructions/fast-mode.md").read_text(encoding="utf-8").split())

        # When
        rules = (
            "Text the user pasted or quoted, and code spans and blocks, do not count.",
            "Run at most the limit the plugin reports of local processes at once",
            "Keep the pinned or user-requested models and efforts, every required check, the final review, and every approval rule.",
            "Never parallelize tightly dependent steps.",
        )

        # Then
        self.assert_in_every_context(
            "When the user's own words, not pasted or quoted text or code, contain the word `turbogoal` or `ulw`, read"
        )
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, fast)


if __name__ == "__main__":
    unittest.main()
