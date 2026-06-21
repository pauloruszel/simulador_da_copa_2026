from src.reports import write_reports


def test_write_csv_json_summary():
    out = "output/test_reports"
    result = {
        "simulations": 1,
        "seed": 1,
        "third_mapping_approximate_pct": 0,
        "rows": [{
            "team": "Brazil", "group": "C", "group_winner_pct": 1, "group_runner_up_pct": 2,
            "best_third_pct": 3, "group_eliminated_pct": 4, "round32_pct": 5,
            "round16_pct": 6, "quarterfinal_pct": 7, "semifinal_pct": 8,
            "final_pct": 9, "winner_pct": 10, "most_common_round32_match": "76",
            "winner_ci_low": 9, "winner_ci_high": 11, "final_ci_low": 8, "final_ci_high": 10,
            "semifinal_ci_low": 7, "semifinal_ci_high": 9,
            "most_common_round32_opponent": "Sweden", "most_common_elimination_stage": "Final",
        }],
        "team_paths": {
            "Brazil": {
                "round32_matches": [{"name": "76", "count": 1, "pct": 100}],
                "round32_opponents": [{"name": "Sweden", "count": 1, "pct": 100}],
                "elimination_stages": [{"name": "Final", "count": 1, "pct": 100}],
            }
        },
    }
    paths = write_reports(result, out)
    assert all(p.exists() for p in paths)
    assert "Brazil" in paths[0].read_text()
    team_paths = next(path for path in paths if path.name == "team_paths_Brazil.json")
    assert "Sweden" in team_paths.read_text()
    assert any(path.name == "model_explanation.txt" for path in paths)
