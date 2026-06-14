import unittest
from typing import Any

from wix_monk.domain.filtering import FilterConfigError, matches_filter, validate_criteria
from wix_monk.domain.models import WixContact


def contact(**overrides: Any) -> WixContact:
    values = {
        "id": "contact-1",
        "email": "member@example.com",
        "name": "Example Member",
        "subscription_status": "NOT_SET",
        "deliverability_status": "VALID",
        "has_active_pricing_plan": True,
        "is_member": True,
        "member_status": "APPROVED",
        "active_plan_names": ("Annual Lago Mar Civic League Membership",),
        "active_plan_ids": ("plan-annual",),
        "contact_ids": ("contact-1",),
        "member_ids": ("member-1",),
        "phone_numbers": ("+17575550100",),
        "cities": ("Virginia Beach",),
        "postal_codes": ("23456",),
        "label_keys": ("custom.neighborhood",),
        "addresses": (
            {
                "tag": "HOME",
                "address_line": "123 Main St",
                "formatted_address": "123 Main St, Virginia Beach VA 23456",
                "city": "Virginia Beach",
                "postal_code": "23456",
                "subdivision": "US-VA",
                "country": "US",
            },
            {
                "tag": "BILLING",
                "address_line": "PO Box 10",
                "formatted_address": "PO Box 10, Norfolk VA 23510",
                "city": "Norfolk",
                "postal_code": "23510",
                "subdivision": "US-VA",
                "country": "US",
            },
        ),
    }
    values.update(overrides)
    return WixContact(**values)


class FilterTests(unittest.TestCase):
    def test_scalar_comparison_operators(self):
        cases = (
            ({"field": "email", "equals": "MEMBER@example.com"}, True),
            ({"field": "email", "not_equals": "other@example.com"}, True),
            ({"field": "email", "in": ["other@example.com", "member@example.com"]}, True),
            ({"field": "email", "not_in": ["other@example.com"]}, True),
            ({"field": "email", "contains_text": "@example"}, True),
            ({"field": "email", "starts_with": "member@"}, True),
            ({"field": "email", "ends_with": ".com"}, True),
            ({"field": "email", "not_in": ["member@example.com"]}, False),
        )

        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(matches_filter(contact(), expression), expected)

    def test_array_comparison_operators(self):
        cases = (
            ({"field": "active_plan_ids", "contains": "PLAN-ANNUAL"}, True),
            (
                {
                    "field": "active_plan_ids",
                    "contains_any": ["plan-monthly", "plan-annual"],
                },
                True,
            ),
            (
                {
                    "field": "label_keys",
                    "contains_all": ["custom.neighborhood"],
                },
                True,
            ),
            (
                {
                    "field": "active_plan_ids",
                    "contains_all": ["plan-annual", "plan-monthly"],
                },
                False,
            ),
        )

        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(matches_filter(contact(), expression), expected)

    def test_nested_filter_combines_membership_consent_and_exact_plan(self):
        expression = {
            "all": [
                {"field": "is_member", "equals": True},
                {
                    "field": "subscription_status",
                    "in": ["SUBSCRIBED", "NOT_SET"],
                },
                {
                    "field": "active_plan_names",
                    "contains": "annual lago mar civic league membership",
                },
            ]
        }

        self.assertTrue(matches_filter(contact(), expression))

    def test_member_status_can_be_filtered_by_wix_access_status(self):
        approved = {"field": "member_status", "equals": "APPROVED"}
        unable_to_log_in = {
            "field": "member_status",
            "in": ["BLOCKED", "OFFLINE", "PENDING"],
        }

        self.assertTrue(matches_filter(contact(member_status="APPROVED"), approved))
        self.assertTrue(
            matches_filter(contact(member_status="BLOCKED"), unable_to_log_in)
        )
        self.assertFalse(matches_filter(contact(member_status="APPROVED"), unable_to_log_in))

    def test_exact_plan_name_does_not_match_partial_name(self):
        expression = {
            "field": "active_plan_names",
            "contains": "Annual Lago Mar",
        }

        self.assertFalse(matches_filter(contact(), expression))

    def test_any_and_not_support_exclusions(self):
        expression = {
            "all": [
                {
                    "any": [
                        {"field": "is_member", "equals": True},
                        {"field": "active_pricing_plan", "equals": True},
                    ]
                },
                {
                    "not": {
                        "field": "deliverability_status",
                        "in": ["BOUNCED", "INACTIVE", "SPAM_COMPLAINT"],
                    }
                },
            ]
        }

        self.assertTrue(matches_filter(contact(), expression))
        self.assertFalse(
            matches_filter(contact(deliverability_status="BOUNCED"), expression)
        )

    def test_case_sensitive_matching_is_available(self):
        expression = {
            "field": "email",
            "equals": "MEMBER@example.com",
            "case_sensitive": True,
        }

        self.assertFalse(matches_filter(contact(), expression))

    def test_regex_matches_scalar_text(self):
        expression = {
            "field": "email",
            "matches_regex": r"^member@.*\.com$",
        }

        self.assertTrue(matches_filter(contact(), expression))

    def test_regex_matches_an_array_element(self):
        expression = {
            "field": "active_plan_names",
            "contains_regex": r"^Annual .* Membership$",
        }

        self.assertTrue(matches_filter(contact(), expression))

    def test_unknown_field_is_rejected(self):
        with self.assertRaisesRegex(FilterConfigError, "unknown field"):
            validate_criteria({"field": "postal_code", "equals": "23456"})

    def test_multiple_operators_are_rejected(self):
        with self.assertRaisesRegex(FilterConfigError, "exactly one filter operator"):
            validate_criteria(
                {"field": "email", "equals": "a@example.com", "ends_with": ".com"}
            )

    def test_operator_must_support_field_type(self):
        with self.assertRaisesRegex(FilterConfigError, "not valid for boolean"):
            validate_criteria(
                {"field": "is_member", "contains_text": "true"}
            )

    def test_boolean_field_rejects_case_sensitivity(self):
        with self.assertRaisesRegex(FilterConfigError, "not valid for boolean"):
            validate_criteria(
                {
                    "field": "is_member",
                    "equals": True,
                    "case_sensitive": True,
                }
            )

    def test_invalid_regex_is_rejected(self):
        with self.assertRaisesRegex(FilterConfigError, "is invalid"):
            validate_criteria({"field": "email", "matches_regex": "["})

    def test_postal_code_and_label_are_filterable(self):
        expression = {
            "all": [
                {"field": "postal_codes", "contains": "23456"},
                {"field": "label_keys", "contains": "custom.neighborhood"},
            ]
        }

        self.assertTrue(matches_filter(contact(), expression))

    def test_any_match_requires_conditions_on_the_same_address(self):
        home_23456 = {
            "field": "addresses",
            "any_match": {
                "all": [
                    {"field": "tag", "equals": "HOME"},
                    {"field": "postal_code", "equals": "23456"},
                ]
            },
        }
        home_23510 = {
            "field": "addresses",
            "any_match": {
                "all": [
                    {"field": "tag", "equals": "HOME"},
                    {"field": "postal_code", "equals": "23510"},
                ]
            },
        }

        self.assertTrue(matches_filter(contact(), home_23456))
        self.assertFalse(matches_filter(contact(), home_23510))

    def test_any_match_rejects_unknown_address_field(self):
        with self.assertRaisesRegex(FilterConfigError, "unknown field"):
            validate_criteria(
                {
                    "field": "addresses",
                    "any_match": {"field": "county", "equals": "Virginia Beach"},
                }
            )


if __name__ == "__main__":
    unittest.main()
