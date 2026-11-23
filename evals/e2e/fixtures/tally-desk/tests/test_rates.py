import pytest

from tally.errors import UnknownTeam
from tally.rates import rate_for


def test_rate_for_reads_the_team_rate():
    assert rate_for("beta") == 55


def test_rate_for_rejects_an_unknown_team():
    with pytest.raises(UnknownTeam):
        rate_for("delta")
