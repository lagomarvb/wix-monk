import unittest
from unittest.mock import Mock

from wix_monk.integrations.datasets import WixDataset


class WixDatasetTests(unittest.TestCase):
    def test_load_fetches_each_source_once_and_normalizes_contacts(self):
        wix = Mock()
        wix.contacts.return_value = [
            {
                "id": "contact-1",
                "primaryEmail": {
                    "email": "Person@example.com",
                    "subscriptionStatus": "SUBSCRIBED",
                },
            }
        ]
        wix.orders.return_value = []
        wix.members.return_value = []

        dataset = WixDataset.load(wix)

        self.assertEqual(dataset.contacts[0].email, "person@example.com")
        wix.contacts.assert_called_once_with()
        wix.orders.assert_called_once_with()
        wix.members.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
