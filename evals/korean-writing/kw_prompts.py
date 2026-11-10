"""Frozen cases, writing rules, blind shuffle, and the writer and grader prompts."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SHARED_TEXT = REPO_ROOT / "instructions" / "shared-text.md"
CASES_FILE = HERE / "cases.json"
SEEDED_FILE = HERE / "seeded.json"
DEFAULT_SEED = "korean-writing"

COMPLETENESS_HEADING = "## Cut and completeness passes"
READABLE_HEADING = "## Readable shared text"
LENGTH_BUDGET_ITEM = re.compile(r"^3\. ", re.MULTILINE)
NEXT_HEADING = re.compile(r"^## ", re.MULTILINE)


def load_cases(path: Path = CASES_FILE) -> dict:
    return {case["id"]: case for case in json.loads(path.read_text(encoding="utf-8"))}


def load_seeded(path: Path = SEEDED_FILE) -> list:
    return json.loads(path.read_text(encoding="utf-8"))["pairs"]


def load_rules(shared_text: Path = SHARED_TEXT) -> str:
    """Return items 1 and 2 of the cut and completeness passes plus the readable shared text section."""
    text = shared_text.read_text(encoding="utf-8")
    start = text.index(COMPLETENESS_HEADING)
    item_three = LENGTH_BUDGET_ITEM.search(text, start)
    if item_three is None:
        raise ValueError(f"{shared_text}: item 3 of the cut and completeness passes not found")
    readable = text.index(READABLE_HEADING)
    following = NEXT_HEADING.search(text, readable + len(READABLE_HEADING))
    readable_end = following.start() if following else len(text)
    return text[start:item_three.start()].rstrip() + "\n\n" + text[readable:readable_end].rstrip()


def fact_lines(case: dict) -> str:
    return "\n".join(f"- {fact['id']}: {fact['text']}" for fact in case["facts"])


def writer_prompt(case: dict, rules: str) -> str:
    return f"""You write one Korean text for people to read. Write it from the sources below only; you cannot run commands or look anything else up.

# Writing rules
{rules}

# Text to write
Kind: {case['kind']} ({case['title']})
Reader: {case['reader']}

# Sources
{case['sources']}

# Output
Write the finished Korean text only, ready to post. No preamble, no explanation, no code fence around the whole text."""


def grader_prompt(case: dict, drafts: dict, rules: str) -> str:
    labels = list(drafts)
    shown = "\n\n".join(f"=== DRAFT {label} ===\n{text}\n=== END DRAFT {label} ===" for label, text in drafts.items())
    entry = '{"missing_facts": [], "added_facts": [], "unnatural": [{"quote": "", "why": ""}]}'
    per_draft = ", ".join(f'"{label}": {entry}' for label in labels)
    order = ", ".join(f'"{label}"' for label in labels)
    return f"""You grade Korean drafts written for the same task by different writers whose identity is hidden. You are a strict, native-level Korean editor.

# Writing rules the writers were given
{rules}

# Task
Kind: {case['kind']} ({case['title']})
Reader: {case['reader']}

# Sources the writers had
{case['sources']}

# Required facts (each must be present in a draft, in meaning; wording may differ)
{fact_lines(case)}

# Drafts
{shown}

# Grading
For every draft decide:
1. missing_facts: ids of required facts whose meaning is absent or contradicted. Judge by the fact text only: a specific number or detail that appears in the sources but not in the fact text is not required, and the writing rules tell writers to leave out numbers that do not change understanding.
2. added_facts: facts, claims, numbers, or names that are not in the sources (short quotes). Rephrasing a source fact, or a reasonable connective, is not an added fact.
3. unnatural: every translated or unnatural phrasing in the draft (English-style structure, literal rendering of an English term, stiff nominalisation, awkward particles, wrong register), each with the exact quote and a few words of why. List every instance; an empty list means the Korean reads fully natural.
Then ranking: order the drafts that have NO missing fact and NO added fact from most natural to least natural (first = reads most like Korean written by a careful Korean colleague for this reader and kind of text). Leave out of "ranking" every draft that has a missing or added fact. Also give "ranking_all": all drafts, including those with a fact problem, ordered by naturalness of the Korean alone. Break ties by deciding; do not output ties.

Output exactly one JSON object and nothing else:
{{"drafts": {{{per_draft}}}, "ranking": [{order}], "ranking_all": [{order}]}}"""


def shuffle_key(seed: str, task_id: str, run: int, writers: list) -> dict:
    """Map the labels A, B, C, ... to writer ids in an order fixed by the seed, task, and run."""
    rng = random.Random(f"{seed}-{task_id}-{run}")
    shuffled = sorted(writers)
    rng.shuffle(shuffled)
    return {chr(ord("A") + index): writer for index, writer in enumerate(shuffled)}


def parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        first, last = cleaned.find("{"), cleaned.rfind("}")
        if first < 0 or last < first:
            raise
        return json.loads(cleaned[first:last + 1])
