import unittest
from typing import Any

from wix_monk.config.loading import SyncConfig
from wix_monk.domain.filtering import FilterConfigError


def valid_config() -> dict[str, Any]:
    return {
        "criteria": {"field": "email", "is_empty": False},
        "lists": [
            {
                "name": "Members",
                "criteria": {"field": "is_member", "equals": True},
            }
        ]
    }


class ConfigurationTests(unittest.TestCase):
    def test_defaults_are_applied(self):
        config = SyncConfig.from_mapping(valid_config())

        self.assertEqual(config.consent.subscribed_statuses, frozenset({"SUBSCRIBED"}))
        self.assertEqual(
            config.consent.unsubscribed_statuses,
            frozenset({"UNSUBSCRIBED"}),
        )
        self.assertIsNotNone(config.criteria)
        self.assertEqual(config.lists[0].list_type, "private")
        self.assertEqual(config.lists[0].optin, "single")

    def test_global_criteria_is_loaded(self):
        config = SyncConfig.from_mapping(valid_config())

        self.assertEqual(
            config.criteria.describe(),
            "email is_empty False",
        )

    def test_explicit_empty_list_consent_does_not_inherit(self):
        raw = valid_config()
        raw["lists"][0]["consent"] = {"subscribed_statuses": []}

        config = SyncConfig.from_mapping(raw)

        self.assertEqual(config.lists[0].consent.subscribed_statuses, frozenset())

    def test_duplicate_list_names_are_rejected(self):
        raw = valid_config()
        raw["lists"].append(dict(raw["lists"][0]))

        with self.assertRaisesRegex(FilterConfigError, "must be unique"):
            SyncConfig.from_mapping(raw)

    def test_overlapping_consent_statuses_are_rejected(self):
        raw = valid_config()
        raw["consent"] = {
            "subscribed_statuses": ["NOT_SET"],
            "unsubscribed_statuses": ["NOT_SET"],
        }

        with self.assertRaisesRegex(FilterConfigError, "both subscribed and unsubscribed"):
            SyncConfig.from_mapping(raw)

    def test_list_consent_cannot_conflict_with_inherited_denials(self):
        raw = valid_config()
        raw["lists"][0]["consent"] = {
            "subscribed_statuses": ["SUBSCRIBED", "UNSUBSCRIBED"]
        }

        with self.assertRaisesRegex(FilterConfigError, "after inheritance"):
            SyncConfig.from_mapping(raw)

    def test_unknown_keys_are_rejected(self):
        raw = valid_config()
        raw["lists"][0]["critera"] = raw["lists"][0].pop("criteria")

        with self.assertRaisesRegex(FilterConfigError, "unknown keys: critera"):
            SyncConfig.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
