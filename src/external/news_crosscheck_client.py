from __future__ import annotations

from .base_client import NoopExternalDataClient, UnsupportedDataTypeError


class NewsCrosscheckClient(NoopExternalDataClient):
    source_name = "news_crosscheck"

    def fetch_matches(self):
        raise UnsupportedDataTypeError("News crosscheck ainda nao configurado.")
