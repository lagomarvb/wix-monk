import unittest
from datetime import datetime, timezone

from wix_monk.integrations.adapters import adapt_wix_contacts, order_is_active_term


class WixContactAdapterTests(unittest.TestCase):
    def test_undefined_order_status_is_not_active(self):
        self.assertFalse(order_is_active_term({"status": "UNDEFINED"}))

    def test_paused_order_does_not_count_as_active(self):
        self.assertFalse(order_is_active_term({"status": "PAUSED"}))

    def test_pending_order_does_not_count_as_active(self):
        self.assertFalse(order_is_active_term({"status": "PENDING"}))

    def test_draft_order_does_not_count_as_active(self):
        order = {
            "status": "DRAFT",
            "paymentModel": "RECURRING",
        }

        self.assertFalse(order_is_active_term(order))

    def test_canceled_auto_renew_counts_until_term_end(self):
        order = {
            "status": "CANCELED",
            "autoRenewCanceled": True,
            "cancellation": {"effectiveAt": "NEXT_PAYMENT_DATE"},
            "endDate": "2027-01-01T00:00:00Z",
        }
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)

        self.assertTrue(order_is_active_term(order, now))

    def test_immediately_canceled_order_does_not_count_as_active(self):
        order = {
            "status": "CANCELED",
            "cancellation": {"effectiveAt": "IMMEDIATELY"},
            "endDate": "2027-01-01T00:00:00Z",
        }
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)

        self.assertFalse(order_is_active_term(order, now))

    def test_ended_order_does_not_count_even_with_future_date(self):
        order = {"status": "ENDED", "endDate": "2027-01-01T00:00:00Z"}
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)

        self.assertFalse(order_is_active_term(order, now))

    def test_canceled_order_without_end_date_is_not_active(self):
        order = {
            "status": "CANCELED",
            "autoRenewCanceled": True,
            "cancellation": {"effectiveAt": "NEXT_PAYMENT_DATE"},
        }

        self.assertFalse(order_is_active_term(order))

    def test_order_can_join_by_buyer_email(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {
                    "email": "person@example.com",
                    "subscriptionStatus": "SUBSCRIBED",
                },
            }
        ]
        orders = [
            {
                "status": "ACTIVE",
                "buyer": {"email": "person@example.com"},
                "plan": {"id": "plan-1", "name": "Annual plan"},
            }
        ]

        merged = adapt_wix_contacts(contacts, orders)[0]

        self.assertTrue(merged.has_active_pricing_plan)
        self.assertEqual(merged.active_plan_names, ("Annual plan",))

    def test_contact_member_id_links_member_without_email_or_contact_id(self):
        contacts = [
            {
                "id": "contact-1",
                "memberId": "member-1",
                "primaryEmail": {
                    "email": "person@example.com",
                    "subscriptionStatus": "SUBSCRIBED",
                },
            }
        ]
        members = [{"id": "member-1", "status": "APPROVED"}]

        merged = adapt_wix_contacts(contacts, [], members)[0]

        self.assertTrue(merged.is_member)
        self.assertEqual(merged.member_ids, ("member-1",))

    def test_member_contact_name_takes_precedence_over_nickname(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {
                    "email": "person@example.com",
                    "subscriptionStatus": "SUBSCRIBED",
                },
            }
        ]
        members = [
            {
                "id": "member-1",
                "contactId": "contact-1",
                "loginEmail": "person@example.com",
                "status": "APPROVED",
                "contact": {
                    "firstName": "Robert",
                    "lastName": "Seitzinger",
                },
                "profile": {
                    "nickname": "Bob S.",
                },
            }
        ]

        merged = adapt_wix_contacts(contacts, [], members)[0]

        self.assertEqual(merged.name, "Robert Seitzinger")

    def test_duplicate_email_prefers_member_contact_but_preserves_opt_out(self):
        contacts = [
            {
                "id": "form-contact",
                "updatedDate": "2026-01-01T00:00:00Z",
                "primaryEmail": {
                    "email": "PERSON@example.com",
                    "subscriptionStatus": "UNSUBSCRIBED",
                    "deliverabilityStatus": "VALID",
                },
                "info": {"name": {"first": "Form", "last": "Submission"}},
            },
            {
                "id": "member-contact",
                "memberId": "member-1",
                "updatedDate": "2025-01-01T00:00:00Z",
                "primaryEmail": {
                    "email": "person@example.com",
                    "subscriptionStatus": "SUBSCRIBED",
                    "deliverabilityStatus": "VALID",
                },
                "info": {"name": {"first": "Portal", "last": "Member"}},
            },
        ]
        members = [
            {
                "id": "member-1",
                "contactId": "member-contact",
                "loginEmail": "person@example.com",
                "status": "APPROVED",
                "contact": {
                    "firstName": "Portal",
                    "lastName": "Member",
                },
                "profile": {
                    "nickname": "Portal Member",
                },
            }
        ]
        orders = [
            {
                "id": "order-1",
                "status": "ACTIVE",
                "planId": "plan-1",
                "planName": "Annual Lago Mar Civic League Membership",
                "buyer": {"memberId": "member-1"},
            }
        ]

        result = adapt_wix_contacts(contacts, orders, members)

        self.assertEqual(len(result), 1)
        merged = result[0]
        self.assertEqual(merged.email, "person@example.com")
        self.assertEqual(merged.id, "member-contact")
        self.assertEqual(merged.name, "Portal Member")
        self.assertEqual(merged.subscription_status, "UNSUBSCRIBED")
        self.assertTrue(merged.is_member)
        self.assertTrue(merged.has_active_pricing_plan)
        self.assertEqual(
            merged.active_plan_names,
            ("Annual Lago Mar Civic League Membership",),
        )
        self.assertEqual(merged.active_plan_ids, ("plan-1",))
        self.assertEqual(merged.attributes["wix_duplicate_contact_count"], 2)
        self.assertEqual(
            merged.attributes["wix_contact_ids"],
            ["form-contact", "member-contact"],
        )

    def test_blocked_member_is_not_a_valid_portal_member(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {
                    "email": "person@example.com",
                    "subscriptionStatus": "SUBSCRIBED",
                },
            }
        ]
        members = [
            {
                "id": "member-1",
                "contactId": "contact-1",
                "loginEmail": "person@example.com",
                "status": "BLOCKED",
            }
        ]

        merged = adapt_wix_contacts(contacts, [], members)[0]

        self.assertFalse(merged.is_member)
        self.assertEqual(merged.member_status, "BLOCKED")

    def test_offline_member_is_not_treated_as_approved(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {"email": "person@example.com"},
            }
        ]
        members = [
            {
                "id": "member-1",
                "contactId": "contact-1",
                "status": "OFFLINE",
            }
        ]

        merged = adapt_wix_contacts(contacts, [], members)[0]

        self.assertFalse(merged.is_member)
        self.assertEqual(merged.member_status, "OFFLINE")

    def test_inactive_deliverability_wins_when_duplicate_contacts_are_merged(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {
                    "email": "person@example.com",
                    "deliverabilityStatus": "VALID",
                },
            },
            {
                "id": "contact-2",
                "primaryEmail": {
                    "email": "person@example.com",
                    "deliverabilityStatus": "INACTIVE",
                },
            },
        ]

        merged = adapt_wix_contacts(contacts, [], [])[0]

        self.assertEqual(merged.deliverability_status, "INACTIVE")

    def test_contact_details_are_normalized_for_filtering(self):
        contacts = [
            {
                "id": "contact-1",
                "primaryEmail": {"email": "person@example.com"},
                "source": {"sourceType": "WIX_FORMS"},
                "segments": {"items": ["segment-1"]},
                "info": {
                    "locale": "en-US",
                    "labelKeys": {"items": ["custom.neighborhood"]},
                    "phones": {
                        "items": [
                            {
                                "phone": "757-555-0100",
                                "e164Phone": "+17575550100",
                            }
                        ]
                    },
                    "addresses": {
                        "items": [
                            {
                                "address": {
                                    "addressLine": "123 Main St",
                                    "city": "Virginia Beach",
                                    "postalCode": "23456",
                                    "subdivision": "US-VA",
                                    "country": "US",
                                }
                            }
                        ]
                    },
                },
            }
        ]

        merged = adapt_wix_contacts(contacts, [])[0]

        self.assertEqual(merged.phone_numbers, ("+17575550100",))
        self.assertEqual(merged.address_lines, ("123 Main St",))
        self.assertEqual(merged.cities, ("Virginia Beach",))
        self.assertEqual(merged.postal_codes, ("23456",))
        self.assertEqual(merged.subdivisions, ("US-VA",))
        self.assertEqual(merged.countries, ("US",))
        self.assertEqual(
            merged.addresses,
            (
                {
                    "tag": "UNTAGGED",
                    "address_line": "123 Main St",
                    "formatted_address": "",
                    "city": "Virginia Beach",
                    "postal_code": "23456",
                    "subdivision": "US-VA",
                    "country": "US",
                },
            ),
        )
        self.assertEqual(merged.label_keys, ("custom.neighborhood",))
        self.assertEqual(merged.segment_ids, ("segment-1",))
        self.assertEqual(merged.locales, ("en-US",))
        self.assertEqual(merged.source_types, ("WIX_FORMS",))
        self.assertEqual(merged.attributes["wix_postal_codes"], ["23456"])
        self.assertEqual(merged.attributes["wix_addresses"], list(merged.addresses))


if __name__ == "__main__":
    unittest.main()
