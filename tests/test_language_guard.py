from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "language_guard.py"
HOOKS = json.loads((REPO_ROOT / "hooks/hooks.json").read_text())["hooks"]

ENGLISH = "I checked the deployment logs and restarted the worker. Everything looks healthy now."
KOREAN = "배포 로그를 확인하고 worker를 다시 시작했습니다. 지금은 모든 상태가 정상입니다."
KOREAN_TECH = "`kubectl rollout status` 결과를 확인했습니다. API 서버와 PostgreSQL 연결이 정상이라서 배포를 계속 진행합니다."

STOP_REASON = (
    "Your last reply was not written in Korean. Rewrite the whole reply in Korean now. "
    "Keep code, identifiers, paths, and commands as they are, and put any text the user asked for "
    "in another language in a code block or block quote."
)
REMINDER = (
    "Your previous progress message was not written in Korean. "
    "Write every following message to the user, including progress updates, in Korean."
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load_module("language_guard_under_test", SCRIPT)


def text_block(text):
    return {"type": "text", "text": text}


def tool_use_block(tool_use_id):
    return {"type": "tool_use", "id": tool_use_id, "name": "Bash", "input": {"command": "true"}}


def claude_assistant(blocks, message_id="msg_1", model="claude-sonnet-5-5", sidechain=False):
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "message": {"id": message_id, "type": "message", "role": "assistant", "model": model, "content": blocks},
    }


def claude_user(text):
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}}


def codex_item(payload):
    return {"timestamp": "2026-01-01T00:00:00.000Z", "type": "response_item", "payload": payload}


def codex_message(role, text, phase=None):
    payload = {
        "type": "message",
        "role": role,
        "content": [{"type": "output_text" if role == "assistant" else "input_text", "text": text}],
    }
    if phase:
        payload["phase"] = phase
    return codex_item(payload)


def codex_call(call_id, kind="function_call"):
    return codex_item({"type": kind, "call_id": call_id, "name": "shell", "arguments": "{}"})


def codex_output(call_id, kind="function_call_output"):
    return codex_item({"type": kind, "call_id": call_id, "output": "ok"})


class LanguageGuardCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.config = self.base / "config"
        self.project = self.base / "project"
        self.data = self.base / "data"
        for directory in (self.home, self.config, self.project / ".claude"):
            directory.mkdir(parents=True)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)

    def write_settings(self, path: Path, language: object):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"language": language}), encoding="utf-8")

    def use_korean_setting(self):
        self.write_settings(self.config / "settings.json", "Korean")

    def write_transcript(self, entries, name="transcript.jsonl") -> str:
        path = self.base / name
        path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8")
        return str(path)

    def environment(self, host="claude", **extra) -> dict:
        env = {"PATH": os.defpath, "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config)}
        if host == "codex":
            env["PLUGIN_ROOT"] = str(REPO_ROOT)
        env.update(extra)
        return env

    def run_guard(self, event, host="claude", stdin=None, **extra):
        if stdin is None:
            stdin = json.dumps(event, ensure_ascii=False)
        data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=data,
            capture_output=True,
            env=self.environment(host, **extra),
            cwd=self.project,
            timeout=30,
        )

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")

    def output(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout)

    def stop_event(self, message=ENGLISH, **fields):
        event = {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "prompt_id": "prompt-1",
            "cwd": str(self.project),
            "stop_hook_active": False,
        }
        if message is not None:
            event["last_assistant_message"] = message
        event.update(fields)
        return event

    def post_event(self, transcript, tool_use_id="tool-1", **fields):
        event = {
            "hook_event_name": "PostToolUse",
            "session_id": "session-1",
            "cwd": str(self.project),
            "tool_name": "Bash",
            "tool_use_id": tool_use_id,
            "transcript_path": transcript,
        }
        event.update(fields)
        return event


