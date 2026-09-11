# NetBox MCP Server

## Core Concept

A [Model Context Protocol](https://modelcontextprotocol.io/) server that lets LLMs work with NetBox infrastructure data. It uses FastMCP and it serves NetBox operators.

This repository is a **write-enabled fork** of the read-only upstream server. The read tools come from upstream. The fork layer adds three write tools: `netbox_create_object`, `netbox_update_object`, and `netbox_delete_object`. Every write tool defaults to `dry_run=True`.

**Your role**: Help contributors design and implement features within the project's stated scope (see [CONTRIBUTING.md](CONTRIBUTING.md)). Challenge proposals that fall outside scope before implementation begins, not after. Ask clarifying questions and challenge assumptions when needed.

## Tech Stack

- **Python**: >=3.11, <3.15
- **Package Manager**: uv
- **MCP Framework**: FastMCP >=3.0.0
- **HTTP Client**: httpx
- **NetBox API**: REST API via token authentication

## Project Structure

```text
.
├── src/
│   └── netbox_mcp_server/
│       ├── __init__.py          # Package initialization with __version__
│       ├── __main__.py          # Entry point for module execution
│       ├── server.py            # Main MCP server with tool definitions
│       ├── netbox_client.py     # NetBox REST API client abstraction
│       ├── netbox_write_client.py # Real writes and script-backed dry runs (fork layer)
│       ├── write_tools.py       # create/update/delete MCP tools (fork layer)
│       ├── netbox_types.py      # NetBox object type mappings
│       └── config.py            # Settings and logging configuration
├── netbox_scripts/               # NetBox-side validator script for dry runs (fork layer)
├── tests/                        # Test suite
├── .github/workflows/            # CI/CD automation
├── pyproject.toml               # Dependencies and project metadata
├── README.md                    # User-facing documentation
├── CHANGELOG.md                 # Upstream history; fork releases are not added here
└── LICENSE                      # Apache 2.0 license
```

**Design Pattern**: Clean separation between MCP server logic (`server.py`) and NetBox API client (`netbox_client.py`) to support future plugin-based implementations.

## Common Commands

```bash
# Install dependencies (ONLY use uv, NEVER pip)
uv sync

# Run the server locally (requires env vars)
NETBOX_URL=https://netbox.example.com/ NETBOX_TOKEN=<token> uv run netbox-mcp-server

# Alternative: module execution
uv run -m netbox_mcp_server

# Add to Claude Code (for development/testing)
claude mcp add --transport stdio netbox \
  --env NETBOX_URL=https://netbox.example.com/ \
  --env NETBOX_TOKEN=<token> \
  -- uv --directory /path/to/netbox-mcp-server run netbox-mcp-server
```

## Development Philosophy

- **Simplicity over cleverness**: Write simple, straightforward code that's easy to understand
- **Readability first**: Code is read 10x more than it's written - optimize for the reader
- **Build iteratively**: Start with minimal functionality, verify it works, then add complexity
- **DRY (Don't Repeat Yourself)**: Extract common patterns, but only after the third occurrence
- **Early returns**: Use early returns to avoid nested conditions and improve readability
- **Descriptive names**: Use clear variable and function names that explain intent
- **Less code = less debt**: Minimize code footprint; the best code is no code at all
- **Test frequently**: Test with realistic inputs and validate outputs as you build
- **Functional where clear**: Use functional, stateless approaches when they improve clarity
- **Clean core logic**: Keep business logic clean; push implementation details to the edges

## Version Management

This repository is a fork of [netboxlabs/netbox-mcp-server](https://github.com/netboxlabs/netbox-mcp-server). It adds a fork layer on top of an upstream release and keeps that upstream release visible in the version number.

**Version scheme**: `<upstream-version>.postN`, a PEP 440 post-release. `1.2.1.post1` is the first fork-layer release on upstream `v1.2.1`. `UPSTREAM_VERSION` holds the upstream tag that `main` is rebased onto. Four files must always agree: `UPSTREAM_VERSION`, `pyproject.toml`, `src/netbox_mcp_server/__init__.py`, and `uv.lock`.

**A merge to `main` does not release anything.** The version does not come from commit messages. A `feat:` commit produces no version change. Conventional commits are still required, because they make the history readable, but they have no effect on the version.

Two workflows produce a release. Both end by pushing a `v*.post*` tag, which starts `release-extended.yml` (GitHub Release plus PyPI through Trusted Publisher) and `docker-publish.yml` (GHCR image).

| Situation | Workflow | Result |
|---|---|---|
| Upstream published a new release | `sync-upstream.yml` (Monday 06:00 UTC, or manual) | Rebases the fork layer onto the new upstream tag, resets the counter to `<new-upstream>.post1`, tags, and pushes |
| Only the fork layer changed | `release-fork.yml` (manual) | Increments the counter, for example `1.2.1.post1` → `1.2.1.post2`, tags, and pushes |

**To cut a fork-layer release**: merge the work to `main`, wait for Test & Lint to pass, then run the **Release Fork Layer** workflow. Use its `dry_run` input first if you want to see the computed version. The workflow stops if the version records disagree, if the tag exists, or if Test & Lint did not pass on the head of `main`.

Both workflows need the `SYNC_TOKEN` secret, a fine-grained PAT for this repository. A tag pushed with the default `GITHUB_TOKEN` does not start another workflow, so the release would stop at the tag.

**Do not add python-semantic-release back.** It parses versions as semver and cannot read a `.postN` tag. With no tag it can parse, it reads the history as empty and computes a downgrade. See issue #25.

## Code Standards

### Python Conventions

- **Type hints required**: All function parameters and return types must be annotated
- **Docstrings**: Use Google-style docstrings for all public functions and classes
- **Line length**: 88 characters maximum (Ruff/Black standard)
- **Naming conventions**:
  - Functions and variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
- **String formatting**: Use f-strings for string formatting
- **Imports**: Absolute imports preferred, group standard library → third-party → local
- **Error handling**: Never use bare `except` - specify exception types (e.g., `except ValueError:`); raise descriptive exceptions and let FastMCP handle error responses

### Code Style

```python
# ✅ Good: Clear types, descriptive names, proper error handling, comprehensive docstrings
def netbox_get_objects(object_type: str, filters: dict) -> list[dict]:
    """Get objects from NetBox based on their type and filters.

    Args:
        object_type: String representing the NetBox object type (e.g. "devices")
        filters: Dictionary of filters to apply to the API call

    Returns:
        Either a single object dict or a list of object dicts
    """
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")
    return netbox.get(NETBOX_OBJECT_TYPES[object_type], params=filters)

# ❌ Avoid: Missing types, generic names, silent failures, no docstrings
def get_stuff(t, f):
    try:
        return netbox.get(types[t], params=f)
    except:
        return None
```

### Architecture Patterns

- **Abstraction layer**: `NetBoxClientBase` defines interface for future ORM implementation
- **Writes are explicit and reversible to preview**: The fork exposes create, update, and delete. Each tool defaults to `dry_run=True`
- **NetBox validates a dry run, not this server**: A dry run runs the `MCPWriteValidator` custom script with `commit=false`. NetBox applies the change with its own REST serializers inside a transaction that it always rolls back
- **A dry run fails closed**: If the script is missing, the RQ worker is down, or the job gives no verdict, the tool raises an error. A dry run never falls back to a real write
- **Environment-based config**: All secrets via environment variables, never hardcoded
- **Explicit object mapping**: `NETBOX_OBJECT_TYPES` dictionary maintains allowed types

## Tool Development Guidelines

### Adding New Tools

1. Define tool function with `@mcp.tool` decorator
2. Include comprehensive docstring with args, return types, and examples
3. Validate inputs before calling NetBox client
4. Return structured data (dict or list); let FastMCP handle serialization

### Adding or Changing a Write Tool

Warning: a defect here can destroy NetBox data. Issue #34 is the precedent — a dry run
executed the write it claimed to preview.

1. Keep `dry_run: bool = True` as the default
2. Route the dry run through `NetBoxWriteClient._dry_run()`. Do not invent a new preview mechanism
3. Raise on any doubt. A dry run that cannot produce a verdict must not perform the write
4. Validate `object_type` against `NETBOX_OBJECT_TYPES` before the call reaches NetBox
5. Document the change in `README.md` and, when it touches the NetBox side, in `netbox_scripts/README.md`

### Tool Naming Convention

- Use `netbox_` prefix for all tools (e.g., `netbox_get_objects`)
- Use descriptive action verbs: `get`, `list`, `search`
- Keep names intuitive for LLM consumption

### Supported NetBox Objects

Tools support core NetBox object types across these modules:

- **DCIM**: devices, sites, racks, interfaces, cables, etc.
- **IPAM**: IP addresses, prefixes, VLANs, VRFs, ASNs
- **Circuits**: circuits, providers, circuit terminations
- **Virtualization**: VMs, clusters, VM interfaces
- **Tenancy**: tenants, contacts, contact groups
- **VPN**: tunnels, IPsec policies, IKE policies
- **Wireless**: wireless LANs, wireless links
- **Extras**: config contexts, custom fields, export templates, image attachments, jobs, saved filters, scripts, tags, webhooks

See `NETBOX_OBJECT_TYPES` in `server.py` for complete list.

## Environment Variables

- `NETBOX_URL`: Base URL of NetBox instance (e.g., `https://netbox.example.com/`)
- `NETBOX_TOKEN`: API token. Use a read-only token for query-only use. The write tools need a write token
- `LOG_LEVEL`: Logging verbosity (default: `INFO`, options: `DEBUG`, `WARNING`, `ERROR`)
- `DRY_RUN_SCRIPT`: NetBox custom script that backs dry runs (default: `netbox_mcp_server_extended.MCPWriteValidator`)
- `DRY_RUN_TIMEOUT`: Seconds to wait for a dry-run job (default: `60`)
- `ENABLE_PLUGIN_DISCOVERY`: Auto-discover plugin object types at startup (default: `false`)

`README.md` holds the full table, including the transport and HTTP authentication variables.

## Security Considerations

- **Prefer a read-only token**: Use a read-only token unless the deployment needs the write tools. A read-only token cannot change NetBox data
- **Scope a write token narrowly**: Grant only the object permissions the deployment intends to change
- **Constrain `extras.run_script`**: Dry runs need this permission. Constrain it to the `MCP Write Validator` script. An unconstrained permission lets the token run every script on that NetBox instance
- **A valid dry run is not an authorization check**: The validator script reaches the ORM directly, so it does not apply object-level permissions. `valid: true` can precede a 403 on the real write
- **No credential storage**: Tokens passed via environment, never stored or logged
- **SSL verification**: Enabled by default in REST client
- **Plugin object types are opt-in**: `ENABLE_PLUGIN_DISCOVERY` is `false` by default. The default keeps the attack surface small
- **Open source**: All code auditable; report security issues per SECURITY.md

## Testing Philosophy

`tests/` holds the suite. Run it with `uv run pytest`. CI runs it on Python 3.11 to 3.14.

- Mock the NetBox API at the `httpx` layer; do not call a live instance in a unit test
- `tests/test_write_integration.py` needs a live NetBox. It skips when the environment
  variables are absent, and the dry-run test also skips when the validator script or the
  RQ worker is missing
- Validate error handling (invalid object types, missing credentials, API errors)
- Test pagination handling for large result sets
- **Cover the dry-run contract for any change to the write path**: a failed dry run must
  raise, never fall back to a real write. `test_dry_run_never_falls_back_to_real_write`
  is the guard

## Do Not

### Package Management

- ❌ **NEVER use pip** - Only use `uv` for package management
- ❌ **NEVER use `uv pip install`** - This is forbidden; use `uv add` instead
- ❌ **NEVER use `@latest` syntax** - Specify versions explicitly or let uv manage them

### Code Quality

- ❌ Add a write tool that can bypass the dry-run path, or make a failed dry run fall back to a real write
- ❌ Widen the write surface (bulk writes, raw endpoint access) without maintainer approval
- ❌ Enable plugin discovery by default
- ❌ Hardcode credentials or NetBox URLs
- ❌ Bypass the `NetBoxClientBase` abstraction
- ❌ Remove type hints or comprehensive docstrings
- ❌ Use print statements (use proper logging via `LOG_LEVEL`)

## Open Source Best Practices

- **Professional communication**: Be courteous and constructive
- **Documentation is mandatory**: A user-facing feature doesn't exist unless documented in README.md
- **Licensing**: Apache 2.0; ensure all contributions are compatible
- **Issue-driven development**: Reference issues in commits and PRs

### Communication Style

Write all English text in **ASD-STE100 Simplified Technical English**. This applies to
docstrings, code comments, README and other documentation, commit messages, PR
descriptions, issue text, log messages, and chat replies.

Core STE rules:

- **One word, one meaning**: Use each word with a single approved meaning. Use the same
  word for the same thing every time. Do not use synonyms for variety.
- **Simple tenses**: Use the simple present, simple past, or simple future. Do not use
  the perfect or continuous tenses.
- **Active voice**: Write "The server reads the token." Do not write "The token is read
  by the server."
- **Short sentences**: Maximum 20 words for an instruction, 25 words for a description.
  One instruction per sentence.
- **Short paragraphs**: Maximum 6 sentences.
- **Keep the articles**: Write "the device", not "device".
- **No -ing forms as verbs**: Write "Set the variable", not "Setting the variable".
- **No noun clusters over 3 words**: Write "the timeout of the API token", not "the API
  token timeout value".
- **Warning first**: Put the condition or the warning before the instruction.
- **No slang, no idioms, no jargon**: Technical terms from NetBox, MCP, and Python stay
  as they are. Everything else uses plain words.

Style rules that stay in effect:

- **Be direct**: State what things ARE (avoid "This isn't X, it's Y" constructions)
- **Be brief**: Optimize for reader comprehension, not writer expression
- **Be clear**: Avoid defensive writing patterns and ambiguous language

## Git Workflow

### Branch Strategy

- **Always use feature branches** - NEVER commit directly to `main`
- **Branch naming**: Use descriptive names with prefixes:
  - `fix/auth-timeout` - Bug fixes
  - `feat/api-pagination` - New features
  - `chore/ruff-fixes` - Maintenance tasks
- **One logical change per branch** - Simplifies review and rollback

### Commit Practices

- **Conventional commit format** (preferred):

  ```bash
  type(scope): short description

  Examples:
  feat(tools): add netbox_search_objects tool
  fix(client): handle pagination correctly
  chore(deps): upgrade fastmcp to 2.13.0
  ```

- **Commit trailers** for attribution:

  ```bash
  # Link to GitHub issue
  git commit --trailer "Github-Issue:#123"

  # Credit bug reporter
  git commit --trailer "Reported-by:Jane Doe"
  ```

- **Make atomic commits** - One logical change per commit
- **Keep granular history** on feature branch; squash only when merging to `main`

### Pull Request Workflow

1. **Create or reference an issue** before starting work
2. **Create feature branch**: `git checkout -b feat/issue-123-description`
3. **Commit in small, logical increments** as you work
4. **Push and open draft PR early** for visibility
5. **Convert to ready PR** when functionally complete and tests pass
6. **Wait for reviews** and address feedback
7. **Merge after approval** and CI checks pass

### PR Guidelines

**PR Description Format**:

- 1-2 paragraphs: State the problem/need and your solution
- Include a focused code example if adding new functionality
- Keep it concise for minor fixes (1-2 sentences is fine)

**What to Avoid**:

- Bullet-point summaries of every file changed
- Marketing language or excessive justification
- Repeating what the code diff already shows

**What to Include**:

- Link related issues: `Fixes #123` or `Relates to #456`
- Why this change matters (not just what changed)

### Critical Rules

- ❌ **NEVER commit directly to `main`** - Always use feature branches
- ✅ **DO keep commits professional and concise** and focused on the change

## Decision Heuristics

### When to Add a New Tool

✅ **Add if**:

- Exposes core NetBox functionality not currently accessible
- Has clear use case for LLM-driven queries
- Keeps the dry-run contract for any tool that changes data
- Follows existing tool patterns

❌ **Don't add if**:

- Duplicates existing tool functionality
- Changes data without a dry-run path
- Only benefits niche use cases
- Adds complexity without clear value

### When to Modify the Client Abstraction

Only modify `NetBoxClientBase` if:

- Planning to add plugin-based ORM implementation
- All CRUD methods must remain in sync
- Changes must not break REST implementation

### Progressive Complexity

**Level 1 (New Contributors)**: Add tools, fix bugs, improve documentation

**Level 2 (Maintainers)**: Modify client abstraction, add new object type categories

**Level 3 (Core Team)**: Architectural changes, security-sensitive code

## Common Patterns

### Querying NetBox Objects

These examples show how LLMs interact with MCP tools (conceptual format):

```python
# Get all devices in a site
mcp_tool("netbox_get_objects", {
    "object_type": "devices",
    "filters": {"site": "equinix-dc14"}
})

# Get specific device by ID
mcp_tool("netbox_get_object_by_id", {
    "object_type": "devices",
    "object_id": 123
})

# Find recent changes
mcp_tool("netbox_get_changelogs", {
    "filters": {
        "action": "update",
        "time_after": "2025-01-01T00:00:00Z"
    }
})
```

## Troubleshooting

**"NETBOX_URL and NETBOX_TOKEN environment variables must be set"**
→ Set environment variables before running server

**"Invalid object_type"**
→ Check `NETBOX_OBJECT_TYPES` dictionary for supported types
→ Plugin object types need `ENABLE_PLUGIN_DISCOVERY=true`

**"Connection refused" or timeout**
→ Verify NETBOX_URL is accessible and includes protocol (https://)
→ Check firewall rules and network connectivity

**"Authentication failed"**
→ Verify API token is valid and not expired
→ Ensure token has read permissions for requested objects

## References

- [NetBox API Documentation](https://docs.netbox.dev/en/stable/integrations/rest-api/)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Project README](./README.md) - User-facing setup and usage
- [Contributing Guide](./CONTRIBUTING.md) - Project scope, contribution workflow, and out-of-scope list
- [Security Policy](./SECURITY.md) - Vulnerability reporting
