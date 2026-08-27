#!/usr/bin/env python3
"""Read image pixel dimensions and compute display height for a target width.

Supported formats: PNG, JPEG, GIF. Standard library only.

Unsupported or unreadable input is reported as a failure, never skipped.

Usage:
    image_size.py IMAGE [IMAGE ...] [--display-width N]

Output: JSON on stdout.
Exit codes: 0 every file read, 1 at least one failure, 2 usage error.
"""

import argparse
import json
import struct
import sys


class UnsupportedImage(Exception):
    pass


def _png_size(data):
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise UnsupportedImage("PNG header is truncated or malformed")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _gif_size(data):
    if len(data) < 10:
        raise UnsupportedImage("GIF header is truncated")
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def _jpeg_size(data):
    size = len(data)
    offset = 2
    standalone = {0x01} | set(range(0xD0, 0xD8))
    sof = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
    while offset < size:
        if data[offset] != 0xFF:
            raise UnsupportedImage("JPEG marker structure is malformed")
        while offset < size and data[offset] == 0xFF:
            offset += 1
        if offset >= size:
            break
        marker = data[offset]
        offset += 1
        if marker in standalone:
            continue
        if offset + 2 > size:
            raise UnsupportedImage("JPEG segment length is truncated")
        (length,) = struct.unpack(">H", data[offset:offset + 2])
        if length < 2:
            raise UnsupportedImage("JPEG segment length is invalid")
        if marker in sof:
            if offset + 7 > size:
                raise UnsupportedImage("JPEG frame header is truncated")
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return width, height
        offset += length
    raise UnsupportedImage("JPEG contains no frame header")


def read_size(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", _png_size(data)
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif", _gif_size(data)
    if data.startswith(b"\xff\xd8"):
        return "jpeg", _jpeg_size(data)
    raise UnsupportedImage("format is not PNG, JPEG, or GIF")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", nargs="+")
    parser.add_argument(
        "--display-width",
        type=int,
        help="target width in pixels; the matching height is computed from the real ratio",
    )
    args = parser.parse_args(argv)

    if args.display_width is not None and args.display_width <= 0:
        parser.error("--display-width must be positive")

    results = []
    failed = False
    for path in args.images:
        entry = {"path": path}
        try:
            image_format, (width, height) = read_size(path)
        except (OSError, UnsupportedImage) as error:
            entry.update(status="failed", error=str(error))
            failed = True
        else:
            entry.update(status="ok", format=image_format, width=width, height=height)
            if args.display_width and width > 0:
                entry["display_width"] = args.display_width
                entry["display_height"] = round(args.display_width * height / width)
        results.append(entry)

    json.dump({"ok": not failed, "results": results}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