class ResolutionTest(LanguageGuardCase):
    def test_언어_값은_영어_이름과_코드와_고유_이름으로_같은_언어가_된다(self):
        """영어 이름, ISO 코드, 고유 이름, 지역 코드가 붙은 값, 대소문자 차이는 모두 같은 언어로 해석된다."""
        # Given
        expected = {
            "Korean": ["korean", "KOREAN", "ko", "한국어", "ko-KR", "KO_kr", " ko-KR "],
            "Japanese": ["japanese", "ja", "日本語", "ja-JP"],
            "Chinese": ["chinese", "zh", "中文", "简体中文", "繁體中文", "zh_CN", "zh-Hant"],
            "Russian": ["russian", "ru", "русский", "ru-RU"],
            "Ukrainian": ["ukrainian", "uk", "українська"],
            "Greek": ["greek", "el", "ελληνικά"],
            "Arabic": ["arabic", "ar", "العربية", "ar-SA"],
            "Hebrew": ["hebrew", "he", "עברית"],
            "Thai": ["thai", "th", "ไทย"],
            "Hindi": ["hindi", "hi", "हिन्दी", "hi-IN"],
        }

        # When
        resolved = {name: [GUARD.language_name(value) for value in values] for name, values in expected.items()}

        # Then
        for name, values in resolved.items():
            with self.subTest(language=name):
                self.assertEqual(values, [name] * len(values))

    def test_지원하지_않는_언어_값은_해석되지_않는다(self):
        """영어, 프랑스어, 알 수 없는 값은 강제 대상 언어가 아니다."""
        # Given
        values = ["English", "en", "en-US", "French", "fr", "Deutsch", "xx", "", "   ", "-"]

        # When
        resolved = [GUARD.language_name(value) for value in values]

        # Then
        self.assertEqual(resolved, [None] * len(values))

    def test_Claude_설정은_프로젝트_로컬_프로젝트_사용자_순서로_우선한다(self):
        """language 값은 프로젝트 settings.local.json, 프로젝트 settings.json, 사용자 settings.json 순서로 찾는다."""
        # Given
        self.write_settings(self.config / "settings.json", "Japanese")
        event = {"cwd": str(self.project)}
        env = {"CLAUDE_CONFIG_DIR": str(self.config), "CLAUDE_PROJECT_DIR": ""}
        results = {}

        # When
        with mock.patch.dict(os.environ, env):
            results["user"] = GUARD.claude_language(event)
            self.write_settings(self.project / ".claude" / "settings.json", "Chinese")
            results["project"] = GUARD.claude_language(event)
            self.write_settings(self.project / ".claude" / "settings.local.json", "Korean")
            results["local"] = GUARD.claude_language(event)

        # Then
        self.assertEqual(results, {"user": "Japanese", "project": "Chinese", "local": "Korean"})

    def test_비어_있거나_깨진_설정_파일은_건너뛰고_다음_파일을_본다(self):
        """빈 문자열, 문자열이 아닌 값, 잘못된 JSON, 없는 파일은 건너뛰고 다음 우선순위의 값을 쓴다."""
        # Given
        self.write_settings(self.config / "settings.json", "Korean")
        (self.project / ".claude" / "settings.local.json").write_text("{not json", encoding="utf-8")
        self.write_settings(self.project / ".claude" / "settings.json", "   ")
        event = {"cwd": str(self.project)}

        # When
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)}):
            skipped = GUARD.claude_language(event)
            self.write_settings(self.project / ".claude" / "settings.json", 7)
            non_string = GUARD.claude_language(event)
            (self.project / ".claude" / "settings.json").write_text("[1, 2]", encoding="utf-8")
            non_object = GUARD.claude_language(event)

        # Then
        self.assertEqual((skipped, non_string, non_object), ("Korean", "Korean", "Korean"))

    def test_설정이_하나도_없으면_언어가_없다(self):
        """어느 settings 파일에도 language 값이 없으면 강제하지 않는다."""
        # Given
        event = {"cwd": str(self.project)}

        # When
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)}):
            value = GUARD.claude_language(event)

        # Then
        self.assertIsNone(value)

    def test_CLAUDE_PROJECT_DIR가_이벤트_cwd보다_우선한다(self):
        """프로젝트 설정 위치는 CLAUDE_PROJECT_DIR이 있으면 그 값을, 없으면 이벤트의 cwd를 쓴다."""
        # Given
        other = self.base / "other"
        self.write_settings(other / ".claude" / "settings.json", "Greek")
        self.write_settings(self.project / ".claude" / "settings.json", "Thai")
        event = {"cwd": str(self.project)}

        # When
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config), "CLAUDE_PROJECT_DIR": str(other)}):
            from_env = GUARD.claude_language(event)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config), "CLAUDE_PROJECT_DIR": ""}):
            from_cwd = GUARD.claude_language(event)

        # Then
        self.assertEqual((from_env, from_cwd), ("Greek", "Thai"))

    def test_Codex_언어는_환경_변수이고_없으면_한국어다(self):
        """HEI5ENBUG_RESPONSE_LANGUAGE의 앞뒤 공백을 지운 값을 쓰고, 없거나 비어 있으면 Korean이다."""
        # Given
        cases = {None: "Korean", "": "Korean", "   ": "Korean", " Japanese ": "Japanese", "ko-KR": "ko-KR"}
        resolved = {}

        # When
        for value in cases:
            env = {} if value is None else {"HEI5ENBUG_RESPONSE_LANGUAGE": value}
            with mock.patch.dict(os.environ, env):
                if value is None:
                    os.environ.pop("HEI5ENBUG_RESPONSE_LANGUAGE", None)
                resolved[value] = GUARD.codex_language()

        # Then
        self.assertEqual(resolved, cases)

    def test_지원하지_않는_언어로_설정하면_출력이_없다(self):
        """language가 English이면 영어 답변에도 아무것도 출력하지 않고 exit 0으로 끝난다."""
        # Given
        self.write_settings(self.config / "settings.json", "English")
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event)

        # Then
        self.assert_silent(result)

    def test_설정이_없으면_Claude_Code에서는_출력이_없다(self):
        """Claude Code에 language 설정이 없으면 영어 답변도 막지 않는다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event)

        # Then
        self.assert_silent(result)

    def test_Codex는_설정_없이도_한국어를_강제한다(self):
        """Codex에서 환경 변수가 없으면 한국어가 기본이라 영어 답변을 막는다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assertEqual(self.output(result), {"decision": "block", "reason": STOP_REASON})

    def test_Codex는_환경_변수의_언어로_강제하고_지역_코드를_받아들인다(self):
        """HEI5ENBUG_RESPONSE_LANGUAGE가 ja-JP이면 일본어를 기준으로 판단하고 사유에 Japanese를 쓴다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, host="codex", HEI5ENBUG_RESPONSE_LANGUAGE="ja-JP")

        # Then
        reason = self.output(result)["reason"]
        self.assertTrue(reason.startswith("Your last reply was not written in Japanese. "))

    def test_Codex는_지원하지_않는_환경_변수_언어면_출력이_없다(self):
        """Codex 환경 변수가 English이면 강제하지 않는다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, host="codex", HEI5ENBUG_RESPONSE_LANGUAGE="English")

        # Then
        self.assert_silent(result)

    def test_Codex에서는_Claude_설정_파일을_보지_않는다(self):
        """Codex 호스트에서는 settings.json의 language가 아니라 환경 변수와 기본값만 쓴다."""
        # Given
        self.write_settings(self.config / "settings.json", "English")
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assertEqual(self.output(result)["decision"], "block")

    def test_PLUGIN_ROOT가_다른_경로면_Claude_Code로_본다(self):
        """상속된 PLUGIN_ROOT가 이 플러그인 루트가 아니면 Claude Code 규칙을 따른다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, PLUGIN_ROOT=str(self.base))

        # Then
        self.assert_silent(result)


class ToggleTest(LanguageGuardCase):
    def test_Claude_옵션이_꺼짐_값이면_영어_답변도_출력이_없다(self):
        """CLAUDE_PLUGIN_OPTION_LANGUAGE_GUARD가 false, 0, off, no(대소문자 무시)이면 Stop과 PostToolUse 모두 출력이 없다."""
        # Given
        self.use_korean_setting()
        transcript = self.write_transcript([
            claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")]),
        ])

        for value in ("false", "0", "off", "no", "OFF", "False"):
            with self.subTest(value=value):
                # When
                stop = self.run_guard(self.stop_event(ENGLISH), CLAUDE_PLUGIN_OPTION_LANGUAGE_GUARD=value)
                post = self.run_guard(self.post_event(transcript), CLAUDE_PLUGIN_OPTION_LANGUAGE_GUARD=value)

                # Then
                self.assert_silent(stop)
                self.assert_silent(post)

    def test_Codex_변수가_꺼짐_값이면_영어_답변도_출력이_없다(self):
        """HEI5ENBUG_LANGUAGE_GUARD가 꺼짐 값이면 한국어 기본 강제도 하지 않는다."""
        # Given
        event = self.stop_event(ENGLISH)

        for value in ("false", "0", "off", "no"):
            with self.subTest(value=value):
                # When
                result = self.run_guard(event, host="codex", HEI5ENBUG_LANGUAGE_GUARD=value)

                # Then
                self.assert_silent(result)

    def test_값이_비었거나_알_수_없으면_가드는_켜진_채로_동작한다(self):
        """빈 문자열이나 인식할 수 없는 값은 기본값인 켜짐으로 읽는다."""
        # Given
        self.use_korean_setting()
        event = self.stop_event(ENGLISH)
        transcript = self.write_transcript([
            claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")]),
        ])

        for value in ("", "on", "true", "maybe"):
            with self.subTest(value=value):
                # When
                claude = self.run_guard(event, CLAUDE_PLUGIN_OPTION_LANGUAGE_GUARD=value)
                codex = self.run_guard(event, host="codex", HEI5ENBUG_LANGUAGE_GUARD=value)
                post = self.run_guard(self.post_event(transcript), CLAUDE_PLUGIN_OPTION_LANGUAGE_GUARD=value)

                # Then
                self.assertEqual(self.output(claude)["decision"], "block")
                self.assertEqual(self.output(codex)["decision"], "block")
                self.assertEqual(self.output(post)["hookSpecificOutput"]["additionalContext"], REMINDER)

    def test_호스트가_아닌_쪽의_토글은_영향을_주지_않는다(self):
        """Codex는 Claude 옵션 변수를, Claude Code는 HEI5ENBUG 변수를 읽지 않는다."""
        # Given
        self.use_korean_setting()
        event = self.stop_event(ENGLISH)

        # When
        codex = self.run_guard(event, host="codex", CLAUDE_PLUGIN_OPTION_LANGUAGE_GUARD="off")
        claude = self.run_guard(event, HEI5ENBUG_LANGUAGE_GUARD="off")

        # Then
        self.assertEqual(self.output(codex)["decision"], "block")
        self.assertEqual(self.output(claude)["decision"], "block")


class ComplianceTest(unittest.TestCase):
    def compliant(self, text, language="Korean"):
        return GUARD.is_compliant(text, language)

    def test_기술_용어가_섞인_한국어는_통과한다(self):
        """영문 기술 용어와 코드가 섞여 있어도 한국어 답변은 통과한다."""
        # Given
        texts = [
            KOREAN,
            KOREAN_TECH,
            "PostgreSQL 인덱스를 추가해서 쿼리가 빨라졌습니다. EXPLAIN ANALYZE 결과도 같이 확인했습니다.",
        ]

        # When
        results = [self.compliant(text) for text in texts]

        # Then
        self.assertEqual(results, [True, True, True])

    def test_영어_진행_안내는_통과하지_못한다(self):
        """영어로만 쓴 답변은 한국어 기준에서 실패한다."""
        # Given
        texts = [ENGLISH, "Now I will read the configuration file and then update the failing unit test accordingly."]

        # When
        results = [self.compliant(text) for text in texts]

        # Then
        self.assertEqual(results, [False, False])

    def test_코드_인용_링크_주소_태그는_측정에서_뺀다(self):
        """코드 블록, 인라인 코드, 인용, URL, 링크 대상, HTML 태그 안의 영어는 세지 않는다."""
        # Given
        english = "This is a long english sentence that would otherwise fail the measure."
        cases = {
            "fence": f"파일을 고쳤습니다.\n```python\n{english}\n```\n끝났습니다.",
            "tilde fence": f"파일을 고쳤습니다.\n~~~\n{english}\n~~~\n끝났습니다.",
            "long fence": f"결과입니다.\n````\n```\n{english}\n```\n````\n",
            "unterminated fence": f"결과입니다.\n```\n{english}\n",
            "inline code": f"이 값을 `{english}` 그대로 사용했습니다.",
            "block quote": f"원문은 다음과 같습니다.\n> {english}\n   > {english}\n",
            "url": f"자세한 내용은 https://example.com/{'a' * 40}/{'b' * 40} 에서 볼 수 있습니다.",
            "link target": f"[문서](https://example.com/{'c' * 60}) 를 참고하세요.",
            "image target": f"![그림](images/{'d' * 60}.png) 그림을 참고하세요.",
            "html tag": f'<a href="https://example.com/{"e" * 60}" class="{"f" * 30}">링크</a> 입니다.',
        }

        # When
        results = {name: (self.compliant(text), GUARD.measured_text(text)) for name, text in cases.items()}

        # Then
        for name, (ok, rest) in results.items():
            with self.subTest(case=name):
                self.assertTrue(ok, rest)

    def test_코드_밖의_영어는_측정에_남는다(self):
        """코드 블록이 있어도 그 밖에 쓴 영어 문장은 그대로 판정한다."""
        # Given
        text = f"```\ncode\n```\n{ENGLISH}\n```\nmore\n```"

        # When
        result = self.compliant(text)

        # Then
        self.assertFalse(result)

    def test_짧은_글은_언어와_관계없이_통과한다(self):
        """대상 글자와 영문자 합이 20 미만이면 영어여도 통과한다."""
        # Given
        texts = ["OK", "Done.", "Tests pass", "a" * 19, "한 줄 ok", ""]

        # When
        results = [self.compliant(text) for text in texts]

        # Then
        self.assertEqual(results, [True] * len(texts))

    def test_경계값은_합이_20이고_비율이_0점3_이상일_때_통과한다(self):
        """합이 19면 통과하고 20부터 측정하며, 비율 0.3은 통과하고 그보다 낮으면 실패한다."""
        # Given
        cases = {
            "sum 19 english": ("a" * 19, True),
            "sum 20 english": ("a" * 20, False),
            "ratio 0.30": ("가나다라마바 " + "a" * 14, True),
            "ratio 0.25": ("가나다라마 " + "a" * 15, False),
            "ratio 0.35": ("가나다라마바사 " + "a" * 13, True),
            "korean only 20": ("가" * 20, True),
        }

        # When
        results = {name: self.compliant(text) for name, (text, _) in cases.items()}

        # Then
        for name, (_, expected) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(results[name], expected)

    def test_다른_언어는_각자의_문자_범위로_센다(self):
        """일본어, 중국어, 러시아어 등은 지정한 문자 범위를 대상 글자로 센다."""
        # Given
        english = "I checked the deployment logs and restarted the worker. Everything looks healthy."
        samples = {
            "Japanese": "デプロイのログを確認して、ワーカーを再起動しました。今は正常に動いています。",
            "Chinese": "我已经检查了部署日志并重新启动了工作进程，现在一切都正常运行了，请放心。",
            "Russian": "Я проверил журналы развертывания и перезапустил обработчик. Сейчас все работает.",
            "Ukrainian": "Я перевірив журнали розгортання і перезапустив обробник. Зараз усе працює.",
            "Greek": "Έλεγξα τα αρχεία καταγραφής και επανεκκίνησα τον εργάτη. Τώρα όλα λειτουργούν.",
            "Arabic": "لقد فحصت سجلات النشر وأعدت تشغيل العامل. كل شيء يعمل بشكل جيد الآن.",
            "Hebrew": "בדקתי את יומני הפריסה והפעלתי מחדש את העובד. עכשיו הכול עובד בצורה תקינה.",
            "Thai": "ฉันตรวจสอบบันทึกการติดตั้งและรีสตาร์ทตัวทำงานแล้ว ตอนนี้ทุกอย่างทำงานปกติ",
            "Hindi": "मैंने तैनाती के लॉग जांचे और वर्कर को फिर से शुरू किया। अब सब कुछ ठीक चल रहा है।",
        }

        # When
        results = {name: (self.compliant(text, name), self.compliant(english, name)) for name, text in samples.items()}

        # Then
        for name, (own, foreign) in results.items():
            with self.subTest(language=name):
                self.assertTrue(own)
                self.assertFalse(foreign)

    def test_일본어는_가나와_한자를_중국어는_한자만_센다(self):
        """히라가나와 가타카나는 일본어에서만 대상 글자이고 중국어에서는 세지 않는다."""
        # Given
        kana = "ひらがなとカタカナだけの文章をここに長めに書いてみます。ありがとうございます。"

        # When
        japanese = GUARD.is_compliant(kana + " " + "abcdefghijklmnopqrstuvwxyz", "Japanese")
        chinese = GUARD.is_compliant(kana + " " + "abcdefghijklmnopqrstuvwxyz" * 3, "Chinese")

        # Then
        self.assertTrue(japanese)
        self.assertFalse(chinese)


class StopTest(LanguageGuardCase):
    def setUp(self):
        super().setUp()
        self.use_korean_setting()

    def test_영어_답변은_한_줄_차단_사유와_함께_막힌다(self):
        """한국어가 아닌 마지막 답변은 decision이 block이고 정해진 사유가 한 줄로 출력된다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event)

        # Then
        self.assertEqual(self.output(result), {"decision": "block", "reason": STOP_REASON})
        self.assertEqual(len(result.stdout.decode().strip().splitlines()), 1)

    def test_한국어_답변은_막지_않는다(self):
        """한국어 답변은 아무것도 출력하지 않고 exit 0으로 끝난다."""
        # Given
        event = self.stop_event(KOREAN_TECH)

        # When
        result = self.run_guard(event)

        # Then
        self.assert_silent(result)

    def test_하위_에이전트_이벤트는_건너뛴다(self):
        """agent_id가 있는 이벤트는 영어 답변이어도 출력하지 않는다."""
        # Given
        event = self.stop_event(ENGLISH, agent_id="agent-1", agent_type="worker")

        # When
        result = self.run_guard(event)

        # Then
        self.assert_silent(result)

    def test_한_턴에_최대_세_번까지만_막고_상태를_저장한다(self):
        """데이터 디렉터리가 있으면 같은 턴에서 세 번 막은 뒤 네 번째부터는 통과시키고 횟수를 기록한다."""
        # Given
        event = self.stop_event(ENGLISH, stop_hook_active=True)

        # When
        results = [self.run_guard(event, CLAUDE_PLUGIN_DATA=str(self.data)) for _ in range(5)]

        # Then
        decisions = [result.stdout != b"" for result in results]
        self.assertEqual(decisions, [True, True, True, False, False])
        state = json.loads((self.data / "language_guard_state.json").read_text())
        self.assertEqual(list(state), ["session-1:prompt-1"])
        self.assertEqual(state["session-1:prompt-1"]["count"], 3)
        self.assertAlmostEqual(state["session-1:prompt-1"]["time"], time.time(), delta=60)
        self.assertEqual([p.name for p in self.data.iterdir()], ["language_guard_state.json"])

    def test_턴마다_횟수를_따로_센다(self):
        """다른 prompt_id나 turn_id는 새 턴이라 다시 세 번까지 막고, prompt_id가 없으면 turn_id를 쓴다."""
        # Given
        first = self.stop_event(ENGLISH)
        second = self.stop_event(ENGLISH, prompt_id="prompt-2")
        codex_turn = self.stop_event(ENGLISH)
        del codex_turn["prompt_id"]
        codex_turn["turn_id"] = "turn-9"
        env = {"CLAUDE_PLUGIN_DATA": str(self.data)}

        # When
        for _ in range(4):
            self.run_guard(first, **env)
        after_cap = self.run_guard(first, **env)
        new_prompt = self.run_guard(second, **env)
        new_turn = self.run_guard(codex_turn, **env)

        # Then
        self.assert_silent(after_cap)
        self.assertEqual(self.output(new_prompt)["decision"], "block")
        self.assertEqual(self.output(new_turn)["decision"], "block")
        state = json.loads((self.data / "language_guard_state.json").read_text())
        self.assertEqual(set(state), {"session-1:prompt-1", "session-1:prompt-2", "session-1:turn-9"})

    def test_턴_식별자가_없으면_상태_파일_없이_stop_hook_active로_판단한다(self):
        """prompt_id와 turn_id가 문자열이 아니거나 비어 있으면 데이터 디렉터리가 있어도 상태를 쓰지 않고 stop_hook_active 규칙을 쓴다."""
        # Given
        env = {"CLAUDE_PLUGIN_DATA": str(self.data)}
        variants = [{}, {"prompt_id": ""}, {"prompt_id": None, "turn_id": 5}, {"prompt_id": "", "turn_id": ""}]
        events = []
        for fields in variants:
            event = self.stop_event(ENGLISH)
            del event["prompt_id"]
            event.update(fields)
            events.append(event)

        # When
        inactive = [[self.run_guard(event, **env) for _ in range(5)] for event in events]
        active = [self.run_guard({**event, "stop_hook_active": True}, **env) for event in events]

        # Then
        for results in inactive:
            for result in results:
                self.assertEqual(self.output(result)["decision"], "block")
        for result in active:
            self.assert_silent(result)
        self.assertFalse((self.data / "language_guard_state.json").exists())

    def test_턴_식별자가_있으면_식별자별로_센다(self):
        """식별자가 있으면 같은 식별자는 세 번까지 막고 다른 식별자는 따로 센다."""
        # Given
        env = {"CLAUDE_PLUGIN_DATA": str(self.data)}
        turn_a = self.stop_event(ENGLISH, prompt_id="turn-a", stop_hook_active=True)
        turn_b = self.stop_event(ENGLISH, prompt_id="turn-b", stop_hook_active=True)

        # When
        a_results = [self.run_guard(turn_a, **env) for _ in range(4)]
        b_first = self.run_guard(turn_b, **env)

        # Then
        self.assertEqual([r.stdout != b"" for r in a_results], [True, True, True, False])
        self.assertEqual(self.output(b_first)["decision"], "block")
        state = json.loads((self.data / "language_guard_state.json").read_text())
        self.assertEqual({k: v["count"] for k, v in state.items()}, {"session-1:turn-a": 3, "session-1:turn-b": 1})

    def test_PLUGIN_DATA도_상태_위치로_쓴다(self):
        """CLAUDE_PLUGIN_DATA가 없으면 PLUGIN_DATA 디렉터리에 상태를 저장한다."""
        # Given
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, host="codex", PLUGIN_DATA=str(self.data))

        # Then
        self.assertEqual(self.output(result)["decision"], "block")
        self.assertTrue((self.data / "language_guard_state.json").is_file())

    def test_CLAUDE_PLUGIN_DATA가_PLUGIN_DATA보다_우선한다(self):
        """두 변수가 모두 있으면 CLAUDE_PLUGIN_DATA 쪽에만 상태를 저장한다."""
        # Given
        event = self.stop_event(ENGLISH)
        other = self.base / "other-data"

        # When
        self.run_guard(event, CLAUDE_PLUGIN_DATA=str(self.data), PLUGIN_DATA=str(other))

        # Then
        self.assertTrue((self.data / "language_guard_state.json").is_file())
        self.assertFalse(other.exists())

    def test_7일이_지난_상태는_정리한다(self):
        """7일보다 오래된 항목은 지우고 최근 항목은 남긴다."""
        # Given
        self.data.mkdir()
        now = time.time()
        old = {"count": 3, "time": now - 8 * 24 * 3600}
        recent = {"count": 1, "time": now - 6 * 24 * 3600}
        broken = {"count": "x"}
        (self.data / "language_guard_state.json").write_text(
            json.dumps({"old:key": old, "recent:key": recent, "broken:key": broken, "list:key": [1]})
        )
        event = self.stop_event(ENGLISH)

        # When
        self.run_guard(event, CLAUDE_PLUGIN_DATA=str(self.data))

        # Then
        state = json.loads((self.data / "language_guard_state.json").read_text())
        self.assertEqual(set(state), {"recent:key", "session-1:prompt-1"})

    def test_상태_파일이_깨져_있어도_새로_시작한다(self):
        """잘못된 JSON 상태 파일은 무시하고 막은 뒤 새 상태를 기록한다."""
        # Given
        self.data.mkdir()
        (self.data / "language_guard_state.json").write_text("{broken", encoding="utf-8")
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event, CLAUDE_PLUGIN_DATA=str(self.data))

        # Then
        self.assertEqual(self.output(result)["decision"], "block")
        state = json.loads((self.data / "language_guard_state.json").read_text())
        self.assertEqual(state["session-1:prompt-1"]["count"], 1)

    def test_데이터_디렉터리가_없으면_stop_hook_active가_아닐_때만_막는다(self):
        """데이터 디렉터리가 없으면 stop_hook_active가 true일 때 통과시키고 false나 누락이면 막는다."""
        # Given
        events = {
            "inactive": self.stop_event(ENGLISH, stop_hook_active=False),
            "active": self.stop_event(ENGLISH, stop_hook_active=True),
        }
        missing = self.stop_event(ENGLISH)
        del missing["stop_hook_active"]
        events["missing"] = missing

        # When
        results = {name: self.run_guard(event) for name, event in events.items()}

        # Then
        self.assertEqual(self.output(results["inactive"])["decision"], "block")
        self.assertEqual(self.output(results["missing"])["decision"], "block")
        self.assert_silent(results["active"])

    def test_저장할_수_없는_데이터_디렉터리는_stop_hook_active로_대신한다(self):
        """상태를 쓸 수 없으면 데이터 디렉터리가 없을 때와 같은 규칙을 쓴다."""
        # Given
        blocker = self.base / "blocker"
        blocker.write_text("file", encoding="utf-8")
        unusable = blocker / "nested"
        active = self.stop_event(ENGLISH, stop_hook_active=True)
        inactive = self.stop_event(ENGLISH, stop_hook_active=False)

        # When
        stopped = self.run_guard(active, CLAUDE_PLUGIN_DATA=str(unusable))
        blocked = self.run_guard(inactive, CLAUDE_PLUGIN_DATA=str(unusable))

        # Then
        self.assert_silent(stopped)
        self.assertEqual(self.output(blocked)["decision"], "block")

    def test_Claude_기록에서_마지막_답변을_읽는다(self):
        """last_assistant_message가 없으면 Claude Code 기록의 마지막 일반 assistant 메시지를 본다."""
        # Given
        transcript = self.write_transcript(
            [
                claude_user("질문입니다"),
                claude_assistant([text_block(KOREAN)], message_id="m1"),
                claude_user("다음 질문입니다"),
                claude_assistant([text_block(ENGLISH)], message_id="m2"),
            ]
        )
        event = self.stop_event(None, transcript_path=transcript)

        # When
        result = self.run_guard(event)

        # Then
        self.assertEqual(self.output(result)["decision"], "block")

    def test_Claude_기록은_사이드체인과_합성_메시지를_건너뛴다(self):
        """사이드체인 메시지와 model이 <synthetic>인 메시지는 마지막 답변으로 보지 않는다."""
        # Given
        transcript = self.write_transcript(
            [
                claude_assistant([text_block(KOREAN)], message_id="m1"),
                claude_assistant([text_block(ENGLISH)], message_id="m2", sidechain=True),
                claude_assistant([text_block("No response requested. Please continue the work.")], message_id="m3", model="<synthetic>"),
            ]
        )
        event = self.stop_event(None, transcript_path=transcript)

        # When
        result = self.run_guard(event)

        # Then
        self.assert_silent(result)

    def test_Claude_기록은_같은_메시지의_텍스트_블록을_모두_합친다(self):
        """같은 message.id로 나뉜 항목의 텍스트 블록과 문자열 content를 이어 붙여 판정한다."""
        # Given
        transcript = self.write_transcript(
            [
                claude_assistant([text_block("배포를 끝냈습니다.")], message_id="m1"),
                claude_assistant([text_block(ENGLISH)], message_id="m1"),
            ]
        )
        string_content = self.write_transcript(
            [{"type": "assistant", "message": {"id": "m2", "role": "assistant", "content": ENGLISH}}],
            name="string.jsonl",
        )

        # When
        split = self.run_guard(self.stop_event(None, transcript_path=transcript))
        plain = self.run_guard(self.stop_event(None, transcript_path=string_content))

        # Then
        self.assertEqual(self.output(split)["decision"], "block")
        self.assertEqual(self.output(plain)["decision"], "block")

    def test_Codex_기록에서_마지막_최종_답변을_읽는다(self):
        """last_assistant_message가 없으면 Codex 기록의 final_answer를 우선해 본다."""
        # Given
        transcript = self.write_transcript(
            [
                {"type": "session_meta", "payload": {"id": "s1", "source": "cli"}},
                codex_message("user", "질문입니다"),
                codex_message("assistant", KOREAN, phase="commentary"),
                codex_call("c1"),
                codex_output("c1"),
                codex_message("assistant", ENGLISH, phase="final_answer"),
            ]
        )
        event = self.stop_event(None, transcript_path=transcript)

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assertEqual(self.output(result)["decision"], "block")

    def test_Codex_기록은_final_answer가_있으면_뒤의_다른_메시지보다_우선한다(self):
        """final_answer가 한국어이면 그 앞이나 뒤의 영어 commentary는 판정하지 않는다."""
        # Given
        transcript = self.write_transcript(
            [
                codex_message("user", "질문입니다"),
                codex_message("assistant", ENGLISH, phase="commentary"),
                codex_message("assistant", KOREAN, phase="final_answer"),
                codex_message("assistant", ENGLISH, phase="commentary"),
            ]
        )
        event = self.stop_event(None, transcript_path=transcript)

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assert_silent(result)

    def test_Codex_기록은_phase가_없으면_마지막_assistant_메시지를_본다(self):
        """phase가 없는 기록은 마지막 assistant 메시지의 output_text를 이어 붙여 판정한다."""
        # Given
        transcript = self.write_transcript(
            [codex_message("user", "질문입니다"), codex_message("assistant", KOREAN), codex_message("assistant", ENGLISH)]
        )
        event = self.stop_event(None, transcript_path=transcript)

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assertEqual(self.output(result)["decision"], "block")

    def test_Codex_기록은_이전_턴의_답변을_보지_않는다(self):
        """사용자 메시지 앞의 이전 턴 영어 답변은 이번 턴 판정에 쓰지 않는다."""
        # Given
        transcript = self.write_transcript(
            [
                codex_message("assistant", ENGLISH, phase="final_answer"),
                codex_message("user", "다음 질문입니다"),
            ]
        )
        event = self.stop_event(None, transcript_path=transcript)

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assert_silent(result)

    def test_줄_구분_문자가_든_기록에서도_마지막_답변을_읽는다(self):
        """U+2028, U+2029, U+0085가 그대로 든 Claude와 Codex 기록 모두 마지막 영어 답변을 찾아 막는다."""
        # Given
        separators = "  \u0085"
        claude = self.write_transcript(
            [claude_user(f"질문{separators}입니다"), claude_assistant([text_block(f"{ENGLISH}{separators}Done.")])],
            name="claude.jsonl",
        )
        codex = self.write_transcript(
            [codex_message("user", f"질문{separators}입니다"), codex_message("assistant", f"{ENGLISH}{separators}Done.", phase="final_answer")],
            name="codex.jsonl",
        )

        # When
        claude_result = self.run_guard(self.stop_event(None, transcript_path=claude))
        codex_result = self.run_guard(self.stop_event(None, transcript_path=codex), host="codex")

        # Then
        self.assertEqual(self.output(claude_result)["decision"], "block")
        self.assertEqual(self.output(codex_result)["decision"], "block")

    def test_답변도_기록도_없으면_출력이_없다(self):
        """last_assistant_message, 기록 경로, 기록 파일이 모두 없으면 조용히 끝난다."""
        # Given
        events = [
            self.stop_event(None),
            self.stop_event(None, transcript_path=str(self.base / "missing.jsonl")),
            self.stop_event(None, transcript_path=12),
            self.stop_event("   "),
            self.stop_event(None, transcript_path=self.write_transcript([claude_user("질문")])),
        ]

        # When
        results = [self.run_guard(event) for event in events]

        # Then
        for result in results:
            self.assert_silent(result)


