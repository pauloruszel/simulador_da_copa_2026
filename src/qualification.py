from __future__ import annotations

from .models import TeamStanding


def select_best_thirds(group_rankings: dict[str, list[TeamStanding]], ratings: dict[str, int]) -> list[TeamStanding]:
    thirds = [rankings[2] for rankings in group_rankings.values()]
    return sorted(
        thirds,
        key=lambda s: (s.points, s.goal_difference, s.goals_for, ratings[s.team]),
        reverse=True,
    )[:8]


def qualification_snapshot(group_rankings: dict[str, list[TeamStanding]], ratings: dict[str, int]) -> dict:
    best_thirds = select_best_thirds(group_rankings, ratings)
    best_third_groups = [s.group for s in best_thirds]
    qualifiers = []
    for group, rankings in group_rankings.items():
        qualifiers.extend(rankings[:2])
    qualifiers.extend(best_thirds)
    if len(qualifiers) != 32:
        raise ValueError("Numero final de classificados deve ser 32.")
    return {
        "qualifiers": qualifiers,
        "best_thirds": best_thirds,
        "best_third_groups": best_third_groups,
        "eliminated": [
            s for group, rankings in group_rankings.items() for s in rankings if s not in qualifiers
        ],
    }

