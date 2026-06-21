from __future__ import annotations

from typing import Any


DEFAULT_CONFIDENCE = {
    "fifa_official": 1.0,
    "openfootball_json": 0.82,
    "wikipedia": 0.75,
    "news_crosscheck": 0.86,
}


def source_confidence(source_name: str, source_config: dict[str, Any] | None = None) -> float:
    if source_config and "confidence" in source_config:
        return float(source_config["confidence"])
    return DEFAULT_CONFIDENCE.get(source_name, 0.5)


def confidence_label(sources: set[str], score_agreements: int = 1, conflict: bool = False) -> str:
    if conflict:
        return "conflict"
    if "fifa_official" in sources and score_agreements >= 2:
        return "high"
    if "fifa_official" in sources:
        return "high"
    medium_sources = sources & {"openfootball_json", "wikipedia", "news_crosscheck"}
    if len(medium_sources) >= 2 and score_agreements >= 2:
        return "medium_high"
    if sources == {"wikipedia"}:
        return "medium"
    if sources:
        return "medium"
    return "local_only"