class PostToolUseTest(LanguageGuardCase):
    def setUp(self):
        super().setUp()
        self.use_korean_setting()

    def reminder(self):
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": REMINDER}}

    def test_Claude_영어_진행_안내_뒤의_첫_도구_호출은_알림을_받는다(self):
        """영어 텍스트 바로 뒤의 tool_use 결과에는 한국어로 쓰라는 추가 컨텍스트를 출력한다."""
        # Given
        transcript = self.write_transcript(
            [claude_user("작업해 주세요"), claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])]
        )
        event = self.post_event(transcript)

        # When
        result = self.run_guard(event)

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_Claude_한_메시지를_나눈_항목도_하나로_묶어_첫_도구에만_알린다(self):
        """같은 message.id가 항목별로 나뉘어도 첫 tool_use에만 알리고 병렬 호출의 나머지에는 알리지 않는다."""
        # Given
        transcript = self.write_transcript(
            [
                claude_assistant([text_block(ENGLISH)], message_id="m1"),
                claude_assistant([tool_use_block("tool-1")], message_id="m1"),
                claude_assistant([tool_use_block("tool-2")], message_id="m1"),
            ]
        )

        # When
        results = [self.run_guard(self.post_event(transcript, tool_use_id=tid)) for tid in ("tool-1", "tool-2")]

        # Then
        self.assertEqual(self.output(results[0]), self.reminder())
        self.assert_silent(results[1])

    def test_Claude_한_항목에_든_병렬_호출도_첫_도구에만_알린다(self):
        """한 항목 안에 tool_use가 여럿이어도 첫 번째에만 알린다."""
        # Given
        transcript = self.write_transcript(
            [claude_assistant([text_block(ENGLISH), tool_use_block("tool-1"), tool_use_block("tool-2")])]
        )

        # When
        results = [self.run_guard(self.post_event(transcript, tool_use_id=tid)) for tid in ("tool-1", "tool-2")]

        # Then
        self.assertEqual(self.output(results[0]), self.reminder())
        self.assert_silent(results[1])

    def test_Claude_한국어_진행_안내에는_알리지_않는다(self):
        """도구 호출 앞의 텍스트가 한국어이면 출력이 없다."""
        # Given
        transcript = self.write_transcript([claude_assistant([text_block(KOREAN_TECH), tool_use_block("tool-1")])])

        # When
        result = self.run_guard(self.post_event(transcript))

        # Then
        self.assert_silent(result)

    def test_Claude_앞선_텍스트가_없는_도구_호출에는_알리지_않는다(self):
        """tool_use만 있거나 텍스트가 tool_use 뒤에 있으면 출력이 없다."""
        # Given
        only_call = self.write_transcript([claude_assistant([tool_use_block("tool-1")])], name="a.jsonl")
        text_after = self.write_transcript(
            [claude_assistant([tool_use_block("tool-1"), text_block(ENGLISH)])], name="b.jsonl"
        )
        previous_message = self.write_transcript(
            [claude_assistant([text_block(ENGLISH)], message_id="m1"), claude_assistant([tool_use_block("tool-1")], message_id="m2")],
            name="c.jsonl",
        )

        # When
        results = [self.run_guard(self.post_event(path)) for path in (only_call, text_after, previous_message)]

        # Then
        for result in results:
            self.assert_silent(result)

    def test_Claude_기록에_없는_tool_use_id에는_알리지_않는다(self):
        """tool_use_id가 기록에 없거나 비어 있으면 출력이 없다."""
        # Given
        transcript = self.write_transcript([claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])])

        # When
        unknown = self.run_guard(self.post_event(transcript, tool_use_id="tool-9"))
        empty = self.run_guard(self.post_event(transcript, tool_use_id=""))
        missing_event = self.post_event(transcript)
        del missing_event["tool_use_id"]
        missing = self.run_guard(missing_event)

        # Then
        for result in (unknown, empty, missing):
            self.assert_silent(result)

    def test_Codex_영어_진행_안내_뒤의_첫_도구_호출은_알림을_받는다(self):
        """영어 assistant 메시지 바로 뒤의 호출 항목에는 알림을 출력한다."""
        # Given
        transcript = self.write_transcript(
            [
                {"type": "session_meta", "payload": {"id": "s1"}},
                codex_message("user", "작업해 주세요"),
                codex_item({"type": "reasoning", "summary": []}),
                codex_message("assistant", ENGLISH, phase="commentary"),
                codex_call("call-1"),
            ]
        )
        event = self.post_event(transcript, tool_use_id="call-1")

        # When
        result = self.run_guard(event, host="codex")

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_Codex_호출_종류와_관계없이_앞선_텍스트를_찾는다(self):
        """function_call, custom_tool_call, local_shell_call 등 _call로 끝나는 모든 항목을 호출로 본다."""
        # Given
        kinds = ["function_call", "custom_tool_call", "local_shell_call", "web_search_call"]
        transcripts = {
            kind: self.write_transcript(
                [codex_message("user", "작업해 주세요"), codex_message("assistant", ENGLISH), codex_call("call-1", kind)],
                name=f"{kind}.jsonl",
            )
            for kind in kinds
        }

        # When
        results = {kind: self.run_guard(self.post_event(path, tool_use_id="call-1"), host="codex") for kind, path in transcripts.items()}

        # Then
        for kind, result in results.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.output(result), self.reminder())

    def test_Codex_병렬_호출과_도구_출력_뒤의_호출에는_알리지_않는다(self):
        """텍스트 뒤 첫 호출에만 알리고, 앞에 다른 호출이나 도구 출력이 있으면 알리지 않는다."""
        # Given
        transcript = self.write_transcript(
            [
                codex_message("user", "작업해 주세요"),
                codex_message("assistant", ENGLISH),
                codex_call("call-1"),
                codex_call("call-2"),
                codex_output("call-1"),
                codex_output("call-2"),
                codex_call("call-3", "custom_tool_call"),
            ]
        )

        # When
        results = {cid: self.run_guard(self.post_event(transcript, tool_use_id=cid), host="codex") for cid in ("call-1", "call-2", "call-3")}

        # Then
        self.assertEqual(self.output(results["call-1"]), self.reminder())
        self.assert_silent(results["call-2"])
        self.assert_silent(results["call-3"])

    def test_Codex_도구_출력_뒤_새_텍스트_다음_호출에는_다시_알린다(self):
        """도구 출력 뒤에 새 영어 진행 안내가 나오면 그 다음 첫 호출에도 알린다."""
        # Given
        transcript = self.write_transcript(
            [
                codex_message("user", "작업해 주세요"),
                codex_message("assistant", KOREAN),
                codex_call("call-1"),
                codex_output("call-1"),
                codex_message("assistant", ENGLISH),
                codex_call("call-2"),
            ]
        )

        # When
        first = self.run_guard(self.post_event(transcript, tool_use_id="call-1"), host="codex")
        second = self.run_guard(self.post_event(transcript, tool_use_id="call-2"), host="codex")

        # Then
        self.assert_silent(first)
        self.assertEqual(self.output(second), self.reminder())

    def test_Codex_사용자_메시지_앞의_텍스트는_쓰지_않는다(self):
        """앞선 assistant 텍스트가 사용자 메시지 너머에 있으면 알리지 않는다."""
        # Given
        transcript = self.write_transcript(
            [codex_message("assistant", ENGLISH), codex_message("user", "작업해 주세요"), codex_call("call-1")]
        )

        # When
        result = self.run_guard(self.post_event(transcript, tool_use_id="call-1"), host="codex")

        # Then
        self.assert_silent(result)

    def test_Codex_한국어_텍스트와_텍스트_없는_호출에는_알리지_않는다(self):
        """한국어 텍스트 뒤 호출이나 텍스트 없이 시작한 호출에는 출력이 없다."""
        # Given
        korean = self.write_transcript(
            [codex_message("user", "작업"), codex_message("assistant", KOREAN_TECH), codex_call("call-1")], name="k.jsonl"
        )
        bare = self.write_transcript([codex_message("user", "작업"), codex_call("call-1")], name="b.jsonl")

        # When
        results = [self.run_guard(self.post_event(path, tool_use_id="call-1"), host="codex") for path in (korean, bare)]

        # Then
        for result in results:
            self.assert_silent(result)

    def test_Codex_여러_assistant_메시지는_이어_붙여_판정한다(self):
        """호출 앞에 assistant 메시지가 여러 개이면 모두 합친 글로 판정한다."""
        # Given
        transcript = self.write_transcript(
            [
                codex_message("user", "작업"),
                codex_message("assistant", ENGLISH),
                codex_message("assistant", "Next I will run the tests and then report the result back to you."),
                codex_call("call-1"),
            ]
        )

        # When
        result = self.run_guard(self.post_event(transcript, tool_use_id="call-1"), host="codex")

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_기록이_없거나_깨져도_출력이_없다(self):
        """기록 경로가 없거나, 파일이 없거나, 디렉터리이거나, 비어 있거나, 전부 깨진 줄이면 조용히 끝난다."""
        # Given
        empty = self.base / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        garbage = self.base / "garbage.jsonl"
        garbage.write_text("not json\n{\n[1, 2]\n\"text\"\n", encoding="utf-8")
        events = [
            self.post_event(None),
            self.post_event(5),
            self.post_event(str(self.base / "missing.jsonl")),
            self.post_event(str(self.base)),
            self.post_event(str(empty)),
            self.post_event(str(garbage)),
        ]

        # When
        results = [self.run_guard(event) for event in events]

        # Then
        for result in results:
            self.assert_silent(result)

    def test_깨진_줄이_섞여_있어도_나머지_기록으로_판단한다(self):
        """잘못된 줄은 무시하고 읽을 수 있는 항목으로 알림을 결정한다."""
        # Given
        path = self.base / "mixed.jsonl"
        good = json.dumps(claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")]))
        path.write_text(f"garbage\n{{\"type\": \n{good}\n[]\n", encoding="utf-8")

        # When
        result = self.run_guard(self.post_event(str(path)))

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_기록은_끝의_4MiB만_읽는다(self):
        """4 MiB보다 앞에 있는 항목은 찾지 못하고, 뒤쪽 항목은 잘린 첫 줄과 관계없이 찾는다."""
        # Given
        filler = json.dumps(claude_user("x" * 900)) + "\n"
        padding = filler * (5 * 1024 * 1024 // len(filler) + 1)
        target = json.dumps(claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])) + "\n"
        head = self.base / "head.jsonl"
        head.write_text(target + padding, encoding="utf-8")
        tail = self.base / "tail.jsonl"
        tail.write_text(padding + target, encoding="utf-8")

        # When
        lost = self.run_guard(self.post_event(str(head)))
        found = self.run_guard(self.post_event(str(tail)))

        # Then
        self.assert_silent(lost)
        self.assertEqual(self.output(found), self.reminder())

    def test_Claude_JSON_문자열_안의_줄_구분_문자가_있어도_알림을_받는다(self):
        """U+2028, U+2029, U+0085가 JSON 문자열 안에 그대로 있어도 그 줄을 한 항목으로 읽어 알림을 출력한다."""
        # Given
        separators = "  \u0085"
        transcript = self.write_transcript(
            [
                claude_user(f"작업해 주세요{separators}부탁합니다"),
                claude_assistant([text_block(f"{ENGLISH}{separators}Next I will run the tests."), tool_use_block("tool-1")]),
            ]
        )

        # When
        result = self.run_guard(self.post_event(transcript))

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_Codex_JSON_문자열_안의_줄_구분_문자가_있어도_알림을_받는다(self):
        """Codex 기록의 assistant 메시지에 줄 구분 문자가 그대로 있어도 호출 앞 텍스트를 찾아 알림을 출력한다."""
        # Given
        separators = "  \u0085"
        transcript = self.write_transcript(
            [
                codex_message("user", f"작업해 주세요{separators}부탁합니다"),
                codex_message("assistant", f"{ENGLISH}{separators}Next I will run the tests."),
                codex_call("call-1"),
            ]
        )

        # When
        result = self.run_guard(self.post_event(transcript, tool_use_id="call-1"), host="codex")

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_CRLF로_끝나는_기록_줄도_읽는다(self):
        """줄 끝이 CRLF인 기록도 각 줄을 올바르게 읽어 알림을 출력한다."""
        # Given
        entry = claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])
        path = self.base / "crlf.jsonl"
        path.write_bytes((json.dumps(claude_user("작업"), ensure_ascii=False) + "\r\n" + json.dumps(entry, ensure_ascii=False) + "\r\n").encode("utf-8"))

        # When
        result = self.run_guard(self.post_event(str(path)))

        # Then
        self.assertEqual(self.output(result), self.reminder())

    def test_하위_에이전트_이벤트는_건너뛴다(self):
        """agent_id가 있는 PostToolUse 이벤트는 영어 텍스트여도 출력하지 않는다."""
        # Given
        transcript = self.write_transcript([claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])])
        event = self.post_event(transcript, agent_id="agent-1", agent_type="worker")

        # When
        result = self.run_guard(event)

        # Then
        self.assert_silent(result)

    def test_언어가_지원되지_않으면_알리지_않는다(self):
        """language가 English이면 영어 진행 안내에도 출력이 없다."""
        # Given
        self.write_settings(self.config / "settings.json", "English")
        transcript = self.write_transcript([claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])])

        # When
        result = self.run_guard(self.post_event(transcript))

        # Then
        self.assert_silent(result)


