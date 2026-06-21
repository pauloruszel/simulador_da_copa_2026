from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    id: str
    group: str
    home: str
    away: str
    home_score: int | None = None
    away_score: int | None = None
    status: str = "scheduled"
    date: str | None = None
    provider_id: str | None = None
    source: str | None = None
    last_updated: str | None = None
    venue: str | None = None
    sources: list[dict] | None = None
    resolved_confidence: str | None = None
    last_verified_at: str | None = None
    # Non-final/live score metadata can be persisted by the multi-source updater.
    # These fields must be accepted by the domain model, but standings/simulation
    # continue to use only home_score/away_score when status == "finished".
    live_home_score: int | None = None
    live_away_score: int | None = None
    live_status: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Match":
        # Be tolerant to forward-compatible metadata that may be written by data
        # ingestion pipelines. Unknown keys are intentionally ignored so reports
        # can evolve without breaking backtest/simulation loading.
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class TeamStanding:
    team: str
    group: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    def apply(self, gf: int, ga: int) -> None:
        self.played += 1
        self.goals_for += gf
        self.goals_against += ga
        if gf > ga:
            self.wins += 1
            self.points += 3
        elif gf == ga:
            self.draws += 1
            self.points += 1
        else:
            self.losses += 1
