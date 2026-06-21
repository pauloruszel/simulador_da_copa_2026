import json
import sys
from pathlib import Path

import pytest

import main
from src.calibration.odds_converter import normalize_three_way_market
from src.calibration.probability_blender import blend_probabilities
from src.calibration.rating_calibrator import blend_ratings
from src.storage.json_store import JsonStore
from src.update.data_updater import DataUpdater
from src.update.results_updater import apply_results_update, match_external_to_local


def test_match_external_to_local_by_id():
    local = [{"id": "C03", "group": "C", "home": "Scotland", "away": "Brazil"}]
    external = {"id": "C03", "home": "Scotland", "away": "Brazil", "status": "finished", "home_score": 0, "away_score": 2}
    assert match_external_to_local(local, external) == 0


def test_apply_results_update_finished_match():
    local = [{"id": "C03", "group": "C", "home": "Scotland", "away": "Brazil", "status": "scheduled"}]
    external = [{"id": "C03", "home": "Scotland", "away": "Brazil", "status": "finished", "home_score": 0, "away_score": 2, "source": "test"}]
    updated, log = apply_results_update(local, external)
    assert updated[0]["status"] == "finished"
    assert updated[0]["away_score"] == 2
    assert log


def test_apply_results_update_swaps_score_when_fixture_orientation_differs():
    local = [{"id": "C02", "group": "C", "home": "Scotland", "away": "Haiti", "status": "scheduled"}]
    external = [{"home": "Haiti", "away": "Scotland", "group": "C", "status": "finished", "home_score": 0, "away_score": 1, "source": "test"}]
    updated, _ = apply_results_update(local, external)
    assert updated[0]["home_score"] == 1
    assert updated[0]["away_score"] == 0


def test_apply_results_update_reports_unchanged():
    local = [{
        "id": "C01",
        "group": "C",
        "home": "Brazil",
        "away": "Morocco",
        "status": "finished",
        "home_score": 1,
        "away_score": 1,
        "provider_id": "wikipedia-C01",
        "date": "2026-06-13T00:00:00Z",
        "source": "wikipedia",
        "last_updated": "old",
    }]
    external = [{
        "provider_id": "wikipedia-C01",
        "home": "Brazil",
        "away": "Morocco",
        "status": "finished",
        "home_score": 1,
        "away_score": 1,
        "date": "2026-06-13T00:00:00Z",
        "source": "wikipedia",
    }]
    updated, log = apply_results_update(local, external)
    assert updated == local
    assert "Sem mudanca" in log[0]


def test_apply_results_update_preserves_local_real_datetime_from_generic_external_date():
    local = [{
        "id": "C01",
        "group": "C",
        "home": "Brazil",
        "away": "Morocco",
        "status": "scheduled",
        "date": "2026-06-13T22:00:00Z",
    }]
    external = [{
        "id": "C01",
        "group": "C",
        "home": "Brazil",
        "away": "Morocco",
        "status": "finished",
        "home_score": 1,
        "away_score": 1,
        "date": "2026-06-13T00:00:00Z",
        "source": "wikipedia",
    }]
    updated, _ = apply_results_update(local, external)
    assert updated[0]["date"] == "2026-06-13T22:00:00Z"
    assert updated[0]["status"] == "finished"


def test_odds_and_probability_calibration():
    market = normalize_three_way_market(2.0, 3.5, 4.0)
    assert round(sum(market.values()), 8) == 1
    assert round(blend_probabilities(0.4, 0.6, 0.25), 8) == 0.45
    assert blend_ratings({"Brazil": 2000}, {"Brazil": 2100}, 0.5)["Brazil"] == 2050


def test_data_updater_noop_sources_do_not_crash():
    store = JsonStore("output/test_update_v2")
    store.write("data/external_sources.json", {"sources": {"fifa": {"enabled": True, "base_url": "https://www.fifa.com"}}})
    store.write("data/update_log.json", [])
    updater = DataUpdater(store)
    updater.run(results=True, odds=False, rankings=False)
    assert updater.log


class FakeScraper:
    source_name = "wikipedia"

    def fetch_matches(self):
        return [{
            "id": "C01",
            "group": "C",
            "home": "Brazil",
            "away": "Morocco",
            "home_score": 2,
            "away_score": 0,
            "status": "finished",
            "date": "2026-06-13T00:00:00Z",
            "source": "wikipedia",
        }]


def test_scrape_results_dry_run_does_not_change_matches_and_writes_report(monkeypatch):
    store = JsonStore()
    before = store.read("data/matches.json", [])
    updater = DataUpdater(store)
    monkeypatch.setattr(updater, "_clients_for", lambda category: [FakeScraper()] if category == "scraping" else [])

    updater.scrape_results(dry_run=True)

    after = store.read("data/matches.json", [])
    assert after == before
    report = Path("output/scrape_results_report.txt")
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Fonte: wikipedia" in text
    assert "Modo: dry-run" in text
    assert "Partidas atualizadas:" in text


def test_scrape_results_only_with_offline_is_friendly_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scrape-results-only", "--offline"])
    with pytest.raises(SystemExit):
        main.main()
    captured = capsys.readouterr()
    assert "--scrape-results-only precisa de internet; remova --offline." in captured.err
