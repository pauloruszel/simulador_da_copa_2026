from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)

    def read(self, path: str | Path, default: Any = None) -> Any:
        target = self.root / path
        if not target.exists():
            return default
        with target.open(encoding="utf-8") as f:
            return json.load(f)

    def write(self, path: str | Path, data: Any) -> Path:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return target
