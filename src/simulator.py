from __future__ import annotations

from .data_provider import LocalJsonDataProvider, apply_scenario, validate_data, validate_third_place_mapping
from .monte_carlo import SimulationConfig, run_monte_carlo
from .reports import write_reports
from .storage.json_store import JsonStore
from .calibration.team_strength import build_calibrated_ratings, load_model_weights, load_weights_file, save_calibrated_ratings

USE_OFFICIAL_FIFA_BRACKET = True
STRICT_THIRD_PLACE_MAPPING = True


def run(
    simulations: int = 50000,
    seed: int | None = None,
    scenario: str | None = None,
    team: str = "Brazil",
    use_adjusted_ratings: bool = False,
    rating_source: str = "base",
    model_preset: str | None = None,
    weights_file: str | None = None,
    write_output: bool = True,
) -> dict:
    provider = LocalJsonDataProvider()
    groups = provider.load_groups()
    matches = apply_scenario(provider.load_matches(), scenario)
    ratings = provider.load_ratings()
    weight_warnings = []
    if weights_file:
        model_config, weight_warnings = load_weights_file(weights_file, model_preset)
    else:
        model_config = load_model_weights(model_preset)
    rating_breakdown = None
    if rating_source == "calibrated":
        calibrated = build_calibrated_ratings(
            ratings,
            matches,
            model_config,
            JsonStore().read("data/fifa_ranking.json", {}),
            JsonStore().read("data/elo_ratings.json", {}),
            JsonStore().read("data/odds.json", {}),
        )
        if write_output:
            save_calibrated_ratings(calibrated)
        ratings = calibrated["ratings"]
        rating_breakdown = calibrated["breakdown"]
    elif use_adjusted_ratings or rating_source == "adjusted":
        adjusted = JsonStore().read("data/adjusted_ratings.json", {})
        ratings = adjusted.get("ratings") or ratings
    bracket = provider.load_knockout_bracket()
    third_mapping = provider.load_third_place_mapping()
    validate_data(groups, matches, ratings, bracket)
    validate_third_place_mapping(third_mapping)
    result = run_monte_carlo(
        groups,
        matches,
        ratings,
        bracket,
        third_mapping,
        SimulationConfig(
            simulations=simulations,
            seed=seed,
            strict_third_mapping=STRICT_THIRD_PLACE_MAPPING,
            model_config=model_config,
        ),
    )
    result["rating_source"] = rating_source
    result["model_preset"] = model_config.get("preset")
    result["weights_file"] = model_config.get("weights_file")
    result["weight_warnings"] = weight_warnings
    result["rating_breakdown"] = rating_breakdown or {}
    if write_output:
        write_reports(result, team=team)
    return result
