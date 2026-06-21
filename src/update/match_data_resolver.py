from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import re
from typing import Any

from src.update.results_updater import TEAM_ALIASES


def resolve_match_updates(
    local_matches: list[dict[str, Any]],
    source_matches: dict[str, list[dict[str, Any]]],
    source_configs: dict[str, dict[str, Any]],
    field_priority: dict[str, list[str]],
    allow_future_results: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    updated = [dict(match) for match in local_matches]
    conflicts: list[dict[str, Any]] = []
    changed: list[str] = []
    metadata_only: list[str] = []
    non_final_score_matches: list[str] = []
    unchanged = 0
    skipped = 0
    candidate_rows = 0
    ignored_placeholders: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    fields_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    candidates_by_idx: dict[int, list[dict[str, Any]]] = defaultdict(list)
    now = now or datetime.now(UTC)

    for source_name, matches in source_matches.items():
        for external in matches:
            if _is_knockout_placeholder_match(external):
                skipped += 1
                ignored_placeholders.append({
                    "match_id": external.get("id", ""),
                    "home": external.get("home", ""),
                    "away": external.get("away", ""),
                    "source": source_name,
                    "reason": "knockout_placeholder",
                })
                continue
            external, live_warning = _strip_non_final_score(external, source_name)
            if live_warning:
                warnings.append(live_warning)
            external, future_warning = _strip_future_score(external, source_name, allow_future_results, now)
            if future_warning:
                warnings.append(future_warning)
            idx = match_external_to_local(updated, external)
            if idx is None:
                skipped += 1
                conflicts.append({
                    "match_id": external.get("id", ""),
                    "home": external.get("home", ""),
                    "away": external.get("away", ""),
                    "field": "match",
                    "local": "",
                    "external": "unmatched",
                    "sources": source_name,
                    "reason": "ambiguous_or_missing",
                })
                continue
            candidate = _canonical_candidate(external)
            candidate["source"] = source_name
            candidates_by_idx[idx].append(candidate)
            candidate_rows += 1

    for idx, candidates in candidates_by_idx.items():
        current = updated[idx]
        resolved, match_conflicts, field_changes = _resolve_one(current, candidates, source_configs, field_priority)
        conflicts.extend(match_conflicts)
        if resolved == current:
            unchanged += 1
            continue
        updated[idx] = resolved
        for source, field in field_changes:
            fields_by_source[source][field] += 1
        match_label = f"{resolved.get('id')}: {resolved.get('home')} x {resolved.get('away')}"
        if _material_changed(current, resolved):
            changed.append(match_label)
        elif _non_final_score_detected(field_changes):
            non_final_score_matches.append(match_label)
        else:
            metadata_only.append(match_label)

    return {
        "matches": updated,
        "changed": changed,
        "metadata_only": metadata_only,
        "non_final_score_matches": non_final_score_matches,
        "unchanged": unchanged,
        "skipped": skipped,
        "candidate_rows": candidate_rows,
        "candidate_matches": len(candidates_by_idx),
        "ignored_placeholders": ignored_placeholders,
        "conflicts": conflicts,
        "warnings": warnings,
        "fields_by_source": {source: dict(counts) for source, counts in fields_by_source.items()},
    }


def match_external_to_local(local_matches: list[dict[str, Any]], external: dict[str, Any]) -> int | None:
    provider_id = external.get("provider_id")
    if provider_id:
        hits = [i for i, match in enumerate(local_matches) if match.get("provider_id") == provider_id]
        if len(hits) == 1:
            return hits[0]
    ext_id = external.get("id")
    if ext_id:
        hits = [i for i, match in enumerate(local_matches) if match.get("id") == ext_id]
        if len(hits) == 1:
            return hits[0]
    home = _team_name(external.get("home"))
    away = _team_name(external.get("away"))
    group = external.get("group")
    hits = [
        i for i, match in enumerate(local_matches)
        if _team_name(match.get("home")) == home
        and _team_name(match.get("away")) == away
        and group
        and match.get("group") == group
    ]
    if len(hits) == 1:
        return hits[0]
    hits = [
        i for i, match in enumerate(local_matches)
        if {_team_name(match.get("home")), _team_name(match.get("away"))} == {home, away}
        and ((group and match.get("group") == group) or not group)
    ]
    if len(hits) == 1:
        return hits[0]
    external_date = _date_key(external.get("date"))
    if external_date:
        hits = [
            i for i, match in enumerate(local_matches)
            if {_team_name(match.get("home")), _team_name(match.get("away"))} == {home, away}
            and _date_key(match.get("date")) == external_date
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def _resolve_one(
    current: dict[str, Any],
    candidates: list[dict[str, Any]],
    source_configs: dict[str, dict[str, Any]],
    field_priority: dict[str, list[str]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[str, str]]]:
    merged = dict(current)
    conflicts: list[dict[str, Any]] = []
    field_changes: list[tuple[str, str]] = []
    fetched_at = _now()

    # Match ids/provider ids are stable, but some upstream sources may list the
    # teams in the opposite home/away order from older local data. Scores must
    # always be interpreted in the same orientation as the canonical match row.
    # Prefer the highest-priority source for the team order, then normalize every
    # candidate score to that order before comparing/updating scores.
    team_order_source = _pick_team_order_source(candidates, field_priority)
    if team_order_source:
        order_candidate = next(item for item in candidates if item["source"] == team_order_source)
        if _same_team_set(current, order_candidate):
            canonical_home = _team_name(order_candidate.get("home"))
            canonical_away = _team_name(order_candidate.get("away"))
            if canonical_home and canonical_away and (merged.get("home") != canonical_home or merged.get("away") != canonical_away):
                merged["home"] = canonical_home
                merged["away"] = canonical_away
                field_changes.append((team_order_source, "team_order"))

    score_values = _score_values(candidates, merged.get("home"), merged.get("away"))
    score_conflict = len({value for value in score_values.values() if value is not None}) > 1

    if score_conflict:
        conflicts.append(_conflict_row(merged, "score", (merged.get("home_score"), merged.get("away_score")), score_values, "score_conflict"))
    else:
        score_source = _pick_source(candidates, "score", field_priority)
        if score_source and score_values.get(score_source) is not None:
            home_score, away_score = score_values[score_source]
            if merged.get("home_score") != home_score or merged.get("away_score") != away_score:
                merged["home_score"] = home_score
                merged["away_score"] = away_score
                field_changes.append((score_source, "score_final_updated"))

    live_source = _pick_live_score_source(candidates, field_priority)
    if live_source:
        candidate = next(item for item in candidates if item["source"] == live_source and _has_live_score(item))
        if (
            merged.get("live_home_score") != candidate.get("live_home_score")
            or merged.get("live_away_score") != candidate.get("live_away_score")
            or merged.get("live_status") != candidate.get("live_status")
        ):
            merged["live_home_score"] = candidate.get("live_home_score")
            merged["live_away_score"] = candidate.get("live_away_score")
            merged["live_status"] = candidate.get("live_status") or candidate.get("status")
            field_changes.append((live_source, "live_score_detected"))
            field_changes.append((live_source, "live_score_not_applied"))

    for field in ("status", "date", "venue", "provider_id"):
        source = _pick_source(candidates, field, field_priority)
        if not source:
            continue
        candidate = next(item for item in candidates if item["source"] == source and item.get(field) is not None)
        value = candidate.get(field)
        if field == "status":
            value = _normalize_status(value)
            if value == "unknown":
                continue
            if merged.get("status") == "finished" and value != "finished":
                continue
        if field == "date":
            value = _merge_date(current.get("date"), value, candidate)
        if value != merged.get(field):
            merged[field] = value
            field_changes.append((source, field))

    sources = {item["source"] for item in candidates}
    score_agreements = _score_agreement_count(score_values)
    metadata_before = {key: merged.get(key) for key in ("sources", "resolved_confidence", "last_verified_at")}
    merged["sources"] = _source_metadata(candidates, source_configs, field_changes, fetched_at)
    merged["resolved_confidence"] = _confidence_label(sources, score_agreements, score_conflict)
    merged["last_verified_at"] = fetched_at
    metadata_after = {key: merged.get(key) for key in ("sources", "resolved_confidence", "last_verified_at")}
    if metadata_after != metadata_before:
        for source in sorted(sources):
            field_changes.append((source, "metadata"))
    return merged, conflicts, field_changes


def validate_resolved_matches(matches: list[dict[str, Any]], expected_total: int | None = None) -> None:
    if expected_total is not None and len(matches) != expected_total:
        raise ValueError(f"Total de partidas invalido: {len(matches)}; esperado {expected_total}.")
    ids = set()
    for match in matches:
        if not match.get("id"):
            raise ValueError("Partida sem id interno.")
        if match["id"] in ids:
            raise ValueError(f"Partida duplicada: {match['id']}")
        ids.add(match["id"])
        if match.get("home") == match.get("away"):
            raise ValueError(f"Times duplicados no jogo {match['id']}")
        for field in ("home_score", "away_score"):
            if match.get(field) is not None and match[field] < 0:
                raise ValueError(f"Placar negativo em {match['id']}")
        status = _normalize_status(match.get("status"))
        if status == "finished" and (match.get("home_score") is None or match.get("away_score") is None):
            raise ValueError(f"Partida finalizada sem placar: {match['id']}")
        if status in {"scheduled", "live", "halftime", "postponed", "cancelled"}:
            if match.get("home_score") is not None or match.get("away_score") is not None:
                raise ValueError(f"Partida nao finalizada com placar definitivo: {match['id']}")
        for field in ("live_home_score", "live_away_score"):
            if match.get(field) is not None and match[field] < 0:
                raise ValueError(f"Placar ao vivo negativo em {match['id']}")


def _pick_source(candidates: list[dict[str, Any]], field: str, field_priority: dict[str, list[str]]) -> str | None:
    priorities = field_priority.get(field, [])
    for source in priorities:
        if any(item["source"] == source and _has_field(item, field) for item in candidates):
            return source
    for item in candidates:
        if _has_field(item, field):
            return item["source"]
    return None


def _has_field(candidate: dict[str, Any], field: str) -> bool:
    if field == "score":
        return (
            _normalize_status(candidate.get("status")) == "finished"
            and candidate.get("home_score") is not None
            and candidate.get("away_score") is not None
        )
    if field == "live_score":
        return _has_live_score(candidate)
    return candidate.get(field) is not None


def _has_live_score(candidate: dict[str, Any]) -> bool:
    return candidate.get("live_home_score") is not None and candidate.get("live_away_score") is not None


def _pick_live_score_source(candidates: list[dict[str, Any]], field_priority: dict[str, list[str]]) -> str | None:
    priorities = field_priority.get("score", [])
    for source in priorities:
        if any(item["source"] == source and _has_live_score(item) for item in candidates):
            return source
    for item in candidates:
        if _has_live_score(item):
            return item["source"]
    return None


def _score_values(
    candidates: list[dict[str, Any]],
    target_home: str | None = None,
    target_away: str | None = None,
) -> dict[str, tuple[int, int] | None]:
    values = {}
    for item in candidates:
        source = item["source"]
        if not _has_field(item, "score"):
            values[source] = None
            continue
        item_home = _team_name(item.get("home"))
        item_away = _team_name(item.get("away"))
        raw_score = (item["home_score"], item["away_score"])
        if target_home and target_away:
            if item_home == target_home and item_away == target_away:
                values[source] = raw_score
            elif item_home == target_away and item_away == target_home:
                values[source] = (raw_score[1], raw_score[0])
            else:
                values[source] = None
        else:
            values[source] = raw_score
    return values


def _score_agreement_count(score_values: dict[str, tuple[int, int] | None]) -> int:
    counts = Counter(value for value in score_values.values() if value is not None)
    return max(counts.values(), default=0)


def _source_metadata(
    candidates: list[dict[str, Any]],
    source_configs: dict[str, dict[str, Any]],
    field_changes: list[tuple[str, str]],
    fetched_at: str,
) -> list[dict[str, Any]]:
    fields_by_source: dict[str, set[str]] = defaultdict(set)
    for source, field in field_changes:
        fields_by_source[source].add(field)
    out = []
    for item in candidates:
        source = item["source"]
        fields = []
        for field in ("status", "score", "live_score", "date", "venue"):
            if _has_field(item, field):
                fields.append(field)
        out.append({
            "name": source,
            "confidence": float(source_configs.get(source, {}).get("confidence", 0.5)),
            "fields": fields,
            "fetched_at": item.get("last_updated") or fetched_at,
        })
    return out


def _confidence_label(sources: set[str], score_agreements: int, conflict: bool) -> str:
    if conflict:
        return "conflict"
    if "fifa_official" in sources:
        return "high"
    if score_agreements >= 2 and len(sources & {"openfootball_json", "wikipedia", "news_crosscheck"}) >= 2:
        return "medium_high"
    if sources == {"wikipedia"}:
        return "medium"
    return "medium" if sources else "local_only"


def _conflict_row(current: dict[str, Any], field: str, local: Any, external: Any, reason: str) -> dict[str, Any]:
    return {
        "match_id": current.get("id", ""),
        "home": current.get("home", ""),
        "away": current.get("away", ""),
        "field": field,
        "local": str(local),
        "external": str(external),
        "sources": ",".join(external.keys()) if isinstance(external, dict) else "",
        "reason": reason,
    }


def _team_name(name: str | None) -> str | None:
    if name is None:
        return None
    return TEAM_ALIASES.get(name, name)

def _canonical_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    out = dict(candidate)
    if out.get("home") is not None:
        out["home"] = _team_name(str(out.get("home")))
    if out.get("away") is not None:
        out["away"] = _team_name(str(out.get("away")))
    return out


def _same_team_set(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_teams = {_team_name(left.get("home")), _team_name(left.get("away"))}
    right_teams = {_team_name(right.get("home")), _team_name(right.get("away"))}
    return None not in left_teams and left_teams == right_teams


def _pick_team_order_source(candidates: list[dict[str, Any]], field_priority: dict[str, list[str]]) -> str | None:
    priorities = field_priority.get("team_order") or field_priority.get("score") or []
    for source in priorities:
        if any(item["source"] == source and item.get("home") and item.get("away") for item in candidates):
            return source
    for item in candidates:
        if item.get("home") and item.get("away"):
            return item["source"]
    return None



def _is_knockout_placeholder_match(match: dict[str, Any]) -> bool:
    return _is_placeholder(match.get("home")) or _is_placeholder(match.get("away"))


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if re.fullmatch(r"[12][A-L]", text):
        return True
    if re.fullmatch(r"3[A-L](?:/[A-L])+", text):
        return True
    if re.fullmatch(r"[WL]\d{2,3}", text):
        return True
    if re.fullmatch(r"RU\d{2,3}", text):
        return True
    return False


def _date_key(value: str | None) -> str | None:
    if not value:
        return None
    return value[:10]


def _merge_date(current_date: str | None, external_date: str | None, candidate: dict[str, Any] | None = None) -> str | None:
    if (
        current_date
        and external_date
        and external_date.endswith("T00:00:00Z")
        and not current_date.endswith("T00:00:00Z")
        and (candidate or {}).get("date_precision") != "exact"
    ):
        return current_date
    return external_date


def _strip_non_final_score(external: dict[str, Any], source_name: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    status = _normalize_status(external.get("status"))
    sanitized = dict(external)
    sanitized["status"] = status
    has_score = sanitized.get("home_score") is not None and sanitized.get("away_score") is not None
    if not has_score or status == "finished":
        return sanitized, None
    sanitized["live_home_score"] = sanitized.get("home_score")
    sanitized["live_away_score"] = sanitized.get("away_score")
    sanitized["live_status"] = status
    sanitized["home_score"] = None
    sanitized["away_score"] = None
    warning = {
        "match_id": external.get("id", ""),
        "home": external.get("home", ""),
        "away": external.get("away", ""),
        "source": source_name,
        "date": external.get("date", ""),
        "reason": "live_score_seen_but_not_applied_as_final",
        "message": "Fonte trouxe placar sem status final; placar mantido apenas como live_score.",
    }
    return sanitized, warning


def _strip_future_score(
    external: dict[str, Any],
    source_name: str,
    allow_future_results: bool,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if allow_future_results:
        return external, None
    if external.get("home_score") is None or external.get("away_score") is None:
        return external, None
    match_date = _parse_datetime(external.get("date"))
    if match_date is None or match_date <= now:
        return external, None
    sanitized = dict(external)
    sanitized["home_score"] = None
    sanitized["away_score"] = None
    sanitized.pop("live_home_score", None)
    sanitized.pop("live_away_score", None)
    sanitized.pop("live_status", None)
    if _normalize_status(sanitized.get("status")) == "finished":
        sanitized["status"] = "scheduled"
    warning = {
        "match_id": external.get("id", ""),
        "home": external.get("home", ""),
        "away": external.get("away", ""),
        "source": source_name,
        "date": external.get("date", ""),
        "reason": "future_result_ignored",
        "message": "Fonte trouxe placar para jogo futuro; placar ignorado.",
    }
    return sanitized, warning


def _normalize_status(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip().lower().replace("_", "-").replace(" ", "-")
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


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _material_changed(current: dict[str, Any], resolved: dict[str, Any]) -> bool:
    material_fields = ("home", "away", "home_score", "away_score", "status", "date", "venue")
    return any(current.get(field) != resolved.get(field) for field in material_fields)


def _non_final_score_detected(field_changes: list[tuple[str, str]]) -> bool:
    fields = {field for _, field in field_changes}
    return "live_score_detected" in fields or "live_score_not_applied" in fields


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
