from __future__ import annotations

import csv
import json
from json import JSONDecodeError
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.models import Match
from src.storage.json_store import JsonStore


def load_model_weights(preset: str | None = None, store: JsonStore | None = None) -> dict[str, Any]:
    store = store or JsonStore()
    weights = store.read("data/model_weights.json", {})
    if preset:
        presets = store.read("data/model_presets.json", {})
        if preset not in presets:
            raise ValueError(f"Preset desconhecido: {preset}")
        weights = apply_preset(weights, presets[preset])
        weights["preset"] = preset
        weights["preset_description"] = presets[preset].get("description", "")
    else:
        weights["preset"] = "custom"
    return weights


def load_weights_file(path: str | Path, preset: str | None = None, store: JsonStore | None = None) -> tuple[dict[str, Any], list[str]]:
    store = store or JsonStore()
    base = load_model_weights(None, store)
    warnings: list[str] = []
    target = Path(path)
    if not target.exists():
        raise ValueError(f"Arquivo de pesos nao encontrado: {path}")
    try:
        with target.open(encoding="utf-8") as f:
            payload = json.load(f)
    except JSONDecodeError as exc:
        raise ValueError(f"JSON invalido em arquivo de pesos {path}: {exc}") from exc
    candidate = extract_weights_payload(payload)
    if not isinstance(candidate, dict):
        raise ValueError(f"Arquivo de pesos sem objeto de pesos valido: {path}")
    merged = _deep_merge(base, candidate, warnings)
    merged["preset"] = "weights_file"
    merged["weights_file"] = str(path)
    if preset:
        warnings.append("--weights-file informado; --model-preset foi ignorado.")
    return merged, warnings


def extract_weights_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "weights" in payload and isinstance(payload["weights"], dict):
        return payload["weights"]
    if "best" in payload and isinstance(payload["best"], dict) and isinstance(payload["best"].get("config"), dict):
        return payload["best"]["config"]
    if "config" in payload and isinstance(payload["config"], dict):
        return payload["config"]
    return payload


def apply_preset(weights: dict[str, Any], preset: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(weights))
    rating_model = merged.setdefault("rating_model", {})
    rating_model["base_rating_weight"] = preset.get("base_rating_weight", rating_model.get("base_rating_weight", 0.5))
    rating_model["tournament_form_weight"] = preset.get(
        "tournament_form_weight", rating_model.get("tournament_form_weight", 0.2)
    )
    rating_model["market_odds_weight"] = preset.get("market_odds_weight", rating_model.get("market_odds_weight", 0.0))
    rating_model["home_advantage_weight"] = preset.get(
        "home_advantage_weight", rating_model.get("home_advantage_weight", 0.0)
    )
    merged.setdefault("knockout", {})["sensitivity"] = preset.get(
        "knockout_sensitivity", merged.get("knockout", {}).get("sensitivity", 420)
    )
    return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any], warnings: list[str] | None = None, path: str = "") -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if key not in result:
            result[key] = value
            continue
        if isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value, warnings, f"{path}.{key}" if path else key)
        else:
            result[key] = value
    if warnings is not None:
        missing = _missing_paths(base, override)
        if missing:
            warnings.append("Pesos ausentes preenchidos com fallback: " + ", ".join(missing[:12]))
    return result


def _missing_paths(base: dict[str, Any], override: dict[str, Any], prefix: str = "") -> list[str]:
    missing = []
    for key, value in base.items():
        full = f"{prefix}.{key}" if prefix else key
        if key not in override:
            missing.append(full)
        elif isinstance(value, dict) and isinstance(override.get(key), dict):
            missing.extend(_missing_paths(value, override[key], full))
    return missing


def expected_result_score(team: str, opponent: str, ratings: dict[str, int]) -> float:
    diff = ratings[team] - ratings[opponent]
    return 1 / (1 + 10 ** (-diff / 420))


