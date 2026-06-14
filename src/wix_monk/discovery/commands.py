from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TextIO

from wix_monk.discovery.calculations import (
    DEFAULT_DISCOVERY_FIELDS,
    SENSITIVE_FIELDS,
    contact_row,
    schema_document,
)
from wix_monk.domain.filtering import FilterConfigError, FilterExpression, validate_criteria
from wix_monk.integrations.datasets import NormalizedWixData


class DiscoveryCommands:
    """Render discovery outputs from normalized Wix data."""

    def __init__(
            self,
            stdout: TextIO,
            stderr: TextIO,
            logger: logging.Logger,
            catalog: NormalizedWixData,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.logger = logger
        self.catalog = catalog

    def schema(self, as_json: bool) -> None:
        """Render the filter schema as text or JSON."""

        self.logger.debug("Rendering schema view")
        document = schema_document()
        if as_json:
            self._json(document)
            return
        self._line("Combinators: all, any, not")
        self._line("Fields:")
        for field, details in document["fields"].items():
            sensitive = " [sensitive]" if details["sensitive"] else ""
            self._line(
                f"  {field} ({details['type']}){sensitive}: "
                + ", ".join(details["operators"])
            )
            if "item_fields" in details:
                self._line("    item fields: " + ", ".join(details["item_fields"]))

    def values(self, field: str | None, as_json: bool) -> None:
        """Render observed field values as text or JSON."""

        catalog = self._catalog()
        fields = (field,) if field else DEFAULT_DISCOVERY_FIELDS
        self.logger.debug("Rendering values for fields: %s", fields)
        values = catalog.values(fields)
        if as_json:
            self._json(values)
            return
        if field in SENSITIVE_FIELDS:
            self._line(f"Warning: {field} contains contact-identifying data.")
        for field_name, rows in values.items():
            self._line(f"{field_name}:")
            for row in rows:
                self._line(f"  {row['value']}: {row['count']}")

    def plans(self, as_json: bool) -> None:
        """Render observed pricing-plan orders as text or JSON."""

        self.logger.debug("Rendering pricing plan summary")
        rows = self._catalog().plans()
        if as_json:
            self._json(rows)
            return
        self._line("Pricing plans observed in Wix orders:")
        for row in rows:
            statuses = ", ".join(
                f"{status}={count}" for status, count in row["statuses"].items()
            )
            self._line(f"  {row['plan_name']}")
            self._line(f"    id={row['plan_id']}")
            self._line(
                f"    orders={row['orders']}, "
                f"active_term_orders={row['active_term_orders']}, statuses={statuses}"
            )
            self._line("    criteria_by_id=" + _compact_json(row["criteria_by_id"]))
            self._line(
                "    criteria_by_name=" + _compact_json(row["criteria_by_name"])
            )

    def snapshot(self, as_json: bool, include_contacts: bool) -> None:
        """Render a combined discovery snapshot."""

        catalog = self._catalog()
        self.logger.debug("Rendering snapshot include_contacts=%s", include_contacts)
        snapshot: dict[str, Any] = {
            "schema": schema_document(),
            "observed_values": catalog.values(),
            "pricing_plans_observed_in_orders": catalog.plans(),
        }
        if include_contacts:
            snapshot["contacts"] = [contact_row(contact) for contact in catalog.contacts]
            print("WARNING: output includes personal contact data.", file=self.stderr)
        if as_json:
            self._json(snapshot)
            return
        self.schema(False)
        self._line()
        self._line("Observed values:")
        for field, rows in snapshot["observed_values"].items():
            self._line(f"  {field}:")
            for row in rows:
                self._line(f"    {row['value']}: {row['count']}")
        self._line()
        self._line("Pricing plans observed in Wix orders:")
        for row in snapshot["pricing_plans_observed_in_orders"]:
            self._line(
                f"  {row['plan_name']} | id={row['plan_id']} | "
                f"orders={row['orders']} | "
                f"active_term_orders={row['active_term_orders']}"
            )
            self._line("    " + _compact_json(row["criteria_by_name"]))

    def members(self, as_json: bool, show_contacts: bool, limit: int) -> None:
        """Render the member-only query."""

        self.query(
            {"field": "is_member", "equals": True},
            as_json,
            show_contacts,
            limit,
        )

    def query(
            self,
            criteria: Any,
            as_json: bool,
            show_contacts: bool,
            limit: int,
    ) -> None:
        """Render contacts that match a criteria expression."""

        if limit < 0:
            raise ValueError("limit must be zero or greater")
        catalog = self._catalog()
        self.logger.debug(
            "Running query with criteria=%s show_contacts=%s limit=%s",
            criteria.describe() if hasattr(criteria, "describe") else criteria,
            show_contacts,
            limit,
        )
        matches = catalog.query(criteria)
        output: dict[str, Any] = {
            "criteria": criteria.to_mapping() if hasattr(criteria, "to_mapping") else criteria,
            "summary": catalog.summary(matches),
        }
        if show_contacts:
            output["contacts"] = [contact_row(contact) for contact in matches[:limit]]
            output["contacts_shown"] = min(len(matches), limit)
        if as_json:
            self._json(output)
            return
        self._line(f"Matched contacts: {output['summary']['contacts']}")
        for key, value in output["summary"].items():
            if key != "contacts":
                self._line(f"  {key}: {value}")
        if show_contacts:
            self._line(f"Contacts shown: {output['contacts_shown']}")
            for contact in output["contacts"]:
                self._line(
                    f"  {contact['email']} | {contact['name']} | "
                    f"consent={contact['subscription_status']} | "
                    f"member={contact['is_member']} | "
                    f"plans={', '.join(contact['active_plan_names']) or '<none>'}"
                )

    def duplicates(self, as_json: bool, show_records: bool) -> None:
        """Render duplicate and mismatch diagnostics."""

        self.logger.debug("Rendering duplicate audit show_records=%s", show_records)
        audit = self._catalog().duplicates()
        output = audit if show_records else {"summary": audit["summary"]}
        if show_records:
            print(
                "WARNING: output includes personal contact data and Wix record IDs.",
                file=self.stderr,
            )
        if as_json:
            self._json(output)
            return
        self._line("Duplicate and member/contact audit:")
        for key, value in audit["summary"].items():
            self._line(f"  {key}: {value}")
        if not show_records:
            self._line("Use --show-records to display the records behind any issues.")
            return
        for section in (
                "contact_email_duplicates",
                "member_email_duplicates",
                "member_contact_email_mismatches",
                "email_only_member_links",
                "members_without_contacts",
        ):
            self._line(f"{section}:")
            rows = audit[section]
            if not rows:
                self._line("  <none>")
                continue
            for row in rows:
                self._line("  " + json.dumps(row, sort_keys=True))

    def _json(self, value: Any) -> None:
        print(json.dumps(value, indent=2, sort_keys=True), file=self.stdout)

    def _line(self, value: str = "") -> None:
        print(value, file=self.stdout)

    def _catalog(self) -> NormalizedWixData:
        return self.catalog


def load_criteria(raw: str | None, path: Path | None) -> FilterExpression:
    """Load a criteria expression from inline JSON or a file."""

    try:
        criteria = json.loads(raw) if raw is not None else _load_json(path)
        criteria = validate_criteria(criteria)
    except (json.JSONDecodeError, OSError, FilterConfigError) as error:
        raise ValueError(str(error)) from error
    return criteria


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError("criteria file is required")
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
