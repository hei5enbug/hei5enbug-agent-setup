from tally.clock import now
from tally.store import load_entries


def test_load_entries_reads_the_default_file():
    assert len(load_entries()) == 10


def test_now_follows_tally_now(monkeypatch):
    monkeypatch.setenv("TALLY_NOW", "2026-11-16T09:05")
    assert now().isoformat() == "2026-11-16T09:05:00"
