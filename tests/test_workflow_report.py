from pathlib import Path

from main import _write_workflow_report


def test_workflow_report_has_executive_section():
    steps = [
        {"name": "dry-run-multisource", "status": "ok", "message": "alteradas=0", "outputs": ["output/multisource_update_report.txt"], "metrics": {}},
        {"name": "backtest", "status": "ok", "message": "jogos=34", "outputs": ["output/backtest_report.txt"], "metrics": {}},
    ]
    metrics = {
        "team": "Brazil",
        "simulations": 1000,
        "seed": 42,
        "dry_run": {"changed_real": 0, "conflicts": 0, "warnings": 0, "non_final_score_detected": 0},
        "update": {"changed_real": 0, "conflicts": 0, "warnings": 0, "non_final_score_detected": 0},
        "backtest": {"brier": 0.623, "log_loss": 1.041, "rating_brier": 0.632, "rating_log_loss": 1.051, "uniform_brier": 0.667, "uniform_log_loss": 1.099},
        "balanced": {"winner_pct": 8.57, "final_pct": 16.22, "semifinal_pct": 30.86, "round32_pct": 100.0, "quarterfinal_pct": 53.96, "most_common_round32_opponent": "Japan"},
        "tuned": {"winner_pct": 8.39, "final_pct": 16.0, "semifinal_pct": 30.05, "round32_pct": 100.0, "quarterfinal_pct": 52.15, "most_common_round32_opponent": "Japan"},
        "balanced_path": {"round32_opponents": [{"name": "Japan", "pct": 35.0}], "elimination_stages": [{"name": "Quarterfinal", "pct": 23.0}]},
    }
    report = _write_workflow_report("full", steps, metrics, ["output/probabilities.csv"])
    text = Path(report["latest_report"]).read_text(encoding="utf-8")
    assert "Secao executiva" in text
    assert "Status geral: OK" in text
    assert "Melhor modelo pelo backtest: modelo atual" in text
    assert "Adversario provavel na primeira fase do mata-mata: Japan" in text
    assert "Maiores riscos do caminho:" in text
    assert "Arquivos gerados:" in text

from main import _write_global_report, _write_workflow_report


def _sample_result():
    rows = [
        {"team": "Argentina", "group": "J", "winner_pct": 20.0, "final_pct": 30.0, "semifinal_pct": 45.0, "quarterfinal_pct": 60.0, "round32_pct": 100.0, "group_winner_pct": 80.0, "group_runner_up_pct": 15.0, "best_third_pct": 4.0, "group_eliminated_pct": 1.0, "most_common_round32_opponent": "Ghana", "most_common_elimination_stage": "Champion"},
        {"team": "Brazil", "group": "C", "winner_pct": 8.5, "final_pct": 16.0, "semifinal_pct": 30.0, "quarterfinal_pct": 52.0, "round32_pct": 100.0, "group_winner_pct": 70.0, "group_runner_up_pct": 25.0, "best_third_pct": 4.0, "group_eliminated_pct": 1.0, "most_common_round32_opponent": "Japan", "most_common_elimination_stage": "Quarterfinal"},
        {"team": "Morocco", "group": "C", "winner_pct": 5.0, "final_pct": 10.0, "semifinal_pct": 20.0, "quarterfinal_pct": 40.0, "round32_pct": 90.0, "group_winner_pct": 20.0, "group_runner_up_pct": 40.0, "best_third_pct": 20.0, "group_eliminated_pct": 20.0, "most_common_round32_opponent": "Sweden", "most_common_elimination_stage": "Round of 16"},
        {"team": "Scotland", "group": "C", "winner_pct": 1.2, "final_pct": 3.0, "semifinal_pct": 6.0, "quarterfinal_pct": 12.0, "round32_pct": 70.0, "group_winner_pct": 8.0, "group_runner_up_pct": 25.0, "best_third_pct": 25.0, "group_eliminated_pct": 30.0, "most_common_round32_opponent": "Netherlands", "most_common_elimination_stage": "Round of 32"},
        {"team": "Haiti", "group": "C", "winner_pct": 0.4, "final_pct": 1.0, "semifinal_pct": 2.0, "quarterfinal_pct": 5.0, "round32_pct": 65.0, "group_winner_pct": 2.0, "group_runner_up_pct": 10.0, "best_third_pct": 30.0, "group_eliminated_pct": 35.0, "most_common_round32_opponent": "Germany", "most_common_elimination_stage": "Group stage"},
    ]
    return {"rows": rows, "simulations": 1000, "seed": 42, "team_paths": {}}


