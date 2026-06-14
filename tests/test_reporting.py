import unittest

from wix_monk.domain.models import (
    ListmonkSubscriber,
    ManagedList,
    MembershipStatus,
    WixContact,
)
from wix_monk.domain.policy import ConsentPolicy, plan_contact
from wix_monk.domain.reporting import format_list_summary, summarize_list


class ReportingTests(unittest.TestCase):
    def test_list_summary_calculates_resulting_membership(self):
        managed_list = ManagedList(
            4,
            "Paying members",
            {"field": "active_pricing_plan", "equals": True},
        )
        policy = ConsentPolicy()
        existing = ListmonkSubscriber(
            id=10,
            email="old@example.com",
            name="Old",
            status="enabled",
            memberships={4: MembershipStatus.CONFIRMED},
        )
        new_contact = WixContact(
            id="wix-new",
            email="new@example.com",
            name="New",
            subscription_status="SUBSCRIBED",
            deliverability_status="VALID",
            has_active_pricing_plan=True,
        )
        opted_out_contact = WixContact(
            id="wix-old",
            email="old@example.com",
            name="Old",
            subscription_status="UNSUBSCRIBED",
            deliverability_status="VALID",
            has_active_pricing_plan=True,
        )
        plans = [
            plan_contact(new_contact, None, [managed_list], policy),
            plan_contact(opted_out_contact, existing, [managed_list], policy),
        ]

        summary = summarize_list(managed_list, plans, [existing], {}, policy)

        self.assertEqual(summary["eligible"], 2)
        self.assertEqual(summary["add"], 1)
        self.assertEqual(summary["unsubscribe"], 1)
        self.assertEqual(summary["current_confirmed"], 1)
        self.assertEqual(summary["resulting_confirmed"], 1)

    def test_format_identifies_missing_list(self):
        output = format_list_summary(
            ManagedList(
                -1,
                "All Wix contacts",
                {"field": "email", "is_empty": False},
            ),
            {
                "eligible": 3,
                "eligible_consent_allowed": 2,
                "eligible_consent_denied": 1,
                "eligible_consent_unknown": 0,
                "add": 2,
                "remove": 0,
                "unsubscribe": 0,
                "preserve_unsubscribe": 0,
                "stale_remove": 0,
                "current_confirmed": 0,
                "resulting_confirmed": 2,
            },
            will_create=True,
        )

        self.assertIn("List: All Wix contacts (will create, filter=", output)
        self.assertIn("eligible_contacts=3", output)
        self.assertIn("current=0, resulting=2", output)

    def test_list_summary_uses_list_consent_override(self):
        managed_list = ManagedList(
            5,
            "Members",
            {"field": "is_member", "equals": True},
            subscribed_statuses=frozenset({"SUBSCRIBED", "NOT_SET"}),
        )
        contact = WixContact(
            id="wix-1",
            email="member@example.com",
            name="Member",
            subscription_status="NOT_SET",
            deliverability_status="VALID",
            has_active_pricing_plan=False,
            is_member=True,
        )
        policy = ConsentPolicy()
        plans = [plan_contact(contact, None, [managed_list], policy)]

        summary = summarize_list(managed_list, plans, [], {}, policy)

        self.assertEqual(summary["eligible_consent_allowed"], 1)
        self.assertEqual(summary["eligible_consent_unknown"], 0)
        self.assertEqual(summary["add"], 1)


if __name__ == "__main__":
    unittest.main()
