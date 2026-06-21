from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.models import Match

MAX_DELTA = 80
WIN_BONUS = 18
DRAW_BONUS = 6
LOSS_PENALTY = -12
GOAL_DIFF_FACTOR = 4
GOAL_DIFF_CAP = 20
UPSET_FACTOR = 0.08


def recalibrate_ratings_from_results(
    base_ratings: dict[str, int],
    matches: list[Match],
    max_delta: int = MAX_DELTA,
) -> dict[str, Any]:
    deltas = {team: 0.0 for team in base_ratings}
    details = {team: [] for team in base_ratings}
    for match in matches:
        if match.status != "finished" or match.home_score is None or match.away_score is None:
            continue
        home_delta, away_delta = _match_deltas(match, base_ratings)
        _add_delta(deltas, details, match.home, home_delta, match)
        _add_delta(deltas, details, match.away, away_delta, match)

    adjusted = {}
    rows = []
    for team, base in base_ratings.items():
        delta = round(max(-max_delta, min(max_delta, deltas[team])))
        adjusted[team] = base + delta
        rows.append({
            "team": team,
            "base_rating": base,
            "adjusted_rating": adjusted[team],
            "delta": delta,
            "details": details[team],
        })
    rows.sort(key=lambda row: row["delta"], reverse=True)
    return {
        "source": "tournament_form",
        "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "config": {
            "max_delta": max_delta,
            "win_bonus": WIN_BONUS,
            "draw_bonus": DRAW_BONUS,
            "loss_penalty": LOSS_PENALTY,
            "goal_diff_factor": GOAL_DIFF_FACTOR,
            "goal_diff_cap": GOAL_DIFF_CAP,
            "upset_factor": UPSET_FACTOR,
        },
        "ratings": adjusted,
        "rows": rows,
    }


def _match_deltas(match: Match, ratings: dict[str, int]) -> tuple[float, float]:
    assert match.home_score is not None and match.away_score is not None
    home_gd = match.home_score - match.away_score
    away_gd = -home_gd
    if home_gd > 0:
        home_result, away_result = WIN_BONUS, LOSS_PENALTY
    elif home_gd == 0:
        home_result = away_result = DRAW_BONUS
    else:
        home_result, away_result = LOSS_PENALTY, WIN_BONUS
    home_delta = home_result + _goal_delta(home_gd) + _upset_delta(match.home, match.away, ratings, home_gd)
    away_delta = away_result + _goal_delta(away_gd) + _upset_delta(match.away, match.home, ratings, away_gd)
    return home_delta, away_delta


def _goal_delta(goal_difference: int) -> int:
    return max(-GOAL_DIFF_CAP, min(GOAL_DIFF_CAP, goal_difference * GOAL_DIFF_FACTOR))


def _upset_delta(team: str, opponent: str, ratings: dict[str, int], goal_difference: int) -> float:
    if goal_difference < 0:
        return 0.0
    diff = ratings[opponent] - ratings[team]
    if diff <= 0:
        return 0.0
    return diff * UPSET_FACTOR


def _add_delta(deltas: dict[str, float], details: dict[str, list[str]], team: str, delta: float, match: Match) -> None:
    if team not in deltas:
        return
    deltas[team] += delta
    details[team].append(f"{match.id}: {delta:+.1f}")

