from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from wix_monk.domain.models import WixContact

LOGGER = logging.getLogger("wix_monk.filtering")

FIELD_TYPES = {
    "email": "text",
    "name": "text",
    "subscription_status": "text",
    "deliverability_status": "text",
    "is_member": "boolean",
    "member_status": "text",
    "active_pricing_plan": "boolean",
    "active_plan_names": "text_array",
    "active_plan_ids": "text_array",
    "contact_ids": "text_array",
    "member_ids": "text_array",
    "phone_numbers": "text_array",
    "address_lines": "text_array",
    "cities": "text_array",
    "postal_codes": "text_array",
    "subdivisions": "text_array",
    "countries": "text_array",
    "addresses": "object_array",
    "label_keys": "text_array",
    "segment_ids": "text_array",
    "locales": "text_array",
    "source_types": "text_array",
}
OPERATORS_BY_TYPE = {
    "boolean": {"equals", "not_equals", "in", "not_in"},
    "text": {
        "equals",
        "not_equals",
        "in",
        "not_in",
        "contains_text",
        "starts_with",
        "ends_with",
        "matches_regex",
        "is_empty",
    },
    "text_array": {
        "contains",
        "contains_any",
        "contains_all",
        "contains_regex",
        "is_empty",
    },
    "object_array": {"any_match", "is_empty"},
}
ADDRESS_FIELD_TYPES = {
    "tag": "text",
    "address_line": "text",
    "formatted_address": "text",
    "city": "text",
    "postal_code": "text",
    "subdivision": "text",
    "country": "text",
}
OPERATORS = set().union(*OPERATORS_BY_TYPE.values())
COMBINATORS = {"all", "any", "not"}
MAX_REGEX_LENGTH = 256


class FilterConfigError(ValueError):
    """Raised when a criteria expression cannot be parsed or validated."""

    pass


@runtime_checkable
class FilterExpression(Protocol):
    """Protocol implemented by every parsed criteria node."""

    def matches(self, subject: Any) -> bool: ...

    def describe(self) -> str: ...

    def to_mapping(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AndFilter:
    """A filter that matches when every child matches."""

    children: tuple[FilterExpression, ...]

    def matches(self, subject: Any) -> bool:
        return all(child.matches(subject) for child in self.children)

    def describe(self) -> str:
        return "all(" + ", ".join(child.describe() for child in self.children) + ")"

    def to_mapping(self) -> dict[str, Any]:
        return {"all": [child.to_mapping() for child in self.children]}


@dataclass(frozen=True)
class OrFilter:
    """A filter that matches when any child matches."""

    children: tuple[FilterExpression, ...]

    def matches(self, subject: Any) -> bool:
        return any(child.matches(subject) for child in self.children)

    def describe(self) -> str:
        return "any(" + ", ".join(child.describe() for child in self.children) + ")"

    def to_mapping(self) -> dict[str, Any]:
        return {"any": [child.to_mapping() for child in self.children]}


@dataclass(frozen=True)
class NotFilter:
    """A filter that inverts a single child expression."""

    child: FilterExpression

    def matches(self, subject: Any) -> bool:
        return not self.child.matches(subject)

    def describe(self) -> str:
        return "not(" + self.child.describe() + ")"

    def to_mapping(self) -> dict[str, Any]:
        return {"not": self.child.to_mapping()}


@dataclass(frozen=True)
class FieldFilter:
    """A leaf filter for one field/operator/value comparison."""

    field: str
    operator: str
    value: Any
    case_sensitive: bool = False

    def matches(self, subject: Any) -> bool:
        actual_value = _field_value(subject, self.field)
        if self.operator == "equals":
            return _equals(actual_value, self.value, self.case_sensitive)
        if self.operator == "not_equals":
            return not _equals(actual_value, self.value, self.case_sensitive)
        if self.operator == "in":
            return _matches_any_value(
                actual_value,
                self.value,
                self.case_sensitive,
            )
        if self.operator == "not_in":
            return not _matches_any_value(
                actual_value,
                self.value,
                self.case_sensitive,
            )
        if self.operator == "is_empty":
            return (not bool(actual_value)) == self.value
        if self.operator == "contains_text":
            return _contains_text(actual_value, self.value, self.case_sensitive)
        if self.operator == "starts_with":
            return _starts_with(actual_value, self.value, self.case_sensitive)
        if self.operator == "ends_with":
            return _ends_with(actual_value, self.value, self.case_sensitive)
        if self.operator == "matches_regex":
            return _regex_matches(actual_value, self.value, self.case_sensitive)
        if self.operator == "contains":
            return _contains_value(actual_value, self.value, self.case_sensitive)
        if self.operator == "contains_any":
            return _contains_any_values(
                actual_value,
                self.value,
                self.case_sensitive,
            )
        if self.operator == "contains_all":
            return _contains_all_values(
                actual_value,
                self.value,
                self.case_sensitive,
            )
        if self.operator == "contains_regex":
            return _contains_regex(actual_value, self.value, self.case_sensitive)
        if self.operator == "any_match":
            return any(self.value.matches(item) for item in actual_value)
        raise AssertionError(f"Unhandled filter operator: {self.operator}")

    def describe(self) -> str:
        if self.operator == "any_match":
            return f"{self.field} any_match {self.value.describe()}"
        return f"{self.field} {self.operator} {_describe_value(self.value)}"

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "field": self.field,
            self.operator: _mapping_value(self.value),
        }
        if self.case_sensitive:
            mapping["case_sensitive"] = True
        return mapping


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def validate_criteria(criteria: Any, path: str = "criteria") -> FilterExpression:
    """Parse and validate a raw criteria mapping into a filter expression."""

    parsed = parse_criteria(criteria, path)
    LOGGER.debug("Validated %s -> %s", path, parsed.describe())
    return parsed


