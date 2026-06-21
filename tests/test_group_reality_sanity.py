from src.data_provider import LocalJsonDataProvider
from src.standings import calculate_group_rankings


def _standings_map():
    provider = LocalJsonDataProvider()
    rankings = calculate_group_rankings(provider.load_groups(), provider.load_matches(), provider.load_ratings())
    return {
        group: [(row.team, row.played, row.wins, row.draws, row.losses, row.goals_for, row.goals_against, row.goal_difference, row.points) for row in rows]
        for group, rows in rankings.items()
    }


def test_saved_results_match_official_group_tables_for_completed_matches():
    tables = _standings_map()
    assert tables["D"] == [
        ("United States", 2, 2, 0, 0, 6, 1, 5, 6),
        ("Australia", 2, 1, 0, 1, 2, 2, 0, 3),
        ("Paraguay", 2, 1, 0, 1, 2, 4, -2, 3),
        ("Turkey", 2, 0, 0, 2, 0, 3, -3, 0),
    ]
    assert tables["F"] == [
        ("Netherlands", 2, 1, 1, 0, 7, 3, 4, 4),
        ("Japan", 2, 1, 1, 0, 6, 2, 4, 4),
        ("Sweden", 2, 1, 0, 1, 6, 6, 0, 3),
        ("Tunisia", 2, 0, 0, 2, 1, 9, -8, 0),
    ]
    assert tables["I"] == [
        ("Norway", 1, 1, 0, 0, 4, 1, 3, 3),
        ("France", 1, 1, 0, 0, 3, 1, 2, 3),
        ("Senegal", 1, 0, 0, 1, 1, 3, -2, 0),
        ("Iraq", 1, 0, 0, 1, 1, 4, -3, 0),
    ]
    assert {row[0]: row[1:] for row in tables["K"]} == {
        "Colombia": (1, 1, 0, 0, 3, 1, 2, 3),
        "Portugal": (1, 0, 1, 0, 1, 1, 0, 1),
        "DR Congo": (1, 0, 1, 0, 1, 1, 0, 1),
        "Uzbekistan": (1, 0, 0, 1, 1, 3, -2, 0),
    }


def test_no_zero_point_heavy_loser_is_favored_over_four_point_team_in_same_group():
    tables = _standings_map()
    # Regression guard for the old Japan/Tunisia inversion bug.
    japan = next(row for row in tables["F"] if row[0] == "Japan")
    tunisia = next(row for row in tables["F"] if row[0] == "Tunisia")
    assert japan[-1] == 4
    assert tunisia[-1] == 0
    assert japan[7] - tunisia[7] == 12
