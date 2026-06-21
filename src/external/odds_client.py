from __future__ import annotations

import os

from .base_client import NoopExternalDataClient, UnsupportedDataTypeError


class OddsClient(NoopExternalDataClient):
    source_name = "odds"

    def __init__(self, base_url: str | None = None, api_key_env: str = "ODDS_API_KEY") -> None:
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.api_key = os.getenv(api_key_env)

    def fetch_odds(self) -> list[dict]:
        if not self.base_url or not self.api_key:
            raise UnsupportedDataTypeError("Odds provider sem base_url ou API key configurada.")
        raise UnsupportedDataTypeError("Implementar normalizacao do provider de odds antes de habilitar escrita.")

