"""Library alpha: one list per topic, constant work per call."""

STEPS = 0
_topics: dict[str, list[str]] = {}


def put(topic: str, job: str) -> None:
    global STEPS
    STEPS += 1
    _topics.setdefault(topic, []).append(job)


def get(topic: str) -> str | None:
    global STEPS
    STEPS += 1
    items = _topics.get(topic, [])
    return items.pop(0) if items else None
