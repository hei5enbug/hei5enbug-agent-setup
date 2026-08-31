#!/usr/bin/env python3
"""Compare supported Markdown text with the text extracted from an HTML body.

Supported Markdown includes ATX headings, lists, block quotes, pipe tables, emphasis,
strikethrough, inline code, inline links and images with non-nested destinations, and HTML ``br``
elements. Fenced code, raw HTML, complex links, reference links, footnotes, and task lists are
unsupported unless removed with ``--drop``.

Exit codes: 0 equal, 1 different, 2 invalid or unsupported input.
"""

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser

BREAK_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
TITLE_PATTERN = re.compile(r"^#\s+.*$", re.MULTILINE)
HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
NUMBERED_PATTERN = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
QUOTE_PATTERN = re.compile(r"^\s*>\s?", re.MULTILINE)
TABLE_RULE_PATTERN = re.compile(r"^[\s|:\-]+$", re.MULTILINE)
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^\n)]*\)")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^\n)]*\)")
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
ESCAPE_PATTERN = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
WHITESPACE_PATTERN = re.compile(r"\s+")

UNSUPPORTED_PATTERNS = [
    ("fenced code", re.compile(r"^\s*(```|~~~)", re.MULTILINE)),
    (
        "inline link with nested parentheses",
        re.compile(r"!?\[[^\]]*\]\([^\n)]*\([^\n)]*\)[^\n)]*\)"),
    ),
    ("reference link", re.compile(r"\[[^\]]+\]\[[^\]]*\]|^\s*\[[^\]]+\]:", re.MULTILINE)),
    ("footnote", re.compile(r"\[\^[^\]]+\]")),
    ("task list", re.compile(r"^\s*[-*+]\s+\[[ xX]\]", re.MULTILINE)),
]


class UnsupportedInput(ValueError):
    pass


class BodyTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def stash(pattern, text, values):
    def replace(match):
        values.append(match.group(1))
        return "\ue000{}\ue001".format(len(values) - 1)

    return pattern.sub(replace, text)


def restore(text, values):
    for index, value in enumerate(values):
        text = text.replace("\ue000{}\ue001".format(index), value)
    return text


def reject_unsupported(text):
    without_breaks = BREAK_PATTERN.sub("", text)
    for label, pattern in UNSUPPORTED_PATTERNS:
        if pattern.search(without_breaks):
            raise UnsupportedInput("unsupported Markdown construct: {}".format(label))
    if re.search(r"<[^>]+>", without_breaks):
        raise UnsupportedInput("unsupported Markdown construct: raw HTML")


def source_text(raw, drops, drop_title):
    text = raw
    for pattern in drops:
        try:
            text = re.sub(pattern, "", text, flags=re.DOTALL)
        except re.error as error:
            raise UnsupportedInput("invalid --drop pattern {!r}: {}".format(pattern, error))
    if drop_title:
        text = TITLE_PATTERN.sub("", text)

    reject_unsupported(text)

    protected = []
    text = stash(ESCAPE_PATTERN, text, protected)
    text = stash(INLINE_CODE_PATTERN, text, protected)
    if "`" in text:
        raise UnsupportedInput("unsupported Markdown construct: unmatched or multi-backtick code")

    text = IMAGE_PATTERN.sub("", text)
    text = LINK_PATTERN.sub(r"\1", text)
    if re.search(r"!?\[[^\]]*\]\(", text):
        raise UnsupportedInput("unsupported Markdown construct: complex inline link")

    text = HEADING_PATTERN.sub("", text)
    text = BULLET_PATTERN.sub("", text)
    text = NUMBERED_PATTERN.sub("", text)
    text = QUOTE_PATTERN.sub("", text)
    text = TABLE_RULE_PATTERN.sub("", text)
    text = BREAK_PATTERN.sub(" ", text)
    text = text.replace("|", " ")
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = re.sub(r"(?<!\w)[*_]|[*_](?!\w)", "", text)
    text = html.unescape(text)
    text = restore(text, protected)
    return WHITESPACE_PATTERN.sub("", text)


def body_text(raw):
    parser = BodyTextExtractor()
    parser.feed(raw)
    parser.close()
    return WHITESPACE_PATTERN.sub("", "".join(parser.parts))


def first_difference(left, right, context):
    for index, (source_character, body_character) in enumerate(zip(left, right)):
        if source_character != body_character:
            return {
                "index": index,
                "source": left[max(0, index - context):index + context],
                "body": right[max(0, index - context):index + context],
            }
    shorter = min(len(left), len(right))
    if len(left) == len(right):
        return None
    longer = left if len(left) > len(right) else right
    missing_from = "body" if len(left) > len(right) else "source"
    return {
        "index": shorter,
        "note": "one side ends here; the rest is missing from the {}".format(missing_from),
        "tail": longer[shorter:shorter + context * 2],
    }


def fail(message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source")
    parser.add_argument("body")
    parser.add_argument("--drop", action="append", default=[])
    parser.add_argument("--drop-title", action="store_true")
    parser.add_argument("--context", type=int, default=70)
    options = parser.parse_args(argv)

    if options.context < 1:
        return fail("--context must be at least 1")
    try:
        with open(options.source, encoding="utf-8") as handle:
            raw_source = handle.read()
        with open(options.body, encoding="utf-8") as handle:
            raw_body = handle.read()
        left = source_text(raw_source, options.drop, options.drop_title)
        right = body_text(raw_body)
    except (OSError, UnicodeDecodeError) as error:
        return fail("cannot read input: {}".format(error))
    except UnsupportedInput as error:
        return fail(str(error))

    result = {
        "ok": left == right,
        "source_characters": len(left),
        "body_characters": len(right),
    }
    if left != right:
        result["first_difference"] = first_difference(left, right, options.context)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
