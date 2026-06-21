from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .base_client import NoopExternalDataClient


class OpenFootballClient(NoopExternalDataClient):
    source_name = "openfootball_json"

    def __init__(
        self,
        url: str = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json",
        raw_dir: str | Path = "data/raw/openfootball",
    ) -> None:
        self.url = url
        self.raw_dir = Path(raw_dir)

    def fetch_matches(self) -> list[dict[str, Any]]:
        fetched_at = _now()
        raw = self._fetch_json()
        self._write_raw(raw)
        return self.parse_matches(raw, fetched_at)

    def parse_matches(self, payload: dict[str, Any], fetched_at: str | None = None) -> list[dict[str, Any]]:
        fetched_at = fetched_at or _now()
        matches = []
        for raw in _iter_matches(payload):
            home = raw.get("team1") or raw.get("home")
            away = raw.get("team2") or raw.get("away")
            if not home or not away:
                continue
            home_score, away_score = _score(raw.get("score"))
            matches.append({
                "provider_id": f"openfootball-{raw.get('num') or raw.get('date')}-{home}-{away}",
                "id": str(raw.get("num")) if raw.get("num") else None,
                "group": _group(raw),
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "status": "finished" if home_score is not None and away_score is not None else "scheduled",
                "date": _datetime(raw.get("date"), raw.get("time")),
                "date_precision": "exact" if raw.get("time") else "date",
                "venue": raw.get("ground") or raw.get("venue"),
                "source": self.source_name,
                "last_updated": fetched_at,
            })
        return [{k: v for k, v in match.items() if v is not None and v != ""} for match in matches]

    def _fetch_json(self) -> dict[str, Any]:
        req = Request(self.url, headers={"User-Agent": "simulador-copa-2026/0.1 openfootball"})
        try:
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except (URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Falha ao buscar OpenFootball: {exc}") from exc

    def _write_raw(self, payload: dict[str, Any]) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        (self.raw_dir / f"openfootball_{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _cleanup(self.raw_dir, "openfootball_*.json", 5)


def _iter_matches(payload: dict[str, Any]):
    for key in ("matches", "games"):
        if isinstance(payload.get(key), list):
            yield from payload[key]
    for round_ in payload.get("rounds", []):
        if isinstance(round_, dict):
            yield from round_.get("matches", [])


def _score(score: Any) -> tuple[int | None, int | None]:
    if not isinstance(score, dict):
        return None, None
    ft = score.get("ft") or score.get("fulltime") or score
    if isinstance(ft, list) and len(ft) >= 2:
        return ft[0], ft[1]
    if isinstance(ft, dict):
        return ft.get("team1") or ft.get("home"), ft.get("team2") or ft.get("away")
    return None, None


def _group(raw: dict[str, Any]) -> str | None:
    group = raw.get("group")
    if not group:
        return None
    return str(group).replace("Group ", "").strip()[:1].upper()


def _datetime(date: str | None, time: str | None) -> str | None:
    if not date:
        return None
    if time:
        match = re.search(r"(\d{1,2}):(\d{2})", time)
        if match:
            return f"{date}T{int(match.group(1)):02d}:{match.group(2)}:00Z"
    return f"{date}T00:00:00Z"


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
