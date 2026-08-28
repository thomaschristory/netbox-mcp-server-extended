from typing import Any

from fastmcp import FastMCP

from netbox_mcp_server.config import Settings
from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES
from netbox_mcp_server.netbox_write_client import NetBoxWriteClient

_last_registered: dict[str, Any] = {}

DRY_RUN_NOTE = (
    "With dry_run=True (default), NetBox itself validates the change via the "
    "MCPWriteValidator script and rolls everything back — nothing persists, and "
    "the response reports 'valid' plus any errors. Requires the script and an "
    "RQ worker on the NetBox side; if missing, the dry run fails instead of "
    "writing. Pass dry_run=False to execute."
)


def _resolve_endpoint(object_type: str) -> str:
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")
    return NETBOX_OBJECT_TYPES[object_type]["endpoint"]


def register_write_tools(
    mcp: FastMCP, client: NetBoxRestClient, settings: Settings | None = None
) -> None:
    """Register the create/update/delete tools on the MCP server.

    Args:
        mcp: FastMCP instance to register the tools on.
        client: NetBox REST client used for real writes and dry-run execution.
        settings: Optional server settings supplying the dry-run script name
            and timeout; when omitted, the module defaults apply.
    """
    if settings is not None:
        write_client = NetBoxWriteClient(
            client,
            dry_run_script=settings.dry_run_script,
            dry_run_timeout=settings.dry_run_timeout,
        )
    else:
        write_client = NetBoxWriteClient(client)

    @mcp.tool(
        description=(
            f"Create a new NetBox object. {DRY_RUN_NOTE}\n\n"
            "Uses the same object_type values as netbox_get_objects (e.g. 'dcim.site', "
            "'ipam.ipaddress'). The data dict should match the NetBox API POST body "
            "for that type."
        )
    )
    def netbox_create_object(
        object_type: str,
        data: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        endpoint = _resolve_endpoint(object_type)
        return write_client.create(endpoint, object_type, data, dry_run=dry_run)

    @mcp.tool(
        description=(
            "Update an existing NetBox object (partial update — only supplied fields "
            f"change). {DRY_RUN_NOTE}\n\n"
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
        return write_client.update(endpoint, object_type, object_id, data, dry_run=dry_run)

    @mcp.tool(
        description=(
            f"Delete a NetBox object. {DRY_RUN_NOTE}\n\n"
            "Uses the same object_type values as netbox_get_objects."
        )
    )
    def netbox_delete_object(
        object_type: str,
        object_id: int,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        endpoint = _resolve_endpoint(object_type)
        result = write_client.delete(endpoint, object_type, object_id, dry_run=dry_run)
        if isinstance(result, dict):
            # Script-backed dry runs return the structured verdict directly.
            return result
        return {
            "deleted": bool(result),
            "object_type": object_type,
            "object_id": object_id,
        }

    _last_registered["netbox_create_object"] = netbox_create_object
    _last_registered["netbox_update_object"] = netbox_update_object
    _last_registered["netbox_delete_object"] = netbox_delete_object
