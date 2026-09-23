from pathlib import Path
import re
import subprocess
import tempfile
import zlib


ROOT = Path(__file__).parent
OUTPUT = ROOT / "scanned-two-column.pdf"
PAGE_COUNT = 18


def add_object(objects, value):
    objects.append(value)
    return len(objects) - 1


def make_pdf(objects):
    result = bytearray(b"%PDF-1.4\n%fixture\n")
    offsets = [0]
    for index, value in enumerate(objects[1:], start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode())
        result.extend(value)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects)}\n".encode())
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(result)


def pdf_string(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text(x, y, size, value, gray=0.12):
    return f"{gray:.2f} g BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm ({pdf_string(value)}) Tj ET\n"


def line(x1, y1, x2, y2, gray=0.2, width=0.6):
    return f"{gray:.2f} G {width} w {x1} {y1} m {x2} {y2} l S\n"


def seed_page(page_number):
    commands = ["1 w\n"]
    if page_number < 4:
        commands.extend(
            [
                text(52, 730, 18, "SERVICE RELIABILITY STUDY"),
                text(52, 698, 11, "Reference pages outside the requested range."),
                text(52, 676, 10, "Requested scanned pages begin at page 4."),
                line(52, 660, 560, 660),
                text(52, 632, 9, f"COVER PAGE {page_number:02d}"),
            ]
        )
        return "".join(commands)

    low_quality = page_number in {11, 16}
    gray = 0.52 if low_quality else 0.12
    commands.extend(
        [
            text(48, 748, 13, "SERVICE RELIABILITY STUDY", gray),
            text(48, 730, 8, f"SCANNED SAMPLE PAGE {page_number:02d}", gray),
            line(48, 718, 564, 718, gray),
            line(306, 54, 306, 710, 0.55, 0.4),
            text(48, 688, 9, "AVAILABILITY BY REGION", gray),
            line(48, 674, 288, 674, gray),
            line(48, 650, 288, 650, gray),
            line(48, 626, 288, 626, gray),
            line(48, 602, 288, 602, gray),
            line(48, 578, 288, 578, gray),
            line(48, 674, 48, 578, gray),
            line(190, 674, 190, 578, gray),
            line(288, 674, 288, 578, gray),
            text(56, 658, 8, "REGION", gray),
            text(198, 658, 8, "AVAILABILITY", gray),
            text(56, 634, 8, "REGION A", gray),
            text(198, 634, 8, "99.97%", gray),
            text(56, 610, 8, "REGION B", gray),
            text(198, 610, 8, "99.94%", gray),
            text(56, 586, 8, "REGION C", gray),
            text(198, 586, 8, "99.9?%" if page_number == 16 else "99.91%", gray),
            text(48, 518, 9, "EQUATION", gray),
            text(48, 500, 8, "P(SUCCESS) = 1 - P(FAILURE)^2", gray),
            text(48, 468, 9, "OBSERVATION", gray),
            text(48, 450, 8, "Both regions met the monthly target.", gray),
            text(48, 434, 8, "Samples exclude scheduled maintenance.", gray),
            text(48, 398, 8, "FOOTNOTE: See notes in the right column.", gray),
            text(326, 688, 9, "RETRY POLICY", gray),
            line(326, 674, 564, 674, gray),
            text(326, 650, 8, "TIMEOUT: 2 SECONDS", gray),
            text(326, 632, 8, "RETRY: ONCE", gray),
            text(326, 614, 8, "STOP: AFTER 2 FAILURES", gray),
            text(326, 572, 9, "LATENCY SUMMARY", gray),
            line(326, 558, 564, 558, gray),
            text(326, 534, 8, "MEDIAN: 120 MS", gray),
            text(326, 516, 8, "P95: 410 MS", gray),
            text(326, 474, 9, "NOTES", gray),
            line(326, 460, 564, 460, gray),
            text(326, 436, 8, "* Rolling 30-day sample.", gray),
            text(326, 418, 8, "** Values are per region.", gray),
            text(48, 72, 7, f"LOW-CONTRAST SCAN: {page_number:02d}" if low_quality else "SCAN COPIED FROM FIELD REPORT", gray),
            line(48, 60, 564, 60, gray, 0.4),
        ]
    )
    return "".join(commands)


def make_text_pdf(path):
    objects = [None, b"<< /Type /Catalog /Pages 2 0 R >>", None]
    font_id = add_object(objects, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    for page_number in range(1, PAGE_COUNT + 1):
        stream = seed_page(page_number).encode("ascii")
        content_id = add_object(
            objects,
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream",
        )
        page_id = add_object(
            objects,
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode(),
        )
        page_ids.append(page_id)
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Count {PAGE_COUNT} /Kids [{kids}] >>".encode()
    path.write_bytes(make_pdf(objects))


def parse_ppm(path):
    data = path.read_bytes()
    offset = 0
    tokens = []
    while len(tokens) < 4:
        while offset < len(data) and data[offset] in b" \t\r\n":
            offset += 1
        if data[offset:offset + 1] == b"#":
            offset = data.index(b"\n", offset) + 1
            continue
        end = offset
        while end < len(data) and data[end] not in b" \t\r\n":
            end += 1
        tokens.append(data[offset:end])
        offset = end
    if tokens[0] != b"P6" or tokens[3] != b"255":
        raise ValueError(f"unsupported PPM format in {path}")
    width, height = int(tokens[1]), int(tokens[2])
    if offset >= len(data) or data[offset] not in b" \t\r\n":
        raise ValueError(f"missing PPM data separator in {path}")
    if data[offset:offset + 2] == b"\r\n":
        offset += 2
    else:
        offset += 1
    pixels = data[offset:]
    if len(pixels) != width * height * 3:
        raise ValueError(f"unexpected PPM data size in {path}")
    return width, height, pixels


def make_scan_pdf(ppm_paths, output_path):
    objects = [None, b"<< /Type /Catalog /Pages 2 0 R >>", None]
    page_ids = []
    for index, ppm_path in enumerate(ppm_paths, start=1):
        width, height, pixels = parse_ppm(ppm_path)
        image_data = zlib.compress(pixels, 9)
        image_id = add_object(
            objects,
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            f"/Length {len(image_data)} >>\nstream\n".encode()
            + image_data
            + b"\nendstream",
        )
        content = f"q\n612 0 0 792 0 0 cm\n/Im{index} Do\nQ\n".encode()
        content_id = add_object(
            objects,
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream",
        )
        page_id = add_object(
            objects,
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /XObject << /Im{index} {image_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode(),
        )
        page_ids.append(page_id)
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode()
    output_path.write_bytes(make_pdf(objects))


def main():
    with tempfile.TemporaryDirectory(prefix="confluence-scan-fixture-") as temporary:
        temporary_path = Path(temporary)
        seed_path = temporary_path / "vector-source.pdf"
        make_text_pdf(seed_path)
        prefix = temporary_path / "scan"
        subprocess.run(
            ["pdftoppm", "-r", "110", str(seed_path), str(prefix)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        ppm_paths = sorted(
            temporary_path.glob("scan-*.ppm"),
            key=lambda path: int(re.search(r"-(\d+)\.ppm$", path.name).group(1)),
        )
        if len(ppm_paths) != PAGE_COUNT:
            raise RuntimeError(f"expected {PAGE_COUNT} rasterized pages, found {len(ppm_paths)}")
        make_scan_pdf(ppm_paths, OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