class RobustnessTest(LanguageGuardCase):
    def test_잘못된_표준_입력은_출력_없이_exit_0으로_끝난다(self):
        """빈 입력, JSON이 아닌 입력, 객체가 아닌 JSON, 잘못된 UTF-8은 오류 없이 조용히 끝난다."""
        # Given
        self.use_korean_setting()
        inputs = [b"", b"not json", b"{", b"[]", b"null", b"7", b'"text"', b"\xff\xfe\x00", b'{"hook_event_name": 1}', b'{"hook_event_name": ["Stop"]}']

        # When
        results = [self.run_guard(None, stdin=data) for data in inputs]

        # Then
        for data, result in zip(inputs, results):
            with self.subTest(stdin=data):
                self.assert_silent(result)
                self.assertEqual(result.stderr, b"")

    def test_알_수_없는_이벤트와_필드_누락은_출력이_없다(self):
        """처리하지 않는 이벤트 이름이나 필수 필드가 빠진 이벤트는 조용히 끝난다."""
        # Given
        self.use_korean_setting()
        events = [
            {"hook_event_name": "SessionStart", "last_assistant_message": ENGLISH},
            {"hook_event_name": "PreToolUse", "tool_use_id": "tool-1"},
            {"last_assistant_message": ENGLISH},
            {"hook_event_name": "Stop"},
            {"hook_event_name": "Stop", "last_assistant_message": 7},
            {"hook_event_name": "PostToolUse"},
            {"hook_event_name": "PostToolUse", "tool_use_id": 3, "transcript_path": "x"},
        ]

        # When
        results = [self.run_guard(event) for event in events]

        # Then
        for result in results:
            self.assert_silent(result)

    def test_읽을_수_없는_설정_파일은_건너뛰고_계속한다(self):
        """settings.json이 잘못된 JSON이거나 디렉터리여도 오류 없이 다음 파일로 넘어간다."""
        # Given
        (self.config / "settings.json").write_text("{broken", encoding="utf-8")
        (self.project / ".claude" / "settings.local.json").mkdir()
        self.write_settings(self.project / ".claude" / "settings.json", "Korean")
        event = self.stop_event(ENGLISH)

        # When
        result = self.run_guard(event)

        # Then
        self.assertEqual(self.output(result)["decision"], "block")

    def test_차단_출력은_도구_호출을_거부하는_필드를_담지_않는다(self):
        """어느 출력에도 permissionDecision 같은 거부 필드가 없다."""
        # Given
        self.use_korean_setting()
        transcript = self.write_transcript([claude_assistant([text_block(ENGLISH), tool_use_block("tool-1")])])
        stop = self.run_guard(self.stop_event(ENGLISH))
        post = self.run_guard(self.post_event(transcript))

        # When
        outputs = [stop.stdout.decode(), post.stdout.decode()]

        # Then
        for output in outputs:
            self.assertNotIn("deny", output)
            self.assertNotIn("permissionDecision", output)


