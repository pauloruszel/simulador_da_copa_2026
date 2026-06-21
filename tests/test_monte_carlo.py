from src.data_provider import LocalJsonDataProvider, apply_scenario
from src.data_provider import validate_third_place_mapping
from src.monte_carlo import SimulationConfig, run_monte_carlo
from src.models import Match


def test_scenario_does_not_mutate_original():
    p = LocalJsonDataProvider()
    matches = p.load_matches()
    changed = apply_scenario(matches, "data/scenario.example.json")
    original = next(m for m in matches if m.id == "C03")
    scenario = next(m for m in changed if m.id == "C03")
    assert original.status == "scheduled"
    assert scenario.status == "finished"


def test_seed_reproducibility():
    p = LocalJsonDataProvider()
    args = (p.load_groups(), p.load_matches(), p.load_ratings(), p.load_knockout_bracket(), p.load_third_place_mapping())
    a = run_monte_carlo(*args, SimulationConfig(simulations=20, seed=7))
    b = run_monte_carlo(*args, SimulationConfig(simulations=20, seed=7))
    assert a["rows"] == b["rows"]


def test_official_third_place_mapping_is_complete():
    mapping = LocalJsonDataProvider().load_third_place_mapping()
    validate_third_place_mapping(mapping)
    assert len(mapping) == 495


def test_team_paths_and_real_elimination_counters_are_present():
    p = LocalJsonDataProvider()
    result = run_monte_carlo(
        p.load_groups(),
        p.load_matches(),
        p.load_ratings(),
        p.load_knockout_bracket(),
        p.load_third_place_mapping(),
        SimulationConfig(simulations=30, seed=11, strict_third_mapping=True),
    )
    brazil = next(row for row in result["rows"] if row["team"] == "Brazil")
    assert brazil["most_common_elimination_stage"] in {
        "Group stage", "Round of 32", "Round of 16", "Quarterfinal", "Semifinal", "Final", "Champion"
    }
    assert result["team_paths"]["Brazil"]["round32_opponents"]
    assert result["team_paths"]["Brazil"]["elimination_stages"]


def test_most_common_elimination_stage_uses_actual_elimination_not_progression():
    p = LocalJsonDataProvider()
    groups = p.load_groups()
    ratings = p.load_ratings()
    matches = []
    for group, teams in groups.items():
        strong, second, third, fourth = sorted(teams, key=lambda team: ratings[team], reverse=True)
        matches.extend([
            Match(f"{group}01", group, strong, second, 9, 0, "finished"),
            Match(f"{group}02", group, third, fourth, 0, 0, "finished"),
            Match(f"{group}03", group, strong, third, 9, 0, "finished"),
            Match(f"{group}04", group, second, fourth, 9, 0, "finished"),
            Match(f"{group}05", group, strong, fourth, 9, 0, "finished"),
            Match(f"{group}06", group, second, third, 9, 0, "finished"),
        ])
    result = run_monte_carlo(
        groups,
        matches,
        ratings,
        p.load_knockout_bracket(),
        p.load_third_place_mapping(),
        SimulationConfig(simulations=1, seed=5, strict_third_mapping=True),
    )
    haiti = next(row for row in result["rows"] if row["team"] == "Haiti")
    assert haiti["most_common_elimination_stage"] == "Group stage"
