from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from .knockout import resolve_knockout_slots, simulate_knockout
from .models import Match
from .poisson_model import simulate_score
from .qualification import qualification_snapshot
from .standings import calculate_group_rankings


@dataclass
class SimulationConfig:
    simulations: int = 50000
    seed: int | None = None
    strict_third_mapping: bool = False
    model_config: dict | None = None


def _simulate_group_matches(
    matches: list[Match], ratings: dict[str, int], rng: random.Random, poisson_config: dict | None = None
) -> list[Match]:
    simulated = []
    for m in matches:
        if m.status == "finished":
            simulated.append(m)
        else:
            hs, as_ = simulate_score(m.home, m.away, ratings, rng, poisson_config)
            simulated.append(Match(m.id, m.group, m.home, m.away, hs, as_, "finished", m.date))
    return simulated


def run_monte_carlo(groups, matches, ratings, bracket, third_mapping, config: SimulationConfig) -> dict:
    rng = random.Random(config.seed)
    teams = [t for ts in groups.values() for t in ts]
    team_group = {t: g for g, ts in groups.items() for t in ts}
    c = {t: Counter() for t in teams}
    elimination = {t: Counter() for t in teams}
    r32_match = {t: Counter() for t in teams}
    r32_opp = {t: Counter() for t in teams}
    approximate_count = 0
    model_config = config.model_config or {}
    for _ in range(config.simulations):
        sim_matches = _simulate_group_matches(matches, ratings, rng, model_config.get("poisson"))
        rankings = calculate_group_rankings(groups, sim_matches, ratings)
        q = qualification_snapshot(rankings, ratings)
        qualifier_teams = {s.team for s in q["qualifiers"]}
        for g, table in rankings.items():
            for pos, s in enumerate(table, 1):
                c[s.team][f"group_pos_{pos}"] += 1
            for s in table[:2]:
                c[s.team]["round32"] += 1
            for s in table:
                if s.team not in qualifier_teams:
                    c[s.team]["group_eliminated"] += 1
                    elimination[s.team]["Group stage"] += 1
        for s in q["best_thirds"]:
            c[s.team]["best_third"] += 1
            c[s.team]["round32"] += 1
        resolved = resolve_knockout_slots(
            rankings, q["best_third_groups"], bracket, third_mapping, config.strict_third_mapping
        )
        for mid, pair in resolved.items():
            for a, b in ((pair["team_a"], pair["team_b"]), (pair["team_b"], pair["team_a"])):
                r32_match[a][mid] += 1
                r32_opp[a][b] += 1
        _, stages, approximate = simulate_knockout(
            rankings,
            q["best_third_groups"],
            bracket,
            third_mapping,
            ratings,
            rng,
            config.strict_third_mapping,
            model_config.get("knockout"),
        )
        approximate_count += int(approximate)
        for team, stage in stages.items():
            for reached in _cumulative_stages(stage):
                c[team][reached] += 1
            if stage != "winner":
                elimination[team][_stage_label(stage)] += 1

    rows = []
    n = config.simulations
    for team in teams:
        row = {
            "team": team,
            "group": team_group[team],
            "group_winner_pct": 100 * c[team]["group_pos_1"] / n,
            "group_runner_up_pct": 100 * c[team]["group_pos_2"] / n,
            "best_third_pct": 100 * c[team]["best_third"] / n,
            "group_eliminated_pct": 100 * c[team]["group_eliminated"] / n,
            "round32_pct": 100 * c[team]["round32"] / n,
            "round16_pct": 100 * c[team]["round16"] / n,
            "quarterfinal_pct": 100 * c[team]["quarterfinal"] / n,
            "semifinal_pct": 100 * c[team]["semifinal"] / n,
            "final_pct": 100 * c[team]["final"] / n,
            "winner_pct": 100 * c[team]["winner"] / n,
            "most_common_round32_match": r32_match[team].most_common(1)[0][0] if r32_match[team] else "",
            "most_common_round32_opponent": r32_opp[team].most_common(1)[0][0] if r32_opp[team] else "",
            "most_common_elimination_stage": _most_common_elimination(elimination[team]),
        }
        row.update(_ci_fields(row, n))
        rows.append(row)
    team_paths = {
        team: {
            "round32_matches": _counter_distribution(r32_match[team], n),
            "round32_opponents": _counter_distribution(r32_opp[team], n),
            "elimination_stages": _counter_distribution(elimination[team], n),
        }
        for team in teams
    }
    return {
        "rows": sorted(rows, key=lambda x: x["winner_pct"], reverse=True),
        "simulations": n,
        "seed": config.seed,
        "third_mapping_approximate_pct": 100 * approximate_count / n,
        "team_paths": team_paths,
        "model_config": model_config,
    }


def _most_common_elimination(counter: Counter) -> str:
    if not counter:
        return "Champion"
    return counter.most_common(1)[0][0]


def _cumulative_stages(stage: str) -> list[str]:
    order = ["round16", "quarterfinal", "semifinal", "final", "winner"]
    if stage not in order:
        return []
    return order[: order.index(stage) + 1]


def _stage_label(stage: str) -> str:
    return {
        "round32": "Round of 32",
        "round16": "Round of 16",
        "quarterfinal": "Quarterfinal",
        "semifinal": "Semifinal",
        "final": "Final",
    }[stage]


def _counter_distribution(counter: Counter, simulations: int) -> list[dict]:
    return [
        {"name": str(name), "count": count, "pct": 100 * count / simulations}
        for name, count in counter.most_common()
    ]


def _ci_fields(row: dict, simulations: int) -> dict:
    fields = {}
    for key in ("round32_pct", "round16_pct", "quarterfinal_pct", "semifinal_pct", "final_pct", "winner_pct"):
        p = row[key] / 100
        se = (p * (1 - p) / simulations) ** 0.5
        low = max(0.0, p - 1.96 * se) * 100
        high = min(1.0, p + 1.96 * se) * 100
        fields[f"{key[:-4]}_ci_low"] = low
        fields[f"{key[:-4]}_ci_high"] = high
    return fields
