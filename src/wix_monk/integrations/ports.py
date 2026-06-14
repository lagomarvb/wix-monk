from __future__ import annotations

from typing import Any, Protocol


class WixGateway(Protocol):
    """Minimal Wix API surface needed by the loader."""

    def contacts(self) -> list[dict[str, Any]]: ...

    def orders(self) -> list[dict[str, Any]]: ...

    def members(self) -> list[dict[str, Any]]: ...


class ListmonkGateway(Protocol):
    """Minimal Listmonk API surface needed by the loader and sync service."""

    def lists(self) -> list[dict[str, Any]]: ...

    def create_list(
            self,
            name: str,
            *,
            list_type: str,
            optin: str,
            description: str,
            tags: list[str],
    ) -> int: ...

    def subscribers(self) -> list[dict[str, Any]]: ...

    def create_subscriber(
            self,
            email: str,
            name: str,
            attributes: dict[str, Any],
    ) -> int: ...

    def update_subscriber(
            self,
            subscriber_id: int,
            email: str,
            name: str,
            status: str,
            attributes: dict[str, Any],
    ) -> None: ...

    def change_lists(
            self,
            subscriber_ids: list[int],
            list_ids: list[int],
            action: str,
            status: str | None = None,
    ) -> None: ...
