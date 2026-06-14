from __future__ import annotations

from dataclasses import dataclass

from wix_monk.integrations.clients import ListmonkClient, WixClient
from wix_monk.integrations.datasets import NormalizedListmonkData, NormalizedWixData


@dataclass
class WixService:
    """Lazy loader for normalized Wix data."""

    client: WixClient
    _data: NormalizedWixData | None = None

    def data(self) -> NormalizedWixData:
        if self._data is None:
            self._data = NormalizedWixData.load(self.client)
        return self._data


@dataclass
class ListmonkService:
    """Lazy loader for normalized Listmonk data."""

    client: ListmonkClient
    _data: NormalizedListmonkData | None = None

    def data(self) -> NormalizedListmonkData:
        if self._data is None:
            self._data = NormalizedListmonkData.load(self.client)
        return self._data
