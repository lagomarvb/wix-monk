from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from wix_monk.domain.filtering import describe_filter, matches_filter
from wix_monk.domain.models import (
    Consent,
    ContactPlan,
    ListmonkSubscriber,
    ManagedList,
    MembershipStatus,
    WixContact,
)

LOGGER = logging.getLogger("wix_monk.policy")
UNDELIVERABLE_STATUSES = frozenset({"BOUNCED", "INACTIVE", "SPAM_COMPLAINT"})


@dataclass(frozen=True)
class ConsentPolicy:
    """Classify Wix consent statuses as allowed, denied, or unknown."""

    subscribed_statuses: frozenset[str] = frozenset({"SUBSCRIBED"})
    unsubscribed_statuses: frozenset[str] = frozenset({"UNSUBSCRIBED"})

    def classify(self, status: str) -> Consent:
        normalized = status.strip().upper()
        if normalized in self.subscribed_statuses:
            return Consent.ALLOWED
        if normalized in self.unsubscribed_statuses:
            return Consent.DENIED
        return Consent.UNKNOWN


def consent_policy_for_list(
        default_policy: ConsentPolicy,
        managed_list: ManagedList,
) -> ConsentPolicy:
    """Resolve the effective consent policy for one managed list."""

    return ConsentPolicy(
        subscribed_statuses=(
            managed_list.subscribed_statuses
            if managed_list.subscribed_statuses is not None
            else default_policy.subscribed_statuses
        ),
        unsubscribed_statuses=(
            managed_list.unsubscribed_statuses
            if managed_list.unsubscribed_statuses is not None
            else default_policy.unsubscribed_statuses
        ),
    )


def is_eligible_for_list(contact: WixContact, managed_list: ManagedList) -> bool:
    """Return whether a contact matches a managed list's criteria."""

    result = matches_filter(contact, managed_list.criteria)
    LOGGER.debug(
        "List eligibility list=%r contact=%s criteria=%s result=%s",
        managed_list.name,
        contact.email,
        describe_filter(managed_list.criteria),
        result,
    )
    return result


def stale_managed_memberships(
        subscriber: ListmonkSubscriber,
        managed_lists: Iterable[ManagedList],
) -> frozenset[int]:
    """Return managed list memberships that should be removed from a stale subscriber."""

    return frozenset(
        managed_list.id
        for managed_list in managed_lists
        if subscriber.memberships.get(managed_list.id)
        in {MembershipStatus.CONFIRMED, MembershipStatus.UNCONFIRMED}
    )


def plan_contact(
        contact: WixContact,
        subscriber: ListmonkSubscriber | None,
        managed_lists: Iterable[ManagedList],
        consent_policy: ConsentPolicy,
) -> ContactPlan:
    """Build the intended Listmonk changes for one normalized contact."""

    planner = _ContactPlanner(contact, subscriber, consent_policy)
    return planner.build_plan(managed_lists)


