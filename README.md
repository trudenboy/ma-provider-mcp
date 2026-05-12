# ma-provider-mcp


<!-- >>> ma-provider-tools sync (readme header) — DO NOT EDIT >>> -->
[![CI](https://github.com/trudenboy/ma-provider-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/trudenboy/ma-provider-mcp/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/trudenboy/ma-provider-mcp?display_name=tag)](https://github.com/trudenboy/ma-provider-mcp/releases/latest)
[![License](https://img.shields.io/github/license/trudenboy/ma-provider-mcp)](LICENSE)
[![Music Assistant](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Ffastmcp_server.json)](https://www.music-assistant.io/)
[![Stars](https://img.shields.io/github/stars/trudenboy/ma-provider-mcp?style=flat&logo=github)](https://github.com/trudenboy/ma-provider-mcp/stargazers)

**📖 [Documentation](https://trudenboy.github.io/ma-provider-mcp/)** · **🔄 [Changelog](CHANGELOG.md)** · **🐛 [Issues](https://github.com/trudenboy/ma-provider-mcp/issues)** · **💬 [Discussions](https://github.com/trudenboy/ma-provider-mcp/discussions)**
<!-- <<< ma-provider-tools sync (readme header) <<< -->

**MCP Server** plugin provider for [Music Assistant](https://github.com/music-assistant/server).

Exposes MA's library, queue, playback, players, and metadata controllers as a
[Model Context Protocol](https://modelcontextprotocol.io/) server, accessible to
Claude Code, Codex, and any other MCP-aware LLM client.

## Highlights

- Built on **PrefectHQ FastMCP v3** — no homebrew SDK glue.
- **No core MA changes required.** Authentication delegates to
  `mass.webserver.auth.authenticate_with_token` (handles both JWT and legacy tokens).
- **16-permission tag-based access control** (query / control / edit / delete × 4 categories);
  defaults: reads on, all mutations off.
- **Mounted into MA's existing webserver** at `/mcp/v1` — reuses TLS, reverse proxy,
  and Home Assistant ingress out of the box. No second port, no extra firewall rule.
- 8 namespaced sub-servers, exposing tools as `library_search_tracks`,
  `queue_get_active_queue`, `playback_play_media`, etc.

## Usage

### Quick connect (recommended)

After enabling the plugin in MA settings, click **Open Connect Wizard**
in the provider's config panel. Pick your AI client — the wizard mints a
per-client token (`MCP — <Client>`, revocable individually under
Settings → Security → Tokens) and shows the ready-to-paste snippet.
Cursor users get an extra **Add to Cursor** one-click deeplink. Supports
Claude Desktop, Claude Code, Cursor, Windsurf, VSCode, ChatGPT
Connectors, Codex CLI, Gemini CLI, Cline, and Zed.

### Manual

```bash
TOKEN="<mint a token in MA Settings → Security → Tokens>"

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

The provider config exposes 16 permission booleans, grouped by category:

| Category   | Verbs                                                                |
|------------|----------------------------------------------------------------------|
| Query      | library, queue, players, metadata                                    |
| Control    | playback, volume, players, media (announcements)                     |
| Edit       | library (add), queue (move/save), playlists (create/add/reorder), favorites (add) |
| Delete     | library (remove), queue (clear), playlists (delete), favorites (remove) |

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

## License

[Apache-2.0](LICENSE)