def test_global_report_writes_files_and_metrics():
    outputs, metrics = _write_global_report(_sample_result(), _sample_result(), {"simulations": 1000, "seed": 42})
    assert "output/latest_global_report.txt" in outputs
    assert "output/global_title_ranking.csv" in outputs
    assert "output/global_group_leadership_outlook.csv" in outputs
    assert "output/global_group_qualification_outlook.csv" in outputs
    assert "output/global_model_sensitivity.csv" in outputs
    assert metrics["top_title_balanced"][0]["team"] == "Argentina"
    assert metrics["most_uncertain_groups_balanced"]
    assert metrics["most_uncertain_leadership_groups_balanced"]
    assert metrics["most_uncertain_qualification_groups_balanced"]
    assert metrics["model_sensitivity_abs"]
    assert Path("output/latest_global_report.txt").exists()
    assert Path("output/global_stage_probabilities.csv").exists()
    assert Path("output/global_group_outlook.csv").exists()
    assert Path("output/global_group_leadership_outlook.csv").exists()
    assert Path("output/global_group_qualification_outlook.csv").exists()
    assert Path("output/global_model_sensitivity.csv").exists()
    assert Path("output/global_risk_report.txt").exists()
    text = Path("output/latest_global_report.txt").read_text(encoding="utf-8")
    assert "Panorama geral da Copa 2026" in text
    assert "Top favoritos ao titulo - Cenário Base" in text
    assert "Grupos mais indefinidos para liderança" in text
    assert "Grupos mais indefinidos para classificação" in text
    assert "Seleções mais sensíveis à calibração" in text
    for path in (
        "output/global_group_leadership_outlook.csv",
        "output/global_group_qualification_outlook.csv",
        "output/global_model_sensitivity.csv",
    ):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2


def test_workflow_report_includes_global_section_when_present():
    steps = [{"name": "global-report", "status": "ok", "message": "panorama geral gerado", "outputs": ["output/latest_global_report.txt"], "metrics": {}}]
    metrics = {
        "team": "Brazil",
        "simulations": 1000,
        "seed": 42,
        "global_report": {
            "top_title_balanced": [{"team": "Argentina", "group": "J", "pct": 20.0}],
            "top_title_tuned": [{"team": "Argentina", "group": "J", "pct": 19.5}],
            "most_uncertain_groups_balanced": [{"group": "C", "favorite_to_win_group": "Brazil", "favorite_group_winner_pct": 70.0, "qualification_gap_2v3_pct": 20.0, "uncertainty_score": 80.0}],
            "most_uncertain_leadership_groups_balanced": [{"group": "C", "favorite_to_win_group": "Brazil", "favorite_group_winner_pct": 70.0, "second_group_winner_candidate": "Morocco", "second_group_winner_pct": 20.0, "leadership_gap_pct": 50.0}],
            "most_uncertain_qualification_groups_balanced": [{"group": "C", "second_round32_candidate": "Morocco", "second_round32_pct": 90.0, "third_round32_candidate": "Scotland", "third_round32_pct": 70.0, "qualification_gap_2v3_pct": 20.0}],
            "model_sensitivity_top_gains": [{"team": "Brazil", "delta_winner_pct": 0.5}],
            "model_sensitivity_top_drops": [{"team": "Morocco", "delta_winner_pct": -0.5}],
            "model_sensitivity_abs": [{"team": "Brazil", "delta_winner_pct": 0.5}],
            "top_round32_risks_balanced": [{"team": "Morocco", "group_eliminated_pct": 20.0}],
        },
    }
    report = _write_workflow_report("full", steps, metrics, ["output/latest_global_report.txt"])
    text = Path(report["latest_report"]).read_text(encoding="utf-8")
    assert "Secao executiva global" in text
    assert "Top favoritos ao titulo - Cenário Base" in text
    assert "Grupos mais indefinidos para liderança" in text
    assert "Grupos mais indefinidos para classificação" in text
    assert "Seleções mais sensíveis à calibração" in text
