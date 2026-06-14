import unittest

from wix_monk.domain.models import (
    ListmonkSubscriber,
    ManagedList,
    MembershipStatus,
    WixContact,
)
from wix_monk.domain.policy import (
    ConsentPolicy,
    is_eligible_for_list,
    plan_contact,
    stale_managed_memberships,
)


ALL = ManagedList(1, "All Wix contacts", {"field": "email", "is_empty": False})
MEMBERS = ManagedList(
    2,
    "Paying members",
    {"field": "active_pricing_plan", "equals": True},
)
POLICY = ConsentPolicy()


def contact(
        *,
        consent: str = "SUBSCRIBED",
        active: bool = True,
        deliverability: str = "VALID",
) -> WixContact:
    return WixContact(
        id="wix-1",
        email="person@example.com",
        name="Person",
        subscription_status=consent,
        deliverability_status=deliverability,
        has_active_pricing_plan=active,
    )


def subscriber(
        *,
        status: str = "enabled",
        memberships: dict[int, MembershipStatus] | None = None,
) -> ListmonkSubscriber:
    return ListmonkSubscriber(
        id=10,
        email="person@example.com",
        name="Person",
        status=status,
        memberships=memberships or {},
    )


class PlanContactTests(unittest.TestCase):
    def test_list_eligibility_log_includes_name_and_expanded_condition(self):
        with self.assertLogs("wix_monk.policy", level="DEBUG") as captured:
            is_eligible_for_list(contact(), MEMBERS)

        criteria_logs = "\n".join(captured.output)
        self.assertIn("List eligibility list='Paying members'", criteria_logs)
        self.assertIn("active_pricing_plan equals True", criteria_logs)
        self.assertIn("result=True", criteria_logs)
        self.assertEqual(len(captured.output), 1)

    def test_plan_name_criteria_is_case_insensitive(self):
        annual = ManagedList(
            3,
            "Annual members",
            {
                "field": "active_plan_names",
                "contains": "Annual Lago Mar Civic League Membership",
            },
        )
        wix_contact = WixContact(
            id="wix-1",
            email="person@example.com",
            name="Person",
            subscription_status="SUBSCRIBED",
            deliverability_status="VALID",
            has_active_pricing_plan=True,
            active_plan_names=("annual lago mar civic league membership",),
        )

        self.assertTrue(is_eligible_for_list(wix_contact, annual))

    def test_plan_id_criteria_uses_stable_wix_id(self):
        annual = ManagedList(
            3,
            "Annual members",
            {"field": "active_plan_ids", "contains": "plan-1"},
        )
        wix_contact = WixContact(
            id="wix-1",
            email="person@example.com",
            name="Person",
            subscription_status="SUBSCRIBED",
            deliverability_status="VALID",
            has_active_pricing_plan=True,
            active_plan_ids=("plan-1",),
        )

        self.assertTrue(is_eligible_for_list(wix_contact, annual))

    def test_expression_criteria_selects_exact_active_plan(self):
        annual = ManagedList(
            3,
            "Annual members",
            {
                "all": [
                    {"field": "active_pricing_plan", "equals": True},
                    {
                        "field": "active_plan_ids",
                        "contains": "plan-annual",
                    },
                ]
            },
        )
        wix_contact = WixContact(
            id="wix-1",
            email="person@example.com",
            name="Person",
            subscription_status="SUBSCRIBED",
            deliverability_status="VALID",
            has_active_pricing_plan=True,
            active_plan_ids=("plan-annual",),
        )

        self.assertTrue(is_eligible_for_list(wix_contact, annual))

    def test_subscribed_contact_is_added_to_eligible_lists(self):
        plan = plan_contact(contact(), None, [ALL, MEMBERS], POLICY)
        self.assertEqual(plan.add, frozenset({1, 2}))

    def test_nonmember_is_removed_only_from_member_list(self):
        existing = subscriber(
            memberships={1: MembershipStatus.CONFIRMED, 2: MembershipStatus.CONFIRMED}
        )
        plan = plan_contact(contact(active=False), existing, [ALL, MEMBERS], POLICY)
        self.assertEqual(plan.remove, frozenset({2}))

    def test_wix_opt_out_unsubscribes_current_managed_memberships(self):
        existing = subscriber(memberships={1: MembershipStatus.CONFIRMED})
        plan = plan_contact(contact(consent="UNSUBSCRIBED"), existing, [ALL], POLICY)
        self.assertEqual(plan.unsubscribe, frozenset({1}))
        self.assertFalse(plan.add)

    def test_listmonk_unsubscribe_is_never_overridden(self):
        existing = subscriber(memberships={1: MembershipStatus.UNSUBSCRIBED})
        plan = plan_contact(contact(), existing, [ALL], POLICY)
        self.assertEqual(plan.preserved_unsubscribes, frozenset({1}))
        self.assertFalse(plan.add)

    def test_blocklisted_subscriber_is_not_reenabled(self):
        plan = plan_contact(contact(), subscriber(status="blocklisted"), [ALL], POLICY)
        self.assertTrue(plan.skipped_global_suppression)
        self.assertFalse(plan.add)

    def test_disabled_subscriber_is_not_reenabled(self):
        plan = plan_contact(contact(), subscriber(status="disabled"), [ALL], POLICY)
        self.assertTrue(plan.skipped_global_suppression)
        self.assertFalse(plan.add)

    def test_global_suppression_preserves_existing_eligible_membership(self):
        existing = subscriber(
            status="blocklisted", memberships={1: MembershipStatus.CONFIRMED}
        )
        plan = plan_contact(contact(), existing, [ALL], POLICY)
        self.assertFalse(plan.add)
        self.assertFalse(plan.remove)

    def test_unknown_consent_is_not_treated_as_permission(self):
        existing = subscriber(memberships={1: MembershipStatus.CONFIRMED})
        plan = plan_contact(contact(consent="NOT_SET"), existing, [ALL], POLICY)
        self.assertEqual(plan.remove, frozenset({1}))

    def test_delivery_failure_removes_membership_without_unsubscribing(self):
        existing = subscriber(memberships={1: MembershipStatus.CONFIRMED})

        plan = plan_contact(
            contact(deliverability="BOUNCED"),
            existing,
            [ALL],
            POLICY,
        )

        self.assertEqual(plan.remove, frozenset({1}))
        self.assertFalse(plan.unsubscribe)

    def test_delivery_failure_does_not_add_new_membership(self):
        plan = plan_contact(
            contact(deliverability="INACTIVE"),
            None,
            [ALL],
            POLICY,
        )

        self.assertFalse(plan.add)

    def test_list_can_allow_not_set_without_changing_other_lists(self):
        members_allow_not_set = ManagedList(
            2,
            "Members",
            {"field": "active_pricing_plan", "equals": True},
            subscribed_statuses=frozenset({"SUBSCRIBED", "NOT_SET"}),
        )

        plan = plan_contact(
            contact(consent="NOT_SET"),
            None,
            [ALL, members_allow_not_set],
            POLICY,
        )

        self.assertEqual(plan.add, frozenset({2}))

    def test_list_override_does_not_override_explicit_unsubscribe(self):
        members_allow_not_set = ManagedList(
            2,
            "Members",
            {"field": "active_pricing_plan", "equals": True},
            subscribed_statuses=frozenset({"SUBSCRIBED", "NOT_SET"}),
        )

        plan = plan_contact(
            contact(consent="UNSUBSCRIBED"),
            subscriber(memberships={2: MembershipStatus.CONFIRMED}),
            [members_allow_not_set],
            POLICY,
        )

        self.assertEqual(plan.unsubscribe, frozenset({2}))

    def test_stale_contact_cleanup_preserves_unsubscribe_record(self):
        existing = subscriber(
            memberships={
                1: MembershipStatus.CONFIRMED,
                2: MembershipStatus.UNSUBSCRIBED,
            }
        )
        self.assertEqual(
            stale_managed_memberships(existing, [ALL, MEMBERS]),
            frozenset({1}),
        )


if __name__ == "__main__":
    unittest.main()
