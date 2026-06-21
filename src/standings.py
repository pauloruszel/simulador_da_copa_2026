from __future__ import annotations

from .models import Match, TeamStanding


def empty_group_table(group: str, teams: list[str]) -> dict[str, TeamStanding]:
    return {team: TeamStanding(team=team, group=group) for team in teams}


def apply_result(table: dict[str, TeamStanding], home: str, away: str, home_score: int, away_score: int) -> None:
    table[home].apply(home_score, away_score)
    table[away].apply(away_score, home_score)


def sort_table(table: dict[str, TeamStanding], ratings: dict[str, int]) -> list[TeamStanding]:
    return sorted(
        table.values(),
        key=lambda s: (s.points, s.goal_difference, s.goals_for, ratings[s.team]),
        reverse=True,
    )


def calculate_group_rankings(
    groups: dict[str, list[str]], matches: list[Match], ratings: dict[str, int]
) -> dict[str, list[TeamStanding]]:
    tables = {group: empty_group_table(group, teams) for group, teams in groups.items()}
    for match in matches:
        if match.status == "finished":
            assert match.home_score is not None and match.away_score is not None
            apply_result(tables[match.group], match.home, match.away, match.home_score, match.away_score)
    return {group: sort_table(table, ratings) for group, table in tables.items()}

