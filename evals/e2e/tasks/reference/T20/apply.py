import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "notes_cli/memo.py", "        return needle in self.title.casefold() or needle in self.body.casefold()\n",
        "        return (\n            needle in self.title.casefold()\n            or needle in self.body.casefold()\n"
        "            or any(needle in tag.casefold() for tag in self.tags)\n        )\n")
append(repo, "tests/test_memo.py", '''

def test_search_matches_a_tag():
    memo = make_memo(1, "Plan trip", "book flights", ("travel",))
    assert memo.matches("TRAV")
    assert not memo.matches("holiday")
''')
