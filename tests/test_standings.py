from src.models import Match
from src.standings import calculate_group_rankings, empty_group_table, apply_result, sort_table


R = {"A": 1000, "B": 900, "C": 800, "D": 700}


def test_apply_result_points_and_goal_difference():
    table = empty_group_table("X", ["A", "B"])
    apply_result(table, "A", "B", 2, 1)
    assert table["A"].points == 3
    assert table["A"].goal_difference == 1
    assert table["B"].losses == 1


def test_sort_by_points_goal_difference_goals_for_rating():
    table = empty_group_table("X", ["A", "B", "C", "D"])
    apply_result(table, "A", "B", 1, 0)
    apply_result(table, "C", "D", 3, 2)
    assert [s.team for s in sort_table(table, R)][:2] == ["C", "A"]


def test_calculate_group_rankings():
    groups = {"X": ["A", "B", "C", "D"]}
    matches = [Match("X1", "X", "A", "B", 1, 1, "finished")]
    assert calculate_group_rankings(groups, matches, R)["X"][0].team == "A"



def test_head_to_head_breaks_points_tie_before_goal_difference():
    table = empty_group_table("X", ["A", "B"])
    table["A"].points = 6
    table["A"].goals_for = 2
    table["A"].goals_against = 2
    table["B"].points = 6
    table["B"].goals_for = 12
    table["B"].goals_against = 2
    matches = [Match("X1", "X", "A", "B", 1, 0, "finished")]
    # A and B finish tied on points; B has much better overall goal difference,
    # but A won the direct match and must rank ahead under the 2026 tiebreaker.
    assert [s.team for s in sort_table(table, R, matches)] == ["A", "B"]
