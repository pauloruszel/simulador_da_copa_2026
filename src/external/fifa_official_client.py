from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .base_client import NoopExternalDataClient


@dataclass
class RawFetchResult:
    source: str
    url: str
    content_type: str
    body: str
    fetched_at: str
    warnings: list[str]


class FifaOfficialClient(NoopExternalDataClient):
    source_name = "fifa_official"

    def __init__(
        self,
        url: str = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures",
        api_url: str = (
            "https://api.fifa.com/api/v3/calendar/matches"
            "?from=2026-06-01T00:00:00Z"
            "&to=2026-07-31T23:59:59Z"
            "&language=en"
            "&count=500"
            "&idCompetition=17"
        ),
        raw_dir: str | Path = "data/raw/fifa",
    ) -> None:
        self.url = url
        self.api_url = api_url
        self.raw_dir = Path(raw_dir)
        self.warnings: list[str] = []

    def fetch_matches(self) -> list[dict[str, Any]]:
        raw = self.fetch_raw()
        return self.parse_matches(raw)

    def fetch_raw(self) -> RawFetchResult:
        try:
            return self._fetch_url(self.api_url, expected_content_type="application/json")
        except RuntimeError as exc:
            self.warnings.append(f"API oficial FIFA falhou; tentando HTML: {exc}")
            return self._fetch_url(self.url, expected_content_type="text/html")

    def _fetch_url(self, url: str, expected_content_type: str) -> RawFetchResult:
        fetched_at = _now()
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 simulador-copa-2026/0.1 official-check",
                "Accept": "application/json,text/plain,*/*",
                "Origin": "https://www.fifa.com",
                "Referer": "https://www.fifa.com/",
            },
        )
        try:
            with urlopen(req, timeout=30) as response:
                content_type = response.headers.get("content-type", expected_content_type)
                body = response.read().decode("utf-8", errors="ignore")
        except URLError as exc:
            raise RuntimeError(f"Falha ao buscar FIFA oficial: {exc.reason}") from exc
        raw = RawFetchResult(self.source_name, url, content_type, body, fetched_at, list(self.warnings))
        self._write_raw(raw)
        return raw

    def parse_matches(self, raw: RawFetchResult) -> list[dict[str, Any]]:
        payloads = _json_payloads(raw.body)
        for payload in payloads:
            matches = _extract_matches(payload, raw.fetched_at)
            if matches:
                return matches
        raw.warnings.append("FIFA oficial nao expôs JSON/HTML de partidas em formato conhecido.")
        self.warnings.extend(raw.warnings)
        return []

    def _write_raw(self, raw: RawFetchResult) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suffix = "json" if "json" in raw.content_type else "html"
        (self.raw_dir / f"fifa_official_{stamp}.{suffix}").write_text(raw.body, encoding="utf-8")
        _cleanup(self.raw_dir, "fifa_official_*", 5)


def _json_payloads(body: str) -> list[Any]:
    body = body.lstrip("\ufeff")
    payloads = []
    for pattern in (r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r"self\.__next_f\.push\((.*?)\)"):
        for match in re.finditer(pattern, body, flags=re.S):
            text = match.group(1)
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                continue
    try:
        payloads.append(json.loads(body))
    except json.JSONDecodeError:
        pass
    return payloads


