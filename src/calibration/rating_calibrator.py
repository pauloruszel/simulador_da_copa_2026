from __future__ import annotations


def blend_ratings(base: dict[str, int], external: dict[str, int], weight: float = 0.35) -> dict[str, int]:
    if not 0 <= weight <= 1:
        raise ValueError("weight deve ficar entre 0 e 1.")
    out = dict(base)
    for team, rating in external.items():
        if team in out:
            out[team] = round(out[team] * (1 - weight) + rating * weight)
        else:
            out[team] = rating
    return out

