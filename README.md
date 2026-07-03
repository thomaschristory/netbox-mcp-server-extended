# netbox-mcp-server-extended

> **Write-enabled fork of [`netboxlabs/netbox-mcp-server`](https://github.com/netboxlabs/netbox-mcp-server).**
> Tracks upstream automatically via weekly CI rebase. All original read-only tools are preserved unchanged.

## Extended tools (this fork)

Three new tools, each with `dry_run=True` by default:

| Tool | Description |
|------|-------------|
| `netbox_create_object(object_type, data, dry_run=True)` | Create any NetBox object |
| `netbox_update_object(object_type, object_id, data, dry_run=True)` | Partial-update any NetBox object |
| `netbox_delete_object(object_type, object_id, dry_run=True)` | Delete any NetBox object |

All three accept the same `object_type` values as the read tools (100+ types).

**Dry run is the default.** Every write tool returns a `_dry_run` key with instructions when called without `dry_run=False`:

```
"_dry_run": "Dry run succeeded. Call again with dry_run=False to execute."
```

## Write tools: usage & safety

All three write tools default to `dry_run=True`. A dry run sends the request to NetBox with `?dry_run=true`, so NetBox fully validates the payload (permissions, required fields, uniqueness) without persisting anything. Re-run with `dry_run=False` to commit.

### Dry-run walkthrough

```python
# 1. Dry run (default) — validates but does not write
netbox_create_object(
    object_type="extras.tag",
    data={"name": "decommissioned", "slug": "decommissioned", "color": "9e9e9e"},
)
# → {
#     "id": 42, "name": "decommissioned", "slug": "decommissioned", ...,
#     "_dry_run": "Dry run succeeded. Call again with dry_run=False to execute."
#   }

# 2. Commit — same call with dry_run=False
netbox_create_object(
    object_type="extras.tag",
    data={"name": "decommissioned", "slug": "decommissioned", "color": "9e9e9e"},
    dry_run=False,
)
# → {"id": 42, "name": "decommissioned", "slug": "decommissioned", "color": "9e9e9e", ...}
```

The presence of the `_dry_run` key means nothing was written. Once you pass `dry_run=False`, the change is live.

### Examples per tool

```python
# Create — add a tag
netbox_create_object(
    object_type="extras.tag",
    data={"name": "decommissioned", "slug": "decommissioned", "color": "9e9e9e"},
    dry_run=False,
)

# Update — set a device's status to "offline"
# (partial update: only the supplied fields change)
netbox_update_object(
    object_type="dcim.device",
    object_id=123,
    data={"status": "offline"},
    dry_run=False,
)

# Delete — remove a prefix by ID
netbox_delete_object(
    object_type="ipam.prefix",
    object_id=456,
    dry_run=False,
)
# → {"deleted": true, "object_type": "ipam.prefix", "object_id": 456}
```

`object_type` accepts the same dotted `app_label.model` values as the read tools (e.g. `extras.tag`, `dcim.device`, `ipam.prefix`). Calling a write tool with an invalid type returns the full list of valid types.

### Safety guidance

- **Use a read-only token unless you need writes.** The write tools require a NetBox token with write permissions; if you only query data, keep using a read-only token so the tools physically cannot change anything.
- **Scope write tokens narrowly.** Grant only the object permissions you actually intend to modify.
- **Always dry-run first.** Leave `dry_run=True` (the default) for the initial call, review the returned object, then repeat with `dry_run=False`. This is the recommended workflow for LLM-driven changes: the model proposes a change, you inspect the dry-run result, then approve the commit.
- **Deletes are irreversible.** Confirm the `object_id` from a dry run before committing a delete.

### Enabling write tools in Claude Code

The write tools register automatically when the server starts — no extra flag is needed. Add the extended server with a write-capable token:

```bash
claude mcp add --transport stdio netbox \
  --env NETBOX_URL=https://netbox.example.com/ \
  --env NETBOX_TOKEN=<your-write-token> \
  -- uv --directory /path/to/netbox-mcp-server-extended run netbox-mcp-server
```

Or in a Claude Desktop / MCP client config file:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": [
                "--directory",
                "/path/to/netbox-mcp-server-extended",
                "run",
                "netbox-mcp-server"
            ],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-write-token>"
            }
        }
    }
}
```

After adding, verify with `/mcp` in Claude Code — you should see `netbox_create_object`, `netbox_update_object`, and `netbox_delete_object` alongside the read tools.

## Versioning

Releases follow PEP 440 post-release: `1.1.0.post1`, `1.1.0.post2`, etc.
When upstream releases a new version, the `.post` counter resets: `1.2.0.post1`.

---

<!-- Original upstream README below -->

# NetBox MCP Server

> **⚠️ Breaking Change in v1.0.0**: The project structure has changed.
> If upgrading from v0.1.0, update your configuration:
> - Change `uv run server.py` to `uv run netbox-mcp-server`
> - Update Claude Desktop/Code configs to use `netbox-mcp-server` instead of `server.py`
> - Docker users: rebuild images with updated CMD
> - See [CHANGELOG.md](CHANGELOG.md) for full details

This is a simple read-only [Model Context Protocol](https://modelcontextprotocol.io/) server for NetBox. It enables you to interact with your data in NetBox directly via LLMs that support MCP.

The server is intentionally simple — easy to get started with, hard to misuse (read-only by default, no plugin surface), and easy to fork and adapt. Forking under Apache 2.0 is a first-class path for users who need capabilities beyond the project's scope.

## Tools

| Tool | Description |
|------|-------------|
| get_objects | Retrieves NetBox core objects based on their type and filters |
| get_object_by_id | Gets detailed information about a specific NetBox object by its ID |
| get_changelogs | Retrieves change history records (audit trail) based on filters |

> Note: Core NetBox object types are always available. Plugin object types can be auto-discovered — see [Plugin Object Type Discovery](#plugin-object-type-discovery). Advanced features (GraphQL, dynamic model discovery, etc.) are deliberately out of scope — see [CONTRIBUTING.md](CONTRIBUTING.md) for the full scope statement and rationale.

## Usage

1. Create a read-only API token in NetBox with sufficient permissions for the tool to access the data you want to make available via MCP.

2. Install dependencies:

    ```bash
    # Using UV (recommended)
    uv sync

    # Or using pip
    pip install -e .
    ```

3. Verify the server can run: `NETBOX_URL=https://netbox.example.com/ NETBOX_TOKEN=<your-api-token> uv run netbox-mcp-server`