def _extract_matches(payload: Any, fetched_at: str) -> list[dict[str, Any]]:
    matches = []
    for node in _walk(payload):
        if not isinstance(node, dict):
            continue
        if _is_fdcp_match(node):
            matches.append(_fdcp_match(node, fetched_at))
            continue
        home = _nested_name(node, ("home", "homeTeam", "team1"))
        away = _nested_name(node, ("away", "awayTeam", "team2"))
        if not home or not away:
            continue
        score = node.get("score") or node.get("result") or {}
        home_score = _score_value(score, ("home", "homeScore", "team1", "homeGoals"))
        away_score = _score_value(score, ("away", "awayScore", "team2", "awayGoals"))
        status_raw = _raw_status(node)
        status = _status(node)
        venue = _venue(node)
        match_date = _match_datetime(
            node.get("date") or node.get("utcDate") or node.get("kickoff"),
            node.get("localDate") or node.get("LocalDate"),
            venue,
        )
        matches.append({
            "provider_id": str(node.get("id") or node.get("matchId") or node.get("matchNumber") or ""),
            "id": str(node.get("matchNumber")) if node.get("matchNumber") else None,
            "group": _group(node),
            "home": home,
            "away": away,
            "home_score": home_score,
            "away_score": away_score,
            "status": status,
            "status_raw": status_raw,
            "date": match_date,
            "date_precision": "exact" if match_date else None,
            "venue": venue,
            "source": "fifa_official",
            "last_updated": fetched_at,
        })
    return [_clean(match) for match in matches]


def _is_fdcp_match(node: dict[str, Any]) -> bool:
    return "IdMatch" in node and ("Home" in node or "PlaceHolderA" in node) and ("Away" in node or "PlaceHolderB" in node)


