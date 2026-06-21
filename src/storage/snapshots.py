from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .json_store import JsonStore


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def create_data_snapshot(paths: Iterable[str], snapshot_dir: str | Path = "data/snapshots") -> list[Path]:
    store = JsonStore()
    out_dir = Path(snapshot_dir) / utc_stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in paths:
        data = store.read(path)
        if data is not None:
            written.append(store.write(out_dir / Path(path).name, data))
    return written