4. Add the MCP server to your LLM client. See below for some examples with Claude.

### Claude Code

#### Stdio Transport (Default)

Add the server using the `claude mcp add` command:

```bash
claude mcp add --transport stdio netbox \
  --env NETBOX_URL=https://netbox.example.com/ \
  --env NETBOX_TOKEN=<your-api-token> \
  -- uv --directory /path/to/netbox-mcp-server run netbox-mcp-server
```

**Important notes:**

- Replace `/path/to/netbox-mcp-server` with the absolute path to your local clone
- The `--` separator distinguishes Claude Code flags from the server command
- Use `--scope project` to share the configuration via `.mcp.json` in version control
- Use `--scope user` to make it available across all your projects (default is `local`)

After adding, verify with `/mcp` in Claude Code or `claude mcp list` in your terminal.

#### HTTP Transport

For HTTP transport, first start the server manually:

```bash
# Start the server with HTTP transport (using .env or environment variables)
NETBOX_URL=https://netbox.example.com/ \
NETBOX_TOKEN=<your-api-token> \
TRANSPORT=http \
uv run netbox-mcp-server
```

Then add the running server to Claude Code:

```bash
# Add the HTTP MCP server (note: URL must include http:// or https:// prefix)
claude mcp add --transport http netbox http://127.0.0.1:8000/mcp
```

**Important notes:**

- The URL **must** include the protocol prefix (`http://` or `https://`)
- The default endpoint is `/mcp` when using HTTP transport
- The server must be running before Claude Code can connect
- Verify the connection with `claude mcp list` - you should see a ✓ next to the server name

### Claude Desktop

Add the server configuration to your Claude Desktop config file. On Mac, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": [
                "--directory",
                "/path/to/netbox-mcp-server",
                "run",
                "netbox-mcp-server"
            ],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-api-token>"
            }
        }
    }
}
```

> On Windows, use full, escaped path to your instance, such as `C:\\Users\\myuser\\.local\\bin\\uv` and `C:\\Users\\myuser\\netbox-mcp-server`.
> For detailed troubleshooting, consult the [MCP quickstart](https://modelcontextprotocol.io/quickstart/user).

5. Use the tools in your LLM client.  For example:

```text
> Get all devices in the 'Equinix DC14' site
...
> Tell me about my IPAM utilization
...
> What Cisco devices are in my network?
...
> Who made changes to the NYC site in the last week?
...
> Show me all configuration changes to the core router in the last month
```

### Field Filtering (Token Optimization)

Both `netbox_get_objects()` and `netbox_get_object_by_id()` support an optional `fields` parameter to reduce token usage:

```python
# Without fields: ~5000 tokens for 50 devices
devices = netbox_get_objects('devices', {'site': 'datacenter-1'})

