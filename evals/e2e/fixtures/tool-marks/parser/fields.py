"""Split one line of comma-separated fields."""


def split_fields(line: str) -> list[str]:
    parts = line.rstrip("\n").split(",")
    while parts and parts[-1] == "":
        parts.pop()
    return [part.strip() for part in parts]