class RegistrationTest(LanguageGuardCase):
    def test_hooks_json은_PostToolUse와_Stop에_가드를_등록한다(self):
        """PostToolUse와 Stop은 matcher 없이 language_guard.py를 timeout 5로 실행한다."""
        # Given
        expected_command = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/language_guard.py"'

        # When
        entries = {
            event: [group for group in HOOKS[event] if "language_guard.py" in group["hooks"][0]["command"]]
            for event in ("PostToolUse", "Stop")
        }

        # Then
        for event, groups in entries.items():
            with self.subTest(event=event):
                self.assertEqual(len(groups), 1)
                self.assertNotIn("matcher", groups[0])
                self.assertEqual(groups[0]["hooks"], [{"type": "command", "command": expected_command, "timeout": 5}])

    def test_기존_훅_등록은_바뀌지_않는다(self):
        """SessionStart, SubagentStart, PreToolUse 항목은 그대로다."""
        # Given
        session = [{"hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_context.py"', "timeout": 10}]}]
        guard = [
            {
                "matcher": "Agent|Task",
                "hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_guard.py"', "timeout": 5}],
            }
        ]

        # When
        names = set(HOOKS)

        # Then
        self.assertEqual(names, {"SessionStart", "SubagentStart", "PreToolUse", "PermissionRequest", "PostToolUse", "Stop"})
        self.assertEqual(HOOKS["SessionStart"], session)
        self.assertEqual(HOOKS["SubagentStart"], session)
        self.assertEqual(HOOKS["PreToolUse"][: len(guard)], guard)

    def test_등록된_명령은_플러그인_루트에서_실제로_실행된다(self):
        """hooks.json의 명령 문자열을 셸로 실행하면 Stop 입력에 차단 출력을 낸다."""
        # Given
        self.use_korean_setting()
        handler = HOOKS["Stop"][0]["hooks"][0]
        env = self.environment(CLAUDE_PLUGIN_ROOT=str(REPO_ROOT), PATH=f"{self.bin}{os.pathsep}{os.defpath}")

        # When
        result = subprocess.run(
            handler["command"],
            shell=True,
            input=json.dumps(self.stop_event(ENGLISH)),
            text=True,
            capture_output=True,
            env=env,
            cwd=self.project,
            timeout=handler["timeout"] * 6,
        )

        # Then
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"decision": "block", "reason": STOP_REASON})


