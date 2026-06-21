from __future__ import annotations

import math
import random

BASE_GOALS = 1.25
GOAL_ADVANTAGE_SCALE = 0.0022
MIN_EXPECTED_GOALS = 0.20
MAX_EXPECTED_GOALS = 3.20


def expected_goals(
    rating_home: int,
    rating_away: int,
    base_goals: float = BASE_GOALS,
    goal_advantage_scale: float = GOAL_ADVANTAGE_SCALE,
    min_expected_goals: float = MIN_EXPECTED_GOALS,
    max_expected_goals: float = MAX_EXPECTED_GOALS,
) -> tuple[float, float]:
    diff = rating_home - rating_away
    return (
        min(max_expected_goals, max(min_expected_goals, base_goals + diff * goal_advantage_scale)),
        min(max_expected_goals, max(min_expected_goals, base_goals - diff * goal_advantage_scale)),
    )


def poisson_sample(lam: float, rng: random.Random) -> int:
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def simulate_score(
    home: str,
    away: str,
    ratings: dict[str, int],
    rng: random.Random,
    poisson_config: dict | None = None,
) -> tuple[int, int]:
    cfg = poisson_config or {}
    eh, ea = expected_goals(
        ratings[home],
        ratings[away],
        cfg.get("base_goals", BASE_GOALS),
        cfg.get("goal_advantage_scale", GOAL_ADVANTAGE_SCALE),
        cfg.get("min_expected_goals", MIN_EXPECTED_GOALS),
        cfg.get("max_expected_goals", MAX_EXPECTED_GOALS),
    )
    home_goals, away_goals = poisson_sample(eh, rng), poisson_sample(ea, rng)
    draw_factor = cfg.get("draw_correction_factor", 1.0)
    if draw_factor > 1.0 and home_goals != away_goals:
        if rng.random() < min(0.12, (draw_factor - 1.0) * 0.5):
            target = min(home_goals, away_goals)
            return target, target
    if draw_factor < 1.0 and home_goals == away_goals:
        if rng.random() < min(0.12, (1.0 - draw_factor) * 0.5):
            return home_goals + 1, away_goals
    return home_goals, away_goals
