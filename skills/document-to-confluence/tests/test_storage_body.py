import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "storage_body.py"
SPEC = importlib.util.spec_from_file_location("storage_body", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

MACRO_ID = "11111111-2222-3333-4444-555555555555"
NAMESPACES = 'xmlns:ac="urn:ac" xmlns:ri="urn:ri"'


def toc_placeholder(macro_id=MACRO_ID):
    parameters = {
        "macroParams": {"maxLevel": {"value": "3"}, "minLevel": {"value": "2"}},
        "macroMetadata": {"macroId": {"value": macro_id}},
    }
    attribute = json.dumps(parameters, separators=(",", ":")).replace('"', "&quot;")
    return (
        '<div data-type="extension" data-extension-key="toc" '
        'data-extension-type="com.atlassian.confluence.macro.core" data-layout="default" '
        f'data-parameters="{attribute}"></div>'
    )


def parse(storage):
    return ET.fromstring(f"<root {NAMESPACES}>{storage}</root>")


class TableOfContentsTest(unittest.TestCase):
    def test_목차_자리표시자는_같은_macroId와_매개변수를_가진_저장_매크로가_된다(self):
        # Given
        body = toc_placeholder() + "<h2>개요</h2>"

        # When
        storage = MODULE.convert(body)

        # Then
        macro = parse(storage)[0]
        self.assertEqual("{urn:ac}structured-macro", macro.tag)
        self.assertEqual("toc", macro.get("{urn:ac}name"))
        self.assertEqual(MACRO_ID, macro.get("{urn:ac}macro-id"))
        parameters = {p.get("{urn:ac}name"): p.text for p in macro}
        self.assertEqual({"maxLevel": "3", "minLevel": "2"}, parameters)

    def test_macroId가_없으면_속성을_만들지_않는다(self):
        # Given
        body = (
            '<div data-type="extension" data-extension-key="toc" '
            'data-extension-type="com.atlassian.confluence.macro.core" data-layout="default" '
            'data-parameters="{&quot;macroParams&quot;:{&quot;style&quot;:{&quot;value&quot;:&quot;none&quot;}}}"></div>'
        )

        # When
        storage = MODULE.convert(body)

        # Then
        macro = parse(storage)[0]
        self.assertIsNone(macro.get("{urn:ac}macro-id"))
        self.assertEqual("none", macro[0].text)

    def test_매핑되지_않은_매크로_div는_변환에_실패하고_구성요소를_이름으로_알린다(self):
        # Given
        body = '<div data-type="extension" data-extension-key="jira" data-layout="default"></div>'

        # When
        with self.assertRaises(MODULE.ConversionError) as raised:
            MODULE.convert(body)

        # Then
        self.assertIn("jira", str(raised.exception))
        self.assertIn("div", str(raised.exception))

    def test_data_type_없는_일반_div도_실패한다(self):
        # Given
        body = "<div><p>본문</p></div>"

        # When
        with self.assertRaises(MODULE.ConversionError) as raised:
            MODULE.convert(body)

        # Then
        self.assertIn("div", str(raised.exception))


class ImageTest(unittest.TestCase):
    def test_첨부_이미지는_크기를_가진_ac_image가_된다(self):
        # Given
        body = '<p><img src="/wiki/download/attachments/12345/my%20diagram.png" alt="구조" width="900" height="225"></p>'

        # When
        storage = MODULE.convert(body)

        # Then
        image = parse(storage)[0][0]
        self.assertEqual("{urn:ac}image", image.tag)
        self.assertEqual("900", image.get("{urn:ac}width"))
        self.assertEqual("225", image.get("{urn:ac}height"))
        self.assertEqual("구조", image.get("{urn:ac}alt"))
        self.assertEqual("my diagram.png", image[0].get("{urn:ac}filename".replace("ac", "ri")))

    def test_표_셀_안의_이미지도_변환된다(self):
        # Given
        body = (
            '<table><tbody><tr><td><p><img src="/wiki/download/attachments/1/a.jpg" '
            'alt="a" width="200" height="139"></p></td></tr></tbody></table>'
        )

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertIn('<ac:image ac:alt="a" ac:width="200" ac:height="139">', storage)
        self.assertNotIn("<img", storage)

    def test_첨부가_아닌_이미지_주소는_외부_url_이미지가_된다(self):
        # Given
        body = '<p><img src="https://example.com/a.png" alt="a" width="10" height="10"></p>'

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertIn('<ri:url ri:value="https://example.com/a.png" />', storage)


class CaptionedImageTest(unittest.TestCase):
    FIGURE = (
        '<figure data-type="media-single" data-layout="center">'
        '<img src="/wiki/download/attachments/12345/a%20b.png" alt="구조" width="320" height="160">'
        "<figcaption>그림 <strong>1</strong> 구조 <code>a&lt;b</code></figcaption></figure>"
    )

    def test_캡션이_있는_그림은_캡션을_이미지_안에_둔_ac_image가_된다(self):
        # Given
        body = self.FIGURE

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertEqual(
            '<ac:image ac:align="center" ac:layout="center" ac:alt="구조" ac:width="320" ac:height="160">'
            '<ri:attachment ri:filename="a b.png" />'
            "<ac:caption><p>그림 <strong>1</strong> 구조 <code>a&lt;b</code></p></ac:caption></ac:image>",
            storage,
        )
        self.assertEqual(1, storage.count("<ac:image"))
        self.assertNotIn("figure", storage)

    def test_캡션이_없는_그림은_ac_caption을_만들지_않는다(self):
        # Given
        body = (
            '<figure data-type="media-single"><img src="https://example.com/a.png" alt="a" width="10" height="5"></figure>'
        )

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertEqual(
            '<ac:image ac:alt="a" ac:width="10" ac:height="5"><ri:url ri:value="https://example.com/a.png" /></ac:image>',
            storage,
        )

    def test_배치가_가운데가_아니면_align_없이_layout만_쓴다(self):
        # Given
        body = '<figure data-type="media-single" data-layout="wide"><img src="https://example.com/a.png"></figure>'

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertTrue(storage.startswith('<ac:image ac:layout="wide">'))
        self.assertNotIn("ac:align", storage)

    def assert_fails_naming(self, body, *needles):
        with self.assertRaises(MODULE.ConversionError) as raised:
            MODULE.convert(body)
        for needle in needles:
            self.assertIn(needle, str(raised.exception))

    def test_매핑되지_않은_그림_속성은_이름과_함께_실패한다(self):
        # Given
        body = '<figure data-type="media-single" data-width="50"><img src="https://example.com/a.png"></figure>'

        # When / Then
        self.assert_fails_naming(body, "data-width", "figure")

    def test_이미지가_둘이거나_data_type이_없는_그림은_실패한다(self):
        # Given
        two = '<figure data-type="media-single"><img src="https://example.com/a.png"><img src="https://example.com/b.png"></figure>'
        untyped = '<figure><img src="https://example.com/a.png"></figure>'

        # When / Then
        self.assert_fails_naming(two, "figure", "image")
        self.assert_fails_naming(untyped, "figure", "data-type")

    def test_캡션_안의_인라인이_아닌_자식과_그림_안의_다른_자식은_실패한다(self):
        # Given
        block_caption = '<figure data-type="media-single"><img src="https://example.com/a.png"><figcaption><p>글</p></figcaption></figure>'
        other_child = '<figure data-type="media-single"><img src="https://example.com/a.png"><p>글</p></figure>'

        # When / Then
        self.assert_fails_naming(block_caption, "figcaption", "<p>")
        self.assert_fails_naming(other_child, "figure", "<p>")


class TableTest(unittest.TestCase):
    BODY = (
        '<table data-layout="full-width"><thead><tr>'
        '<th data-colwidth="220"><p>코드</p></th><th data-colwidth="1580"><p>결정</p></th>'
        '</tr></thead><tbody><tr>'
        '<td data-colwidth="220"><p>ABCDE</p></td><td data-colwidth="1580"><p>내용</p></td>'
        "</tr></tbody></table>"
    )

    def test_열_너비는_colgroup으로_남고_레이아웃_속성은_유지된다(self):
        # Given
        body = self.BODY

        # When
        storage = MODULE.convert(body)

        # Then
        table = parse(storage)[0]
        self.assertEqual("full-width", table.get("data-layout"))
        widths = [col.get("style") for col in table.find("colgroup")]
        self.assertEqual(["width: 220px;", "width: 1580px;"], widths)
        self.assertEqual(["코드", "결정", "ABCDE", "내용"], [p.text for p in table.iter("p")])

    def test_열_너비가_없는_표는_colgroup을_만들지_않는다(self):
        # Given
        body = "<table><tbody><tr><td><p>a</p></td></tr></tbody></table>"

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertNotIn("colgroup", storage)

    def test_일부_열에만_너비가_있으면_표를_변환하지_않는다(self):
        # Given
        body = (
            '<table><tbody><tr><td data-colwidth="100"><p>a</p></td><td><p>b</p></td></tr></tbody></table>'
        )

        # When
        with self.assertRaises(MODULE.ConversionError) as raised:
            MODULE.convert(body)

        # Then
        self.assertIn("data-colwidth", str(raised.exception))

    def test_병합_셀의_쉼표_너비는_열마다_나뉜다(self):
        # Given
        body = (
            '<table><tbody><tr><td colspan="2" data-colwidth="100,200"><p>a</p></td></tr></tbody></table>'
        )

        # When
        storage = MODULE.convert(body)

        # Then
        table = parse(storage)[0]
        self.assertEqual(["width: 100px;", "width: 200px;"], [c.get("style") for c in table.find("colgroup")])
        self.assertEqual("2", table.find(".//td").get("colspan"))


class InlineStructureTest(unittest.TestCase):
    def test_빈_문단은_두_형태_모두_유지된다(self):
        # Given
        body = "<p></p><p><br></p><p>본문</p>"

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertEqual("<p /><p><br /></p><p>본문</p>", storage)

    def test_문단_안의_br은_정확히_하나의_줄바꿈이_된다(self):
        # Given
        body = "<p>첫 값<br>둘째 값<br/>셋째 값</p>"

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertEqual("<p>첫 값<br />둘째 값<br />셋째 값</p>", storage)

    def test_수평선은_hr로_유지된다(self):
        # Given
        body = "<p>앞</p><hr><p>뒤</p>"

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertEqual("<p>앞</p><hr /><p>뒤</p>", storage)

    def test_문서_안_링크는_서식을_가진_일반_href가_되고_앵커는_anchor_매크로가_된다(self):
        # Given
        body = '<p><a href="#1.1-구조"><strong>구조</strong> 절</a></p><h2><a id="setup"></a>설정</h2>'

        # When
        storage = MODULE.convert(body)

        # Then
        root = parse(storage)
        self.assertEqual('<p><a href="#1.1-구조"><strong>구조</strong> 절</a></p>', storage[: storage.index("<h2>")])
        self.assertIsNone(root.find("p/{urn:ac}link"))
        macro = root.find("h2/{urn:ac}structured-macro")
        self.assertEqual("anchor", macro.get("{urn:ac}name"))
        self.assertEqual("setup", macro[0].text)

    def test_외부_링크와_서식은_그대로_유지된다(self):
        # Given
        body = '<p><a href="https://example.com/a?x=1&amp;y=2">링크</a> <strong>굵게</strong> <code>a&lt;b</code></p>'

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertEqual(
            '<p><a href="https://example.com/a?x=1&amp;y=2">링크</a> <strong>굵게</strong> <code>a&lt;b</code></p>',
            storage,
        )

    def test_펜스_코드_블록은_code_매크로가_된다(self):
        # Given
        body = '<pre><code class="language-python">if a < b:\n    print("]]>")</code></pre>'

        # When
        storage = MODULE.convert(body)

        # Then
        self.assertIn('ac:name="code"', storage)
        self.assertIn('<ac:parameter ac:name="language">python</ac:parameter>', storage)
        self.assertIn('<ac:plain-text-body><![CDATA[if a < b:\n    print("]]]]><![CDATA[>")]]>', storage)
        self.assertEqual(1, storage.count("<ac:plain-text-body>"))

    def test_접이식_블록은_expand_매크로가_된다(self):
        # Given
        body = "<details><summary>세부</summary><p>내용</p></details>"

        # When
        storage = MODULE.convert(body)

        # Then
        macro = parse(storage)[0]
        self.assertEqual("expand", macro.get("{urn:ac}name"))
        self.assertEqual("세부", macro[0].text)
        self.assertEqual("내용", macro.find("{urn:ac}rich-text-body/p").text)


class UnmappedConstructTest(unittest.TestCase):
    def assert_fails_naming(self, body, *needles):
        with self.assertRaises(MODULE.ConversionError) as raised:
            MODULE.convert(body)
        for needle in needles:
            self.assertIn(needle, str(raised.exception))

    def test_알_수_없는_요소는_이름과_함께_실패한다(self):
        # Given
        body = "<p>앞</p><marquee>흐르는 글</marquee>"

        # When / Then
        self.assert_fails_naming(body, "marquee")

    def test_알_수_없는_속성은_요소와_속성_이름과_함께_실패한다(self):
        # Given
        body = '<p style="color:red">본문</p>'

        # When / Then
        self.assert_fails_naming(body, "style", "p")

    def test_닫는_태그가_맞지_않으면_위치와_함께_실패한다(self):
        # Given
        body = "<p>본문</div>"

        # When / Then
        self.assert_fails_naming(body, "line 1")

    def test_닫히지_않은_요소는_실패한다(self):
        # Given
        body = "<p>본문"

        # When / Then
        self.assert_fails_naming(body, "p")

    def test_html_주석은_조용히_버려지지_않고_실패한다(self):
        # Given
        body = "<p>본문</p><!-- 메모 -->"

        # When / Then
        self.assert_fails_naming(body, "comment")

    def test_본문_안의_댓글_표시는_복원기_몫이므로_실패한다(self):
        # Given
        body = '<p><ac:inline-comment-marker ac:ref="demo-a">FK 제약</ac:inline-comment-marker></p>'

        # When / Then
        self.assert_fails_naming(body, "ac:inline-comment-marker")


class CommandLineTest(unittest.TestCase):
    def run_script(self, body, *extra):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "body.html"
            path.write_text(body, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(path), *extra],
                capture_output=True,
                text=True,
            )

    def test_성공하면_저장_형식을_표준출력에_쓰고_0으로_끝난다(self):
        # Given
        body = "<p>본문</p>"

        # When
        result = self.run_script(body)

        # Then
        self.assertEqual(0, result.returncode)
        self.assertEqual("<p>본문</p>", result.stdout)

    def test_실패하면_표준출력은_비고_표준오류에_이유를_쓰고_1로_끝난다(self):
        # Given
        body = '<div data-type="extension" data-extension-key="jira"></div>'

        # When
        result = self.run_script(body)

        # Then
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("jira", result.stderr)

    def test_없는_파일은_2로_끝난다(self):
        # Given
        command = [sys.executable, str(SCRIPT_PATH), "/tmp/work/does-not-exist.html"]

        # When
        result = subprocess.run(command, capture_output=True, text=True)

        # Then
        self.assertEqual(2, result.returncode)


if __name__ == "__main__":
    unittest.main()
