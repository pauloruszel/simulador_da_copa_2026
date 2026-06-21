from __future__ import annotations

from .base_client import NoopExternalDataClient, UnsupportedDataTypeError


class FifaClient(NoopExternalDataClient):
    source_name = "fifa"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "https://www.fifa.com"

    def fetch_matches(self) -> list[dict]:
        raise UnsupportedDataTypeError(
            "Cliente FIFA oficial ainda nao possui endpoint publico estavel configurado."
        )

    def fetch_groups(self) -> dict[str, list[str]]:
        raise UnsupportedDataTypeError(
            "Cliente FIFA oficial ainda nao possui endpoint publico estavel configurado."
        )

    def fetch_rankings(self) -> dict:
        raise UnsupportedDataTypeError(
            "Cliente FIFA oficial ainda nao possui endpoint publico estavel configurado."
        )