def _fdcp_match(node: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    home_score = _int_or_none(node.get("HomeTeamScore"))
    away_score = _int_or_none(node.get("AwayTeamScore"))
    home = _fdcp_team_name(node.get("Home")) or _placeholder(node.get("PlaceHolderA"))
    away = _fdcp_team_name(node.get("Away")) or _placeholder(node.get("PlaceHolderB"))
    status_raw = _raw_status(node)
    status = _fdcp_status(node)
    venue = _localized_description((node.get("Stadium") or {}).get("Name")) if isinstance(node.get("Stadium"), dict) else None
    city = _localized_description((node.get("Stadium") or {}).get("CityName")) if isinstance(node.get("Stadium"), dict) else None
    venue_text = venue
    if venue and city:
        venue_text = f"{venue}, {city}"
    match_date = _match_datetime(node.get("Date"), node.get("LocalDate"), venue_text or city)
    return _clean({
        "provider_id": str(node.get("IdMatch") or ""),
        "id": str(node.get("MatchNumber")) if node.get("MatchNumber") else None,
        "group": _group({"group": _localized_description(node.get("GroupName")) or _localized_description(node.get("StageName"))}),
        "home": home,
        "away": away,
        "home_score": home_score,
        "away_score": away_score,
        "status": status,
        "status_raw": status_raw,
        "date": match_date,
        "date_precision": "exact" if match_date else None,
        "venue": venue_text,
        "source": "fifa_official",
        "last_updated": fetched_at,
    })


def _raw_status(node: dict[str, Any]) -> str | None:
    for key in ("MatchStatus", "matchStatus", "status", "Status", "period", "Period", "matchState"):
        if key in node and node.get(key) is not None:
            return str(node.get(key))
    return None


def _normalize_status(raw: str | None) -> str:
    if raw is None or str(raw).strip() == "":
        return "unknown"
    text = str(raw).strip().lower().replace("_", "-").replace(" ", "-")
    # FIFA FDCP currently returns 0 for completed matches and 1 for fixtures.
    if text in {"0", "finished", "finish", "complete", "completed", "ft", "full-time", "fulltime", "final", "finalised", "finalized", "after-extra-time", "aet", "penalties"}:
        return "finished"
    if text in {"1", "scheduled", "fixture", "pre-match", "prematch", "not-started", "notstarted", "upcoming", "future", "tbd"}:
        return "scheduled"
    if text in {"ht", "half-time", "halftime", "half"}:
        return "halftime"
    if text in {"live", "in-progress", "inprogress", "playing", "first-half", "second-half", "1st-half", "2nd-half", "running"}:
        return "live"
    if text in {"postponed", "delayed"}:
        return "postponed"
    if text in {"cancelled", "canceled", "abandoned"}:
        return "cancelled"
    return "unknown"


_STADIUM_TIMEZONES = {
    "toronto stadium": "America/Toronto",
    "toronto": "America/Toronto",
    "kansas city stadium": "America/Chicago",
    "kansas city": "America/Chicago",
    "mexico city stadium": "America/Mexico_City",
    "mexico city": "America/Mexico_City",
    "guadalajara stadium": "America/Mexico_City",
    "guadalajara": "America/Mexico_City",
    "monterrey stadium": "America/Monterrey",
    "monterrey": "America/Monterrey",
    "vancouver stadium": "America/Vancouver",
    "vancouver": "America/Vancouver",
    "seattle stadium": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "san francisco bay area stadium": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "los angeles stadium": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "dallas stadium": "America/Chicago",
    "dallas": "America/Chicago",
    "houston stadium": "America/Chicago",
    "houston": "America/Chicago",
    "atlanta stadium": "America/New_York",
    "atlanta": "America/New_York",
    "miami stadium": "America/New_York",
    "miami": "America/New_York",
    "boston stadium": "America/New_York",
    "boston": "America/New_York",
    "new york new jersey stadium": "America/New_York",
    "new york": "America/New_York",
    "philadelphia stadium": "America/New_York",
    "philadelphia": "America/New_York",
}


def _match_datetime(utc_value: Any, local_value: Any, venue: str | None) -> str | None:
    if utc_value:
        parsed = _parse_iso_datetime(str(utc_value), assume_utc=True)
        if parsed:
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if local_value:
        timezone_name = _timezone_for_venue(venue)
        parsed = _parse_iso_datetime(str(local_value), assume_utc=False)
        if parsed:
            if timezone_name:
                local = parsed.replace(tzinfo=ZoneInfo(timezone_name))
                return local.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return None


def _parse_iso_datetime(value: str, assume_utc: bool) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if not assume_utc:
        # Some FIFA LocalDate values are local wall-clock values serialized with a Z suffix.
        # Strip timezone semantics and convert using stadium/city timezone instead.
        return parsed.replace(tzinfo=None)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _timezone_for_venue(venue: str | None) -> str | None:
    if not venue:
        return None
    text = venue.lower()
    for key, tz in _STADIUM_TIMEZONES.items():
        if key in text:
            return tz
    return None


def _fdcp_team_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _localized_description(value.get("TeamName")) or value.get("ShortClubName") or value.get("Abbreviation")


def _localized_description(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not value:
            return None
        preferred = next((item for item in value if isinstance(item, dict) and str(item.get("Locale", "")).lower().startswith("en")), None)
        item = preferred or value[0]
        if isinstance(item, dict):
            return item.get("Description")
    if isinstance(value, dict):
        return value.get("Description") or value.get("description") or value.get("name")
    return None


def _placeholder(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"3([A-L]{2,})", text)
    if match:
        return "3" + "/".join(match.group(1))
    return text


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _fdcp_status(node: dict[str, Any]) -> str:
    return _normalize_status(_raw_status(node))


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _nested_name(node: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            name = value.get("name") or value.get("shortName") or value.get("teamName")
            if name:
                return str(name)
    return None


def _score_value(score: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(score, dict):
        for key in keys:
            value = score.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, dict) and isinstance(value.get("score"), int):
                return value["score"]
    return None


def _status(node: dict[str, Any]) -> str:
    return _normalize_status(_raw_status(node))


def _group(node: dict[str, Any]) -> str | None:
    raw = node.get("group") or node.get("stage") or node.get("round")
    if isinstance(raw, dict):
        raw = raw.get("name")
    if not raw:
        return None
    match = re.search(r"Group\s+([A-L])", str(raw), flags=re.I)
    return match.group(1).upper() if match else str(raw).strip()[-1:].upper()


def _venue(node: dict[str, Any]) -> str | None:
    value = node.get("venue") or node.get("stadium")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name")
    return None


def _clean(match: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in match.items() if value is not None and value != ""}


def _cleanup(raw_dir: Path, pattern: str, keep: int) -> None:
    files = sorted(raw_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files[keep:]:
        try:
            path.chmod(0o666)
            path.unlink()
        except OSError:
            pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
