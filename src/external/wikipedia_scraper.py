from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .base_client import NoopExternalDataClient
from .api_football_client import TEAM_ALIASES

SCORE_RE = re.compile(r"^(\d+)[\u2013-](\d+)$")
MATCH_RE = re.compile(r"^Match\s+(\d+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOISE = {
    "Main article:",
    "Pos",
    "Team",
    "v",
    "t",
    "e",
    "Pld",
    "W",
    "D",
    "L",
    "GF",
    "GA",
    "GD",
    "Pts",
    "Position will qualify for:",
    "Knockout stage",
    "Possible",
    "Updated to match(es) played on June 18, 2026. Source:",
    "Report",
    "[",
    "]",
    "* * *",
}


class WikipediaWorldCupScraper(NoopExternalDataClient):
    source_name = "wikipedia"

    def __init__(
        self,
        url: str = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup",
        raw_dir: str | Path = "data/raw",
    ) -> None:
        self.url = url
        self.raw_dir = Path(raw_dir)

    def fetch_matches(self) -> list[dict[str, Any]]:
        raw = self._fetch_html()
        self._write_raw_snapshot(raw)
        matches: list[dict[str, Any]] = []
        for group in "ABCDEFGHIJKL":
            section = self._group_section(raw, group)
            matches.extend(self._parse_group(section, group))
        return matches

    def _fetch_html(self) -> str:
        req = Request(
            self.url,
            headers={"User-Agent": "simulador-copa-2026/0.1 daily-results-cache"},
        )
        try:
            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        except URLError as exc:
            raise RuntimeError(f"Falha ao buscar Wikipedia: {exc.reason}") from exc

    def _write_raw_snapshot(self, raw: str) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        (self.raw_dir / f"wikipedia_worldcup_{stamp}.html").write_text(raw, encoding="utf-8")
        self._cleanup_raw_snapshots()

    def _cleanup_raw_snapshots(self, keep: int = 5) -> None:
        files = sorted(
            self.raw_dir.glob("wikipedia_worldcup_*.html"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[keep:]:
            try:
                path.chmod(0o666)
                path.unlink()
            except OSError:
                pass

    def _group_section(self, raw: str, group: str) -> str:
        start = raw.find(f'id="Group_{group}"')
        if start < 0:
            return ""
        next_group = chr(ord(group) + 1) if group != "L" else None
        end_candidates = []
        if next_group:
            end_candidates.append(raw.find(f'id="Group_{next_group}"', start + 1))
        end_candidates.append(raw.find('id="Ranking_of_third-placed_teams"', start + 1))
        end_candidates = [x for x in end_candidates if x > start]
        end = min(end_candidates) if end_candidates else start + 50000
        return raw[start:end]

    def _parse_group(self, section: str, group: str) -> list[dict[str, Any]]:
        lines = _html_to_lines(section)
        matches = []
        for i, line in enumerate(lines):
            score_match = SCORE_RE.match(line)
            scheduled_match = MATCH_RE.match(line)
            if not score_match and not scheduled_match:
                continue
            home = _nearest_team(lines, i, -1)
            away = _nearest_team(lines, i, 1)
            date = _nearest_date(lines, i)
            if not home or not away or not date:
                continue
            if score_match:
                home_score = int(score_match.group(1))
                away_score = int(score_match.group(2))
                status = "finished"
                provider_id = f"wikipedia-{group}-{date}-{home}-{away}"
            else:
                home_score = None
                away_score = None
                status = "scheduled"
                provider_id = f"wikipedia-match-{scheduled_match.group(1)}"
            matches.append({
                "provider_id": provider_id,
                "group": group,
                "home": _team_name(home),
                "away": _team_name(away),
                "home_score": home_score,
                "away_score": away_score,
                "status": status,
                "date": f"{date}T00:00:00Z",
                "source": self.source_name,
                "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            })
        return _dedupe(matches)


def _html_to_lines(section: str) -> list[str]:
    section = re.sub(r"<style.*?</style>|<script.*?</script>", "", section, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", section))
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", line)
        if date_match and line != date_match.group(0):
            lines.append(date_match.group(0))
        lines.append(line)
    return lines


def _nearest_team(lines: list[str], index: int, step: int) -> str | None:
    j = index + step
    while 0 <= j < len(lines) and abs(j - index) < 12:
        candidate = lines[j]
        if _looks_like_team(candidate):
            return candidate
        j += step
    return None


def _nearest_date(lines: list[str], index: int) -> str | None:
    for j in range(index, max(-1, index - 12), -1):
        if DATE_RE.match(lines[j]):
            return lines[j]
    return None


def _looks_like_team(value: str) -> bool:
    if value in NOISE or DATE_RE.match(value) or SCORE_RE.match(value) or MATCH_RE.match(value):
        return False
    if value.startswith("UTC") or "p.m." in value or "a.m." in value:
        return False
    if value.isdigit() or value.startswith("+") or value.startswith("\u2212"):
        return False
    if len(value) > 40:
        return False
    return bool(re.search(r"[A-Za-z]", value))


def _team_name(name: str) -> str:
    return TEAM_ALIASES.get(name, name)


def _dedupe(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for match in matches:
        key = (match["group"], match["home"], match["away"], match["date"])
        if key not in seen:
            seen.add(key)
            out.append(match)
    return out
