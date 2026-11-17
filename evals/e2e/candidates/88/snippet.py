STAGE_KEYWORDS = r"(?:steps?|stages?|phases?|divisions?|parts?|sections?|items?)"
STAGE_NUMBERS = r"\d+(?:\s*(?:to|through|and|–|-|,)\s*\d+)*"
STAGE_NUMBER_REFERENCE = re.compile(rf"(?<![\w-]){STAGE_KEYWORDS}\s+{STAGE_NUMBERS}(?!\w)(?!\.\d)", re.IGNORECASE)
STAGE_TITLE_AFTER = re.compile(r"\s*(?:[(:\"“'‘—–]|-\s|,?\s*[A-Z])")
STAGE_TITLE_BEFORE = re.compile(r"[A-Z][\w-]*(?:\s+[\w-]+){0,4}\s*[(\[—–-]\s*$")


def stage_number_alone(lines: list[tuple[int, str]]) -> list[dict]:
    found = []
    for number, line in lines:
        text = without_code(line)
        for match in STAGE_NUMBER_REFERENCE.finditer(text):
            if STAGE_TITLE_AFTER.match(text, match.end()) or STAGE_TITLE_BEFORE.search(text[:match.start()]):
                continue
            found.append(finding("stage-number-alone", number, line))
            break
    return found


