"""The code that candidate c of issue 102 adds to scripts/text_review.py, kept as text that `apply.py` inserts before `build_assignment`.

It is not imported by the plugin; `apply.py` reads this file as text, so the block below is exactly what a patched script holds.
"""

CODE = '''\
HISTORY_VERSION = 1
SENTENCE_BREAK = re.compile(r"(?<=[.!?。！？])\\s+|\\n+")
TRIMMED_TYPE = "removable"
TRIM_HEADING = "## Sentences the cut pass covers\\n"
TRIM_EXPLANATION = (
    "An earlier run of this draft reviewed it already. Report a `removable` finding only for a sentence listed below; a "
    "`removable` finding anywhere else is dropped. Report findings of every other type for the whole draft.\\n"
)


def sentences_of(text: str) -> list[str]:
    return [" ".join(part.split()) for part in SENTENCE_BREAK.split(text) if part and part.strip()]


def load_trim(path: str | None, draft: str) -> dict | None:
    """The sentences changed since the previous run of one draft and those an earlier run flagged, read from its history file."""
    if not path:
        return None
    current = sentences_of(draft)
    trim = {"path": path, "current": current, "first": True, "changed": set(range(len(current))), "flagged": set()}
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return trim
    except (OSError, ValueError) as error:
        raise TextReviewError(f"cannot read the history {path}: {error}") from error
    previous, flagged = stored.get("sentences") if isinstance(stored, dict) else None, stored.get("flagged") if isinstance(stored, dict) else None
    if not (isinstance(previous, list) and isinstance(flagged, list) and all(isinstance(item, str) for item in previous + flagged)):
        raise TextReviewError(f"{path} is not the history of a text review")
    earlier = set(flagged)
    trim.update(first=False, changed=set())
    for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(None, previous, current, autojunk=False).get_opcodes():
        if tag != "equal":
            trim["changed"].update(range(new_start, new_end))
        if any(previous[index] in earlier for index in range(old_start, old_end)):
            trim["flagged"].update(range(new_start, new_end) if tag != "equal" else
                                   (new_start + offset for offset in range(old_end - old_start) if previous[old_start + offset] in earlier))
    return trim


def locate(quote: str, sentences: list[str]) -> set[int]:
    """The indexes of the sentences a quote overlaps; empty when the quote is not in the draft."""
    text, spans = "", []
    for sentence in sentences:
        spans.append((len(text), len(text) + len(sentence)))
        text += sentence + " "
    needle = " ".join(quote.split())
    start = text.find(needle) if needle else -1
    if start < 0:
        return set()
    end = start + len(needle)
    return {index for index, (low, high) in enumerate(spans) if low < end and start < high}


def trim_findings(findings: list[dict], trim: dict | None) -> tuple[list[dict], list[dict]]:
    """Split the findings into those kept and the `removable` ones in a sentence no run changed and no run flagged."""
    if trim is None:
        return findings, []
    kept, dropped = [], []
    for item in findings:
        where = locate(item["quote"], trim["current"])
        (dropped if item["type"] == TRIMMED_TYPE and where and not where & (trim["changed"] | trim["flagged"]) else kept).append(item)
    return kept, dropped


def save_history(trim: dict | None, findings: list[dict]) -> None:
    if trim is None:
        return
    flagged = set(trim["flagged"]).union(*(locate(item["quote"], trim["current"]) for item in findings))
    document = {"version": HISTORY_VERSION, "sentences": trim["current"], "flagged": [trim["current"][index] for index in sorted(flagged)]}
    try:
        Path(trim["path"]).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    except OSError as error:
        raise TextReviewError(f"cannot write the history {trim['path']}: {error}") from error


def trim_section(trim: dict | None) -> list[str]:
    if trim is None or trim["first"]:
        return []
    listed = lambda indexes: fenced("\\n".join(trim["current"][index] for index in sorted(indexes)) or "(none)")  # noqa: E731
    return [TRIM_HEADING, TRIM_EXPLANATION, "### Changed since the previous run\\n", f"{listed(trim['changed'])}\\n",
            "### Flagged by an earlier run\\n", f"{listed(trim['flagged'] - trim['changed'])}\\n"]


'''
