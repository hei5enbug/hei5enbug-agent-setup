from contextlib import redirect_stdout
import importlib.util
from io import BytesIO, StringIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "image_size.py"
SPEC = importlib.util.spec_from_file_location("image_size", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def png_bytes(width, height):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)


def gif_bytes(width, height):
    return b"GIF89a" + struct.pack("<HH", width, height)


def jpeg_bytes(width, height):
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width) + b"\x03"
    return b"\xff\xd8" + sof0 + b"\x00" * 9


class ImageSizeTest(unittest.TestCase):
    def test_dimensions_do_not_read_image_payload(self):
        """이미지 크기는 이미지 본문 전체를 읽지 않고 구한다."""
        for header in (png_bytes(640, 480), gif_bytes(640, 480), jpeg_bytes(640, 480)):
            with self.subTest(header=header[:6]):
                # Given
                reads = []

                class MeasuredFile(BytesIO):
                    def read(self, size=-1):
                        data = super().read(size)
                        reads.append(len(data))
                        return data

                source = MeasuredFile(header + b"x" * 1_000_000)
                # When
                with patch("builtins.open", return_value=source):
                    _, dimensions = MODULE.read_size("sample")
                # Then
                self.assertEqual(dimensions, (640, 480))
                self.assertLess(sum(reads), 64)

    def test_jpeg_skips_metadata_segments(self):
        """JPEG 부가정보 뒤의 프레임에서도 정확한 크기를 읽는다."""
        # Given
        metadata = b"\xff\xe1" + struct.pack(">H", 60002) + b"x" * 60000
        path = self.write("metadata.jpg", b"\xff\xd8" + metadata + jpeg_bytes(640, 480)[2:])
        # When
        result = MODULE.read_size(path)
        # Then
        self.assertEqual(result, ("jpeg", (640, 480)))

    def test_invalid_jpeg_frame_length_is_rejected(self):
        """길이가 잘못된 JPEG 프레임을 정상 이미지로 받아들이지 않는다."""
        # Given
        path = self.write("invalid.jpg", b"\xff\xd8\xff\xc0\x00\x02\x08\x00\x10\x00\x10")
        # When
        with self.assertRaises(MODULE.UnsupportedImage) as caught:
            MODULE.read_size(path)
        # Then
        self.assertIn("length", str(caught.exception))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def run_main(self, *args):
        output = StringIO()
        with redirect_stdout(output):
            status = MODULE.main([str(a) for a in args])
        return status, json.loads(output.getvalue())

    def test_zero_dimension_png_is_a_failure(self):
        path = self.write("zero.png", png_bytes(0, 0))
        status, report = self.run_main(path)
        self.assertEqual(1, status)
        self.assertFalse(report["ok"])
        self.assertEqual("failed", report["results"][0]["status"])
        self.assertIn("positive", report["results"][0]["error"])

    def test_zero_dimension_gif_and_jpeg_fail(self):
        for name, data in (("z.gif", gif_bytes(10, 0)), ("z.jpg", jpeg_bytes(0, 10))):
            with self.subTest(name=name):
                status, report = self.run_main(self.write(name, data))
                self.assertEqual(1, status)
                self.assertEqual("failed", report["results"][0]["status"])

    def test_truncated_png_header_is_a_failure(self):
        path = self.write("short.png", png_bytes(10, 10)[:20])
        status, report = self.run_main(path)
        self.assertEqual(1, status)
        self.assertIn("truncated", report["results"][0]["error"])

    def test_valid_sizes_are_read(self):
        png = self.write("ok.png", png_bytes(800, 400))
        gif = self.write("ok.gif", gif_bytes(30, 20))
        jpeg = self.write("ok.jpg", jpeg_bytes(640, 480))
        status, report = self.run_main(png, gif, jpeg)
        self.assertEqual(0, status)
        sizes = [(r["width"], r["height"]) for r in report["results"]]
        self.assertEqual([(800, 400), (30, 20), (640, 480)], sizes)

    def test_batch_keeps_each_result_when_one_file_fails(self):
        """일괄 측정은 일부 파일이 실패해도 파일별 결과를 보존한다."""
        # given
        first = self.write("first.png", png_bytes(320, 160))
        failed = self.write("failed.svg", b"<svg></svg>")
        last = self.write("last.png", png_bytes(420, 210))

        # when
        status, report = self.run_main(first, failed, last, "--display-width", "240")

        # then
        self.assertEqual(1, status)
        self.assertFalse(report["ok"])
        self.assertEqual(
            [
                {"path": str(first), "status": "ok", "format": "png", "width": 320,
                 "height": 160, "display_width": 240, "display_height": 120, "clamped": False},
                {"path": str(failed), "status": "failed", "error": "format is not PNG, JPEG, or GIF"},
                {"path": str(last), "status": "ok", "format": "png", "width": 420,
                 "height": 210, "display_width": 240, "display_height": 120, "clamped": False},
            ],
            report["results"],
        )

    def test_display_width_is_clamped_to_source_width(self):
        path = self.write("small.png", png_bytes(200, 100))
        status, report = self.run_main(path, "--display-width", "800")
        self.assertEqual(0, status)
        entry = report["results"][0]
        self.assertEqual(200, entry["display_width"])
        self.assertEqual(100, entry["display_height"])
        self.assertTrue(entry["clamped"])

    def test_display_width_below_source_keeps_ratio(self):
        path = self.write("big.png", png_bytes(1600, 900))
        status, report = self.run_main(path, "--display-width", "800")
        self.assertEqual(0, status)
        entry = report["results"][0]
        self.assertEqual(800, entry["display_width"])
        self.assertEqual(450, entry["display_height"])
        self.assertFalse(entry["clamped"])

    def test_display_height_is_at_least_one(self):
        path = self.write("wide.png", png_bytes(4000, 1))
        status, report = self.run_main(path, "--display-width", "10")
        self.assertEqual(0, status)
        self.assertEqual(1, report["results"][0]["display_height"])


if __name__ == "__main__":
    unittest.main()
