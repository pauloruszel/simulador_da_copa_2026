"""
Testes para write_market_comparison_full — compara TODAS as seleções.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.market_odds import write_market_comparison_full, build_market_odds_payload, MarketOdd


def _make_global_title_csv(tmp_path: Path, teams: list[str]) -> Path:
    """Cria um global_title_ranking.csv mínimo para os testes."""
    path = tmp_path / "global_title_ranking.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["model", "team", "group", "winner_pct", "rank"])
        writer.writeheader()
        for i, team in enumerate(teams):
            writer.writerow({"model": "balanced", "team": team, "group": "A",
                              "winner_pct": str(10.0 - i * 0.5), "rank": str(i + 1)})
    return path


def _make_odds_json(tmp_path: Path, teams_odds: dict[str, float]) -> Path:
    """Cria data/odds.json mínimo."""
    records = [
        MarketOdd(
            market_type="winner",
            team=team,
            odds_decimal=odds,
            bookmaker="test",
            source_url="test",
            collected_at="2026-06-22T00:00:00Z",
        )
        for team, odds in teams_odds.items()
    ]
    payload = build_market_odds_payload(records)
    path = tmp_path / "odds.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_all_teams_with_odds_included(tmp_path):
    teams = ["Argentina", "France", "Spain", "England", "Brazil", "Germany",
             "Netherlands", "Portugal", "Morocco", "Mexico", "Uruguay", "Croatia"]
    odds_teams = {"France": 5, "Spain": 7, "England": 7.5, "Argentina": 9.05,
                  "Brazil": 13, "Germany": 15, "Netherlands": 17, "Morocco": 34,
                  "Mexico": 50, "Uruguay": 70, "Croatia": 80}
    model_csv = _make_global_title_csv(tmp_path, teams)
    odds_json = _make_odds_json(tmp_path, odds_teams)
    out_csv = tmp_path / "market_comparison.csv"
    out_txt = tmp_path / "market_comparison_report.txt"

    rows = write_market_comparison_full(
        model_csv_path=model_csv, odds_path=odds_json,
        output_csv=out_csv, output_txt=out_txt,
    )

    rows_with = [r for r in rows if r.get("market_winner_pct") is not None]
    rows_without = [r for r in rows if r.get("market_winner_pct") is None]

    assert len(rows_with) == len(odds_teams), (
        f"Esperava {len(odds_teams)} seleções com odds, obteve {len(rows_with)}"
    )
    assert len(rows_without) == len(teams) - len(odds_teams)
    # Portugal não tem odds neste teste
    assert any(r["team"] == "Portugal" and r["market_winner_pct"] is None for r in rows_without)


def test_csv_contains_all_teams(tmp_path):
    teams = ["Argentina", "France", "Haiti", "Paraguay"]
    odds_teams = {"France": 5, "Argentina": 9.05}
    model_csv = _make_global_title_csv(tmp_path, teams)
    odds_json = _make_odds_json(tmp_path, odds_teams)
    out_csv = tmp_path / "market_comparison.csv"
    out_txt = tmp_path / "market_comparison_report.txt"

    write_market_comparison_full(
        model_csv_path=model_csv, odds_path=odds_json,
        output_csv=out_csv, output_txt=out_txt,
    )

    with out_csv.open(newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    csv_teams = {r["team"] for r in csv_rows}
    for team in teams:
        assert team in csv_teams, f"{team} ausente no CSV"


def test_report_shows_without_odds_section(tmp_path):
    teams = ["France", "Haiti"]
    odds_teams = {"France": 5}
    model_csv = _make_global_title_csv(tmp_path, teams)
    odds_json = _make_odds_json(tmp_path, odds_teams)
    out_csv = tmp_path / "mc.csv"
    out_txt = tmp_path / "mc.txt"
    write_market_comparison_full(
        model_csv_path=model_csv, odds_path=odds_json,
        output_csv=out_csv, output_txt=out_txt,
    )
    txt = out_txt.read_text(encoding="utf-8")
    assert "Haiti" in txt
    assert "sem odds" in txt.lower() or "Selecoes sem odds" in txt


def test_no_silent_limit(tmp_path):
    """Verifica que 30 seleções com odds produzem 30 linhas comparadas."""
    from string import ascii_uppercase
    # 32 times, 30 com odds
    teams = [f"Team{i}" for i in range(32)]
    odds_teams = {f"Team{i}": 5 + i for i in range(30)}
    model_csv = _make_global_title_csv(tmp_path, teams)
    odds_json = _make_odds_json(tmp_path, odds_teams)
    out_csv = tmp_path / "mc.csv"
    out_txt = tmp_path / "mc.txt"
    rows = write_market_comparison_full(
        model_csv_path=model_csv, odds_path=odds_json,
        output_csv=out_csv, output_txt=out_txt,
    )
    rows_with = [r for r in rows if r.get("market_winner_pct") is not None]
    assert len(rows_with) == 30, f"Esperava 30, obteve {len(rows_with)}"


def test_alerts_threshold_in_comparison(tmp_path):
    """Seleções com |delta| >= 3 pp devem ser identificáveis nas linhas."""
    teams = ["France", "Argentina"]
    # France: modelo 14.41%, mercado ~20% — delta ~5.6 pp
    odds_teams = {"France": 5, "Argentina": 9.05}
    model_csv = _make_global_title_csv(tmp_path, teams)
    odds_json = _make_odds_json(tmp_path, odds_teams)
    out_csv = tmp_path / "mc.csv"
    out_txt = tmp_path / "mc.txt"
    rows = write_market_comparison_full(
        model_csv_path=model_csv, odds_path=odds_json,
        output_csv=out_csv, output_txt=out_txt,
    )
    rows_with = [r for r in rows if r.get("market_winner_pct") is not None]
    for row in rows_with:
        assert row["delta_pp"] is not None
