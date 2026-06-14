from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wix_monk.domain.filtering import FilterConfigError, FilterExpression, validate_criteria


@dataclass(frozen=True)
class ConsentDefinition:
    """Consent policy fragment used at the config or list level."""

    subscribed_statuses: frozenset[str] | None
    unsubscribed_statuses: frozenset[str] | None

    @classmethod
    def from_mapping(
            cls,
            raw: Any,
            *,
            path: str,
            defaults: tuple[frozenset[str], frozenset[str]] | None = None,
    ) -> ConsentDefinition:
        if not isinstance(raw, dict):
            raise FilterConfigError(f"{path} must be an object")
        _reject_unknown_keys(raw, {"subscribed_statuses", "unsubscribed_statuses"}, path)

        default_subscribed, default_unsubscribed = defaults or (None, None)
        subscribed = _parse_statuses(
            raw.get("subscribed_statuses"),
            f"{path}.subscribed_statuses",
            default_subscribed,
        )
        unsubscribed = _parse_statuses(
            raw.get("unsubscribed_statuses"),
            f"{path}.unsubscribed_statuses",
            default_unsubscribed,
        )
        if subscribed is not None and unsubscribed is not None:
            overlap = subscribed.intersection(unsubscribed)
            if overlap:
                raise FilterConfigError(
                    f"{path} classifies statuses as both subscribed and unsubscribed: "
                    + ", ".join(sorted(overlap))
                )
        return cls(subscribed, unsubscribed)

    def resolved(
            self,
            *,
            fallback: ConsentDefinition | None = None,
    ) -> ConsentDefinition:
        if fallback is None:
            return self
        return ConsentDefinition(
            subscribed_statuses=(
                self.subscribed_statuses
                if self.subscribed_statuses is not None
                else fallback.subscribed_statuses
            ),
            unsubscribed_statuses=(
                self.unsubscribed_statuses
                if self.unsubscribed_statuses is not None
                else fallback.unsubscribed_statuses
            ),
        )


@dataclass(frozen=True)
class ListDefinition:
    """A list entry from the synchronization config."""

    name: str
    criteria: FilterExpression
    consent: ConsentDefinition
    list_type: str
    optin: str
    description: str
    tags: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Any, *, index: int) -> ListDefinition:
        path = f"lists[{index}]"
        if not isinstance(raw, dict):
            raise FilterConfigError(f"{path} must be an object")
        _reject_unknown_keys(
            raw,
            {"name", "criteria", "consent", "type", "optin", "description", "tags"},
            path,
        )

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FilterConfigError(f"{path}.name must be a non-empty string")
        if "criteria" not in raw:
            raise FilterConfigError(f"{path}.criteria is required")
        criteria = validate_criteria(raw["criteria"], f"{path}.criteria")

        list_type = raw.get("type", "private")
        if list_type not in {"private", "public"}:
            raise FilterConfigError(f"{path}.type must be 'private' or 'public'")
        optin = raw.get("optin", "single")
        if optin not in {"single", "double"}:
            raise FilterConfigError(f"{path}.optin must be 'single' or 'double'")
        description = raw.get("description", "Managed automatically by wix-monk.")
        if not isinstance(description, str):
            raise FilterConfigError(f"{path}.description must be a string")
        tags = raw.get("tags", ["wix-monk"])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise FilterConfigError(f"{path}.tags must be an array of strings")

        return cls(
            name=name.strip(),
            criteria=criteria,
            consent=ConsentDefinition.from_mapping(raw.get("consent", {}), path=f"{path}.consent"),
            list_type=list_type,
            optin=optin,
            description=description,
            tags=tuple(tags),
        )

    def resolved_consent(self, default: ConsentDefinition) -> ConsentDefinition:
        return self.consent.resolved(fallback=default)


@dataclass(frozen=True)
class SyncConfig:
    """Parsed synchronization configuration."""

    lists: tuple[ListDefinition, ...]
    consent: ConsentDefinition
    criteria: FilterExpression | None

    @classmethod
    def from_mapping(cls, raw: Any) -> SyncConfig:
        if not isinstance(raw, dict):
            raise FilterConfigError("config must be an object")
        _reject_unknown_keys(raw, {"lists", "consent", "criteria"}, "config")

        consent = ConsentDefinition.from_mapping(
            raw.get("consent", {}),
            path="consent",
            defaults=(frozenset({"SUBSCRIBED"}), frozenset({"UNSUBSCRIBED"})),
        )
        criteria = None
        if "criteria" in raw:
            criteria = validate_criteria(raw["criteria"], "criteria")

        raw_lists = raw.get("lists")
        if not isinstance(raw_lists, list) or not raw_lists:
            raise FilterConfigError("lists must be a non-empty array")

        lists = tuple(ListDefinition.from_mapping(item, index=index) for index, item in enumerate(raw_lists))
        names = [item.name for item in lists]
        if len(names) != len(set(names)):
            raise FilterConfigError("list names must be unique")
        for index, item in enumerate(lists):
            effective = item.resolved_consent(consent)
            overlap = _consent_overlap(effective)
            if overlap:
                raise FilterConfigError(
                    f"lists[{index}].consent classifies statuses as both subscribed "
                    "and unsubscribed after inheritance: "
                    + ", ".join(sorted(overlap))
                )
        return cls(lists=lists, consent=consent, criteria=criteria)

    @classmethod
    def load(cls, path: Path) -> SyncConfig:
        with path.open(encoding="utf-8") as file:
            raw = json.load(file)
        return cls.from_mapping(raw)


def _parse_statuses(
        raw: Any,
        path: str,
        default: frozenset[str] | None,
) -> frozenset[str] | None:
    if raw is None:
        return default
    if not isinstance(raw, list) or not all(
            isinstance(value, str) and value.strip() for value in raw
    ):
        raise FilterConfigError(f"{path} must be an array of non-empty strings")
    return frozenset(value.strip().upper() for value in raw)


def _consent_overlap(consent: ConsentDefinition) -> frozenset[str]:
    if consent.subscribed_statuses is None or consent.unsubscribed_statuses is None:
        return frozenset()
    return consent.subscribed_statuses.intersection(consent.unsubscribed_statuses)


def _reject_unknown_keys(raw: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise FilterConfigError(
            f"{path} has unknown keys: {', '.join(sorted(unknown))}"
        )