def parse_criteria(
        expression: Any,
        path: str = "criteria",
        field_types: Mapping[str, str] = FIELD_TYPES,
) -> FilterExpression:
    """Parse a raw criteria expression without logging."""

    if not isinstance(expression, dict):
        raise FilterConfigError(f"{path} must be an object")

    combinators = COMBINATORS.intersection(expression)
    if combinators:
        if len(combinators) != 1 or len(expression) != 1:
            raise FilterConfigError(
                f"{path} must contain exactly one of 'all', 'any', or 'not'"
            )
        combinator = next(iter(combinators))
        value = expression[combinator]
        if combinator == "not":
            parsed = NotFilter(parse_criteria(value, f"{path}.not", field_types))
            LOGGER.debug("Parsed %s -> %s", path, parsed.describe())
            return parsed
        if not _is_sequence(value) or not value:
            raise FilterConfigError(f"{path}.{combinator} must be a non-empty array")
        children = tuple(
            parse_criteria(child, f"{path}.{combinator}[{index}]", field_types)
            for index, child in enumerate(value)
        )
        parsed = AndFilter(children) if combinator == "all" else OrFilter(children)
        LOGGER.debug("Parsed %s -> %s", path, parsed.describe())
        return parsed

    field = expression.get("field")
    if field not in field_types:
        raise FilterConfigError(f"{path}.field has unknown field: {field!r}")
    allowed_keys = {"field", "case_sensitive", *OPERATORS}
    extra = set(expression) - allowed_keys
    if extra:
        raise FilterConfigError(f"{path} has unknown keys: {', '.join(sorted(extra))}")

    operators = OPERATORS.intersection(expression)
    if len(operators) != 1:
        raise FilterConfigError(f"{path} must contain exactly one filter operator")
    if "case_sensitive" in expression and not isinstance(
            expression["case_sensitive"], bool
    ):
        raise FilterConfigError(f"{path}.case_sensitive must be true or false")

    operator = next(iter(operators))
    field_type = field_types[field]
    if field_type == "boolean" and "case_sensitive" in expression:
        raise FilterConfigError(
            f"{path}.case_sensitive is not valid for boolean field {field!r}"
        )
    if operator not in OPERATORS_BY_TYPE[field_type]:
        raise FilterConfigError(
            f"{path}.{operator} is not valid for {field_type} field {field!r}"
        )

    case_sensitive = bool(expression.get("case_sensitive", False))
    value = expression[operator]
    parsed_value = _parse_operator_value(
        operator,
        field_type,
        value,
        path,
        field,
        case_sensitive,
    )
    parsed = FieldFilter(
        field=field,
        operator=operator,
        value=parsed_value,
        case_sensitive=case_sensitive,
    )
    LOGGER.debug("Parsed %s -> %s", path, parsed.describe())
    return parsed


