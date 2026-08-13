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
- **Permissions & Confirmations v2** — five named profiles and per-token overrides
  resolve all 26 stable capabilities to `Deny`, `Allow`, or `Confirm`. New and
  unconfigured installations fail closed to the `Read-only` profile.
- **Mounted into MA's existing webserver** at `/mcp/v1` — reuses TLS, reverse proxy,
  and Home Assistant ingress out of the box. No second port, no extra firewall rule.
- The default MCP surface contains exactly three tools: `search_tools`,
  `get_tool_schema`, and `call_tool`. Enabling **Enable MCP App** adds only
  `app_music_assistant`; its state/action tools remain renderer-only.
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
Set `include_top_schema=true` with a non-empty query and no cursor to attach the full
schema only to the first ranked result. Search is Unicode-aware and uses canonical
names plus curated aliases; it does not translate queries or call an embedding service.

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
When a client supports multiple connection methods, the simplest method is
recommended first and alternate CLI, config-file, or guided UI methods remain
in the same client card and reuse its token. Supports Claude Code, Cursor,
OpenCode, Windsurf/Devin, VSCode, GitHub Copilot CLI, Codex CLI, Gemini CLI,
Cline, Roo Code, Zed, OpenClaw, OpenHands, Hermes, and a product-neutral Custom option.
Claude Desktop Chat/Cowork and
ChatGPT custom connectors are omitted because they support OAuth rather than
the wizard's static Bearer token.

### Manual

```bash
TOKEN="<mint a token in MA Profile → Long-lived access tokens>"

# Probe streamable HTTP transport
curl -sS -H "Authorization: Bearer $TOKEN" \
     -H "Accept: text/event-stream" \
     http://localhost:8095/mcp/v1

# Connect Claude Code
claude mcp add --scope user --transport http ma \
  http://localhost:8095/mcp/v1 \
  --header "Authorization: Bearer $TOKEN"
```

## Permissions & confirmations

Version 2 replaces every v1 permission boolean, dynamic-API gate, and global
confirmation toggle with one policy resolver. Choose a default profile and optional
override for each `MCP — …` token (or add a Music Assistant token ID manually):

| Profile | Behavior |
|---|---|
| `Read-only` | Allows `query:*`; denies everything else. |
| `Home control` | Allows query, control, and edit; confirms delete; denies debug, config, and system. |
| `Interactive admin` | Allows query and control; confirms edit, delete, debug, config, and system. |
| `Trusted` | Allows all capabilities without elicitation. |
| `Custom` | Assigns `Deny`, `Allow`, or `Confirm` to each of the 26 capabilities; unset values deny. |

Per-token overrides use `Inherit`, a named profile, or their own `Custom` matrix.
Overrides are keyed by Music Assistant token ID, so replacing or revoking a token
cannot transfer authority to another bearer. Stored v1 keys are ignored; after
upgrading, configure a v2 default and any token overrides explicitly.

`Confirm` is per call and is never remembered. If a client cannot perform MCP
elicitation, either keep the capability denied or deliberately change only that
capability/token to `Allow`; the server returns an actionable error naming the
capability. Resource reads require `Allow`, so a `Confirm` capability cannot be
bypassed through `library://`, `player://`, or `queue://`.

The optional Prefab MCP App uses the same dispatcher and repeats authentication,
scope, filter, policy, and target checks after every elicitation. A UI click is not a
confirmation. Hosts without MCP Apps support receive a text fallback. Changing
`enable_mcp_app` restarts the runtime because it changes tools and resources.

Authorization is resolved for discovery and repeated immediately before execution
and after elicitation. Music Assistant scopes, disabled users, player/provider
filters, authentication, hard-denied auth/dashboard commands, secret-write guards,
and impersonation confirmation remain authoritative upper bounds. The independent
resource and prompt toggles remain available.

Security audit records cover confirmation outcomes, denials, and privileged
execution outcomes using only fixed fields: MA user, exact token ID or safe client
label, command, capability, effective mode, and controlled outcome. Bearers,
fingerprints, submitted values, command arguments, unmasked secure configuration,
and exception text are never included.

The Connect Wizard shows only the selected default policy profile. It intentionally
does not expose capability counts, mode lists, Custom matrices, or per-token overrides.

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
- **Elicitation** for every request whose effective policy mode is `Confirm`.
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
`MA_SERVER_ROOT` defaults to the neighboring `../ma-server` checkout. A provider
worktree should set it to an explicit compatible MA checkout, for example
`MA_SERVER_ROOT=/absolute/path/to/ma-server`. Compose mounts that checkout at
`/ma-server`, overlays this provider inside it, and refuses startup unless the
imported MA package and `fastmcp_server` provider paths both begin with `/ma-server/`.
The test command cuts conftest discovery at the integration directory, so it does
not load the repository's unit-test fixtures (which import the source-root
`provider` package).
`.superpowers/sdd/2026-07-30-native-ma-command-catalog/run-ma-tests.sh` runs the
implementation suite in the same complete Linux MA virtual environment.

`MA_TEST_PLAYER_ID` is optional, but required for the one reversible queue mutation
test. Choose a dedicated player with an active queue; the test refuses unsafe rows
and removes only the item it adds. The suite is skipped unless both MCP URL and token
are explicitly provided.

### Release synchronization preflight

Before changing `provider/VERSION`, fetch the source and integration branch, require
their provider trees to match, and run the shared transform-aware guard against the
canonical Music Assistant `dev` branch:

```bash
ma_server_root=${MA_SERVER_ROOT:-../ma-server}
provider_tools_root=${MA_PROVIDER_TOOLS_ROOT:-../ma-provider-tools}
git fetch origin dev --tags
git -C "$ma_server_root" fetch origin integration/dev
provider_tree=$(git rev-parse origin/dev:provider)
integration_tree=$(git -C "$ma_server_root" rev-parse \
  origin/integration/dev:music_assistant/providers/fastmcp_server)
test "$provider_tree" = "$integration_tree"
python3 "$provider_tools_root/scripts/check_upstream_ahead.py" \
  --domain fastmcp_server \
  --provider-path provider/ \
  --provider-dir .
```

If the integration comparison fails, wait for or repair its ordinary synchronization.
If the upstream guard fails, reverse-sync the upstream changes before releasing. A
one-time `ack_upstream_ahead=true` dispatch is allowed only after recording which
upstream PRs are already superseded by a reviewed provider PR and re-running their
targeted tests; never use it merely to make the pipeline green. After a stable
release, rebuild `upstream/fastmcp_server` from the current canonical `dev` with the
`upstream-pr` workflow's `reset_branch=true` option, then review the resulting diff.
A release is complete only after the top-level pipeline, both sync jobs, the
published GitHub release, the upstream PR update, and the connected Docker MCP smoke
test succeed.

## License

[MIT](LICENSE)
