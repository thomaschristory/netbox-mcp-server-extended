# NetBox-side dry-run script

`netbox_mcp_server_extended.py` is a NetBox [custom script](https://netboxlabs.com/docs/netbox/customization/custom-scripts/)
that backs the write tools' `dry_run=True` mode. The MCP server executes it via
`POST /api/extras/scripts/netbox_mcp_server_extended.MCPWriteValidator/` with `"commit": false`, which
makes NetBox run the requested change inside a database transaction and roll it
back unconditionally (NetBox core behavior — nothing persists, no webhooks or
event rules fire). The script validates create/update payloads with the same
REST serializers the API uses, and validates deletes by attempting them (so
protected references are detected).

The script refuses `commit=true`: it is a validator, never a writer. Real
writes always go through the normal REST API with the token's permissions.

## Requirements

- NetBox 4.0–4.7 (the script mechanism was verified against the newest tag of
  each minor line; on 4.0.x a failing dry run reports job status `failed`
  instead of `completed`, which the MCP server tolerates). Note: on 4.1.9–4.1.11
  and 4.2.0–4.2.4, NetBox may still fire event rules/webhooks for rolled-back
  dry-run changes (fixed in 4.2.5); the database rollback itself is unaffected
- A running RQ worker on the `default` queue (`netbox-rq` on standard installs)
- On NetBox 4.6.8+ and 4.7, the API token must have **write ability** enabled —
  NetBox rejects script execution from read-only tokens even with commit=false
- Custom scripts are deprecated in NetBox 4.7 and will be removed in 5.0
  (~May 2027) in favor of a dedicated plugin; this backend will need
  re-targeting then — tracked in
  [issue #39](https://github.com/thomaschristory/netbox-mcp-server-extended/issues/39)

## Install

Copy the file into `SCRIPTS_ROOT` (default `$INSTALL_ROOT/netbox/scripts/`):

```sh
cp netbox_mcp_server_extended.py /opt/netbox/netbox/scripts/netbox_mcp_server_extended.py
```

The distribution also carries a copy, so an install from PyPI does not need a
checkout. This command prints its path:

```sh
python -c "from netbox_mcp_server.netbox_write_client import packaged_script_path; print(packaged_script_path())"
```

or upload it via the REST API (NetBox 4.5.7+ / 4.6.0+ only; a one-time step —
use an admin-grade token here, since the upload endpoint requires
`extras.add_scriptmodule` and `core.add_managedfile`, which the MCP server's
day-to-day token should not carry):

```sh
curl -X POST https://netbox.example.com/api/extras/scripts/upload/ \
  -H "Authorization: Token $NETBOX_ADMIN_TOKEN" \
  -F "file=@netbox_mcp_server_extended.py"
```

No worker or service restart is needed; NetBox re-reads the script from
storage on each run.

## Permissions

The MCP server's NetBox token needs, in addition to its normal object
permissions:

- the `run` action on Extras > Script (`extras.run_script`)
- `view` on Extras > Script, Extras > Script Module, and Core > Managed File
- `view` on Core > Job (`core.view_job`) — the server polls the script job
  for the verdict

**Warning: constrain the `run` permission to this script.** An unconstrained
`extras.run_script` permission lets the token run every script installed on that
NetBox instance. That ability is much larger than create, update, and delete on
the object types the MCP tools expose. In the permission for the `run` action,
set this constraint:

```json
{ "name": "MCP Write Validator" }
```

NetBox then refuses a run of any other script with the same token. Apply the
same idea to the `view` permissions if you keep them narrow.

## Configuration (MCP server side)

- `DRY_RUN_SCRIPT` — script identifier, default `netbox_mcp_server_extended.MCPWriteValidator`
  (`<filename-without-.py>.<ClassName>`; adjust if you rename the file)
- `DRY_RUN_TIMEOUT` — seconds to wait for the script job, default `60`

If the script is not installed or no RQ worker is running, dry runs fail with
an explanatory error. They never fall back to performing the real write.
