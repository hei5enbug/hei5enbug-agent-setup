"""Pair parsing for the demo library."""

from .tokens import DELIMITERS


def parse_pair(text):
    """Split `text` at the first delimiter and return the stripped key and value."""
    for delimiter in DELIMITERS:
        if delimiter in text:
            key, value = text.split(delimiter, 1)
            return key.strip(), value.strip()
    raise ValueError("no delimiter in " + repr(text))


def parse_many(lines):
    """Parse each non-empty line with `parse_pair`."""
    return [parse_pair(line) for line in lines if line.strip()]
