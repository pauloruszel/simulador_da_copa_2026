from src.models import TeamStanding
from src.qualification import qualification_snapshot, select_best_thirds


def standing(team, group, pts, gd=0, gf=0):
    s = TeamStanding(team, group)
    s.points = pts
    s.goals_for = gf
    s.goals_against = gf - gd
    return s


def test_select_top_two_and_best_eight_thirds():
    rankings = {}
    ratings = {}
    for i, g in enumerate("ABCDEFGHIJKL"):
        rows = [
            standing(f"{g}1", g, 9),
            standing(f"{g}2", g, 6),
            standing(f"{g}3", g, i),
            standing(f"{g}4", g, 0),
        ]
        rankings[g] = rows
        ratings.update({r.team: 1000 + i for r in rows})
    thirds = select_best_thirds(rankings, ratings)
    assert len(thirds) == 8
    assert thirds[0].team == "L3"
    q = qualification_snapshot(rankings, ratings)
    assert len(q["qualifiers"]) == 32

