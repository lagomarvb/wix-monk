from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wix_monk.domain.filtering import FilterExpression


class Consent(str, Enum):
    """Normalized consent classification used by the sync planner."""

    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class MembershipStatus(str, Enum):
    """Listmonk membership state for a subscriber/list pair."""

    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    UNSUBSCRIBED = "unsubscribed"


@dataclass(frozen=True)
class WixContact:
    """Normalized Wix contact data used by filtering and synchronization."""

    id: str
    email: str
    name: str
    subscription_status: str
    deliverability_status: str
    has_active_pricing_plan: bool
    is_member: bool = False
    member_status: str = ""
    active_plan_names: tuple[str, ...] = ()
    active_plan_ids: tuple[str, ...] = ()
    contact_ids: tuple[str, ...] = ()
    member_ids: tuple[str, ...] = ()
    phone_numbers: tuple[str, ...] = ()
    address_lines: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    postal_codes: tuple[str, ...] = ()
    subdivisions: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    addresses: tuple[dict[str, str], ...] = ()
    label_keys: tuple[str, ...] = ()
    segment_ids: tuple[str, ...] = ()
    locales: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListmonkSubscriber:
    """Normalized Listmonk subscriber record."""

    id: int
    email: str
    name: str
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)
    memberships: dict[int, MembershipStatus] = field(default_factory=dict)


@dataclass(frozen=True)
class ManagedList:
    """A configured Listmonk list with its effective filter and consent policy."""

    id: int
    name: str
    criteria: "FilterExpression"
    subscribed_statuses: frozenset[str] | None = None
    unsubscribed_statuses: frozenset[str] | None = None


@dataclass(frozen=True)
class ContactPlan:
    """Planned Listmonk changes for a single normalized Wix contact."""

    contact: WixContact
    subscriber: ListmonkSubscriber | None
    add: frozenset[int] = frozenset()
    remove: frozenset[int] = frozenset()
    unsubscribe: frozenset[int] = frozenset()
    preserved_unsubscribes: frozenset[int] = frozenset()
    skipped_global_suppression: bool = False