def opponent_adjusted_match_delta(
    team: str,
    opponent: str,
    goals_for: int,
    goals_against: int,
    base_ratings: dict[str, int],
    weights: dict[str, Any],
) -> float:
    form = weights.get("form_adjustment", {})
    gd = goals_for - goals_against
    actual = 1.0 if gd > 0 else 0.5 if gd == 0 else 0.0
    expected = expected_result_score(team, opponent, base_ratings)
    surprise = actual - expected
    opponent_gap = base_ratings[opponent] - base_ratings[team]
    opponent_factor = opponent_gap * form.get("opponent_strength_weight", 0.08)
    goal_impact = _saturated_goal_diff(gd) * form.get("goal_difference_weight", 6)
    raw = surprise * 40 + opponent_factor * abs(surprise) + goal_impact
    cap = form.get("cap_single_match_delta", 25)
    return max(-cap, min(cap, raw))


def recency_multiplier(match_date: datetime, reference_date: datetime) -> float:
    days = max(0, (reference_date - match_date).days)
    return max(0.70, 1.0 - 0.15 * (days / 7))


def market_implied_team_strength(odds_data: dict[str, Any], ratings: dict[str, int]) -> dict[str, float]:
    """Return market-derived rating deltas from normalized winner odds.

    The odds feed is intentionally used as a soft anchor: it compares the
    market's normalized title probabilities with a rating-prior distribution
    derived from the current ratings and converts the difference into bounded
    rating deltas. The caller still applies ``market_odds_weight``, so by
    default this remains a benchmark/light adjustment rather than a hard
    replacement for the model.
    """
    deltas = {team: 0.0 for team in ratings}
    outrights = odds_data.get("outrights", []) if isinstance(odds_data, dict) else []
    market_probs = {
        item.get("team"): float(item.get("market_probability", 0.0))
        for item in outrights
        if item.get("team") in ratings and isinstance(item.get("market_probability"), (int, float))
    }
    if len(market_probs) < 2:
        return deltas

    scale = odds_data.get("rating_scale", 350) if isinstance(odds_data, dict) else 350
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 350.0
    scale = max(scale, 50.0)
    max_delta = odds_data.get("max_market_rating_delta", 80) if isinstance(odds_data, dict) else 80
    pp_to_rating = odds_data.get("pp_to_rating", 8) if isinstance(odds_data, dict) else 8
    try:
        max_delta = float(max_delta)
        pp_to_rating = float(pp_to_rating)
    except (TypeError, ValueError):
        max_delta = 80.0
        pp_to_rating = 8.0

    teams = list(market_probs)
    max_rating = max(ratings[team] for team in teams)
    rating_raw = {team: math.exp((ratings[team] - max_rating) / scale) for team in teams}
    rating_total = sum(rating_raw.values())
    if rating_total <= 0:
        return deltas
    rating_probs = {team: value / rating_total for team, value in rating_raw.items()}

    for team in teams:
        diff_pp = (market_probs[team] - rating_probs[team]) * 100
        deltas[team] = max(-max_delta, min(max_delta, diff_pp * pp_to_rating))
    return deltas


