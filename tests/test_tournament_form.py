from src.calibration.tournament_form import recalibrate_ratings_from_results
from src.models import Match


def test_recalibrate_ratings_rewards_good_results_but_caps_delta():
    ratings = {"United States": 1880, "Brazil": 2045, "Haiti": 1540}
    matches = [
        Match("D01", "D", "United States", "Brazil", 2, 0, "finished"),
        Match("D02", "D", "United States", "Haiti", 3, 0, "finished"),
    ]
    result = recalibrate_ratings_from_results(ratings, matches)
    assert result["ratings"]["United States"] > ratings["United States"]
    assert result["ratings"]["United States"] <= ratings["United States"] + 80
    assert result["ratings"]["Brazil"] < ratings["Brazil"]