# With fields: ~500 tokens (90% reduction)
devices = netbox_get_objects(
    'devices',
    {'site': 'datacenter-1'},
    fields=['id', 'name', 'status', 'site']
)
```

**Common field patterns:**

- **Devices:** `['id', 'name', 'status', 'device_type', 'site', 'primary_ip4']`
- **IP Addresses:** `['id', 'address', 'status', 'dns_name', 'description']`
- **Interfaces:** `['id', 'name', 'type', 'enabled', 'device']`
- **Sites:** `['id', 'name', 'status', 'region', 'description']`

The `fields` parameter uses NetBox's native field filtering. See the [NetBox API documentation](https://docs.netbox.dev/en/stable/integrations/rest-api/) for details.

## Configuration

The server supports multiple configuration sources with the following precedence (highest to lowest):

1. **Command-line arguments** (highest priority)
2. **Environment variables**
3. **`.env` file** in the project root
4. **Default values** (lowest priority)

### Configuration Reference

| Setting | Type | Default | Required | Description |
|---------|------|---------|----------|-------------|
| `NETBOX_URL` | URL | - | Yes | Base URL of your NetBox instance (e.g., https://netbox.example.com/) |
| `NETBOX_TOKEN` | String | - | Yes | API token for authentication |
| `TRANSPORT` | `stdio` \| `http` | `stdio` | No | MCP transport protocol |
| `HOST` | String | `127.0.0.1` | If HTTP | Host address for HTTP server |
| `PORT` | Integer | `8000` | If HTTP | Port for HTTP server |
| `VERIFY_SSL` | Boolean | `true` | No | Whether to verify SSL certificates |
| `ENABLE_PLUGIN_DISCOVERY` | Boolean | `false` | No | Auto-discover plugin object types at startup |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` | No | Logging verbosity |

### Transport Examples

#### Stdio Transport (Claude Desktop/Code)

For local Claude Desktop or Claude Code usage with stdio transport:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": ["--directory", "/path/to/netbox-mcp-server", "run", "netbox-mcp-server"],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-api-token>"
            }
        }
    }
}
```

#### HTTP Transport (Web Clients)

For web-based MCP clients using HTTP/SSE transport:

```bash
# Using environment variables
export NETBOX_URL=https://netbox.example.com/
export NETBOX_TOKEN=<your-api-token>
export TRANSPORT=http
export HOST=127.0.0.1
export PORT=8000

uv run netbox-mcp-server

# Or using CLI arguments
uv run netbox-mcp-server \
  --netbox-url https://netbox.example.com/ \
  --netbox-token <your-api-token> \
  --transport http \
  --host 127.0.0.1 \
  --port 8000
```

### Example .env File

Create a `.env` file in the project root:

```env
# Core NetBox Configuration
NETBOX_URL=https://netbox.example.com/
NETBOX_TOKEN=your_api_token_here

# Transport Configuration (optional, defaults to stdio)
TRANSPORT=stdio

# HTTP Transport Settings (only used if TRANSPORT=http)
# HOST=127.0.0.1
# PORT=8000

# Security (optional, defaults to true)
VERIFY_SSL=true

# Plugin Discovery (optional, defaults to false)
# ENABLE_PLUGIN_DISCOVERY=true

# Logging (optional, defaults to INFO)
LOG_LEVEL=INFO
```

### CLI Arguments

All configuration options can be overridden via CLI arguments:

```bash
uv run netbox-mcp-server --help

# Common examples:
uv run netbox-mcp-server --log-level DEBUG --no-verify-ssl  # Development
uv run netbox-mcp-server --transport http --port 9000       # Custom HTTP port
```

## Docker Usage

### Pre-built Image (GHCR) — recommended

This fork publishes pre-built multi-arch images (`linux/amd64`, `linux/arm64`) to the GitHub Container Registry. Pull and run without cloning the repo:

```bash
docker pull ghcr.io/thomaschristory/netbox-mcp-server-extended:latest

docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e ALLOW_UNAUTHENTICATED_HTTP=true \
  -e PORT=8000 \
  -p 8000:8000 \
  ghcr.io/thomaschristory/netbox-mcp-server-extended:latest
```

> **Note:** Docker containers require `TRANSPORT=http` since stdio transport doesn't work in containerized environments.

> **Security:** The server has no built-in authentication and exposes write tools backed by a privileged NetBox token. Binding HTTP to a non-loopback address (such as `0.0.0.0` in a container) is refused unless you set `ALLOW_UNAUTHENTICATED_HTTP=true` to acknowledge the risk. Only do so behind an authenticating TLS reverse proxy, or on a trusted network. Use a read-only NetBox token unless you specifically need the write tools.

**Available tags:**

| Tag | Description |
|-----|-------------|
| `:latest` | Most recent build from the default branch |
| `:main` | Latest build of the `main` branch |
| `:sha-<short>` | Immutable build for a specific commit (e.g. `:sha-4f06758`) |
| `:X.Y.Z`, `:X.Y`, `:X` | Semantic-version tags published on releases |

Pin to a specific version or commit SHA in production — `:latest` and `:main` track the newest build and can change without notice.

**Connecting to NetBox on your host machine:**

If your NetBox instance is running on your host machine (not in a container), use `host.docker.internal` instead of `localhost` on macOS and Windows:

```bash
# For NetBox running on host (macOS/Windows)
docker run --rm \
  -e NETBOX_URL=http://host.docker.internal:18000/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e ALLOW_UNAUTHENTICATED_HTTP=true \
  -e PORT=8000 \
  -p 8000:8000 \
  ghcr.io/thomaschristory/netbox-mcp-server-extended:latest
```

> **Note:** On Linux, you can use `--network host` instead, or use the host's IP address directly.

**With additional configuration options:**

```bash
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e ALLOW_UNAUTHENTICATED_HTTP=true \
  -e LOG_LEVEL=DEBUG \
  -e VERIFY_SSL=false \
  -p 8000:8000 \
  ghcr.io/thomaschristory/netbox-mcp-server-extended:latest
```

The server will be accessible at `http://localhost:8000/mcp` for MCP clients. You can connect to it using your preferred method.

### Build from Source

To build the image yourself (for local development or customisation):

```bash
# Build the image
docker build -t netbox-mcp-server-extended:latest .

# Run it (same environment variables as the pre-built image above)
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e ALLOW_UNAUTHENTICATED_HTTP=true \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server-extended:latest
```

## Plugin Object Type Discovery

By default, only core NetBox object types are available. If your NetBox instance has plugins installed (e.g., `netbox-dns`, `netbox-inventory`), you can enable automatic discovery to make their object types available as well.

### Enabling Discovery

Set the `ENABLE_PLUGIN_DISCOVERY` environment variable or use the `--enable-plugin-discovery` CLI flag:

```bash
# Via environment variable
ENABLE_PLUGIN_DISCOVERY=true uv run netbox-mcp-server

# Via CLI flag
uv run netbox-mcp-server --enable-plugin-discovery

# In Claude Desktop config
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": ["--directory", "/path/to/netbox-mcp-server", "run", "netbox-mcp-server"],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-api-token>",
                "ENABLE_PLUGIN_DISCOVERY": "true"
            }
        }
    }
}
```

### How It Works

At startup, the server queries NetBox's `core/object-types` API endpoint (with `extras/object-types` fallback for NetBox < 4.4) to find all installed plugin models that have REST API endpoints. These are merged into the runtime type registry alongside the core types.

Discovered plugin types use the `app_label.model` naming convention (e.g., `netbox_dns.zone`, `netbox_inventory.asset`) and work with all existing tools (`netbox_get_objects`, `netbox_get_object_by_id`, `netbox_search_objects`).

### Requirements

- NetBox 4.2 or later
- API token must have read access to the object-types endpoint
- Plugin models must expose a REST API endpoint to be discovered

### Failure Behavior

If discovery fails for any reason (network error, insufficient permissions, unsupported NetBox version), the server logs a warning and continues with core types only. This ensures the server always starts successfully regardless of discovery outcome.

## Development

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing new features — we encourage filing an issue for discussion first to confirm scope fit.

If your use case needs capabilities outside this project's scope, forking under Apache 2.0 is an actively supported path.

## License

This project is licensed under the Apache 2.0 license.  See the LICENSE file for details.
