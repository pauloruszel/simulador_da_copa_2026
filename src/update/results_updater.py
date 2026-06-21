from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .validation import validate_normalized_match

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

TEAM_ALIASES.update({
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Cote d'Ivoire": "Ivory Coast",
    "Curacao": "Curacao",
    "Turkiye": "Turkey",
    "USA": "United States",
    "United States of America": "United States",
})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def match_external_to_local(local_matches: list[dict[str, Any]], external: dict[str, Any]) -> int | None:
    provider_id = external.get("provider_id")
    if provider_id:
        hits = [i for i, m in enumerate(local_matches) if m.get("provider_id") == provider_id]
        if len(hits) == 1:
            return hits[0]
    ext_id = external.get("id")
    if ext_id:
        hits = [i for i, m in enumerate(local_matches) if m.get("id") == ext_id]
        if len(hits) == 1:
            return hits[0]
    home = _team_name(external.get("home"))
    away = _team_name(external.get("away"))
    group = external.get("group")
    same_group = [
        i for i, m in enumerate(local_matches)
        if _team_name(m.get("home")) == home
        and _team_name(m.get("away")) == away
        and group
        and m.get("group") == group
    ]
    if len(same_group) == 1:
        return same_group[0]
    same_teams = [
        i for i, m in enumerate(local_matches)
        if {_team_name(m.get("home")), _team_name(m.get("away"))} == {home, away}
        and ((group and m.get("group") == group) or not group)
    ]
    if len(same_teams) == 1:
        return same_teams[0]
    return None


def apply_results_update(
    local_matches: list[dict[str, Any]],
    external_matches: list[dict[str, Any]],
    preserve_manual: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    updated = [dict(m) for m in local_matches]
    log = []
    for external in external_matches:
        validate_normalized_match(external)
        idx = match_external_to_local(updated, external)
        if idx is None:
            log.append(f"Partida ambigua ou ausente: {external.get('home')} x {external.get('away')}. Atualizacao ignorada.")
            continue
        current = updated[idx]
        if preserve_manual and current.get("source") == "manual" and external.get("status") != "finished":
            log.append(f"Preservado dado manual em {current.get('id')}.")
            continue
        same_orientation = _team_name(current.get("home")) == _team_name(external.get("home"))
        merged = current | {k: external[k] for k in ("provider_id", "status", "source") if k in external}
        if "date" in external:
            merged["date"] = _merged_date(current.get("date"), external.get("date"))
        if "home_score" in external and "away_score" in external:
            if same_orientation:
                merged["home_score"] = external["home_score"]
                merged["away_score"] = external["away_score"]
            else:
                merged["home_score"] = external["away_score"]
                merged["away_score"] = external["home_score"]
        if _equivalent_match_state(current, merged):
            log.append(f"Sem mudanca em {current.get('id')}: {current.get('home')} x {current.get('away')}.")
            continue
        merged["last_updated"] = external.get("last_updated") or _now()
        updated[idx] = merged
        log.append(f"Atualizado jogo {merged.get('id')}: {merged.get('home')} x {merged.get('away')}.")
    return updated, log


def _team_name(name: str | None) -> str | None:
    if name is None:
        return None
    return TEAM_ALIASES.get(name, name)


def _equivalent_match_state(current: dict[str, Any], merged: dict[str, Any]) -> bool:
    fields = ("provider_id", "home_score", "away_score", "status", "date", "source")
    return all(current.get(field) == merged.get(field) for field in fields)


def _merged_date(current_date: str | None, external_date: str | None) -> str | None:
    if current_date and external_date and external_date.endswith("T00:00:00Z") and not current_date.endswith("T00:00:00Z"):
        return current_date
    return external_date


def summarize_result_update_log(lines: list[str]) -> dict[str, int]:
    return {
        "updated": sum(line.startswith("Atualizado jogo") for line in lines),
        "unchanged": sum(line.startswith("Sem mudanca") for line in lines),
        "skipped": sum(
            line.startswith("Partida ambigua")
            or line.startswith("Preservado dado manual")
            for line in lines
        ),
    }
