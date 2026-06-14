from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable

from wix_monk.config.loading import ConsentDefinition, ListDefinition, SyncConfig
from wix_monk.domain.models import ContactPlan, ListmonkSubscriber, ManagedList
from wix_monk.domain.filtering import AndFilter, FilterExpression
from wix_monk.domain.policy import ConsentPolicy, plan_contact, stale_managed_memberships
from wix_monk.domain.reporting import format_list_summary, summarize_list
from wix_monk.integrations.adapters import (
    order_contact_id,
    order_email,
    order_is_active_term,
    order_member_id,
    order_plan_name,
    order_status,
)
from wix_monk.integrations.datasets import NormalizedListmonkData, NormalizedWixData
from wix_monk.integrations.ports import ListmonkGateway


class SyncContext:
    """Computed sync state used for reporting and applying changes."""

    def __init__(
            self,
            dataset: NormalizedWixData,
            listmonk: NormalizedListmonkData,
            managed_lists: tuple[ManagedList, ...],
            missing_lists: tuple[ListDefinition, ...],
            plans: tuple[ContactPlan, ...],
            stale_subscribers: tuple[ListmonkSubscriber, ...],
            stale_removals: dict[int, frozenset[int]],
        consent_policy: ConsentPolicy,
    ) -> None:
        self.dataset = dataset
        self.subscribers = listmonk.subscribers
        self.managed_lists = managed_lists
        self.missing_lists = missing_lists
        self.plans = plans
        self.stale_subscribers = stale_subscribers
        self.stale_removals = stale_removals
        self.consent_policy = consent_policy


