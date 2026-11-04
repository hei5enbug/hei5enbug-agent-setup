import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "comment_markers.py"
SPEC = importlib.util.spec_from_file_location("comment_markers", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CLOSE = "</ac:inline-comment-marker>"


def marker(ref, text):
    return f'<ac:inline-comment-marker ac:ref="{ref}">{text}{CLOSE}'


def references(body):
    return re.findall(r'<ac:inline-comment-marker ac:ref="([^"]+)">', body)


def restore(previous, new, anchors=()):
    return MODULE.restore_markers(previous, new, list(anchors))


class UniqueSelectionTest(unittest.TestCase):
    def test_선택_영역이_한_번만_나오면_같은_자리에_다시_감싼다(self):
        # Given
        previous = f"<p>앞 문장. {marker('demo-a', 'FK 제약')}은 필수다.</p>"
        new = "<p>바뀐 문장. FK 제약은 필수다.</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual([], result.unresolved)
        self.assertEqual(f"<p>바뀐 문장. {marker('demo-a', 'FK 제약')}은 필수다.</p>", result.body)

    def test_이미_표시가_있는_참조는_다시_감싸지_않는다(self):
        # Given
        previous = f"<p>{marker('demo-a', 'FK 제약')}</p>"
        new = f"<p>{marker('demo-a', 'FK 제약')}</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual(new, result.body)
        self.assertEqual(["demo-a"], result.kept)

    def test_표시가_없는_이전_본문은_새_본문을_그대로_돌려준다(self):
        # Given
        previous = "<p>표시 없음</p>"
        new = "<p>새 본문</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual(new, result.body)
        self.assertEqual([], result.restored)


class RepeatedSelectionTest(unittest.TestCase):
    NEW = (
        "<p>그룹 목록을 본다.</p>"
        "<p>그룹 삭제는 관리자만 한다.</p>"
        "<p>그룹은 사용자를 묶어 권한을 한 번에 주는 데이터다.</p>"
        "<p>다른 그룹 이름은 바꿀 수 있다.</p>"
        "<p>마지막 그룹</p>"
    )

    def test_이전_문맥으로_같은_문장의_출현만_고른다(self):
        # Given
        previous = f"<p>{marker('demo-g', '그룹')}은 사용자를 묶어 권한을 한 번에 주는 데이터다.</p>"

        # When
        result = restore(previous, self.NEW)

        # Then
        self.assertEqual([], result.unresolved)
        self.assertEqual(["demo-g"], references(result.body))
        self.assertIn(f"<p>{marker('demo-g', '그룹')}은 사용자를 묶어", result.body)
        self.assertEqual(self.NEW, result.body.replace(f'<ac:inline-comment-marker ac:ref="demo-g">', "").replace(CLOSE, ""))

    def test_문맥으로도_하나로_좁혀지지_않으면_자리를_추측하지_않는다(self):
        # Given
        previous = f"<p>{marker('demo-g', '그룹')}</p>"
        new = "<p>그룹</p><p>그룹</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual("<p>그룹</p><p>그룹</p>", result.body)
        self.assertEqual(["demo-g"], [item["ref"] for item in result.unresolved])
        self.assertEqual("ambiguous", result.unresolved[0]["reason"])
        self.assertEqual(2, result.unresolved[0]["candidates"])


class MissingSelectionTest(unittest.TestCase):
    PREVIOUS = f"<p>앞에 있던 {marker('demo-b', '기록을 남기는 방식')}에 대한 설명이다.</p>"
    NEW = "<h2>기록 테이블</h2><p>전혀 다른 문장이다.</p>"

    def test_사라진_선택_영역은_참조와_이전_문맥을_보고한다(self):
        # Given
        previous, new = self.PREVIOUS, self.NEW

        # When
        result = restore(previous, new)

        # Then
        item = result.unresolved[0]
        self.assertEqual("demo-b", item["ref"])
        self.assertEqual("missing", item["reason"])
        self.assertEqual("기록을 남기는 방식", item["selection"])
        self.assertIn("앞에 있던", item["before"])
        self.assertIn("에 대한 설명이다.", item["after"])

    def test_명시한_앵커가_있으면_그_자리에_감싼다(self):
        # Given
        anchor = {"ref": "demo-b", "before": "", "selection": "기록 테이블", "after": ""}

        # When
        result = restore(self.PREVIOUS, self.NEW, [anchor])

        # Then
        self.assertEqual([], result.unresolved)
        self.assertEqual(f"<h2>{marker('demo-b', '기록 테이블')}</h2><p>전혀 다른 문장이다.</p>", result.body)

    def test_앵커도_여러_곳과_맞으면_실패한다(self):
        # Given
        anchor = {"ref": "demo-b", "before": "", "selection": "문장", "after": ""}
        new = "<p>문장 하나</p><p>문장 둘</p>"

        # When
        result = restore(self.PREVIOUS, new, [anchor])

        # Then
        self.assertEqual("ambiguous", result.unresolved[0]["reason"])
        self.assertEqual(new, result.body)

    def test_선택할_글자가_없는_앵커는_복원으로_세지_않고_보고한다(self):
        # Given
        previous = f"<p>{marker('demo-a', 'old')}</p>"
        new = "<p>new</p>"
        anchor = {"ref": "demo-a", "before": "new", "selection": "\x00", "after": ""}

        # When
        result = restore(previous, new, [anchor])

        # Then
        self.assertEqual([], result.restored)
        self.assertEqual(["demo-a"], [item["ref"] for item in result.unresolved])
        self.assertEqual(new, result.body)

    def test_앵커의_앞뒤_문맥이_자리를_하나로_좁힌다(self):
        # Given
        anchor = {"ref": "demo-b", "before": "둘째 ", "selection": "문장", "after": " 끝"}
        new = "<p>첫째 문장 시작</p><p>둘째 문장 끝</p>"

        # When
        result = restore(self.PREVIOUS, new, [anchor])

        # Then
        self.assertEqual(f"<p>첫째 문장 시작</p><p>둘째 {marker('demo-b', '문장')} 끝</p>", result.body)

    def test_이전_본문에_없는_참조의_앵커는_오류다(self):
        # Given
        anchor = {"ref": "demo-z", "before": "", "selection": "기록 테이블", "after": ""}

        # When / Then
        with self.assertRaises(MODULE.MarkerError) as raised:
            restore(self.PREVIOUS, self.NEW, [anchor])
        self.assertIn("demo-z", str(raised.exception))


class NestingAndSplitTest(unittest.TestCase):
    def test_다른_표시_안에_중첩된_표시는_같은_순서로_복원된다(self):
        # Given
        previous = (
            f'<h2><ac:inline-comment-marker ac:ref="demo-d">기록 '
            f'{marker("demo-c", "테이블")}{CLOSE}</h2>'
        )
        new = "<h2>기록 테이블</h2>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual([], result.unresolved)
        self.assertEqual(previous, result.body)

    def test_자식_표시는_복원된_부모_표시_안에서만_자리를_찾는다(self):
        # Given
        previous = (
            f'<h2><ac:inline-comment-marker ac:ref="demo-d">A {marker("demo-c", "key")} Z{CLOSE}</h2>'
            "<p>old tail</p>"
        )
        new = "<h2>A key Z</h2><p>new tail</p><h2>B key Z</h2><p>old tail</p>"

        # When
        result = restore(previous, new)

        # Then
        expected = (
            f'<h2><ac:inline-comment-marker ac:ref="demo-d">A {marker("demo-c", "key")} Z{CLOSE}</h2>'
            "<p>new tail</p><h2>B key Z</h2><p>old tail</p>"
        )
        self.assertEqual([], result.unresolved)
        self.assertEqual(expected, result.body)

    def test_부모_표시_안에서_자식의_자리를_찾지_못하면_밖에_감싸지_않고_보고한다(self):
        # Given
        previous = (
            f'<h2><ac:inline-comment-marker ac:ref="demo-d">A {marker("demo-c", "key")} Z{CLOSE}</h2>'
        )
        new = "<h2>A new Z</h2><h2>B key Z</h2>"
        anchor = {"ref": "demo-d", "before": "", "selection": "A new Z", "after": ""}

        # When
        result = restore(previous, new, [anchor])

        # Then
        self.assertEqual(["demo-c"], [item["ref"] for item in result.unresolved])
        self.assertNotIn("demo-c", references(result.body))

    def test_서식을_가로지르는_선택_영역은_같은_참조의_조각으로_나뉜다(self):
        # Given
        previous = (
            f"<p>다시 보낼 때는 {marker('demo-c', '같은 ')}<code>{marker('demo-c', 'retry_key')}</code>"
            f"{marker('demo-c', '를 쓴다')}.</p>"
        )
        new = "<p>다시 보낼 때는 같은 <code>retry_key</code>를 쓴다.</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual([], result.unresolved)
        self.assertEqual(previous, result.body)
        self.assertEqual(["demo-c"] * 3, references(result.body))

    def test_이전에_여러_조각이던_선택은_새_본문의_단일_텍스트에도_한_번에_감긴다(self):
        # Given
        previous = f"<p>{marker('demo-c', '같은 ')}<code>{marker('demo-c', 'key')}</code></p>"
        new = "<p>같은 key</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual(f"<p>{marker('demo-c', '같은 key')}</p>", result.body)

    def test_블록_경계를_가로지르는_선택은_하나의_문단_안에서만_찾는다(self):
        # Given
        previous = f"<p>{marker('demo-a', '끝말시작')}</p>"
        new = "<p>끝말</p><p>시작</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual("missing", result.unresolved[0]["reason"])

    def test_엔티티를_포함한_선택도_원문_그대로_감싼다(self):
        # Given
        previous = f"<p>{marker('demo-a', 'A &amp; B')}</p>"
        new = "<p>값 A &amp; B 입니다</p>"

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual(f"<p>값 {marker('demo-a', 'A &amp; B')} 입니다</p>", result.body)


class ParameterTextTest(unittest.TestCase):
    EXPAND = '<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">{title}</ac:parameter><ac:rich-text-body>{body}</ac:rich-text-body></ac:structured-macro>'

    def test_매크로_매개변수_안의_같은_글자는_선택을_모호하게_하지_않는다(self):
        # Given
        previous = f"<p>{marker('demo-g', '그룹')}</p>"
        paragraph = "<p>그룹</p>"
        new = self.EXPAND.format(title="그룹 예시", body="<p>내용</p>") + paragraph

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual([], result.unresolved)
        self.assertTrue(result.body.endswith(f"<p>{marker('demo-g', '그룹')}</p>"))
        self.assertIn(">그룹 예시</ac:parameter>", result.body)

    def test_선택이_매개변수_안에만_있으면_누락으로_보고하고_표시를_넣지_않는다(self):
        # Given
        previous = f"<p>{marker('demo-g', '그룹')}</p>"
        new = self.EXPAND.format(title="그룹 예시", body="<p>내용</p>")

        # When
        result = restore(previous, new)

        # Then
        self.assertEqual(new, result.body)
        self.assertEqual("missing", result.unresolved[0]["reason"])


class CheckTest(unittest.TestCase):
    PREVIOUS = f"<p>{marker('demo-a', 'FK 제약')}</p><p>{marker('demo-b', '하나')} {marker('demo-b', '둘')}</p>"

    def test_읽어온_본문에_빠진_참조를_모두_보고한다(self):
        # Given
        readback = f"<p>FK 제약</p><p>{marker('demo-b', '하나')} {marker('demo-b', '둘')}</p>"

        # When
        report = MODULE.check_markers(self.PREVIOUS, readback)

        # Then
        self.assertEqual(["demo-a"], report["missing"])
        self.assertEqual({"references": 2, "pairs": 3}, report["previous"])
        self.assertEqual({"references": 1, "pairs": 2}, report["readback"])

    def test_모두_남아_있으면_빠진_참조가_없다(self):
        # Given
        readback = self.PREVIOUS

        # When
        report = MODULE.check_markers(self.PREVIOUS, readback)

        # Then
        self.assertEqual([], report["missing"])
        self.assertEqual(report["previous"], report["readback"])

    def test_짝이_맞지_않는_표시_태그는_오류다(self):
        # Given
        broken = '<p><ac:inline-comment-marker ac:ref="demo-a">열림만</p>'

        # When / Then
        with self.assertRaises(MODULE.MarkerError):
            MODULE.check_markers(self.PREVIOUS, broken)


class CommandLineTest(unittest.TestCase):
    def run_script(self, *args, files):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, content in files.items():
                path = Path(directory) / (name + (".json" if name == "anchors" else ".html"))
                path.write_text(content, encoding="utf-8")
                paths.append(str(path))
            output = str(Path(directory) / "out.html")
            command = [sys.executable, str(SCRIPT_PATH), *[a.format(out=output, **dict(zip(files, paths))) for a in args]]
            result = subprocess.run(command, capture_output=True, text=True)
            written = Path(output).read_text(encoding="utf-8") if Path(output).exists() else None
            return result, written

    def test_복원에_성공하면_출력_파일을_쓰고_0으로_끝난다(self):
        # Given
        files = {"prev": f"<p>{marker('demo-a', 'FK 제약')}</p>", "new": "<p>FK 제약</p>"}

        # When
        result, written = self.run_script("restore", "{prev}", "{new}", "--output", "{out}", files=files)

        # Then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"<p>{marker('demo-a', 'FK 제약')}</p>", written)
        self.assertEqual(["demo-a"], json.loads(result.stdout)["restored"])

    def test_매개변수에_같은_글자가_있어도_본문_문단을_감싸고_0으로_끝난다(self):
        # Given
        expand = ParameterTextTest.EXPAND.format(title="그룹 예시", body="<p>내용</p>")
        files = {"prev": f"<p>{marker('demo-g', '그룹')}</p>", "new": expand + "<p>그룹</p>"}

        # When
        result, written = self.run_script("restore", "{prev}", "{new}", "--output", "{out}", files=files)

        # Then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(written.endswith(f"<p>{marker('demo-g', '그룹')}</p>"))

    def test_복원하지_못한_참조가_있으면_1로_끝나고_출력_파일을_쓰지_않는다(self):
        # Given
        files = {"prev": f"<p>{marker('demo-b', '사라질 문장')}</p>", "new": "<p>기록 테이블</p>"}

        # When
        result, written = self.run_script("restore", "{prev}", "{new}", "--output", "{out}", files=files)

        # Then
        self.assertEqual(1, result.returncode)
        self.assertIsNone(written)
        report = json.loads(result.stdout)
        self.assertEqual("demo-b", report["unresolved"][0]["ref"])

    def test_블록_경계만_고른_앵커는_출력_파일을_쓰지_않고_0이_아닌_값으로_끝난다(self):
        # Given
        files = {"prev": f"<p>{marker('demo-a', 'old')}</p>", "new": "<p>new</p>"}

        # When
        result, written = self.run_script(
            "restore", "{prev}", "{new}", "--output", "{out}", "--anchor", "demo-a", "new", "¶", "", files=files
        )

        # Then
        self.assertNotEqual(0, result.returncode)
        self.assertIsNone(written)

    def test_anchor_옵션으로_다시_실행하면_성공한다(self):
        # Given
        files = {"prev": f"<p>{marker('demo-b', '사라질 문장')}</p>", "new": "<h2>기록 테이블</h2>"}

        # When
        result, written = self.run_script(
            "restore", "{prev}", "{new}", "--output", "{out}",
            "--anchor", "demo-b", "", "기록 테이블", "", files=files,
        )

        # Then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"<h2>{marker('demo-b', '기록 테이블')}</h2>", written)

    def test_anchors_json_파일로도_앵커를_줄_수_있다(self):
        # Given
        anchors = json.dumps([{"ref": "demo-b", "before": "", "selection": "기록 테이블", "after": ""}])
        files = {
            "prev": f"<p>{marker('demo-b', '사라질 문장')}</p>",
            "new": "<h2>기록 테이블</h2>",
            "anchors": anchors,
        }

        # When
        result, written = self.run_script(
            "restore", "{prev}", "{new}", "--output", "{out}", "--anchors", "{anchors}", files=files,
        )

        # Then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"<h2>{marker('demo-b', '기록 테이블')}</h2>", written)

    def test_check는_빠진_참조가_있으면_1로_끝나고_참조를_출력한다(self):
        # Given
        files = {"prev": f"<p>{marker('demo-a', 'FK 제약')}</p>", "read": "<p>FK 제약</p>"}

        # When
        result, _ = self.run_script("check", "{prev}", "{read}", files=files)

        # Then
        self.assertEqual(1, result.returncode)
        self.assertEqual(["demo-a"], json.loads(result.stdout)["missing"])

    def test_check는_모두_남아_있으면_0으로_끝난다(self):
        # Given
        body = f"<p>{marker('demo-a', 'FK 제약')}</p>"
        files = {"prev": body, "read": body}

        # When
        result, _ = self.run_script("check", "{prev}", "{read}", files=files)

        # Then
        self.assertEqual(0, result.returncode)

    def test_없는_입력_파일은_2로_끝난다(self):
        # Given
        command = [sys.executable, str(SCRIPT_PATH), "check", "/tmp/work/none-a.html", "/tmp/work/none-b.html"]

        # When
        result = subprocess.run(command, capture_output=True, text=True)

        # Then
        self.assertEqual(2, result.returncode)


if __name__ == "__main__":
    unittest.main()
