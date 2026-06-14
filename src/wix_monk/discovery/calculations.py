from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from wix_monk.domain.filtering import (
    ADDRESS_FIELD_TYPES,
    FIELD_TYPES,
    OPERATORS_BY_TYPE,
    matches_filter,
)
from wix_monk.domain.models import WixContact
from wix_monk.integrations.adapters import (
    member_email,
    order_is_active_term,
    order_plan_id,
    order_plan_name,
    order_status,
    wix_email,
    wix_name,
)

DEFAULT_DISCOVERY_FIELDS = (
    "subscription_status",
    "deliverability_status",
    "is_member",
    "member_status",
    "active_pricing_plan",
    "active_plan_names",
    "active_plan_ids",
    "cities",
    "postal_codes",
    "subdivisions",
    "countries",
    "label_keys",
    "segment_ids",
    "locales",
    "source_types",
)
SENSITIVE_FIELDS = frozenset(
    {
        "email",
        "name",
        "contact_ids",
        "member_ids",
        "phone_numbers",
        "address_lines",
        "addresses",
    }
)


def schema_document() -> dict[str, Any]:
    """Return the criteria schema used by the discovery command."""

    fields = {
        field: {
            "type": field_type,
            "operators": sorted(OPERATORS_BY_TYPE[field_type]),
            "sensitive": field in SENSITIVE_FIELDS,
        }
        for field, field_type in FIELD_TYPES.items()
    }
    fields["addresses"]["item_fields"] = {
        field: {
            "type": field_type,
            "operators": sorted(OPERATORS_BY_TYPE[field_type]),
        }
        for field, field_type in ADDRESS_FIELD_TYPES.items()
    }
    return {
        "combinators": ["all", "any", "not"],
        "fields": fields,
    }


def field_value_counts(
        contacts: Iterable[WixContact],
        field: str,
) -> list[dict[str, Any]]:
    """Count observed values for one normalized contact field."""

    counts: Counter[Any] = Counter()
    for contact in contacts:
        value = _field_value(contact, field)
        if isinstance(value, tuple):
            counts.update(
                _display_value(item) for item in (value or ("<empty>",))
            )
        else:
            counts[value if value not in {None, ""} else "<empty>"] += 1
    return [
        {"value": value, "count": count}
        for value, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], str(item[0]).casefold()),
        )
    ]


def discovery_values(
        contacts: Iterable[WixContact],
        fields: Iterable[str] = DEFAULT_DISCOVERY_FIELDS,
) -> dict[str, list[dict[str, Any]]]:
    """Return discovery counts for the selected normalized fields."""

    contacts = list(contacts)
    return {field: field_value_counts(contacts, field) for field in fields}


