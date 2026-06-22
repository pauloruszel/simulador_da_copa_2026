from __future__ import annotations

from collections import defaultdict

from .models import Match, TeamStanding


def empty_group_table(group: str, teams: list[str]) -> dict[str, TeamStanding]:
    return {team: TeamStanding(team=team, group=group) for team in teams}


def apply_result(table: dict[str, TeamStanding], home: str, away: str, home_score: int, away_score: int) -> None:
    table[home].apply(home_score, away_score)
    table[away].apply(away_score, home_score)


def _head_to_head_metrics(teams: set[str], matches: list[Match] | None) -> dict[str, tuple[int, int, int]]:
    """Return points, goal difference and goals scored among tied teams.

    The 2026 World Cup group ranking uses head-to-head criteria before
    overall goal difference for teams level on points. When match data is not
    supplied, all head-to-head metrics remain zero and sorting falls back to
    the legacy overall criteria.
    """
    metrics: dict[str, dict[str, int]] = defaultdict(lambda: {"pts": 0, "gf": 0, "ga": 0})
    for team in teams:
        metrics[team]  # initialise key
    for match in matches or []:
        if match.status != "finished" or match.home not in teams or match.away not in teams:
            continue
        if match.home_score is None or match.away_score is None:
            continue
        home = metrics[match.home]
        away = metrics[match.away]
        home["gf"] += match.home_score
        home["ga"] += match.away_score
        away["gf"] += match.away_score
        away["ga"] += match.home_score
        if match.home_score > match.away_score:
            home["pts"] += 3
        elif match.home_score < match.away_score:
            away["pts"] += 3
        else:
            home["pts"] += 1
            away["pts"] += 1
    return {
        team: (values["pts"], values["gf"] - values["ga"], values["gf"])
        for team, values in metrics.items()
    }


def sort_table(table: dict[str, TeamStanding], ratings: dict[str, int], matches: list[Match] | None = None) -> list[TeamStanding]:
    """Sort a group table using the tournament group tiebreakers.

    Primary order: points. For teams tied on points, use head-to-head points,
    head-to-head goal difference and head-to-head goals scored. If still tied,
    use overall goal difference, goals scored and finally the rating file as a
    deterministic proxy for the final FIFA ranking fallback.
    """
    rows = sorted(table.values(), key=lambda s: (s.points, s.goal_difference, s.goals_for, ratings[s.team]), reverse=True)
    sorted_rows: list[TeamStanding] = []
    idx = 0
    while idx < len(rows):
        tied = [rows[idx]]
        idx += 1
        while idx < len(rows) and rows[idx].points == tied[0].points:
            tied.append(rows[idx])
            idx += 1
        if len(tied) == 1:
            sorted_rows.extend(tied)
            continue
        teams = {standing.team for standing in tied}
        h2h = _head_to_head_metrics(teams, matches)
        sorted_rows.extend(
            sorted(
                tied,
                key=lambda s: (
                    h2h.get(s.team, (0, 0, 0))[0],
                    h2h.get(s.team, (0, 0, 0))[1],
                    h2h.get(s.team, (0, 0, 0))[2],
                    s.goal_difference,
                    s.goals_for,
                    ratings[s.team],
                ),
                reverse=True,
            )
        )
    return sorted_rows


def calculate_group_rankings(
    groups: dict[str, list[str]], matches: list[Match], ratings: dict[str, int]
) -> dict[str, list[TeamStanding]]:
    tables = {group: empty_group_table(group, teams) for group, teams in groups.items()}
    finished_by_group: dict[str, list[Match]] = defaultdict(list)
    for match in matches:
        if match.status == "finished":
            assert match.home_score is not None and match.away_score is not None
            apply_result(tables[match.group], match.home, match.away, match.home_score, match.away_score)
            finished_by_group[match.group].append(match)
    return {group: sort_table(table, ratings, finished_by_group.get(group, [])) for group, table in tables.items()}
