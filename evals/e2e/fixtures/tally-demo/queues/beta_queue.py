"""Library beta: rebuilds the whole topic list on every call."""

STEPS = 0
_topics: dict[str, list[str]] = {}


def put(topic: str, job: str) -> None:
    global STEPS
    items = list(_topics.get(topic, []))
    STEPS += 3 + len(items) // 100
    _topics[topic] = items + [job]


def get(topic: str) -> str | None:
    global STEPS
    items = list(_topics.get(topic, []))
    STEPS += 3 + len(items) // 100
    if not items:
        return None
    first, *rest = items
    _topics[topic] = rest
    return first
