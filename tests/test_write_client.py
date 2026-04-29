from unittest.mock import MagicMock, patch

import pytest

from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_write_client import NetBoxWriteClient


@pytest.fixture
def client():
    return NetBoxRestClient(url="http://netbox.example.com", token="test-token")


@pytest.fixture
def write_client(client):
    return NetBoxWriteClient(client)


def make_response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.raise_for_status = MagicMock()
    return response


class TestCreate:
    def test_dry_run_passes_query_param(self, client, write_client):
        resp = make_response(200, {"id": 1, "name": "test-site"})
        with patch.object(client.session, "post", return_value=resp) as mock_post:
            write_client.create("dcim/sites", {"name": "test-site"}, dry_run=True)
        mock_post.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/",
            json={"name": "test-site"},
            params={"dry_run": "true"},
        )

    def test_real_create_omits_dry_run_param(self, client, write_client):
        resp = make_response(201, {"id": 1, "name": "test-site"})
        with patch.object(client.session, "post", return_value=resp) as mock_post:
            write_client.create("dcim/sites", {"name": "test-site"}, dry_run=False)
        mock_post.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/",
            json={"name": "test-site"},
            params={},
        )

    def test_returns_json_body(self, client, write_client):
        resp = make_response(200, {"id": 42, "name": "my-site"})
        with patch.object(client.session, "post", return_value=resp):
            result = write_client.create("dcim/sites", {"name": "my-site"}, dry_run=True)
        assert result == {"id": 42, "name": "my-site"}


class TestUpdate:
    def test_dry_run_patches_correct_url(self, client, write_client):
        resp = make_response(200, {"id": 5, "name": "updated"})
        with patch.object(client.session, "patch", return_value=resp) as mock_patch:
            write_client.update("dcim/sites", 5, {"name": "updated"}, dry_run=True)
        mock_patch.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/5/",
            json={"name": "updated"},
            params={"dry_run": "true"},
        )

    def test_real_update_omits_dry_run_param(self, client, write_client):
        resp = make_response(200, {"id": 5, "name": "updated"})
        with patch.object(client.session, "patch", return_value=resp) as mock_patch:
            write_client.update("dcim/sites", 5, {"name": "updated"}, dry_run=False)
        mock_patch.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/5/",
            json={"name": "updated"},
            params={},
        )


class TestDelete:
    def test_dry_run_passes_query_param(self, client, write_client):
        resp = make_response(204)
        with patch.object(client.session, "delete", return_value=resp) as mock_del:
            write_client.delete("dcim/sites", 7, dry_run=True)
        mock_del.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/7/",
            params={"dry_run": "true"},
        )

    def test_returns_true_on_204(self, client, write_client):
        resp = make_response(204)
        with patch.object(client.session, "delete", return_value=resp):
            result = write_client.delete("dcim/sites", 7, dry_run=False)
        assert result is True

    def test_real_delete_omits_dry_run_param(self, client, write_client):
        resp = make_response(204)
        with patch.object(client.session, "delete", return_value=resp) as mock_del:
            write_client.delete("dcim/sites", 7, dry_run=False)
        mock_del.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/7/",
            params={},
        )
