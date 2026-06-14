import logging
import unittest
from unittest.mock import Mock

from wix_monk.config.loading import SyncConfig
from wix_monk.integrations.datasets import NormalizedListmonkData, NormalizedWixData
from wix_monk.sync.service import SynchronizationService


def config() -> SyncConfig:
    return SyncConfig.from_mapping(
        {
            "lists": [
                {
                    "name": "Subscribed contacts",
                    "criteria": {"field": "email", "is_empty": False},
                }
            ]
        }
    )


def config_with_global_filter() -> SyncConfig:
    return SyncConfig.from_mapping(
        {
            "criteria": {
                "not": {
                    "field": "email",
                    "matches_regex": "@[^@]+\\.local$",
                }
            },
            "lists": [
                {
                    "name": "Subscribed contacts",
                    "criteria": {"field": "email", "is_empty": False},
                }
            ]
        }
    )


def wix_gateway(
        email: str = "person@example.com",
        first_name: str = "New",
        last_name: str = "Name",
) -> Mock:
    wix = Mock()
    wix.contacts.return_value = [
        {
            "id": "contact-1",
            "memberId": "member-1",
            "primaryEmail": {
                "email": email,
                "subscriptionStatus": "SUBSCRIBED",
                "deliverabilityStatus": "VALID",
            },
        }
    ]
    wix.orders.return_value = []
    wix.members.return_value = [
        {
            "id": "member-1",
            "contactId": "contact-1",
            "loginEmail": email,
            "status": "APPROVED",
            "contact": {
                "firstName": first_name,
                "lastName": last_name,
            },
        }
    ]
    return wix


def listmonk_gateway() -> Mock:
    listmonk = Mock()
    listmonk.lists.return_value = [{"id": 4, "name": "Subscribed contacts"}]
    listmonk.subscribers.return_value = []
    listmonk.create_subscriber.return_value = 10
    return listmonk


def wix_data() -> NormalizedWixData:
    return NormalizedWixData.load(wix_gateway())


def listmonk_data() -> NormalizedListmonkData:
    return NormalizedListmonkData.load(listmonk_gateway())


class SynchronizationServiceTests(unittest.TestCase):
    def test_dry_run_reports_plan_without_mutating_listmonk(self):
        listmonk = listmonk_gateway()
        output = []

        SynchronizationService(
            wix_data(),
            listmonk_data(),
            listmonk,
            logging.getLogger("tests"),
            output.append,
        ).run(config(), apply=False)

        self.assertIn("add=1", output[0])
        listmonk.create_subscriber.assert_not_called()
        listmonk.update_subscriber.assert_not_called()
        listmonk.change_lists.assert_not_called()

    def test_apply_creates_subscriber_and_confirms_membership(self):
        listmonk = listmonk_gateway()

        SynchronizationService(
            wix_data(),
            listmonk_data(),
            listmonk,
            logging.getLogger("tests"),
            lambda _: None,
        ).run(config(), apply=True)

        listmonk.create_subscriber.assert_called_once()
        listmonk.change_lists.assert_any_call([10], [4], "add", "confirmed")

    def test_apply_updates_existing_subscriber_name(self):
        listmonk = listmonk_gateway()
        listmonk.subscribers.return_value = [
            {
                "id": 10,
                "email": "person@example.com",
                "name": "Old Name",
                "status": "enabled",
                "attribs": {"source": "wix"},
                "lists": [],
            }
        ]
        normalized_listmonk = NormalizedListmonkData.load(listmonk)

        SynchronizationService(
            wix_data(),
            normalized_listmonk,
            listmonk,
            logging.getLogger("tests"),
            lambda _: None,
        ).run(config(), apply=True)

        listmonk.update_subscriber.assert_called_once()
        self.assertEqual(
            listmonk.update_subscriber.call_args.args[2],
            "New Name",
        )

    def test_global_criteria_can_exclude_local_domains(self):
        listmonk = listmonk_gateway()
        local_wix = NormalizedWixData.load(wix_gateway(email="person@domain.local"))
        output = []

        SynchronizationService(
            local_wix,
            listmonk_data(),
            listmonk,
            logging.getLogger("tests"),
            output.append,
        ).run(config_with_global_filter(), apply=False)

        self.assertIn("eligible_contacts=0", "\n".join(output))


if __name__ == "__main__":
    unittest.main()