class SessionContextLanguageTest(unittest.TestCase):
    def render(self, host, language=None):
        module = load_module("session_context_under_language_test", REPO_ROOT / "scripts" / "session_context.py")
        env = {} if language is None else {"HEI5ENBUG_RESPONSE_LANGUAGE": language}
        with mock.patch.dict(os.environ, env):
            if language is None:
                os.environ.pop("HEI5ENBUG_RESPONSE_LANGUAGE", None)
            return module.render_context(REPO_ROOT, host)

    def test_Codex_컨텍스트는_기본_언어_줄로_끝난다(self):
        """환경 변수가 없으면 Codex 컨텍스트의 마지막 줄이 Response language: Korean. 이다."""
        # Given
        host = "codex"

        # When
        context = self.render(host)

        # Then
        self.assertEqual(context.rstrip("\n").splitlines()[-1], "Response language: Korean.")
        self.assertEqual(context.count("Response language:"), 1)

    def test_Codex_컨텍스트는_환경_변수_언어로_끝난다(self):
        """환경 변수 값은 공백을 지운 뒤 그대로 마지막 줄에 쓴다."""
        # Given
        host = "codex"

        # When
        context = self.render(host, " Japanese ")

        # Then
        self.assertEqual(context.rstrip("\n").splitlines()[-1], "Response language: Japanese.")

    def test_Codex_컨텍스트는_빈_환경_변수면_한국어로_끝난다(self):
        """환경 변수가 비어 있으면 기본값 Korean을 쓴다."""
        # Given
        host = "codex"

        # When
        context = self.render(host, "  ")

        # Then
        self.assertEqual(context.rstrip("\n").splitlines()[-1], "Response language: Korean.")

    def test_Claude_컨텍스트에는_언어_줄이_없다(self):
        """Claude Code 컨텍스트는 language 설정이 이미 전달되므로 언어 줄을 더하지 않는다."""
        # Given
        host = "claude"

        # When
        context = self.render(host, "Japanese")

        # Then
        self.assertNotIn("Response language:", context)

    def test_두_호스트_모두_응답_언어_지침을_받고_예산을_지킨다(self):
        """공통 지침의 응답 언어 항목과 Claude Code 전용 한 줄이 들어가고 9,000바이트 미만이다."""
        # Given
        hosts = ("codex", "claude")

        # When
        contexts = {host: self.render(host) for host in hosts}

        # Then
        for host, context in contexts.items():
            with self.subTest(host=host):
                self.assertIn("including progress updates between tool calls, in the response language", context)
                self.assertLess(len(context.encode("utf-8")), 9000)
        self.assertIn("The response language is the `language` setting", contexts["claude"])
        self.assertNotIn("The response language is the `language` setting", contexts["codex"])


if __name__ == "__main__":
    unittest.main()
