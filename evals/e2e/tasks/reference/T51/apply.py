import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "tally/costs.py", "from .errors import UnknownTeam\nfrom .rates import load_rates\n", "from .rates import rate_for\n")
replace(repo, "tally/costs.py", "    rates = load_rates()\n    if team not in rates:\n        raise UnknownTeam(team)\n    return round(team_hours(load_entries()).get(team, 0.0) * rates[team])\n",
        "    return round(team_hours(load_entries()).get(team, 0.0) * rate_for(team))\n")
append(repo, "tests/test_cli.py", '''

def test_cost_uses_the_cached_rate():
    from tally import rates

    assert run("cost", "alpha")[1] == "680\\n"
    assert rates.rate_for("alpha") == 40
''')
