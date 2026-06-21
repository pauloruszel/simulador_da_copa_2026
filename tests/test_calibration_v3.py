from src.calibration.backtesting import (
    brier_score,
    calibrate_group_stage_probabilities,
    evaluate_finished_matches,
    log_loss_score,
    tune_weights_grid,
    uniform_baseline_probs,
    write_backtest_report,
)
from src.calibration.team_strength import (
    build_calibrated_ratings,
    load_model_weights,
    opponent_adjusted_match_delta,
    save_calibrated_ratings,
)
from src.knockout import knockout_win_probability
from src.models import Match
from src.monte_carlo import SimulationConfig, run_monte_carlo
from src.data_provider import LocalJsonDataProvider


def test_opponent_adjusted_delta_rewards_strong_opponent():
    ratings = {"Haiti": 1540, "Brazil": 2045}
    weights = load_model_weights("balanced")
    delta = opponent_adjusted_match_delta("Haiti", "Brazil", 1, 1, ratings, weights)
    assert delta > 0


def test_opponent_adjusted_delta_small_for_expected_win_against_weak_team():
    ratings = {"Brazil": 2045, "Haiti": 1540}
    weights = load_model_weights("balanced")
    delta = opponent_adjusted_match_delta("Brazil", "Haiti", 1, 0, ratings, weights)
    assert delta < 15


def test_goal_diff_saturation_against_weak_team():
    ratings = {"Brazil": 2045, "Haiti": 1540}
    weights = load_model_weights("balanced")
    three = opponent_adjusted_match_delta("Brazil", "Haiti", 3, 0, ratings, weights)
    six = opponent_adjusted_match_delta("Brazil", "Haiti", 6, 0, ratings, weights)
    assert six == three


def test_contextual_loss_penalties():
    weights = load_model_weights("balanced")
    ratings = {"Haiti": 1540, "Brazil": 2045}
    weak_loses_to_strong = opponent_adjusted_match_delta("Haiti", "Brazil", 0, 1, ratings, weights)
    strong_loses_to_weak = opponent_adjusted_match_delta("Brazil", "Haiti", 0, 1, ratings, weights)
    assert strong_loses_to_weak < weak_loses_to_strong


def test_model_presets_and_knockout_probability_limits():
    high_upset = load_model_weights("high_upset")
    assert high_upset["knockout"]["sensitivity"] == 520
    ratings = {"A": 2400, "B": 1200}
    assert knockout_win_probability("A", "B", ratings, 420, 0.08, 0.88) == 0.88
    assert knockout_win_probability("B", "A", ratings, 420, 0.08, 0.88) == 0.08


def test_confidence_interval_fields_are_generated():
    p = LocalJsonDataProvider()
    result = run_monte_carlo(
        p.load_groups(),
        p.load_matches(),
        p.load_ratings(),
        p.load_knockout_bracket(),
        p.load_third_place_mapping(),
        SimulationConfig(simulations=10, seed=3, strict_third_mapping=True),
    )
    row = result["rows"][0]
    assert "winner_ci_low" in row
    assert "winner_ci_high" in row


def test_calibrated_rating_breakdown_shape():
    ratings = {"Brazil": 2045, "Haiti": 1540, "United States": 1880}
    matches = [Match("X1", "X", "Brazil", "Haiti", 3, 0, "finished")]
    result = build_calibrated_ratings(ratings, matches, load_model_weights("balanced"))
    assert result["breakdown"]["Brazil"]["final_rating"] >= ratings["Brazil"]
    assert "opponent_adjusted_component" in result["breakdown"]["Brazil"]


def test_rating_breakdown_files_are_generated():
    ratings = {"Brazil": 2045, "Haiti": 1540}
    matches = [Match("X1", "X", "Brazil", "Haiti", 3, 0, "finished")]
    result = build_calibrated_ratings(ratings, matches, load_model_weights("balanced"))
    from pathlib import Path
    out = Path("output/test_calibration_v3")
    save_calibrated_ratings(result, out)
    assert (out / "rating_breakdown.csv").exists()
    assert (out / "rating_breakdown.json").exists()



def test_group_stage_probability_calibration_constraints():
    cfg = {
        "group_stage_calibration": {
            "enabled": True,
            "draw_floor_group_stage": 0.20,
            "draw_floor_balanced_game": 0.26,
            "favorite_ceiling_group_stage": 0.80,
            "favorite_ceiling_strong_favorite": 0.76,
            "upset_floor_group_stage": 0.06,
            "probability_temperature": 1.05,
            "strong_favorite_rating_gap_threshold": 250,
        }
    }
    probs = calibrate_group_stage_probabilities(0.90, 0.08, 0.02, 450, "favorito forte", cfg)
    assert round(sum(probs.values()), 8) == 1
    assert probs["home"] <= 0.76 + 1e-9
    assert probs["draw"] >= 0.20 - 1e-9
    assert probs["away"] >= 0.06 - 1e-9


