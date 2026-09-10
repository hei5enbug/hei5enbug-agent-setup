from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import struct
import tempfile
import unittest


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
