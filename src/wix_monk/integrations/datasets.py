from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wix_monk.integrations.adapters import adapt_listmonk_subscriber, adapt_wix_contacts
from wix_monk.integrations.ports import ListmonkGateway, WixGateway
from wix_monk.discovery.calculations import (
    DEFAULT_DISCOVERY_FIELDS,
    contact_summary,
    discovery_values,
    duplicate_audit,
    pricing_plan_rows,
    query_contacts,
)
from wix_monk.domain.models import ListmonkSubscriber, WixContact


@dataclass(frozen=True)
class WixDataset:
    """Raw and normalized Wix records loaded from a gateway."""

    raw_contacts: tuple[dict[str, Any], ...]
    raw_orders: tuple[dict[str, Any], ...]
    raw_members: tuple[dict[str, Any], ...]
    contacts: tuple[WixContact, ...]

    @classmethod
    def load(cls, gateway: WixGateway) -> WixDataset:
        raw_contacts = tuple(gateway.contacts())
        raw_orders = tuple(gateway.orders())
        raw_members = tuple(gateway.members())
        contacts = tuple(adapt_wix_contacts(raw_contacts, raw_orders, raw_members))
        return cls(raw_contacts, raw_orders, raw_members, contacts)


class NormalizedWixData:
    """Convenience wrapper around Wix records used by discovery and sync."""

    def __init__(self, dataset: WixDataset) -> None:
        self.dataset = dataset

    @classmethod
    def load(cls, gateway: WixGateway) -> NormalizedWixData:
        return cls(WixDataset.load(gateway))

    @property
    def contacts(self) -> tuple[WixContact, ...]:
        return self.dataset.contacts

    @property
    def raw_contacts(self) -> tuple[dict[str, Any], ...]:
        return self.dataset.raw_contacts

    @property
    def raw_orders(self) -> tuple[dict[str, Any], ...]:
        return self.dataset.raw_orders

    @property
    def raw_members(self) -> tuple[dict[str, Any], ...]:
        return self.dataset.raw_members

    def values(
            self,
            fields: tuple[str, ...] = DEFAULT_DISCOVERY_FIELDS,
    ) -> dict[str, list[dict[str, Any]]]:
        return discovery_values(self.contacts, fields)

    def plans(self) -> list[dict[str, Any]]:
        return pricing_plan_rows(self.raw_orders)

    def query(self, criteria: Any) -> list[WixContact]:
        return query_contacts(self.contacts, criteria)

    def summary(self, contacts: list[WixContact]) -> dict[str, Any]:
        return contact_summary(contacts)

    def duplicates(self) -> dict[str, Any]:
        return duplicate_audit(self.raw_contacts, self.raw_members)


class NormalizedListmonkData:
    """Convenience wrapper around Listmonk records used by sync."""

    def __init__(
            self,
            subscribers: tuple[ListmonkSubscriber, ...],
            lists: tuple[dict[str, Any], ...],
    ) -> None:
        self.subscribers = subscribers
        self.lists = lists

    @classmethod
    def load(
            cls,
            gateway: ListmonkGateway,
    ) -> NormalizedListmonkData:
        subscribers = tuple(adapt_listmonk_subscriber(item) for item in gateway.subscribers())
        lists = tuple(gateway.lists())
        return cls(subscribers, lists)

    def subscribers_by_email(self) -> dict[str, ListmonkSubscriber]:
        return {subscriber.email: subscriber for subscriber in self.subscribers}

    def list_ids_by_name(self) -> dict[str, int]:
        return {item["name"]: int(item["id"]) for item in self.lists}
