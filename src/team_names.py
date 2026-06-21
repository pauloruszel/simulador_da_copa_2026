from __future__ import annotations

import json
import unicodedata
from pathlib import Path


def normalize_team_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_value.lower().replace("-", " ").split())


def load_team_aliases(path: str | Path = "data/team_aliases.json") -> dict[str, str]:
    with Path(path).open(encoding="utf-8") as f:
        aliases = json.load(f)
    index: dict[str, str] = {}
    for canonical, values in aliases.items():
        index[normalize_team_key(canonical)] = canonical
        for value in values:
            index[normalize_team_key(value)] = canonical
    return index


def resolve_team_name(value: str, aliases: dict[str, str] | None = None) -> str:
    aliases = aliases or load_team_aliases()
    key = normalize_team_key(value)
    if key not in aliases:
        raise ValueError(f"Selecao desconhecida: {value}")
    return aliases[key]

