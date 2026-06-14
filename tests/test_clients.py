import unittest
from unittest.mock import patch

import wix_monk.integrations.clients as clients_module
from wix_monk.integrations.clients import ListmonkClient, WixClient


class ListmonkClientTests(unittest.TestCase):
    def test_create_list_uses_private_single_optin_defaults(self):
        client = ListmonkClient("https://example.test", "user", "password")
        with patch.object(clients_module, "_request_json", return_value={"data": {"id": 12}}) as request:
            list_id = client.create_list("All Wix contacts")

        self.assertEqual(list_id, 12)
        request.assert_called_once_with(
            "https://example.test/api",
            {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="},
            "POST",
            "/lists",
            body={
                "name": "All Wix contacts",
                "type": "private",
                "optin": "single",
                "description": "",
                "tags": ["wix-monk"],
            },
        )

    def test_subscriber_update_uses_patch_to_preserve_lists(self):
        client = ListmonkClient("https://example.test", "user", "password")
        with patch.object(clients_module, "_request_json") as request:
            client.update_subscriber(7, "person@example.com", "Person", "enabled", {})

        request.assert_called_once_with(
            "https://example.test/api",
            {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="},
            "PATCH",
            "/subscribers/7",
            body={
                "email": "person@example.com",
                "name": "Person",
                "status": "enabled",
                "attribs": {},
            },
        )

    def test_unsubscribe_uses_list_action_without_status(self):
        client = ListmonkClient("https://example.test", "user", "password")
        with patch.object(clients_module, "_request_json") as request:
            client.change_lists([7], [2], "unsubscribe")

        request.assert_called_once_with(
            "https://example.test/api",
            {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="},
            "PUT",
            "/subscribers/lists",
            body={"ids": [7], "target_list_ids": [2], "action": "unsubscribe"},
        )


class WixClientTests(unittest.TestCase):
    def test_orders_use_top_level_limit_and_offset(self):
        client = WixClient("key", "site")
        with patch.object(
            clients_module,
            "_request_json",
            side_effect=[
                {
                    "orders": [{"id": "order-1"}, {"id": "order-2"}],
                    "pagingMetadata": {"count": 2, "offset": 0, "hasNext": True},
                },
                {
                    "orders": [{"id": "order-3"}],
                    "pagingMetadata": {"count": 1, "offset": 2, "hasNext": False},
                },
            ],
        ) as request:
            orders = client.orders()

        self.assertEqual([order["id"] for order in orders], ["order-1", "order-2", "order-3"])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].kwargs["query"]["offset"], 2)
        self.assertEqual(request.call_args_list[0].kwargs["query"]["limit"], 50)

    def test_members_uses_query_endpoint(self):
        client = WixClient("key", "site")
        with patch.object(clients_module, "_request_json", return_value={"members": [{"id": "member-1"}]}) as request:
            members = client.members()

        self.assertEqual(members, [{"id": "member-1"}])
        request.assert_called_once_with(
            "https://www.wixapis.com",
            {"Authorization": "key", "wix-site-id": "site"},
            "POST",
            "/members/v1/members/query",
            body={
                "fieldsets": ["FULL"],
                "query": {"paging": {"limit": 100, "offset": 0}},
            },
        )


if __name__ == "__main__":
    unittest.main()
