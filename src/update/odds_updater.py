from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .validation import validate_odds_record


def normalize_odds(records: list[dict[str, Any]], source: str) -> dict[str, Any]:
    for record in records:
        validate_odds_record(record)
    return {
        "source": source,
        "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "matches": records,
    }

