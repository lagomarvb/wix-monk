import unittest
from typing import Any

from wix_monk.discovery import (
    contact_summary,
    discovery_values,
    duplicate_audit,
    field_value_counts,
    pricing_plan_rows,
    query_contacts,
    schema_document,
)
from wix_monk.domain.models import WixContact


def contact(**overrides: Any) -> WixContact:
    values = {
        "id": "contact-1",
        "email": "member@example.com",
        "name": "Member",
        "subscription_status": "NOT_SET",
        "deliverability_status": "VALID",
        "has_active_pricing_plan": True,
        "is_member": True,
        "member_status": "APPROVED",
        "active_plan_names": ("Annual plan",),
        "active_plan_ids": ("plan-1",),
        "postal_codes": ("23456",),
        "label_keys": ("custom.neighborhood",),
    }
    values.update(overrides)
    return WixContact(**values)


class DiscoveryTests(unittest.TestCase):
    def test_schema_lists_field_type_and_operators(self):
        schema = schema_document()

        self.assertEqual(schema["fields"]["active_plan_names"]["type"], "text_array")
        self.assertIn(
            "contains_regex",
            schema["fields"]["active_plan_names"]["operators"],
        )
        self.assertTrue(schema["fields"]["email"]["sensitive"])
        self.assertEqual(schema["fields"]["addresses"]["type"], "object_array")
        self.assertIn("any_match", schema["fields"]["addresses"]["operators"])
        self.assertIn("postal_code", schema["fields"]["addresses"]["item_fields"])

    def test_array_value_counts_are_flattened(self):
        rows = field_value_counts(
            [
                contact(active_plan_names=("Annual plan", "Board plan")),
                contact(active_plan_names=("Annual plan",)),
            ],
            "active_plan_names",
        )

        self.assertEqual(
            rows,
            [
                {"value": "Annual plan", "count": 2},
                {"value": "Board plan", "count": 1},
            ],
        )

    def test_default_discovery_does_not_include_pii_fields(self):
        values = discovery_values([contact()])

        self.assertNotIn("email", values)
        self.assertNotIn("name", values)
        self.assertIn("subscription_status", values)
        self.assertIn("postal_codes", values)
        self.assertNotIn("phone_numbers", values)

    def test_pricing_plans_pair_ids_names_and_status_counts(self):
        rows = pricing_plan_rows(
            [
                {
                    "status": "ACTIVE",
                    "planId": "plan-1",
                    "planName": "Annual plan",
                },
                {
                    "status": "ENDED",
                    "planId": "plan-1",
                    "planName": "Annual plan",
                },
            ]
        )

        self.assertEqual(rows[0]["plan_id"], "plan-1")
        self.assertEqual(rows[0]["orders"], 2)
        self.assertEqual(rows[0]["active_term_orders"], 1)
        self.assertEqual(rows[0]["statuses"], {"ACTIVE": 1, "ENDED": 1})
        self.assertEqual(
            rows[0]["criteria_by_name"],
            {"field": "active_plan_names", "contains": "Annual plan"},
        )

    def test_query_uses_the_filter_engine(self):
        contacts = [contact(), contact(is_member=False, email="other@example.com")]

        matches = query_contacts(
            contacts,
            {"field": "is_member", "equals": True},
        )

        self.assertEqual([item.email for item in matches], ["member@example.com"])
        self.assertEqual(contact_summary(matches)["contacts"], 1)

    def test_duplicate_audit_groups_normalized_contact_emails(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {"email": "Person@example.com"},
            },
            {
                "id": "contact-2",
                "primaryEmail": {"email": "person@example.com"},
            },
        ]

        audit = duplicate_audit(contacts, [])

        self.assertEqual(audit["summary"]["duplicate_contact_email_groups"], 1)
        self.assertEqual(audit["summary"]["duplicate_contact_rows"], 1)
        self.assertEqual(
            [row["contact_id"] for row in audit["contact_email_duplicates"][0]["contacts"]],
            ["contact-1", "contact-2"],
        )

    def test_duplicate_audit_finds_email_only_member_link(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {"email": "person@example.com"},
            }
        ]
        members = [
            {
                "id": "member-1",
                "contactId": "missing-contact",
                "loginEmail": "person@example.com",
            }
        ]

        audit = duplicate_audit(contacts, members)

        self.assertEqual(audit["summary"]["email_only_member_links"], 1)

    def test_duplicate_audit_finds_member_contact_email_mismatch(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {"email": "contact@example.com"},
            }
        ]
        members = [
            {
                "id": "member-1",
                "contactId": "contact-1",
                "loginEmail": "member@example.com",
            }
        ]

        audit = duplicate_audit(contacts, members)

        self.assertEqual(audit["summary"]["member_contact_email_mismatches"], 1)


if __name__ == "__main__":
    unittest.main()