def pricing_plan_rows(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize Wix pricing-plan orders by plan id and plan name."""

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for order in orders:
        plan_id = order_plan_id(order) or "<missing>"
        plan_name = order_plan_name(order) or "<missing>"
        key = (plan_id, plan_name)
        row = rows.setdefault(
            key,
            {
                "plan_id": plan_id,
                "plan_name": plan_name,
                "orders": 0,
                "active_term_orders": 0,
                "statuses": Counter(),
            },
        )
        row["orders"] += 1
        row["active_term_orders"] += order_is_active_term(order)
        row["statuses"][order_status(order) or "<missing>"] += 1

    result = []
    for row in rows.values():
        result.append(
            {
                **row,
                "statuses": dict(sorted(row["statuses"].items())),
                "criteria_by_id": {
                    "field": "active_plan_ids",
                    "contains": row["plan_id"],
                },
                "criteria_by_name": {
                    "field": "active_plan_names",
                    "contains": row["plan_name"],
                },
            }
        )
    return sorted(result, key=lambda row: (row["plan_name"].casefold(), row["plan_id"]))


def query_contacts(
        contacts: Iterable[WixContact],
        criteria: Any,
) -> list[WixContact]:
    """Filter normalized contacts with a criteria expression."""

    return [contact for contact in contacts if matches_filter(contact, criteria)]


def duplicate_audit(
        contacts: Iterable[dict[str, Any]],
        members: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Find duplicate and mismatched Wix contact/member records."""

    contacts = list(contacts)
    members = list(members)
    contacts_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    contacts_by_id: dict[str, dict[str, Any]] = {}
    for contact in contacts:
        contact_id = str(contact.get("id") or "").strip()
        if contact_id:
            contacts_by_id[contact_id] = contact
        email = wix_email(contact)
        if email:
            contacts_by_email[email].append(contact)

    members_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        email = member_email(member)
        if email:
            members_by_email[email].append(member)

    contact_email_duplicates = [
        {
            "email": email,
            "contacts": [_raw_contact_row(contact) for contact in rows],
        }
        for email, rows in sorted(contacts_by_email.items())
        if len(rows) > 1
    ]
    member_email_duplicates = [
        {
            "email": email,
            "members": [_raw_member_row(member) for member in rows],
        }
        for email, rows in sorted(members_by_email.items())
        if len(rows) > 1
    ]

    member_contact_email_mismatches = []
    email_only_member_links = []
    members_without_contacts = []
    for member in members:
        member_row = _raw_member_row(member)
        email = member_email(member)
        contact_id = str(member.get("contactId") or "").strip()
        linked_contact = contacts_by_id.get(contact_id)
        if linked_contact is not None:
            contact_email = wix_email(linked_contact)
            if email and contact_email and email != contact_email:
                member_contact_email_mismatches.append(
                    {
                        "member": member_row,
                        "contact": _raw_contact_row(linked_contact),
                    }
                )
            continue
        if email and email in contacts_by_email:
            email_only_member_links.append(
                {
                    "member": member_row,
                    "contacts": [
                        _raw_contact_row(contact)
                        for contact in contacts_by_email[email]
                    ],
                }
            )
        else:
            members_without_contacts.append(member_row)

    return {
        "summary": {
            "raw_contacts": len(contacts),
            "unique_contact_emails": len(contacts_by_email),
            "contacts_without_email": sum(
                not wix_email(contact) for contact in contacts
            ),
            "duplicate_contact_email_groups": len(contact_email_duplicates),
            "duplicate_contact_rows": sum(
                len(group["contacts"]) - 1 for group in contact_email_duplicates
            ),
            "raw_members": len(members),
            "unique_member_emails": len(members_by_email),
            "members_without_email": sum(
                not member_email(member) for member in members
            ),
            "duplicate_member_email_groups": len(member_email_duplicates),
            "member_contact_email_mismatches": len(member_contact_email_mismatches),
            "email_only_member_links": len(email_only_member_links),
            "members_without_contacts": len(members_without_contacts),
        },
        "contact_email_duplicates": contact_email_duplicates,
        "member_email_duplicates": member_email_duplicates,
        "member_contact_email_mismatches": member_contact_email_mismatches,
        "email_only_member_links": email_only_member_links,
        "members_without_contacts": members_without_contacts,
    }


def contact_summary(contacts: Iterable[WixContact]) -> dict[str, Any]:
    """Build a summary of normalized contact records."""

    contacts = list(contacts)
    return {
        "contacts": len(contacts),
        "subscription_statuses": _counter(
            contact.subscription_status or "<empty>" for contact in contacts
        ),
        "deliverability_statuses": _counter(
            contact.deliverability_status or "<empty>" for contact in contacts
        ),
        "members": sum(contact.is_member for contact in contacts),
        "active_pricing_plan": sum(
            contact.has_active_pricing_plan for contact in contacts
        ),
        "active_plan_names": _counter(
            name for contact in contacts for name in contact.active_plan_names
        ),
    }


def contact_row(contact: WixContact) -> dict[str, Any]:
    """Convert a normalized contact into a JSON-friendly row."""

    return {
        "email": contact.email,
        "name": contact.name,
        "subscription_status": contact.subscription_status,
        "deliverability_status": contact.deliverability_status,
        "is_member": contact.is_member,
        "member_status": contact.member_status,
        "active_pricing_plan": contact.has_active_pricing_plan,
        "active_plan_names": list(contact.active_plan_names),
        "active_plan_ids": list(contact.active_plan_ids),
        "contact_ids": list(contact.contact_ids),
        "member_ids": list(contact.member_ids),
        "phone_numbers": list(contact.phone_numbers),
        "address_lines": list(contact.address_lines),
        "cities": list(contact.cities),
        "postal_codes": list(contact.postal_codes),
        "subdivisions": list(contact.subdivisions),
        "countries": list(contact.countries),
        "addresses": list(contact.addresses),
        "label_keys": list(contact.label_keys),
        "segment_ids": list(contact.segment_ids),
        "locales": list(contact.locales),
        "source_types": list(contact.source_types),
        "listmonk_attributes": contact.attributes,
    }


def _field_value(contact: WixContact, field: str) -> Any:
    if field == "active_pricing_plan":
        return contact.has_active_pricing_plan
    return getattr(contact, field)


def _counter(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _display_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True)
    return value


def _raw_contact_row(contact: dict[str, Any]) -> dict[str, Any]:
    return {
        "contact_id": str(contact.get("id") or ""),
        "email": wix_email(contact),
        "name": wix_name(contact),
        "member_id": str(contact.get("memberId") or ""),
        "subscription_status": str(
            ((contact.get("primaryEmail") or {}).get("subscriptionStatus") or "")
        ),
        "source_type": str(((contact.get("source") or {}).get("sourceType") or "")),
        "created_date": contact.get("createdDate"),
        "updated_date": contact.get("updatedDate"),
    }


def _raw_member_row(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "member_id": str(member.get("id") or ""),
        "contact_id": str(member.get("contactId") or ""),
        "login_email": member_email(member),
        "status": str(member.get("status") or ""),
        "created_date": member.get("createdDate"),
        "updated_date": member.get("updatedDate"),
    }
