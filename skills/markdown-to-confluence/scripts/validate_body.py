#!/usr/bin/env python3
"""Validate a Confluence HTML body against mechanical rules.

Declared scope. Every check below is exact: a finding is always a real violation, and every
violation inside the scope is reported.

    banned-media-container   a div carrying data-type media-single or media-group
    img-missing-dimension    an img element without width or without height
    bare-table-cell          text directly inside td or th, not wrapped in a child element
    local-path               an absolute filesystem path, or a link to a Markdown file
    missing-attachment       an attachment download reference absent from --attachments

Outside the scope. This script does not judge wording, structure, ordering, diagram quality, or
whether the markup expresses what the author meant. It does not verify that the document is
well-formed HTML. Read the body yourself for those.

Usage:
    validate_body.py BODY_FILE [--attachments NAME [NAME ...]]
    cat body.html | validate_body.py - [--attachments NAME [NAME ...]]

Output: JSON on stdout.
Exit codes: 0 no findings, 1 findings present, 2 usage or read error.
"""

import argparse
import json
import posixpath
import re
import sys
from html.parser import HTMLParser

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

BANNED_MEDIA_TYPES = {"media-single", "media-group"}

LOCAL_PATH_PATTERNS = [
    re.compile(r"(?:/Users/|/home/)[A-Za-z0-9._-]+/"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\\\?[A-Za-z0-9._-]"),
    re.compile(r"(?:^|[\s\"'(>])~/[A-Za-z0-9._-]"),
]

MARKDOWN_LINK_PATTERN = re.compile(r"\.md(?:#[^\"'\s]*)?$")

LINK_ATTRIBUTES = {"href", "src"}

ATTACHMENT_PATTERN = re.compile(r"/download/attachments/[^/]+/([^\"'?\s]+)")


class BodyChecker(HTMLParser):
    def __init__(self, known_attachments):
        super().__init__(convert_charrefs=True)
        self.known_attachments = known_attachments
        self.findings = []
        self.stack = []

    def _add(self, rule, message):
        line, column = self.getpos()
        self.findings.append(
            {"rule": rule, "line": line, "column": column, "message": message}
        )

    def _check_text_for_paths(self, text, where):
        for pattern in LOCAL_PATH_PATTERNS:
            match = pattern.search(text)
            if match:
                self._add(
                    "local-path",
                    "absolute filesystem path in {}: {}".format(where, match.group(0).strip()),
                )
                return

    def _check_attributes(self, tag, attrs):
        values = dict(attrs)

        if tag == "div":
            data_type = values.get("data-type")
            if data_type in BANNED_MEDIA_TYPES:
                self._add(
                    "banned-media-container",
                    "div carries data-type {}; write a plain img element instead".format(data_type),
                )

        if tag == "img":
            for dimension in ("width", "height"):
                if not values.get(dimension):
                    self._add(
                        "img-missing-dimension",
                        "img has no {}; measure the file and set both dimensions".format(dimension),
                    )

        for name, value in values.items():
            if value is None:
                continue
            if name in LINK_ATTRIBUTES:
                if MARKDOWN_LINK_PATTERN.search(value.strip()):
                    self._add(
                        "local-path",
                        "{} points at a Markdown file: {}".format(name, value.strip()),
                    )
                match = ATTACHMENT_PATTERN.search(value)
                if match and self.known_attachments is not None:
                    name_only = posixpath.basename(match.group(1))
                    if name_only not in self.known_attachments:
                        self._add(
                            "missing-attachment",
                            "body references {} which is not in the uploaded set".format(name_only),
                        )
            self._check_text_for_paths(value, "attribute {}".format(name))

    def handle_starttag(self, tag, attrs):
        self._check_attributes(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self._check_attributes(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        if not data.strip():
            return
        if self.stack and self.stack[-1] in ("td", "th"):
            self._add(
                "bare-table-cell",
                "text sits directly in {}; wrap cell content in a block element".format(
                    self.stack[-1]
                ),
            )
        self._check_text_for_paths(data, "text")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("body", help="path to the HTML body file, or - for standard input")
    parser.add_argument(
        "--attachments",
        nargs="*",
        default=None,
        help="file names already uploaded to the page; omit to skip the attachment check",
    )
    args = parser.parse_args(argv)

    try:
        if args.body == "-":
            markup = sys.stdin.read()
        else:
            with open(args.body, encoding="utf-8") as handle:
                markup = handle.read()
    except OSError as error:
        sys.stderr.write("cannot read body: {}\n".format(error))
        return 2

    known = None
    if args.attachments is not None:
        known = {posixpath.basename(name) for name in args.attachments}

    checker = BodyChecker(known)
    try:
        checker.feed(markup)
        checker.close()
    except Exception as error:  # noqa: BLE001 - unparseable input must not read as success
        sys.stderr.write("cannot parse body: {}\n".format(error))
        return 2

    findings = checker.findings
    report = {
        "ok": not findings,
        "checked": [
            "banned-media-container",
            "img-missing-dimension",
            "bare-table-cell",
            "local-path",
        ]
        + (["missing-attachment"] if known is not None else []),
        "finding_count": len(findings),
        "findings": findings,
    }
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
