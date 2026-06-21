from __future__ import annotations

from .base_client import NoopExternalDataClient, UnsupportedDataTypeError


class RankingClient(NoopExternalDataClient):
    source_name = "ranking"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url

    def fetch_rankings(self) -> dict:
        raise UnsupportedDataTypeError("Ranking provider ainda nao configurado.")