def test_balanced_game_draw_floor_and_redistribution():
    cfg = {
        "group_stage_calibration": {
            "enabled": True,
            "draw_floor_group_stage": 0.18,
            "draw_floor_balanced_game": 0.28,
            "favorite_ceiling_group_stage": 0.84,
            "favorite_ceiling_strong_favorite": 0.76,
            "upset_floor_group_stage": 0.06,
            "probability_temperature": 1.0,
            "strong_favorite_rating_gap_threshold": 250,
        }
    }
    probs = calibrate_group_stage_probabilities(0.42, 0.20, 0.38, 40, "jogo equilibrado", cfg)
    assert round(sum(probs.values()), 8) == 1
    assert probs["draw"] >= 0.28 - 1e-9
    assert probs["home"] < 0.42


def test_non_final_score_calibration_does_not_worsen_controlled_draw_case():
    cfg = {
        "group_stage_calibration": {
            "enabled": True,
            "draw_floor_group_stage": 0.24,
            "draw_floor_balanced_game": 0.28,
            "favorite_ceiling_group_stage": 0.80,
            "favorite_ceiling_strong_favorite": 0.76,
            "upset_floor_group_stage": 0.06,
            "probability_temperature": 1.05,
            "strong_favorite_rating_gap_threshold": 250,
        }
    }
    raw = {"home": 0.60, "draw": 0.18, "away": 0.22}
    calibrated = calibrate_group_stage_probabilities(0.60, 0.18, 0.22, 160, "favorito moderado", cfg)
    assert brier_score(calibrated, "draw") <= brier_score(raw, "draw")


def test_backtesting_metrics_and_tuning():
    ratings = {"Brazil": 2045, "Haiti": 1540}
    matches = [Match("X1", "X", "Brazil", "Haiti", 3, 0, "finished")]
    weights = load_model_weights("balanced")
    result = evaluate_finished_matches(matches, ratings, weights)
    assert result["matches_evaluated"] == 1
    assert result["brier_mean"] >= 0
    assert "baselines" in result
    assert "uniform" in result["baselines"]
    assert result["rows"][0]["probability_source"] == "model"
    assert result["rows"][0]["score"] == "3-0"
    probs = {"home": 0.7, "draw": 0.2, "away": 0.1}
    assert brier_score(probs, "home") < brier_score(probs, "away")
    assert log_loss_score(probs, "home") < log_loss_score(probs, "away")
    tuned = tune_weights_grid(matches, ratings, weights)
    assert tuned["tested"] > 1
    assert tuned["best"]["config"] != weights
    assert "baseline" in tuned


def test_backtest_walk_forward_does_not_use_current_match_in_calibration():
    ratings = {"Brazil": 2045, "Haiti": 1540, "Morocco": 2005}
    matches = [
        Match("X1", "X", "Brazil", "Haiti", 6, 0, "finished", "2026-06-01T00:00:00Z"),
        Match("X2", "X", "Brazil", "Morocco", 1, 1, "finished", "2026-06-02T00:00:00Z"),
    ]
    weights = load_model_weights("balanced")
    base = evaluate_finished_matches(matches, ratings, weights, calibrate_ratings=False)
    walk_forward = evaluate_finished_matches(matches, ratings, weights, calibrate_ratings=True)

    assert walk_forward["rows"][0]["home_prob"] == base["rows"][0]["home_prob"]
    assert walk_forward["rows"][0]["away_prob"] == base["rows"][0]["away_prob"]
    assert walk_forward["rows"][1]["home_prob"] != base["rows"][1]["home_prob"]


def test_uniform_baseline_and_backtest_report_files():
    probs = uniform_baseline_probs()
    assert round(sum(probs.values()), 8) == 1
    assert probs["home"] == probs["draw"] == probs["away"]
    ratings = {"Brazil": 2045, "Haiti": 1540}
    matches = [Match("X1", "X", "Brazil", "Haiti", 3, 0, "finished")]
    result = evaluate_finished_matches(matches, ratings, load_model_weights("balanced"))
    write_backtest_report(result, "output/test_calibration_v3")
    from pathlib import Path
    assert Path("output/test_calibration_v3/backtest_results.csv").exists()
    text = Path("output/test_calibration_v3/backtest_report.txt").read_text()
    assert "Baselines" in text
    assert "Analise por categoria" in text
