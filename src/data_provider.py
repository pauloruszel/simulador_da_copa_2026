from __future__ import annotations

import copy
import json
from pathlib import Path

from .models import Match


class DataProvider:
    def load_groups(self) -> dict[str, list[str]]:
        raise NotImplementedError

    def load_matches(self) -> list[Match]:
        raise NotImplementedError

    def load_ratings(self) -> dict[str, int]:
        raise NotImplementedError

    def load_knockout_bracket(self) -> dict:
        raise NotImplementedError

    def load_third_place_mapping(self) -> dict:
        raise NotImplementedError


class LocalJsonDataProvider(DataProvider):
    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)

    def _load_json(self, name: str):
        with (self.data_dir / name).open(encoding="utf-8") as f:
            return json.load(f)

    def load_groups(self) -> dict[str, list[str]]:
        return self._load_json("groups.json")

    def load_matches(self) -> list[Match]:
        return [Match.from_dict(x) for x in self._load_json("matches.json")]

    def load_ratings(self) -> dict[str, int]:
        return self._load_json("ratings.json")

    def load_knockout_bracket(self) -> dict:
        return self._load_json("knockout_bracket.json")

    def load_third_place_mapping(self) -> dict:
        return self._load_json("third_place_mapping.json")


class ApiFootballDataProvider(DataProvider):
    """Future integration point for external football APIs."""


def apply_scenario(matches: list[Match], scenario_path: str | Path | None) -> list[Match]:
    cloned = copy.deepcopy(matches)
    if not scenario_path:
        return cloned
    with Path(scenario_path).open(encoding="utf-8") as f:
        scenario = json.load(f)
    for override in scenario.get("overrides", []):
        for i, match in enumerate(cloned):
            same_id = override.get("id") and override["id"] == match.id
            same_teams = override.get("home") == match.home and override.get("away") == match.away
            if same_id or same_teams:
                data = match.__dict__ | override
                cloned[i] = Match.from_dict(data)
                break
        else:
            raise ValueError(f"Cenario referencia jogo inexistente: {override}")
    return cloned


def validate_data(groups: dict[str, list[str]], matches: list[Match], ratings: dict[str, int], bracket: dict) -> None:
    if len(groups) != 12:
        raise ValueError("groups.json deve conter 12 grupos.")
    teams = {team for group in groups.values() for team in group}
    for group, group_teams in groups.items():
        if len(group_teams) != 4:
            raise ValueError(f"Grupo {group} deve conter 4 selecoes.")
    missing_ratings = sorted(teams - set(ratings))
    if missing_ratings:
        raise ValueError(f"Ratings ausentes: {missing_ratings}")
    team_to_group = {team: group for group, ts in groups.items() for team in ts}
    for match in matches:
        if match.home not in teams or match.away not in teams:
            raise ValueError(f"Jogo {match.id} possui selecao fora dos grupos.")
        if team_to_group[match.home] != match.group or team_to_group[match.away] != match.group:
            raise ValueError(f"Jogo {match.id} nao pertence ao grupo informado.")
        if match.status == "finished" and (match.home_score is None or match.away_score is None):
            raise ValueError(f"Jogo finalizado {match.id} precisa de placar.")
        if match.status not in {"finished", "scheduled"}:
            raise ValueError(f"Status invalido em {match.id}.")
    valid_prefixes = tuple(str(i) for i in range(1, 4)) + ("W", "L")
    for round_matches in bracket.values():
        for m in round_matches:
            for slot in (m["slot_a"], m["slot_b"]):
                if not slot.startswith(valid_prefixes):
                    raise ValueError(f"Slot invalido: {slot}")


def validate_third_place_mapping(third_place_mapping: dict) -> None:
    from itertools import combinations

    expected = {",".join(c) for c in combinations("ABCDEFGHIJKL", 8)}
    slots = {
        "3A/B/C/D/F",
        "3C/D/F/G/H",
        "3C/E/F/H/I",
        "3E/H/I/J/K",
        "3B/E/F/I/J",
        "3A/E/H/I/J",
        "3E/F/G/I/J",
        "3D/E/I/J/L",
    }
    keys = set(third_place_mapping)
    if keys != expected:
        raise ValueError(
            f"Mapeamento de terceiros incompleto: {len(keys)} entradas; esperado 495."
        )
    for key, mapping in third_place_mapping.items():
        if set(mapping) != slots:
            raise ValueError(f"Slots de terceiros incompletos para {key}.")
        groups = set(key.split(","))
        for value in mapping.values():
            if not isinstance(value, str) or len(value) != 2 or value[0] != "3" or value[1] not in groups:
                raise ValueError(f"Destino invalido de terceiro colocado em {key}: {value}")
