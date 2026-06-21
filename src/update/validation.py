from __future__ import annotations

from typing import Any


VALID_STATUSES = {"scheduled", "live", "finished"}


def validate_normalized_match(match: dict[str, Any]) -> None:
    required = {"home", "away", "status"}
    missing = required - set(match)
    if missing:
        raise ValueError(f"Partida externa sem campos obrigatorios: {sorted(missing)}")
    if match["status"] not in VALID_STATUSES:
        raise ValueError(f"Status externo invalido: {match['status']}")
    if match["status"] == "finished" and (
        match.get("home_score") is None or match.get("away_score") is None
    ):
        raise ValueError("Partida finalizada precisa de placar.")


def validate_odds_record(record: dict[str, Any]) -> None:
    if "home" not in record or "away" not in record or "markets" not in record:
        raise ValueError("Registro de odds precisa de home, away e markets.")

