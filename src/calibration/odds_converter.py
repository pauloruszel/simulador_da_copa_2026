from __future__ import annotations


def decimal_odds_to_implied_probability(odds: float) -> float:
    if odds <= 1:
        raise ValueError("Odd decimal precisa ser maior que 1.")
    return 1 / odds


def normalize_three_way_market(home: float, draw: float, away: float) -> dict[str, float]:
    raw = {
        "home": decimal_odds_to_implied_probability(home),
        "draw": decimal_odds_to_implied_probability(draw),
        "away": decimal_odds_to_implied_probability(away),
    }
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}

