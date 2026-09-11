from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from netbox_mcp_server.config import Settings
from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.write_tools import register_write_tools

DRY_RUN_VERDICT = {
    "valid": True,
    "operation": "create",
    "object_type": "dcim.site",
    "detail": "Would create dcim.site (x)",
    "_dry_run": "Validated by NetBox ... Call again with dry_run=False to execute.",
}


@pytest.fixture
def mcp_and_write_client():
    mcp = FastMCP("test")
    rest_client = NetBoxRestClient(url="http://netbox.example.com", token="test-token")
    write_mock = MagicMock()
    with patch("netbox_mcp_server.write_tools.NetBoxWriteClient", return_value=write_mock):
        register_write_tools(mcp, rest_client)
    return mcp, write_mock


class TestCreateTool:
    def test_dry_run_returns_client_verdict(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.create.return_value = DRY_RUN_VERDICT
        from netbox_mcp_server.write_tools import _last_registered

        result = _last_registered["netbox_create_object"](
            "dcim.site", {"name": "test-site"}, dry_run=True
        )
        assert result is DRY_RUN_VERDICT
        write_mock.create.assert_called_once_with(
            "dcim/sites", "dcim.site", {"name": "test-site"}, dry_run=True
        )

    def test_no_dry_run_message_when_executing(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.create.return_value = {"id": 1, "name": "test-site"}
        from netbox_mcp_server.write_tools import _last_registered

        result = _last_registered["netbox_create_object"](
            "dcim.site", {"name": "test-site"}, dry_run=False
        )
        assert "_dry_run" not in result

    def test_invalid_object_type_raises(self, mcp_and_write_client):
        from netbox_mcp_server.write_tools import _last_registered

        with pytest.raises(ValueError, match="Invalid object_type"):
            _last_registered["netbox_create_object"]("not.a.real.type", {}, dry_run=True)

    def test_uses_correct_endpoint(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.create.return_value = {"id": 1}
        from netbox_mcp_server.write_tools import _last_registered

        _last_registered["netbox_create_object"]("dcim.site", {"name": "x"}, dry_run=False)
        write_mock.create.assert_called_once_with(
            "dcim/sites", "dcim.site", {"name": "x"}, dry_run=False
        )


class TestUpdateTool:
    def test_dry_run_returns_client_verdict(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.update.return_value = DRY_RUN_VERDICT
        from netbox_mcp_server.write_tools import _last_registered

        result = _last_registered["netbox_update_object"](
            "dcim.site", 5, {"name": "updated"}, dry_run=True
        )
        assert result is DRY_RUN_VERDICT
        write_mock.update.assert_called_once_with(
            "dcim/sites", "dcim.site", 5, {"name": "updated"}, dry_run=True
        )

    def test_uses_correct_endpoint(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.update.return_value = {"id": 5}
        from netbox_mcp_server.write_tools import _last_registered

        _last_registered["netbox_update_object"]("dcim.site", 5, {"name": "x"}, dry_run=False)
        write_mock.update.assert_called_once_with(
            "dcim/sites", "dcim.site", 5, {"name": "x"}, dry_run=False
        )


class TestDeleteTool:
    def test_dry_run_returns_client_verdict(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        verdict = {"valid": True, "operation": "delete", "_dry_run": "Validated ..."}
        write_mock.delete.return_value = verdict
        from netbox_mcp_server.write_tools import _last_registered

        result = _last_registered["netbox_delete_object"]("dcim.site", 7, dry_run=True)
        assert result is verdict

    def test_real_delete_returns_deleted_true(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.delete.return_value = True
        from netbox_mcp_server.write_tools import _last_registered

        result = _last_registered["netbox_delete_object"]("dcim.site", 7, dry_run=False)
        assert result == {"deleted": True, "object_type": "dcim.site", "object_id": 7}
        assert "_dry_run" not in result

    def test_uses_correct_endpoint(self, mcp_and_write_client):
        _, write_mock = mcp_and_write_client
        write_mock.delete.return_value = True
        from netbox_mcp_server.write_tools import _last_registered

        _last_registered["netbox_delete_object"]("dcim.site", 7, dry_run=False)
        write_mock.delete.assert_called_once_with("dcim/sites", "dcim.site", 7, dry_run=False)


class TestSettingsWiring:
    def test_settings_forwarded_to_write_client(self):
        mcp = FastMCP("test-settings")
        rest_client = NetBoxRestClient(url="http://netbox.example.com", token="test-token")
        settings = Settings(
            netbox_url="http://netbox.example.com/",
            netbox_token="test-token",
            dry_run_script="custom_module.CustomValidator",
            dry_run_timeout=5.0,
        )
        with patch("netbox_mcp_server.write_tools.NetBoxWriteClient") as write_cls:
            register_write_tools(mcp, rest_client, settings)
        write_cls.assert_called_once_with(
            rest_client,
            dry_run_script="custom_module.CustomValidator",
            dry_run_timeout=5.0,
        )
