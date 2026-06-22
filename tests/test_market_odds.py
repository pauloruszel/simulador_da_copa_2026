from pathlib import Path

from src.calibration.team_strength import market_implied_team_strength
from src.market_odds import (
    build_market_odds_payload,
    fetch_market_odds_periodically,
    merge_market_odds_records,
    parse_winner_market_lines,
    read_market_odds_csv,
    update_market_odds_files,
    write_market_comparison,
    write_market_odds_csv,
)
from src.storage.json_store import JsonStore


def test_parse_oddschecker_winner_lines_extracts_visible_market():
    lines = [
        "2026 World Cup",
        "Mercados de Vitória",
        "Vencedor",
        "França",
        "bookie logo",
        "5",
        "Espanha",
        "7",
        "Inglaterra",
        "7.5",
        "Argentina",
        "9.05",
        "Para chegar na final",
        "França",
        "3",
    ]

    records = parse_winner_market_lines(lines, "https://example.test", "2026-06-22T00:00:00Z")

    assert [record.team for record in records] == ["France", "Spain", "England", "Argentina"]
    assert records[0].odds_decimal == 5
    assert records[-1].odds_decimal == 9.05


def test_market_odds_files_feed_csv_and_normalized_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    records = parse_winner_market_lines(
        ["Vencedor", "França", "5", "Brasil", "13", "Argentina", "9.05", "Comparar todas as odds"],
        "https://example.test",
        "2026-06-22T00:00:00Z",
    )

    payload = update_market_odds_files(records)

    assert Path("data/market_odds_manual.csv").exists()
    assert Path("data/odds.json").exists()
    assert Path("output/market_odds_report.txt").exists()
    assert len(read_market_odds_csv()) == 3
    assert round(sum(item["market_probability"] for item in payload["outrights"]), 8) == 1


def test_market_odds_generates_model_comparison(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("output").mkdir()
    Path("output/global_title_ranking.csv").write_text(
        "rank,model,team,group,winner_pct\n"
        "1,balanced,France,I,13.0\n"
        "2,balanced,Brazil,C,7.0\n",
        encoding="utf-8",
    )
    records = parse_winner_market_lines(["Vencedor", "França", "5", "Brasil", "13"], "https://example.test")
    JsonStore().write("data/odds.json", build_market_odds_payload(records))

    rows = write_market_comparison()

    assert len(rows) == 2
    assert Path("output/market_comparison.csv").exists()
    assert Path("output/market_comparison_report.txt").exists()
    assert {row["team"] for row in rows} == {"France", "Brazil"}


def test_market_odds_can_create_soft_rating_deltas():
    payload = build_market_odds_payload(
        parse_winner_market_lines(["Vencedor", "França", "5", "Brasil", "13"], "https://example.test")
    )

    deltas = market_implied_team_strength(payload, {"France": 2100, "Brazil": 2040})

    assert deltas["France"] > 0
    assert deltas["Brazil"] < 0


def test_market_odds_merge_preserves_manual_cache_when_scrape_is_partial():
    scraped = parse_winner_market_lines(["Vencedor", "França", "5"], "https://example.test/scraped")
    cached = parse_winner_market_lines(["Vencedor", "França", "6", "Brasil", "13", "Argentina", "9.05"], "manual")

    merged = merge_market_odds_records(scraped, cached)

    assert [record.team for record in merged] == ["France", "Brazil", "Argentina"]
    assert next(record for record in merged if record.team == "France").odds_decimal == 5


def test_fetch_market_odds_periodically_merges_scraped_records_with_existing_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cached = parse_winner_market_lines(["Vencedor", "França", "6", "Brasil", "13"], "manual")
    write_market_odds_csv(cached)

    monkeypatch.setattr(
        "src.market_odds.scrape_oddschecker_winner",
        lambda url: parse_winner_market_lines(["Vencedor", "França", "5"], url),
    )

    payload = fetch_market_odds_periodically(url="https://example.test")

    teams = {item["team"] for item in payload["outrights"]}
    assert teams == {"France", "Brazil"}
    assert payload["fetch_status"] == "partial_merged"
    assert payload["scraped_records"] == 1
    assert payload["cached_records"] == 2
    assert len(read_market_odds_csv()) == 2