def _parse_operator_value(
        operator: str,
        field_type: str,
        value: Any,
        path: str,
        field: str,
        case_sensitive: bool,
) -> Any:
    if operator == "any_match":
        return parse_criteria(value, f"{path}.any_match", ADDRESS_FIELD_TYPES)
    if operator in {"in", "not_in", "contains_any", "contains_all"}:
        if not _is_sequence(value) or not value:
            raise FilterConfigError(f"{path}.{operator} must be a non-empty array")
        expected_type = bool if field_type == "boolean" else str
        if not all(isinstance(item, expected_type) for item in value):
            raise FilterConfigError(
                f"{path}.{operator} values must be {expected_type.__name__}s"
            )
        return tuple(value)
    if operator == "is_empty":
        if not isinstance(value, bool):
            raise FilterConfigError(f"{path}.is_empty must be true or false")
        return value
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise FilterConfigError(f"{path}.{operator} must be true or false")
        return value
    if not isinstance(value, str):
        raise FilterConfigError(f"{path}.{operator} must be a string")
    if operator in {"matches_regex", "contains_regex"}:
        _validate_regex(value, path, operator)
    return value


def _validate_regex(pattern: str, path: str, operator: str) -> None:
    if len(pattern) > MAX_REGEX_LENGTH:
        raise FilterConfigError(
            f"{path}.{operator} exceeds the {MAX_REGEX_LENGTH}-character limit"
        )
    try:
        re.compile(pattern)
    except re.error as error:
        raise FilterConfigError(f"{path}.{operator} is invalid: {error}") from error


def _field_value(contact: Any, field: str) -> Any:
    if isinstance(contact, Mapping):
        return contact.get(field, "")
    if field == "active_pricing_plan":
        return contact.has_active_pricing_plan
    return getattr(contact, field)


def _normalize(value: Any, case_sensitive: bool) -> Any:
    if isinstance(value, str) and not case_sensitive:
        return value.casefold()
    return value


def _equals(left: Any, right: Any, case_sensitive: bool) -> bool:
    return _normalize(left, case_sensitive) == _normalize(right, case_sensitive)


def _matches_any_value(
        actual_value: Any,
        expected_values: Sequence[Any],
        case_sensitive: bool,
) -> bool:
    return any(
        _equals(actual_value, expected_value, case_sensitive)
        for expected_value in expected_values
    )


def _contains_text(actual_value: str, expected_text: str, case_sensitive: bool) -> bool:
    normalized_actual = _normalize(actual_value, case_sensitive)
    normalized_expected = _normalize(expected_text, case_sensitive)
    return normalized_expected in normalized_actual


def _starts_with(actual_value: str, prefix: str, case_sensitive: bool) -> bool:
    normalized_actual = _normalize(actual_value, case_sensitive)
    normalized_prefix = _normalize(prefix, case_sensitive)
    return normalized_actual.startswith(normalized_prefix)


def _ends_with(actual_value: str, suffix: str, case_sensitive: bool) -> bool:
    normalized_actual = _normalize(actual_value, case_sensitive)
    normalized_suffix = _normalize(suffix, case_sensitive)
    return normalized_actual.endswith(normalized_suffix)


def _contains_value(
        actual_values: Sequence[Any],
        expected_value: Any,
        case_sensitive: bool,
) -> bool:
    return any(
        _equals(actual_value, expected_value, case_sensitive)
        for actual_value in actual_values
    )


def _contains_any_values(
        actual_values: Sequence[Any],
        expected_values: Sequence[Any],
        case_sensitive: bool,
) -> bool:
    return any(
        _contains_value(actual_values, expected_value, case_sensitive)
        for expected_value in expected_values
    )


def _contains_all_values(
        actual_values: Sequence[Any],
        expected_values: Sequence[Any],
        case_sensitive: bool,
) -> bool:
    return all(
        _contains_value(actual_values, expected_value, case_sensitive)
        for expected_value in expected_values
    )


def _contains_regex(
        actual_values: Sequence[str],
        pattern: str,
        case_sensitive: bool,
) -> bool:
    return any(
        _regex_matches(actual_value, pattern, case_sensitive)
        for actual_value in actual_values
    )


def _regex_matches(value: str, pattern: str, case_sensitive: bool) -> bool:
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.search(pattern, value, flags) is not None


def matches_filter(
        contact: WixContact,
        expression: Mapping[str, Any] | FilterExpression,
) -> bool:
    """Return ``True`` when a contact satisfies a criteria expression."""

    parsed = _ensure_filter(expression)
    return parsed.matches(contact)


def describe_filter(expression: Mapping[str, Any] | FilterExpression) -> str:
    """Render a criteria expression as a human-readable string."""

    return _ensure_filter(expression).describe()


def _ensure_filter(expression: Mapping[str, Any] | FilterExpression) -> FilterExpression:
    if isinstance(expression, Mapping):
        return parse_criteria(expression)
    return expression


def _describe_value(value: Any) -> str:
    if isinstance(value, tuple):
        return "[" + ", ".join(repr(item) for item in value) + "]"
    return repr(value)


def _mapping_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, FilterExpression):
        return value.to_mapping()
    return value
