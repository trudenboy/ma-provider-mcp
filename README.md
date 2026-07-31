# ma-provider-mcp


<!-- >>> ma-provider-tools sync (readme header) — DO NOT EDIT >>> -->
[![CI](https://github.com/trudenboy/ma-provider-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/trudenboy/ma-provider-mcp/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/trudenboy/ma-provider-mcp?display_name=tag)](https://github.com/trudenboy/ma-provider-mcp/releases/latest)
[![License](https://img.shields.io/github/license/trudenboy/ma-provider-mcp)](LICENSE)
[![Music Assistant](https://img.shields.io/badge/Music%20Assistant-9070B8?logo=python&logoColor=white)](https://www.music-assistant.io/)[![stable](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Ffastmcp_server-stable.json)](https://github.com/music-assistant/server/releases/latest)[![beta](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Ffastmcp_server-beta.json)](https://github.com/music-assistant/server/releases?q=prerelease)
[![Stars](https://img.shields.io/github/stars/trudenboy/ma-provider-mcp?style=flat&logo=github)](https://github.com/trudenboy/ma-provider-mcp/stargazers)

**📖 [Documentation](https://trudenboy.github.io/ma-provider-mcp/)** · **🔄 [Changelog](CHANGELOG.md)** · **🐛 [Issues](https://github.com/trudenboy/ma-provider-mcp/issues)** · **💬 [Discussions](https://github.com/trudenboy/ma-provider-mcp/discussions)**
<!-- <<< ma-provider-tools sync (readme header) <<< -->

**MCP Server** plugin provider for [Music Assistant](https://github.com/music-assistant/server).

Exposes Music Assistant's live API-command registry through a compact
[Model Context Protocol](https://modelcontextprotocol.io/) server, accessible to
Claude, Cursor, Codex, the OpenClaw and Hermes multi-agent orchestrators, and any
other MCP-aware client. The catalog covers library, queue, playback, players,
configuration, and provider diagnostics without maintaining a parallel tool API.

## Highlights

- Built on **PrefectHQ FastMCP v3** — no homebrew SDK glue.
- **No core MA changes required.** Authentication delegates to
  `mass.webserver.auth.authenticate_with_token` (handles both JWT and legacy tokens).
- **Tag-based access control** — 16 action permissions (query / control / edit / delete × 4)
  plus 3 MCP-resource toggles; reads on, all mutations off by default. Two further
  off-by-default namespaces (`debug`, `config`) add 4 + 5 capability flags.
- **Mounted into MA's existing webserver** at `/mcp/v1` — reuses TLS, reverse proxy,
  and Home Assistant ingress out of the box. No second port, no extra firewall rule.
- The MCP surface contains exactly three tools: `search_tools`, `get_tool_schema`,
  and `call_tool`. They discover and invoke Music Assistant's live API registry as
  `ma_api:*` commands.
- Provider-owned `fastmcp/*` commands use that same registry and exist only for safe
  queue batch removal and diagnostics that Music Assistant does not expose natively.

## Usage

### Unified command catalog

Start with `search_tools` using a short intent such as `album tracks` or `queue
items`, inspect the selected `ma_api:*` command with `get_tool_schema`, then invoke
it through `call_tool`. Schemas are loaded one at a time, and runtime changes to
Music Assistant's command registry become discoverable without adding MCP wrappers.

`search_tools(query="album tracks")` returns a ranked page with descriptions. For a
complete alphabetical browse, call `search_tools(query="", limit=25)` and follow
with `search_tools(cursor="...")` until `next_cursor` is null. Resource-aware clients
can traverse the same catalog through `catalog://commands{?cursor,limit}` and follow
`next_uri`. Catalog pages contain command names only; descriptions belong to ranked
search pages, and command schemas always remain on-demand through `get_tool_schema`.

The provider registers eight ordinary MA extension commands under `fastmcp/*`: one
server-side safe queue batch-removal command and seven bounded diagnostics commands.
They are discovered and called as `ma_api:fastmcp/*`; there is no separate recipe
dispatcher or executable `mcp_api:*` namespace. Existing `library://`, `player://`,
and `queue://` resources and the canned prompts remain available through the normal
MCP resource and prompt APIs.

### Quick connect (recommended)

After enabling the plugin in MA settings, click **Open Connect Wizard**
in the provider's config panel. Pick your AI client — the wizard mints a
per-client token (`MCP — <Client>`, revocable individually under
Profile → Long-lived access tokens) and shows the ready-to-paste snippet.
Cursor users get an extra **Add to Cursor** one-click deeplink. Supports
Claude Desktop, Claude Code, Cursor, Windsurf, VSCode, ChatGPT
Connectors, Codex CLI, Gemini CLI, Cline, Zed, OpenClaw, and Hermes.

### Manual

```bash
TOKEN="<mint a token in MA Profile → Long-lived access tokens>"

# Probe streamable HTTP transport
curl -sS -H "Authorization: Bearer $TOKEN" \
     -H "Accept: text/event-stream" \
     http://localhost:8095/mcp/v1

# Connect Claude Code
claude mcp add ma --transport http \
  --url http://localhost:8095/mcp/v1 \
  --header "Authorization: Bearer $TOKEN"
```

## Permissions

The provider config exposes 16 action-permission booleans, grouped by category:

| Category   | Verbs                                                                |
|------------|----------------------------------------------------------------------|
| Query      | library, queue, players, metadata                                    |
| Control    | playback, volume, players, media (announcements)                     |
| Edit       | library (add), queue (move/save), playlists (create/add/reorder), favorites (add) |
| Delete     | library (remove), queue (clear), playlists (delete), favorites (remove) |

Three further **MCP Resources** toggles control which `library://`,
`player://` / `queue://`, and prompt resources are advertised. Two optional,
off-by-default namespaces add their own flags: **Debug** (4 — inspect, logs,
events, providers) and **Config** (5 — read, edit provider / core /
player, allow secret writes; writes delegate to MA's atomic save). Every
capability outside the Query group is off by default.

Each maps to a tag (`query:library`, `control:playback`, …). The unified catalog
applies those tags to native MA commands before discovery and repeats the check
immediately before execution, so a cached command cannot bypass a revoked permission.
Native `config/*` commands use the existing Config read/provider/core/player toggles;
writing a `SECURE_STRING` additionally requires `config:write:secret`. Direct queue
clear/delete operations and the safe batch-removal extension always elicit client
confirmation. Resource and prompt visibility continues to use the three MCP Resource
toggles above.

## Spec compliance (MCP 2025-06-18 / draft)

- **Streamable HTTP transport** with mandatory `Origin` validation
  (DNS-rebinding mitigation). Allowlist auto-built from `mass.webserver`;
  add reverse-proxy hosts via `extra_allowed_origins` (CSV).
- **OAuth 2.0 Protected Resource Metadata** (RFC 9728) at
  `/.well-known/oauth-protected-resource[/mcp/v1]`, plus `resource_metadata`
  in `WWW-Authenticate` 401 responses.
- **Resource Indicator support** (RFC 8707): `AccessToken.resource` is set,
  optional `enforce_audience` config rejects tokens whose `aud` ≠ canonical
  URI (soft mode by default — logs warning until MA issues audience-bound JWTs).
- **Tool annotations** (`title`, `readOnly`/`destructive`/`idempotent`/`openWorld` hints).
- **Elicitation** for destructive operations.
- **Per-tool timeouts** so a stuck provider doesn't tie up an MCP session.

## Development

```bash
uv sync --all-extras
bash .superpowers/sdd/2026-07-30-native-ma-command-catalog/run-ma-tests.sh -q
uv run ruff check provider tests
uv run ruff format --check provider tests
```

MA-dependent tests and final type checking must run in a complete Linux virtual
environment from the current Music Assistant `dev` checkout; the repository wrapper
mounts `/Users/renso/Projects/ma-server` at `/ma-server` and reuses MA's canonical
fixtures.

### Opt-in Docker integration coverage

The live catalog smoke tests run in the complete Linux MA virtual environment and
use the persisted development instance in `.ma-data/`. Start Docker, mint a
dedicated MA user token, and supply it only through your shell:

```bash
MA_SERVER_ROOT=/Users/renso/Projects/ma-server \
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec -T ma \
  /app/venv/bin/python -c 'import music_assistant; import music_assistant.providers.fastmcp_server as p; print(music_assistant.__file__); print(p.__file__)'
docker compose -f docker-compose.dev.yml exec -T ma \
  /app/venv/bin/uv pip install --quiet --python /app/venv/bin/python \
  pytest==9.0.3 pytest-asyncio==1.3.0
docker compose -f docker-compose.dev.yml exec -T \
  -e MA_MCP_URL=http://127.0.0.1:8095/mcp/v1 \
  -e MA_MCP_TOKEN="$MA_MCP_TOKEN" \
  -e MA_TEST_PLAYER_ID="$MA_TEST_PLAYER_ID" \
  ma /app/venv/bin/python -m pytest -o addopts= -p no:cacheprovider \
  --confcutdir=/tmp/provider-tests/integration \
  /tmp/provider-tests/integration/test_live_catalog.py -m integration -v -s
```

Set `MA_DATA_DIR=/absolute/path/to/.ma-data` on `docker compose` when a worktree
should reuse an already configured development instance without copying its data.
`MA_SERVER_ROOT` defaults to `/Users/renso/Projects/ma-server`; Compose mounts that
checkout at `/ma-server`, overlays this provider inside it, and refuses startup unless
the imported MA package and `fastmcp_server` provider paths both begin with
`/ma-server/`. The test command cuts conftest discovery at the integration
directory, so it does not load the repository's unit-test fixtures (which import
the source-root `provider` package).
`.superpowers/sdd/2026-07-30-native-ma-command-catalog/run-ma-tests.sh` runs the
implementation suite in the same complete Linux MA virtual environment.

`MA_TEST_PLAYER_ID` is optional, but required for the one reversible queue mutation
test. Choose a dedicated player with an active queue; the test refuses unsafe rows
and removes only the item it adds. The suite is skipped unless both MCP URL and token
are explicitly provided.

## License

[MIT](LICENSE)