class _ContactPlanner:
    """Stateful helper that assembles a single contact plan."""

    def __init__(
            self,
            contact: WixContact,
            subscriber: ListmonkSubscriber | None,
            default_consent_policy: ConsentPolicy,
    ) -> None:
        self.contact = contact
        self.subscriber = subscriber
        self.default_consent_policy = default_consent_policy
        self.memberships = subscriber.memberships if subscriber is not None else {}
        self.globally_suppressed = (
                subscriber is not None and subscriber.status != "enabled"
        )
        self.lists_to_add: set[int] = set()
        self.lists_to_remove: set[int] = set()
        self.lists_to_unsubscribe: set[int] = set()
        self.preserved_unsubscribes: set[int] = set()

    def build_plan(self, managed_lists: Iterable[ManagedList]) -> ContactPlan:
        self._log_contact_start()
        for managed_list in managed_lists:
            self._plan_managed_list(managed_list)

        return ContactPlan(
            contact=self.contact,
            subscriber=self.subscriber,
            add=frozenset(self.lists_to_add),
            remove=frozenset(self.lists_to_remove),
            unsubscribe=frozenset(self.lists_to_unsubscribe),
            preserved_unsubscribes=frozenset(self.preserved_unsubscribes),
            skipped_global_suppression=self.globally_suppressed,
        )

    def _plan_managed_list(self, managed_list: ManagedList) -> None:
        consent = self._consent_for(managed_list)
        current_membership = self.memberships.get(managed_list.id)
        is_eligible = is_eligible_for_list(self.contact, managed_list)
        can_receive = self._can_receive_messages(consent)

        # A Listmonk unsubscribe is a user preference, not stale membership.
        if current_membership == MembershipStatus.UNSUBSCRIBED:
            self.preserved_unsubscribes.add(managed_list.id)
            self._log_list_action(
                managed_list,
                current_membership,
                consent,
                is_eligible,
                "preserve_unsubscribe",
            )
            return

        if consent == Consent.DENIED:
            action = self._handle_denied_consent(
                managed_list,
                current_membership,
            )
            self._log_list_action(
                managed_list,
                current_membership,
                consent,
                is_eligible,
                action,
            )
            return

        if is_eligible and self.globally_suppressed:
            # Global suppression already prevents delivery. Preserve the list
            # relationship so this tool does not reinterpret it.
            self._log_list_action(
                managed_list,
                current_membership,
                consent,
                is_eligible,
                "preserve_global_suppression",
            )
            return

        action = self._plan_membership_change(
            managed_list,
            current_membership,
            is_eligible,
            can_receive,
        )
        self._log_membership_action(
            managed_list,
            current_membership,
            consent,
            is_eligible,
            action,
            can_receive=can_receive,
        )

    def _consent_for(self, managed_list: ManagedList) -> Consent:
        list_policy = consent_policy_for_list(
            self.default_consent_policy,
            managed_list,
        )
        return list_policy.classify(self.contact.subscription_status)

    def _can_receive_messages(self, consent: Consent) -> bool:
        deliverability_status = self.contact.deliverability_status.strip().upper()
        return (
                consent == Consent.ALLOWED
                and deliverability_status not in UNDELIVERABLE_STATUSES
        )

    def _handle_denied_consent(
            self,
            managed_list: ManagedList,
            current_membership: MembershipStatus | None,
    ) -> str:
        if current_membership is None:
            return "skip_denied"
        self.lists_to_unsubscribe.add(managed_list.id)
        return "unsubscribe"

    def _plan_membership_change(
            self,
            managed_list: ManagedList,
            current_membership: MembershipStatus | None,
            is_eligible: bool,
            can_receive: bool,
    ) -> str:
        if is_eligible and can_receive:
            if current_membership == MembershipStatus.CONFIRMED:
                return "keep_confirmed"
            self.lists_to_add.add(managed_list.id)
            return "add"

        if current_membership is None:
            return "skip"

        # Unknown consent, delivery failures, and eligibility changes remove
        # managed membership without inventing a user unsubscribe.
        self.lists_to_remove.add(managed_list.id)
        return "remove"

    def _log_contact_start(self) -> None:
        LOGGER.debug(
            "Planning contact email=%s subscriber=%s globally_suppressed=%s",
            self.contact.email,
            self.subscriber.id if self.subscriber is not None else None,
            self.globally_suppressed,
        )

    def _log_list_action(
            self,
            managed_list: ManagedList,
            current_membership: MembershipStatus | None,
            consent: Consent,
            is_eligible: bool,
            action: str,
    ) -> None:
        LOGGER.debug(
            "Contact email=%s list=%s current=%s consent=%s eligible=%s action=%s",
            self.contact.email,
            managed_list.name,
            current_membership.value if current_membership is not None else None,
            consent.value,
            is_eligible,
            action,
        )

    def _log_membership_action(
            self,
            managed_list: ManagedList,
            current_membership: MembershipStatus | None,
            consent: Consent,
            is_eligible: bool,
            action: str,
            *,
            can_receive: bool,
    ) -> None:
        LOGGER.debug(
            "Contact email=%s list=%s current=%s consent=%s eligible=%s can_receive=%s action=%s",
            self.contact.email,
            managed_list.name,
            current_membership.value if current_membership is not None else None,
            consent.value,
            is_eligible,
            can_receive,
            action,
        )
