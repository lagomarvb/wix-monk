from __future__ import annotations

import base64
import json
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _basic_auth(username: str, password: str) -> str:
    """Build a Basic auth header value."""

    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def _request_json(
        base_url: str,
        headers: dict[str, str],
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any = None,
) -> Any:
    """Send a JSON request and return the decoded payload."""

    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {"Accept": "application/json", **headers}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {url} failed: HTTP {error.code}: {detail}"
        ) from error
    return json.loads(payload) if payload else None


class WixClient:
    """Thin HTTP client for the Wix API endpoints used by this tool."""

    def __init__(self, api_key: str, site_id: str, account_id: str = "") -> None:
        self.base_url = "https://www.wixapis.com"
        self.headers = {"Authorization": api_key, "wix-site-id": site_id}
        if account_id:
            self.headers["wix-account-id"] = account_id

    def _pages(self, path: str, key: str, limit: int) -> Iterable[dict[str, Any]]:
        offset = 0
        seen_ids: set[str] = set()
        while True:
            response = _request_json(
                self.base_url,
                self.headers,
                "GET",
                path,
                query={"fieldsets": "FULL", "paging.limit": limit, "paging.offset": offset},
            )
            items = response.get(key, [])
            if not items:
                return

            new_items = []
            for item in items:
                item_id = str(item.get("id") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                new_items.append(item)
            if not new_items:
                raise RuntimeError(
                    f"Wix pagination for {path} repeated a page at offset {offset}."
                )
            yield from new_items

            paging = response.get("pagingMetadata") or response.get("paging") or {}
            total = paging.get("total")
            if total is None:
                total = paging.get("totalCount")

            offset += len(items)
            if total is not None and offset >= int(total):
                return
            if total is None and len(items) == 0:
                return

    def contacts(self) -> list[dict[str, Any]]:
        return list(self._pages("/contacts/v4/contacts", "contacts", 1000))

    def orders(self) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        offset = 0
        limit = 50
        while True:
            response = _request_json(
                self.base_url,
                self.headers,
                "GET",
                "/pricing-plans/v2/orders",
                query={"fieldsets": "FULL", "limit": limit, "offset": offset},
            )
            page = response.get("orders", [])
            orders.extend(page)
            paging = response.get("pagingMetadata") or response.get("paging") or {}
            if not paging.get("hasNext", len(page) == limit):
                return orders
            if not page:
                raise RuntimeError("Wix pricing-orders pagination returned an empty next page.")
            offset += len(page)

    def members(self) -> list[dict[str, Any]]:
        members: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            response = _request_json(
                self.base_url,
                self.headers,
                "POST",
                "/members/v1/members/query",
                body={
                    "fieldsets": ["FULL"],
                    "query": {"paging": {"limit": limit, "offset": offset}},
                },
            )
            page = response.get("members", [])
            members.extend(page)
            if len(page) < limit:
                return members
            offset += limit


class ListmonkClient:
    """Thin HTTP client for the Listmonk API endpoints used by this tool."""

    def __init__(self, url: str, username: str, password: str) -> None:
        self.base_url = f"{url.rstrip('/')}/api"
        self.headers = {"Authorization": _basic_auth(username, password)}

    def _data(self, response: dict[str, Any]) -> Any:
        return response.get("data", response)

    def lists(self) -> list[dict[str, Any]]:
        response = _request_json(self.base_url, self.headers, "GET", "/lists", query={"per_page": "all"})
        data = self._data(response)
        return data.get("results", data) if isinstance(data, dict) else data

    def create_list(
            self,
            name: str,
            *,
            list_type: str = "private",
            optin: str = "single",
            description: str = "",
            tags: list[str] | None = None,
    ) -> int:
        response = _request_json(
            self.base_url,
            self.headers,
            "POST",
            "/lists",
            body={
                "name": name,
                "type": list_type,
                "optin": optin,
                "description": description,
                "tags": tags or ["wix-monk"],
            },
        )
        return int(self._data(response)["id"])

    def subscribers(self) -> list[dict[str, Any]]:
        response = _request_json(self.base_url, self.headers, "GET", "/subscribers", query={"per_page": "all"})
        data = self._data(response)
        return data.get("results", data) if isinstance(data, dict) else data

    def create_subscriber(self, email: str, name: str, attributes: dict[str, Any]) -> int:
        response = _request_json(
            self.base_url,
            self.headers,
            "POST",
            "/subscribers",
            body={"email": email, "name": name, "status": "enabled", "lists": [], "attribs": attributes},
        )
        return int(self._data(response)["id"])

    def update_subscriber(
            self,
            subscriber_id: int,
            email: str,
            name: str,
            status: str,
            attributes: dict[str, Any],
    ) -> None:
        _request_json(
            self.base_url,
            self.headers,
            "PATCH",
            f"/subscribers/{subscriber_id}",
            body={"email": email, "name": name, "status": status, "attribs": attributes},
        )

    def change_lists(
            self,
            subscriber_ids: list[int],
            list_ids: list[int],
            action: str,
            status: str | None = None,
    ) -> None:
        if not subscriber_ids or not list_ids:
            return
        body: dict[str, Any] = {
            "ids": subscriber_ids,
            "target_list_ids": list_ids,
            "action": action,
        }
        if status:
            body["status"] = status
        _request_json(self.base_url, self.headers, "PUT", "/subscribers/lists", body=body)