class SynchronizationService:
    """Coordinate loading, planning, reporting, and applying sync changes."""

    def __init__(
            self,
            wix_data: NormalizedWixData,
            listmonk_data: NormalizedListmonkData,
            listmonk: ListmonkGateway,
            logger: logging.Logger,
            output: Callable[[str], None] = print,
    ) -> None:
        self.wix_data = wix_data
        self.listmonk_data = listmonk_data
        self.listmonk = listmonk
        self.logger = logger
        self.output = output

    def run(self, config: SyncConfig, apply: bool) -> None:
        """Execute a dry run or apply pass for one synchronization config."""

        self.logger.info("Starting %s sync for %d configured lists", "apply" if apply else "dry-run", len(config.lists))
        managed_lists, missing_lists = self._resolve_lists(
            config.lists,
            config.consent,
            apply,
            config.criteria,
        )
        consent_policy = ConsentPolicy(
            subscribed_statuses=config.consent.subscribed_statuses or frozenset(),
            unsubscribed_statuses=config.consent.unsubscribed_statuses or frozenset(),
        )
        plans = self._plan_contacts(
            self.wix_data,
            self.listmonk_data,
            managed_lists,
            consent_policy,
        )
        stale_subscribers, stale_removals = self._find_stale_subscribers(
            self.wix_data,
            self.listmonk_data,
            managed_lists,
        )

        context = SyncContext(
            dataset=self.wix_data,
            listmonk=self.listmonk_data,
            managed_lists=managed_lists,
            missing_lists=missing_lists,
            plans=plans,
            stale_subscribers=stale_subscribers,
            stale_removals=stale_removals,
            consent_policy=consent_policy,
        )
        self._report(context, apply)
        if apply:
            self._apply(context)

    def _resolve_lists(
            self,
            definitions: tuple[ListDefinition, ...],
            default_consent: ConsentDefinition,
            apply: bool,
            global_criteria: FilterExpression | None = None,
    ) -> tuple[tuple[ManagedList, ...], tuple[ListDefinition, ...]]:
        """Resolve configured lists into effective managed lists."""

        available = self.listmonk_data.list_ids_by_name()
        managed = []
        missing = []
        for index, definition in enumerate(definitions):
            consent = definition.resolved_consent(default_consent)
            criteria = definition.criteria
            if global_criteria is not None:
                criteria = AndFilter((global_criteria, criteria))
            if definition.name not in available:
                missing.append(definition)
                if apply:
                    self.logger.info("Creating missing list %s", definition.name)
                    available[definition.name] = self.listmonk.create_list(
                        definition.name,
                        list_type=definition.list_type,
                        optin=definition.optin,
                        description=definition.description,
                        tags=list(definition.tags),
                    )
                    self.output(f"Created Listmonk list: {definition.name}")
                else:
                    available[definition.name] = -(index + 1)
            managed.append(
                ManagedList(
                    id=available[definition.name],
                    name=definition.name,
                    criteria=criteria,
                    subscribed_statuses=consent.subscribed_statuses,
                    unsubscribed_statuses=consent.unsubscribed_statuses,
                )
            )
        return tuple(managed), tuple(missing)

    def _plan_contacts(
            self,
            dataset: NormalizedWixData,
            listmonk: NormalizedListmonkData,
            managed_lists: tuple[ManagedList, ...],
            consent_policy: ConsentPolicy,
    ) -> tuple[ContactPlan, ...]:
        by_email = listmonk.subscribers_by_email()
        return tuple(
            plan_contact(
                contact,
                by_email.get(contact.email),
                managed_lists,
                consent_policy,
            )
            for contact in dataset.contacts
        )

    def _find_stale_subscribers(
            self,
            dataset: NormalizedWixData,
            listmonk: NormalizedListmonkData,
            managed_lists: tuple[ManagedList, ...],
    ) -> tuple[tuple[ListmonkSubscriber, ...], dict[int, frozenset[int]]]:
        wix_emails = {contact.email for contact in dataset.contacts}
        subscribers = listmonk.subscribers
        stale = tuple(
            subscriber
            for subscriber in subscribers
            if subscriber.email not in wix_emails
            and (
                    subscriber.attributes.get("source") == "wix"
                    or subscriber.attributes.get("wix_contact_id")
            )
        )
        removals = {
            subscriber.id: stale_managed_memberships(subscriber, managed_lists)
            for subscriber in stale
        }
        return stale, removals

    def _report(
            self,
            context: SyncContext,
            apply: bool,
    ) -> None:
        summary, diagnostics = _sync_diagnostics(context)
        mode = "APPLY" if apply else "DRY RUN"
        self.logger.info(
            "Sync summary: %s",
            ", ".join(f"{key}={value}" for key, value in summary.items()),
        )
        self.output(
            f"{mode}: " + ", ".join(f"{key}={value}" for key, value in summary.items())
        )
        for label, counts in diagnostics:
            self.output(
                label
                + ": "
                + ", ".join(f"{key}={value}" for key, value in counts.items())
            )

        missing_names = {item.name for item in context.missing_lists}
        for managed_list in context.managed_lists:
            list_summary = summarize_list(
                managed_list,
                context.plans,
                context.subscribers,
                context.stale_removals,
                context.consent_policy,
            )
            self.output("")
            self.output(
                format_list_summary(
                    managed_list,
                    list_summary,
                    will_create=managed_list.name in missing_names and not apply,
                )
            )

    def _apply(self, context: SyncContext) -> None:
        self.logger.info("Applying %d contact plans", len(context.plans))
        for plan in context.plans:
            subscriber = plan.subscriber
            attributes = dict(subscriber.attributes) if subscriber else {}
            attributes.update(plan.contact.attributes)
            if subscriber is None:
                subscriber_id = self.listmonk.create_subscriber(
                    plan.contact.email,
                    plan.contact.name,
                    attributes,
                )
            else:
                subscriber_id = subscriber.id
                self.listmonk.update_subscriber(
                    subscriber.id,
                    plan.contact.email,
                    plan.contact.name or subscriber.name,
                    subscriber.status,
                    attributes,
                )
            self.listmonk.change_lists(
                [subscriber_id], sorted(plan.add), "add", "confirmed"
            )
            self.listmonk.change_lists([subscriber_id], sorted(plan.remove), "remove")
            self.listmonk.change_lists(
                [subscriber_id], sorted(plan.unsubscribe), "unsubscribe"
            )

        for subscriber in context.stale_subscribers:
            self.logger.info("Removing stale subscriber %s", subscriber.email)
            self.listmonk.change_lists(
                [subscriber.id],
                sorted(context.stale_removals[subscriber.id]),
                "remove",
            )


