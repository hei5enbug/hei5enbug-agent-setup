import io
from pathlib import Path

import pytest

from tally.cli import main
from tally.costs import team_cost
from tally.errors import UnknownTeam


def count_rate_file_reads(monkeypatch):
    reads = []
    original = Path.open

    def counting(self, *args, **kwargs):
        if self.name == "rates.json":
            reads.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting)
    return reads


def test_two_cost_calls_read_the_rates_file_once(monkeypatch):
    reads = count_rate_file_reads(monkeypatch)
    assert team_cost("alpha") == team_cost("alpha") == 680
    assert len(reads) == 1


def test_the_cost_command_still_prints_the_cost_and_rejects_an_unknown_team():
    out = io.StringIO()
    assert main(["cost", "beta"], stdout=out, stderr=io.StringIO()) == 0
    assert out.getvalue() == "1155\n"
    with pytest.raises(UnknownTeam):
        team_cost("delta")
