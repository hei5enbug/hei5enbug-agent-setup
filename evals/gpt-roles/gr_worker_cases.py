"""The three new worker cases of the GPT role comparison: small seeded repositories, a fixed list of allowed paths, and hidden
tests applied after the run. A case passes when the hidden tests and the visible tests pass, only allowed paths changed, and
no commit was made."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]

SLUG_SOURCE = '''def slugify(text):
    """Lowercase `text`, replace each run of non-alphanumeric characters with one hyphen, and strip hyphens at both ends."""
    out = []
    for char in text.lower():
        out.append(char if char.isalnum() else "-")
    return "".join(out).strip("-")
'''

STOCK_SOURCE = '''class Stock:
    """Available quantity per sku."""

    def __init__(self, quantities):
        self._available = dict(quantities)

    def available(self, sku):
        return self._available[sku]

    def skus(self):
        return sorted(self._available)
'''

REPORT_SOURCE = '''def total_available(stock):
    return sum(stock.available(sku) for sku in stock.skus())
'''

TOTALS_SOURCE = '''def calc_total(items):
    """Sum quantity times price_cents over the items."""
    return sum(item["quantity"] * item["price_cents"] for item in items)
'''

INVOICE_SOURCE = '''from billing.totals import calc_total


def invoice_line(items):
    return f"Total: {calc_total(items)}"
'''

RECEIPT_SOURCE = '''from billing import totals


def receipt_total(items):
    return totals.calc_total(items)
'''

CLI_SOURCE = '''from billing.totals import calc_total


def main(items):
    return calc_total(items)
'''

CASES = {
    "W1": {
        "title": "Fix slugify so a run of separators becomes one hyphen",
        "files": {
            "slugs/__init__.py": "", "slugs/text.py": SLUG_SOURCE,
            "tests/test_text.py": 'from slugs.text import slugify\n\n\ndef test_simple():\n    assert slugify("Hello World") == "hello-world"\n',
        },
        "assignment": "Fix `slugify` in slugs/text.py so it does what its docstring says. Edit only slugs/text.py and the tests folder. Run the tests, make no commit, and report the changed paths and the test result.\n",
        "allowed": ("slugs/text.py", "tests/"),
        "hidden": {"tests_hidden/test_slug.py": (
            "from slugs.text import slugify\n\n\ndef test_runs_collapse():\n    assert slugify('a  b') == 'a-b'\n    assert slugify('a - b') == 'a-b'\n\n\n"
            "def test_ends_stripped():\n    assert slugify('--x--') == 'x'\n    assert slugify('!!!') == ''\n\n\n"
            "def test_unicode_letters_stay():\n    assert slugify('Café au lait') == 'café-au-lait'\n")},
    },
    "W2": {
        "title": "Add Stock.reserve and report.low_stock across two files",
        "files": {
            "inventory/__init__.py": "", "inventory/stock.py": STOCK_SOURCE, "inventory/report.py": REPORT_SOURCE,
            "tests/test_stock.py": "from inventory.stock import Stock\n\n\ndef test_available():\n    assert Stock({'a': 3}).available('a') == 3\n",
        },
        "assignment": (
            "Add `Stock.reserve(sku, quantity)` to inventory/stock.py: it lowers the available quantity of `sku` by `quantity` and returns "
            "the quantity left. An unknown sku raises KeyError; a quantity below 1 or above the available quantity raises ValueError and "
            "changes nothing. Add `low_stock(stock, threshold)` to inventory/report.py: the skus whose available quantity is at most "
            "`threshold`, in sorted order. Edit only inventory/stock.py, inventory/report.py, and the tests folder. Add tests, run them, "
            "make no commit, and report the changed paths and the test result.\n"),
        "allowed": ("inventory/stock.py", "inventory/report.py", "tests/"),
        "hidden": {"tests_hidden/test_reserve.py": (
            "import pytest\n\nfrom inventory.report import low_stock\nfrom inventory.stock import Stock\n\n\n"
            "def test_reserve_returns_left():\n    stock = Stock({'a': 5})\n    assert stock.reserve('a', 5) == 0\n    assert stock.available('a') == 0\n\n\n"
            "def test_reserve_rejects_bad_quantity_and_changes_nothing():\n    stock = Stock({'a': 5})\n"
            "    for quantity in (0, -1, 6):\n        with pytest.raises(ValueError):\n            stock.reserve('a', quantity)\n    assert stock.available('a') == 5\n\n\n"
            "def test_reserve_unknown_sku():\n    with pytest.raises(KeyError):\n        Stock({'a': 1}).reserve('b', 1)\n\n\n"
            "def test_low_stock_threshold_is_inclusive_and_sorted():\n    stock = Stock({'c': 2, 'a': 2, 'b': 9})\n    assert low_stock(stock, 2) == ['a', 'c']\n")},
    },
    "W3": {
        "title": "Rename calc_total to total_cents in every module and test",
        "files": {
            "billing/__init__.py": "", "billing/totals.py": TOTALS_SOURCE, "billing/invoice.py": INVOICE_SOURCE,
            "billing/receipt.py": RECEIPT_SOURCE, "billing/cli.py": CLI_SOURCE,
            "tests/test_totals.py": "from billing.totals import calc_total\n\n\ndef test_total():\n    assert calc_total([{'quantity': 2, 'price_cents': 150}]) == 300\n",
            "README.md": "Use `billing.totals.calc_total(items)` to sum a list of line items.\n",
        },
        "assignment": (
            "Rename `calc_total` to `total_cents` everywhere in the repository: its definition, every import and call in billing/, the test, and "
            "the README. Keep the behavior and leave no alias or mention of the old name. Edit only the billing folder, the tests folder, and "
            "README.md. Run the tests, make no commit, and report the changed paths and the test result.\n"),
        "allowed": ("billing/", "tests/", "README.md"),
        "hidden": {"tests_hidden/test_rename.py": (
            "import pathlib\n\nimport billing.totals as totals\nfrom billing.invoice import invoice_line\nfrom billing.receipt import receipt_total\n\n\n"
            "def test_new_name_works_everywhere():\n    items = [{'quantity': 3, 'price_cents': 100}]\n    assert totals.total_cents(items) == 300\n"
            "    assert invoice_line(items) == 'Total: 300'\n    assert receipt_total(items) == 300\n\n\n"
            "def test_old_name_is_gone():\n    assert not hasattr(totals, 'calc_total')\n    root = pathlib.Path(__file__).resolve().parents[1]\n"
            "    hits = [str(p) for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and 'tests_hidden' not in p.parts\n"
            "            and '__pycache__' not in p.parts and 'calc_total' in p.read_text(errors='ignore')]\n    assert hits == []\n")},
    },
}


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True).stdout


def seed(case_id: str, repo: Path) -> str:
    """Create the repository with one commit and return the commit id."""
    for relative, text in CASES[case_id]["files"].items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "-c", "user.name=demo", "-c", "user.email=demo@example.com", "add", "-A")
    git(repo, "-c", "user.name=demo", "-c", "user.email=demo@example.com", "commit", "-q", "-m", "seed")
    return git(repo, "rev-parse", "HEAD").strip()


def changed_paths(repo: Path, base: str) -> list[str]:
    tracked = git(repo, "diff", "--name-only", base).splitlines()
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(path for path in {*tracked, *untracked} if "__pycache__" not in path and not path.endswith(".pyc"))


def allowed(path: str, rules: tuple[str, ...]) -> bool:
    return any(path == rule or (rule.endswith("/") and path.startswith(rule)) for rule in rules)


def failures(case_id: str, repo: Path, base: str) -> list[str]:
    """The reasons a worker run fails the case; the hidden tests are copied in only now."""
    case, found = CASES[case_id], []
    if git(repo, "rev-parse", "HEAD").strip() != base:
        found.append("a commit was made")
    outside = [path for path in changed_paths(repo, base) if not allowed(path, case["allowed"])]
    if outside:
        found.append(f"paths outside the allowed ones changed: {', '.join(outside)}")
    visible = subprocess.run([*PYTEST, "tests"], cwd=repo, capture_output=True, text=True)
    if visible.returncode != 0:
        found.append("the visible tests fail")
    for relative, text in case["hidden"].items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    hidden = subprocess.run([*PYTEST, "tests_hidden"], cwd=repo, capture_output=True, text=True)
    if hidden.returncode != 0:
        found.append("the hidden tests fail: " + hidden.stdout.strip().splitlines()[-1] if hidden.stdout.strip() else "the hidden tests fail")
    return found
