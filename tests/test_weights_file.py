import json
from pathlib import Path

import pytest

from main import compare_weight_files
from src.calibration.team_strength import load_weights_file


def test_weights_file_loads_valid_partial_file_with_fallback():
    path = Path("output/test_weights_file_partial.json")
    path.write_text(json.dumps({"weights": {"poisson": {"draw_correction_factor": 1.15}}}), encoding="utf-8")
    weights, warnings = load_weights_file(path)
    assert weights["poisson"]["draw_correction_factor"] == 1.15
    assert "base_goals" in weights["poisson"]
    assert warnings


def test_weights_file_has_priority_over_preset():
    path = Path("output/test_weights_file_priority.json")
    path.write_text(json.dumps({"weights": {"knockout": {"sensitivity": 999}}}), encoding="utf-8")
    weights, warnings = load_weights_file(path, preset="favorite_heavy")
    assert weights["knockout"]["sensitivity"] == 999
    assert any("ignorado" in warning for warning in warnings)


def test_weights_file_missing_has_friendly_error():
    with pytest.raises(ValueError, match="Arquivo de pesos nao encontrado"):
        load_weights_file("output/nao_existe_weights.json")


def test_weights_file_with_tuning_metadata_is_interpreted():
    path = Path("output/test_weights_file_tuning.json")
    payload = {
        "metadata": {"created_by": "test"},
        "best": {"config": {"poisson": {"goal_advantage_scale": 0.003}}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    weights, _ = load_weights_file(path)
    assert weights["poisson"]["goal_advantage_scale"] == 0.003


def test_compare_weight_files_generates_reports():
    a = Path("output/test_weights_a.json")
    b = Path("output/test_weights_b.json")
    probabilities = Path("output/probabilities.csv")
    summary = Path("output/summary.txt")
    probabilities.write_text("sentinel probabilities", encoding="utf-8")
    summary.write_text("sentinel summary", encoding="utf-8")
    a.write_text(json.dumps({"weights": {"poisson": {"draw_correction_factor": 1.0}}}), encoding="utf-8")
    b.write_text(json.dumps({"weights": {"poisson": {"draw_correction_factor": 1.15}}}), encoding="utf-8")
    compare_weight_files([str(a), str(b)], "Brazil", 5, 1)
    assert probabilities.read_text(encoding="utf-8") == "sentinel probabilities"
    assert summary.read_text(encoding="utf-8") == "sentinel summary"
    assert Path("output/weights_comparison_Brazil.csv").exists()
    report = Path("output/weights_comparison_Brazil.txt")
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Analise automatica" in text
    assert "Deltas principais" in text
    assert "Adversarios mais comuns no Round of 32" in text
    assert "Top 10 favoritos ao titulo" in text
    assert "Ratings calibrados" in text
    assert "Pesos principais" in text
    assert "Diagnostico:" in text
