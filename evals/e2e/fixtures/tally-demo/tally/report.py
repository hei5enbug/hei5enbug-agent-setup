"""Report helpers."""


def top_notes(notes: list[str], limit: int = 3) -> tuple[str, ...]:
    """Return the `limit` longest notes, longest first; equal lengths keep their input order."""
    ranked = sorted(notes, key=len, reverse=True)
    return tuple(ranked[:limit])
