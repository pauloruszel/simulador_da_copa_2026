from __future__ import annotations


def blend_probabilities(model_probability: float, market_probability: float, market_weight: float = 0.5) -> float:
    if not 0 <= model_probability <= 1 or not 0 <= market_probability <= 1:
        raise ValueError("Probabilidades devem ficar entre 0 e 1.")
    if not 0 <= market_weight <= 1:
        raise ValueError("market_weight deve ficar entre 0 e 1.")
    return model_probability * (1 - market_weight) + market_probability * market_weight

