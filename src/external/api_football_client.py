from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base_client import NoopExternalDataClient, UnsupportedDataTypeError

TEAM_ALIASES = {
    "Korea Republic": "South Korea",
    "Czech Republic": "Czechia",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Curaçao": "Curacao",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Congo DR": "DR Congo",
    "Cabo Verde": "Cape Verde",
    "IR Iran": "Iran",
}

FINISHED_STATUSES = {"FT", "AET", "PEN"}
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}


class ApiFootballClient(NoopExternalDataClient):
    source_name = "api_football"

    def __init__(
        self,
        base_url: str | None = None,
        api_key_env: str = "API_FOOTBALL_KEY",
        league: int = 1,
        season: int = 2026,
        max_odds_fixtures: int = 10,
    ) -> None:
        self.base_url = (base_url or "https://v3.football.api-sports.io").rstrip("/")
        self.api_key_env = api_key_env
        self.api_key = os.getenv(api_key_env)
        self.league = league
        self.season = season
        self.max_odds_fixtures = max_odds_fixtures

    def fetch_matches(self) -> list[dict[str, Any]]:
        data = self._get("fixtures", {"league": self.league, "season": self.season})
        return [self._normalize_fixture(item) for item in data.get("response", [])]

    def fetch_odds(self) -> list[dict[str, Any]]:
        raise UnsupportedDataTypeError(
            "API-FOOTBALL exige fixture_id para odds; use update_odds com provider_id em matches.json."
        )

    def fetch_odds_for_matches(self, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = [m for m in matches if m.get("provider_id") and m.get("status") != "finished"]
        selected = selected[: self.max_odds_fixtures]
        odds = []
        for match in selected:
            data = self._get("odds", {"fixture": match["provider_id"]})
            odds.extend(self._normalize_odds_response(data, match))
        return odds

    def fetch_groups(self) -> dict[str, list[str]]:
        raise UnsupportedDataTypeError("API-FOOTBALL nao retorna grupos no formato local diretamente.")

    def fetch_rankings(self) -> dict[str, Any]:
        raise UnsupportedDataTypeError("API-FOOTBALL nao fornece ranking FIFA oficial.")

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise UnsupportedDataTypeError(f"Variavel de ambiente {self.api_key_env} nao configurada.")
        url = f"{self.base_url}/{endpoint}?{urlencode(params)}"
        req = Request(url, headers={"x-apisports-key": self.api_key})
        try:
            with urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"API-FOOTBALL HTTP {exc.code}: {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Falha de rede API-FOOTBALL: {exc.reason}") from exc
        if payload.get("errors"):
            raise RuntimeError(f"API-FOOTBALL retornou erro: {payload['errors']}")
        return payload

    def _normalize_fixture(self, item: dict[str, Any]) -> dict[str, Any]:
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        league = item.get("league", {})
        status_short = fixture.get("status", {}).get("short")
        return {
            "provider_id": str(fixture.get("id")),
            "group": _group_from_round(league.get("round")),
            "home": _team_name(teams.get("home", {}).get("name")),
            "away": _team_name(teams.get("away", {}).get("name")),
            "home_score": goals.get("home"),
            "away_score": goals.get("away"),
            "status": _status(status_short),
            "date": fixture.get("date"),
            "source": self.source_name,
            "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def _normalize_odds_response(self, data: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for item in data.get("response", []):
            bookmakers = item.get("bookmakers", [])
            out.append({
                "provider_id": match.get("provider_id"),
                "home": match.get("home"),
                "away": match.get("away"),
                "date": match.get("date"),
                "source": self.source_name,
                "markets": bookmakers,
            })
        return out


def _team_name(name: str | None) -> str | None:
    if name is None:
        return None
    return TEAM_ALIASES.get(name, name)


def _status(status_short: str | None) -> str:
    if status_short in FINISHED_STATUSES:
        return "finished"
    if status_short in LIVE_STATUSES:
        return "live"
    return "scheduled"


def _group_from_round(round_name: str | None) -> str | None:
    if not round_name:
        return None
    for token in round_name.replace("-", " ").split():
        if len(token) == 1 and "A" <= token <= "L":
            return token
    return None

