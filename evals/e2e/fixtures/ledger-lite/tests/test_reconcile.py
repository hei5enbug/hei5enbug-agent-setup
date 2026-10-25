from datetime import date
from decimal import Decimal

from ledger.journal import Journal
from ledger.models import Entry, StatementLine
from ledger.reconcile import reconcile
from ledger.statements import load_statement


def test_march_statement_has_one_unexplained_fee(march_journal, sample_dir):
    result = reconcile(march_journal, load_statement(sample_dir / "march_statement.csv"))
    assert len(result.matched) == 5
    assert [line.description for line in result.unmatched_lines] == ["Monthly bank fee"]
    assert result.unmatched_entries == []
    assert not result.clean


def test_entries_are_used_at_most_once():
    journal = Journal([Entry(date(2026, 3, 1), "bank", Decimal("10"))])
    lines = [StatementLine(date(2026, 3, 1), "a", Decimal("10")), StatementLine(date(2026, 3, 2), "b", Decimal("10"))]
    result = reconcile(journal, lines)
    assert len(result.matched) == 1 and len(result.unmatched_lines) == 1


def test_window_limits_the_date_difference():
    journal = Journal([Entry(date(2026, 3, 1), "bank", Decimal("10"))])
    far = [StatementLine(date(2026, 3, 9), "late", Decimal("10"))]
    assert reconcile(journal, far).matched == []
    assert len(reconcile(journal, far, window_days=10).matched) == 1


def test_other_accounts_are_ignored():
    journal = Journal([Entry(date(2026, 3, 1), "cash", Decimal("10"))])
    result = reconcile(journal, [StatementLine(date(2026, 3, 1), "x", Decimal("10"))])
    assert result.matched == [] and result.unmatched_entries == []
