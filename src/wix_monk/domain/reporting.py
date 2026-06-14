from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from wix_monk.domain.filtering import describe_filter
from wix_monk.domain.models import ContactPlan, ListmonkSubscriber, ManagedList, MembershipStatus
from wix_monk.domain.policy import ConsentPolicy, consent_policy_for_list, is_eligible_for_list


def summarize_list(
        managed_list: ManagedList,
        plans: Iterable[ContactPlan],
        subscribers: Iterable[ListmonkSubscriber],
        stale_removals: Mapping[int, frozenset[int]],
        consent_policy: ConsentPolicy,
) -> Counter[str]:
    """Summarize how one managed list will change during sync."""

    plans = list(plans)
    subscribers = list(subscribers)
    summary: Counter[str] = Counter()

    summary["current_confirmed"] = sum(
        subscriber.memberships.get(managed_list.id) == MembershipStatus.CONFIRMED
        for subscriber in subscribers
    )

    for plan in plans:
        eligible = is_eligible_for_list(plan.contact, managed_list)
        if eligible:
            summary["eligible"] += 1
            consent = consent_policy_for_list(consent_policy, managed_list).classify(
                plan.contact.subscription_status
            )
            summary[f"eligible_consent_{consent.value}"] += 1

        summary["add"] += managed_list.id in plan.add
        summary["remove"] += managed_list.id in plan.remove
        summary["unsubscribe"] += managed_list.id in plan.unsubscribe
        summary["preserve_unsubscribe"] += (
                managed_list.id in plan.preserved_unsubscribes
        )

    summary["stale_remove"] = sum(
        managed_list.id in list_ids for list_ids in stale_removals.values()
    )

    confirmed_removals = sum(
        plan.subscriber is not None
        and plan.subscriber.memberships.get(managed_list.id)
        == MembershipStatus.CONFIRMED
        and (
                managed_list.id in plan.remove
                or managed_list.id in plan.unsubscribe
        )
        for plan in plans
    )
    stale_confirmed_removals = sum(
        managed_list.id in stale_removals.get(subscriber.id, frozenset())
        and subscriber.memberships.get(managed_list.id)
        == MembershipStatus.CONFIRMED
        for subscriber in subscribers
    )
    summary["resulting_confirmed"] = (
            summary["current_confirmed"]
            + summary["add"]
            - confirmed_removals
            - stale_confirmed_removals
    )
    return summary


def format_list_summary(
        managed_list: ManagedList,
        summary: Mapping[str, int],
        *,
        will_create: bool,
) -> str:
    """Render a human-readable summary for one managed list."""

    state = "will create" if will_create else f"existing id={managed_list.id}"
    criteria = "filter=" + describe_filter(managed_list.criteria)
    if managed_list.subscribed_statuses is not None:
        criteria += ", allowed_statuses=" + " | ".join(
            sorted(managed_list.subscribed_statuses)
        )
    lines = [
        f"List: {managed_list.name} ({state}, {criteria})",
        (
            "  Wix: "
            f"eligible_contacts={summary['eligible']}, "
            f"eligible_subscribed={summary['eligible_consent_allowed']}, "
            f"eligible_unsubscribed={summary['eligible_consent_denied']}, "
            f"eligible_unknown_consent={summary['eligible_consent_unknown']}"
        ),
        (
            "  Plan: "
            f"add={summary['add']}, "
            f"remove={summary['remove']}, "
            f"unsubscribe={summary['unsubscribe']}, "
            f"preserve_unsubscribe={summary['preserve_unsubscribe']}, "
            f"stale_remove={summary['stale_remove']}"
        ),
        (
            "  Confirmed membership: "
            f"current={summary['current_confirmed']}, "
            f"resulting={summary['resulting_confirmed']}"
        ),
    ]
    return "\n".join(lines)
