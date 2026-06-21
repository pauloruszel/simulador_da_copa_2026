from __future__ import annotations

import random

from .models import TeamStanding

KNOCKOUT_SENSITIVITY = 420.0
ROUND_ORDER = ["round_of_32", "round_of_16", "quarterfinals", "semifinals", "final"]


def knockout_win_probability(
    team_a: str,
    team_b: str,
    ratings: dict[str, int],
    sensitivity: float = KNOCKOUT_SENSITIVITY,
    upset_floor: float = 0.0,
    favorite_ceiling: float = 1.0,
) -> float:
    rating_diff = ratings[team_a] - ratings[team_b]
    raw = 1 / (1 + 10 ** (-rating_diff / sensitivity))
    return max(upset_floor, min(favorite_ceiling, raw))


def simulate_knockout_match(
    team_a: str,
    team_b: str,
    ratings: dict[str, int],
    rng: random.Random,
    sensitivity: float = KNOCKOUT_SENSITIVITY,
    upset_floor: float = 0.0,
    favorite_ceiling: float = 1.0,
) -> str:
    probability = knockout_win_probability(team_a, team_b, ratings, sensitivity, upset_floor, favorite_ceiling)
    return team_a if rng.random() < probability else team_b


def _third_key(groups: list[str]) -> str:
    return ",".join(sorted(groups))


def _fallback_third_mapping(best_third_groups: list[str], slots: list[str]) -> dict[str, str]:
    remaining = sorted(best_third_groups)
    result = {}
    for slot in slots:
        allowed = slot[1:].split("/")
        pick = next((g for g in remaining if g in allowed), remaining[0])
        result[slot] = "3" + pick
        remaining.remove(pick)
    return result


def resolve_knockout_slots(
    group_rankings: dict[str, list[TeamStanding]],
    best_third_groups: list[str],
    bracket_config: dict,
    third_place_mapping: dict,
    strict: bool = True,
) -> dict[str, dict[str, str]]:
    slots = sorted({s for m in bracket_config["round_of_32"] for s in (m["slot_a"], m["slot_b"]) if s.startswith("3")})
    key = _third_key(best_third_groups)
    mapping = third_place_mapping.get(key)
    approximate = False
    if mapping is None:
        if strict:
            raise ValueError(f"Mapeamento de terceiros ausente para combinacao: {key}")
        mapping = _fallback_third_mapping(best_third_groups, slots)
        approximate = True

    def resolve(slot: str) -> str:
        if slot[0] in "12" and len(slot) == 2:
            return group_rankings[slot[1]][int(slot[0]) - 1].team
        if slot.startswith("3"):
            mapped = mapping.get(slot)
            if not mapped:
                if strict:
                    raise ValueError(f"Slot de terceiro nao mapeado: {slot} em {key}")
                mapped = _fallback_third_mapping(best_third_groups, [slot])[slot]
            return group_rankings[mapped[1]][2].team
        raise ValueError(f"Slot ainda nao resolvivel no Round of 32: {slot}")

    resolved = {}
    for match in bracket_config["round_of_32"]:
        resolved[str(match["match_id"])] = {
            "team_a": resolve(match["slot_a"]),
            "team_b": resolve(match["slot_b"]),
            "approximate_third_mapping": approximate,
        }
    return resolved


def simulate_knockout(
    group_rankings: dict[str, list[TeamStanding]],
    best_third_groups: list[str],
    bracket_config: dict,
    third_place_mapping: dict,
    ratings: dict[str, int],
    rng: random.Random,
    strict_third_mapping: bool = False,
    knockout_config: dict | None = None,
) -> tuple[dict[int, str], dict[str, str], bool]:
    knockout_config = knockout_config or {}
    sensitivity = knockout_config.get("sensitivity", KNOCKOUT_SENSITIVITY)
    upset_floor = knockout_config.get("upset_floor", 0.0)
    favorite_ceiling = knockout_config.get("favorite_ceiling", 1.0)
    results: dict[int, str] = {}
    team_stage: dict[str, str] = {}
    approximate = False
    try:
        r32 = resolve_knockout_slots(
            group_rankings, best_third_groups, bracket_config, third_place_mapping, strict_third_mapping
        )
    except ValueError:
        if strict_third_mapping:
            raise
        r32 = resolve_knockout_slots(group_rankings, best_third_groups, bracket_config, third_place_mapping, False)
        approximate = True
    for m in bracket_config["round_of_32"]:
        mid = int(m["match_id"])
        team_a = r32[str(mid)]["team_a"]
        team_b = r32[str(mid)]["team_b"]
        winner = simulate_knockout_match(team_a, team_b, ratings, rng, sensitivity, upset_floor, favorite_ceiling)
        loser = team_b if winner == team_a else team_a
        results[mid] = winner
        team_stage[winner] = "round16"
        team_stage[loser] = "round32"
        approximate = approximate or bool(r32[str(mid)].get("approximate_third_mapping"))
    round_stage = {
        "round_of_16": "quarterfinal",
        "quarterfinals": "semifinal",
        "semifinals": "final",
        "final": "winner",
    }
    loser_stage = {
        "round_of_16": "round16",
        "quarterfinals": "quarterfinal",
        "semifinals": "semifinal",
        "final": "final",
    }
    for round_name in ROUND_ORDER[1:]:
        for m in bracket_config[round_name]:
            team_a = results[int(m["slot_a"][1:])]
            team_b = results[int(m["slot_b"][1:])]
            winner = simulate_knockout_match(team_a, team_b, ratings, rng, sensitivity, upset_floor, favorite_ceiling)
            loser = team_b if winner == team_a else team_a
            results[int(m["match_id"])] = winner
            team_stage[winner] = round_stage[round_name]
            team_stage[loser] = loser_stage[round_name]
    return results, team_stage, approximate
