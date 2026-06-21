from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UnsupportedDataTypeError(Exception):
    pass


class ExternalDataClient(ABC):
    source_name = "external"

    @abstractmethod
    def fetch_matches(self) -> list[dict[str, Any]]:
        raise UnsupportedDataTypeError

    @abstractmethod
    def fetch_groups(self) -> dict[str, list[str]]:
        raise UnsupportedDataTypeError

    @abstractmethod
    def fetch_rankings(self) -> dict[str, Any]:
        raise UnsupportedDataTypeError

    @abstractmethod
    def fetch_odds(self) -> list[dict[str, Any]]:
        raise UnsupportedDataTypeError


class NoopExternalDataClient(ExternalDataClient):
    def fetch_matches(self) -> list[dict[str, Any]]:
        raise UnsupportedDataTypeError("Fonte nao configurada para partidas.")

    def fetch_groups(self) -> dict[str, list[str]]:
        raise UnsupportedDataTypeError("Fonte nao configurada para grupos.")

    def fetch_rankings(self) -> dict[str, Any]:
        raise UnsupportedDataTypeError("Fonte nao configurada para rankings.")

    def fetch_odds(self) -> list[dict[str, Any]]:
        raise UnsupportedDataTypeError("Fonte nao configurada para odds.")

