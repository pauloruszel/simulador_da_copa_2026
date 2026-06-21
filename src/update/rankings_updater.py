from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def normalize_rankings(payload: dict[str, Any], source: str) -> dict[str, Any]:
    rankings = payload.get("rankings", payload if isinstance(payload, list) else [])
    if not isinstance(rankings, list):
        raise ValueError("Ranking externo precisa ser lista ou conter chave rankings.")
    return {
        "source": source,
        "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "rankings": rankings,
    }


def ranking_to_ratings(rankings: list[dict[str, Any]], max_rating: int = 2100, step: int = 8) -> dict[str, int]:
    ratings = {}
    for item in rankings:
        team = item.get("team") or item.get("name")
        rank = item.get("rank")
        if team and isinstance(rank, int):
            ratings[team] = max(1200, max_rating - (rank - 1) * step)
    return ratings