def build_calibrated_ratings(
    base_ratings: dict[str, int],
    matches: list[Match],
    weights: dict[str, Any],
    fifa_ranking: dict[str, Any] | None = None,
    elo_ratings: dict[str, Any] | None = None,
    odds_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    form_deltas = _tournament_form_deltas(base_ratings, matches, weights)
    market_deltas = market_implied_team_strength(odds_data or {}, base_ratings)
    host_teams = set(weights.get("home_advantage", {}).get("host_teams", []))
    home_bonus = weights.get("home_advantage", {}).get("rating_bonus", 0)
    home_enabled = weights.get("home_advantage", {}).get("enabled", False)
    rating_model = weights.get("rating_model", {})
    form_weight = rating_model.get("tournament_form_weight", 0.2)
    market_weight = rating_model.get("market_odds_weight", 0.0)
    home_weight = rating_model.get("home_advantage_weight", 1.0)
    breakdown = {}
    ratings = {}
    for team, base in base_ratings.items():
        fifa_component = 0
        elo_component = 0
        form_component = round(form_deltas.get(team, 0) * form_weight)
        opponent_component = round(form_deltas.get(team, 0) * 0.25)
        market_component = round(market_deltas.get(team, 0) * market_weight)
        home_component = round(home_bonus * home_weight) if home_enabled and team in host_teams else 0
        uncertainty_adjustment = _uncertainty_adjustment(team, matches)
        final_rating = round(
            base
            + fifa_component
            + elo_component
            + form_component
            + opponent_component
            + market_component
            + home_component
            + uncertainty_adjustment
        )
        ratings[team] = final_rating
        breakdown[team] = {
            "team": team,
            "base_rating": base,
            "fifa_component": fifa_component,
            "elo_component": elo_component,
            "tournament_form_component": form_component,
            "opponent_adjusted_component": opponent_component,
            "market_component": market_component,
            "home_advantage_component": home_component,
            "uncertainty_adjustment": uncertainty_adjustment,
            "final_rating": final_rating,
            "delta_total": final_rating - base,
            "explanation": _explain(team, final_rating - base, form_component, opponent_component, home_component, market_component),
        }
    return {
        "source": "calibrated",
        "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "preset": weights.get("preset", "custom"),
        "ratings": ratings,
        "breakdown": breakdown,
        "weights": weights,
    }


def save_calibrated_ratings(result: dict[str, Any], output_dir: str | Path = "output") -> None:
    JsonStore().write("data/calibrated_ratings.json", result)
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    rows = list(result["breakdown"].values())
    fields = [
        "team", "base_rating", "fifa_component", "elo_component", "tournament_form_component",
        "opponent_adjusted_component", "market_component", "home_advantage_component",
        "uncertainty_adjustment", "final_rating", "delta_total", "explanation",
    ]
    with (out / "rating_breakdown.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (out / "rating_breakdown.json").open("w", encoding="utf-8") as f:
        json.dump(result["breakdown"], f, indent=2)


def _tournament_form_deltas(base_ratings: dict[str, int], matches: list[Match], weights: dict[str, Any]) -> dict[str, float]:
    form = weights.get("form_adjustment", {})
    max_positive = form.get("max_positive_delta", 60)
    max_negative = form.get("max_negative_delta", 60)
    deltas = {team: 0.0 for team in base_ratings}
    finished_dates = [_parse_date(m.date) for m in matches if m.status == "finished" and m.date]
    reference = max(finished_dates) if finished_dates else datetime.now(UTC)
    for match in matches:
        if match.status != "finished" or match.home_score is None or match.away_score is None:
            continue
        multiplier = recency_multiplier(_parse_date(match.date), reference) if match.date else 1.0
        home_delta = opponent_adjusted_match_delta(
            match.home, match.away, match.home_score, match.away_score, base_ratings, weights
        )
        away_delta = opponent_adjusted_match_delta(
            match.away, match.home, match.away_score, match.home_score, base_ratings, weights
        )
        deltas[match.home] += home_delta * multiplier
        deltas[match.away] += away_delta * multiplier
    return {team: max(-max_negative, min(max_positive, delta)) for team, delta in deltas.items()}


def _saturated_goal_diff(goal_difference: int) -> float:
    if goal_difference == 0:
        return 0.0
    return math.copysign(math.log1p(min(abs(goal_difference), 3)), goal_difference)


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


def _uncertainty_adjustment(team: str, matches: list[Match]) -> int:
    played = sum(1 for m in matches if m.status == "finished" and team in {m.home, m.away})
    return -3 if played < 2 else 0


def _explain(team: str, total: int, form: int, opponent: int, home: int, market: int = 0) -> str:
    parts = []
    if form:
        parts.append(f"forma recente {form:+}")
    if opponent:
        parts.append(f"forca dos adversarios {opponent:+}")
    if market:
        parts.append(f"mercado/odds {market:+}")
    if home:
        parts.append(f"mando/sede {home:+}")
    if not parts:
        parts.append("sem ajuste relevante")
    return f"{team}: delta total {total:+}; " + ", ".join(parts) + "."
