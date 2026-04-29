from typing import Any

from netbox_mcp_server.netbox_client import NetBoxRestClient


class NetBoxWriteClient:
    """Wraps NetBoxRestClient to add dry_run support for write operations."""

    def __init__(self, client: NetBoxRestClient) -> None:
        self._client = client

    def create(self, endpoint: str, data: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
        url = self._client._build_url(endpoint)
        params = {"dry_run": "true"} if dry_run else {}
        response = self._client.session.post(url, json=data, params=params)
        response.raise_for_status()
        return response.json()

    def update(
        self, endpoint: str, object_id: int, data: dict[str, Any], dry_run: bool = True
    ) -> dict[str, Any]:
        url = self._client._build_url(endpoint, object_id)
        params = {"dry_run": "true"} if dry_run else {}
        response = self._client.session.patch(url, json=data, params=params)
        response.raise_for_status()
        return response.json()

    def delete(self, endpoint: str, object_id: int, dry_run: bool = True) -> bool:
        url = self._client._build_url(endpoint, object_id)
        params = {"dry_run": "true"} if dry_run else {}
        response = self._client.session.delete(url, params=params)
        response.raise_for_status()
        return response.status_code == 204
