import random

from src.knockout import knockout_win_probability, resolve_knockout_slots, simulate_knockout_match
from src.models import TeamStanding


def rows(group):
    return [TeamStanding(f"{group}{i}", group) for i in range(1, 5)]


def test_resolve_regular_and_third_slots():
    rankings = {g: rows(g) for g in "ABCDEFGHIJKL"}
    bracket = {"round_of_32": [{"match_id": 1, "slot_a": "1C", "slot_b": "3A/B/C/D/F"}, {"match_id": 2, "slot_a": "2F", "slot_b": "2B"}]}
    mapping = {"A,B,C,D,E,F,G,H": {"3A/B/C/D/F": "3A"}}
    out = resolve_knockout_slots(rankings, list("ABCDEFGH"), bracket, mapping, True)
    assert out["1"]["team_a"] == "C1"
    assert out["1"]["team_b"] == "A3"
    assert out["2"]["team_a"] == "F2"


def test_knockout_probability_and_simulation():
    ratings = {"A": 2000, "B": 1500}
    assert knockout_win_probability("A", "B", ratings) > 0.5
    assert simulate_knockout_match("A", "B", ratings, random.Random(1)) in {"A", "B"}

