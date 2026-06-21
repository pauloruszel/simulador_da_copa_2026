import json
from datetime import UTC, datetime
from pathlib import Path

from src.external.fifa_official_client import FifaOfficialClient, RawFetchResult
from src.external.openfootball_client import OpenFootballClient
from src.storage.json_store import JsonStore
from src.update.match_data_resolver import resolve_match_updates
from src.update.multi_source_results_updater import MultiSourceResultsUpdater


def _config(enabled=("fifa_official", "openfootball_json", "wikipedia")):
    sources = [
        {"name": "fifa_official", "enabled": "fifa_official" in enabled, "priority": 1, "confidence": 1.0},
        {"name": "openfootball_json", "enabled": "openfootball_json" in enabled, "priority": 2, "confidence": 0.82},
        {"name": "wikipedia", "enabled": "wikipedia" in enabled, "priority": 3, "confidence": 0.75},
        {"name": "news_crosscheck", "enabled": "news_crosscheck" in enabled, "priority": 4, "confidence": 0.86},
    ]
    return {
        "sources": sources,
        "field_priority": {
            "date": ["fifa_official", "openfootball_json", "wikipedia"],
            "venue": ["fifa_official", "openfootball_json", "wikipedia"],
            "status": ["fifa_official", "news_crosscheck", "wikipedia"],
            "score": ["fifa_official", "news_crosscheck", "wikipedia", "openfootball_json"],
        },
    }


def _local():
    return [{
        "id": "C01",
        "group": "C",
        "home": "Brazil",
        "away": "Morocco",
        "home_score": None,
        "away_score": None,
        "status": "scheduled",
        "date": "2026-06-13T22:00:00Z",
    }]


def _match(source, home_score=1, away_score=0, date="2026-06-13T00:00:00Z"):
    return {
        "id": "C01",
        "group": "C",
        "home": "Brazil",
        "away": "Morocco",
        "home_score": home_score,
        "away_score": away_score,
        "status": "finished",
        "date": date,
        "source": source,
    }


def test_fifa_official_client_unparseable_html_returns_empty_without_breaking():
    client = FifaOfficialClient()
    raw = RawFetchResult("fifa_official", "http://example.test", "text/html", "<html></html>", "now", [])
    assert client.parse_matches(raw) == []
    assert client.warnings


def test_fifa_official_client_normalizes_fdcp_api_payload():
    payload = {
        "Results": [{
            "IdCompetition": "17",
            "IdSeason": "285023",
            "IdMatch": "400021443",
            "MatchNumber": 1,
            "GroupName": [{"Locale": "en-GB", "Description": "Group A"}],
            "StageName": [{"Locale": "en-GB", "Description": "First Stage"}],
            "Date": "2026-06-11T19:00:00Z",
            "Home": {"Score": 2, "TeamName": [{"Locale": "en-GB", "Description": "Mexico"}]},
            "Away": {"Score": 0, "TeamName": [{"Locale": "en-GB", "Description": "South Africa"}]},
            "HomeTeamScore": 2,
            "AwayTeamScore": 0,
            "MatchStatus": 0,
            "Stadium": {
                "Name": [{"Locale": "en-GB", "Description": "Mexico City Stadium"}],
                "CityName": [{"Locale": "en-GB", "Description": "Mexico City"}],
            },
        }]
    }
    raw = RawFetchResult("fifa_official", "http://example.test", "application/json", json.dumps(payload), "now", [])
    rows = FifaOfficialClient().parse_matches(raw)
    assert rows == [{
        "provider_id": "400021443",
        "id": "1",
        "group": "A",
        "home": "Mexico",
        "away": "South Africa",
        "home_score": 2,
        "away_score": 0,
        "status": "finished",
        "status_raw": "0",
        "date": "2026-06-11T19:00:00Z",
        "date_precision": "exact",
        "venue": "Mexico City Stadium, Mexico City",
        "source": "fifa_official",
        "last_updated": "now",
    }]


def test_fifa_official_client_normalizes_fdcp_third_place_placeholders():
    payload = {
        "Results": [{
            "IdMatch": "400021548",
            "MatchNumber": 103,
            "StageName": [{"Locale": "en-GB", "Description": "Play-off for third place"}],
            "Date": "2026-07-18T20:00:00Z",
            "PlaceHolderA": "RU101",
            "PlaceHolderB": "RU102",
        }]
    }
    raw = RawFetchResult("fifa_official", "http://example.test", "application/json", json.dumps(payload), "now", [])
    rows = FifaOfficialClient().parse_matches(raw)
    result = resolve_match_updates(_local(), {"fifa_official": rows}, {"fifa_official": {"confidence": 1.0}}, {})
    assert result["conflicts"] == []
    assert result["ignored_placeholders"][0]["home"] == "RU101"


