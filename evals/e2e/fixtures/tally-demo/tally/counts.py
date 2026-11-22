"""Counting helpers."""


def note_total(notes: list[str]) -> int:
    """Return how many non-empty notes the list holds."""
    return sum(1 for note in notes if note.strip())
