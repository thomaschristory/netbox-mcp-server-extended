"""Integration tests for the write tools against a real NetBox instance.

These tests exercise ``netbox_create_object``, ``netbox_update_object`` and
``netbox_delete_object`` end to end against a live NetBox API, using a
throwaway ``extras.tag`` object that has no dependencies. They are skipped
automatically unless both ``NETBOX_URL`` and ``NETBOX_TOKEN`` are set, matching
the environment the CI ``test`` job (``.github/workflows/test.yml``) exports.

The write tools are invoked through ``write_tools._last_registered`` (the same
accessor used by ``tests/test_write_tools.py``) and the read tools through
``server.netbox_get_objects`` / ``server.netbox_get_object_by_id``. The module
global ``server.netbox`` is patched to the live client so the read tools work.
"""

import os
import uuid

import httpx2
import pytest
from fastmcp import FastMCP

from netbox_mcp_server import server
from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.write_tools import _last_registered, register_write_tools

pytestmark = pytest.mark.skipif(
    not (os.environ.get("NETBOX_URL") and os.environ.get("NETBOX_TOKEN")),
    reason="Live NetBox instance required: set NETBOX_URL and NETBOX_TOKEN",
)

TAG_TYPE = "extras.tag"
TAG_ENDPOINT = "extras/tags"
MISSING_OBJECT_ID = 999999999


def _delete_tags_by_slug(client: NetBoxRestClient, slug: str) -> None:
    """Best-effort delete of every tag matching ``slug`` (used for teardown).

    Args:
        client: Live NetBox REST client.
        slug: Slug of the throwaway tags to remove.
    """
    response = client.get(TAG_ENDPOINT, params={"slug": slug})
    results = response.get("results", []) if isinstance(response, dict) else []
    for obj in results:
        try:
            deleted = client.session.delete(client._build_url(TAG_ENDPOINT, obj["id"]))
            deleted.raise_for_status()
        except httpx2.HTTPError:
            # Cleanup is best-effort; a failed delete must not mask test results.
            pass


@pytest.fixture
def live_client(monkeypatch: pytest.MonkeyPatch) -> NetBoxRestClient:
    """Build a live NetBox client, register the write tools, and wire read tools.

    The write tools are registered so they populate ``_last_registered``, and
    the module global ``server.netbox`` is patched so the read tools operate
    against the same live instance.

    Args:
        monkeypatch: Pytest fixture used to patch ``server.netbox``.

    Returns:
        The live ``NetBoxRestClient`` bound to the configured instance.
    """
    url = os.environ["NETBOX_URL"]
    token = os.environ["NETBOX_TOKEN"]
    verify_ssl = os.environ.get("NETBOX_VERIFY_SSL", "true").lower() != "false"
    client = NetBoxRestClient(url=url, token=token, verify_ssl=verify_ssl)
    register_write_tools(FastMCP("test-integration"), client)
    monkeypatch.setattr(server, "netbox", client)
    return client


@pytest.fixture
def throwaway_slug(live_client: NetBoxRestClient) -> str:
    """Yield a unique tag slug and delete any matching tags on teardown.

    Args:
        live_client: Live NetBox client used to clean up created tags.

    Yields:
        A slug unique to the test, safe to create and destroy.
    """
    slug = f"mcp-test-{uuid.uuid4().hex[:12]}"
    try:
        yield slug
    finally:
        _delete_tags_by_slug(live_client, slug)


class TestDryRun:
    def test_dry_run_default_returns_flag_and_no_mutation(
        self, live_client: NetBoxRestClient, throwaway_slug: str
    ) -> None:
        create = _last_registered["netbox_create_object"]

        result = create(TAG_TYPE, {"name": throwaway_slug, "slug": throwaway_slug})

        assert "_dry_run" in result
        assert "dry_run=False" in result["_dry_run"]
        listing = server.netbox_get_objects(TAG_TYPE, {"slug": throwaway_slug})
        assert listing["count"] == 0


class TestLifecycle:
    def test_create_read_update_delete(
        self, live_client: NetBoxRestClient, throwaway_slug: str
    ) -> None:
        create = _last_registered["netbox_create_object"]
        update = _last_registered["netbox_update_object"]
        delete = _last_registered["netbox_delete_object"]

        created = create(
            TAG_TYPE,
            {"name": throwaway_slug, "slug": throwaway_slug, "color": "00ff00"},
            dry_run=False,
        )
        assert "_dry_run" not in created
        object_id = created["id"]
        assert object_id > 0

        fetched = server.netbox_get_object_by_id(
            TAG_TYPE, object_id, fields=["id", "slug", "color"]
        )
        assert fetched["id"] == object_id
        assert fetched["slug"] == throwaway_slug
        assert fetched["color"] == "00ff00"

        updated = update(TAG_TYPE, object_id, {"color": "ff0000"}, dry_run=False)
        assert "_dry_run" not in updated
        assert updated["color"] == "ff0000"

        refetched = server.netbox_get_object_by_id(TAG_TYPE, object_id, fields=["id", "color"])
        assert refetched["color"] == "ff0000"

        deleted = delete(TAG_TYPE, object_id, dry_run=False)
        assert deleted == {
            "deleted": True,
            "object_type": TAG_TYPE,
            "object_id": object_id,
        }

        listing = server.netbox_get_objects(TAG_TYPE, {"slug": throwaway_slug})
        assert listing["count"] == 0


class TestErrors:
    def test_invalid_object_type_raises(self, live_client: NetBoxRestClient) -> None:
        create = _last_registered["netbox_create_object"]

        with pytest.raises(ValueError, match="Invalid object_type"):
            create("not.a.real.type", {"name": "x"}, dry_run=True)

    def test_missing_required_fields_raises(self, live_client: NetBoxRestClient) -> None:
        create = _last_registered["netbox_create_object"]

        with pytest.raises(httpx2.HTTPStatusError):
            create(TAG_TYPE, {}, dry_run=False)

    def test_update_nonexistent_object_raises(self, live_client: NetBoxRestClient) -> None:
        update = _last_registered["netbox_update_object"]

        with pytest.raises(httpx2.HTTPStatusError):
            update(TAG_TYPE, MISSING_OBJECT_ID, {"color": "ff0000"}, dry_run=False)

    def test_delete_nonexistent_object_raises(self, live_client: NetBoxRestClient) -> None:
        delete = _last_registered["netbox_delete_object"]

        with pytest.raises(httpx2.HTTPStatusError):
            delete(TAG_TYPE, MISSING_OBJECT_ID, dry_run=False)


class TestReadToolsAfterWrite:
    def test_read_tools_work_after_write(
        self, live_client: NetBoxRestClient, throwaway_slug: str
    ) -> None:
        create = _last_registered["netbox_create_object"]
        delete = _last_registered["netbox_delete_object"]

        created = create(
            TAG_TYPE,
            {"name": throwaway_slug, "slug": throwaway_slug},
            dry_run=False,
        )
        object_id = created["id"]

        listing = server.netbox_get_objects(TAG_TYPE, {})
        assert isinstance(listing["results"], list)

        fetched = server.netbox_get_object_by_id(TAG_TYPE, object_id, fields=["id", "slug"])
        assert fetched["slug"] == throwaway_slug

        delete(TAG_TYPE, object_id, dry_run=False)
