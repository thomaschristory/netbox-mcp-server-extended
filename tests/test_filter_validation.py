"""Tests for filter validation."""

from unittest.mock import patch

import pytest

from netbox_mcp_server.server import netbox_get_changelogs, validate_filters


def test_direct_field_filters_pass():
    """Direct field filters should pass validation."""
    validate_filters({"site_id": 1, "name": "router", "status": "active"})


def test_lookup_suffixes_pass():
    """Lookup suffixes should pass validation."""
    validate_filters({"name__ic": "switch", "vid__gte": 100})


def test_relationship_id_in_lookup_rejected():
    """Relationship ID list filters are unsafe because NetBox may ignore them."""
    with pytest.raises(ValueError, match="'__in' lookup suffix is not supported"):
        validate_filters({"vminterface_id__in": [621493, 631527]})


def test_object_id_in_lookup_rejected():
    """Even id__in is silently ignored by NetBox on many endpoints."""
    with pytest.raises(ValueError, match=r"'id': \[1, 2, 3\]"):
        validate_filters({"id__in": [1, 2, 3]})


def test_special_parameters_ignored():
    """Special parameters like limit, offset should be ignored."""
    validate_filters({"limit": 10, "offset": 5, "fields": "id,name", "q": "search"})


def test_multi_hop_filters_rejected():
    """Multi-hop relationship traversal should be rejected."""
    with pytest.raises(ValueError, match="Multi-hop relationship traversal"):
        validate_filters({"device__site_id": 1})


def test_nested_relationships_rejected():
    """Deeply nested relationships should be rejected."""
    with pytest.raises(ValueError, match="Multi-hop relationship traversal"):
        validate_filters({"interface__device__site": "dc1"})


def test_error_message_helpful():
    """Error message should mention the invalid filter and suggest alternatives."""
    with pytest.raises(ValueError, match="Multi-hop relationship traversal"):
        validate_filters({"device__site_id": 1})


@patch("netbox_mcp_server.server.netbox")
def test_changelogs_rejects_invalid_filters(mock_netbox):
    """netbox_get_changelogs validates filters before calling the API."""
    with pytest.raises(ValueError, match="'__in' lookup suffix is not supported"):
        netbox_get_changelogs({"changed_object_id__in": [1, 2, 3]})
    mock_netbox.get.assert_not_called()


@patch("netbox_mcp_server.server.netbox")
def test_changelogs_valid_filters_reach_api(mock_netbox):
    """Valid changelog filters are forwarded to the NetBox API."""
    mock_netbox.get.return_value = {"count": 0, "results": []}

    netbox_get_changelogs({"action": "delete"})

    mock_netbox.get.assert_called_once()
    assert mock_netbox.get.call_args[1]["params"] == {"action": "delete"}