def _sync_diagnostics(
        context: SyncContext,
) -> tuple[Counter[str], tuple[tuple[str, dict[str, int]], ...]]:
    """Build the top-level sync summary and supporting diagnostics."""

    dataset = context.dataset
    active_orders = [order for order in dataset.raw_orders if order_is_active_term(order)]
    contact_ids = {value for contact in dataset.contacts for value in contact.contact_ids}
    member_ids = {value for contact in dataset.contacts for value in contact.member_ids}
    emails = {contact.email for contact in dataset.contacts}

    identity_counts = Counter()
    match_counts = Counter()
    matched_orders = 0
    for order in active_orders:
        contact_id = order_contact_id(order)
        member_id = order_member_id(order)
        email = order_email(order)
        identity_counts["contact_id"] += bool(contact_id)
        identity_counts["member_id"] += bool(member_id)
        identity_counts["email"] += bool(email)
        identity_counts["no_identity"] += not any((contact_id, member_id, email))
        contact_match = contact_id in contact_ids
        member_match = member_id in member_ids
        email_match = email in emails
        match_counts["contact_id"] += contact_match
        match_counts["member_id"] += member_match
        match_counts["email"] += email_match
        matched_orders += contact_match or member_match or email_match

    summary = Counter(
        lists_to_create=len(context.missing_lists),
        wix_contacts_raw=len(dataset.raw_contacts),
        wix_members_raw=len(dataset.raw_members),
        wix_orders_raw=len(dataset.raw_orders),
        active_term_orders=len(active_orders),
        matched_active_orders=matched_orders,
        unmatched_active_orders=len(active_orders) - matched_orders,
        duplicate_wix_rows=sum(
            max(int(contact.attributes.get("wix_duplicate_contact_count", 1)) - 1, 0)
            for contact in dataset.contacts
        ),
        members=sum(contact.is_member for contact in dataset.contacts),
        non_members=sum(not contact.is_member for contact in dataset.contacts),
        active_pricing_plan=sum(
            contact.has_active_pricing_plan for contact in dataset.contacts
        ),
    )
    summary["duplicate_active_term_orders"] = (
            len(active_orders) - summary["active_pricing_plan"]
    )
    for plan in context.plans:
        summary["contacts"] += 1
        summary["create"] += plan.subscriber is None
        summary["add"] += len(plan.add)
        summary["remove"] += len(plan.remove)
        summary["unsubscribe"] += len(plan.unsubscribe)
        summary["preserve_unsubscribe"] += len(plan.preserved_unsubscribes)
        summary["globally_suppressed"] += plan.skipped_global_suppression
    summary["stale_wix_subscribers"] = len(context.stale_subscribers)
    summary["stale_memberships_removed"] = sum(
        map(len, context.stale_removals.values())
    )

    diagnostics = (
        (
            "Wix member API statuses",
            dict(
                sorted(
                    Counter(
                        str(member.get("status") or "<missing>").upper()
                        for member in dataset.raw_members
                    ).items()
                )
            ),
        ),
        (
            "Wix pricing order statuses",
            dict(
                sorted(
                    Counter(
                        order_status(order) or "<missing>"
                        for order in dataset.raw_orders
                    ).items()
                )
            ),
        ),
        (
            "Active-term pricing plans",
            dict(
                sorted(
                    Counter(
                        order_plan_name(order) or "<missing>"
                        for order in active_orders
                    ).items()
                )
            ),
        ),
        (
            "Active-order identity fields",
            {
                key: identity_counts[key]
                for key in ("contact_id", "member_id", "email", "no_identity")
            },
        ),
        (
            "Active-order matches",
            {key: match_counts[key] for key in ("contact_id", "member_id", "email")},
        ),
    )
    return summary, diagnostics
