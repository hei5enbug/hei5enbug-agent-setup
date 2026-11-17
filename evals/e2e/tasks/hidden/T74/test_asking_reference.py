from pathlib import Path

from host.context import MAX_CONTEXT_BYTES, render_context

ROOT = Path(__file__).resolve().parents[2]
ENTRY = "Before asking the user a question, read asking.md."
ENTRY_LINE = "- " + ENTRY
RULES = [
    "- Ask one question at a time, with the decision it blocks in the first sentence.",
    "- Give two or three options, put the recommended one first, and say why it is recommended in one clause.",
    "- Spell out any term, abbreviation, or label the user has not seen in this conversation.",
    "- Never ask what the code, the schema, or an existing agreement already settles; state the basis instead.",
    "- After the answer, repeat the decision in one line and continue without asking it again.",
    "- When no answer is needed to continue, record the assumption and go on.",
    "- Ask nothing about a reversible local step that is in scope.",
    "- If the user does not answer, continue only with work that does not depend on the answer.",
    "- Never bundle an unrelated approval into a question about a decision.",
]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_the_context_shrinks_under_700_bytes_without_raising_the_budget():
    assert MAX_CONTEXT_BYTES == 1800
    assert len(render_context(ROOT, {}).encode("utf-8")) <= 700


def test_common_keeps_one_entry_line_and_loses_the_section():
    common = read("instructions/session/common.md")
    assert common.splitlines().count(ENTRY_LINE) == 1
    assert "## Asking the user" not in common
    for rule in RULES:
        assert rule not in common
    assert "- Report what the reader must act on first." in common
    assert render_context(ROOT, {}).count(ENTRY) == 1


def test_the_reference_holds_every_moved_rule_word_for_word_in_order():
    lines = read("instructions/asking.md").splitlines()
    assert lines[0] == "# Asking the user"
    assert [line for line in lines if line.startswith("- ")] == RULES


def test_the_korean_mirror_follows_the_mirror_rules():
    lines = read("docs/ko/instructions/asking.ko.md").splitlines()
    assert lines[0].startswith("# ") and len(lines[0]) > 2
    assert "(../../../instructions/asking.md)" in lines[2] and lines[2].startswith("> ")
    assert "비권위" in "\n".join(lines[2:4])
    assert sum(1 for line in lines if line.startswith("- ")) == len(RULES)


def test_the_documentation_map_and_its_mirror_list_the_reference():
    english = [line for line in read("README.md").splitlines() if "instructions/asking.md" in line]
    korean = [line for line in read("docs/ko/README.ko.md").splitlines() if "asking" in line]
    assert len(english) == 1 and english[0].startswith("| [instructions/asking.md](instructions/asking.md) |")
    assert len(korean) == 1 and korean[0].startswith("| [instructions/asking.md](")
