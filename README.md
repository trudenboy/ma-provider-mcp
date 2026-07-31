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

Exposes MA's library, queue, playback, players, and metadata controllers as a
[Model Context Protocol](https://modelcontextprotocol.io/) server, accessible to
Claude, Cursor, Codex, the OpenClaw and Hermes multi-agent orchestrators, and any
other MCP-aware client. Optional `debug` and `config` namespaces add
troubleshooting and settings management for power users.

## Highlights

- Built on **PrefectHQ FastMCP v3** — no homebrew SDK glue.
- **No core MA changes required.** Authentication delegates to
  `mass.webserver.auth.authenticate_with_token` (handles both JWT and legacy tokens).
- **Tag-based access control** — 16 action permissions (query / control / edit / delete × 4)
  plus 3 MCP-resource toggles; reads on, all mutations off by default. Two further
  off-by-default namespaces (`debug`, `config`) add 5 + 5 capability flags.
- **Mounted into MA's existing webserver** at `/mcp/v1` — reuses TLS, reverse proxy,
  and Home Assistant ingress out of the box. No second port, no extra firewall rule.
- 8 always-on namespaced sub-servers (library, queue, playback, players, playlists,
  volume, media, metadata) plus the optional `debug` and `config` namespaces — exposing
  tools as `library_search_tracks`, `queue_get_active_queue`, `playback_play_media`, etc.

## Usage

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
off-by-default namespaces add their own flags: **Debug** (5 — inspect, logs,
events, providers, reload) and **Config** (5 — read, edit provider / core /
player, allow secret writes; writes delegate to MA's atomic save). Every
capability outside the Query group is off by default.

Each maps to a tag (`query:library`, `control:playback`, …). A custom
`TagFilterMiddleware` filters `tools/list` / `resources/list` / `prompts/list`
**and** blocks direct invocation of disabled components — so a client that
cached a tool name from an earlier permission set cannot bypass the filter.

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
uv run pytest
uv run ruff check provider tests
uv run mypy provider
```

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
