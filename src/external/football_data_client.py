from __future__ import annotations

import os

from .base_client import NoopExternalDataClient, UnsupportedDataTypeError


class FootballDataClient(NoopExternalDataClient):
    source_name = "football_data"

    def __init__(self, base_url: str | None = None, api_key_env: str = "FOOTBALL_DATA_API_KEY") -> None:
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.api_key = os.getenv(api_key_env)

    def fetch_matches(self) -> list[dict]:
        if not self.base_url or not self.api_key:
            raise UnsupportedDataTypeError("Football-data sem base_url ou API key configurada.")
        raise UnsupportedDataTypeError("Implementar parser especifico do provider antes de habilitar escrita.")

