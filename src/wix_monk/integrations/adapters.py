from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from wix_monk.domain.models import ListmonkSubscriber, MembershipStatus, WixContact

ACTIVE_ORDER_STATUSES = {"ACTIVE"}
INACTIVE_ORDER_STATUSES = {"DRAFT", "PENDING", "PAUSED", "ENDED", "UNDEFINED"}
ACTIVE_MEMBER_STATUSES = {"APPROVED"}
DENIED_SUBSCRIPTION_STATUSES = {"UNSUBSCRIBED"}
ALLOWED_SUBSCRIPTION_STATUSES = {"SUBSCRIBED"}
DELIVERABILITY_PRIORITY = {
    "SPAM_COMPLAINT": 4,
    "INACTIVE": 3,
    "BOUNCED": 2,
    "VALID": 1,
    "": 0,
}


def _nested(value: dict[str, Any], *keys: str, default: Any = "") -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _first(order: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        value = _nested(order, *path, default=None)
        if value is not None and value != "":
            return value
    return ""


def order_status(order: dict[str, Any]) -> str:
    """Return the normalized Wix order status."""

    value = _first(
        order,
        (("status",), ("statusNew",), ("orderStatus",)),
    )
    if isinstance(value, dict):
        value = value.get("status") or value.get("value") or value.get("state") or ""
    return str(value).strip().upper()


def order_contact_id(order: dict[str, Any]) -> str:
    return str(
        _first(
            order,
            (
                ("buyer", "contactId"),
                ("buyer", "contact", "id"),
                ("contactId",),
            ),
        )
    ).strip()


def order_member_id(order: dict[str, Any]) -> str:
    return str(
        _first(
            order,
            (
                ("buyer", "memberId"),
                ("buyer", "member", "id"),
                ("memberId",),
            ),
        )
    ).strip()


def order_email(order: dict[str, Any]) -> str:
    return str(
        _first(
            order,
            (
                ("buyer", "email"),
                ("buyer", "loginEmail"),
                ("email",),
            ),
        )
    ).strip().lower()


def order_end_date(order: dict[str, Any]) -> datetime | None:
    value = _first(
        order,
        (
            ("endDate",),
            ("currentCycle", "endedDate"),
            ("currentCycle", "endDate"),
            ("validUntil",),
        ),
    )
    text = str(value or "").replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def order_is_active_term(
        order: dict[str, Any],
        now: datetime | None = None,
) -> bool:
    """Return whether a pricing-plan order is still active for sync."""

    status = order_status(order)
    if status in ACTIVE_ORDER_STATUSES:
        return True
    if status in INACTIVE_ORDER_STATUSES:
        return False
    if status != "CANCELED":
        return False

    cancellation_effective_at = str(
        _nested(order, "cancellation", "effectiveAt")
    ).strip().upper()
    cancellation_is_future = (
        cancellation_effective_at == "NEXT_PAYMENT_DATE"
        or order.get("autoRenewCanceled") is True
    )
    if not cancellation_is_future:
        return False

    end_date = order_end_date(order)
    if end_date is not None:
        now = now or datetime.now(timezone.utc)
        return end_date > now
    return False


def order_plan_name(order: dict[str, Any]) -> str:
    return str(
        _first(order, (("planName",), ("plan", "name"), ("planSnapshot", "name")))
    ).strip()


def order_plan_id(order: dict[str, Any]) -> str:
    return str(
        _first(order, (("planId",), ("plan", "id"), ("planSnapshot", "id")))
    ).strip()


def wix_email(contact: dict[str, Any]) -> str:
    """Return the best normalized email address for a Wix contact."""

    candidates = (
        _nested(contact, "primaryEmail", "email"),
        _nested(contact, "primaryInfo", "email"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()

    for item in _nested(contact, "info", "emails", "items", default=[]):
        if isinstance(item, dict) and item.get("email"):
            return str(item["email"]).strip().lower()
    return ""


def wix_name(contact: dict[str, Any]) -> str:
    """Return the best normalized display name for a Wix contact."""

    first = _nested(contact, "info", "name", "first") or _nested(
        contact, "primaryInfo", "name", "first"
    )
    last = _nested(contact, "info", "name", "last") or _nested(
        contact, "primaryInfo", "name", "last"
    )
    return f"{first} {last}".strip() or str(contact.get("displayName") or "").strip()


def member_email(member: dict[str, Any]) -> str:
    """Return the normalized login email for a Wix member."""

    return str(member.get("loginEmail") or "").strip().lower()


def member_name(member: dict[str, Any]) -> str:
    """Return the best normalized display name for a Wix member."""

    contact = member.get("contact") or {}
    first = str(contact.get("firstName") or "").strip()
    last = str(contact.get("lastName") or "").strip()
    if first or last:
        return f"{first} {last}".strip()

    profile = member.get("profile") or {}
    nickname = str(profile.get("nickname") or "").strip()
    if nickname:
        return nickname

    return str(member.get("loginEmail") or "").strip()


def _date_rank(value: Any) -> float:
    text = str(value or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0


def _member_status(member: dict[str, Any]) -> str:
    return str(member.get("status") or "").strip().upper()


def _contact_member_id(contact: dict[str, Any]) -> str:
    return str(contact.get("memberId") or "").strip()


def _item_values(container: Any) -> list[dict[str, Any]]:
    if isinstance(container, dict):
        container = container.get("items", [])
    if not isinstance(container, list):
        return []
    return [item for item in container if isinstance(item, dict)]


def _string_items(container: Any) -> list[str]:
    if isinstance(container, dict):
        container = container.get("items", [])
    if not isinstance(container, list):
        return []
    return [str(item).strip() for item in container if str(item).strip()]


def _merged_contact_details(contacts: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, set[str]] = {
        "phone_numbers": set(),
        "address_lines": set(),
        "cities": set(),
        "postal_codes": set(),
        "subdivisions": set(),
        "countries": set(),
        "label_keys": set(),
        "segment_ids": set(),
        "locales": set(),
        "source_types": set(),
    }
    addresses: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
    for contact in contacts:
        info = contact.get("info") or {}
        for phone in _item_values(info.get("phones")):
            value = phone.get("e164Phone") or phone.get("formattedPhone") or phone.get("phone")
            if value:
                values["phone_numbers"].add(str(value).strip())
        for item in _item_values(info.get("addresses")):
            address = item.get("address") or {}
            normalized_address = {
                "tag": str(item.get("tag") or "UNTAGGED").strip().upper(),
                "address_line": str(address.get("addressLine") or "").strip(),
                "formatted_address": str(
                    address.get("formattedAddress") or ""
                ).strip(),
                "city": str(address.get("city") or "").strip(),
                "postal_code": str(address.get("postalCode") or "").strip(),
                "subdivision": str(address.get("subdivision") or "").strip(),
                "country": str(address.get("country") or "").strip(),
            }
            key = tuple(sorted(normalized_address.items()))
            addresses[key] = normalized_address
            for field, key in (
                    ("address_lines", "addressLine"),
                    ("cities", "city"),
                    ("postal_codes", "postalCode"),
                    ("subdivisions", "subdivision"),
                    ("countries", "country"),
            ):
                value = address.get(key)
                if value:
                    values[field].add(str(value).strip())
        values["label_keys"].update(_string_items(info.get("labelKeys")))
        values["segment_ids"].update(_string_items(contact.get("segments")))
        locale = str(info.get("locale") or "").strip()
        if locale:
            values["locales"].add(locale)
        source_type = str(_nested(contact, "source", "sourceType") or "").strip()
        if source_type:
            values["source_types"].add(source_type)
    return {
        **{key: tuple(sorted(items)) for key, items in values.items()},
        "addresses": tuple(
            sorted(
                addresses.values(),
                key=lambda item: (
                    item["tag"],
                    item["postal_code"],
                    item["address_line"],
                ),
            )
        ),
    }


def _select_contact(
        contacts: list[dict[str, Any]],
        member_contact_ids: set[str],
        member_ids: set[str],
) -> dict[str, Any]:
    def rank(contact: dict[str, Any]) -> tuple[int, int, float, int]:
        contact_id = str(contact.get("id") or "")
        member_id = _contact_member_id(contact)
        return (
            int(contact_id in member_contact_ids),
            int(bool(member_id) and member_id in member_ids),
            _date_rank(contact.get("updatedDate")),
            int(contact.get("revision") or 0),
        )

    return max(contacts, key=rank)


def _merged_subscription_status(contacts: list[dict[str, Any]]) -> str:
    statuses = [
        str(_nested(contact, "primaryEmail", "subscriptionStatus")).strip().upper()
        for contact in contacts
    ]
    for status in statuses:
        if status in DENIED_SUBSCRIPTION_STATUSES:
            return status
    for status in statuses:
        if status in ALLOWED_SUBSCRIPTION_STATUSES:
            return status
    return next((status for status in statuses if status), "")


def _merged_deliverability_status(contacts: list[dict[str, Any]]) -> str:
    statuses = [
        str(_nested(contact, "primaryEmail", "deliverabilityStatus")).strip().upper()
        for contact in contacts
    ]
    return max(statuses, key=lambda value: DELIVERABILITY_PRIORITY.get(value, 1), default="")


def adapt_wix_contacts(
        contacts: Iterable[dict[str, Any]],
        orders: Iterable[dict[str, Any]],
        members: Iterable[dict[str, Any]] = (),
) -> list[WixContact]:
    """Merge raw Wix contacts, orders, and members into normalized contacts."""

    contacts_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for contact in contacts:
        email = wix_email(contact)
        if email:
            contacts_by_email[email].append(contact)

    members = list(members)
    members_by_id: dict[str, dict[str, Any]] = {}
    members_by_contact_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    members_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        member_id = str(member.get("id") or "").strip()
        if member_id:
            members_by_id[member_id] = member
        contact_id = str(member.get("contactId") or "").strip()
        if contact_id:
            members_by_contact_id[contact_id].append(member)
        email = member_email(member)
        if email:
            members_by_email[email].append(member)

    active_orders = [
        order
        for order in orders
        if order_is_active_term(order)
    ]
    result: list[WixContact] = []

    for email, email_contacts in contacts_by_email.items():
        contact_ids = {
            str(contact.get("id") or "").strip()
            for contact in email_contacts
            if contact.get("id")
        }
        linked_members: dict[str, dict[str, Any]] = {}
        for contact in email_contacts:
            member_id = _contact_member_id(contact)
            if member_id and member_id in members_by_id:
                linked_members[member_id] = members_by_id[member_id]
        for contact_id in contact_ids:
            for member in members_by_contact_id.get(contact_id, []):
                linked_members[str(member.get("id") or contact_id)] = member
        for member in members_by_email.get(email, []):
            linked_members[str(member.get("id") or email)] = member

        approved_members = [
            member
            for member in linked_members.values()
            if _member_status(member) in ACTIVE_MEMBER_STATUSES
        ]
        member_ids = {
            str(member.get("id") or "").strip()
            for member in linked_members.values()
            if member.get("id")
        }
        member_ids.update(
            member_id
            for member_id in (_contact_member_id(contact) for contact in email_contacts)
            if member_id
        )
        member_contact_ids = {
            str(member.get("contactId") or "").strip()
            for member in linked_members.values()
            if member.get("contactId")
        }
        primary = _select_contact(email_contacts, member_contact_ids, member_ids)

        matched_orders = [
            order
            for order in active_orders
            if order_contact_id(order) in contact_ids
               or order_member_id(order) in member_ids
               or order_email(order) == email
        ]
        active_plan_names = sorted(
            {
                order_plan_name(order)
                for order in matched_orders
                if order_plan_name(order)
            }
        )
        active_plan_ids = sorted(
            {
                order_plan_id(order)
                for order in matched_orders
                if order_plan_id(order)
            }
        )
        name = wix_name(primary)
        if approved_members:
            # Wix member contact names are the most accurate source for the
            # person's actual name, so prefer them over display strings.
            name = member_name(max(approved_members, key=lambda item: _date_rank(item.get("updatedDate")))) or name
        if not name:
            name = next((wix_name(contact) for contact in email_contacts if wix_name(contact)), "")

        subscription_status = _merged_subscription_status(email_contacts)
        deliverability_status = _merged_deliverability_status(email_contacts)
        details = _merged_contact_details(email_contacts)
        statuses = sorted({_member_status(member) for member in linked_members.values() if _member_status(member)})
        primary_contact_id = str(primary.get("id") or "")
        result.append(
            WixContact(
                id=primary_contact_id,
                email=email,
                name=name,
                subscription_status=subscription_status,
                deliverability_status=deliverability_status,
                has_active_pricing_plan=bool(matched_orders),
                is_member=bool(approved_members),
                member_status="APPROVED" if approved_members else (statuses[0] if statuses else ""),
                active_plan_names=tuple(active_plan_names),
                active_plan_ids=tuple(active_plan_ids),
                contact_ids=tuple(sorted(contact_ids)),
                member_ids=tuple(sorted(member_ids)),
                **details,
                attributes={
                    "source": "wix",
                    "wix_contact_id": primary_contact_id,
                    "wix_contact_ids": sorted(contact_ids),
                    "wix_duplicate_contact_count": len(email_contacts),
                    "wix_revision": primary.get("revision"),
                    "wix_created_date": primary.get("createdDate"),
                    "wix_updated_date": primary.get("updatedDate"),
                    "wix_email_subscription_status": subscription_status,
                    "wix_email_deliverability_status": deliverability_status,
                    "wix_is_member": bool(approved_members),
                    "wix_member_statuses": statuses,
                    "wix_member_ids": sorted(member_ids),
                    "wix_active_pricing_plan": bool(matched_orders),
                    "wix_active_plan_names": active_plan_names,
                    "wix_active_plan_ids": active_plan_ids,
                    "wix_phone_numbers": list(details["phone_numbers"]),
                    "wix_address_lines": list(details["address_lines"]),
                    "wix_cities": list(details["cities"]),
                    "wix_postal_codes": list(details["postal_codes"]),
                    "wix_subdivisions": list(details["subdivisions"]),
                    "wix_countries": list(details["countries"]),
                    "wix_addresses": list(details["addresses"]),
                    "wix_label_keys": list(details["label_keys"]),
                    "wix_segment_ids": list(details["segment_ids"]),
                    "wix_locales": list(details["locales"]),
                    "wix_source_types": list(details["source_types"]),
                },
            )
        )
    return result


def adapt_listmonk_subscriber(raw: dict[str, Any]) -> ListmonkSubscriber:
    """Normalize a raw Listmonk subscriber payload."""

    memberships: dict[int, MembershipStatus] = {}
    for item in raw.get("lists") or []:
        list_id = item.get("id") or item.get("list_id")
        status = item.get("subscription_status") or item.get("status")
        if list_id is None or status not in {item.value for item in MembershipStatus}:
            continue
        memberships[int(list_id)] = MembershipStatus(status)

    return ListmonkSubscriber(
        id=int(raw["id"]),
        email=str(raw["email"]).strip().lower(),
        name=str(raw.get("name") or ""),
        status=str(raw.get("status") or "enabled"),
        attributes=dict(raw.get("attribs") or {}),
        memberships=memberships,
    )
