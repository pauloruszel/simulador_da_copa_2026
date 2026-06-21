from src.external.api_football_client import ApiFootballClient


def test_api_football_fixture_normalization():
    client = ApiFootballClient()
    item = {
        "fixture": {
            "id": 123,
            "date": "2026-06-24T22:00:00+00:00",
            "status": {"short": "FT"},
        },
        "league": {"round": "Group C - 3"},
        "teams": {
            "home": {"name": "Czech Republic"},
            "away": {"name": "Korea Republic"},
        },
        "goals": {"home": 2, "away": 1},
    }
    normalized = client._normalize_fixture(item)
    assert normalized["provider_id"] == "123"
    assert normalized["group"] == "C"
    assert normalized["home"] == "Czechia"
    assert normalized["away"] == "South Korea"
    assert normalized["status"] == "finished"

