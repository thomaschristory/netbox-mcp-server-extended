from typing import Any

from fastmcp import FastMCP

from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES
from netbox_mcp_server.netbox_write_client import NetBoxWriteClient

_last_registered: dict[str, Any] = {}

DRY_RUN_MSG = "Dry run succeeded. Call again with dry_run=False to execute."


def _resolve_endpoint(object_type: str) -> str:
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")
    return NETBOX_OBJECT_TYPES[object_type]["endpoint"]


def register_write_tools(mcp: FastMCP, client: NetBoxRestClient) -> None:
    write_client = NetBoxWriteClient(client)

    @mcp.tool(
        description=(
            "Create a new NetBox object. Pass dry_run=True (default) to validate without "
            "writing — response will include '_dry_run' with instructions to execute for real.\n\n"
            "Uses the same object_type values as netbox_get_objects (e.g. 'dcim.site', "
            "'ipam.ipaddress'). The data dict should match the NetBox API POST body for that type."
        )
    )
    def netbox_create_object(
        object_type: str,
        data: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        endpoint = _resolve_endpoint(object_type)
        result = write_client.create(endpoint, data, dry_run=dry_run)
        if dry_run:
            result["_dry_run"] = DRY_RUN_MSG
        return result

    @mcp.tool(
        description=(
            "Update an existing NetBox object (partial update — only supplied fields change). "
            "Pass dry_run=True (default) to validate without writing.\n\n"
            "Uses the same object_type values as netbox_get_objects. "
            "The data dict should contain only the fields you want to change."
        )
    )
    def netbox_update_object(
        object_type: str,
        object_id: int,
        data: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        endpoint = _resolve_endpoint(object_type)
        result = write_client.update(endpoint, object_id, data, dry_run=dry_run)
        if dry_run:
            result["_dry_run"] = DRY_RUN_MSG
        return result

    @mcp.tool(
        description=(
            "Delete a NetBox object. Pass dry_run=True (default) to validate without deleting. "
            "Pass dry_run=False to execute the deletion.\n\n"
            "Uses the same object_type values as netbox_get_objects."
        )
    )
    def netbox_delete_object(
        object_type: str,
        object_id: int,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        endpoint = _resolve_endpoint(object_type)
        deleted = write_client.delete(endpoint, object_id, dry_run=dry_run)
        result: dict[str, Any] = {
            "deleted": deleted,
            "object_type": object_type,
            "object_id": object_id,
        }
        if dry_run:
            result["_dry_run"] = DRY_RUN_MSG
        return result

    _last_registered["netbox_create_object"] = netbox_create_object
    _last_registered["netbox_update_object"] = netbox_update_object
    _last_registered["netbox_delete_object"] = netbox_delete_object