def test_openfootball_client_normalizes_json():
    payload = {"matches": [{
        "num": 1,
        "group": "Group C",
        "team1": "Brazil",
        "team2": "Morocco",
        "score": {"ft": [2, 1]},
        "ground": "Miami Stadium",
        "date": "2026-06-13",
        "time": "22:00",
    }]}
    rows = OpenFootballClient().parse_matches(payload, "now")
    assert rows[0]["home"] == "Brazil"
    assert rows[0]["away"] == "Morocco"
    assert rows[0]["home_score"] == 2
    assert rows[0]["group"] == "C"
    assert rows[0]["venue"] == "Miami Stadium"


def test_match_data_resolver_prefers_fifa_over_wikipedia():
    result = resolve_match_updates(
        _local(),
        {"fifa_official": [_match("fifa_official", 2, 0)], "wikipedia": [_match("wikipedia", 2, 0)]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
    )
    match = result["matches"][0]
    assert match["home_score"] == 2
    assert match["resolved_confidence"] == "high"


def test_match_data_resolver_conflict_does_not_overwrite_score():
    local = _local()
    local[0]["home_score"] = 0
    local[0]["away_score"] = 0
    result = resolve_match_updates(
        local,
        {"fifa_official": [_match("fifa_official", 2, 0)], "wikipedia": [_match("wikipedia", 1, 0)]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
    )
    assert result["matches"][0]["home_score"] == 0
    assert result["matches"][0]["resolved_confidence"] == "conflict"
    assert result["conflicts"]


def test_repeated_update_counts_metadata_not_real_change():
    local = _local()
    local[0].update({
        "home_score": 1,
        "away_score": 0,
        "status": "finished",
        "venue": "Miami Stadium",
        "sources": [{"name": "fifa_official", "fields": ["score", "status", "venue"]}],
        "resolved_confidence": "high",
        "last_verified_at": "old",
    })
    result = resolve_match_updates(
        local,
        {"fifa_official": [_match("fifa_official", 1, 0, date="2026-06-13T22:00:00Z") | {"venue": "Miami Stadium"}]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
        now=datetime(2026, 6, 20, tzinfo=UTC),
    )
    assert result["changed"] == []
    assert result["metadata_only"] == ["C01: Brazil x Morocco"]


def test_future_external_score_does_not_mark_finished_by_default():
    result = resolve_match_updates(
        _local(),
        {"fifa_official": [_match("fifa_official", 5, 0, date="2026-06-24T22:00:00Z")]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
        now=datetime(2026, 6, 20, tzinfo=UTC),
    )
    match = result["matches"][0]
    assert match["status"] == "scheduled"
    assert match.get("home_score") is None
    assert result["warnings"][0]["reason"] == "future_result_ignored"


def test_live_score_is_not_applied_as_final_score():
    live = _match("fifa_official", 0, 1) | {"status": "live", "status_raw": "live"}
    result = resolve_match_updates(
        _local(),
        {"fifa_official": [live]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
        now=datetime(2026, 6, 13, 23, tzinfo=UTC),
    )
    match = result["matches"][0]
    assert match["status"] == "live"
    assert match.get("home_score") is None
    assert match.get("away_score") is None
    assert match["live_home_score"] == 0
    assert match["live_away_score"] == 1
    assert result["warnings"][0]["reason"] == "live_score_seen_but_not_applied_as_final"


def test_halftime_score_is_not_marked_finished():
    live = _match("fifa_official", 0, 1) | {"status": "halftime", "status_raw": "HT"}
    result = resolve_match_updates(
        _local(),
        {"fifa_official": [live]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
    )
    match = result["matches"][0]
    assert match["status"] == "halftime"
    assert match.get("home_score") is None
    assert match.get("away_score") is None
    assert match["live_home_score"] == 0
    assert match["live_away_score"] == 1


def test_fifa_timezone_converts_kansas_city_local_to_utc():
    payload = {"Results": [{
        "IdMatch": "400021465",
        "MatchNumber": 34,
        "GroupName": [{"Locale": "en-GB", "Description": "Group E"}],
        "Date": None,
        "LocalDate": "2026-06-20T19:00:00Z",
        "MatchStatus": 1,
        "Home": {"TeamName": [{"Locale": "en-GB", "Description": "Ecuador"}]},
        "Away": {"TeamName": [{"Locale": "en-GB", "Description": "Curacao"}]},
        "Stadium": {
            "Name": [{"Locale": "en-GB", "Description": "Kansas City Stadium"}],
            "CityName": [{"Locale": "en-GB", "Description": "Kansas City"}],
        },
    }]}
    raw = RawFetchResult("fifa_official", "http://example.test", "application/json", json.dumps(payload), "now", [])
    rows = FifaOfficialClient().parse_matches(raw)
    assert rows[0]["date"] == "2026-06-21T00:00:00Z"
    assert rows[0]["status"] == "scheduled"


def test_fifa_timezone_converts_toronto_local_to_utc():
    payload = {"Results": [{
        "IdMatch": "400021469",
        "MatchNumber": 33,
        "GroupName": [{"Locale": "en-GB", "Description": "Group E"}],
        "Date": None,
        "LocalDate": "2026-06-20T16:00:00Z",
        "MatchStatus": 1,
        "Home": {"TeamName": [{"Locale": "en-GB", "Description": "Germany"}]},
        "Away": {"TeamName": [{"Locale": "en-GB", "Description": "Ivory Coast"}]},
        "Stadium": {
            "Name": [{"Locale": "en-GB", "Description": "Toronto Stadium"}],
            "CityName": [{"Locale": "en-GB", "Description": "Toronto"}],
        },
    }]}
    raw = RawFetchResult("fifa_official", "http://example.test", "application/json", json.dumps(payload), "now", [])
    rows = FifaOfficialClient().parse_matches(raw)
    assert rows[0]["date"] == "2026-06-20T20:00:00Z"
    assert rows[0]["status"] == "scheduled"


def test_allow_future_results_applies_future_score():
    result = resolve_match_updates(
        _local(),
        {"fifa_official": [_match("fifa_official", 5, 0, date="2026-06-24T22:00:00Z")]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
        allow_future_results=True,
        now=datetime(2026, 6, 20, tzinfo=UTC),
    )
    match = result["matches"][0]
    assert match["status"] == "finished"
    assert match["home_score"] == 5
    assert result["warnings"] == []


def test_match_data_resolver_ignores_knockout_placeholders_without_conflict():
    result = resolve_match_updates(
        _local(),
        {"openfootball_json": [{
            "id": "73",
            "home": "2A",
            "away": "2B",
            "status": "scheduled",
            "source": "openfootball_json",
        }]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
    )
    assert result["conflicts"] == []
    assert len(result["ignored_placeholders"]) == 1
    assert result["skipped"] == 1


def test_two_medium_sources_agree_generate_medium_high():
    result = resolve_match_updates(
        _local(),
        {"openfootball_json": [_match("openfootball_json", 1, 1)], "wikipedia": [_match("wikipedia", 1, 1)]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
    )
    assert result["matches"][0]["resolved_confidence"] == "medium_high"


def test_only_wikipedia_generates_medium_and_preserves_precise_datetime():
    result = resolve_match_updates(
        _local(),
        {"wikipedia": [_match("wikipedia", 1, 1)]},
        {source["name"]: source for source in _config()["sources"]},
        _config()["field_priority"],
    )
    assert result["matches"][0]["resolved_confidence"] == "medium"
    assert result["matches"][0]["date"] == "2026-06-13T22:00:00Z"


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail

    def fetch_matches(self):
        if self.fail:
            raise RuntimeError("boom")
        return self.rows


def test_multisource_updater_uses_wikipedia_fallback_when_fifa_fails(monkeypatch):
    store = JsonStore()
    store.write("data/source_priority.json", _config(enabled=("fifa_official", "wikipedia")))
    updater = MultiSourceResultsUpdater(store)

    def fake_client(name):
        if name == "fifa_official":
            return FakeClient(fail=True)
        return FakeClient([_match("wikipedia", 1, 0)])

    monkeypatch.setattr(updater, "_client", fake_client)
    report = updater.update(dry_run=True)
    assert report["sources"][0]["status"] == "error"
    assert report["updated"] == 1
    assert report["changed_matches"]


def test_multisource_dry_run_does_not_change_matches_and_writes_reports(monkeypatch):
    store = JsonStore()
    store.write("data/source_priority.json", _config(enabled=("wikipedia",)))
    before = store.read("data/matches.json")
    updater = MultiSourceResultsUpdater(store)
    external = dict(before[0]) | {"home_score": 3, "away_score": 0, "status": "finished", "source": "wikipedia"}
    monkeypatch.setattr(updater, "_client", lambda name: FakeClient([external]))
    report = updater.update(dry_run=True)
    assert store.read("data/matches.json") == before
    assert report["updated"] == 1
    assert Path("output/multisource_update_report.txt").exists()
    assert "placeholder de mata-mata" in Path("output/multisource_update_report.txt").read_text(encoding="utf-8")
    assert Path("output/group_integrity_report.txt").exists()
    assert Path("output/multisource_update_report.json").exists()
    assert Path("output/source_conflicts.csv").exists()


def test_multisource_real_update_creates_snapshot_and_conflict_report(monkeypatch):
    store = JsonStore()
    store.write("data/source_priority.json", _config(enabled=("wikipedia",)))
    before = store.read("data/matches.json")
    updater = MultiSourceResultsUpdater(store)
    external = dict(before[0]) | {"home_score": 3, "away_score": 0, "status": "finished", "source": "wikipedia"}
    monkeypatch.setattr(updater, "_client", lambda name: FakeClient([external]))
    report = updater.update(dry_run=False)
    assert report["snapshot"]
    assert list(Path("data/snapshots").glob("matches_*.json"))
    assert Path("output/source_conflicts.csv").exists()
    assert store.read("data/matches.json")[0]["home_score"] == 3


def test_source_health_check_writes_report(monkeypatch):
    store = JsonStore()
    store.write("data/source_priority.json", _config(enabled=("wikipedia",)))
    updater = MultiSourceResultsUpdater(store)
    monkeypatch.setattr(updater, "_client", lambda name: FakeClient([_match("wikipedia", 1, 0)]))
    result = updater.health_check()
    assert result["sources"][0]["status"] == "ok"
    assert Path("output/source_health_report.txt").exists()


def test_audit_group_writes_report():
    updater = MultiSourceResultsUpdater(JsonStore())
    result = updater.audit_group("C")
    assert result["group"] == "C"
    assert result["matches"]
    text = Path("output/audit_group_C.txt").read_text(encoding="utf-8")
    assert "Audit Group C" in text
    assert "status" not in text.lower() or "Brazil" in text


def test_non_final_score_detected_is_not_real_change(monkeypatch):
    store = JsonStore()
    store.write("data/source_priority.json", _config(enabled=("fifa_official",)))
    before = store.read("data/matches.json")
    updater = MultiSourceResultsUpdater(store)
    external = dict(before[0]) | {
        "home_score": 0,
        "away_score": 1,
        "status": "unknown",
        "status_raw": "3",
        "source": "fifa_official",
    }
    monkeypatch.setattr(updater, "_client", lambda name: FakeClient([external]))

    report = updater.update(dry_run=True)

    assert report["changed_real"] == 0
    assert report["updated"] == 0
    assert report["non_final_score_detected"] == 1
    assert report["changed_matches"] == []
    assert report["non_final_score_matches"] == [f"{before[0]['id']}: {before[0]['home']} x {before[0]['away']}"]
    text = Path("output/multisource_update_report.txt").read_text(encoding="utf-8")
    assert "partidas_alteradas_de_fato: 0" in text
    assert "partidas_com_live_score_detectado: 1" in text
    assert "Jogos com placar nao-final detectado e nao aplicado:" in text


def test_match_from_dict_accepts_live_score_metadata_without_breaking_domain_model():
    from src.models import Match

    match = Match.from_dict(
        {
            "id": "E01",
            "group": "E",
            "home": "Germany",
            "away": "Ivory Coast",
            "status": "scheduled",
            "date": "2026-06-20T20:00:00Z",
            "live_home_score": 0,
            "live_away_score": 1,
            "live_status": "unknown",
            "future_metadata_field": "ignored",
        }
    )

    assert match.live_home_score == 0
    assert match.live_away_score == 1
    assert match.live_status == "unknown"
    assert match.home_score is None
    assert match.away_score is None
    assert not hasattr(match, "future_metadata_field")
